# Architecture

This document describes the **starter**. At the bottom is a section for **your Pod's architecture**, which you must fill in and which is part of the submission. A submission whose `ARCHITECTURE.md` still only describes the starter has not documented its system.

## 1. The system

```text
                POD
                 │
       ┌─────────▼─────────┐      owns workflow state; derives status and final outcome from the evidence chain
       │    Orchestrator   │      routes · validates · records evidence · retries · handles failures and UNCERTAIN
       └─────────┬─────────┘
                 │  Agent Input ▼          ▲ Agent Output (evidence)
       ┌─────────▼─────────┐
       │     Receiving     │
       └─────────┬─────────┘
                 ↓
       ┌───────────────────┐
       │       Prep        │   (FBA units)
       └─────────┬─────────┘
                 ↓
       ┌───────────────────┐
       │       Pack        │   (merchant-fulfilled / 3PL units)
       └─────────┬─────────┘
                 ↓
       ┌───────────────────┐
       │      Returns      │   (if a return happened)
       └─────────┬─────────┘
                 ↓
       ┌───────────────────┐
       │     Recovery      │   reads ALL accumulated evidence
       └─────────┬─────────┘
                 ↓
          Final Outcome        derived by the orchestrator, not copied from any agent

  shared/schemas · shared/contracts · shared/utils      data/input · data/sample · data/expected      examples/
```

The arrows show the *expected commerce journey*. Physically, every hand-off goes through the orchestrator ([`INTEGRATION-GUIDE.md`](INTEGRATION-GUIDE.md) section 1).

## 2. Responsibilities

| Component | Responsible for | Not responsible for |
|---|---|---|
| **Agent** (`agents/<stage>/`) | One stage's judgment, returned as an Agent Output with an Evidence Record. Failing open. Refusing other tenants. | Calling other agents. Setting workflow state. Rewriting earlier evidence. |
| **Orchestrator** (`orchestration/`) | Starting workflows; identifying the current stage; invoking agents with context; validating and recording evidence; updating state; routing; retries; failures; UNCERTAIN; the final outcome. | Making stage judgments. Fabricating or deleting evidence. Turning UNCERTAIN into PASS/FAIL without an explicit rule. |
| **Contract** (`shared/schemas/`) | One strict set of data shapes. | Agent-specific logic (that goes in `payload`). |
| **Stubs** (`agents/*/app.py` as shipped) | Replaying Round 2 CSV rows as valid evidence, so the plumbing can be tested. | Pretending to be agents. |

## 3. Shared data

| Object | Owner | Lives in |
|---|---|---|
| Evidence Record | the agent that produced it (immutable) | the evidence store |
| Workflow State | **the orchestrator** | the workflow store |
| Overrides | the orchestrator records them; a person makes them | Workflow State (`overrides[]`), referencing evidence |
| Final Outcome | **the orchestrator**, derived | Workflow State (`final_outcome`) |
| Captures | the Pod | `data/input/<subject>/<stage>/`, referenced by `sha256` |

## 4. Evidence flow and workflow state

```text
Agent Result → Evidence Record → Orchestrator state transition → Next stage → New evidence → Updated workflow state → Final Outcome
```

- Each stage's evidence is stored and passed to **every later stage** as `previous_evidence`.
- State is `PENDING → IN_PROGRESS → COMPLETED`, or `FAILED` / `BLOCKED` / `RECOVERY_REQUIRED` ([`ORCHESTRATION-GUIDE.md`](ORCHESTRATION-GUIDE.md) section 5), always derived from the evidence and overrides.
- `transitions[]` is the audit trail.
- A reviewer can walk from the Final Outcome to `contributing_records`, to checks, to `evidence_refs`, to the `sha256` of the exact bytes examined.

## 5. Error handling

Every failure is **recorded and never becomes success**: a degraded evidence record stands in (no checks, UNCERTAIN, the error), the stage is `error`, the workflow `FAILED` with outcome `INCOMPLETE`. Transient failures retry; refusals and invalid output do not; UNCERTAIN is preserved; `resume` retries. Full table: [`ORCHESTRATION-GUIDE.md`](ORCHESTRATION-GUIDE.md) section 8. Tenancy: `org_id` on every request, record and workflow; a record about another org is rejected as a security event; **your storage must enforce it too**.

