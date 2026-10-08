"""Recovery Manager: agent entry point.

Round 2 tri-state fee audit (Vishruth) behind the Round 3 contract. Recovery has no camera: each fee line is a
check whose condition is "this charge is supported by evidence".
    FAIL      = CONTRADICTS  -> claim, cites the upstream record(s)
    PASS      = SUPPORTS     -> no claim
    UNCERTAIN = SILENT       -> never claimed; listed in payload.unclaimable with the reason

Default mode is deterministic rules (no model call, model.name = "rules"). RECOVERY_MODEL_MODE=live adds ONE
batched Gemini call per unit (google-genai) for fee lines no explicit rule covers. A model answer can only turn a
line into a claim if it cites an upstream record that actually exists; any model failure falls back to the rules
and is recorded in payload.model_fallback. Run:  uvicorn agents.recovery.app:app --port 8105
"""
from __future__ import annotations

import json
import os

from shared.utils import sample_data
from shared.utils.records import build_output, build_record, check, utcnow
from shared.utils.server import make_app
from shared.utils.stubs import effective_verdict, previous

STAGE = "recovery"
AGENT_ID = "recovery-vishruth@1"
RULES_MODEL = {"name": "rules", "version": "recovery-rules-2", "provider": None, "calls": 0, "cost_usd": 0.0}
LIVE_MODEL_NAME = os.environ.get("RECOVERY_MODEL", "gemini-2.5-flash")
# Lines on these reports are credits paid to the seller, not charges to dispute.
CREDIT_REPORTS = {"reimbursement_report"}


def _completed(record: dict | None) -> bool:
    return bool(record) and record.get("status") == "completed"


def position(line: dict, request: dict) -> tuple[str | None, str, list[str]]:
    """(CONTRADICTS | SUPPORTS | SILENT | None, reason, upstream record ids). None = no explicit rule covers it."""
    ctype = line["charge_type"]

    if line.get("report_type") in CREDIT_REPORTS or ctype == "damaged_in_warehouse":
        return "SILENT", "reimbursement credit to the seller, not a charge to dispute", []
    if ctype == "fulfilment_fee_weight_tier":
        prep = previous(request, "prep")
        if _completed(prep) and (prep.get("payload") or {}).get("measurements"):
            return ("SILENT", "Prep measured the unit but no fee schedule is looked up to compare the tier (finding F-07)",
                    [prep["record_id"]])
        return "SILENT", "no measured weight/dimensions upstream (finding F-07)", []
    if ctype == "lost_inbound":
        return "SILENT", "receiving shortfall is supplier-side, not channel-side loss (finding F-10)", []

    if ctype == "refund_issued_item_not_returned":
        # D-007 (our assumption on finding F-11): a seller-side Returns record that physically verified the unit
        # and routed it contradicts "item not returned".
        ret = previous(request, "returns")
        if not _completed(ret):
            return "SILENT", "no seller-side return record to contradict the refund (finding F-11)", []
        verdict = effective_verdict(request, ret)
        disposition = ret["decision"].get("outcome", "unknown")
        identity = next((c["verdict"] for c in ret.get("checks", []) if c["check_key"] == "identity_match"), None)
        # A wrong item coming back does not contradict "item not returned": require a verified identity.
        if verdict == "PASS" or (identity == "PASS" and disposition in ("restock", "refurbish", "liquidate")):
            return ("CONTRADICTS", f"Returns record {ret['record_id']} shows the item came back "
                    f"(verdict {verdict}, disposition {disposition}) (finding F-11, D-007)", [ret["record_id"]])
        return "SILENT", f"Returns record {ret['record_id']} is {verdict} / {disposition}: receipt not verified (finding F-11)", [ret["record_id"]]

    if ctype == "inbound_defect_fee":
        for stage in ("prep", "receiving"):
            rec = previous(request, stage)
            if not _completed(rec):
                continue
            verdict = effective_verdict(request, rec)
            if verdict == "PASS":
                return "CONTRADICTS", f"{stage.title()} evidence {rec['record_id']} shows the unit compliant", [rec["record_id"]]
            if verdict == "FAIL":
                return "SUPPORTS", f"{stage.title()} evidence {rec['record_id']} confirms a defect", [rec["record_id"]]
            return "SILENT", f"{stage.title()} evidence {rec['record_id']} is uncertain", [rec["record_id"]]
        return "SILENT", "no Prep or Receiving evidence for this unit (Specialist Pods: no Prep)", []

    return None, "", []


