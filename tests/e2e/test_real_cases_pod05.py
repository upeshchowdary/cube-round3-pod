"""End-to-end tests for Pod 05 real input cases from data/input/my_cases.json.
Validates integrated Receiving, Returns, and Recovery agents.
"""
import json
from pathlib import Path

from orchestration.orchestrator import run_workflow, load_flow, default_flow_path, flow_stages
from orchestration.store import MemoryStore
from shared.utils.schema import errors

ROOT = Path(__file__).resolve().parents[2]
CASES_FILE = ROOT / "data" / "input" / "my_cases.json"


def test_real_cases_file_exists_and_valid():
    assert CASES_FILE.exists(), "data/input/my_cases.json must exist"
    cases = json.loads(CASES_FILE.read_text())
    assert len(cases) == 6, "Expected 6 real test cases"
    for case in cases:
        assert "org_id" in case
        assert "unit_id" in case
        assert "route" in case
        assert "returned" in case


def test_run_all_real_cases_through_orchestration():
    cases = json.loads(CASES_FILE.read_text())
    flow = load_flow(default_flow_path())
    stages = flow_stages(flow)
    assert "receiving" in stages
    assert "returns" in stages
    assert "recovery" in stages

    store = MemoryStore()

    for idx, case in enumerate(cases):
        wf = run_workflow(case, flow, store=store)

        # 1. Workflow state schema validation
        errs = errors("workflow-state", wf)
        assert errs == [], f"Workflow schema errors in case {case['unit_id']}: {errs}"

        # 2. Status reached terminal or active state
        assert wf["status"] in ("COMPLETED", "FAILED", "BLOCKED", "RECOVERY_REQUIRED")

        # 3. Final outcome assertions
        fo = wf["final_outcome"]
        assert fo is not None
        assert fo["outcome"] in ("CLEAN", "CLAIM_RECOMMENDED", "EXCEPTION", "NEEDS_REVIEW", "INCOMPLETE")
        assert fo["contributing_records"]

        # 4. Evidence records validation
        for rec_id in wf["evidence_references"]:
            rec = store.get_evidence(rec_id)
            assert rec is not None
            assert errors("evidence", rec) == [], f"Invalid evidence {rec_id}"
            assert "content_hash" in rec and len(rec["content_hash"]) == 64

        # 5. Returns manager validation (all cases in my_cases have returned=True)
        if case.get("returned"):
            returns_stage = next((s for s in wf["stage_results"] if s["stage"] == "returns"), None)
            assert returns_stage is not None, f"Returns stage missing for {case['unit_id']}"
            assert returns_stage["state"] == "completed"
            returns_rec = store.get_evidence(returns_stage["record_id"])
            assert returns_rec["agent_id"] == "returns-manager-rtn0045@2"
            payload = returns_rec["payload"]
            assert "recommended_disposition" in payload or "disposition" in payload
            assert returns_rec["decision"]["verdict"] in ("PASS", "FAIL", "UNCERTAIN")

        # 6. Recovery manager validation
        recovery_stage = next((s for s in wf["stage_results"] if s["stage"] == "recovery"), None)
        assert recovery_stage is not None, f"Recovery stage missing for {case['unit_id']}"
        assert recovery_stage["state"] == "completed"
        recovery_rec = store.get_evidence(recovery_stage["record_id"])
        assert recovery_rec["agent_id"] == "recovery-vishruth@1"
        assert "charges" in recovery_rec["payload"]


def test_finding_f11_contradiction_on_real_data():
    """Verify that Finding F-11 correctly disputes refund charges when unit was returned and passed/restocked."""
    from agents.recovery.app import position

    # 1. Test position() directly on a simulated fee line with positive amount
    mock_request = {
        "subject": {"org_id": "org_demo_alpha", "subject_id": "UNIT-0014"},
        "previous_evidence": [
            {
                "kind": "evidence_record",
                "stage": "returns",
                "record_id": "RTN-UNIT-0014",
                "status": "completed",
                "decision": {"verdict": "PASS", "outcome": "restock"},
                "payload": {"recommended_disposition": "restock"},
            }
        ],
    }
    pos_fee = {
        "line_id": "FEE-0014-4",
        "charge_type": "refund_issued_item_not_returned",
        "amount_usd": 15.50,
    }
    pos, why, ids = position(pos_fee, mock_request)
    assert pos == "CONTRADICTS"
    assert "finding f-11" in why.lower()
    assert "RTN-UNIT-0014" in ids

    # 2. Test that across real sample cases, $0.00 refund charges are safely guarded by Finding F-09
    cases = json.loads(CASES_FILE.read_text())
    flow = load_flow(default_flow_path())
    store = MemoryStore()

    for case in cases:
        wf = run_workflow(case, flow, store=store)
        recovery_stage = next((s for s in wf["stage_results"] if s["stage"] == "recovery"), None)
        if not recovery_stage:
            continue
        rec = store.get_evidence(recovery_stage["record_id"])
        charges = rec["payload"].get("charges", [])

        for c in charges:
            if c.get("charge_type") == "refund_issued_item_not_returned":
                assert c["position"] == "SILENT"
                assert "finding" in c["reason"].lower()

