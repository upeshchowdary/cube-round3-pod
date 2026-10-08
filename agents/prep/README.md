# agents/prep/ · Prep Manager

**Owner:** Mohammad Suhana (@mdsuhana231-gif) · Member 2 · Provenance: [`PROVENANCE.md`](PROVENANCE.md)

The Round 2 Prep Manager's compliance rules behind the Round 3 contract. Runs for FBA units only
(`orchestration/flow.json`: `route = fba`).

| | |
|---|---|
| **Agent ID** | `prep-manager@1.0.0` · prefix `PRP-` · port `8102` |
| **Reads (inputs)** | captures in `data/input/<unit>/prep/`, or the recorded prep observations for the unit (`data/sample/prep_sample.csv`) |
| **Reads (previous evidence)** | Receiving (listed in `upstream_refs`) |
| **Checks** | `polybag_sealed`, `suffocation_warning`, `fnsku_label_placement`, `original_barcode_covered`, `expiry_legible`, `handling_marks` (a check that is `not_required` for the unit is omitted, never marked PASS) |
| **Outcome** | `compliant` (all PASS) · `non_compliant` (any FAIL) · `pending_review` (any UNCERTAIN, or nothing to check) |
| **Model** | none: deterministic rules, `model.name = "rules"`, 0 calls, $0 |
| **Downstream** | Recovery uses a Prep PASS to contradict an `inbound_defect_fee` (claim), a FAIL to support it |

## How it decides

`prep_logic.py` maps each observed value to PASS / FAIL / UNCERTAIN against fixed sets (e.g. `fnsku_label_placement`:
`flat` → PASS; `on_seam`, `on_curve`, `on_edge`, `missing` → FAIL; anything else → UNCERTAIN). The roll-up is
FAIL > UNCERTAIN > PASS. The rule source is recorded in `payload.rule_source`.

**No vision.** Given only image captures (no recorded observations), the agent does not pretend to read pixels:
every check is UNCERTAIN with the captures cited, and the unit goes to a person.

## Limits

- Observations come from the recorded sample row, not from images.
- `payload.measurements` (weight/dimensions) are `null`: nothing is measured, so Recovery stays SILENT on weight-tier
  fees (finding F-07).
- Record ids are derived from the request id (`PRP-WF-<org>-<unit>-prep`), so the same request gives the same record.

## Run

```sh
python -m pytest tests/integration/test_agent_contracts.py -k prep
uvicorn agents.prep.app:app --port 8102     # then "mode": "http" in agent.json to call it over HTTP
```