## 6. Final outcome

`CLEAN`, `CLAIM_RECOMMENDED`, `EXCEPTION`, `NEEDS_REVIEW` or `INCOMPLETE`, with the reason, the contributing evidence, `needs_human`, and `provisional` (true unless the workflow is `COMPLETED`). Default rules: [`ORCHESTRATION-GUIDE.md`](ORCHESTRATION-GUIDE.md) section 6.

## 7. What is fixed and what is yours

**Fixed (the contract, strict):**

- The five required agents and their stages (Specialist Pods: four agents plus integration work, see [`FAQ.md`](FAQ.md))
- Common evidence requirements: the Agent Input/Output and Evidence Record shapes; PASS / FAIL / UNCERTAIN; the status vocabularies
- Required traceability: workflow id, agent id, hashes, `upstream_refs`, overrides that reference what they supersede
- An orchestrator that owns workflow state and produces a **Final Outcome**
- Minimum testing, and the submission and evaluation requirements ([`SUBMISSION-GUIDE.md`](SUBMISSION-GUIDE.md), [`ROUND3-RUBRIC.md`](ROUND3-RUBRIC.md))

**Participant-designed (the implementation, flexible):**

- Internal architecture, programming language, frameworks, how each agent is built
- How the orchestrator is implemented (the starter is one option; LangGraph, a queue, a state machine, your own)
- The communication mechanism (in-process, HTTP, queue) as long as the contract holds
- Database, persistence, deployment platform
- UI, review queue, dashboards
- Additional services, additional features
- The final-outcome policy, routing and `on_uncertain` / `on_error` policies (documented in `docs/decisions.md`)

## 8. Extension points

| You want to… | Change |
|---|---|
| Add or reroute a stage | `orchestration/flow.json` (and write a decision) |
| Change the final decision or status rules | `orchestration/rollup.py` (and its tests, and a decision) |
| Plug in a real agent | `agents/<stage>/app.py` + `agent.json` |
| Run an agent as a service in any language | `agent.json` `mode: "http"` + [`agent-api.md`](shared/contracts/agent-api.md) |
| Run your own subjects | `data/input/<subject>/<stage>/` + a cases file |
| Add agent-specific data to evidence | `payload` (never the envelope) |
| Persist to a database | implement the four store methods in `orchestration/store.py` |

## 9. Deployment options (yours)

- **Single process:** `uvicorn orchestration.api:app` with all agents `inproc`. Simplest.
- **Orchestrator + agent services:** each agent its own process, `mode: "http"`, `<STAGE>_URL` set; `GET /health` for readiness.
- Whatever you pick, the demo runs from the submitted commit and any URL works without your accounts. The API ships with **no authentication**: add it before exposing it.

---

## Pod 05 architecture

### 1. Components and flow

```text
 UI (React, ui/)  ──/api──▶  Orchestrator API (FastAPI, orchestration/api.py :8100)
                                   │  404 for unknown / wrong-tenant subjects (no workflow created)
                                   ▼
                        Orchestrator (orchestration/orchestrator.py)  ──▶  FileStore out/workflows, out/evidence
                                   │ route by case: route = fba | mfn, returned = true | false
   ┌───────────────┬───────────────┴───────────────┬─────────────────┬───────────────────┐
   ▼               ▼ (fba)                         ▼ (mfn)           ▼ (returned)        ▼
 Receiving  ──▶  Prep  ─────────────────────or──▶ Pack ─────────▶  Returns  ─────────▶  Recovery
 PO-line checks   6 prep rules                    box vs order     identity, parts,     fee lines vs all
                                                                   grade, disposition   earlier evidence
   each agent: in-process handle(request) (default) or HTTP /run; every one gets ALL previous evidence + overrides
```

### 2. What each agent really is

