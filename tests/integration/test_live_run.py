"""Live Run (orchestration/live_demo.py + live_run.py): the form is validated, the agents' input files are written in
the Round 2 format they already read, and a run goes through the real agents in its own process.

No model is called: the FBA run has no photos and no return, so Receiving replays the typed counts and no Gemini or Groq
stage runs.
"""
from __future__ import annotations

import base64
import copy
import csv
import io
import time

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from orchestration import api, live_demo

FBA = {
    "product": {"title": "Soy Candle Trio", "sku": "SKU-CANDLE-LIVE", "asin": "B0LIVE0001", "category": "home_kitchen",
                "colour": "cream", "variant": "3-pack", "components": ["candle x3", "gift box"]},
    "route": "fba", "returned": False,
    "receiving": {"supplier": "Supplier Coastal", "po_number": "PO-LIVE-2", "cartons_ordered": 2, "cartons_received": 2,
                  "units_per_carton_ordered": 12, "units_per_carton_counted": 10, "qty_ordered": 24, "qty_received": 20,
                  "identity_match": "yes", "carton_damage": "none", "unit_damage": "none", "quality_flags": []},
    "prep": {"fnsku": "X00LIVE002", "prep_price_usd": 0.4, "wo_polybag": True, "wo_suffocation_warning": True,
             "wo_expiry_date": False, "wo_handling_marks": ["fragile"], "polybag_present_sealed": "yes",
             "suffocation_warning": "legible", "fnsku_label_placement": "on_curve", "original_barcode_covered": "yes",
             "expiry_date": "not_required", "handling_marks": "all_present"},
    "fees": [{"charge_type": "inbound_defect_fee", "amount_usd": 2.5}],
}


def _jpeg() -> str:
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), (200, 30, 30)).save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(live_demo, "RUNS", tmp_path / "live")
    return TestClient(api.app)


@pytest.mark.parametrize("change, message", [
    (lambda s: s.update(route="mfn"), "needs the Pack section"),
    (lambda s: s.update(returned=True, returns={"parts_list": ["candles"]}), "at least one photo of the returned item"),
    (lambda s: s["receiving"].update(qty_received=-1), "greater than or equal to 0"),
    (lambda s: s["product"].update(category="cars"), "electronics"),
    (lambda s: s["prep"].update(fnsku_label_placement="sideways"), "fnsku_label_placement must be one of"),
    (lambda s: s.update(photos={"selfie": [{"name": "a.jpg", "data": _jpeg()}]}), "unknown photo slot"),
])
def test_bad_forms_are_refused_with_a_reason(client, change, message):
    spec = copy.deepcopy(FBA)
    change(spec)
    r = client.post("/live/runs", json=spec)
    assert r.status_code == 422
    assert message in r.text


def test_a_file_that_is_not_an_image_is_refused_and_leaves_nothing(client, tmp_path):
    spec = copy.deepcopy(FBA) | {"returned": True, "returns": {"parts_list": ["a"]},
                                 "photos": {"returns": [{"name": "x.jpg", "data": "data:image/jpeg;base64,bm90IGFuIGltYWdl"}]}}
    r = client.post("/live/runs", json=spec)
    assert r.status_code == 422 and "not an image" in r.text
    assert not any((tmp_path / "live").glob("LIVE-*"))


def test_inputs_are_written_in_the_format_the_agents_read(client, tmp_path, monkeypatch):
    monkeypatch.setattr(live_demo.subprocess, "Popen", lambda *a, **k: None)  # build only: no run process
    spec = copy.deepcopy(FBA) | {"route": "mfn", "prep": None, "returned": True, "returns": {"parts_list": ["candles"]},
                                 "pack": {"order_lines": [{"sku": "SKU-CANDLE-LIVE", "qty": 1}]},
                                 "photos": {"pack": [{"name": "box.png", "data": _jpeg()}],
                                            "returns": [{"name": "back.png", "data": _jpeg()}]}}
    r = client.post("/live/runs", json=spec)
    assert r.status_code == 201, r.text
    unit = r.json()["unit_id"]
    run = tmp_path / "live" / unit
    rows = {f.stem: list(csv.DictReader(open(f, encoding="utf-8"))) for f in (run / "data").glob("*.csv")}
    assert set(rows) == {"receiving_sample", "pack_sample", "returns_sample", "fee_report_sample"}
    from shared.utils import sample_data
    for kind, file in sample_data.FILES.items():  # every file carries the columns its agent requires
        if file[:-4] in rows:
            assert not sample_data.missing_columns(kind, list(rows[file[:-4]][0]))
    assert rows["pack_sample"][0]["photo_refs"] == f"{unit}/pack/open_box_1.jpg"
    assert rows["returns_sample"][0]["category"] == "home_kitchen"
    assert (run / "input" / unit / "pack" / "open_box_1.jpg").is_file()
    assert r.json()["ai"] == {"receiving": False, "pack": True, "returns": True}
    # every photo the run view lists must be served (receiving/returns photos are named 1.jpg: they were refused once)
    listed = client.get(f"/live/runs/{unit}").json()["photos"]
    assert listed == {"pack": [f"/live/runs/{unit}/photos/pack/open_box_1.jpg"], "returns": [f"/live/runs/{unit}/photos/returns/1.jpg"]}
    for urls in listed.values():
        for u in urls:
            photo = client.get(u)
            assert photo.status_code == 200 and photo.headers["content-type"] == "image/jpeg", u
    assert client.get(f"/live/runs/{unit}/photos/pack/..%2F..%2Fspec.json").status_code == 404


