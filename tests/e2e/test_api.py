"""The orchestrator's HTTP front door (what the UI uses): tenancy at the door, listing, and override-then-resume."""
import pytest
from fastapi.testclient import TestClient

from orchestration import api
from orchestration.store import FileStore


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "STORE", FileStore(tmp_path))
    return TestClient(api.app)


def test_unknown_or_wrong_tenant_subject_is_refused_and_nothing_is_stored(client):
    # UNIT-0014 exists only under org_demo_alpha.
    assert client.post("/workflows", json={"org_id": "org_demo_bravo", "unit_id": "UNIT-0014"}).status_code == 404
    assert client.post("/workflows", json={"org_id": "org_demo_alpha", "unit_id": "UNIT-9999"}).status_code == 404
    assert client.post("/workflows", json={"org_id": "org_demo_alpha"}).status_code == 422
    assert client.get("/workflows").json() == []


def test_run_then_list_and_filter_by_org(client):
    wf = client.post("/workflows", json={"org_id": "org_demo_alpha", "unit_id": "UNIT-0014", "route": "fba", "returned": True}).json()
    assert wf["status"] == "COMPLETED" and wf["final_outcome"]["outcome"] == "CLAIM_RECOMMENDED"
    assert [w["workflow_id"] for w in client.get("/workflows").json()] == [wf["workflow_id"]]
    assert client.get("/workflows", params={"org_id": "org_demo_bravo"}).json() == []
    ev = client.get(f"/workflows/{wf['workflow_id']}/evidence").json()["evidence"]
    assert set(ev) == set(wf["evidence_references"])


def test_uncertain_reaches_a_person_and_is_resolved_by_an_override(client):
    """Returns cannot verify UNIT-0092's identity -> BLOCKED for a person (synthetic cassette scenario: blurred photo).
    The person's override is recorded against the evidence, Recovery is re-run with it, and the workflow completes."""
    wf = client.post("/workflows", json={"org_id": "org_demo_alpha", "unit_id": "UNIT-0092", "route": "fba", "returned": True}).json()
    assert wf["status"] == "BLOCKED"
    rtn = next(s for s in wf["stage_results"] if s["stage"] == "returns")
    assert rtn["verdict"] == "UNCERTAIN" and rtn["needs_human"]

    wf_id = wf["workflow_id"]
    over = client.post(f"/workflows/{wf_id}/overrides", json={
        "record_id": rtn["record_id"], "new_verdict": "PASS", "new_outcome": "restock",
        "actor": "returns-lead", "reason": "re-photographed: label matches SKU-SERUM-30"}).json()
    assert over["overrides"][-1]["supersedes"]["record_id"] == rtn["record_id"]
    done = client.post(f"/workflows/{wf_id}/resume").json()
    assert done["status"] == "COMPLETED", done["status_reason"]
    assert rtn["record_id"] in done["evidence_references"], "the original UNCERTAIN record is kept"
    assert sum(t["event"] == "stage_stale" and t["stage"] == "recovery" for t in done["transitions"]) == 1


def test_hand_authored_cassettes_are_never_labelled_as_a_model_run(client):
    wf = client.post("/workflows", json={"org_id": "org_demo_alpha", "unit_id": "UNIT-0014", "route": "fba", "returned": True}).json()
    rid = next(s["record_id"] for s in wf["stage_results"] if s["stage"] == "returns")
    rec = client.get(f"/workflows/{wf['workflow_id']}/evidence").json()["evidence"][rid]
    assert rec["model"]["name"].startswith("synthetic-cassette") and rec["model"]["calls"] == 0
    assert rec["payload"]["cassette_provenance"] == "synthetic"
