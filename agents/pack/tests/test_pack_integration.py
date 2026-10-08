"""Integration tests for Pack Manager."""
import pytest

from agents.pack.app import handle
from orchestration.clients import client_for, AgentRejected
from shared.utils.hashing import verify
from shared.utils.schema import errors


def make_pack_request(unit_id: str, org_id: str, inputs=None, previous=None):
    wf = f"WF-{org_id}-{unit_id}"
    return {
        "schema_version": "1.0",
        "request_id": f"{wf}:pack",
        "workflow_id": wf,
        "stage": "pack",
        "subject": {"org_id": org_id, "subject_id": unit_id, "route": "mfn"},
        "inputs": inputs or [],
        "previous_evidence": previous or [],
        "context": {"overrides": []},
    }


def test_pack_contract_and_hash_validity():
    req = make_pack_request("UNIT-0006", "org_demo_bravo")
    out = handle(req)

    assert errors("agent-output", out) == []
    ev = out["evidence"]
    assert errors("evidence", ev) == []
    assert ev["record_id"].startswith("PCK-")
    assert ev["stage"] == "pack"
    assert ev["agent_id"] == "pack-manager-nikhil@2.0.0"
    assert verify(ev) is True
    assert out["verdict"] in ("PASS", "FAIL", "UNCERTAIN")
    assert len(ev["checks"]) == 3
    keys = {c["check_key"] for c in ev["checks"]}
    assert keys == {"items_present", "quantities_correct", "no_extra_items"}


def test_pack_multi_tenant_isolation():
    # UNIT-0006 belongs to org_demo_bravo, requesting under org_demo_alpha must fail
    req_wrong_tenant = make_pack_request("UNIT-0006", "org_demo_alpha")
    with pytest.raises(LookupError):
        handle(req_wrong_tenant)


def test_pack_idempotency():
    req = make_pack_request("UNIT-0009", "org_demo_bravo")
    out1 = handle(req)
    out2 = handle(req)
    assert out1["evidence"]["record_id"] == out2["evidence"]["record_id"]
    # produced_at (second resolution) and the measured latency_ms change from call to call, and both are in the
    # content hash; everything else (checks, decision, inputs, payload) must be identical.
    per_call = ("produced_at", "latency_ms", "content_hash")
    same = lambda ev: {k: v for k, v in ev.items() if k not in per_call}  # noqa: E731
    assert same(out1["evidence"]) == same(out2["evidence"])


def test_pack_traces_upstream_evidence():
    fake_rcv = {
        "record_id": "RCV-0006",
        "stage": "receiving",
        "decision": {"verdict": "PASS"},
    }
    req = make_pack_request("UNIT-0006", "org_demo_bravo", previous=[fake_rcv])
    out = handle(req)
    assert "RCV-0006" in out["evidence"]["upstream_refs"]


def test_pack_stop_and_fix_on_discrepancy():
    # UNIT-0027 in sample data has extra item (observed SKU-CABLE-USBC not on order)
    req = make_pack_request("UNIT-0027", "org_demo_bravo")
    out = handle(req)
    assert out["verdict"] == "FAIL"
    assert out["evidence"]["decision"]["outcome"] == "stop_and_fix"
    no_extra_check = next(c for c in out["evidence"]["checks"] if c["check_key"] == "no_extra_items")
    assert no_extra_check["verdict"] == "FAIL"


def test_pack_replay_fixture_uncertain_occlusion():
    # Fixture 1.d is pre-recorded as severe occlusion
    req = make_pack_request("FIX-1.d", "org_demo_alpha")
    out = handle(req)
    assert out["verdict"] == "UNCERTAIN"
    assert out["evidence"]["decision"]["outcome"] == "pending_review"
    for c in out["evidence"]["checks"]:
        assert c["verdict"] == "UNCERTAIN"
        assert c.get("uncertain_reason") is not None