def test_an_fba_unit_runs_through_the_real_agents(client):
    r = client.post("/live/runs", json=FBA)
    assert r.status_code == 201, r.text
    run_id = r.json()["run_id"]
    for _ in range(120):
        view = client.get(f"/live/runs/{run_id}").json()
        if view["status"].get("state") in ("done", "error"):
            break
        time.sleep(0.5)
    assert view["status"]["state"] == "done", view
    wf = view["workflow"]
    stages = {s["stage"]: s for s in wf["stage_results"]}
    assert stages["receiving"]["verdict"] == "FAIL"  # 20 of 24 received
    assert stages["prep"]["verdict"] == "FAIL"  # FNSKU label on a curve
    assert stages["pack"]["state"] == stages["returns"]["state"] == "skipped"
    recovery = view["evidence"][stages["recovery"]["record_id"]]
    assert recovery["payload"]["charges"][0]["position"] == "SUPPORTS"  # Prep's FAIL supports the defect fee
    assert wf["final_outcome"]["outcome"] == "EXCEPTION"


def test_demo_sets_are_listed_with_their_photos_and_load_as_valid_forms(client, monkeypatch, tmp_path):
    sets = tmp_path / "sets"
    d = sets / "set1_test_product"
    (d / "pack").mkdir(parents=True)
    Image.new("RGB", (20, 20), "blue").save(d / "pack" / "1_box.jpg")
    spec = copy.deepcopy(FBA) | {"route": "mfn", "prep": None, "pack": {"order_lines": [{"sku": "SKU-CANDLE-LIVE", "qty": 1}]}}
    import json
    (d / "spec.json").write_text(json.dumps(spec))
    (d / "about.json").write_text(json.dumps({"title": "Test product", "story": "A story."}))
    (sets / "not_a_set").mkdir()
    monkeypatch.setattr(live_demo, "SETS", sets)
    listed = client.get("/live/sets").json()
    assert [s["name"] for s in listed] == ["set1_test_product"]
    assert listed[0]["photos"] == {"pack": ["/live/sets/set1_test_product/photos/pack/1_box.jpg"]}
    assert client.get(listed[0]["photos"]["pack"][0]).headers["content-type"] == "image/jpeg"
    assert client.get("/live/sets/set1_test_product/photos/pack/..%2Fspec.json").status_code == 404
    assert client.get("/live/sets/..%2F..%2Fpod/photos/pack/1_box.jpg").status_code == 404
    monkeypatch.setattr(live_demo.subprocess, "Popen", lambda *a, **k: None)
    assert client.post("/live/runs", json=listed[0]["spec"]).status_code == 201  # a set's spec is a valid form


def test_the_shipped_demo_sets_are_valid_forms(client, monkeypatch):
    """Every set in live_demo_sets/ passes the same validation as a hand-typed form (when the folder is present)."""
    if not live_demo.SETS.is_dir():
        pytest.skip("live_demo_sets/ not present")
    import json
    from pathlib import Path
    root = Path(live_demo.ROOT)
    photos = [p for p in json.loads((root / "data" / "photos.json").read_text(encoding="utf-8"))["photos"]
              if p["path"].startswith("live_demo_sets/")]
    if not all((root / p["path"]).is_file() for p in photos):  # the photos are not in git: scripts/fetch_photos.py
        pytest.skip("demo set photos not downloaded: python scripts/fetch_photos.py")
    for d in (p for p in live_demo.SETS.iterdir() if p.is_dir()):  # every photo a set uses is in the download list
        for f in d.rglob("*.jpg"):
            assert f.relative_to(root).as_posix() in {p["path"] for p in photos}, f
    monkeypatch.setattr(live_demo.subprocess, "Popen", lambda *a, **k: None)
    for s in client.get("/live/sets").json():
        spec = s["spec"] | {"photos": {stage: [{"name": "x.png", "data": _jpeg()}] for stage in s["photos"]}}
        r = client.post("/live/runs", json=spec)
        assert r.status_code == 201, (s["name"], r.text)


def test_unknown_or_malformed_run_ids_are_404(client):
    assert client.get("/live/runs/LIVE-000000-ABCD").status_code == 404
    assert client.get("/live/runs/..%2F..%2Fpod").status_code == 404
