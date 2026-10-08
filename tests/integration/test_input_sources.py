"""Each agent really reads its own input files, and what it reads reaches the agents after it.

The stage-to-stage hand-off is covered elsewhere (previous_evidence). These tests cover the inputs that are NOT handed
over by another agent: the sample CSVs under DATA_DIR (PO lines, prep observations, box contents, the fee report) and
the captures under INPUT_DIR. Each test changes one value in a copy of those files and checks that the agent's
evidence, and where it matters the downstream agent and the final outcome, change with it.
"""
import csv
import hashlib
import shutil
from pathlib import Path

import pytest

from orchestration.orchestrator import run_workflow
from orchestration.store import MemoryStore

ROOT = Path(__file__).resolve().parents[2]
FBA_RETURNED = {"org_id": "org_demo_alpha", "unit_id": "UNIT-0014", "route": "fba", "returned": True}
MFN_RETURNED = {"org_id": "org_demo_alpha", "unit_id": "UNIT-0016", "route": "mfn", "returned": True}


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    """A private copy of data/sample/ that a test may edit."""
    d = tmp_path / "sample"
    shutil.copytree(ROOT / "data" / "sample", d)
    monkeypatch.setenv("DATA_DIR", str(d))
    return d


@pytest.fixture()
def input_dir(tmp_path, monkeypatch):
    """A private copy of data/input/ (the captures) that a test may edit."""
    d = tmp_path / "input"
    shutil.copytree(ROOT / "data" / "input", d)
    monkeypatch.setenv("INPUT_DIR", str(d))
    return d


def edit_row(path: Path, record_id: str, **changes) -> None:
    with path.open(newline="") as fh:
        rows = list(csv.DictReader(fh))
    hit = [r for r in rows if r.get("record_id") == record_id or r.get("line_id") == record_id]
    assert hit, f"{record_id} not in {path.name}"
    for r in hit:
        r.update(changes)
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def run(case: dict) -> tuple[dict, dict]:
    store = MemoryStore()
    wf = run_workflow(case, store=store)
    by_stage = {sr["stage"]: store.get_evidence(sr["record_id"]) for sr in wf["stage_results"] if sr["record_id"]}
    return wf, by_stage


def check_of(record: dict, key: str) -> dict:
    return next(c for c in record["checks"] if c["check_key"] == key)


def test_receiving_reads_the_po_line_and_counts(data_dir):
    _, ev = run(FBA_RETURNED)
    assert ev["receiving"]["payload"]["qty_received"] == 24
    assert ev["receiving"]["decision"]["verdict"] == "PASS"

    edit_row(data_dir / "receiving_sample.csv", "RCV-0014", qty_received="20", units_per_carton_counted="10")
    _, ev = run(FBA_RETURNED)
    rec = ev["receiving"]
    assert rec["payload"]["qty_received"] == 20
    assert rec["payload"]["shortfall_units"] == 4
    assert rec["decision"]["verdict"] != "PASS"


def test_prep_reads_its_observations_and_recovery_follows(data_dir):
    wf, ev = run(FBA_RETURNED)
    assert ev["prep"]["decision"]["verdict"] == "PASS"
    assert wf["final_outcome"]["outcome"] == "CLAIM_RECOMMENDED"  # Prep says compliant: the defect fee is disputed

    edit_row(data_dir / "prep_sample.csv", "PRP-0014", fnsku_label_placement="on_seam")
    wf, ev = run(FBA_RETURNED)
    assert check_of(ev["prep"], "fnsku_label_placement")["verdict"] == "FAIL"
    assert ev["prep"]["decision"]["verdict"] == "FAIL"
    # Recovery now reads a Prep FAIL from previous_evidence: the inbound-defect fee is supported, not claimed.
    charge = next(c for c in ev["recovery"]["payload"]["charges"] if c["charge_type"] == "inbound_defect_fee")
    assert charge["position"] == "SUPPORTS"
    assert ev["prep"]["record_id"] in charge["evidence_record_ids"]
    assert ev["recovery"]["payload"]["claimable_usd"] == 0


def test_pack_reads_the_box_contents(data_dir):
    _, ev = run(MFN_RETURNED)
    assert ev["pack"]["decision"]["outcome"] == "seal"

    edit_row(data_dir / "pack_sample.csv", "PCK-0016", observed_in_box="SKU-TOWEL-BLU:1")
    _, ev = run(MFN_RETURNED)
    assert ev["pack"]["decision"]["outcome"] == "stop_and_fix"
    assert check_of(ev["pack"], "quantities_correct")["verdict"] == "FAIL"


def test_recovery_reads_the_fee_report(data_dir):
    wf, ev = run(FBA_RETURNED)
    assert ev["recovery"]["payload"]["claimable_usd"] == 2.0

    edit_row(data_dir / "fee_report_sample.csv", "FEE-0014-1", amount_usd="3.50")
    wf, ev = run(FBA_RETURNED)
    assert ev["recovery"]["payload"]["claimable_usd"] == 3.5
    assert wf["final_outcome"]["claimable_usd"] == 3.5


def test_returns_hashes_the_capture_bytes_it_was_given(input_dir):
    _, ev = run(FBA_RETURNED)
    folder = input_dir / "UNIT-0014" / "returns"
    on_disk = {f"UNIT-0014/returns/{p.name}": hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir()}
    recorded = {i["ref"]: i["sha256"] for i in ev["returns"]["inputs"]}
    assert recorded and recorded.items() <= on_disk.items()


def test_returns_without_captures_fails_open(input_dir):
    shutil.rmtree(input_dir / "UNIT-0014" / "returns")
    wf, ev = run(FBA_RETURNED)
    assert ev["returns"]["status"] != "completed"
    assert ev["returns"]["decision"]["verdict"] == "UNCERTAIN"
    assert ev["returns"]["error"]["code"] == "no_reference_photo"
    assert wf["status"] in ("FAILED", "BLOCKED", "RECOVERY_REQUIRED")  # recorded, never turned into success
