"""Read the synthetic Round 2 sample CSVs (used by the organiser stub agents and the tests).

Your real agent will not read these. It reads captures and upstream records.
Tenancy: every lookup is scoped by org_id. A unit that exists only under another org
raises LookupError, which the server turns into a 404 (never a cross-tenant answer).
"""
from __future__ import annotations

import csv
import os
from functools import lru_cache
from pathlib import Path

DEFAULT_DIR = Path(__file__).resolve().parents[2] / "data" / "sample"
FILES = {
    "receiving": "receiving_sample.csv",
    "prep": "prep_sample.csv",
    "pack": "pack_sample.csv",
    "returns": "returns_sample.csv",
    "fees": "fee_report_sample.csv",
}


def data_dir() -> Path:
    return Path(os.environ.get("DATA_DIR", DEFAULT_DIR))


@lru_cache(maxsize=64)
def _rows(kind: str, directory: str, mtime_ns: int, size: int) -> tuple[dict, ...]:
    with open(Path(directory) / FILES[kind], newline="", encoding="utf-8") as fh:
        return tuple(csv.DictReader(fh))


def rows(kind: str) -> tuple[dict, ...]:
    # Keyed on the file's mtime and size too, so an edited CSV is re-read (a running API used to serve the old rows).
    st = (data_dir() / FILES[kind]).stat()
    return _rows(kind, str(data_dir()), st.st_mtime_ns, st.st_size)


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
