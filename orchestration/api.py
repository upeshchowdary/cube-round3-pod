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
from pathlib import Path
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
    """The Pod's own cases (data/input/my_cases.json) first, then the organiser sample cases."""
    out, seen = [], set()
    for path in (ROOT / "data" / "input" / "my_cases.json", ROOT / "data" / "sample" / "cases.json"):
        if path.exists():
            for case in json.loads(path.read_text()):
                key = (case["org_id"], case["unit_id"])
                if key not in seen:
                    seen.add(key)
                    out.append({**case, "source": "pod" if path.parent.name == "input" else "sample"})
    return out


@app.get("/workflows")
def list_workflows(org_id: str | None = None) -> list[dict]:
    """Every stored workflow (optionally one org's), newest first."""
    wfs = [w for w in STORE.list_workflows() if not org_id or w["org_id"] == org_id]
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
    if any(sample_data.has(kind, subject, org) for kind in sample_data.FILES):
        return True
    return any(c["org_id"] == org and c["unit_id"] == subject for c in list_cases())


@app.post("/workflows")
def create(body: dict) -> dict:
    org, subject = body.get("org_id"), body.get("subject_id") or body.get("unit_id")
    if not org or not subject:
        raise HTTPException(422, "org_id and unit_id (or subject_id) are required")
    if not _known(org, subject):
        # Tenancy at the front door: a subject that does not exist under this org is refused, and no workflow is created.
        raise HTTPException(404, f"unknown subject {subject} in {org}")
    case = {"org_id": org, "unit_id": subject, "route": body.get("route") or sample_data.route(subject, org),
            "returned": body.get("returned", sample_data.has("returns", subject, org))}
    return run_workflow(case, load_flow(FLOW), STORE)


def _get(workflow_id: str) -> dict:
    wf = STORE.load_workflow(workflow_id)
    if wf is None:
        raise HTTPException(404, f"no workflow {workflow_id}")
    return wf


@app.get("/workflows/{workflow_id}")
def get(workflow_id: str) -> dict:
    return _get(workflow_id)


@app.get("/workflows/{workflow_id}/evidence")
def evidence(workflow_id: str) -> dict:
    return bundle(_get(workflow_id), STORE)


@app.post("/workflows/{workflow_id}/resume")
def resume_workflow(workflow_id: str) -> dict:
    _get(workflow_id)
    return resume(workflow_id, load_flow(FLOW), STORE)


@app.post("/workflows/{workflow_id}/overrides")
def override(workflow_id: str, body: dict) -> dict:
    _get(workflow_id)
    try:
        return apply_override(workflow_id, STORE, record_id=body.get("record_id", ""), new_verdict=body.get("new_verdict", ""),
                              actor=body.get("actor", ""), reason=body.get("reason", ""), new_outcome=body.get("new_outcome"))
    except (ValueError, EvidenceConflict) as exc:
        raise HTTPException(422, str(exc)) from exc
