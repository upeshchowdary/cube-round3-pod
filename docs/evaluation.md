# Evaluation · Pod 05

Measured on 2026-10-08 at the integration commit, in-process, default modes (no model API keys). Every number here
comes from a run of the committed code; how to reproduce it is at the end. **Read the limits section first:** this
evaluates the integrated system (routing, hand-offs, rules, failure handling, tenancy), **not** model accuracy.

## Method

| | |
|---|---|
| Units | 100: the 100 units of the organiser's Round 2 sample (`data/sample/cases.json`); 6 of them are also the Pod's own demo cases (`data/input/my_cases.json`) |
| Held out? | No. The sample is the data the agents were integrated against. Not an unseen test set. |
| Labels | **No independent human labels exist.** The only reference available is the operator columns in the sample CSVs, which are also what the replay modes read. Two-person labelling was not done. |
| What actually ran | Receiving: CSV replay of the operator's observations (`csv-replay`). Prep: deterministic rules over the CSV observations (`rules`). Pack: CSV replay of `observed_in_box` (`csv-replay`). Returns: Round 2 pipeline over **hand-authored cassettes and placeholder images** for 8 units (`synthetic-cassette`). Recovery: deterministic rules (`rules`). **0 model calls in total.** |

## Per check (verdict counts, not accuracy)

