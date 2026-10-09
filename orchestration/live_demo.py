"""Live Run: the API behind the UI page where someone types in one product, uploads its photos and watches the Pod's
real agents process it step by step (local demo).

  GET  /live/config                       choices for the form, and how many model keys are configured (counts only)
  POST /live/runs                         validate the form, write the agents' input files and photos, start the run
  GET  /live/runs/{run_id}                progress: run state, the workflow (saved after every stage) and its evidence
  GET  /live/runs/{run_id}/photos/{stage}/{name}   an uploaded photo, for the page to show

Each run gets its own folder under out/live/<run_id>/ (data/ = one row per agent file in the Round 2 format, input/ =
the photos) and its own process (orchestration/live_run.py), so it never changes what the dashboard's API serves.
Nothing here judges: every verdict and reason the page shows comes from the agents' evidence records.
"""
from __future__ import annotations

import base64
import binascii
import csv
import io
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator, model_validator

from .orchestrator import ROOT
from .store import FileStore

router = APIRouter(prefix="/live", tags=["live"])
RUNS = Path(os.environ.get("OUT_DIR") or ROOT / "out").resolve() / "live"
SETS = ROOT / "live_demo_sets"  # ready-made inputs: one folder per product (spec.json + receiving/ pack/ returns/ photos)
RUN_ID = re.compile(r"^LIVE-\d{6}-[0-9A-F]{4}$")
SET_NAME = re.compile(r"^set\d+_[a-z0-9_]+$")
PHOTO_NAME = re.compile(r"^[a-z_]*\d+\.jpg$")  # the names _build writes: 1.jpg (receiving, returns), open_box_1.jpg, ref_1.jpg
SET_PHOTO = re.compile(r"^\d+_[a-z0-9_]+\.jpg$")
ORG = "org_demo_alpha"
MAX_PHOTO_BYTES = 12 * 1024 * 1024

# The values the agents understand (the Round 2 sample files use exactly these).
CATEGORIES = ("electronics", "toys_games", "home_kitchen", "beauty_topical", "grocery_ingestible", "pet")
DAMAGE = ("none", "crushing", "tears", "water", "uncertain")
QUALITY_FLAGS = ("missing_components", "obvious_defect", "wrong_colour", "wrong_variant")
CHANNELS = ("shopify", "amazon_mfn", "walmart", "3pl_client")
CHARGE_TYPES = ("inbound_defect_fee", "fulfilment_fee_weight_tier", "refund_issued_item_not_returned", "lost_inbound",
                "damaged_in_warehouse")
REPORT_TYPES = ("fee_report", "inventory_adjustment", "reimbursement_report")
PREP_OBSERVED = {
    "polybag_present_sealed": ("yes", "not_sealed", "missing", "not_required", "uncertain"),
    "suffocation_warning": ("legible", "obscured_by_fold", "missing", "not_required", "uncertain"),
    "fnsku_label_placement": ("flat", "on_curve", "on_seam", "on_edge", "missing", "uncertain"),
    "original_barcode_covered": ("yes", "no", "uncertain"),
    "expiry_date": ("legible", "illegible_after_wrap", "not_required", "uncertain"),
    "handling_marks": ("all_present", "some_missing", "not_required", "uncertain"),
}
PHOTO_SLOTS = {"receiving": ("receiving", "{i}.jpg"), "pack": ("pack", "open_box_{i}.jpg"),
               "returns": ("returns", "{i}.jpg"), "returns_ref": ("returns", "ref_{i}.jpg")}


