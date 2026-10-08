from __future__ import annotations

import hashlib
from typing import Any

from returns_manager.batch.runner import RowResult
from shared.utils.records import build_output, build_record, check as make_check, rollup

from .captures import ResolvedCaptures
from .orders import ReturnOrder


def _map_uncertain_reason(reason_str: str | None) -> str:
    if not reason_str:
        return "insufficient_evidence"
    r = reason_str.lower()
    if any(k in r for k in ("single_photo", "poor", "blurry", "low_res", "dark", "lighting")):
        return "poor_image"
    if any(k in r for k in ("occluded", "not_visible", "hidden", "partial")):
        return "occluded"
    if any(k in r for k in ("model", "session", "timeout", "quota")):
        return "model_error"
    if any(k in r for k in ("rule", "unsupported", "missing_policy")):
        return "rule_unavailable"
    if any(k in r for k in ("conflict", "discrepancy", "ambiguous")):
        return "conflicting_evidence"
    return "insufficient_evidence"


def build_returns_record(
    request: dict,
    order: ReturnOrder,
    row_result: RowResult,
    captures: ResolvedCaptures,
    upstream_recon: dict[str, Any],
    *,
    agent_id: str,
    model_mode: str,
    cassette_sha256: str | None,
    cassette_provenance: str | None = None,
    prompt_version: str,
    model_name: str,
    model_version: str,
    live_calls: int,
    recorded_calls: int | None,
    cost_note: str,
    condition_scale_source: str,
    round2_commit: str,
    captured_at_source: str,
    captured_at: str,
    latency_ms: int,
    packing_error_note: str | None = None,
) -> dict[str, Any]:
    detail = row_result.detail or {}
    checks_by_key = {c.get("check_key") or c.get("name"): c for c in detail.get("checks", [])}

    mapped_checks: list[dict[str, Any]] = []

    # 1. identity_match (§4.5: MUST be index 0)
    if "identity" in checks_by_key:
        r2_chk = checks_by_key["identity"]
        v = r2_chk["verdict"]
        conf = round(r2_chk["confidence_bp"] / 10000.0, 2) if r2_chk.get("confidence_bp") is not None else None
        ident_detail = detail.get("identity", {})
        
        evidence_refs: list[str] = []
        for alias in ident_detail.get("evidence_photos", []):
            if alias in captures.alias_map:
                evidence_refs.append(captures.alias_map[alias])
            elif alias == "ref_before":
                evidence_refs.append(captures.reference_ref)
        if not evidence_refs:
            evidence_refs = [captures.reference_ref, *captures.return_refs]

        obs_ident = {
            "actual_sku": ident_detail.get("actual_sku") or (order.ordered_sku if v == "PASS" else None),
            "color_match": ident_detail.get("color_match"),
            "size_match": ident_detail.get("size_match"),
            "risk_flags": list(ident_detail.get("risk_flags", ())),
            "barcode_status": ident_detail.get("barcode_status"),
        }
        unc_reason = _map_uncertain_reason(ident_detail.get("reasons", [None])[0]) if v == "UNCERTAIN" else None

        mapped_checks.append(
            make_check(
                "identity_match",
                v,
                conf,
                expected=order.ordered_sku,
                observed=obs_ident,
                detail=r2_chk.get("detail", ""),
                evidence_refs=evidence_refs,
                uncertain_reason=unc_reason,
            )
        )

    # 2. completeness (§4.5: MUST be index 1)
    if "completeness" in checks_by_key:
        r2_chk = checks_by_key["completeness"]
        v = r2_chk["verdict"]
        conf = round(r2_chk["confidence_bp"] / 10000.0, 2) if r2_chk.get("confidence_bp") is not None else None
        comp_detail = detail.get("completeness", {})

        evidence_refs = []
        for c in comp_detail.get("components", []):
            for ph in c.get("photos", []):
                ref = captures.alias_map.get(ph)
                if ref and ref not in evidence_refs:
                    evidence_refs.append(ref)
        if not evidence_refs:
            evidence_refs = list(captures.return_refs)

        parts_missing = comp_detail.get("parts_missing", "")
        parts_uncertain = comp_detail.get("parts_uncertain", "")
        obs_comp = {
            "status": comp_detail.get("status"),
            "parts_present": [c["name"] for c in comp_detail.get("components", []) if c.get("status") == "present"],
            "parts_missing": [p for p in parts_missing.split(";") if p] if parts_missing else [],
            "parts_uncertain": [p for p in parts_uncertain.split(";") if p] if parts_uncertain else [],
        }
        unc_reason = "insufficient_evidence" if v == "UNCERTAIN" else None

        mapped_checks.append(
            make_check(
                "completeness",
                v,
                conf,
                expected=comp_detail.get("parts_list") or order.parts_list,
                observed=obs_comp,
                detail=r2_chk.get("detail", ""),
                evidence_refs=evidence_refs,
                uncertain_reason=unc_reason,
            )
        )

    # 3. condition (§4.5: MUST be index 2)
    if "condition_grade" in checks_by_key:
        r2_chk = checks_by_key["condition_grade"]
        v = r2_chk["verdict"]
        conf = round(r2_chk["confidence_bp"] / 10000.0, 2) if r2_chk.get("confidence_bp") is not None else None
        cond_detail = detail.get("condition", {})

        obs_cond = {
            "amazon_condition": cond_detail.get("amazon_condition"),
            "cosmetic_grade": cond_detail.get("cosmetic_grade"),
            "listing_blockers": list(cond_detail.get("listing_blockers", ())),
            "phrases_matched": list(cond_detail.get("phrases_matched", ())),
        }
        unc_reason = _map_uncertain_reason(cond_detail.get("uncertainty_reason")) if v == "UNCERTAIN" else None

        mapped_checks.append(
            make_check(
                "condition",
                v,
                conf,
                expected="relistable in new or like-new condition",
                observed=obs_cond,
                detail=r2_chk.get("detail", ""),
                evidence_refs=list(captures.return_refs),
                uncertain_reason=unc_reason,
            )
        )

    # Roll-up & decision
    verdict = rollup(mapped_checks)
    d_obj = detail.get("decision", {})
    recommended_disp = d_obj.get("recommended_disposition")
    requires_review = detail.get("requires_review", False) or (row_result.output_row.get("requires_review") == "true")
    rule_id = d_obj.get("rule_id", "R00")

    # Outcome mapping (§4.5):
    # Only allow engine's recommended_disposition if requires_review is False; else pending_review
    if not requires_review and recommended_disp:
        outcome = recommended_disp
    else:
        outcome = "pending_review"

    needs_human = requires_review or (verdict == "UNCERTAIN")

    rationale = row_result.output_row.get("rationale") or detail.get("rationale") or ""
    reason_parts = [f"{rule_id}: {rationale}"]
    if packing_error_note:
        reason_parts.append(packing_error_note)
    full_reason = " ".join(reason_parts)

    confidences = [c["confidence"] for c in mapped_checks if c["confidence"] is not None]
    min_confidence = min(confidences) if confidences else None

    # Deterministic record ID (§4.5): RTN- + first 16 hex chars of sha256(request_id)
    safe_req_id = request.get("request_id", "")
    rec_hash = hashlib.sha256(safe_req_id.encode("utf-8")).hexdigest()[:16]
    record_id = f"RTN-{rec_hash}"

    # Build payload with all required contract and additive keys
    ident_dict = detail.get("identity", {})
    parts_missing_raw = row_result.output_row.get("parts_missing", "")
    parts_missing_list = [p for p in parts_missing_raw.split(";") if p] if parts_missing_raw else []

    payload: dict[str, Any] = {
        "observed_state": row_result.output_row.get("observed_state", "uncertain"),
        "amazon_condition": row_result.output_row.get("amazon_condition", "uncertain"),
        "parts_missing": parts_missing_list,
        "recommended_disposition": recommended_disp,
        "requires_review": requires_review,
        "review_reasons": detail.get("review_reasons", []),
        "rule_id": rule_id,
        "rules_version": "batch-import-v1",
        "claim_signals": detail.get("claims", {}),
        "identity": {
            "color_match": ident_dict.get("color_match"),
            "size_match": ident_dict.get("size_match"),
            "risk_flags": list(ident_dict.get("risk_flags", ())),
            "barcode_status": ident_dict.get("barcode_status"),
        },
        "reference_source": captures.reference_source,
        "photo_alias_map": captures.alias_map,
        "upstream_reconciliation": upstream_recon,
        "model_mode": model_mode,
        "round2_commit": round2_commit,
        "condition_scale_source": condition_scale_source,
        "cost_note": cost_note,
        "captured_at_source": captured_at_source,
    }
    if cassette_sha256:
        payload["cassette_sha256"] = cassette_sha256
    if recorded_calls is not None:
        payload["recorded_calls"] = recorded_calls

    # D-013: a replayed answer is labelled as recorded, the same way Pack labels its benchmark replay, so nobody reads
    # "gemini … 0 calls" as a live judgment. Live runs keep the model name and the real request count.
    # A cassette marked provenance=synthetic was written by hand in the Gemini response format, not recorded from a
    # model run on these captures: it exercises the pipeline and rules, and must never be read as a model judgment.
    replayed = model_mode == "replay"
    synthetic = replayed and cassette_provenance == "synthetic"
    if synthetic:
        payload["cassette_provenance"] = "synthetic"
    model_meta = {
        "name": "synthetic-cassette (hand-authored, no model run)" if synthetic
        else (f"{model_name} (recorded)" if replayed else model_name),
        "version": model_version,
        "provider": ("replay:synthetic-cassette" if synthetic else "replay:cassette") if replayed else "google",
        "prompt_version": prompt_version,
        "calls": live_calls if model_mode in ("live", "record") else 0,
        "cost_usd": 0.0,
    }

    # Pass all upstream records actually provided in request
    upstream_refs = [r["record_id"] for r in request.get("previous_evidence", [])]

    record = build_record(
        request,
        agent_id=agent_id,
        record_id=record_id,
        captured_at=captured_at,
        checks=mapped_checks,
        outcome=outcome,
        reason=full_reason,
        model=model_meta,
        status="completed",
        operator_id=order.operator_id,
        inputs=captures.inputs,
        payload=payload,
        upstream_refs=upstream_refs,
        verdict=verdict,
        confidence=min_confidence,
        needs_human=needs_human,
        latency_ms=latency_ms,
    )

    return build_output(record)
