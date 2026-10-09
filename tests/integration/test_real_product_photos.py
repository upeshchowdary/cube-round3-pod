"""The real-photo units (data/input/RETURNS_PHOTOS.md): Pack checks the photo of the product as sold and hands it to
Returns as its reference, and Returns replays the Gemini answer recorded from a real model run on these photos.

No model is called here: keys are cleared, so Pack replays the operator row and Returns replays its cassette.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from orchestration.orchestrator import default_flow_path, load_flow, run_workflow
from orchestration.store import MemoryStore
from shared.utils import sample_data
from shared.utils.hashing import verify
from shared.utils.schema import errors

ROOT = Path(__file__).resolve().parents[2]
CASES = json.loads((ROOT / "data" / "input" / "returns_photo_cases.json").read_text())
CASSETTES = ROOT / "agents" / "returns" / "cassettes"
RECORDED = [c for c in CASES if (CASSETTES / c["org_id"] / f"{c['unit_id']}.jsonl").is_file()]
LIVE_ONLY = [c for c in CASES if c not in RECORDED]
PHOTOS = json.loads((ROOT / "data" / "photos.json").read_text(encoding="utf-8"))["photos"]
# The photos are not in git (scripts/fetch_photos.py downloads them); without them these units cannot run.
needs_photos = pytest.mark.skipif(
    not all((ROOT / p["path"]).is_file() for p in PHOTOS if p["path"].startswith("data/input/")),
    reason="real product photos not downloaded: python scripts/fetch_photos.py")


def test_every_unit_photo_is_listed_for_download_and_kept_out_of_git():
    listed = {p["path"] for p in PHOTOS}
    for c in CASES:
        for rel in (f"data/input/{c['unit_id']}/pack/open_box.jpg", f"data/input/{c['unit_id']}/returns/1.jpg"):
            assert rel in listed, rel
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "data/input/UNIT-C26RM-*/**/*.jpg" in gitignore
    assert all(len(p["sha256"]) == 64 and p["commons_file"] for p in PHOTOS)


@pytest.fixture(autouse=True)
def no_model_access(monkeypatch):
    for key in ("GEMINI_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.setenv(key, "")
    monkeypatch.setenv("RETURNS_MODEL_MODE", "replay")
    monkeypatch.delenv("RETURNS_LIVE_MODEL", raising=False)
    monkeypatch.delenv("DATA_DIR", raising=False)
    monkeypatch.delenv("INPUT_DIR", raising=False)


def _run(case):
    store = MemoryStore()
    wf = run_workflow(case, load_flow(default_flow_path()), store=store)
    stages = {s["stage"]: s for s in wf["stage_results"]}
    return wf, stages, store


def test_the_set_is_eight_recorded_units_and_two_for_a_live_run():
    assert len(RECORDED) == 8 and len(LIVE_ONLY) == 2
    for c in RECORDED:
        first = json.loads((CASSETTES / c["org_id"] / f"{c['unit_id']}.jsonl").read_text(encoding="utf-8").splitlines()[0])
        assert "provenance" not in first, "recorded from a real model run, not hand-authored"
        assert first["model"].startswith("gemini-")


def test_pod_rows_join_only_the_default_dataset(monkeypatch, tmp_path):
    unit = CASES[0]["unit_id"]
    assert sample_data.has("pack", unit, "org_demo_alpha") and sample_data.has("returns", unit, "org_demo_alpha")
    assert sample_data.route(unit, "org_demo_alpha") == "mfn"
    monkeypatch.setenv("DATA_DIR", str(tmp_path))  # a dataset someone hands us never gets the Pod's units mixed in
    assert not sample_data.has("pack", unit, "org_demo_alpha")


@needs_photos
@pytest.mark.parametrize("case", RECORDED, ids=lambda c: c["unit_id"])
def test_recorded_unit_replays_with_the_reference_photo_from_pack(case):
    wf, stages, store = _run(case)
    assert errors("workflow-state", wf) == []
    assert [s for s in ("receiving", "recovery") if stages[s]["state"] == "skipped"] == ["receiving", "recovery"]
    pack = store.get_evidence(stages["pack"]["record_id"])
    assert [i["ref"] for i in pack["inputs"]] == [f"{case['unit_id']}/pack/open_box.jpg"]

    assert stages["returns"]["state"] == "completed", stages["returns"].get("error")
    ret = store.get_evidence(stages["returns"]["record_id"])
    assert errors("evidence", ret) == [] and verify(ret)
    assert ret["payload"]["reference_source"] == "pack"
    assert pack["record_id"] in ret["upstream_refs"]
    assert [i["ref"] for i in ret["inputs"]] == [f"{case['unit_id']}/returns/1.jpg"]
    assert ret["model"]["name"].endswith("(recorded)") and ret["model"]["calls"] == 0
    assert ret["payload"]["model_mode"] == "replay" and "cassette_provenance" not in ret["payload"]


@needs_photos
def test_gemini_catches_the_model_swaps():
    """Recorded answers on swapped products: a different model came back, and Gemini says identity FAIL. Two of these
    (DualSense -> DualSense Edge, JBL Flip 3 -> Flip 4) were labelled 'same model' in the Round 2 test set."""
    swapped = {"UNIT-C26RM-012", "UNIT-C26RM-015", "UNIT-C26RM-022", "UNIT-C26RM-031", "UNIT-C26RM-044"}
    for case in (c for c in RECORDED if c["unit_id"] in swapped):
        _, stages, store = _run(case)
        ret = store.get_evidence(stages["returns"]["record_id"])
        assert {c["check_key"]: c["verdict"] for c in ret["checks"]}["identity_match"] == "FAIL", case["unit_id"]
        assert stages["returns"]["verdict"] == "FAIL"


@needs_photos
@pytest.mark.parametrize("case", LIVE_ONLY, ids=lambda c: c["unit_id"])
def test_unit_without_a_recording_fails_open_until_it_is_judged_live(case):
    wf, stages, _ = _run(case)
    assert stages["returns"]["state"] == "error"
    assert stages["returns"]["error"]["code"] == "no_cassette"
    assert wf["status"] == "FAILED" and wf["final_outcome"]["outcome"] == "INCOMPLETE"
