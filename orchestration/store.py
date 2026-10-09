"""Where workflow state and evidence live. Two implementations of one tiny interface.

MemoryStore: tests and library use. FileStore: the CLI and API (JSON files under out/).
Swap in a database by implementing the same four methods. Evidence is IMMUTABLE: a record_id, once written,
can only be written again with identical content.

Tenancy is enforced here too, not only in the orchestrator (D-016): every read takes an optional `org_id` and returns
nothing for another org's workflow or record, and a write that would reuse another org's record_id or workflow_id is
refused as a TenantConflict.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path


class EvidenceConflict(Exception):
    pass


class TenantConflict(EvidenceConflict):
    """A write would place one org's data under an id that already belongs to another org."""


class InvalidId(EvidenceConflict):
    """An id that is not a plain file name (e.g. '../x'): refused, so it can never address a file outside the store."""


def _org_of_record(record: dict) -> str | None:
    return (record.get("subject") or {}).get("org_id")


class MemoryStore:
    def __init__(self) -> None:
        self.workflows: dict[str, dict] = {}
        self.evidence: dict[str, dict] = {}

    # -- raw access (no tenancy); subclasses override these two
    def _read_workflow(self, workflow_id: str) -> dict | None:
        wf = self.workflows.get(workflow_id)
        return json.loads(json.dumps(wf)) if wf else None

    def _read_evidence(self, record_id: str) -> dict | None:
        return self.evidence.get(record_id)

    # -- tenant-scoped interface
    def load_workflow(self, workflow_id: str, org_id: str | None = None) -> dict | None:
        wf = self._read_workflow(workflow_id)
        return wf if wf and (org_id is None or wf["org_id"] == org_id) else None

    def save_workflow(self, wf: dict) -> None:
        existing = self._read_workflow(wf["workflow_id"])
        if existing and existing["org_id"] != wf["org_id"]:
            raise TenantConflict(f"workflow {wf['workflow_id']} belongs to another org")
        self._write_workflow(wf)

    def list_workflows(self, org_id: str | None = None) -> list[dict]:
        return [wf for wf in self._all_workflows() if org_id is None or wf["org_id"] == org_id]

    def get_evidence(self, record_id: str, org_id: str | None = None) -> dict | None:
        rec = self._read_evidence(record_id)
        return rec if rec and (org_id is None or _org_of_record(rec) == org_id) else None

    def put_evidence(self, record: dict) -> None:
        existing = self._read_evidence(record["record_id"])
        if existing and _org_of_record(existing) != _org_of_record(record):
            raise TenantConflict(f"{record['record_id']} already belongs to another org; refusing a cross-tenant write")
        if existing and existing["content_hash"] != record["content_hash"]:
            raise EvidenceConflict(f"{record['record_id']} already exists with different content; evidence is immutable")
        if not existing:
            self._write_evidence(record)

    # -- raw writes / listing
    def _write_workflow(self, wf: dict) -> None:
        self.workflows[wf["workflow_id"]] = json.loads(json.dumps(wf))

    def _write_evidence(self, record: dict) -> None:
        self.evidence[record["record_id"]] = record

    def _all_workflows(self) -> list[dict]:
        return [json.loads(json.dumps(wf)) for wf in self.workflows.values()]


class FileStore(MemoryStore):
    def __init__(self, root: str | Path | None = None) -> None:
        super().__init__()
        self.root = Path(root or os.environ.get("OUT_DIR", "out"))
        (self.root / "workflows").mkdir(parents=True, exist_ok=True)
        (self.root / "evidence").mkdir(parents=True, exist_ok=True)

    def _path(self, kind: str, ident: str) -> Path | None:
        """The file for one id, or None when the id is not a plain file name. Ids come from URLs: '..\\..\\pod' must not
        read pod.json (or any other .json on the disk) as if it were a workflow."""
        if not isinstance(ident, str) or not ident or any(c in ident for c in "/\\\0:") or ident.startswith("."):
            return None
        return self.root / kind / f"{ident}.json"

    def _safe_path(self, kind: str, ident: str) -> Path:
        p = self._path(kind, ident)
        if p is None:
            raise InvalidId(f"{ident!r} is not a valid {kind} id (no path separators, ':' or leading '.')")
        return p

    def _read_workflow(self, workflow_id: str) -> dict | None:
        p = self._path("workflows", workflow_id)
        return json.loads(p.read_text()) if p and p.exists() else None

    def _write_workflow(self, wf: dict) -> None:
        p = self._safe_path("workflows", wf["workflow_id"])
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(wf, indent=2))
        # atomic: a crash never leaves half a workflow. On Windows the replace is refused (WinError 5) while another
        # process (antivirus, search indexer) briefly holds the file it just saw written, so retry for up to ~2 s.
        for attempt in range(20):
            try:
                tmp.replace(p)
                return
            except PermissionError:
                if attempt == 19:
                    raise
                time.sleep(0.1)

    def _all_workflows(self) -> list[dict]:
        return [json.loads(p.read_text()) for p in sorted((self.root / "workflows").glob("*.json"))]

    def _read_evidence(self, record_id: str) -> dict | None:
        p = self._path("evidence", record_id)
        return json.loads(p.read_text()) if p and p.exists() else None

    def _write_evidence(self, record: dict) -> None:
        self._safe_path("evidence", record["record_id"]).write_text(json.dumps(record, indent=2))
