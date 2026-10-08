# Cube Buildathon · Round 3 · Pod Integration Build

**Commerce Context stream · Round 3 · Pod build**

> Five agents, one unit, one record that follows it. In Round 3 your Pod connects the five Round 2 agents into **one commerce system**.

**New here? Read [`START-HERE.md`](START-HERE.md) first.** This README is the concise overview; the detailed rules live in the guides.

## Objective

Integrate the five independently built Round 2 agents into one connected, end-to-end commerce workflow, and show it working. **Integrate → Orchestrate → Test → Deploy → Demonstrate.** Not a rebuild.

## What the Pod builds

```text
Receiving → Prep → Pack → Returns → Recovery → Final Commerce Outcome
```

| Member | Agent | Folder |
|---|---|---|
| 1 | Receiving Manager | `agents/receiving/` |
| 2 | Prep Manager | `agents/prep/` |
| 3 | Pack Manager | `agents/pack/` |
| 4 | Returns Manager | `agents/returns/` |
| 5 | Recovery Manager | `agents/recovery/` |

Each member owns one agent. The Pod jointly owns the orchestration, shared contracts, workflow state, integration, end-to-end testing, documentation, demo and submission. **No participant owns the final system alone.**

## Architecture in one picture

```text
              ┌────────────────────────── Orchestrator (owns workflow state) ───────────────────────────┐
 case ──────▶ │ route · pass previous evidence · validate · record evidence · retry · UNCERTAIN · outcome │ ──▶ Workflow State
              └────┬─────────┬─────────┬─────────┬─────────┬────────────────────────────────────────────┘      + Final Outcome
        Agent Input ▼         │         │         │         │  ▲ Agent Output (result + Evidence Record)
              Receiving     Prep      Pack     Returns   Recovery     ← each: in-process handle()  OR  HTTP /health + /run
```

- **One contract.** Every agent takes an *Agent Input* and returns an *Agent Output* containing an *Evidence Record*: per-check verdicts (PASS / FAIL / **UNCERTAIN**), confidence, model/version, timestamps, hashes.
- **One owner of state.** The orchestrator derives workflow status and the final outcome from the evidence chain. Agent outputs inform; they do not set state.
- **Failures are recorded, never hidden,** and never become success.

Details: [`ARCHITECTURE.md`](ARCHITECTURE.md) · [`INTEGRATION-GUIDE.md`](INTEGRATION-GUIDE.md) · [`ORCHESTRATION-GUIDE.md`](ORCHESTRATION-GUIDE.md).

## Quick setup and how to run

Requires Python 3.11+.

```sh
make setup            # venv + dependencies + .env
make test             # integration, end-to-end, failure, UNCERTAIN, override and HTTP tests
make run              # all sample workflows end to end -> out/workflows/*.json and out/evidence/*.json
make case UNIT=UNIT-0014 ORG=org_demo_alpha     # one workflow, in full
make serve            # orchestrator API on :8100 (POST /workflows, GET /workflows/{id}, GET /health)
```

