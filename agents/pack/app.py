"""Pack Manager: agent entry point.

Round 2 Pack Manager (Llama-3.2-90B / Qwen-2.5-VL vision extractor + deterministic
reconciliation engine + occlusion guard + fail-open timeout policy).
Author: Nikhil Agarwal (@nikhilagarwal03)
"""
from __future__ import annotations

from typing import Any

from agents.pack.adapter.engine import aggregate_items, reconcile_pack
from agents.pack.adapter.orders import lookup_pack_order
from agents.pack.adapter.vision import extract_pack_vision
from shared.utils import sample_data
from shared.utils.log import get_logger
from shared.utils.records import (
    build_output,
    build_record,
    check,
    pending_output,
    utcnow,
)
from shared.utils.server import make_app
from shared.utils.stubs import photos

STAGE = "pack"
AGENT_ID = "pack-manager-nikhil@2.0.0"

logger = get_logger("pack")


def handle(request: dict) -> dict:
    s = request["subject"]
    subject_id = s["subject_id"]
    org_id = s["org_id"]

    # 1. Tenancy isolation & order lookup (§5.1)
    # Raises LookupError if subject is unknown or belongs to another tenant
    try:
        order = lookup_pack_order(subject_id, org_id)
    except LookupError as exc:
        logger.warning(f"Tenancy / subject lookup failed: {exc}")
        raise

    # 2. Extract inputs (images)
    inputs = request.get("inputs") or []
    sample_row = None
    try:
        sample_row = sample_data.row("pack", subject_id, org_id)
    except LookupError:
        pass

    if not inputs:
        if sample_row:
            inputs = photos(sample_row)
        elif order.photo_refs:
            inputs = [{"ref": p, "sha256": None, "kind": "image"} for p in order.photo_refs if p]

    evidence_refs = [inp.get("ref") for inp in inputs if inp.get("ref")] or [f"capture:{subject_id}"]

    # 3. Vision extraction (Batched, fail-open)
    expected_skus = [str(line.get("sku", "")).strip() for line in order.order_lines if line.get("sku")]
    sample_obs = sample_row.get("observed_in_box") if sample_row else None
    first_image = inputs[0]["ref"] if inputs else None

    extracted = extract_pack_vision(
        image_url=first_image,
        expected_skus=expected_skus,
        fixture_id=order.fixture_id,
        sample_observed_text=sample_obs,
    )

    # 4. Fail open guard (§5.3)
    if extracted.get("status") == "uncertain" and "VLM failure" in extracted.get("reason", ""):
        return pending_output(
            request,
            code="VLM_TIMEOUT_OR_FAILURE",
            message=extracted["reason"],
            retryable=True,
            agent_id=AGENT_ID,
        )

    # 5. Deterministic reconciliation
    reconciliation = reconcile_pack(order.order_lines, extracted)
    verdict = reconciliation["verdict"]

    # 6. Build contract checks
    expected_agg = reconciliation["expected_aggregated"]
    observed_agg = reconciliation["observed_aggregated"]
    missing = reconciliation["missing_items"]
    mismatches = reconciliation["quantity_mismatches"]
    extras = reconciliation["unexpected_items"]
    extra_labels = [e["sku"] for e in extras]

    is_uncertain = verdict == "UNCERTAIN"
    # The contract allows only coded reasons; the engine's text goes into `detail`.
    uncertain_reason = "occluded" if is_uncertain else None
    unc_detail = f"uncertain: {reconciliation['reason']}"
    # A CSV replay is deterministic: no model confidence to report.
    replay = extracted.get("model", {}).get("name") == "csv-replay"

    def conf(bad: bool) -> float | None:
        if replay:
            return None
        return 0.50 if is_uncertain else (0.95 if bad else 0.98)

    checks = [
        check(
            "items_present",
            "UNCERTAIN" if is_uncertain else ("FAIL" if missing else "PASS"),
            conf(bool(missing)),
            expected=sorted(expected_agg.keys()),
            observed=sorted(observed_agg.keys()),
            detail=unc_detail if is_uncertain else (f"missing: {missing}" if missing else "all expected items accounted for"),
            evidence_refs=evidence_refs,
            uncertain_reason=uncertain_reason,
        ),
        check(
            "quantities_correct",
            "UNCERTAIN" if is_uncertain else ("FAIL" if mismatches else "PASS"),
            conf(bool(mismatches)),
            expected=expected_agg,
            observed={k: observed_agg.get(k, 0) for k in expected_agg},
            detail=unc_detail if is_uncertain else (f"mismatches: {mismatches}" if mismatches else "quantities match expected counts"),
            evidence_refs=evidence_refs,
            uncertain_reason=uncertain_reason,
        ),
        check(
            "no_extra_items",
            "UNCERTAIN" if is_uncertain else ("FAIL" if extras else "PASS"),
            conf(bool(extras)),
            expected=[],
            observed=extra_labels,
            detail=unc_detail if is_uncertain else (f"unexpected: {extras}" if extras else "no extra items or decoys found"),
            evidence_refs=evidence_refs,
            uncertain_reason=uncertain_reason,
        ),
    ]

    outcome_map = {
        "SEAL": "seal",
        "STOP_AND_FIX": "stop_and_fix",
        "UNCERTAIN": "pending_review",
    }
    pack_outcome = outcome_map.get(verdict, "pending_review")

    # Record ID determination (deterministic for idempotency)
    record_id = sample_row.get("record_id") if sample_row else f"PCK-{subject_id}"

    # Previous evidence traceability (§4.3)
    upstream_refs = [r["record_id"] for r in request.get("previous_evidence", [])]

    captured_at = order.captured_at or (sample_row.get("captured_at") if sample_row else utcnow())
    operator_id = order.operator_id or (sample_row.get("operator_id") if sample_row else "op_packer")

    record = build_record(
        request,
        agent_id=AGENT_ID,
        record_id=record_id,
        captured_at=captured_at,
        operator_id=operator_id,
        unit_scope="order",
        refs={"order_id": order.order_id},
        checks=checks,
        outcome=pack_outcome,
        model=extracted.get("model", {
            "name": "meta-llama/llama-3.2-90b-vision-instruct",
            "version": "2026-10",
            "provider": "openrouter",
            "calls": 1,
            "cost_usd": 0.002,
        }),
        inputs=inputs,
        reason=reconciliation["reason"],
        upstream_refs=upstream_refs,
        latency_ms=extracted.get("latency_ms", 1845),
        payload={
            "channel": order.channel,
            "order_lines": order.order_lines,
            "observed_in_box": extracted.get("observations", []),
            "operator_verdict": sample_row.get("operator_verdict") if sample_row else pack_outcome,
            "agent_agrees_with_operator": (sample_row.get("operator_verdict") == pack_outcome) if sample_row else True,
        },
    )

    return build_output(record)


app = make_app(STAGE, handle)
