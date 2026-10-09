"""Optional HTTP front door for the orchestrator (useful for a deployed demo).

  uvicorn orchestration.api:app --port 8100
  POST /workflows                 {"org_id": "org_demo_alpha", "unit_id": "UNIT-0002"}   -> Workflow State (runs it); 404 if unknown in that org
  GET  /workflows[?org_id=]       -> stored workflows, newest first
  GET  /workflows/{id}            -> Workflow State
  GET  /workflows/{id}/evidence   -> the workflow plus all its evidence records
  POST /workflows/{id}/resume     -> continue after a halt / decision / failure
  POST /workflows/{id}/overrides  {"record_id": "...", "new_verdict": "PASS", "actor": "...", "reason": "..."}
  GET  /health                    -> orchestrator and every agent in the flow
No authentication is included. Add it before you deploy anywhere public.
"""
from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import json

from shared.utils import sample_data

from .clients import HttpClient, client_for, load_manifest
from .orchestrator import ROOT, apply_override, bundle, default_flow_path, flow_stages, load_flow, resume, run_workflow
from .store import EvidenceConflict, FileStore

app = FastAPI(title="CUBE Round 3 orchestrator")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
FLOW = os.environ.get("ORCH_FLOW") or default_flow_path()
STORE = FileStore()


@app.get("/cases")
def list_cases() -> list[dict]:
    """The Pod's own cases (data/input/my_cases.json, then the real-photo units in returns_photo_cases.json) first, then
    the dataset's cases.json.

    With DATA_DIR pointing at a loaded dataset (scripts/dev.py dataset), only that dataset's cases are listed: the Pod's
    demo units are not in it. A real-photo unit is listed only once its photos are there (scripts/fetch_photos.py).
    """
    out, seen = [], set()
    paths = [sample_data.data_dir() / "cases.json"]
    photo_cases = ROOT / "data" / "input" / "returns_photo_cases.json"
    if sample_data.data_dir().resolve() == sample_data.DEFAULT_DIR.resolve():
        paths[:0] = [ROOT / "data" / "input" / "my_cases.json", photo_cases]
    for path in paths:
        if path.exists():
            for case in json.loads(path.read_text()):
                key = (case["org_id"], case["unit_id"])
                if path == photo_cases and not any((ROOT / "data" / "input" / case["unit_id"]).rglob("*.jpg")):
                    continue
                if key not in seen:
                    seen.add(key)
                    out.append({**case, "source": "pod" if path.parent.name == "input" else "sample"})
    return out


@app.get("/workflows")
def list_workflows(org_id: str | None = None) -> list[dict]:
    """Every stored workflow (optionally one org's), newest first."""
    wfs = STORE.list_workflows(org_id)
    return sorted(wfs, key=lambda w: w["timestamps"]["updated_at"], reverse=True)


@app.get("/health")
def health() -> dict:
    agents = {}
    for stage in flow_stages(load_flow(FLOW)):
        manifest = load_manifest(stage)
        info = {k: manifest.get(k) for k in ("agent_id", "owner", "implementation")}
        client = client_for(stage)
        try:
            if isinstance(client, HttpClient):
                state = client.health()
            elif getattr(client, "load_error", None):
                state = {"status": "down", "mode": "inproc", "error": client.load_error[:200]}
            else:
                state = {"status": "ok", "mode": "inproc"}
            agents[stage] = {**info, **state}
        except Exception as exc:
            agents[stage] = {**info, "status": "down", "mode": "http", "error": str(exc)[:200]}
    ok = all(a["status"] == "ok" for a in agents.values())
    return {"status": "ok" if ok else "degraded", "flow": load_flow(FLOW)["flow_id"], "agents": agents}


def _known(org: str, subject: str) -> bool:
    """A subject exists for an org when any stage's data has it, or the Pod's / organiser's cases list it."""
    if sample_data.known(subject, org):
        return True
    return any(c["org_id"] == org and c["unit_id"] == subject for c in list_cases())


@app.post("/workflows")
def create(body: dict) -> dict:
    org, subject = body.get("org_id"), body.get("subject_id") or body.get("unit_id")
    if not org or not subject:
        raise HTTPException(422, "org_id and unit_id (or subject_id) are required")
    try:
        if not _known(org, subject):
            # Tenancy at the front door: a subject that does not exist under this org is refused, and no workflow is created.
            raise HTTPException(404, f"unknown subject {subject} in {org}")
        case = sample_data.case_for(subject, org, route_hint=body.get("route"), returned=body.get("returned"))
    except sample_data.DatasetError as exc:  # a dataset file lacks a column an agent needs: say which, run nothing
        raise HTTPException(422, str(exc)) from exc
    return run_workflow(case, load_flow(FLOW), STORE)


@app.get("/recovery/charges")
def recovery_charges(org_id: str | None = None) -> list[dict]:
    """Every fee line judged by each workflow's current Recovery record, in one call (the Recovery page used to fetch
    every workflow's evidence bundle, about 100 requests, and repeat that on each 15-second refresh)."""
    out = []
    for wf in STORE.list_workflows(org_id):
        sr = next((s for s in wf["stage_results"] if s["stage"] == "recovery" and s["state"] == "completed"), None)
        rec = STORE.get_evidence(sr["record_id"], wf["org_id"]) if sr and sr.get("record_id") else None
        if rec:
            out.append({"workflow_id": wf["workflow_id"], "record_id": rec["record_id"],
                        "reason": rec["decision"].get("reason"), "charges": (rec.get("payload") or {}).get("charges", [])})
    return out


def _get(workflow_id: str, org_id: str | None = None) -> dict:
    """With ?org_id=, another org's workflow is answered exactly like a missing one (404), never returned."""
    wf = STORE.load_workflow(workflow_id, org_id)
    if wf is None:
        raise HTTPException(404, f"no workflow {workflow_id}")
    return wf


@app.get("/workflows/{workflow_id}")
def get(workflow_id: str, org_id: str | None = None) -> dict:
    return _get(workflow_id, org_id)


@app.get("/workflows/{workflow_id}/evidence")
def evidence(workflow_id: str, org_id: str | None = None) -> dict:
    return bundle(_get(workflow_id, org_id), STORE)


@app.post("/workflows/{workflow_id}/resume")
def resume_workflow(workflow_id: str, org_id: str | None = None) -> dict:
    _get(workflow_id, org_id)
    return resume(workflow_id, load_flow(FLOW), STORE)


@app.post("/workflows/{workflow_id}/overrides")
def override(workflow_id: str, body: dict, org_id: str | None = None) -> dict:
    _get(workflow_id, org_id)
    try:
        return apply_override(workflow_id, STORE, record_id=body.get("record_id", ""), new_verdict=body.get("new_verdict", ""),
                              actor=body.get("actor", ""), reason=body.get("reason", ""), new_outcome=body.get("new_outcome"))
    except (ValueError, EvidenceConflict) as exc:
        raise HTTPException(422, str(exc)) from exc