**TP / TN / FP / FN are not reported yet**: they need two independent human labels per check. The sheet and the
scorer are ready: `data/labels/labels.csv` (75 checks on the Pod's 6 cases) and `python scripts/score_checks.py
data/labels/labels.csv` (FAIL = positive; UNCERTAIN counted per label value; Cohen's kappa between the labellers).
Labelling needs real captures first (the committed ones are placeholders).

Without independent labels there are no TP/TN/FP/FN to report; these are verdict counts so the share of
UNCERTAIN is visible. UNCERTAIN is never dropped.

| Stage · check | PASS | FAIL | UNCERTAIN |
|---|---:|---:|---:|
| receiving · identity_match | 94 | 3 | 3 |
| receiving · carton_count | 93 | 7 | 0 |
| receiving · quantity | 85 | 15 | 0 |
| receiving · carton_damage | 74 | 17 | 9 |
| receiving · unit_damage | 85 | 6 | 9 |
| receiving · quality_flags | 90 | 10 | 0 |
| prep · polybag_sealed | 29 | 2 | 2 |
| prep · suffocation_warning | 29 | 2 | 2 |
| prep · fnsku_label_placement | 52 | 6 | 4 |
| prep · original_barcode_covered | 56 | 4 | 2 |
| prep · expiry_legible | 7 | 1 | 1 |
| prep · handling_marks | 17 | 1 | 3 |
| pack · items_present | 28 | 1 | 0 |
| pack · quantities_correct | 28 | 1 | 0 |
| pack · no_extra_items | 25 | 4 | 0 |
| returns · identity_match (8 scripted units) | 6 | 1 | 1 |
| returns · completeness (8 scripted units) | 7 | 0 | 1 |
| returns · condition (8 scripted units) | 6 | 0 | 2 |

Pack against the operator's recorded verdict (29 MFN units): agree 27 (25 seal, 2 stop_and_fix); the agent says
`stop_and_fix` where the operator sealed in 2 (an extra item in `observed_in_box`). Because Pack replays the same
CSV row, this measures the reconciliation rules, not vision.

Pack's own Round 2 benchmark (50 held-out fixtures, recorded VLM answers): see `agents/pack/eval-report.md`. It was
not re-run here.

## System (end to end, 100 units)

| Status | n | | Final outcome | n |
|---|---:|---|---|---:|
| COMPLETED | 66 | | EXCEPTION | 47 |
| BLOCKED (a person must decide) | 18 | | CLEAN | 28 |
| FAILED | 16 | | NEEDS_REVIEW | 12 |
| | | | CLAIM_RECOMMENDED | 7 |
| | | | INCOMPLETE | 6 |

- **Needing a human:** 34 / 100 (BLOCKED, NEEDS_REVIEW, or a provisional outcome).
- **FAILED 16:** all are returned units with no return photos; Returns records `no_reference_photo` instead of guessing.
- **Hand-offs:** every completed stage lists every earlier record in `upstream_refs`; all content hashes verify (the orchestrator rejects any that do not).
- **UNCERTAIN to override:** UNIT-0092 (Returns cannot verify identity) goes BLOCKED; the override is recorded against the record, `resume` re-runs Recovery with it, the workflow ends COMPLETED (`tests/e2e/test_api.py`).

### Failure injection (each agent killed in turn, all 100 units)

| Agent killed | Units where it runs | Status of those runs | Reported as success |
|---|---:|---|---:|
| receiving | 100 | FAILED 100 | 0 |
| prep | 62 | FAILED (all 62 with Prep) | 0 |
| pack | 29 | FAILED (all 29 with Pack) | 0 |
| returns | 24 | FAILED 24 | 0 |
| recovery | 100 | FAILED 100 | 0 |

An agent that fails to import (e.g. a missing dependency) is recorded the same way (`agent_exception`), not a crash.

### Tenancy

Every subject asked under the other org, against Receiving and Recovery: 200 / 200 refused, 0 answered. The API
refuses an unknown or wrong-tenant subject with 404 and stores nothing (`tests/e2e/test_api.py`).

## Claims (Recovery)

7 claims recommended, $8.00 in total, all `inbound_defect_fee`, each citing the Prep record that shows the unit
compliant. 0 claims without a cited record. 42 weight-tier fees, 5 lost-inbound, 4 refund-not-returned, 2
inbound-defect and 1 damaged-in-warehouse lines are SILENT (never claimed); the reasons are in each record.
**Claim precision is not measured**: there is no independent label of which fees were truly wrong.

## Returns on real product photos (10 more units, added 2026-10-09)

The 100 sample units above have no real images. To show the vision path on real input, 10 units from the Round 2
Returns test set (`returns_input_50.csv`) were added with **real product photos from Wikimedia Commons**
(`data/input/RETURNS_PHOTOS.md`: sources, authors, licences). They are catalogue-style photos of the product, not photos
of an actual shipment or returned item, and the orders are synthetic.

- **Hand-off:** the photo of the product as sold is Pack's open-box capture. Pack checks it, and Returns takes its
  reference photo from Pack's record (`reference_source: pack`, Pack's record in `upstream_refs`). The returned item's
  photo is Returns' own capture.
- **Model:** Returns' answers for 8 units were recorded once from `gemini-3-flash-preview` on these photos (14 requests),
  and are replayed (`<model> (recorded)`, 0 calls). 2 units have no recording; they fail open (`no_cassette`) until they
  are resumed with a Gemini key and judged live.
- **Pack** replays the operator row by default; with a Groq key it looks at the photo itself (`qwen/qwen3.8-27b`, about
  1-2 s). On these catalogue photos it answers UNCERTAIN: it names the product but sees no SKU label to confirm.

| Unit | What the photos show | Gemini identity | Disposition |
|---|---|---|---|
| C26RM-012 Galaxy Tab S9 | a MacBook Pro 16 came back | FAIL | dispose |
| C26RM-015 Dell XPS 13 2017 | a ThinkPad X1 Carbon came back | FAIL | dispose |
| C26RM-022 Canon EOS R6 Mark II | a Canon EOS 5D Mark IV came back | FAIL | dispose |
| C26RM-031 DualSense controller | a **DualSense Edge** came back | FAIL | dispose |
| C26RM-044 JBL Flip | sold a **Flip 3**, a **Flip 4** came back | FAIL | dispose |
| C26RM-002 iPhone 15 Pro | an iPhone 15 / 15 Plus display came back | UNCERTAIN | review |
| C26RM-001 iPhone 15 | same family, different photos | UNCERTAIN | review |
| C26RM-041 Logitech MX Master 3S | same model | UNCERTAIN | review |

For C26RM-031 and C26RM-044 the Round 2 test set said "same model"; the Wikimedia file names show the photos are of
different models, so Gemini's FAIL is right and the test set's label was wrong. Gemini passed no swapped item; where it
could not tell (similar iPhones, a mouse photographed differently) it held the unit for a person. Completeness is
UNCERTAIN on all 8: a product photo cannot show the cables in the box. **8 units are far too few for an accuracy
figure**; this shows the path works on real photos, not how accurate it is.

## Cost and latency

0 model calls and $0 per unit in the default modes. In-process stage latency p50 ≤ 4 ms, max 115 ms (Returns). Live
modes were not measured: no `GEMINI_API_KEY` was available. One live Pack call through Groq
(`qwen/qwen3.8-27b`) on a placeholder image returned UNCERTAIN ("no physical inventory is visible") as it should.

## Failure modes we know

- **Placeholder captures and hand-authored cassettes (Returns).** The 8 demo units' return images are coloured frames
  with a file name, and their cassettes were written by hand. Evidence labels them `synthetic-cassette`; they prove the
  plumbing only. Adding any new capture for such a unit changes the request, and the cassette no longer matches, so
  Returns records an error (by design).
- **Replay modes.** Receiving and Pack replay the operator's CSV observations by default, so they cannot disagree with
  the operator about what is in the photo.
- **Prep has no vision.** Given only image captures (no observations), every Prep check is UNCERTAIN.
- **Returned units without photos** end FAILED, not NEEDS_REVIEW.

## Limits: what this does not tell you

- Any model's accuracy on real photos: the sample has no real captures, and the 10 real-photo units are catalogue
  photos, too few to measure accuracy.
- Generalisation: no held-out set; one synthetic sample.
- Claim precision: no ground truth for the fee lines.
- Live latency, cost, rate limits.

## Reproduce

```sh
python -m pytest                                                     # 141 passed, 1 skipped
python -m orchestration.run --all                                    # the 100-unit table above
python -m orchestration.run --all --cases data/input/my_cases.json   # the Pod's 6 cases
RETURNS_LIVE_FALLBACK=0 python -m orchestration.run --all --cases data/input/returns_photo_cases.json   # the 10 real-photo units
```
