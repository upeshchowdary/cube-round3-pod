"""Read the Round 2-format CSVs every agent takes its own input from (DATA_DIR, default data/sample/).

Tenancy: every lookup is scoped by org_id. A unit that exists only under another org
raises LookupError, which the server turns into a 404 (never a cross-tenant answer).

A dataset may hold only some of the five files (a judge may hand over just the Receiving file): a missing file has no
rows, so its stage is skipped for every unit instead of crashing. A file that lacks a column an agent reads is refused
with a DatasetError naming the column, because the agents used to fill a missing column with a default and could
report a confident PASS on data they never saw (a renamed `qty_received` compared the order with itself).
"""
from __future__ import annotations

import csv
import difflib
import os
from functools import lru_cache
from pathlib import Path

DEFAULT_DIR = Path(__file__).resolve().parents[2] / "data" / "sample"
# The Pod's own units next to the organisers' sample (data/input/RETURNS_PHOTOS.md): read only with the default dataset,
# never mixed into a dataset someone hands us. Pack and Returns already read these files for their order lookup.
POD_DIR = Path(__file__).resolve().parents[2] / "data" / "input"
POD_FILES = {"pack": "pack_orders.csv", "returns": "returns_orders.csv"}
FILES = {
    "receiving": "receiving_sample.csv",
    "prep": "prep_sample.csv",
    "pack": "pack_sample.csv",
    "returns": "returns_sample.csv",
    "fees": "fee_report_sample.csv",
}
# Columns an agent reads without which it would crash or silently judge on a default. Other columns are optional.
REQUIRED = {
    "receiving": ("record_id", "unit_id", "org_id", "po_number", "po_line", "supplier", "sku", "asin",
                  "cartons_ordered", "cartons_received", "qty_ordered", "qty_received",
                  "identity_match", "carton_damage", "unit_damage", "captured_at"),
    "prep": ("record_id", "unit_id", "org_id", "polybag_present_sealed", "suffocation_warning", "fnsku_label_placement",
             "original_barcode_covered", "expiry_date", "handling_marks", "prep_price_usd", "operator_id", "captured_at"),
    "pack": ("record_id", "unit_id", "org_id", "order_id", "order_lines", "observed_in_box", "captured_at"),
    "returns": ("unit_id", "org_id", "order_id", "ordered_sku", "parts_list"),
    "fees": ("line_id", "report_type", "unit_id", "org_id", "sku", "fnsku", "charge_type", "amount_usd", "posted_date"),
}
# The stage that reads each file (fees -> Recovery).
STAGE_OF = {"receiving": "receiving", "prep": "prep", "pack": "pack", "returns": "returns", "fees": "recovery"}


class DatasetError(ValueError):
    """A dataset file cannot be used as it is. The message says what to change."""


def data_dir() -> Path:
    return Path(os.environ.get("DATA_DIR", DEFAULT_DIR))


def missing_columns(kind: str, header: list[str]) -> list[str]:
    return [c for c in REQUIRED[kind] if c not in header]


def describe_missing(kind: str, header: list[str]) -> str:
    """'qty_received (closest: received_qty), ...' for a header that lacks required columns."""
    parts = []
    for col in missing_columns(kind, header):
        close = difflib.get_close_matches(col, [h for h in header if h not in REQUIRED[kind]], n=1, cutoff=0.5)
        parts.append(f"{col} (closest: {close[0]})" if close else col)
    return ", ".join(parts)


@lru_cache(maxsize=64)
def _rows(kind: str, file: str, mtime_ns: int, size: int) -> tuple[dict, ...]:
    path = Path(file)
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        header = [h.strip() for h in (reader.fieldnames or [])]
        if missing_columns(kind, header):
            raise DatasetError(f"{path.name} is missing required column(s): {describe_missing(kind, header)}. "
                               f"Rename them, or load the folder with: python scripts/dev.py dataset <folder> --map OLD=NEW")
        return tuple({(k or "").strip(): v for k, v in r.items()} for r in reader)


def _read(kind: str, path: Path) -> tuple[dict, ...]:
    try:
        st = path.stat()
    except FileNotFoundError:
        return ()
    # Keyed on the file's mtime and size too, so an edited CSV is re-read (a running API used to serve the old rows).
    return _rows(kind, str(path), st.st_mtime_ns, st.st_size)


def rows(kind: str) -> tuple[dict, ...]:
    """Every row of one file. A file that is not in the dataset has no rows.

    With the default dataset, the Pod's own rows for that file (POD_FILES) follow the sample's; a unit already in the
    sample keeps its sample row."""
    base = _read(kind, data_dir() / FILES[kind])
    if kind not in POD_FILES or data_dir().resolve() != DEFAULT_DIR.resolve():
        return base
    seen = {(r["unit_id"], r["org_id"]) for r in base}
    return base + tuple(r for r in _read(kind, POD_DIR / POD_FILES[kind]) if (r["unit_id"], r["org_id"]) not in seen)


def present(kind: str) -> bool:
    """Whether this dataset includes the file for `kind` at all."""
    return (data_dir() / FILES[kind]).is_file()


def row(kind: str, unit_id: str, org_id: str) -> dict:
    """The single row for a unit under an org, or LookupError."""
    for r in rows(kind):
        if r["unit_id"] == unit_id and r["org_id"] == org_id:
            return r
    raise LookupError(f"no {kind} record for {unit_id} in {org_id}")


def has(kind: str, unit_id: str, org_id: str) -> bool:
    try:
        row(kind, unit_id, org_id)
        return True
    except LookupError:
        return False


def known(unit_id: str, org_id: str) -> bool:
    """The unit exists under this org in at least one file of the dataset (tenancy: another org's unit is unknown)."""
    return any(has(kind, unit_id, org_id) for kind in FILES)


def fee_lines(unit_id: str, org_id: str) -> list[dict]:
    return [r for r in rows("fees") if r["unit_id"] == unit_id and r["org_id"] == org_id]


def route(unit_id: str, org_id: str) -> str:
    """fba if a prep record exists, mfn if a pack record exists, else unknown.

    Round 2 sample: a unit has a Prep record or a Pack record, never both,
    and 9 units have neither (see docs/decisions.md, finding F-12).
    """
    if has("prep", unit_id, org_id):
        return "fba"
    if has("pack", unit_id, org_id):
        return "mfn"
    return "unknown"


def case_for(unit_id: str, org_id: str, *, route_hint: str | None = None, returned: bool | None = None) -> dict:
    """The case the orchestrator runs for one unit of this dataset.

    Prep, Pack and Returns are already routed by their own rows (route / returned). Receiving and Recovery run for every
    unit, so when the dataset cannot feed them they are listed in `skip_stages` (with `skip_reasons`) and recorded as
    skipped instead of failing: a unit missing from the Receiving file, a dataset without a fee report, or a unit
    without a Receiving row, which Recovery's own tenancy check requires.
    """
    case = {"org_id": org_id, "unit_id": unit_id, "route": route_hint or route(unit_id, org_id),
            "returned": has("returns", unit_id, org_id) if returned is None else returned}
    in_receiving = has("receiving", unit_id, org_id)
    reasons = {}
    if not in_receiving:
        reasons["receiving"] = "no receiving input for this unit in the dataset"
    if not present("fees"):
        reasons["recovery"] = "no fee report in the dataset"
    elif not in_receiving:
        reasons["recovery"] = "Recovery needs the unit's Receiving row (its tenancy check), which the dataset lacks"
    if reasons:
        case["skip_stages"], case["skip_reasons"] = list(reasons), reasons
    return case
