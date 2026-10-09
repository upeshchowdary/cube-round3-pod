# Live demo runbook (Pod 05)

What to do when the judges ask to see the system run live, including on data they hand you. Every command runs from the
repo root; on macOS/Linux use `python3` if `python` is older than 3.11.

## The day before (everyone)

```sh
git pull                          # main
python scripts/dev.py setup       # .venv, Python and UI dependencies, .env
python scripts/dev.py test        # must say "... passed"
python scripts/dev.py run         # 106 workflows in seconds
python scripts/dev.py up          # http://localhost:5173/overview, Ctrl+C to stop
```

Put the Gemini key in `.env` on the demo laptop only (`GEMINI_API_KEY=...`, never in git, never in chat). The free tier
allows **20 requests per model per day** and one Returns unit uses 1-2, so do not burn them on rehearsal. If a model
says 503/504 (overloaded) or 429 (quota), set another one: `RETURNS_LIVE_MODEL=gemini-3-flash-preview` (answered on
2026-10-08), `gemini-3.6-flash`, `gemini-3.5-flash`.

## When a judge hands you a dataset

They may give all five files or only one (for example just a Receiving file, or a Returns file while the photos come from
us). The files are the Round 2 shapes in `data/sample/` (column lists below). Put them in one folder and run:

```sh
python scripts/dev.py dataset <their-folder>
python scripts/dev.py up --dataset <their-folder-name>       # the UI on their data only
```

The first command checks every file, prints what it recognised, and either refuses with a `FIX` line or runs every unit
through the five agents and prints one row per unit:

```text
  UNIT       ORG             RECEIVING    PREP            PACK       RETURNS         RECOVERY                FINAL
  UNIT-0014  org_demo_alpha  PASS accept  PASS compliant  -          PASS liquidate  FAIL claim_recommended  CLAIM_RECOMMENDED $2.00
```

`-` = the stage does not apply to this unit (route, not returned, or no input for it in their data: the workflow page
says which). `ERR code` = the stage ran and could not judge (fail-open: recorded, held for a person, never turned into a
pass).

| The check says | Do this |
|---|---|
| `missing column(s) qty_received (closest: received_qty) ... --map received_qty=qty_received` | Re-run with exactly that `--map` (one per renamed column). Never guess a different column. |
| `SKU 'X' has no product category ... --category X=<...>` | Add `--category X=electronics` (or toys_games, home_kitchen, beauty_topical, grocery_ingestible, pet). |
| `row 7: qty_received='twenty' is not a whole number` / `duplicate ...` | Ask the judge which value is meant, fix the cell, re-run. |
| `N returned unit(s) have no photos (...)` | Returns will hold those units for a person. Add photos (next section) if you have them. |
| `N unit(s) have no stage that can run` | E.g. a fee report alone: Recovery needs the unit's Receiving row. Ask for the Receiving file too. |
| `the file is empty` / `no data rows` | The judge's export has no rows. Ask for the file again. |
| `no recorded Returns answer; Gemini judges it live` | Fine: needs the key and quota. Without a key Returns records `no_cassette`. |
| `not recognised ... ignored` | The file name and columns match no stage. Rename it (receiving / prep / pack / returns / fees). |

Their files are never modified: a clean copy and the run live in `out/datasets/<name>/` and are rebuilt on every load.

### Photos ("half the input comes from us")

Lay photos out as `<unit>/<stage>/<file>` and pass the folder, or put it next to their CSVs as `photos/`:

```text
our_photos/UNIT-0201/receiving/pallet.jpg      Receiving (and Returns' "before" reference)
our_photos/UNIT-0201/pack/open_box.jpg         Pack (Groq vision runs when GROQ_API_KEY is set)
our_photos/UNIT-0201/returns/ref_1.jpg         Returns reference, only needed if no receiving/pack photo
our_photos/UNIT-0201/returns/1.jpg  2.jpg      the returned item
```

