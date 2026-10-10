"""Starter orchestrator: a small workflow engine that owns workflow state.

Model:  Agent Output -> Evidence Record (stored, immutable) -> state transition -> next stage -> ... -> Final Outcome.
The orchestrator is the authoritative owner of workflow state. Agents return evidence; they never write state.

What it does for you (keep or replace, but keep the behaviour; it is tested):
  * start_workflow / advance / resume / apply_override
  * routes stages from a JSON flow (`when`), passes ALL previous evidence and overrides to each agent
  * validates every agent output (schema, stage, workflow, tenant, hash, consistency) before accepting it
  * retries transient failures, never retries refusals; every failure is RECORDED, never hidden or turned into success
  * fails open: a broken agent becomes a pending/error evidence record and the workflow continues (or blocks, by policy)
  * keeps an audit trail (`transitions`) and derives status + final outcome from the evidence (rollup.py)
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path

from shared.utils.hashing import verify
from shared.utils.log import get_logger
from shared.utils.records import error_obj, pending_output, utcnow
from shared.utils.schema import errors as schema_errors

from .clients import AgentRejected, AgentTimeout, AgentUnavailable, client_for, load_manifest
from .rollup import derive_final_outcome, derive_status, effective
from .store import EvidenceConflict, MemoryStore, TenantConflict

ROOT = Path(__file__).resolve().parents[1]
logger = get_logger("orchestrator")
VERDICTS = ("PASS", "FAIL", "UNCERTAIN")
# Receiving quality flags that mean the ordered product itself did not arrive (not damage or a count): the model
# names them freely, e.g. wrong_item, no_product_visible, unrelated_image, empty_carton.
NOT_THE_PRODUCT = re.compile(r"wrong.?(item|product|sku|model)|no.?(product|item|unit)|(product|item|unit)s?.?not.?(visible|present)|"
                             r"empty|missing.?(item|product|unit)|unrelated|irrelevant|non.?product|different.?(item|product)|"
                             r"product.?mismatch|swap|substitut", re.IGNORECASE)
KINDS = {".jpg": "image", ".jpeg": "image", ".png": "image", ".webp": "image", ".heic": "image",
         ".mp4": "video", ".mov": "video", ".pdf": "document", ".csv": "document", ".json": "document", ".txt": "document"}


# ---------------------------------------------------------------- flow
def default_flow_path() -> Path:
    """The flow named in pod.json (Specialist Pods run flow.specialist.json), else flow.json."""
    pod = ROOT / "pod.json"
    rel = json.loads(pod.read_text()).get("flow") if pod.exists() else None
    return ROOT / (rel or "orchestration/flow.json")


def load_flow(path: str | Path | None = None) -> dict:
    return json.loads(Path(path or default_flow_path()).read_text())


def flow_stages(flow: dict | None = None) -> list[str]:
    return list(dict.fromkeys(s["stage"] for s in (flow or load_flow())["steps"]))


def applies(step: dict, case: dict) -> tuple[bool, str]:
    for key, allowed in step.get("when", {}).items():
        if case.get(key) not in allowed:
            return False, f"{key}={case.get(key)!r} not in {allowed}"
    return True, ""


def discover_inputs(subject_id: str, stage: str) -> list[dict]:
    """Captures for one stage live in data/input/<subject_id>/<stage>/ (override the root with INPUT_DIR).

    Each file becomes a content-addressed input {ref, kind, sha256}. Refs are relative to the input root:
    never absolute (no local paths in evidence).
    """
    root = Path(os.environ.get("INPUT_DIR", ROOT / "data" / "input"))
    folder = root / subject_id / stage
    if not folder.is_dir():
        return []
    return [{"ref": p.relative_to(root).as_posix(), "kind": KINDS.get(p.suffix.lower(), "other"),
             "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
            for p in sorted(folder.iterdir()) if p.is_file() and not p.name.startswith(".")]


# ---------------------------------------------------------------- workflow state
def workflow_id_for(case: dict) -> str:
    return f"WF-{case['org_id']}-{case.get('subject_id') or case['unit_id']}"


def _log(wf: dict, event: str, stage: str | None = None, detail: str | None = None, **extra) -> None:
    wf["transitions"].append({"at": utcnow(), "event": event, "stage": stage, "detail": detail, **extra})
    logger.info(event, extra={"ctx": {"workflow_id": wf["workflow_id"], "org_id": wf["org_id"],
                                     "subject_id": wf["subject_id"], "stage": stage, "detail": detail}})


def _set_status(wf: dict, status: str, reason: str) -> None:
    if wf["status"] != status:
        _log(wf, "status_changed", detail=reason, from_status=wf["status"], to_status=status)
    wf["status"], wf["status_reason"] = status, reason
    wf["timestamps"]["updated_at"] = utcnow()


def new_workflow(case: dict, flow: dict) -> dict:
    """A PENDING workflow with every stage listed and routing already decided."""
    now = utcnow()
    subject_id = case.get("subject_id") or case["unit_id"]
    no_input = set(case.get("skip_stages") or [])  # stages the dataset has no input for (sample_data.case_for)
    stage_results = []
    for step in flow["steps"]:
        ok, why = applies(step, case)
        if ok and step["stage"] in no_input:
            ok, why = False, (case.get("skip_reasons") or {}).get(step["stage"]) or f"no {step['stage']} input in the dataset"
        try:
            agent_id = load_manifest(step["stage"])["agent_id"]
        except FileNotFoundError:
            agent_id = None
        stage_results.append({
            "stage": step["stage"], "agent_id": agent_id, "state": "pending" if ok else "skipped",
            "skipped_reason": None if ok else why, "record_id": None, "evidence_status": None, "verdict": None,
            "outcome": None, "needs_human": None, "next_step_recommendation": None, "runs": 0, "attempts": 0,
            "started_at": None, "finished_at": None, "duration_ms": None, "error": None})
    wf = {"schema_version": "1.0", "workflow_id": workflow_id_for(case), "flow_id": flow["flow_id"],
          "org_id": case["org_id"], "subject_id": subject_id,
          "context": {k: v for k, v in case.items() if k not in ("org_id", "unit_id", "subject_id")},
          "status": "PENDING", "status_reason": "created", "current_stage": None, "previous_stage": None,
          "stage_results": stage_results, "evidence_references": [],
          "timestamps": {"created_at": now, "updated_at": now, "completed_at": None},
          "errors": [], "overrides": [], "halted": None, "final_outcome": None, "transitions": []}
    _log(wf, "workflow_created", detail=f"flow={flow['flow_id']}")
    for sr in stage_results:
        if sr["state"] == "skipped":
            _log(wf, "stage_skipped", sr["stage"], sr["skipped_reason"])
    return wf


def _previous_evidence(wf: dict, upto: int, store) -> list[dict]:
    out = []
    for sr in wf["stage_results"][:upto]:
        if sr["record_id"] and (rec := store.get_evidence(sr["record_id"], wf["org_id"])):
            out.append(rec)
    return out


def _validate(out: dict, wf: dict, stage: str) -> list[str]:
    """Why an agent output is not acceptable (empty list = accept)."""
    bad = schema_errors("agent-output", out)
    if bad:
        return bad[:3]
    ev = out["evidence"]
    if out["stage"] != stage or ev["stage"] != stage:
        return [f"stage mismatch: expected {stage!r}, got {out['stage']!r}/{ev['stage']!r}"]
    if out["workflow_id"] != wf["workflow_id"] or ev["workflow_id"] != wf["workflow_id"]:
        return ["workflow_id mismatch"]
    if (ev["subject"]["org_id"], ev["subject"]["subject_id"]) != (wf["org_id"], wf["subject_id"]):
        return ["TENANCY/SUBJECT MISMATCH: evidence is about a different org or subject than this workflow"]
    if not verify(ev):
        return ["content_hash does not match the evidence body"]
    if (out["verdict"], out["status"], out["agent_id"]) != (ev["decision"]["verdict"], ev["status"], ev["agent_id"]):
        return ["output and evidence disagree (verdict/status/agent_id)"]
    return []


def _run_stage(wf: dict, sr: dict, idx: int, opts: dict, store, client) -> dict | None:
    """Run one stage. Returns a halt reason, or None. Always leaves a stored evidence record behind."""
    stage = sr["stage"]
    sr["runs"] += 1
    sr["attempts"], sr["started_at"], sr["error"] = 0, utcnow(), None
    wf["previous_stage"], wf["current_stage"] = wf["current_stage"], stage
    base = f"{wf['workflow_id']}:{stage}"
    request = {
        "schema_version": "1.0", "request_id": base if sr["runs"] == 1 else f"{base}:r{sr['runs']}",
        "workflow_id": wf["workflow_id"], "stage": stage,
        "subject": {"org_id": wf["org_id"], "subject_id": wf["subject_id"], "route": wf["context"].get("route", "unknown")},
        "inputs": discover_inputs(wf["subject_id"], stage),
        "previous_evidence": _previous_evidence(wf, idx, store),
        "context": {"overrides": wf["overrides"], "case": wf["context"]},
    }
    t0, out, err = time.monotonic(), None, None
    while sr["attempts"] <= int(opts["retries"]):
        sr["attempts"] += 1
        try:
            out = client.run(request, float(opts["timeout_s"]))
            err = None
            break
        except AgentTimeout as exc:
            err = error_obj("agent_timeout", str(exc), retryable=True, stage=stage)
        except AgentUnavailable as exc:
            err = error_obj("agent_unavailable", str(exc), retryable=True, stage=stage)
        except AgentRejected as exc:
            err = error_obj("agent_rejected", str(exc), retryable=False, stage=stage)
            break
        except Exception as exc:  # an agent bug must not take the orchestrator down
            err = error_obj("agent_exception", f"{type(exc).__name__}: {exc}", retryable=False, stage=stage)
            break
        if sr["attempts"] <= int(opts["retries"]):
            _log(wf, "retry", stage, err["message"])
    if out is not None:
        bad = _validate(out, wf, stage)
        if bad:
            code = "tenant_mismatch" if bad[0].startswith("TENANCY") else "invalid_output"
            err, out = error_obj(code, "; ".join(bad), retryable=False, stage=stage), None
            _log(wf, "invalid_output", stage, err["message"])
    if out is None:
        out = pending_output(request, code=err["code"], message=err["message"], retryable=err["retryable"],
                             agent_id=sr["agent_id"])
        _log(wf, "stage_degraded", stage, f"{err['code']}: recorded as {out['evidence']['status']}; flow policy decides what next")

    ev = out["evidence"]
    try:
        store.put_evidence(ev)
    except EvidenceConflict as exc:  # an agent reused a record_id for different content: reject, never overwrite
        code = "tenant_mismatch" if isinstance(exc, TenantConflict) else "invalid_output"
        err = error_obj(code, str(exc), retryable=False, stage=stage)
        _log(wf, "invalid_output", stage, err["message"])
        out = pending_output(request, code=err["code"], message=err["message"], retryable=False, agent_id=sr["agent_id"])
        ev = out["evidence"]
        store.put_evidence(ev)
    if ev["record_id"] not in wf["evidence_references"]:
        wf["evidence_references"].append(ev["record_id"])
    agent_err = ev.get("error") or err
    if agent_err:
        wf["errors"].append({**agent_err, "stage": stage, "agent_id": ev["agent_id"], "at": agent_err.get("at") or utcnow()})
    sr.update({
        "agent_id": ev["agent_id"], "record_id": ev["record_id"], "evidence_status": ev["status"],
        "verdict": ev["decision"]["verdict"], "outcome": ev["decision"]["outcome"],
        "needs_human": ev["decision"].get("needs_human"), "next_step_recommendation": out.get("next_step_recommendation"),
        "state": "completed" if ev["status"] == "completed" else "error", "error": agent_err,
        "finished_at": utcnow(), "duration_ms": int((time.monotonic() - t0) * 1000)})
    _log(wf, "stage_completed" if sr["state"] == "completed" else "stage_error", stage,
         f"{ev['decision']['outcome']} / {ev['decision']['verdict']}")
    if sr["state"] == "error" and opts["on_error"] == "block":
        return f"stage {stage} failed and on_error=block"
    # Block only when an UNCERTAIN result actually asks for a person. Recovery's SILENT ("no evidence, so no claim")
    # is UNCERTAIN with needs_human=false: there is nothing for a human to decide, so it must not halt the workflow.
    if ev["decision"]["verdict"] == "UNCERTAIN" and ev["decision"].get("needs_human") and opts["on_uncertain"] == "block":
        return f"stage {stage} is UNCERTAIN, needs a person, and on_uncertain=block"
    return None


def _finalize(wf: dict, store) -> dict:
    evidence = {rid: store.get_evidence(rid, wf["org_id"]) for rid in wf["evidence_references"]}
    status, reason = derive_status(wf, evidence)
    _set_status(wf, status, reason)
    wf["final_outcome"] = derive_final_outcome(wf, evidence, status)
    wf["timestamps"]["completed_at"] = utcnow() if status == "COMPLETED" else None
    store.save_workflow(wf)
    return wf


def _stale_reason(wf: dict, idx: int, store) -> str | None:
    """Why a completed stage's judgment no longer reflects its upstream evidence (None = still current).

    It is stale when an earlier stage has since produced a different record (e.g. a failed stage was resumed), or
    when an override on an earlier record was made at or after this stage finished (it judged the old verdict).
    """
    sr = wf["stage_results"][idx]
    rec = store.get_evidence(sr["record_id"], wf["org_id"]) if sr.get("record_id") else None
    if rec is None:
        return None
    current = [s["record_id"] for s in wf["stage_results"][:idx] if s.get("record_id")]
    if set(rec["upstream_refs"]) != set(current):
        return f"upstream evidence changed since it ran ({sorted(set(current) - set(rec['upstream_refs']))} new)"
    later = [o["override_id"] for o in wf["overrides"]
             if o["supersedes"]["record_id"] in current and o["at"] >= (sr["finished_at"] or "")]
    if later:
        return f"upstream override(s) {later} were made after it ran"
    return None


def _step_opts(flow: dict, stage: str) -> dict:
    defaults = {"timeout_s": 30, "retries": 1, "on_uncertain": "continue", "on_error": "continue",
                "rerun_when_upstream_changes": False, **flow.get("defaults", {})}
    step = next(s for s in flow["steps"] if s["stage"] == stage)
    return {**defaults, **{k: v for k, v in step.items() if k not in ("stage", "when")}}


def _alnum(text) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(text or "").upper())


def product_unconfirmed(wf: dict, store) -> str | None:
    """Why Receiving's (effective) FAIL says the ordered product did not arrive; None when it did or nobody checked.

    Only the product itself counts: a wrong, missing or unseen item makes every later check judge the wrong thing.
    A damage or carton-count FAIL does not stop the flow (Recovery still needs it). Receiving's identity check
    compares the text it read with the SKU code letter for letter, so reading "MDR-V6" on the right box is a FAIL
    there; here that only counts when the text is not part of the ordered SKU or product name. A person's override
    of the record decides.
    """
    sr = next((s for s in wf["stage_results"] if s["stage"] == "receiving" and s.get("record_id")), None)
    rec = store.get_evidence(sr["record_id"], wf["org_id"]) if sr else None
    if rec is None or effective(wf, rec)[0] != "FAIL":
        return None
    checks = {c.get("check_key"): c for c in rec.get("checks") or []}
    ident, qty = checks.get("identity_match", {}), checks.get("quantity", {})
    seen = _alnum(ident.get("observed"))
    if ident.get("verdict") == "FAIL" and len(seen) >= 3 and seen not in _alnum(ident.get("expected")):
        return f"Receiving read {ident.get('observed')!r}, not {ident.get('expected')}"
    if qty.get("verdict") == "FAIL" and qty.get("observed") == 0:
        return "Receiving counted no unit of the ordered product"
    flags = checks.get("quality_flags", {})
    if flags.get("verdict") == "FAIL":
        observed = flags.get("observed")
        hits = [str(f) for f in (observed if isinstance(observed, list) else [observed]) if NOT_THE_PRODUCT.search(str(f))]
        if hits:
            return f"Receiving flagged {', '.join(hits)}"
    unit = ("identity_match", "quantity", "unit_damage")
    if all(k in checks for k in unit) and not any(checks[k].get("verdict") == "PASS" for k in unit):
        return "Receiving could not see the ordered product in its photos (identity, count and condition unconfirmed)"
    return None


# ---------------------------------------------------------------- public API
def advance(wf: dict, flow: dict, store, clients: dict | None = None) -> dict:
    """Run every stage that has not completed (errored stages are retried), in order, until done or halted.

    A completed stage whose flow step sets `rerun_when_upstream_changes` is run again (new record; the old one stays
    in evidence_references) when its upstream evidence or an upstream override changed after it ran.
    """
    wf["halted"] = None
    _set_status(wf, "IN_PROGRESS", "advancing")
    store.save_workflow(wf)
    for idx, sr in enumerate(wf["stage_results"]):
        opts = _step_opts(flow, sr["stage"])
        if sr["state"] == "completed" and opts["rerun_when_upstream_changes"]:
            why = _stale_reason(wf, idx, store)
            if why:
                sr["state"] = "pending"
                _log(wf, "stage_stale", sr["stage"], f"{sr['record_id']} re-run: {why}")
        if sr["state"] in ("completed", "skipped"):
            continue
        why = product_unconfirmed(wf, store) if opts.get("needs_confirmed_product") else None
        if why:
            reason = (f"{why}; {sr['stage']} would judge a product that is not confirmed. A person must decide "
                      f"(override the Receiving record, then resume)")
            wf["halted"] = {"stage": sr["stage"], "reason": reason, "at": utcnow()}
            _log(wf, "halted", sr["stage"], reason)
            break
        client = (clients or {}).get(sr["stage"]) or client_for(sr["stage"])
        halt = _run_stage(wf, sr, idx, opts, store, client)
        store.save_workflow(wf)
        if halt:
            wf["halted"] = {"stage": sr["stage"], "reason": halt, "at": utcnow()}
            _log(wf, "halted", sr["stage"], halt)
            break
    return _finalize(wf, store)


def run_workflow(case: dict, flow: dict | None = None, store=None, clients: dict | None = None) -> dict:
    """Start (or continue) the workflow for a case. Idempotent: an existing workflow is advanced, not duplicated."""
    flow, store = flow or load_flow(), store or MemoryStore()
    wf = store.load_workflow(workflow_id_for(case), case["org_id"]) or new_workflow(case, flow)
    return advance(wf, flow, store, clients)


def resume(workflow_id: str, flow: dict | None = None, store=None, clients: dict | None = None) -> dict:
    """Continue after a halt, a person's decision, or a failure (errored stages are retried)."""
    flow = flow or load_flow()
    wf = store.load_workflow(workflow_id)
    if wf is None:
        raise KeyError(workflow_id)
    _log(wf, "resumed", detail=f"from status {wf['status']}")
    return advance(wf, flow, store, clients)


