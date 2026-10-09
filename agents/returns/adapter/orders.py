from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from shared.utils import sample_data

# Allowed order metadata keys (§1.7)
ORDER_METADATA_FIELDS = {
    "record_id",
    "unit_id",
    "org_id",
    "order_id",
    "ordered_sku",
    "ordered_asin",
    "parts_list",
    "operator_id",
    "captured_at",
    "category",
    "list_price_minor",
}


@dataclass
class ReturnOrder:
    record_id: str
    unit_id: str
    org_id: str
    order_id: str
    ordered_sku: str
    ordered_asin: str
    parts_list: str
    operator_id: str | None
    captured_at: str | None
    category: str | None
    list_price_minor: int


def _resolve_category(org_id: str, sku: str, explicit_cat: str | None, r2_ref_dir: Path) -> str | None:
    if explicit_cat:
        return explicit_cat

    # 1. Product card
    card_path = r2_ref_dir / "products" / org_id / f"{sku}.yaml"
    if card_path.is_file():
        try:
            data = yaml.safe_load(card_path.read_text(encoding="utf-8"))
            if data and "category_key" in data:
                return data["category_key"]
        except Exception:
            pass

    # 2. Category map
    map_path = r2_ref_dir / "categories" / "sku-category-map.yaml"
    if map_path.is_file():
        try:
            data = yaml.safe_load(map_path.read_text(encoding="utf-8"))
            mapping = data.get("mapping", {})
            if sku in mapping and "category_key" in mapping[sku]:
                return mapping[sku]["category_key"]
        except Exception:
            pass

    return None


def lookup_order(
    subject_id: str,
    org_id: str,
    *,
    input_dir: Path,
    r2_ref_dir: Path,
) -> ReturnOrder:
    """Finds return order metadata while strictly ignoring operator verdict columns (§1.7).

    Enforces tenancy isolation: raises LookupError if subject does not belong to org_id.
    """
    rows_by_org: dict[tuple[str, str], dict[str, Any]] = {}
    known_units: set[str] = set()

    # 1. Read custom returns_orders.csv if present
    custom_csv = input_dir / "returns_orders.csv"
    if custom_csv.is_file():
        with open(custom_csv, newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for r in reader:
                uid, oid = r.get("unit_id"), r.get("org_id")
                if uid and oid:
                    known_units.add(uid)
                    filtered = {k: v for k, v in r.items() if k in ORDER_METADATA_FIELDS}
                    rows_by_org[(uid, oid)] = filtered

    # 2. Read sample returns_sample.csv through sample_data.rows("returns")
    for r in sample_data.rows("returns"):
        uid, oid = r.get("unit_id"), r.get("org_id")
        if uid and oid:
            known_units.add(uid)
            if (uid, oid) not in rows_by_org:
                filtered = {k: v for k, v in r.items() if k in ORDER_METADATA_FIELDS}
                rows_by_org[(uid, oid)] = filtered

    # Tenancy check (§1.6)
    target_key = (subject_id, org_id)
    if target_key not in rows_by_org:
        if subject_id in known_units:
            raise LookupError(f"no return for {subject_id} in {org_id} (subject belongs to different tenant)")
        raise LookupError(f"no return for {subject_id} in {org_id}")

    raw = rows_by_org[target_key]
    sku = raw.get("ordered_sku") or ""
    cat = _resolve_category(org_id, sku, raw.get("category"), r2_ref_dir)

    list_price = 2500
    if raw.get("list_price_minor"):
        try:
            list_price = int(raw["list_price_minor"])
        except ValueError:
            pass

    return ReturnOrder(
        record_id=raw.get("record_id") or f"RTN-{subject_id}",
        unit_id=subject_id,
        org_id=org_id,
        order_id=raw.get("order_id") or "",
        ordered_sku=sku,
        ordered_asin=raw.get("ordered_asin") or "",
        parts_list=raw.get("parts_list") or "",
        operator_id=raw.get("operator_id"),
        captured_at=raw.get("captured_at"),
        category=cat,
        list_price_minor=list_price,
    )