**Pod 05:** all five stages run the members' Round 2 agents (no organiser stub left). With no API keys they run in their offline modes, and every record's `model` says so: Receiving and Pack replay the CSV observations (`csv-replay`), Prep and Recovery are deterministic rules (`rules`), Returns replays cassettes (the 8 committed ones are hand-authored over placeholder images: `synthetic-cassette`). Live model modes and their keys are in `.env.example`. What each agent really is: [`ARCHITECTURE.md` › Pod 05 architecture](ARCHITECTURE.md#pod-05-architecture); numbers and limits: [`docs/evaluation.md`](docs/evaluation.md).

UI: `uvicorn orchestration.api:app --port 8100`, then `cd ui && npm ci && npm run dev` (Vite proxies `/api` to the orchestrator). On Windows use `.venv\Scripts\python -m …` in place of `.venv/bin/…`.

Run an agent as its own service:

```sh
.venv/bin/uvicorn agents.prep.app:app --port 8102
curl localhost:8102/health          # then set "mode": "http" in agents/prep/agent.json
```

## Where participants put their agents

`agents/<stage>/` (`app.py` exposes `handle()`; `agent.json` describes your agent). Shared areas need Pod-level coordination: `orchestration/`, `shared/`, `tests/`, `docs/`. See [`PARTICIPANT-GUIDE.md`](PARTICIPANT-GUIDE.md).

## How the agents connect

Through the orchestrator only. It sends each agent an Agent Input (subject, this stage's captures, **all previous evidence**, overrides), validates and stores the Agent Output's evidence, updates workflow state, and decides what runs next. See [`INTEGRATION-GUIDE.md`](INTEGRATION-GUIDE.md).

## Required environment variables

Copy `.env.example` to `.env`. **Never commit `.env`.**

| Variable | Purpose | Default |
|---|---|---|
| `ORCH_MODE` | Force `inproc` or `http` for all agents | each `agent.json` |
| `ORCH_FLOW` | Flow file for the API | the flow in `pod.json` |
| `<STAGE>_URL` | Where an `http`-mode agent listens (`PREP_URL`, …) | `agent.json` `url` |
| `OUT_DIR` | Where workflow state and evidence are written | `out` |
| `DATA_DIR`, `INPUT_DIR` | Sample CSVs for the stubs; your per-stage captures | `data/sample`, `data/input` |
| `LOG_LEVEL`, `LOG_FORMAT` | Logging | `WARNING`, `json` |
| Model provider keys | Whatever *your* agents use (e.g. `ANTHROPIC_API_KEY`) | none |

## Example end-to-end workflow

`UNIT-0014` (FBA, returned), as the Pod's agents produce it (`make case UNIT=UNIT-0014 ORG=org_demo_alpha`).

```text
Receiving  RCV-0014                              accept             PASS   ─┐  csv-replay
Prep       PRP-WF-org_demo_alpha-UNIT-0014-prep  compliant          PASS    │  rules     every record is stored and
Pack       skipped (route = fba: Amazon packs it)                           │            handed forward as previous_evidence
Returns    RTN-7b7ce61f9db70424                  liquidate          PASS   ─┤  synthetic-cassette (R11, Used - Like New)
Recovery   RCY-UNIT-0014                         claim_recommended  FAIL ◀─┘  rules
             • inbound_defect_fee               $2.00  CONTRADICTS  <- cites the Prep record (Prep says compliant)
             • fulfilment_fee_weight_tier       $4.75  SILENT       <- no fee schedule looked up; NOT claimed (F-07)
             • lost_inbound / refund_not_returned  $0  SILENT       <- nothing to claim (F-09, F-10, F-11)
Workflow status COMPLETED · Final outcome CLAIM_RECOMMENDED ($2.00, evidence attached)
```

The organiser's stub-based reference files are in [`examples/end-to-end/`](examples/end-to-end/). Also see [`examples/happy-path/`](examples/happy-path/), [`examples/uncertain-path/`](examples/uncertain-path/), [`examples/failure-path/`](examples/failure-path/).

## Repository structure

```text
START-HERE.md  README.md  PARTICIPANT-GUIDE.md  GITHUB-GUIDE.md  RULES.md  FAQ.md
ARCHITECTURE.md  INTEGRATION-GUIDE.md  EVIDENCE-CONTRACT.md  ORCHESTRATION-GUIDE.md
ROUND3-RUBRIC.md  SUBMISSION-GUIDE.md  DEMO-GUIDE.md  pod.json  .env.example
agents/{receiving,prep,pack,returns,recovery}/   app.py · agent.json · README.md
orchestration/       flow.json · orchestrator.py · rollup.py · store.py · clients.py · run.py (CLI) · api.py
shared/schemas/      agent-input · agent-output · evidence · workflow-state · final-outcome · error
shared/contracts/    agent-api.md        shared/utils/   hashing · schema validation · record builders · logging · server
data/input/ (yours) · data/sample/ (Round 2 synthetic CSVs) · data/expected/ (golden outcomes for the stubs)
examples/{happy-path,uncertain-path,failure-path,end-to-end}/      tests/{integration,e2e}/      docs/{build-log,decisions}.md
```

## Submission overview

Your Pod's final repository (tagged), a working integrated system, documentation and architecture, a demo, a deployment URL if applicable, evaluation and testing evidence, and the LinkedIn post URL. The literal checklist, the process and the finality rules are in [`SUBMISSION-GUIDE.md`](SUBMISSION-GUIDE.md). Dates and the submission form are **TBA**.

---

*CUBE Buildathon · Commerce Context · Round 3*
