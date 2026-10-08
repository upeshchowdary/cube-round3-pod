"""Multimodal Perception Pipeline for Receiving Inspection.

Supports:
- Deterministic Replay / Offline Mock (used in tests and CI)
- Live Google Gemini Vision (gemini-2.5-flash / gemini-2.5-flash-lite via google-genai)
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Tuple

from .prompts import RECEIVING_INSPECTION_SYSTEM_PROMPT, build_user_prompt
from .schemas import (
    ComponentsObservation,
    ConditionObservation,
    EvidenceRef,
    ProductObservation,
    PurchaseOrderInput,
    QuantityObservation,
    UncertaintyItem,
    VariantObservation,
    VisionObservation,
)


def observe_deterministic(po: PurchaseOrderInput, row: dict[str, Any], refs: list[str]) -> Tuple[VisionObservation, dict[str, Any]]:
    """Replay the operator-recorded facts of a sample CSV row as observations. NOT vision: no image is examined,
    so every observation says it came from the CSV row, and model.name is "csv-replay"."""
    flags = [f.strip() for f in (row.get("quality_flags") or "").split(";") if f.strip()]
    co = int(row.get("cartons_ordered", po.expected_cartons))
    cr = int(row.get("cartons_received", po.expected_cartons))
    qo = int(row.get("qty_ordered", po.expected_quantity))
    qr = int(row.get("qty_received", po.expected_quantity))
    ident = row.get("identity_match", "yes")
    c_dam = row.get("carton_damage", "none")
    u_dam = row.get("unit_damage", "none")
    src = f"csv:{row.get('record_id', 'receiving_sample')}"

    evidence_list: list[EvidenceRef] = []
    uncertainty_list: list[UncertaintyItem] = []

    # Cite the capture refs the row names (no bytes are read in replay), else the CSV row itself.
    primary_ref = refs[0] if refs else src
    carton_ref = refs[1] if len(refs) > 1 else primary_ref
    unit_ref = refs[2] if len(refs) > 2 else primary_ref

    # Product identity observation
    if ident.lower() == "yes":
        evidence_list.append(EvidenceRef(image_id=primary_ref, observation=f"CSV row records identity match for {po.sku}", field="product"))
        prod_obs = ProductObservation(observed_sku=po.sku, confidence=0.98)
    elif ident.lower() == "uncertain":
        uncertainty_list.append(UncertaintyItem(field="product", reason="CSV row records identity as uncertain."))
        prod_obs = ProductObservation(observed_sku="uncertain", confidence=0.4)
    else:
        evidence_list.append(EvidenceRef(image_id=primary_ref, observation=f"CSV row records identity mismatch: {ident}", field="product"))
        prod_obs = ProductObservation(observed_sku=ident, confidence=0.95)

    # Quantity observation
    qty_conf = 0.95
    if qo != qr or co != cr:
        qty_conf = 0.90
    evidence_list.append(EvidenceRef(image_id=carton_ref, observation=f"CSV row records cartons {cr} of {co}; units {qr} of {qo}", field="quantity"))
    qty_obs = QuantityObservation(observed_units=qr, observed_cartons=cr, confidence=qty_conf)

    # Condition observation
    c_conf = 0.4 if (c_dam.lower() == "uncertain" or u_dam.lower() == "uncertain") else 0.95
    if c_dam.lower() == "uncertain":
        uncertainty_list.append(UncertaintyItem(field="condition", reason="CSV row records carton condition as uncertain."))
    elif c_dam.lower() not in ("none", ""):
        evidence_list.append(EvidenceRef(image_id=carton_ref, observation=f"CSV row records carton damage: {c_dam}", field="condition"))

    if u_dam.lower() == "uncertain":
        uncertainty_list.append(UncertaintyItem(field="condition", reason="CSV row records unit condition as uncertain."))
    elif u_dam.lower() not in ("none", ""):
        evidence_list.append(EvidenceRef(image_id=unit_ref, observation=f"CSV row records unit damage: {u_dam}", field="condition"))

    cond_obs = ConditionObservation(
        damaged=(c_dam.lower() not in ("none", "", "uncertain") or u_dam.lower() not in ("none", "", "uncertain")),
        carton_damage=c_dam,
        unit_damage=u_dam,
        confidence=c_conf,
    )

    # Variant & Components
    var_obs = VariantObservation(observed_variant=po.expected_variant or "Standard", confidence=0.95)
    missing_comps = [f for f in flags if "missing" in f.lower() or "component" in f.lower()]
    comp_obs = ComponentsObservation(missing=missing_comps, confidence=0.92)

    obs = VisionObservation(
        product=prod_obs,
        quantity=qty_obs,
        variant=var_obs,
        condition=cond_obs,
        components=comp_obs,
        quality_flags=flags,
        evidence=evidence_list,
        uncertainty=uncertainty_list,
    )

    model_meta = {
        "name": "csv-replay",
        "version": "receiving-r2-replay",
        "provider": None,
        "calls": 0,
        "cost_usd": 0.0,
    }
    return obs, model_meta


_MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}


def observe_gemini(po: PurchaseOrderInput, refs: list[str], api_key: str, input_dir: Path | None = None) -> Tuple[VisionObservation, dict[str, Any]]:
    """Live Google Gemini multimodal perception: one call carrying every capture's bytes."""
    root = (input_dir or Path(os.environ.get("INPUT_DIR", Path(__file__).resolve().parents[3] / "data" / "input"))).resolve()
    images = []
    for ref in refs:
        path = (root / ref).resolve()
        if path.is_relative_to(root) and path.is_file() and path.suffix.lower() in _MIME:
            images.append((ref, path.read_bytes(), _MIME[path.suffix.lower()]))
    if not images:
        raise RuntimeError("no readable receiving captures under data/input/<unit>/receiving/: nothing to look at")
    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)
        user_prompt = build_user_prompt(
            order_number=po.order_number,
            sku=po.sku,
            product_name=po.product_name,
            expected_quantity=po.expected_quantity,
            expected_cartons=po.expected_cartons,
            expected_variant=po.expected_variant,
            image_refs=[ref for ref, _, _ in images],
        )
        parts: list[Any] = [RECEIVING_INSPECTION_SYSTEM_PROMPT, user_prompt]
        for ref, data_bytes, mime in images:
            parts += [f"imageId: {ref}", types.Part.from_bytes(data=data_bytes, mime_type=mime)]

        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=parts,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.1,
            ),
        )

        text = response.text or "{}"
        clean_text = re.sub(r"^```json\s*", "", text.strip())
        clean_text = re.sub(r"\s*```$", "", clean_text)
        data = json.loads(clean_text)

        p = data.get("product", {})
        q = data.get("quantity", {})
        v = data.get("variant", {})
        c = data.get("condition", {})
        comp = data.get("components", {})

        obs = VisionObservation(
            product=ProductObservation(observed_sku=p.get("observedSku"), confidence=float(p.get("confidence", 1.0))),
            quantity=QuantityObservation(
                observed_units=q.get("observedUnits"),
                observed_cartons=q.get("observedCartons"),
                confidence=float(q.get("confidence", 1.0)),
            ),
            variant=VariantObservation(observed_variant=v.get("observed"), confidence=float(v.get("confidence", 1.0))),
            condition=ConditionObservation(
                carton_damage=c.get("cartonDamage", "none"),
                unit_damage=c.get("unitDamage", "none"),
                damage_types=c.get("damageTypes", []),
                confidence=float(c.get("confidence", 1.0)),
            ),
            components=ComponentsObservation(missing=comp.get("missing", []), confidence=float(comp.get("confidence", 1.0))),
            quality_flags=data.get("qualityFlags", []),
            evidence=[EvidenceRef(image_id=e.get("imageId", ""), observation=e.get("observation", ""), field=e.get("field", "")) for e in data.get("evidence", [])],
            uncertainty=[UncertaintyItem(field=u.get("field", ""), reason=u.get("reason", "")) for u in data.get("uncertainty", [])],
        )

        model_meta = {
            "name": "gemini-2.5-flash",
            "version": "2.5-flash",
            "provider": "google",
            "prompt_version": "v1.2",
            "calls": 1,
            "cost_usd": None,  # not measured
        }
        return obs, model_meta
    except Exception as exc:
        raise RuntimeError(f"Gemini perception failed: {exc}") from exc
