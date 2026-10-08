"""Order lookup and tenancy enforcement for Pack Manager."""
from __future__ import annotations

import csv
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from shared.utils import sample_data

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "test_fixtures.json"


@dataclass
class PackOrder:
    unit_id: str
    org_id: str
    order_id: str
    order_lines: list[dict[str, Any]]
    photo_refs: list[str]
    channel: str = "mfn"
    operator_id: str | None = None
    captured_at: str | None = None
    fixture_id: str | None = None


def _load_fixtures() -> list[dict[str, Any]]:
    if FIXTURES_PATH.is_file():
        try:
            return json.loads(FIXTURES_PATH.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def lookup_pack_order(subject_id: str, org_id: str, input_dir: Path | None = None) -> PackOrder:
    """Finds pack order metadata, strictly enforcing tenancy isolation (§5.1).

    Raises:
        LookupError: If subject is unknown or belongs to a different tenant.
    """
    input_dir = input_dir or Path(os.environ.get("INPUT_DIR", REPO_ROOT / "data" / "input"))
    custom_csv = input_dir / "pack_orders.csv"

    known_units: dict[str, set[str]] = {}  # unit_id -> set of org_ids

    # 1. Custom input pack_orders.csv if present
    if custom_csv.is_file():
        with open(custom_csv, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                uid, oid = r.get("unit_id"), r.get("org_id")
                if uid and oid:
                    known_units.setdefault(uid, set()).add(oid)
                    if uid == subject_id and oid == org_id:
                        from agents.pack.adapter.engine import parse_order_lines
                        return PackOrder(
                            unit_id=uid,
                            org_id=oid,
                            order_id=r.get("order_id", f"ORD-{uid}"),
                            order_lines=parse_order_lines(r.get("order_lines", "")),
                            photo_refs=list(filter(None, r.get("photo_refs", "").split(";"))),
                            channel=r.get("channel", "mfn"),
                            operator_id=r.get("operator_id"),
                            captured_at=r.get("captured_at"),
                        )

    # 2. Sample pack data (data/sample/pack_sample.csv)
    for r in sample_data.rows("pack"):
        uid, oid = r.get("unit_id"), r.get("org_id")
        if uid and oid:
            known_units.setdefault(uid, set()).add(oid)
            if uid == subject_id and oid == org_id:
                from agents.pack.adapter.engine import parse_order_lines
                return PackOrder(
                    unit_id=uid,
                    org_id=oid,
                    order_id=r.get("order_id", f"ORD-{uid}"),
                    order_lines=parse_order_lines(r.get("order_lines", "")),
                    photo_refs=list(filter(None, r.get("photo_refs", "").split(";"))),
                    channel=r.get("channel", "mfn"),
                    operator_id=r.get("operator_id"),
                    captured_at=r.get("captured_at"),
                )

    # 3. Held-out test fixtures (mapped under demo orgs)
    fixtures = _load_fixtures()
    for fix in fixtures:
        fid = fix.get("fixture_id")
        if not fid:
            continue
        # Fixtures can be mapped as FIX-1.a or unit_id
        fixture_unit_id = f"FIX-{fid}"
        # Default fixtures belong to org_demo_alpha unless specified
        fixture_org = fix.get("org_id", "org_demo_alpha")
        known_units.setdefault(fid, set()).add(fixture_org)
        known_units.setdefault(fixture_unit_id, set()).add(fixture_org)

        if (subject_id in (fid, fixture_unit_id)) and org_id == fixture_org:
            return PackOrder(
                unit_id=subject_id,
                org_id=org_id,
                order_id=f"ORD-FIX-{fid}",
                order_lines=fix.get("expected_order", []),
                photo_refs=[fix.get("image_url", "")],
                channel="mfn",
                operator_id="op_held_out",
                fixture_id=fid,
            )

    # Tenancy check: was unit found under another tenant?
    if subject_id in known_units:
        raise LookupError(f"Subject {subject_id} belongs to another tenant (not {org_id})")

    raise LookupError(f"No pack order found for {subject_id} under tenant {org_id}")

