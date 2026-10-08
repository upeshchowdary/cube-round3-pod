"""A dataset handed over live (e.g. by a judge): any subset of the five files, checked, then run through all agents.

Found by simulating it: a dataset with only some files crashed three agents (FileNotFoundError), and a renamed column
(`received_qty` for `qty_received`) made Receiving say PASS, because the agent filled the missing column with the
expected value and compared the order with itself.
"""
import csv
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from orchestration import dataset
from orchestration.store import FileStore
from shared.utils import sample_data

ROOT = Path(__file__).resolve().parents[2]
SAMPLE = ROOT / "data" / "sample"


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch, tmp_path):
    # load()/run() point DATA_DIR / INPUT_DIR / OUT_DIR at the loaded dataset; registering them here restores them.
    for var in ("DATA_DIR", "INPUT_DIR", "OUT_DIR"):
        monkeypatch.setenv(var, str(tmp_path / "unused"))
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)


def unit_rows(kind: str, unit: str) -> tuple[list[str], list[dict]]:
    with (SAMPLE / sample_data.FILES[kind]).open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        return list(reader.fieldnames), [r for r in reader if r["unit_id"] == unit]


def write(path: Path, header: list[str], rows: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=header, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return path


def judge_folder(tmp_path: Path, unit: str, kinds: list[str], rename: dict | None = None) -> Path:
    """A judge's folder holding only `unit`'s rows of the given files, under judge-style file names."""
    folder = tmp_path / "judge"
    for kind in kinds:
        header, rows = unit_rows(kind, unit)
        header = [(rename or {}).get(h, h) for h in header]
        rows = [{(rename or {}).get(k, k): v for k, v in r.items()} for r in rows]
        write(folder / f"{kind}_input.csv", header, rows)
    return folder


def load(tmp_path, sources, **kw):
    kw.setdefault("maps", {})
    kw.setdefault("cats", {})
    kw.setdefault("photos_dir", None)
    return dataset.load(sources, name="judge", root=tmp_path / "datasets", **kw)


def by_stage(wf: dict) -> dict:
    return {sr["stage"]: sr for sr in wf["stage_results"]}


def test_renamed_column_is_refused_with_the_fix_not_judged(tmp_path):
    folder = judge_folder(tmp_path, "UNIT-0014", ["receiving"], rename={"qty_received": "received_qty"})
    rep, out, _ = load(tmp_path, [folder])
    assert any("qty_received (closest: received_qty)" in e and "--map received_qty=qty_received" in e for e in rep.errors)
    assert not out.exists()  # nothing is run on a file the agent would misread

    rep, out, _ = load(tmp_path, [folder], maps={"received_qty": "qty_received"})
    assert rep.errors == []
    wf = dataset.run(out)[0]
    assert by_stage(wf)["receiving"]["verdict"] == "PASS"


def test_header_case_spaces_and_bom_are_fixed_silently(tmp_path):
    header, rows = unit_rows("receiving", "UNIT-0014")
    messy = {h: f" {h.replace('_', ' ').title()} " for h in header}
    path = write(tmp_path / "judge" / "Receiving Data.csv", [messy[h] for h in header],
                 [{messy[k]: v for k, v in r.items()} for r in rows])
    path.write_bytes(b"\xef\xbb\xbf" + path.read_bytes())  # Excel's UTF-8 BOM
    rep, _, tables = load(tmp_path, [path])
    assert rep.errors == [] and tables["receiving"][0]["qty_received"] == "24"


def test_only_a_receiving_file_runs_receiving_and_skips_the_rest_with_reasons(tmp_path):
    rep, out, _ = load(tmp_path, [judge_folder(tmp_path, "UNIT-0014", ["receiving"])])
    assert rep.errors == []
    wf = dataset.run(out)[0]
    st = by_stage(wf)
    assert st["receiving"]["state"] == "completed" and st["receiving"]["verdict"] == "PASS"
    assert all(st[s]["state"] == "skipped" for s in ("prep", "pack", "returns", "recovery"))
    assert "no recovery input" in st["recovery"]["skipped_reason"]
    assert wf["errors"] == [] and wf["status"] == "COMPLETED" and wf["final_outcome"]["outcome"] == "CLEAN"


def test_full_dataset_for_a_new_unit_reaches_every_agent(tmp_path):
    folder = tmp_path / "judge"
    for kind in ("receiving", "prep", "returns", "fees"):
        header, rows = unit_rows(kind, "UNIT-0014")
        for r in rows:  # a brand-new unit the Pod has never seen
            r.update(unit_id="UNIT-0901", record_id=r.get("record_id", "").replace("0014", "0901"))
            if "line_id" in r:
                r["line_id"] = r["line_id"].replace("0014", "0901")
        write(folder / sample_data.FILES[kind], header, rows)
    rep, out, _ = load(tmp_path, [folder])
    assert rep.errors == [] and any("UNIT-0901: returned but no photos" in w for w in rep.warnings)
    wf = dataset.run(out)[0]
    st = by_stage(wf)
    assert st["receiving"]["verdict"] == "PASS" and st["prep"]["verdict"] == "PASS"
    assert st["returns"]["error"]["code"] == "no_reference_photo"  # honest: we were given no photos
    assert st["recovery"]["outcome"] == "claim_recommended" and wf["final_outcome"]["claimable_usd"] == 2.0


def test_returns_input_from_the_judge_and_photos_from_us(tmp_path):
    folder = judge_folder(tmp_path, "UNIT-0014", ["returns"])
    photos = tmp_path / "our_photos" / "UNIT-0014" / "returns"
    shutil.copytree(ROOT / "data" / "input" / "UNIT-0014" / "returns", photos)
    rep, out, _ = load(tmp_path, [folder], photos_dir=tmp_path / "our_photos")
    assert rep.errors == []
    wf = dataset.run(out)[0]
    st = by_stage(wf)
    assert st["receiving"]["state"] == "skipped" and st["recovery"]["state"] == "skipped"
    assert st["returns"]["state"] == "completed" and st["returns"]["outcome"] == "liquidate"
    rec = FileStore(out / "run").get_evidence(st["returns"]["record_id"])
    assert {i["ref"] for i in rec["inputs"]} == {f"UNIT-0014/returns/{p.name}" for p in photos.iterdir()}


def test_a_new_product_needs_a_category_for_returns(tmp_path):
    header, rows = unit_rows("returns", "UNIT-0014")
    rows[0]["ordered_sku"] = "SKU-NEW-KETTLE"
    path = write(tmp_path / "judge" / "returns.csv", header, rows)
    rep, _, _ = load(tmp_path, [path])
    assert any("SKU-NEW-KETTLE" in e and "--category SKU-NEW-KETTLE=" in e and "home_kitchen" in e for e in rep.errors)
    rep, _, tables = load(tmp_path, [path], cats={"SKU-NEW-KETTLE": "Home_Kitchen"})
    assert rep.errors == [] and tables["returns"][0]["category"] == "home_kitchen"


def test_bad_rows_are_reported_by_row_number(tmp_path):
    header, rows = unit_rows("receiving", "UNIT-0014")
    bad = [dict(rows[0], qty_received="twenty"), dict(rows[0]), dict(rows[0], unit_id="UNIT-0015", org_id="")]
    rep, _, _ = load(tmp_path, [write(tmp_path / "judge" / "receiving.csv", header, bad)])
    text = " | ".join(rep.errors)
    assert "row 2: qty_received='twenty' is not a whole number" in text
    assert "row 3: duplicate UNIT-0014 in org_demo_alpha" in text
    assert "row 4: unit_id and org_id must not be empty" in text


def test_agents_refuse_a_misnamed_column_at_runtime_too(tmp_path, monkeypatch):
    """Even without the loader (a CSV edited by hand), a missing column is an error, never a default."""
    header, rows = unit_rows("receiving", "UNIT-0014")
    write(tmp_path / "data" / "receiving_sample.csv", [h.replace("qty_received", "received_qty") for h in header],
          [{k.replace("qty_received", "received_qty"): v for k, v in r.items()} for r in rows])
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    with pytest.raises(sample_data.DatasetError, match="qty_received"):
        sample_data.rows("receiving")
    assert sample_data.rows("prep") == ()  # a file that is not in the dataset simply has no rows


def test_api_serves_the_loaded_dataset_and_recovery_charges_in_one_call(tmp_path, monkeypatch):
    from orchestration import api

    rep, out, _ = load(tmp_path, [judge_folder(tmp_path, "UNIT-0014", ["receiving", "prep", "returns", "fees"])])
    assert rep.errors == []
    monkeypatch.setattr(api, "STORE", FileStore(tmp_path / "api-run"))
    client = TestClient(api.app)
    assert [(c["unit_id"], c["source"]) for c in client.get("/cases").json()] == [("UNIT-0014", "sample")]
    assert client.post("/workflows", json={"org_id": "org_demo_alpha", "unit_id": "UNIT-0016"}).status_code == 404
    wf = client.post("/workflows", json={"org_id": "org_demo_alpha", "unit_id": "UNIT-0014"}).json()
    assert wf["final_outcome"]["outcome"] == "CLAIM_RECOMMENDED"
    charges = client.get("/recovery/charges").json()
    assert [c["workflow_id"] for c in charges] == [wf["workflow_id"]]
    assert {c["line_id"] for c in charges[0]["charges"]} == {"FEE-0014-1", "FEE-0014-2", "FEE-0014-3", "FEE-0014-4"}


def test_returns_judges_a_unit_without_a_recorded_answer_live_when_a_key_is_set(monkeypatch):
    returns_app = pytest.importorskip("agents.returns.app")
    monkeypatch.delenv("RETURNS_MODEL_MODE", raising=False)
    assert returns_app._model_mode("org_demo_alpha", "UNIT-0901") == "replay"  # no key: never calls a model
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-real")
    assert returns_app._model_mode("org_demo_alpha", "UNIT-0901") == "live"
    assert returns_app._model_mode("org_demo_alpha", "UNIT-0014") == "replay"  # recorded answer: replayed
    monkeypatch.setenv("RETURNS_LIVE_FALLBACK", "0")
    assert returns_app._model_mode("org_demo_alpha", "UNIT-0901") == "replay"