| Agent (owner) | Default mode (no keys) | Live mode | Status |
|---|---|---|---|
| Receiving (@KiranTejz20005) | Round 2 deterministic decision engine over the CSV operator observations; `model.name = csv-replay` | `RECEIVING_MODEL_MODE=live` + `GEMINI_API_KEY`: one Gemini 2.5 Flash call over the receiving captures | integrated; no receiving captures committed |
| Prep (@mdsuhana231-gif) | deterministic rules over recorded prep observations; `rules` | none (no vision): captures without observations are UNCERTAIN | integrated |
| Pack (@nikhilagarwal03) | reconciliation engine over the CSV `observed_in_box`; `csv-replay` | `OPENROUTER_API_KEY` (Llama 3.2 90B Vision) or `GROQ_API_KEY` (`qwen/qwen3.8-27b`): one call per box, 6 s fail-open | integrated; live path tested once via Groq |
| Returns (@upeshchowdary) | Round 2 pipeline over cassettes. The 8 committed cassettes are hand-authored over placeholder images: `synthetic-cassette (hand-authored, no model run)` | `RETURNS_MODEL_MODE=live|record` + `GEMINI_API_KEY` | integrated; needs real photos + recorded cassettes |
| Recovery (@vishruth-16) | deterministic rules per charge type against upstream evidence; `rules` | `RECOVERY_MODEL_MODE=live`: one batched Gemini call for charge types no rule covers; a model claim must cite a real record | integrated |

No organiser stub remains in the flow. Every record's `model` says what actually ran (D-013, D-015).

### 3. Orchestrator

The organiser's engine, kept: it owns workflow state; agents only return evidence. Each stage gets the subject, its
captures (`data/input/<unit>/<stage>/`, sha256-hashed), every earlier evidence record and the workflow's overrides.
Outputs are validated (schema, stage, workflow, tenant, content hash, output/evidence agreement) before they are
stored. State and evidence are JSON files under `out/` (atomic writes), so a restart resumes where it stopped. Retries:
1 for timeouts / unavailable agents, never for refusals. Evidence is immutable: reusing a `record_id` for different
content is rejected (D-012). Overrides are workflow entries that reference a record and the previous effective verdict
(D-004); downstream agents read the effective verdict. Returns and Recovery are re-run on `resume` when their upstream
evidence or an override of it changed after they ran (D-012). An agent that cannot even be imported becomes an error
record for its stage (D-014).

### 4. Routing and final outcome

`orchestration/flow.json`: Receiving always; Prep for `fba`; Pack for `mfn`; Returns if the unit came back; Recovery
always. `on_uncertain: continue`, `on_error: continue` (D-002, D-003), so Recovery always sees what exists. Status
precedence (rollup.py): any stage in error → FAILED; FAIL with no Recovery → RECOVERY_REQUIRED; UNCERTAIN that asks for
a person → BLOCKED; else COMPLETED. Weak evidence never becomes a claim: Recovery claims only CONTRADICTS lines with
a cited record; SILENT lines are listed and never claimed (D-005, D-007, D-010).

### 5. Tenancy

Enforced three times: the API refuses subjects unknown to the org (404, nothing stored); every agent looks its subject
up scoped by `org_id` and raises → `agent_rejected`; the orchestrator rejects any output whose evidence names another
org or subject. Tested in `tests/integration/test_agent_contracts.py`, `tests/e2e/test_http.py`, `tests/e2e/test_api.py`;
200/200 cross-org requests refused in the evaluation run.

### 6. Failure model (demo)

Kill an agent (stop its HTTP server, or `ORCH_MODE=http` with one URL down): its stage becomes a recorded error, the
rest of the flow still runs, the workflow is FAILED with a provisional INCOMPLETE outcome, never a success; `resume`
after restarting it re-runs the stage and the downstream judges. Numbers: `docs/evaluation.md`.

### 7. Deployment

Local: `make setup` (or `python -m venv .venv && pip install -r requirements.txt`), `uvicorn orchestration.api:app --port 8100`,
`cd ui && npm ci && npm run dev` (Vite proxies `/api` to `ORCH_API_URL`, default `http://localhost:8100`). Agents run
in-process by default; each can run alone with `uvicorn agents.<stage>.app:app --port 810N`. No authentication: do not
expose the API publicly as is.

### 8. Known limits

No real captures are committed; Returns' demo cassettes are synthetic; Receiving and Pack replay CSV observations by
default; Prep has no vision; live Gemini modes were not run (no key); no held-out labelled evaluation. See
`docs/evaluation.md`.
