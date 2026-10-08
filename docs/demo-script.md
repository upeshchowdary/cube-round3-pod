# Demo script · Pod 05 (10 minutes)

Follows the handbook's recommended 10-minute demo. Everything shown is the running system: no mock-ups, no
hand-edited JSON. Say out loud which agents run in which mode (the `model` field of every record says it too).

**Before you start** (fresh terminal, no keys on screen, `.env` not open):

```sh
rm -rf out                                    # Windows: Remove-Item -Recurse out
uvicorn orchestration.api:app --port 8100     # terminal 1
cd ui && npm run dev                          # terminal 2 → open the printed URL
```

| Time | Show | How |
|---|---|---|
| 0:00–1:00 | Problem and Pod type: Standard Pod, five members, one commerce chain | Cover page `/`; `pod.json` |
| 1:00–2:30 | Architecture: agents, orchestrator owns state, key decisions | `ARCHITECTURE.md` › Pod 05 diagram; D-012 (re-run on upstream change), D-014 (tenancy at the door), D-015 (synthetic cassettes) |
| 2:30–5:00 | One complete workflow live, case → Final Commerce Outcome; label real vs replay | UI › Run: `org_demo_alpha` / `UNIT-0014` / fba / returned → Receiving `csv-replay`, Prep `rules`, Pack skipped (fba), Returns `synthetic-cassette`, Recovery `rules` → **CLAIM_RECOMMENDED $2.00** |
| 5:00–6:00 | Trace the outcome to a check, an upstream record and an input hash | Workflow detail › Recovery charge `inbound_defect_fee` cites the Prep record → open it → check `fnsku_label_placement` → `inputs[].sha256` / `upstream_refs` |
| 6:00–8:00 | UNCERTAIN → BLOCKED → override → resume; then an injected failure | Run `UNIT-0092` (Returns identity UNCERTAIN → **BLOCKED**) → Override the Returns record (actor + reason) → Resume → Recovery re-runs, **COMPLETED**, original record kept. Failure: stop an agent in HTTP mode (below) → run `UNIT-0016` → **FAILED / INCOMPLETE**, error recorded |
| 8:00–9:00 | One claim with evidence, one SILENT charge left unclaimed | `UNIT-0014`: `inbound_defect_fee` $2.00 CONTRADICTS (claim) vs `fulfilment_fee_weight_tier` $4.75 SILENT (no fee schedule, F-07) |
| 9:00–10:00 | Tests/CI, evaluation, limits | GitHub Actions green; `docs/evaluation.md` (numbers + what was not measured); limits: placeholder captures, synthetic cassettes, replay modes, no live Gemini run |

**Wrong tenant (if asked):** UI › Run `org_demo_bravo` / `UNIT-0014` → refused (404), nothing stored.

**Failure injection in HTTP mode:**

```sh
uvicorn agents.returns.app:app --port 8104      # start it, then stop it (Ctrl+C) to "kill" Returns
ORCH_MODE=http uvicorn orchestration.api:app --port 8100   # other agents: start each on 8101/8102/8103/8105
```

or in-process without servers: `python -m pytest tests/e2e/test_http.py -k dead_agent -v`.

**Fallback:** if the live run fails, play the recording and say it is a recording.

Every member explains their own agent: Receiving (Kiran), Prep (Suhana), Pack (Nikhil), Returns (Upesh),
Recovery (Vishruth). The team explains the orchestrator together.
