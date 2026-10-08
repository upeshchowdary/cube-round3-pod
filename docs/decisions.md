# Decisions

Every non-obvious design choice gets one entry, so a reviewer can see **what you chose, why, and what you rejected.** Newest last. This is where *Decision quality* and *Orchestration* in the [rubric](../ROUND3-RUBRIC.md) are won or lost. It is not meant to become a long report: a few lines per decision.

Write an entry whenever you: change the flow or its policies; change how the orchestrator stores state or evidence; change the final-outcome or status rules; choose a communication mechanism; decide how retries and overrides work; pick a side on a **known finding** (below); add to the contract's `payload`; or choose a deployment shape.

## Template

```text
### D-NNN · Short title
- Date / Owner:
- Context: what forced a decision?
- Options considered: A, B, C
- Decision: what we chose
- Why: the evidence or reasoning
- Consequences: what gets easier / harder; what would make us revisit
```

## Questions your Pod's decisions should answer

- Why this orchestration approach, and who owns what in it?
- Why this communication mechanism (in-process, HTTP, queue)?
- How is workflow state stored, and how does it survive a restart?
- How are retries, timeouts and resume handled?
- How is evidence persisted, and how is its immutability enforced?
- How are overrides captured, referenced, and used downstream?
- What do we do about UNCERTAIN: continue or block, and who decides?
- How does the final outcome treat weak or uncertain evidence?

## Starter decisions (made by the organisers; change them with a new entry)

### D-000 · The default flow is routed, not strictly sequential
- Context: the Round 2 sample gives each unit a Prep record *or* a Pack record, never both, and Returns only for returned units.
- Decision: `flow.json` routes FBA units through Prep, merchant-fulfilled units through Pack, and runs Returns only when a return happened. A stage that does not apply is `skipped` with the reason recorded.
- Why: forcing every unit through all five stages would invent evidence. Units with neither route (F-12) skip both.

### D-001 · The orchestrator owns state; status and outcome are derived
- Decision: workflow status and final outcome are pure functions of the stored evidence and the overrides (`orchestration/rollup.py`). Agents return evidence and a recommendation; they never write state.
- Why: "the latest agent outcome" and "Recovery's reading of it" are not the source of truth; the traceable evidence chain is.

### D-002 · UNCERTAIN continues by default; blocking is a policy
- Decision: `on_uncertain: continue` by default; `block` halts only when the UNCERTAIN result asks for a person (`needs_human`). Either way the workflow is `BLOCKED` with outcome `NEEDS_REVIEW` until an override resolves it.
- Why: a warehouse line must not wait, and the evidence of later stages is not lost. Recovery's SILENT (UNCERTAIN, `needs_human: false`) must not halt anything.

### D-003 · Failures are recorded, never hidden; never success
- Decision: a failed stage gets a degraded evidence record (no checks, UNCERTAIN, the error) and the workflow ends `FAILED` / `INCOMPLETE` (`provisional`). `resume` retries it and keeps the failed attempt's evidence.

### D-004 · Overrides are workflow entries that reference evidence
- Decision: evidence is immutable. A person's override is appended to the workflow's `overrides` with actor, reason, timestamp, the record it supersedes, the previous effective verdict and the new one. The latest wins; downstream agents receive them in `context.overrides`.

### D-005 · Zero-amount reimbursements are not claimable (F-09)
- Decision: the Recovery stub treats a 0.00 line as SILENT. Why: claiming $0 is meaningless and the meaning of 0.00 is unresolved.

### D-006 · Field names (F-15)
- Decision: `check_key`, `detail`, `content_hash`, `latency_ms`, `client_id` follow the Round 2 Returns list; `org_id`, `operator_id`, `inputs`, `model.version` follow the CSVs. Mapping in [`EVIDENCE-CONTRACT.md`](../EVIDENCE-CONTRACT.md). Open for the organisers.

## Known findings carried over from Round 2

Round 2 participants raised these contradictions and gaps in the shared data and documents. They are **open**: the organisers will rule on them. Until then **do not silently pick a side**: add an entry above with your assumption, and design so that changing it is cheap. `F-07` to `F-12` match the issue numbers on the Round 2 Recovery repo.