class Product(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    sku: str = Field(min_length=1, max_length=60, pattern=r"^[A-Za-z0-9._-]+$")
    asin: str = Field("", max_length=20)
    category: Literal[CATEGORIES]  # type: ignore[valid-type]
    colour: str = Field("n/a", max_length=40)
    variant: str = Field("standard", max_length=60)
    components: list[str] = Field(default_factory=list, max_length=12)


class Receiving(BaseModel):
    supplier: str = Field(min_length=1, max_length=80)
    po_number: str = Field(min_length=1, max_length=40)
    cartons_ordered: int = Field(ge=0, le=100000)
    cartons_received: int = Field(ge=0, le=100000)
    units_per_carton_ordered: int = Field(ge=1, le=100000)
    units_per_carton_counted: int = Field(ge=0, le=100000)
    qty_ordered: int = Field(ge=0, le=10000000)
    qty_received: int = Field(ge=0, le=10000000)
    identity_match: Literal["yes", "no", "uncertain"]
    carton_damage: Literal[DAMAGE]  # type: ignore[valid-type]
    unit_damage: Literal[DAMAGE]  # type: ignore[valid-type]
    quality_flags: list[Literal[QUALITY_FLAGS]] = Field(default_factory=list)  # type: ignore[valid-type]


class Prep(BaseModel):
    fnsku: str = Field("", max_length=20)
    prep_price_usd: float = Field(0.4, ge=0, le=1000)
    wo_polybag: bool
    wo_suffocation_warning: bool
    wo_expiry_date: bool
    wo_handling_marks: list[Literal["fragile", "this_way_up", "liquid"]] = Field(default_factory=list)
    polybag_present_sealed: str
    suffocation_warning: str
    fnsku_label_placement: str
    original_barcode_covered: str
    expiry_date: str
    handling_marks: str

    @model_validator(mode="after")
    def _known_values(self):
        for name, allowed in PREP_OBSERVED.items():
            if getattr(self, name) not in allowed:
                raise ValueError(f"prep.{name} must be one of {', '.join(allowed)}")
        return self


class Line(BaseModel):
    sku: str = Field(min_length=1, max_length=60, pattern=r"^[A-Za-z0-9._-]+$")
    qty: int = Field(ge=1, le=1000)


class Pack(BaseModel):
    channel: Literal[CHANNELS] = "shopify"  # type: ignore[valid-type]
    order_lines: list[Line] = Field(min_length=1, max_length=10)
    observed_in_box: list[Line] = Field(default_factory=list, max_length=10)
    operator_verdict: Literal["seal", "stop_and_fix"] = "seal"


class Returns(BaseModel):
    parts_list: list[str] = Field(min_length=1, max_length=12)


class Fee(BaseModel):
    charge_type: Literal[CHARGE_TYPES]  # type: ignore[valid-type]
    amount_usd: float = Field(ge=0, le=100000)
    quantity: int = Field(1, ge=1, le=1000)
    report_type: Literal[REPORT_TYPES] = "fee_report"  # type: ignore[valid-type]


class Photo(BaseModel):
    name: str = Field("photo", max_length=200)
    data: str  # base64, or a data: URL


class LiveSpec(BaseModel):
    product: Product
    route: Literal["fba", "mfn"]
    returned: bool
    receiving: Receiving
    prep: Prep | None = None
    pack: Pack | None = None
    returns: Returns | None = None
    fees: list[Fee] = Field(default_factory=list, max_length=10)
    photos: dict[str, list[Photo]] = Field(default_factory=dict)

    @field_validator("photos")
    @classmethod
    def _slots(cls, v):
        for slot, items in v.items():
            if slot not in PHOTO_SLOTS:
                raise ValueError(f"unknown photo slot {slot!r} (use {', '.join(PHOTO_SLOTS)})")
            if len(items) > 4:
                raise ValueError(f"at most 4 photos for {slot}")
        return v

    @model_validator(mode="after")
    def _route_and_return(self):
        if self.route == "fba" and self.prep is None:
            raise ValueError("an FBA unit needs the Prep section (Amazon's prep checks)")
        if self.route == "mfn" and self.pack is None:
            raise ValueError("a merchant-fulfilled (MFN) unit needs the Pack section (the order and the open box)")
        if self.returned:
            if self.returns is None:
                raise ValueError("a returned unit needs the Returns section")
            if not self.photos.get("returns"):
                raise ValueError("a returned unit needs at least one photo of the returned item")
        return self


def _decode(photo: Photo) -> bytes:
    data = photo.data.split(",", 1)[1] if photo.data.startswith("data:") else photo.data
    try:
        raw = base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(422, f"photo {photo.name!r} is not valid base64 image data")
    if len(raw) > MAX_PHOTO_BYTES:
        raise HTTPException(422, f"photo {photo.name!r} is larger than {MAX_PHOTO_BYTES // (1024 * 1024)} MB")
    return raw


def _save_photo(raw: bytes, dest: Path, name: str) -> None:
    """Re-encode as JPEG, at most 1280 px: a clean file the agents can read, and fewer image tokens for the models."""
    from PIL import Image, UnidentifiedImageError
    try:
        im = Image.open(io.BytesIO(raw))
        im.load()
    except (UnidentifiedImageError, OSError):
        raise HTTPException(422, f"{name!r} is not an image the server can read (use JPEG, PNG or WebP)")
    im = im.convert("RGB")
    im.thumbnail((1280, 1280))
    dest.parent.mkdir(parents=True, exist_ok=True)
    im.save(dest, "JPEG", quality=88, optimize=True)


def _write_csv(path: Path, row: dict) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(row))
        w.writeheader()
        w.writerow(row)


