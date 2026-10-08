"""CLI: run workflows, resume them, record overrides.

  python -m orchestration.run --all                                  # every sample case
  python -m orchestration.run --unit UNIT-0014 --org org_demo_alpha  # one workflow, printed in full
  python -m orchestration.run --all --flow orchestration/flow.specialist.json
  python -m orchestration.run --case examples/uncertain-path/case.json
  python -m orchestration.run --resume WF-org_demo_alpha-UNIT-0014
  python -m orchestration.run --override WF-... --record PRP-0014 --verdict PASS --actor you --reason "..." [--and-resume]
State and evidence are written under --out (default $OUT_DIR, else out/): workflows/<id>.json and evidence/<record_id>.json.
"""
from __future__ import annotations

import argparse
import collections
import json
import os
from pathlib import Path

from shared.utils.schema import errors

from .orchestrator import apply_override, default_flow_path, load_flow, resume, run_workflow
from .store import FileStore

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cases", default=str(ROOT / "data/sample/cases.json"))
    ap.add_argument("--case", help="a single case JSON file")
    ap.add_argument("--flow", default=str(default_flow_path()), help="default: the flow named in pod.json")
    ap.add_argument("--out", default=os.environ.get("OUT_DIR") or str(ROOT / "out"))
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--unit")
    ap.add_argument("--org")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--resume")
    ap.add_argument("--override")
    ap.add_argument("--record")
    ap.add_argument("--verdict", choices=["PASS", "FAIL", "UNCERTAIN"])
    ap.add_argument("--actor")
    ap.add_argument("--reason")
    ap.add_argument("--and-resume", action="store_true")
    args = ap.parse_args()

    store, flow = FileStore(args.out), load_flow(args.flow)
    if args.override:
        if not (args.record and args.verdict and args.actor and args.reason):
            ap.error("--override needs --record --verdict --actor --reason")
        wf = apply_override(args.override, store, record_id=args.record, new_verdict=args.verdict,
                            actor=args.actor, reason=args.reason)
        if args.and_resume:
            wf = resume(args.override, flow, store)
        print(json.dumps(wf, indent=2))
        return 0
    if args.resume:
        print(json.dumps(resume(args.resume, flow, store), indent=2))
        return 0

    if args.case:
        cases = [json.loads(Path(args.case).read_text())]
    else:
        cases = json.loads(Path(args.cases).read_text())
        if args.unit:
            cases = [c for c in cases if c["unit_id"] == args.unit and (not args.org or c["org_id"] == args.org)]
        elif not args.all:
            ap.error("pass --all, --unit, --case, --resume or --override")
    cases = cases[: args.limit] if args.limit else cases
    if not cases:
        ap.error("no matching cases")

    outcomes, statuses = collections.Counter(), collections.Counter()
    for case in cases:
        wf = run_workflow(case, flow, store)
        bad = errors("workflow-state", wf)
        if bad:
            raise SystemExit(f"{wf['workflow_id']} produced an invalid Workflow State: {bad[:3]}")
        outcomes[(wf["final_outcome"] or {}).get("outcome")] += 1
        statuses[wf["status"]] += 1
        if len(cases) == 1:
            print(json.dumps(wf, indent=2))
    print(f"\nflow={flow['flow_id']}  workflows={len(cases)}  written to {args.out}")
    print("  final outcome:", ", ".join(f"{k}={v}" for k, v in outcomes.most_common()))
    print("  status:       ", ", ".join(f"{k}={v}" for k, v in statuses.most_common()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