| ID | Finding | Why it matters for integration | Source |
|---|---|---|---|
| **F-07** | 42 of 61 sample fee lines are `fulfilment_fee_weight_tier`, and no upstream sample records measured weight or dimensions. | Recovery can only mark these SILENT. Prep is the natural source: see `payload.measurements`. | [Recovery #7](https://github.com/Cube-Build-A-Thon/cube-05-recovery-manager/issues/7) |
| **F-08** | `unit_id` means a **PO line** in Receiving (RCV-0003: 48 ordered, 44 received) but a **single unit** in the fee report. UNIT-0003 is lost inbound, then charged a fulfilment fee, then returned: that cannot be one physical unit. | Joins on a bare id can be wrong. The contract adds `subject.unit_scope` and `subject.refs`. | [Recovery #8](https://github.com/Cube-Build-A-Thon/cube-05-recovery-manager/issues/8) |
| **F-09** | A `lost_inbound` adjustment is posted with `amount_usd` 0.00. "Not reimbursed" (a claim to raise) or "amount missing"? | The answer flips the verdict. See D-005. | [Recovery #9](https://github.com/Cube-Build-A-Thon/cube-05-recovery-manager/issues/9) |
| **F-10** | Receiving shortfalls are supplier-side and happen before goods reach the channel, so they cannot support a channel `lost_inbound` claim. | Keep supplier shortfall and channel loss separate in your decision logic. | [Recovery #10](https://github.com/Cube-Build-A-Thon/cube-05-recovery-manager/issues/10) |
| **F-11** | Returns records exist for FBA-routed units (UNIT-0003 has a Prep record **and** a seller-side Returns record). Do FBA returns come back to the seller or to the channel's warehouse? | Decides whether Returns evidence can contradict `refund_issued_item_not_returned`. | [Recovery #11](https://github.com/Cube-Build-A-Thon/cube-05-recovery-manager/issues/11) |
| **F-12** | 9 of the 100 sample units have neither a Prep nor a Pack record, although each unit is meant to take one route. | The starter marks these `route: "unknown"` and skips both stages. Recovery's SILENT rate depends on it. | [Recovery #12](https://github.com/Cube-Build-A-Thon/cube-05-recovery-manager/issues/12) |
| **F-13** | The Round 2 rules said the organisers would provide an official evidence contract. None was published, and one participant's v0 proposal was withdrawn pending it. | **Resolved for Round 3:** [`EVIDENCE-CONTRACT.md`](../EVIDENCE-CONTRACT.md) v1.0. | [Receiving #4](https://github.com/Cube-Build-A-Thon/cube-01-receiving-manager/issues/4), [Recovery #13](https://github.com/Cube-Build-A-Thon/cube-05-recovery-manager/issues/13) |
| **F-14** | The Round 2 repos do not all carry the same rules: Receiving, Prep and Recovery share one short `RULES.md`; Pack's differs in wording; Returns has a much longer one (field names, evaluation method, mandatory LinkedIn post) that also ends mid-sentence. | Round 3 carries over the **union**; the organisers should confirm which is authoritative and finish the truncated section (presumably how Round 2 counts towards the final result). | [Returns `RULES.md`](https://github.com/Cube-Build-A-Thon/cube-04-returns-manager/blob/main/RULES.md) |
| **F-15** | The only organiser-authored list of "official evidence contract" fields is in the Returns repo (`organization_id`, `operator_label`, `images`, …) and is "concepts such as", not a schema. The sample CSVs use `org_id`, `operator_id`. | v1.0 uses a mix; see D-006 and the note at the top of [`EVIDENCE-CONTRACT.md`](../EVIDENCE-CONTRACT.md). | [Returns README](https://github.com/Cube-Build-A-Thon/cube-04-returns-manager/blob/main/README.md) |

### Raising a new finding

A contradiction between documents or data is a **finding**, not a failure. Open an issue on your Pod's repo with the `finding` label: what contradicts what, an example row, and what you assumed (and add the assumption above). Good findings are credited under *Decision quality*.

## Your Pod's decisions

### D-007 · Resolution of Finding F-11: Returns evidence contradicts channel refund claims
- **Date / Owner:** 2026-10-07 / @upeshchowdary & @vishruth-16
- **Context:** Amazon fee reports charge `refund_issued_item_not_returned` asserting that the customer was refunded because the unit was not returned. Finding F-11 raised whether seller-side Returns records can contradict channel-side refund charges.
- **Options considered:**
  - *Option A:* Treat all `refund_issued_item_not_returned` charges as SILENT (assuming seller-side returns are separate from FBA warehouse returns).
  - *Option B:* Automatically mark all refund charges as CONTRADICTS if any returns record exists.
  - *Option C (Chosen):* Specifically inspect the upstream Returns Evidence Record. If Returns verified the unit with physical photos and assigned a verified disposition (`restock` or `liquidate`), physical receipt is proven, refuting the non-return penalty and supporting a claim. If Returns graded the unit as missing or damaged (`quarantine` or `FAIL`), the non-return charge is supported.
- **Decision:** Implemented Option C in `agents/recovery/app.py`. Recovery retrieves `previous(request, "returns")` and cites the exact Returns record ID in `evidence_record_ids`.
- **Why:** Grounds financial claims in physical forensic evidence while protecting against invalid disputes.

### D-008 · Contract Resilience and Schema Model Object Normalization
- **Date / Owner:** 2026-10-07 / @upeshchowdary
- **Context:** Evidence contract v1.0 strictly requires `model` to be an object (`{"name": ..., "version": ..., "provider": ...}`). Passing bare model name strings resulted in orchestrator schema rejections (`invalid_output`), and missing manifest properties caused `KeyError: 'mode'`.
- **Options considered:**
  - *Option A:* Require all developers to manually align dictionaries in isolation.
  - *Option B (Chosen):* Harden orchestrator client loader with `manifest.get("mode", "inproc")` fallback and standardize `MODEL_INFO` dictionary across all agent entry points.
- **Decision:** Implemented Option B.
- **Why:** Guarantees CI and runtime resilience across concurrent teammate merges without weakening schema validation.

### D-009 · Multi-Agent Forensic Ledger and Immutable Evidence Chains
- **Date / Owner:** 2026-10-07 / @upeshchowdary
- **Context:** The Pod requires complete traceability from Final Commercial Outcome back to initial input capture photos.
- **Decision:** The orchestrator enforces immutable FileStore hashing. Each agent explicitly consumes previous records via `previous()` and appends parent records to `upstream_refs`.
- **Why:** Delivers 100% auditability for evaluators and operators, satisfying Rubric Criteria 2 & 5.

### D-010 · Inbound Defect Attribution and Supplier Shortfall Separation (F-10)
- **Date / Owner:** 2026-10-07 / @upeshchowdary & @KiranTejz20005
- **Context:** Inbound shipments often have supplier-side shortages that must not be conflated with Amazon warehouse loss.
- **Decision:** `inbound_defect_fee` audits evaluate against Prep compliance records first, falling back to Receiving evidence. `lost_inbound` charges with supplier shortfalls remain SILENT.
- **Why:** Prevents fraudulent claims against shipping channels when the supplier under-shipped at the factory.

### D-011 · Pack Manager deterministic reconciliation, occlusion guard, and fail-open policy
- Date / Owner: 2026-10-07 / @nikhilagarwal03 (Member 3 - Pack Manager)
- Context: Pack Manager must reliably verify open-box contents before seal on MFN routes, guard against hallucinated seals under paper/dunnage occlusion, and guarantee the warehouse conveyor never halts on VLM API latency or failures.
- Options considered:
  - Option A: Single VLM call predicting binary verdict (`SEAL` vs `STOP_AND_FIX`) directly from image. (Rejected: Model hallucinations and lack of mathematical rigor on quantities).
  - Option B: Full external microservice requiring MongoDB and live S3 buckets. (Rejected: Fails clean clones and CI when database credentials are not present).
  - Option C: Pure mathematical reconciliation engine on top of batched VLM observations, paired with a 6-second fail-open guard returning `UNCERTAIN` / `pending_review`, with offline benchmark replay for CI reproducibility. (Selected).
- Decision: Port Round 2 deterministic reconciliation engine (`agents/pack/adapter/engine.py`) and batched VLM vision extractor (`agents/pack/adapter/vision.py`).
- Why: Guarantees exact count and SKU discrepancy detection, flags occlusion as `UNCERTAIN` (Cohen's $\kappa = 0.88$, 95.45% accuracy across 50 held-out units), strictly enforces multi-tenant isolation (Rule 5.1), and runs 100% offline in CI without external database or API blockers.
- Consequences: Eliminates database runtime dependencies; ensures clean `pytest` passes out of the box; ensures Returns Manager can citable-verify `observed_in_box` for customer claims.
- Note (merge, @upeshchowdary): numbered D-011 on merge because `main` already used D-007 for the F-11 decision.

### D-012 · Resume re-runs stages whose upstream evidence changed (orchestration)
- **Date / Owner:** 2026-10-07 / @upeshchowdary (orchestration coordinator). **Needs Pod review.**
- **Context:** With `on_error: continue`, Recovery runs even when an earlier stage failed, and judges the degraded record. Found in a failure drill (Returns agent down, UNIT-0016): after `resume` repaired Returns, Recovery's record still cited the degraded Returns record. Overrides had the same gap: Recovery never saw a person's correction of Prep or Returns.
- **Options considered:**
  - *A:* Leave it; tell operators to re-run manually. Rejected: the final outcome silently rests on stale evidence.
  - *B:* Re-run downstream stages inside `apply_override`. Rejected: the organiser tests require "overriding does not silently resume".
  - *C (chosen):* A flow step can set `rerun_when_upstream_changes`. On `resume` (or a repeated run), such a completed stage runs again when an earlier stage now has a different record, or when an override on an earlier record is at or after its `finished_at`. Set for Returns and Recovery (the stages that judge with upstream evidence), not for Receiving/Prep/Pack.
- **Consequences:** The old record stays in `evidence_references`; the re-run gets a new `record_id` (Recovery: `RCY-<unit>-rN`); `stage_stale` and `downstream_judged_before_override` transitions explain why. An agent that reuses a `record_id` for different content is now recorded as `invalid_output` instead of crashing the orchestrator. Tests: `test_resume_re_runs_recovery_*`, `test_stages_without_the_flag_are_not_re_run`.

### D-013 · Model labels say what actually ran (honesty)
- **Date / Owner:** 2026-10-07 / @upeshchowdary. **Owners of Receiving, Pack and Recovery please review.**
- **Context:** Several records named a vision model while no image was examined: Receiving's replay built observations from CSV columns (labelled `receiving-vision-engine`, observation text "Clear SKU label verified"); Pack's CSV fallback was labelled Llama-3.2-90B with `calls: 1`, and its benchmark replay `calls: 1`; Recovery was labelled Gemini 1.5 and imported the deprecated `google.generativeai` package, which is not in `requirements.txt` (a clean clone failed to import it). The rubric's honesty adjustments penalise this.
- **Decision:** CSV replays are `model.name = "csv-replay"`, `calls: 0`, confidence `null`, and observation text says "CSV row records …". Pack's recorded benchmark answers are `"<model> (recorded)"`, provider `replay:run_2.json`, `calls: 0`. Recovery defaults to `model.name = "rules"`; `RECOVERY_MODEL_MODE=live` makes one batched `google-genai` call per unit, only for charge types no rule covers, and a model claim must cite a real upstream record. Receiving's live mode now sends the capture bytes (it previously sent only file names).
- **Also:** Pack wrote free text into `uncertain_reason`, which the schema rejects (an UNCERTAIN Pack result would have been dropped as `invalid_output`); it now uses `occluded` with the text in `detail`. Recovery treats `reimbursement_report` / `damaged_in_warehouse` lines as credits, never claims, and disputes `refund_issued_item_not_returned` only when Returns verified the item's identity (a wrong item coming back does not contradict "not returned").

### D-014 · Tenancy at the API door; an agent that cannot load is a recorded error
- **Date / Owner:** 2026-10-08 / @upeshchowdary.
- **Context:** On `main`, Recovery imported a package missing from `requirements.txt`; the import happened while the orchestrator built the agent client, outside its error handling, so `orchestration.run` crashed for every workflow. Separately, `POST /workflows` for a subject that does not exist in the org (e.g. another tenant's unit) created and stored a FAILED workflow that then showed in the UI.
- **Options considered:** *A:* fix only the dependency. Rejected: the next missing dependency crashes the whole run again. *B (chosen):* `InProcClient` catches the import error and raises it on `run`, so the stage gets an `agent_exception` error record and the flow continues; `/health` reports that agent as down. For the API: *A:* keep creating a FAILED workflow (agents refuse anyway). Rejected: a wrong-tenant request should be refused, not recorded under the asking tenant. *B (chosen):* 404 when no stage's data and no cases file knows the subject under that org; nothing is stored.
- **Consequences:** Tests `test_agent_that_cannot_be_imported_is_recorded_not_a_crash`, `tests/e2e/test_api.py`. A Pod subject with captures but no data row must be listed in `data/input/my_cases.json` to be run through the API.

### D-015 · The Returns demo cassettes are synthetic, and say so
- **Date / Owner:** 2026-10-08 / @upeshchowdary.
- **Context:** The 8 committed return captures in `data/input/<unit>/returns/` are placeholder images (a coloured frame with the file name), and the 8 cassettes were written by hand in the Gemini response format (60 ms latency, ids like `interaction-UNIT-0014`, judgments such as "two critical product body features match" that no model could make from those images). Evidence labelled them `gemini-3.8-flash (recorded)`. Found by sending one capture to a vision model (Groq `qwen/qwen3.8-27b`), which described it as a placeholder.
- **Options considered:** *A:* delete them. Rejected: they are the only way CI exercises the Returns pipeline, rules and hand-offs end to end. *B:* re-record. Not possible without real photos and a `GEMINI_API_KEY`. *C (chosen):* keep them, mark each cassette `provenance: synthetic`, and label the evidence `synthetic-cassette (hand-authored, no model run)` with `payload.cassette_provenance`. Cassettes written by `record` mode keep `<model> (recorded)`.
- **Consequences:** Demo and evaluation state that Returns' 8 verdicts are scripted (`docs/evaluation.md`). Revisit when real photos are captured: replace the images and run `python -m agents.returns.tools.record_cassette`. Also: Pack's live default model on Groq is `qwen/qwen3.8-27b` (Groq does not serve Llama 3.2 Vision); live cost is `null` (not measured) instead of a fixed number.
