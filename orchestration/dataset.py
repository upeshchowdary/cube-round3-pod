"""Load a dataset someone hands you (e.g. a judge, live), check it, and run every unit through all five agents.

  python -m orchestration.dataset <folder-or-csv-files...> [--name NAME] [--map OLD=NEW ...] [--category SKU=CAT ...]
                                  [--photos DIR] [--check]
  (or: python scripts/dev.py dataset ...; then  python scripts/dev.py up --dataset NAME  shows it in the UI)

Any subset of the five Round 2-format files works (receiving / prep / pack / returns / fee report). Each file is matched
to its stage by name, else by its columns. Header case, spaces, hyphens and an Excel BOM are fixed silently; a column
that is really missing is refused with the closest name found and the --map that fixes it, because an agent reading a
missing column used to fall back to a default and could say PASS about data it never saw. Rows are checked too (ids
present, numbers numeric, one row per unit). Returns needs a product category per SKU (a `category` column, the Round 2
SKU map, or --category SKU=CAT) and photos: from --photos DIR/<unit>/<stage>/..., a photos/ or input/ folder next to the
CSVs, or the files the rows' photo_refs name. Nothing is changed in the input: a clean copy is written to
out/datasets/NAME/ (data/, input/, run/), and the run there starts empty every time.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import shutil
import sys
from pathlib import Path

from shared.utils import sample_data
from shared.utils.sample_data import FILES, REQUIRED, STAGE_OF

ROOT = Path(__file__).resolve().parents[1]
DATASETS = ROOT / "out" / "datasets"
R2_REF = ROOT / "agents" / "returns" / "r2" / "reference"
STAGES = ("receiving", "prep", "pack", "returns", "recovery")
KEYWORDS = (("receiving", ("receiv",)), ("prep", ("prep",)), ("pack", ("pack",)), ("returns", ("return",)),
            ("fees", ("fee", "charge", "settlement", "reimburs")))
INTS = {"receiving": ("cartons_ordered", "cartons_received", "qty_ordered", "qty_received", "units_per_carton_ordered",
                      "units_per_carton_counted"), "fees": ("quantity",)}
FLOATS = {"prep": ("prep_price_usd",), "fees": ("amount_usd",), "returns": ("list_price_minor",)}
IMAGE = {".jpg", ".jpeg", ".png", ".webp"}


class Report:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.notes: list[str] = []


def norm(name: str) -> str:
    """'  Qty Received ' / 'qty-received' / '\\ufeffqty_received' -> 'qty_received'."""
    return re.sub(r"_+", "_", re.sub(r"[\s\-]+", "_", name.replace("﻿", "").strip().lower())).strip("_")


def categories() -> list[str]:
    return sorted(p.stem for p in (R2_REF / "rubrics" / "amazon.co.uk").glob("*.yaml"))


def read_csv(path: Path) -> tuple[list[str], list[dict]]:
    raw = path.read_bytes()
    text = raw.decode("latin-1")  # never fails; replaced by the first encoding that fits
    for enc in ("utf-8-sig", "cp1252"):  # Excel on Windows saves cp1252
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    reader = csv.DictReader(io.StringIO(text, newline=""))
    header = [norm(h) for h in (reader.fieldnames or [])]
    rows = [{norm(k): (v or "").strip() for k, v in r.items() if k is not None} for r in reader]
    return header, rows


def detect_kind(path: Path, header: list[str]) -> str | None:
    stem = path.stem.lower()
    for kind, words in KEYWORDS:
        if any(w in stem for w in words):
            return kind
    scores = {k: len(set(REQUIRED[k]) & set(header)) / len(REQUIRED[k]) for k in REQUIRED}
    best = max(scores, key=scores.get)
    return best if scores[best] >= 0.6 else None


def check_rows(kind: str, name: str, rows: list[dict], rep: Report) -> None:
    seen: dict[tuple, int] = {}
    errs = []
    for i, r in enumerate(rows, start=2):  # row 1 is the header
        if not r.get("unit_id") or not r.get("org_id"):
            errs.append(f"row {i}: unit_id and org_id must not be empty")
        for col in INTS.get(kind, ()):
            if r.get(col, "") != "" and not re.fullmatch(r"-?\d+", r[col]):
                errs.append(f"row {i}: {col}={r[col]!r} is not a whole number")
        for col in FLOATS.get(kind, ()):
            if r.get(col, "") != "":
                try:
                    float(r[col])
                except ValueError:
                    errs.append(f"row {i}: {col}={r[col]!r} is not a number")
        key = (r.get("line_id"),) if kind == "fees" else (r.get("unit_id"), r.get("org_id"))
        if key in seen:
            what = f"line_id {key[0]}" if kind == "fees" else f"{key[0]} in {key[1]}"
            errs.append(f"row {i}: duplicate {what} (also row {seen[key]}); the agent would only ever read the first")
        seen.setdefault(key, i)
    rep.errors += [f"{name}: {e}" for e in errs[:10]]
    if len(errs) > 10:
        rep.errors.append(f"{name}: ... and {len(errs) - 10} more row problem(s)")


def resolve_category(org: str, sku: str, explicit: str) -> str | None:
    if explicit:
        return explicit
    from agents.returns.adapter.orders import _resolve_category  # the Returns agent's own lookup: card, then SKU map
    return _resolve_category(org, sku, None, R2_REF)


def collect_photos(sources: list[Path], tables: dict[str, list[dict]], photos_dir: Path | None, target: Path,
                   rep: Report) -> None:
    """Copy captures into target/<unit>/<stage>/ (the layout the orchestrator hashes and hands to each agent)."""
    roots = [photos_dir] if photos_dir else []
    for src in sources:
        base = src if src.is_dir() else src.parent
        roots += [d for d in (base / "photos", base / "input") if d.is_dir()]
    copied = 0
    for root in roots:  # <root>/<unit>/<stage>/<file>
        for f in root.glob("*/*/*"):
            if f.is_file() and f.suffix.lower() in IMAGE and f.parent.name in STAGES:
                dest = target / f.parent.parent.name / f.parent.name / f.name
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, dest)
                copied += 1
    bases = list(dict.fromkeys((s if s.is_dir() else s.parent) for s in sources))
    for kind, rows in tables.items():
        stage = STAGE_OF[kind]
        for r in rows:
            for ref in filter(None, (p.strip() for p in r.get("photo_refs", "").split(";"))):
                hit = next((b / c for b in bases for c in (ref, Path(ref).name) if (b / c).is_file()), None)
                if hit and hit.suffix.lower() in IMAGE:
                    dest = target / r["unit_id"] / stage / hit.name
                    if not dest.exists():
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(hit, dest)
                        copied += 1
    rep.notes.append(f"photos: {copied} file(s) placed under input/<unit>/<stage>/")


def load(sources: list[Path], *, name: str, maps: dict[str, str], cats: dict[str, str],
         photos_dir: Path | None, root: Path = DATASETS) -> tuple[Report, Path, dict[str, list[dict]]]:
    """Check and copy the dataset to root/name (data/, input/), write its cases.json, and point DATA_DIR / INPUT_DIR
    at it. Returns the report, that folder and the parsed tables. Nothing is written when the report has errors."""
    rep = Report()
    cats = {k.strip(): v.strip().lower() for k, v in cats.items()}
    files = []
    for s in sources:
        if s.is_dir():
            files += sorted(p for p in s.glob("*.csv"))
        elif s.is_file():
            files.append(s)
        else:
            rep.errors.append(f"{s}: not found")
    if not files and not rep.errors:
        rep.errors.append("no .csv files found")
    maps = {norm(k): norm(v) for k, v in maps.items()}
    tables: dict[str, list[dict]] = {}
    headers: dict[str, list[str]] = {}
    for f in files:
        header, rows = read_csv(f)
        if not header:
            rep.errors.append(f"{f.name}: the file is empty (not even a header row)")
            continue
        header = [maps.get(h, h) for h in header]
        rows = [{maps.get(k, k): v for k, v in r.items()} for r in rows]
        kind = detect_kind(f, header)
        if kind is None:
            rep.warnings.append(f"{f.name}: not recognised as receiving / prep / pack / returns / fee report; ignored")
            continue
        if kind in tables:
            rep.errors.append(f"{f.name}: a second {kind} file; give one file per stage")
            continue
        missing = sample_data.missing_columns(kind, header)
        if missing:
            rep.errors.append(f"{f.name} ({kind}): missing column(s) {sample_data.describe_missing(kind, header)}. "
                              f"Fix the file, or add e.g. --map {_map_hint(kind, header)}")
            continue
        check_rows(kind, f.name, rows, rep)
        tables[kind], headers[kind] = rows, header
        rep.notes.append(f"{f.name} -> {kind} ({len(rows)} rows)")

    valid = categories()
    for r in tables.get("returns", []):
        sku = r.get("ordered_sku", "")
        explicit = (cats.get(sku) or r.get("category", "")).strip().lower()
        cat = resolve_category(r.get("org_id", ""), sku, explicit)
        if not cat:
            rep.errors.append(f"returns: {r.get('unit_id')} SKU {sku!r} has no product category. Add a 'category' column "
                              f"or --category {sku}=<{'|'.join(valid)}>")
        elif cat not in valid:
            rep.errors.append(f"returns: {r.get('unit_id')} category {cat!r} is not one of {', '.join(valid)}")
        else:
            r["category"] = cat
    if "returns" in tables and "category" not in headers["returns"]:
        headers["returns"].append("category")

    if tables and not any(tables.values()):
        rep.errors.append("every file has a header but no data rows: there is no unit to run")
    out = (root / name).resolve()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", name) or out.parent != root.resolve():
        rep.errors.append(f"dataset name {name!r}: use letters, digits, - and _ only")
    if rep.errors:
        return rep, out, tables
    if out.exists():
        shutil.rmtree(out)  # our own generated folder: every load starts clean (old evidence would conflict)
    (out / "data").mkdir(parents=True)
    for kind, rows in tables.items():
        with (out / "data" / FILES[kind]).open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=headers[kind], extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
    collect_photos(sources, tables, photos_dir, out / "input", rep)

    os.environ["DATA_DIR"], os.environ["INPUT_DIR"] = str(out / "data"), str(out / "input")
    units = list(dict.fromkeys((r["unit_id"], r["org_id"]) for rows in tables.values() for r in rows))
    cases = [sample_data.case_for(u, o) for u, o in units]
    (out / "data" / "cases.json").write_text(json.dumps(cases, indent=2) + "\n", encoding="utf-8")
    absent = [STAGE_OF[k] for k in FILES if k not in tables]
    if absent:
        rep.notes.append(f"no file for: {', '.join(absent)} (skipped, with that reason, for every unit)")
    live = bool(os.environ.get("GEMINI_API_KEY")) and os.environ.get("RETURNS_LIVE_FALLBACK", "1") != "0"
    no_photos = []
    for c in cases:
        if not c["returned"]:
            continue
        u, o = c["unit_id"], c["org_id"]
        if not any((out / "input" / u / s).is_dir() for s in ("returns", "receiving", "pack")):
            no_photos.append(u)
        elif not (ROOT / "agents" / "returns" / "cassettes" / o / f"{u}.jsonl").is_file():
            rep.warnings.append(f"{u}: no recorded Returns answer; " + (
                f"Gemini judges it live ({os.environ.get('RETURNS_LIVE_MODEL') or 'gemini-3.8-flash'}, free tier 20/day)"
                if live else "set GEMINI_API_KEY in .env to judge it live, or Returns records no_cassette"))
    if no_photos:  # one line, not one per unit: a whole dataset without photos would bury every other note
        shown = ", ".join(no_photos[:6]) + (f" and {len(no_photos) - 6} more" if len(no_photos) > 6 else "")
        rep.warnings.append(f"{len(no_photos)} returned unit(s) have no photos ({shown}); Returns will hold them for a "
                            f"person (no_reference_photo). Add them with --photos DIR")
    idle = [c["unit_id"] for c in cases if not _runs_anything(c)]
    if idle:
        rep.warnings.append(f"{len(idle)} unit(s) have no stage that can run ({', '.join(idle[:6])}"
                            f"{' ...' if len(idle) > 6 else ''}): e.g. a fee report alone, since Recovery needs the "
                            f"unit's Receiving row. Their workflows stay PENDING")
    for c in cases:
        if sample_data.has("prep", c["unit_id"], c["org_id"]) and sample_data.has("pack", c["unit_id"], c["org_id"]):
            rep.warnings.append(f"{c['unit_id']}: has both a Prep and a Pack row; routed as FBA (Prep)")
    return rep, out, tables


def _runs_anything(case: dict) -> bool:
    """Whether at least one flow step applies to this case once the dataset's skip_stages are taken out."""
    from .orchestrator import applies, load_flow
    skip = set(case.get("skip_stages") or [])
    return any(applies(step, case)[0] and step["stage"] not in skip for step in load_flow()["steps"])