def _live_audit(lines: list[dict], request: dict) -> tuple[dict[str, tuple[str, str, list[str]]], dict]:
    """One batched Gemini call for every line no rule covers. Returns ({line_id: position}, model meta)."""
    from google import genai
    from google.genai import types

    upstream = {r["record_id"]: {"stage": r["stage"], "verdict": effective_verdict(request, r),
                                 "outcome": r["decision"].get("outcome"), "reason": r["decision"].get("reason")}
                for r in request.get("previous_evidence", []) if r.get("status") == "completed"}
    prompt = (
        "You audit marketplace fee lines against warehouse evidence records. For EACH line answer with one of "
        "CONTRADICTS (the evidence shows the charge is wrong), SUPPORTS (the evidence confirms it) or SILENT (the "
        "evidence does not speak to it). Only cite record_ids from EVIDENCE. If unsure, answer SILENT.\n"
        'Reply as JSON: {"lines": [{"line_id": str, "position": str, "reason": str, "record_ids": [str]}]}\n'
        f"FEE LINES: {json.dumps(lines)}\nEVIDENCE: {json.dumps(upstream)}")
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    resp = client.models.generate_content(model=LIVE_MODEL_NAME, contents=prompt,
                                          config=types.GenerateContentConfig(response_mime_type="application/json"))
    out: dict[str, tuple[str, str, list[str]]] = {}
    for item in json.loads(resp.text or "{}").get("lines", []):
        ids = [i for i in item.get("record_ids", []) if i in upstream]
        pos = item.get("position", "SILENT")
        if pos not in ("CONTRADICTS", "SUPPORTS", "SILENT") or (pos == "CONTRADICTS" and not ids):
            pos = "SILENT"  # a claim must cite real upstream evidence
        out[item.get("line_id", "")] = (pos, f"model: {item.get('reason', '')}", ids)
    meta = {"name": LIVE_MODEL_NAME, "version": LIVE_MODEL_NAME, "provider": "google", "prompt_version": "recovery-v2",
            "calls": 1, "cost_usd": None}
    return out, meta


def handle(request: dict) -> dict:
    s = request["subject"]
    if not sample_data.has("receiving", s["subject_id"], s["org_id"]):  # tenancy: never answer for another org
        raise LookupError(f"unknown subject {s['subject_id']} in {s['org_id']}")

    lines = sample_data.fee_lines(s["subject_id"], s["org_id"])
    decided = {line["line_id"]: position(line, request) for line in lines}
    open_lines = [line for line in lines if decided[line["line_id"]][0] is None]

    model, fallback = RULES_MODEL, None
    if open_lines and os.environ.get("RECOVERY_MODEL_MODE") == "live" and os.environ.get("GEMINI_API_KEY"):
        try:
            answers, model = _live_audit(open_lines, request)
            decided.update({lid: answers[lid] for lid in answers if lid in decided})
        except Exception as exc:  # fail open to the rules, and say so
            fallback = f"{type(exc).__name__}: {str(exc)[:200]}"
    for lid, (pos, _, _) in list(decided.items()):
        if pos is None:
            decided[lid] = ("SILENT", "no rule maps this charge type to upstream evidence", [])

    checks, charges, claimable = [], [], 0.0
    for line in lines:
        pos, why, ids = decided[line["line_id"]]
        amount = float(line["amount_usd"])
        if pos == "CONTRADICTS" and amount <= 0:
            pos, why = "SILENT", f"{why}; but amount is 0.00: nothing to claim, or the amount is missing (finding F-09)"
        verdict = {"CONTRADICTS": "FAIL", "SUPPORTS": "PASS", "SILENT": "UNCERTAIN"}[pos]
        checks.append(check(f"charge_{line['line_id'].lower().replace('-', '_')}", verdict, None,
                            expected="charge supported by evidence", observed=pos, detail=why,
                            evidence_refs=ids, uncertain_reason="insufficient_evidence"))
        if pos == "CONTRADICTS":
            claimable += amount
        charges.append({"line_id": line["line_id"], "charge_type": line["charge_type"], "amount_usd": amount,
                        "position": pos, "reason": why, "evidence_record_ids": ids})

    n_claim = sum(c["position"] == "CONTRADICTS" for c in charges)
    silent = any(c["position"] == "SILENT" for c in charges)
    verdict = "FAIL" if n_claim else ("UNCERTAIN" if silent else "PASS")
    outcome = "claim_recommended" if n_claim else ("insufficient_evidence" if silent else "no_claim")
    payload = {"charges": charges, "claimable_usd": round(claimable, 2),
               "unclaimable": [c for c in charges if c["position"] != "CONTRADICTS"]}
    if fallback:
        payload["model_fallback"] = fallback
    # Same request in, same record_id out; a re-run (request_id ends ":rN") is a new record, never an overwrite.
    rerun = request["request_id"].rsplit(":", 1)[-1]
    record_id = f"RCY-{s['subject_id']}" + (f"-{rerun}" if rerun.startswith("r") and rerun[1:].isdigit() else "")
    record = build_record(
        request, agent_id=AGENT_ID, record_id=record_id, model=model,
        captured_at=max((line["posted_date"] + "T00:00:00Z" for line in lines), default=utcnow()),
        refs={"sku": lines[0]["sku"], "fnsku": lines[0]["fnsku"]} if lines else None,
        checks=checks, outcome=outcome, verdict=verdict,
        needs_human=False,  # SILENT has nothing for a person to decide; claims are reviewed via the final outcome
        reason=f"{len(charges)} charge(s) audited by {model['name']}: {n_claim} contradicted, "
               f"{sum(c['position'] == 'SILENT' for c in charges)} silent",
        payload=payload,
    )
    return build_output(record, next_step="complete")


app = make_app(STAGE, handle)
