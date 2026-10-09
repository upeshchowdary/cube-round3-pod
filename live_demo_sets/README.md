# Live demo sets

Five ready-made products for the **Live Run** page (`/live`): real product photos plus the values to type into the
form. They are only **inputs**. The processing is done by the Pod's real agents (Receiving, Prep, Pack, Returns,
Recovery) through the orchestrator, exactly as for anything typed in by hand, with AI on the photos:

- **Receiving:** Gemini looks at the receiving photos and checks them against the purchase order.
- **Pack:** Groq's vision model looks at the open-box photo.
- **Returns:** Gemini compares the returned item with the reference photo it takes from Pack (MFN) or Receiving (FBA).

## How to use a set in the demo

1. Start the project (`python scripts/dev.py up`) and open <http://localhost:5173/live>.
2. In **Ready-made demo sets**, pick a product and press **Load into the form**: the form is filled and the set's
   photos are attached. (Or type the values from the set's `INPUTS.md` and add the photos from its folders yourself.)
3. Press **Start processing** and walk through the agents as they finish. A whole set takes 25 s to 1.5 min
   (Gemini `gemini-3.8-flash`); explain Receiving and Pack while Returns works. If a model call fails (a key's limit, a
   timeout, a malformed answer) the run retries on the next key by itself and says so on the page.

## The sets

| Set | Route | What it shows |
|---|---|---|
| `set1_kindle_paperwhite_fba_clean_return` | FBA | Receiving -> **Prep** -> Returns (reference from Receiving) -> Recovery disputes a "refund issued, item not returned" charge |
| `set2_switch_oled_zelda_swapped_return` | MFN | a **different console** came back: Returns finds the swap |
| `set3_switch_lite_grey_damaged_return` | MFN | the **same console came back damaged** |
| `set4_sony_mdr_v6_damaged_delivery` | MFN | a **crushed parcel** caught at Receiving; not returned |
| `set5_dualsense_swapped_for_edge` | MFN | a DualSense was sold, a **DualSense Edge** came back |

Each set folder holds:

- `receiving/`, `pack/`, `returns/`: the photos for each agent that takes photos. **They are not stored in git:** `python scripts/fetch_photos.py` downloads them (`dev.py setup`, `make setup` and the Docker build run it) and checks each one against `data/photos.json`
- `spec.json`: the form values (what the page fills in)
- `INPUTS.md`: the same values in plain words, and **what happened when the set was run** through the real agents
- `about.json`: title and story shown on the page

## Honest limits

- The photos are real (Wikimedia Commons, see `CREDITS.md`), but they are product photos chosen to fit each story,
  not photos of an actual shipment or return.
- Model answers can differ slightly from run to run; the results in each `INPUTS.md` are from one real run.
- A product photo shows no SKU label, so Receiving and Pack answer UNCERTAIN on identity rather than guess.