def apply_override(workflow_id: str, store, *, record_id: str, new_verdict: str, actor: str, reason: str,
                   new_outcome: str | None = None) -> dict:
    """A person (or rule) changes the effective decision of a record. Nothing is deleted or rewritten:
    the new entry references the evidence and the previous effective decision, and the state is re-derived."""
    if not actor.strip() or not reason.strip():
        raise ValueError("an override needs an actor and a reason")
    if new_verdict not in VERDICTS:
        raise ValueError(f"new_verdict must be one of {', '.join(VERDICTS)}, got {new_verdict!r}")
    wf = store.load_workflow(workflow_id)
    if wf is None:
        raise KeyError(workflow_id)
    if record_id not in wf["evidence_references"]:
        raise ValueError(f"{record_id} is not evidence in {workflow_id}")
    record = store.get_evidence(record_id, wf["org_id"])
    if record is None:
        raise ValueError(f"{record_id} is not evidence of {wf['org_id']}")
    previous_verdict, _ = effective(wf, record)
    earlier = [o for o in wf["overrides"] if o["supersedes"]["record_id"] == record_id]
    entry = {"override_id": f"OVR-{len(wf['overrides']) + 1:03d}",
             "supersedes": {"record_id": record_id, "override_id": earlier[-1]["override_id"] if earlier else None},
             "target": "decision", "actor": actor, "at": utcnow(), "reason": reason,
             "original_verdict": record["decision"]["verdict"], "previous_verdict": previous_verdict,
             "new_verdict": new_verdict, "new_outcome": new_outcome}
    wf["overrides"].append(entry)
    _log(wf, "override", record["stage"], f"{entry['override_id']} by {actor}: {previous_verdict} -> {new_verdict}")
    stages = [s["stage"] for s in wf["stage_results"]]
    after = [s["stage"] for s in wf["stage_results"][stages.index(record["stage"]) + 1:] if s["state"] == "completed"]
    if after:  # they judged the old verdict; resume re-runs the ones the flow marks rerun_when_upstream_changes
        _log(wf, "downstream_judged_before_override", record["stage"], f"{', '.join(after)} ran before {entry['override_id']}; resume to re-evaluate")
    return _finalize(wf, store)


def bundle(wf: dict, store) -> dict:
    """The workflow plus every evidence record it references: a self-contained, reviewable export."""
    return {"workflow": wf, "evidence": {rid: store.get_evidence(rid, wf["org_id"]) for rid in wf["evidence_references"]}}