def _map_hint(kind: str, header: list[str]) -> str:
    """'--map' arguments for the missing columns. Only columns the agent does not already read are offered: suggesting
    a real column (cartons_received for qty_received) would make the agent read the wrong number."""
    import difflib
    spare = [h for h in header if h not in REQUIRED[kind]]
    hints = []
    for col in sample_data.missing_columns(kind, header):
        close = difflib.get_close_matches(col, spare, n=1, cutoff=0.5)
        hints.append(f"{close[0]}={col}" if close else f"YOUR_COLUMN={col}")
    return " --map ".join(hints)


def run(out: Path) -> list[dict]:
    from .orchestrator import load_flow, run_workflow
    from .store import FileStore

    os.environ["OUT_DIR"] = str(out / "run")
    store, flow = FileStore(out / "run"), load_flow()
    cases = json.loads((out / "data" / "cases.json").read_text(encoding="utf-8"))
    return [run_workflow(c, flow, store) for c in cases]


def cell(sr: dict) -> str:
    if sr["state"] == "skipped":
        return "-"
    if sr["state"] == "error":
        return f"ERR {(sr.get('error') or {}).get('code', '')}"[:22]
    return f"{sr['verdict']} {sr['outcome']}"[:22]


def print_table(wfs: list[dict]) -> None:
    head = ["UNIT", "ORG", *[s.upper() for s in STAGES], "FINAL"]
    rows = []
    for wf in wfs:
        by = {sr["stage"]: sr for sr in wf["stage_results"]}
        fo = wf.get("final_outcome") or {}
        final = fo.get("outcome") or f"{wf['status']} (nothing to run)"
        if fo.get("claimable_usd"):
            final += f" ${fo['claimable_usd']:.2f}"
        rows.append([wf["subject_id"], wf["org_id"], *[cell(by[s]) if s in by else "-" for s in STAGES], final])
    widths = [max(len(str(x)) for x in col) for col in zip(head, *rows)]
    for r in [head, *rows]:
        print("  " + "  ".join(str(x).ljust(w) for x, w in zip(r, widths)))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sources", nargs="+", type=Path, help="a folder of CSVs, or the CSV files themselves")
    ap.add_argument("--name", help="dataset name (default: the folder or file name)")
    ap.add_argument("--map", action="append", default=[], metavar="OLD=NEW", help="rename a column, e.g. received_qty=qty_received")
    ap.add_argument("--category", action="append", default=[], metavar="SKU=CAT", help="product category for a SKU (Returns)")
    ap.add_argument("--photos", type=Path, help="folder laid out as <unit>/<stage>/<image>")
    ap.add_argument("--check", action="store_true", help="only check the files; run nothing")
    args = ap.parse_args(argv)

    def pairs(items: list[str], flag: str) -> dict[str, str]:
        bad = [i for i in items if "=" not in i]
        if bad:
            ap.error(f"{flag} needs OLD=NEW, got {bad[0]!r}")
        return dict(i.split("=", 1) for i in items)

    first = args.sources[0]
    name = re.sub(r"[^A-Za-z0-9_-]+", "-", args.name or (first.resolve().name if first.is_dir() else first.stem)).strip("-") or "dataset"
    rep, out, tables = load(args.sources, name=name, maps=pairs(args.map, "--map"),
                            cats=pairs(args.category, "--category"), photos_dir=args.photos)
    for n in rep.notes:
        print(f"  ok    {n}")
    for w in rep.warnings:
        print(f"  note  {w}")
    if rep.errors:
        print("\nThe dataset cannot be run yet:")
        for e in rep.errors:
            print(f"  FIX   {e}")
        return 1
    units = len(json.loads((out / "data" / "cases.json").read_text(encoding="utf-8")))
    print(f"\nDataset '{name}' is valid: {units} unit(s) -> {out}")
    if args.check:
        return 0
    wfs = run(out)
    print(f"\nRan {len(wfs)} workflow(s) through the five agents:\n")
    print_table(wfs)
    print(f"\nEvidence and workflow state: {out / 'run'}")
    print(f"Open it in the UI:  python scripts/dev.py up --dataset {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
