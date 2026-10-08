"""Tenancy is enforced in storage too, not only by the orchestrator and the agents (D-016)."""
import copy

import pytest
from fastapi.testclient import TestClient

from orchestration import api
from orchestration.orchestrator import load_flow, run_workflow
from orchestration.store import FileStore, MemoryStore, TenantConflict
from tests.helpers import Fake

CASE = {"org_id": "org_demo_alpha", "unit_id": "UNIT-0014", "route": "fba", "returned": True}


def fakes():
    return {s: Fake("PASS") for s in ("receiving", "prep", "pack", "returns", "recovery")}


@pytest.mark.parametrize("make_store", [MemoryStore, FileStore], ids=["memory", "file"])
def test_reads_are_scoped_to_the_org(make_store, tmp_path):
    store = make_store(tmp_path) if make_store is FileStore else make_store()
    wf = run_workflow(CASE, load_flow(), store, fakes())
    rid = wf["evidence_references"][0]
    assert store.load_workflow(wf["workflow_id"], "org_demo_alpha")["workflow_id"] == wf["workflow_id"]
    assert store.load_workflow(wf["workflow_id"], "org_demo_bravo") is None
    assert store.get_evidence(rid, "org_demo_alpha")["record_id"] == rid
    assert store.get_evidence(rid, "org_demo_bravo") is None
    assert store.list_workflows("org_demo_bravo") == []


@pytest.mark.parametrize("make_store", [MemoryStore, FileStore], ids=["memory", "file"])
def test_a_write_cannot_reuse_another_orgs_ids(make_store, tmp_path):
    store = make_store(tmp_path) if make_store is FileStore else make_store()
    wf = run_workflow(CASE, load_flow(), store, fakes())
    rec = copy.deepcopy(store.get_evidence(wf["evidence_references"][0]))
    rec["subject"]["org_id"] = "org_demo_bravo"
    with pytest.raises(TenantConflict):
        store.put_evidence(rec)
    with pytest.raises(TenantConflict):
        store.save_workflow({**wf, "org_id": "org_demo_bravo"})
    assert store.get_evidence(rec["record_id"])["subject"]["org_id"] == "org_demo_alpha", "the original is untouched"


def test_an_agent_reusing_another_orgs_record_id_is_recorded_as_tenant_mismatch():
    """The fake agents name records by stage only (e.g. RCV-receiving), so a second org's run reuses org_demo_alpha's
    record ids. Storage refuses the cross-tenant write; the stage is a recorded error, never a success."""
    store = MemoryStore()
    run_workflow(CASE, load_flow(), store, fakes())
    wf = run_workflow({**CASE, "org_id": "org_demo_bravo"}, load_flow(), store, fakes())
    rcv = next(s for s in wf["stage_results"] if s["stage"] == "receiving")
    assert rcv["state"] == "error" and rcv["error"]["code"] == "tenant_mismatch"
    assert wf["status"] == "FAILED"
    assert store.get_evidence("RCV-receiving")["subject"]["org_id"] == "org_demo_alpha"


def test_api_hides_another_orgs_workflow(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "STORE", FileStore(tmp_path))
    client = TestClient(api.app)
    wf = client.post("/workflows", json={"org_id": "org_demo_alpha", "unit_id": "UNIT-0016", "route": "mfn", "returned": True}).json()
    wid = wf["workflow_id"]
    assert client.get(f"/workflows/{wid}", params={"org_id": "org_demo_alpha"}).status_code == 200
    assert client.get(f"/workflows/{wid}", params={"org_id": "org_demo_bravo"}).status_code == 404
    assert client.get(f"/workflows/{wid}/evidence", params={"org_id": "org_demo_bravo"}).status_code == 404
    assert client.post(f"/workflows/{wid}/resume", params={"org_id": "org_demo_bravo"}).status_code == 404