def _build(run: Path, unit: str, spec: LiveSpec) -> dict:
    """Write data/ and input/ for the run. Returns which agents will look at photos with a model."""
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    p, rc = spec.product, spec.receiving
    refs: dict[str, list[str]] = {}
    for slot, items in spec.photos.items():
        stage, pattern = PHOTO_SLOTS[slot]
        for i, photo in enumerate(items, 1):
            name = pattern.format(i=i)
            _save_photo(_decode(photo), run / "input" / unit / stage / name, photo.name)
            refs.setdefault(stage, []).append(f"{unit}/{stage}/{name}")
    data = run / "data"
    data.mkdir(parents=True, exist_ok=True)
    _write_csv(data / "receiving_sample.csv", {
        "record_id": f"RCV-{unit}", "unit_id": unit, "org_id": ORG, "po_number": rc.po_number, "po_line": "1",
        "supplier": rc.supplier, "sku": p.sku, "asin": p.asin, "product_title": p.title, "spec_colour": p.colour,
        "spec_variant": p.variant, "spec_components": ";".join(c.strip() for c in p.components if c.strip()),
        "cartons_ordered": rc.cartons_ordered, "cartons_received": rc.cartons_received,
        "units_per_carton_ordered": rc.units_per_carton_ordered, "units_per_carton_counted": rc.units_per_carton_counted,
        "qty_ordered": rc.qty_ordered, "qty_received": rc.qty_received, "identity_match": rc.identity_match,
        "carton_damage": rc.carton_damage, "unit_damage": rc.unit_damage, "quality_flags": ";".join(rc.quality_flags),
        "photo_refs": ";".join(refs.get("receiving", [])), "operator_id": "op_live_demo", "captured_at": now})
    if spec.route == "fba" and spec.prep:
        pr = spec.prep
        _write_csv(data / "prep_sample.csv", {
            "record_id": f"PRP-{unit}", "unit_id": unit, "org_id": ORG, "work_order_id": f"WO-{unit}",
            "fba_shipment_id": f"FBA-{unit}", "sku": p.sku, "asin": p.asin, "fnsku": pr.fnsku,
            "prep_price_usd": f"{pr.prep_price_usd:.2f}", "wo_polybag": str(pr.wo_polybag),
            "wo_suffocation_warning": str(pr.wo_suffocation_warning), "wo_expiry_date": str(pr.wo_expiry_date),
            "wo_handling_marks": ";".join(pr.wo_handling_marks), "polybag_present_sealed": pr.polybag_present_sealed,
            "suffocation_warning": pr.suffocation_warning, "fnsku_label_placement": pr.fnsku_label_placement,
            "original_barcode_covered": pr.original_barcode_covered, "expiry_date": pr.expiry_date,
            "handling_marks": pr.handling_marks, "photo_refs": "", "operator_id": "op_live_demo", "captured_at": now})
    if spec.route == "mfn" and spec.pack:
        pk = spec.pack
        lines = lambda ls: ";".join(f"{x.sku}:{x.qty}" for x in ls)  # noqa: E731
        _write_csv(data / "pack_sample.csv", {
            "record_id": f"PCK-{unit}", "unit_id": unit, "org_id": ORG, "order_id": f"ORD-{unit}", "channel": pk.channel,
            "order_lines": lines(pk.order_lines), "observed_in_box": lines(pk.observed_in_box or pk.order_lines),
            "operator_verdict": pk.operator_verdict, "photo_refs": ";".join(refs.get("pack", [])),
            "operator_id": "op_live_demo", "captured_at": now})
    if spec.returned and spec.returns:
        _write_csv(data / "returns_sample.csv", {
            "record_id": f"RTN-{unit}", "unit_id": unit, "org_id": ORG, "order_id": f"ORD-{unit}", "ordered_sku": p.sku,
            "ordered_asin": p.asin, "identity_match": "", "parts_list": ";".join(x.strip() for x in spec.returns.parts_list if x.strip()),
            "parts_missing": "", "observed_state": "", "amazon_condition": "", "operator_disposition": "",
            "photo_refs": ";".join(refs.get("returns", [])), "operator_id": "op_live_demo", "captured_at": now,
            "category": p.category})
    if spec.fees:
        rows = [{"line_id": f"FEE-{unit}-{i}", "report_type": f.report_type, "unit_id": unit, "org_id": ORG, "sku": p.sku,
                 "fnsku": spec.prep.fnsku if spec.prep else "", "fba_shipment_id": f"FBA-{unit}" if spec.route == "fba" else "",
                 "order_id": f"ORD-{unit}", "charge_type": f.charge_type, "quantity": f.quantity,
                 "amount_usd": f"{f.amount_usd:.2f}", "posted_date": now[:10]} for i, f in enumerate(spec.fees, 1)]
        with open(data / "fee_report_sample.csv", "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
    return {"receiving": bool(refs.get("receiving")), "pack": spec.route == "mfn" and bool(refs.get("pack")),
            "returns": spec.returned}


def _key_count(single: str, many: str) -> int:
    keys = {k.strip() for k in [os.environ.get(single, "")] + os.environ.get(many, "").split(",") if k.strip()}
    return len(keys)


@router.get("/config")
def config() -> dict:
    return {
        "categories": CATEGORIES, "damage": DAMAGE, "quality_flags": QUALITY_FLAGS, "channels": CHANNELS,
        "charge_types": CHARGE_TYPES, "report_types": REPORT_TYPES, "prep_observed": PREP_OBSERVED,
        "keys": {"gemini": _key_count("GEMINI_API_KEY", "GEMINI_API_KEYS"),
                 "groq": _key_count("GROQ_API_KEY", "GROQ_API_KEYS") + _key_count("OPENROUTER_API_KEY", "")},
        "models": {"gemini": os.environ.get("LIVE_GEMINI_MODEL") or "gemini-3.8-flash",
                   "groq": os.environ.get("PACK_MODEL_NAME") or "qwen/qwen3.8-27b"},
    }


@router.post("/runs", status_code=201)
def start_run(spec: LiveSpec) -> dict:
    unit = f"LIVE-{time.strftime('%H%M%S')}-{secrets.token_hex(2).upper()}"
    run = RUNS / unit
    run.mkdir(parents=True)
    try:
        ai = _build(run, unit, spec)
    except Exception:
        shutil.rmtree(run, ignore_errors=True)  # a refused photo leaves no half-written run behind
        raise
    summary = spec.model_dump(exclude={"photos"})
    summary.update(unit_id=unit, org_id=ORG, ai=ai, photos={k: len(v) for k, v in spec.photos.items()})
    (run / "spec.json").write_text(json.dumps(summary, indent=2))
    (run / "status.json").write_text(json.dumps({"state": "starting", "notes": []}))
    log = open(run / "run.log", "w", encoding="utf-8")
    subprocess.Popen([sys.executable, "-m", "orchestration.live_run", str(run)], cwd=ROOT, stdout=log,
                     stderr=subprocess.STDOUT, env={**os.environ, "PYTHONUNBUFFERED": "1"})
    return {"run_id": unit, "unit_id": unit, "ai": ai}


def _run_dir(run_id: str) -> Path:
    if not RUN_ID.match(run_id) or not (RUNS / run_id).is_dir():
        raise HTTPException(404, f"no live run {run_id}")
    return RUNS / run_id


def _read_json(path: Path) -> dict:
    for _ in range(5):  # the run process may be replacing the file right now
        try:
            return json.loads(path.read_text())
        except (OSError, ValueError):
            time.sleep(0.05)
    return {}


@router.get("/runs/{run_id}")
def get_run(run_id: str) -> dict:
    run = _run_dir(run_id)
    spec, status = _read_json(run / "spec.json"), _read_json(run / "status.json")
    store = FileStore(run / "out")
    wf = store.load_workflow(f"WF-{ORG}-{run_id}")
    evidence = {rid: store.get_evidence(rid) for rid in (wf or {}).get("evidence_references", [])}
    photos = {}
    for stage in ("receiving", "pack", "returns"):
        folder = run / "input" / run_id / stage
        if folder.is_dir():
            photos[stage] = [f"/live/runs/{run_id}/photos/{stage}/{p.name}" for p in sorted(folder.iterdir()) if p.is_file()]
    running = None
    if wf and status.get("state") in ("starting", "running") and wf["status"] in ("PENDING", "IN_PROGRESS"):
        running = next((s["stage"] for s in wf["stage_results"] if s["state"] in ("pending", "error")), None)
    elif not wf and status.get("state") in ("starting", "running"):
        running = "receiving"
    log_tail = (run / "run.log").read_text(encoding="utf-8", errors="replace")[-1500:] if status.get("state") == "error" else ""
    return {"run_id": run_id, "spec": spec, "status": status, "running_stage": running, "workflow": wf,
            "evidence": evidence, "photos": photos, "log_tail": log_tail}


@router.get("/sets")
def list_sets() -> list[dict]:
    """The ready-made demo sets (live_demo_sets/): what to type and which photos to attach, to fill the form in one click.
    Loading a set only fills the form; the run itself is the same as for anything typed in by hand."""
    out = []
    for d in sorted(p for p in SETS.iterdir() if p.is_dir() and SET_NAME.match(p.name)) if SETS.is_dir() else []:
        try:
            spec = json.loads((d / "spec.json").read_text(encoding="utf-8"))
            about = json.loads((d / "about.json").read_text(encoding="utf-8")) if (d / "about.json").is_file() else {}
        except (OSError, ValueError):
            continue
        photos = {stage: [f"/live/sets/{d.name}/photos/{stage}/{f.name}" for f in sorted((d / stage).glob("*.jpg"))]
                  for stage in ("receiving", "pack", "returns") if (d / stage).is_dir()}
        out.append({"name": d.name, "title": about.get("title", d.name), "story": about.get("story", ""), "spec": spec,
                    "photos": photos})
    return out


@router.get("/sets/{name}/photos/{stage}/{file}")
def get_set_photo(name: str, stage: str, file: str):
    if not SET_NAME.match(name) or stage not in ("receiving", "pack", "returns") or not SET_PHOTO.match(file):
        raise HTTPException(404, "no such photo")
    path = SETS / name / stage / file
    if not path.is_file():
        raise HTTPException(404, "no such photo")
    return FileResponse(path, media_type="image/jpeg")


@router.get("/runs/{run_id}/photos/{stage}/{name}")
def get_photo(run_id: str, stage: str, name: str):
    run = _run_dir(run_id)
    if stage not in ("receiving", "pack", "returns") or not PHOTO_NAME.match(name):
        raise HTTPException(404, "no such photo")
    path = run / "input" / run_id / stage / name
    if not path.is_file():
        raise HTTPException(404, "no such photo")
    return FileResponse(path, media_type="image/jpeg")