```sh
python scripts/dev.py dataset <their-folder> --photos our_photos
```

Photo files named in a row's `photo_refs` column are picked up too when they sit at that path inside their folder.

## Who shows what (one minute each, on the workflow page of one unit)

| Member | Agent | Reads | Shows |
|---|---|---|---|
| Kiran | Receiving | receiving file (PO line + counts), receiving photos | the six checks, shortfall, `csv-replay` or Gemini |
| Suhana | Prep | prep file (observed prep values) | the prep checks; a FAIL here flips Recovery to SUPPORTS |
| Nikhil | Pack | pack file (order lines + box contents), open-box photo | seal / stop_and_fix, occlusion becomes UNCERTAIN |
| Upesh | Returns | returns file + our photos + category | identity / completeness / condition, rule-based disposition, live Gemini |
| Vishruth | Recovery | fee report + every earlier record | CONTRADICTS / SUPPORTS / SILENT per charge, the cited record |

Then: override a blocked unit (Intervene / Override, name and reason), Resume, show Recovery re-run on the new verdict.

### Real photos and a live Gemini run (Pack -> Returns)

The units `UNIT-C26RM-*` carry real product photos (`data/input/RETURNS_PHOTOS.md`). Open **UNIT-C26RM-031**: Pack
checked the photo of the controller as sold and handed it to Returns, which compared it with the returned one and found
a DualSense **Edge** instead of a DualSense (identity FAIL, Gemini's recorded answer). Open the Pack and Returns records
to show the photo travelling from one to the other (`reference_source: pack`).

For a live run, open **UNIT-C26RM-032** or **UNIT-C26RM-011** (FAILED, `no_cassette`: no recorded answer) and press
**Resume**. With `GEMINI_API_KEY` set (Render: the service's Environment; laptop: `.env`), Returns now asks Gemini
live, in about 10-30 s, and the record names the model and the number of calls. Each run costs about 1-4 of the
roughly 20 free requests a day, so do not rehearse it on the day.

## Column lists (required; other columns are optional)

| File | Required columns |
|---|---|
| receiving | record_id, unit_id, org_id, po_number, po_line, supplier, sku, asin, cartons_ordered, cartons_received, qty_ordered, qty_received, identity_match, carton_damage, unit_damage, captured_at |
| prep | record_id, unit_id, org_id, polybag_present_sealed, suffocation_warning, fnsku_label_placement, original_barcode_covered, expiry_date, handling_marks, prep_price_usd, operator_id, captured_at |
| pack | record_id, unit_id, org_id, order_id, order_lines, observed_in_box, captured_at |
| returns | unit_id, org_id, order_id, ordered_sku, parts_list (+ category for a SKU we have not seen) |
| fee report | line_id, report_type, unit_id, org_id, sku, fnsku, charge_type, amount_usd, posted_date |

Source of truth: `REQUIRED` in `shared/utils/sample_data.py`.

## If something goes wrong in the room

| Symptom | Fix |
|---|---|
| `port 8100 is in use` | `python scripts/dev.py up --api-port 8120 --ui-port 5190` |
| UI says the API is not connected | the `up` terminal was closed; start it again |
| Returns `quota_exhausted` / `rate_limit` | another model in `RETURNS_LIVE_MODEL`, or show the recorded run |
| No internet | units with a recorded answer replay offline; new units are held for a person (`ERR`), which is the honest result |
| Anything else | `python scripts/dev.py doctor`, and keep a screen recording of a good run as the last resort |

## Limits to say out loud (judges reward honesty)

- Prep has no vision: it applies rules to recorded observations. With photos only, its checks are UNCERTAIN.
- Receiving's live Gemini mode and Pack's live vision exist but were not yet run on real photos.
- The 8 committed Returns photos are placeholders and their recorded answers were hand-authored; on them live Gemini
  correctly answers "bad photo". Real photos are needed for real grades.
