"""Deterministic Pack Reconciliation Engine.

Ported from Round 2 TypeScript implementation (nikhilagarwal03/agent/src/lib/reconciliation/engine.ts).
Compares expected order manifest against VLM observations and visual decoys.
Emits tri-state verdicts: SEAL, STOP_AND_FIX, or UNCERTAIN.
"""
from __future__ import annotations

from typing import Any


def aggregate_items(items: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> dict[str, int]:
    """Sums quantities grouped by trimmed SKU."""
    totals: dict[str, int] = {}
    for item in items:
        sku = str(item.get("sku", "")).strip()
        if not sku:
            continue
        try:
            qty = int(item.get("quantity", 1))
        except (ValueError, TypeError):
            qty = 1
        totals[sku] = totals.get(sku, 0) + qty
    return totals


def parse_order_lines(text: str) -> list[dict[str, Any]]:
    """Parses semicolon-separated SKU:qty strings into item dicts."""
    items: list[dict[str, Any]] = []
    for part in filter(None, text.split(";")):
        sku, _, qty_str = part.partition(":")
        sku = sku.strip()
        if not sku:
            continue
        try:
            qty = int(qty_str) if qty_str else 1
        except ValueError:
            qty = 1
        items.append({"sku": sku, "quantity": qty})
    return items


def reconcile_pack(
    order_lines: list[dict[str, Any]],
    extracted: dict[str, Any],
) -> dict[str, Any]:
    """Reconciles expected order lines against extracted visual observations.

    Parameters:
        order_lines: List of {"sku": str, "quantity": int} expected by manifest.
        extracted: VLM output containing observations, decoys, occlusion, status, and reason.

    Returns:
        dict containing all_items_present, quantities_correct, missing_items,
        quantity_mismatches, unexpected_items, verdict, and reason.
    """
    expected = aggregate_items(order_lines)
    observations = extracted.get("observations", [])
    observed = aggregate_items(observations)

    missing_items: list[str] = []
    quantity_mismatches: list[dict[str, Any]] = []
    unexpected_items: list[dict[str, Any]] = []

    # Check for missing items and quantity mismatches
    for sku, exp_qty in expected.items():
        obs_qty = observed.get(sku, 0)
        if obs_qty == 0:
            missing_items.append(sku)
        if obs_qty != exp_qty:
            quantity_mismatches.append({
                "sku": sku,
                "expected": exp_qty,
                "observed": obs_qty,
            })

    # Check for unexpected items in observations
    for sku, qty in observed.items():
        if sku not in expected:
            unexpected_items.append({
                "sku": sku,
                "quantity": qty,
                "reason": "The visible SKU could not be identified" if sku == "UNKNOWN" else "SKU was not ordered",
            })

    # Include any visual decoys / foreign objects
    for decoy in extracted.get("decoys", []):
        unexpected_items.append({
            "sku": decoy.get("label", "FOREIGN_OBJECT"),
            "quantity": decoy.get("quantity", 1),
            "reason": decoy.get("reason", "Foreign object or decoy detected in open carton"),
        })

    all_items_present = len(missing_items) == 0
    quantities_correct = len(quantity_mismatches) == 0

    occlusion = extracted.get("occlusion")
    occlusion_status = occlusion.get("status", "not_reported") if isinstance(occlusion, dict) else "not_reported"
    # Same rule as Round 2 engine.ts: anything other than an explicit "clear" is uncertain evidence. (The port used to
    # check only partial/severe, so an unexpected value such as "heavy" or a missing field could still be sealed.)
    has_uncertain_evidence = (
        extracted.get("status") == "uncertain"
        or occlusion_status != "clear"
    )

    if has_uncertain_evidence:
        verdict = "UNCERTAIN"
        reason = (
            extracted.get("reason")
            or f"Visual evidence is ambiguous due to {occlusion_status} occlusion in carton."
        )
    elif not all_items_present or not quantities_correct or len(unexpected_items) > 0:
        verdict = "STOP_AND_FIX"
        reasons = []
        if missing_items:
            reasons.append(f"missing: {', '.join(missing_items)}")
        if quantity_mismatches:
            reasons.append(f"quantity mismatch for {', '.join(m['sku'] for m in quantity_mismatches)}")
        if unexpected_items:
            reasons.append(f"unexpected items: {', '.join(u['sku'] for u in unexpected_items)}")
        reason = "Discrepancy detected: " + "; ".join(reasons)
    else:
        verdict = "SEAL"
        reason = "Every expected SKU is present at the expected quantity with no extra or foreign items."

    return {
        "all_items_present": all_items_present,
        "quantities_correct": quantities_correct,
        "missing_items": missing_items,
        "quantity_mismatches": quantity_mismatches,
        "unexpected_items": unexpected_items,
        "verdict": verdict,
        "reason": reason,
        "expected_aggregated": expected,
        "observed_aggregated": observed,
    }

