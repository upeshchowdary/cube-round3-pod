# PlayStation 5 DualSense: a DualSense Edge came back

A merchant-fulfilled DualSense controller is packed and shipped. The customer returns a DualSense Edge, a different (pro) controller. The Live Run page's default form is this set.

Fastest way: on the Live Run page pick this set under **Ready-made demo sets** and press **Load into the form**.
Or type these values and add the photos from the folders below.

## 1. Product

- Product name: **PlayStation 5 DualSense Wireless Controller**
- SKU: `SKU-DUALSENSE-WHT` · ASIN: `B08H99BPJN` · Category: electronics
- Colour: white · Variant: standard · Components: controller; USB cable
- Fulfilment route: **MFN** · Returned: **yes**

## 2. Receiving

- Supplier: Sony Interactive (distributor) · PO number: PO-LIVE-1001
- Cartons ordered / received: 1 / 1 · Units per carton ordered / counted: 12 / 12
- Quantity ordered / received: 12 / 12
- Right product: yes · Carton damage: none · Unit damage: none · Quality flags: none
- Photos: none (the agent judges the typed counts)

## 3. Pack (MFN)

- Channel: shopify · Operator's decision: seal
- Order lines: SKU-DUALSENSE-WHT x1
- Open-box photo: `pack/1_playstation_dualsense_controller.jpg`

## 4. Returns

- Parts that should come back: controller; USB cable
- Returned item photo: `returns/1_dualsense_edge_controller.jpg`

## 5. Recovery: fee lines

- inbound defect fee: $3.00

## What happened when we ran it (real agents, real model calls)

Run `LIVE-021719-D9FE`, 60 s in total.

| Agent | Result | Model | Why (from the agent's record) |
|---|---|---|---|
| Receiving | **PASS** accept | csv-replay (0 calls, 0.0 s) | Shipment fully complies with PO specifications and receiving condition standards. |
| Prep | skipped | | route='mfn' not in ['fba'] |
| Pack | **UNCERTAIN** pending review | qwen/qwen3.8-27b (1 calls, 1.0 s) | items_present: uncertain: A single unit consistent with the expected DualSense White SKU was clearly identified in the image.; quantities_correct: uncertain: A single unit consistent with the expected DualSense White SKU was clearly identified in the image.; no_extra_items: uncertain: A single unit consistent with the expected DualSense White SKU was clearly identified in the image. |
| Returns | **FAIL** pending review, dispose | gemini-3.8-flash (2 calls, 55.6 s) · reference photo from pack | identity_match: Not the ordered item SKU-DUALSENSE-WHT (P1).; completeness: Not visible in the provided photos: USB cable. |
| Recovery | **FAIL** claim recommended | rules (0 calls, 0.0 s) | inbound defect fee $3.00 → **CONTRADICTS** (Receiving evidence RCV-LIVE-021719-D9FE shows the unit compliant) |

**Final outcome: CLAIM RECOMMENDED** · claimable $3.00 · needs a person: yes
> Recovery contradicted at least one charge (claimable $3.00). Flagged for review: pack, returns.

Model answers can differ a little between runs; this is one real run.
