# Nintendo Switch OLED (Zelda Edition): a different console came back

A merchant-fulfilled (MFN) Switch OLED Zelda Edition is received and packed. The customer returns a blue Switch Lite instead: a cheaper, different console.

Fastest way: on the Live Run page pick this set under **Ready-made demo sets** and press **Load into the form**.
Or type these values and add the photos from the folders below.

## 1. Product

- Product name: **Nintendo Switch OLED Model - The Legend of Zelda: Tears of the Kingdom Edition**
- SKU: `SKU-NSW-OLED-ZELDA` · ASIN: `B0DEMONSW2` · Category: electronics
- Colour: gold and green (Zelda edition) · Variant: OLED 64GB · Components: console; dock; Joy-Con controllers
- Fulfilment route: **MFN** · Returned: **yes**

## 2. Receiving

- Supplier: Nintendo authorised distributor · PO number: PO-DEMO-1002
- Cartons ordered / received: 1 / 1 · Units per carton ordered / counted: 1 / 1
- Quantity ordered / received: 1 / 1
- Right product: yes · Carton damage: none · Unit damage: none · Quality flags: none
- Photos: `receiving/1_zelda_oled_switch_hof03533_raw_export.jpg`

## 3. Pack (MFN)

- Channel: shopify · Operator's decision: seal
- Order lines: SKU-NSW-OLED-ZELDA x1
- Open-box photo: `pack/1_nintendo_switch_oled_modell_the_legend_o.jpg`

## 4. Returns

- Parts that should come back: console; dock; Joy-Con controllers
- Returned item photo: `returns/1_nintendo_switch_lite_blue.jpg`

## 5. Recovery: fee lines

- inbound defect fee: $3.00

## What happened when we ran it (real agents, real model calls)

Run `LIVE-021423-10A0`, 75 s in total.

| Agent | Result | Model | Why (from the agent's record) |
|---|---|---|---|
| Receiving | **UNCERTAIN** pending review | gemini-3.8-flash (1 calls, 15.1 s) | identity_match: Observed SKU could not be clearly verified from visual evidence. |
| Prep | skipped | | route='mfn' not in ['fba'] |
| Pack | **PASS** seal | qwen/qwen3.8-27b (1 calls, 1.5 s) | Every expected SKU is present at the expected quantity with no extra or foreign items. |
| Returns | **FAIL** pending review, dispose | gemini-3.8-flash (2 calls, 55.4 s) · reference photo from pack | identity_match: Not the ordered item SKU-NSW-OLED-ZELDA (P1).; completeness: Not visible in the provided photos: console;dock;Joy-Con controllers. |
| Recovery | **UNCERTAIN** insufficient evidence | rules (0 calls, 0.0 s) | inbound defect fee $3.00 → **SILENT** (Receiving evidence RCV-LIVE-021423-10A0 is uncertain) |

**Final outcome: EXCEPTION** · needs a person: yes
> Failed verdict from: returns; no claim recommended. Flagged for review: receiving, returns.

Model answers can differ a little between runs; this is one real run.
