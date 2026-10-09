"""Run one product typed into the UI's Live Run page through the Pod's real agents, with AI on the photos.

  python -m orchestration.live_run out/live/<run_id>

The API (orchestration/live_demo.py) has already written the run folder:

  spec.json             what was typed in (no photo data)
  data/*.csv            one row per agent file, in the Round 2 format every agent reads (DATA_DIR)
  input/<unit>/<stage>/ the uploaded photos (INPUT_DIR)

This process runs the workflow with the orchestrator into <run>/out (workflows/, evidence/), which the page polls: the
workflow is saved after every stage. It runs in its own process so DATA_DIR / INPUT_DIR / keys never touch the API
serving the dashboard.

AI: Receiving (Gemini) looks at the receiving photos when there are any, Pack (Groq) at the open-box photo, Returns
(Gemini) at the returned item against the reference photo it takes from Pack or Receiving. When a model call fails
because a key hit its limit or is not accepted, the next key from GEMINI_API_KEYS / GROQ_API_KEYS is put in place and the
workflow is resumed: the orchestrator re-runs the failed stage, and Returns / Recovery re-run on the new upstream record.
Every switch is written to status.json (key numbers only, never a key).
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import traceback
from pathlib import Path

# Things a different key (or a second try) can fix: rate limit / quota, a key that is not accepted, an overloaded or
# slow model (gemini-3-flash-preview answered the same Returns request in 2.5 min once and timed out after 6 min once).
KEY_PROBLEM = re.compile(r"\b429\b|RESOURCE_EXHAUSTED|rate.?limit|quota|exhausted|\b40[13]\b|UNAUTHENTICATED|"
                         r"PERMISSION_DENIED|API.?key|\b503\b|UNAVAILABLE|overloaded|timeout|timed out|deadline|"
                         r"schema_error",  # a malformed model answer (after Round 2's own repair turn): a fresh try usually passes
                         re.IGNORECASE)
PROVIDER = {"receiving": "gemini", "returns": "gemini", "pack": "groq"}
MAX_SWITCHES = 12


class Keys:
    """The keys for one provider, in order: the single-key variable first, then the list."""

    def __init__(self, name: str, single: str, many: str):
        # The list first: the single key is the one the rest of the project spends, so it is the likeliest to be used up.
        seen, self.keys = set(), []
        for k in os.environ.get(many, "").split(",") + [os.environ.get(single, "")]:
            k = k.strip()
            if k and k not in seen:
                seen.add(k)
                self.keys.append(k)
        self.name, self.single, self.i = name, single, 0
        if self.keys:
            os.environ[single] = self.keys[0]

    def advance(self) -> bool:
        if self.i + 1 >= len(self.keys):
            return False
        self.i += 1
        os.environ[self.single] = self.keys[self.i]
        return True


def _status(run: Path, **fields) -> None:
    path = run / "status.json"
    data = json.loads(path.read_text()) if path.exists() else {}
    data.update(fields)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    for _ in range(20):  # Windows: the API may be reading the file at this moment
        try:
            tmp.replace(path)
            return
        except PermissionError:
            time.sleep(0.05)


def _note(run: Path, text: str) -> None:
    notes = json.loads((run / "status.json").read_text()).get("notes", [])
    _status(run, notes=notes + [{"at": time.strftime("%H:%M:%S"), "text": text}])


def main(run_dir: str) -> int:
    run = Path(run_dir).resolve()
    spec = json.loads((run / "spec.json").read_text())
    unit, org = spec["unit_id"], spec["org_id"]

    # Before any orchestration import: the agents read these per call; the .env loader never overrides them.
    os.environ.update({
        "DATA_DIR": str(run / "data"), "INPUT_DIR": str(run / "input"), "OUT_DIR": str(run / "out"),
        "RETURNS_MODEL_MODE": "live", "RECOVERY_MODEL_MODE": "rules", "LOG_LEVEL": os.environ.get("LOG_LEVEL", "WARNING"),
        "RECEIVING_MODEL_MODE": "live" if spec.get("ai", {}).get("receiving") else "replay",
    })
    # Returns (Round 2 settings) tuned for a demo someone is watching: the second-opinion step thinks "medium" instead
    # of "high", and crops go at "high" instead of "ultra_high" (about 7 min -> 2.5 min on the same photos, same verdict).
    # The 180 s per-call timeout stays: gemini-3-flash-preview sometimes needs more than 90 s for one judgment call.
    for name, value in (("RM_ESCALATION_THINKING", "medium"), ("RM_CROP_RESOLUTION", "high")):
        os.environ.setdefault(name, value)
    import shared  # noqa: F401  (loads .env: keys and model names, never overriding what is set above)

    gemini = Keys("Gemini", "GEMINI_API_KEY", "GEMINI_API_KEYS")
    groq = Keys("Groq", "GROQ_API_KEY", "GROQ_API_KEYS")
    # gemini-3.8-flash (the model Returns was built on in Round 2): the same DualSense Returns judgment took 55 s and was
    # right, where gemini-3-flash-preview took 2.5 to 6 min or timed out. LIVE_GEMINI_MODEL picks another one.
    live_model = os.environ.get("LIVE_GEMINI_MODEL") or "gemini-3.8-flash"
    os.environ["RETURNS_LIVE_MODEL"] = os.environ["RECEIVING_MODEL"] = live_model
    if not spec.get("ai", {}).get("pack"):
        os.environ["GROQ_API_KEY"] = os.environ["OPENROUTER_API_KEY"] = ""  # no photo: Pack replays the typed box contents

    from orchestration.orchestrator import load_flow, resume, run_workflow, workflow_id_for
    from orchestration.store import FileStore
    from shared.utils import sample_data

    _status(run, state="running", started_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), notes=[],
            keys={"gemini": len(gemini.keys), "groq": len(groq.keys)})
    try:
        case = sample_data.case_for(unit, org, route_hint=spec["route"], returned=spec["returned"])
        flow, store = load_flow(), FileStore(run / "out")
        wf = run_workflow(case, flow, store)
        for _ in range(MAX_SWITCHES):
            stuck = [s for s in wf["stage_results"] if s["state"] == "error" and s["stage"] in PROVIDER
                     and KEY_PROBLEM.search(json.dumps(s.get("error") or {}))]
            if not stuck:
                break
            switched = False
            for s in stuck:
                keys = gemini if PROVIDER[s["stage"]] == "gemini" else groq
                before = keys.i + 1
                if keys.advance():
                    switched = True
                    why = (s.get("error") or {}).get("message", "")[:120]
                    _note(run, f"{s['stage'].title()}: {keys.name} key {before} failed ({why}). Retrying with key {keys.i + 1}.")
            if not switched:
                _note(run, "No spare key left for the failed stage(s); the failure stays recorded (fail-open).")
                break
            wf = resume(workflow_id_for(case), flow, store)
        _status(run, state="done", finished_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                keys_used={"gemini": gemini.i + 1 if gemini.keys else 0, "groq": groq.i + 1 if groq.keys else 0})
        return 0
    except Exception as exc:  # recorded for the page, never a silent hang
        _status(run, state="error", error=f"{type(exc).__name__}: {exc}", trace=traceback.format_exc()[-2000:],
                finished_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
