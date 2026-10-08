# agents/recovery/ · Recovery Manager

**Owner:** Vishruth Jeelakapally (@vishruth-16) · Member 5 · Provenance: [`PROVENANCE.md`](PROVENANCE.md)

The Round 2 tri-state fee audit behind the Round 3 contract. Final stage for every unit. Recovery has no camera: it
reads the unit's fee report lines and **every earlier evidence record**, and decides charge by charge.

| | |
|---|---|
| **Agent ID** | `recovery-vishruth@1` · prefix `RCY-` · port `8105` |
| **Reads** | fee lines for the unit (`data/sample/fee_report_sample.csv`), all `previous_evidence`, workflow overrides (effective verdicts) |
| **Per fee line** | `CONTRADICTS` → check FAIL → **claim**, citing the upstream record · `SUPPORTS` → PASS → no claim · `SILENT` → UNCERTAIN → never claimed, listed in `payload.unclaimable` with the reason |
| **Outcome** | `claim_recommended` (any CONTRADICTS) · `insufficient_evidence` (any SILENT, no claim) · `no_claim` |
| **Model** | default `rules` (0 calls, $0). `RECOVERY_MODEL_MODE=live` + `GEMINI_API_KEY`: one batched Gemini call per unit, only for charge types no rule covers |

## Rules (default mode)

| Charge type | Decision |
|---|---|
| `inbound_defect_fee` | Prep (else Receiving) effective verdict PASS → CONTRADICTS (claim); FAIL → SUPPORTS; UNCERTAIN or no record → SILENT |
| `refund_issued_item_not_returned` | CONTRADICTS only if Returns verified the item came back (PASS, or identity PASS with restock/refurbish/liquidate) (F-11, D-007); a wrong item returned stays SILENT |
| `fulfilment_fee_weight_tier` | SILENT: no measured weight and no fee schedule lookup (F-07) |
| `lost_inbound` | SILENT: a receiving shortfall is supplier-side, not channel loss (F-10) |
| reimbursement credits, `damaged_in_warehouse` | SILENT: credits to the seller, not charges to dispute |
| amount 0.00 | never claimed (F-09, D-005) |

In live mode a model answer can only become a claim if it cites a record id that exists upstream; any model failure
falls back to the rules and is recorded in `payload.model_fallback`.

## Limits

- No fee schedule lookup, so weight-tier fees are never disputed.
- Claim precision is not measured (no labelled fee data); see `docs/evaluation.md`.
- Live mode not run in this repo's evaluation (no key).

## Run

```sh
python -m pytest tests/integration/test_agent_contracts.py -k recovery
uvicorn agents.recovery.app:app --port 8105
```
