# agents/returns/  ·  Returns Manager

**Owner:** Upesh Chowdary (@upeshchowdary) · Member 4 · Provenance: [`PROVENANCE.md`](PROVENANCE.md)

The Round 2 Returns Manager pipeline, copied byte-identical into `r2/` and run in-process behind a thin
Round 3 adapter (`app.py` + `adapter/`). From the returned unit's photos, the seller's order and parts list and
Amazon's published condition guidelines, it records identity, completeness and condition. Deterministic rules
(never the model) compute restock / refurbish / liquidate / dispose, or hold the unit for review.

| | |
|---|---|
| **Reads (inputs)** | `data/input/<unit>/returns/*.jpg` (return photos) and `ref_*.jpg` (reference photo) |
| **Reads (previous evidence)** | Pack (preferred reference photo, shipped SKU), Receiving (fallback reference, inbound SKU) |
| **Checks** | `identity_match`, `completeness`, `condition` (in that order) |
| **`decision.outcome`** | `restock`, `refurbish`, `liquidate`, `dispose`, or `pending_review` when the engine requires review |
| **Hands on** | `payload.recommended_disposition`, `amazon_condition`, `parts_missing`, `upstream_reconciliation`; Recovery uses identity + disposition for `refund_issued_item_not_returned` (D-007) |

## How a request flows

1. `adapter/orders.py` looks the return up **for this org only** (`LookupError` → 404 for another tenant).
2. `adapter/captures.py` hashes every capture, rejects path traversal and hash mismatches, and picks the
   reference photo: Pack's image input, then Receiving's, then our own `ref_*` photo.
3. `adapter/upstream.py` reconciles Pack/Receiving SKUs with the order and flags a likely packing error
   (Pack FAIL + identity FAIL) instead of blaming the customer.
4. `r2/…/batch/runner.py: process_returned_row` runs **one Gemini judgment session per unit** (all checks in one
   structured output) and the rules engine.
5. `adapter/mapping.py` maps the result to an Evidence Record (`RTN-<sha256(request_id)[:16]>`, idempotent).

Any failure (no photo, no cassette, quota, model error) returns a `pending` / `error` record with the reason,
never a guessed verdict.

## Model modes (`RETURNS_MODEL_MODE`)

| Mode | What runs | `model.calls` |
|---|---|---|
| `replay` (default, CI) | Gemini-format responses from `cassettes/<org>/<unit>.jsonl`; cassette hash in `payload.cassette_sha256`. The 8 committed cassettes are **hand-authored** (`provenance: synthetic`) over placeholder captures, and evidence names the model `synthetic-cassette (hand-authored, no model run)`; a cassette written by `record` mode is labelled `<model> (recorded)` | 0 (`payload.recorded_calls` = 1) |
| `live` | the real Gemini call (`GEMINI_API_KEY` required) | measured |
| `record` | live, and writes a new cassette | measured |

Cassettes exist for UNIT-0014, 0016, 0038, 0092 (alpha) and 0003, 0021, 0039, 0054 (bravo). Other returned
units fail open as `no_return_photo` / `no_cassette`.

## Limits (honest)

- Condition grades are checked against a stored snapshot of Amazon's guidelines marked `unverified_substitute`.
- No independently labelled evaluation set yet: accuracy is not reported.
- `model.cost_usd` is 0.0 on the free tier; `payload.cost_note` gives the list-price estimate.

## Run

```sh
python -m pytest tests/integration/test_agent_contracts.py -k returns
uvicorn agents.returns.app:app --port 8104      # then "mode": "http" in agent.json
```
