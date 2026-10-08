"""Derive a workflow's STATUS and FINAL OUTCOME from its evidence chain and overrides. Pure functions, no I/O.

The authoritative state is the orchestrator's state *derived from the traceable evidence*: the latest agent outcome
alone is not the source of truth, and neither is Recovery's reading of it. See ORCHESTRATION-GUIDE.md.

STATUS (precedence, highest first):
  PENDING            nothing has run yet
  FAILED             a required stage ended in error / pending after the retry policy (re-run with resume)
  RECOVERY_REQUIRED  a stage's verdict is FAIL and the Recovery stage has not completed (something may be recoverable)
  BLOCKED            a person must decide (needs_human), or policy halted the workflow; resumes after an override/resume
  IN_PROGRESS        some required stages have not run yet
  COMPLETED          every required stage finished and nothing awaits a person

FINAL OUTCOME (precedence, highest first):
  CLAIM_RECOMMENDED  Recovery's effective verdict is FAIL (a charge is contradicted by evidence)
  EXCEPTION          any stage's effective verdict is FAIL (a real-world problem, no claim)
  INCOMPLETE         a required stage did not complete
  NEEDS_REVIEW       a stage asks for a person
  CLEAN              every required stage passed
UNCERTAIN is never turned into PASS. This is the DEFAULT policy: improve it and document why (docs/decisions.md).
"""
from __future__ import annotations

from shared.utils.records import utcnow


def effective(workflow: dict, record: dict) -> tuple[str, bool]:
    """(verdict, needs_human) for a record after applying workflow-level overrides. The latest override wins."""
    mine = [o for o in workflow["overrides"] if o["supersedes"]["record_id"] == record["record_id"]]
    if mine:
        v = mine[-1]["new_verdict"]
        return v, v == "UNCERTAIN"
    return record["decision"]["verdict"], bool(record["decision"].get("needs_human"))


def _latest(workflow: dict, evidence: dict) -> list[tuple[dict, dict]]:
    """[(stage_result, record)] for stages that produced a record."""
    return [(sr, evidence[sr["record_id"]]) for sr in workflow["stage_results"]
            if sr.get("record_id") and sr["record_id"] in evidence]


def derive_status(workflow: dict, evidence: dict) -> tuple[str, str]:
    srs = [sr for sr in workflow["stage_results"] if sr["state"] != "skipped"]
    if not any(sr["runs"] for sr in workflow["stage_results"]):
        return "PENDING", "no stage has run"
    failed = [sr["stage"] for sr in srs if sr["state"] == "error"]
    if failed:
        return "FAILED", f"stage did not complete: {', '.join(failed)}"
    pairs = [(sr, rec) for sr, rec in _latest(workflow, evidence) if sr["state"] != "skipped"]
    eff = {sr["stage"]: effective(workflow, rec) for sr, rec in pairs}
    has_recovery = any(sr["stage"] == "recovery" for sr in srs)
    recovery_done = any(sr["stage"] == "recovery" and sr["state"] == "completed" for sr in srs)
    fails = [stage for stage, (v, _) in eff.items() if v == "FAIL" and stage != "recovery"]
    if fails and has_recovery and not recovery_done:
        return "RECOVERY_REQUIRED", f"FAIL from {', '.join(fails)}; Recovery has not run"
    asks = [stage for stage, (_, h) in eff.items() if h]
    if workflow.get("halted"):
        return "BLOCKED", f"halted at {workflow['halted']['stage']}: {workflow['halted']['reason']}"
    if asks:
        return "BLOCKED", f"a person must decide: {', '.join(asks)}"
    if any(sr["state"] == "pending" for sr in srs):
        return "IN_PROGRESS", "stages remain"
    return "COMPLETED", "all required stages finished"


def derive_final_outcome(workflow: dict, evidence: dict, status: str) -> dict | None:
    if status == "PENDING":
        return None
    srs = [sr for sr in workflow["stage_results"] if sr["state"] != "skipped"]
    pairs = [(sr, rec) for sr, rec in _latest(workflow, evidence) if sr["state"] != "skipped"]
    eff = {sr["stage"]: effective(workflow, rec) for sr, rec in pairs}
    incomplete = [sr["stage"] for sr in srs if sr["state"] in ("error", "pending")]
    asks = [s for s, (_, h) in eff.items() if h]
    failed = [s for s, (v, _) in eff.items() if v == "FAIL" and s != "recovery"]
    rec_pair = next(((sr, rec) for sr, rec in pairs if sr["stage"] == "recovery" and sr["state"] == "completed"), None)
    rec_claim = bool(rec_pair) and eff["recovery"][0] == "FAIL"
    claimable = rec_pair[1]["payload"].get("claimable_usd") if rec_pair else None
    needs_human = bool(incomplete or asks)

    if rec_claim:
        outcome, verdict = "CLAIM_RECOMMENDED", "FAIL"
        reason = f"Recovery contradicted at least one charge (claimable ${claimable or 0:.2f})."
    elif failed:
        outcome, verdict = "EXCEPTION", "FAIL"
        reason = f"Failed verdict from: {', '.join(failed)}; no claim recommended."
    elif incomplete:
        outcome, verdict = "INCOMPLETE", "UNCERTAIN"
        reason = f"Stage did not complete: {', '.join(incomplete)}."
    elif asks:
        outcome, verdict = "NEEDS_REVIEW", "UNCERTAIN"
        reason = f"Human review requested by: {', '.join(asks)}."
    else:
        outcome, verdict = "CLEAN", "PASS"
        reason = "All applicable stages passed."
    if needs_human and outcome in ("CLAIM_RECOMMENDED", "EXCEPTION"):
        # A failed stage's fail-open record also asks for a person: list each stage once.
        reason += f" Flagged for review: {', '.join(dict.fromkeys(incomplete + asks))}."
    return {
        "workflow_id": workflow["workflow_id"], "outcome": outcome, "verdict": verdict, "reason": reason,
        "needs_human": needs_human, "provisional": status != "COMPLETED",
        "claimable_usd": claimable if outcome == "CLAIM_RECOMMENDED" else None,
        "contributing_records": [rec["record_id"] for _, rec in pairs],
        "effective_verdicts": {s: v for s, (v, _) in eff.items()},
        "decided_by": "orchestrator", "decided_at": utcnow(),
    }
