"""Per-check TP / TN / FP / FN against human labels (handbook §11, SUBMISSION-GUIDE: docs/evaluation.md).

  python scripts/score_checks.py --template data/labels/labels.csv   # write a blank labelling sheet for the cases
  python scripts/score_checks.py data/labels/labels.csv              # score the agents against the filled sheet

Labelling sheet columns: org_id, unit_id, stage, check_key, input_refs, label_a, label_b, notes.
label_a / label_b are two independent people's answers, PASS or FAIL (blank = not labelled). The sheet deliberately
does not show the agent's verdict, so labellers are not anchored by it.

Scoring: "positive" = FAIL (a problem exists). Agent FAIL & label FAIL = TP, FAIL & PASS = FP, PASS & FAIL = FN,
PASS & PASS = TN. UNCERTAIN is never dropped: it is counted per label value. The label used is label_a where both
agree; rows where the two people disagree are reported, not scored. Cohen's kappa is reported for label_a vs label_b.
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from orchestration.orchestrator import load_flow, run_workflow  # noqa: E402
from orchestration.store import MemoryStore  # noqa: E402

FIELDS = ["org_id", "unit_id", "stage", "check_key", "input_refs", "label_a", "label_b", "notes"]


def run_cases(cases_file: Path) -> dict[tuple, dict]:
    """(org, unit, stage, check_key) -> {verdict, refs} for every completed stage."""
    store, out, flow = MemoryStore(), {}, load_flow()
    for case in json.loads(cases_file.read_text()):
        wf = run_workflow(case, flow, store)
        for sr in wf["stage_results"]:
            if sr["state"] != "completed" or sr["stage"] == "recovery":
                continue
            ev = store.get_evidence(sr["record_id"], wf["org_id"])
            refs = ";".join(i["ref"] for i in ev["inputs"] if i.get("ref"))
            for ch in ev["checks"]:
                out[(wf["org_id"], wf["subject_id"], sr["stage"], ch["check_key"])] = {"verdict": ch["verdict"], "refs": refs}
    return out


def kappa(pairs: list[tuple[str, str]]) -> float | None:
    if not pairs:
        return None
    n = len(pairs)
    po = sum(a == b for a, b in pairs) / n
    cats = {"PASS", "FAIL"}
    pe = sum((sum(a == c for a, _ in pairs) / n) * (sum(b == c for _, b in pairs) / n) for c in cats)
    return None if pe == 1 else round((po - pe) / (1 - pe), 3)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("labels", nargs="?", help="filled labelling sheet (CSV)")
    ap.add_argument("--cases", default=str(ROOT / "data/input/my_cases.json"))
    ap.add_argument("--template", help="write a blank labelling sheet here and exit")
    args = ap.parse_args()
    results = run_cases(Path(args.cases))

    if args.template:
        Path(args.template).parent.mkdir(parents=True, exist_ok=True)
        with open(args.template, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=FIELDS)
            w.writeheader()
            for (org, unit, stage, key), r in sorted(results.items()):
                w.writerow({"org_id": org, "unit_id": unit, "stage": stage, "check_key": key, "input_refs": r["refs"]})
        print(f"wrote {len(results)} rows to {args.template}; fill label_a and label_b (PASS/FAIL) independently")
        return 0
    if not args.labels:
        ap.error("give a filled labelling sheet, or --template PATH")

    counts = collections.defaultdict(collections.Counter)
    disagree, pairs, unlabelled = [], [], 0
    with open(args.labels, newline="", encoding="utf-8-sig") as fh:  # -sig: sheets saved by Excel carry a BOM
        for row in csv.DictReader(fh):
            a, b = row["label_a"].strip().upper(), row["label_b"].strip().upper()
            if a in ("PASS", "FAIL") and b in ("PASS", "FAIL"):
                pairs.append((a, b))
            if a not in ("PASS", "FAIL") or (b and b != a):
                if b and a and b != a:
                    disagree.append(row)
                else:
                    unlabelled += 1
                continue
            got = results.get((row["org_id"], row["unit_id"], row["stage"], row["check_key"]))
            key = f"{row['stage']}.{row['check_key']}"
            if got is None:
                counts[key]["not_run"] += 1
                continue
            v = got["verdict"]
            if v == "UNCERTAIN":
                counts[key][f"UNCERTAIN(label {a})"] += 1
            else:
                counts[key][{("FAIL", "FAIL"): "TP", ("FAIL", "PASS"): "FP", ("PASS", "FAIL"): "FN", ("PASS", "PASS"): "TN"}[(v, a)]] += 1

    print("| check | TP | TN | FP | FN | UNCERTAIN (label PASS) | UNCERTAIN (label FAIL) |")
    print("|---|---:|---:|---:|---:|---:|---:|")
    for key, c in sorted(counts.items()):
        print(f"| {key} | {c['TP']} | {c['TN']} | {c['FP']} | {c['FN']} | {c['UNCERTAIN(label PASS)']} | {c['UNCERTAIN(label FAIL)']} |")
    print(f"\nlabelled by both: {len(pairs)}; Cohen's kappa (label_a vs label_b): {kappa(pairs)}; "
          f"disagreements (not scored): {len(disagree)}; unlabelled rows: {unlabelled}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
