# Kindle Paperwhite: FBA unit, returned in good condition, refund disputed

An Amazon-fulfilled (FBA) e-reader arrives, is prepped to Amazon's rules, and later comes back from a customer in good condition. Amazon still posted a 'refund issued, item not returned' charge.

Fastest way: on the Live Run page pick this set under **Ready-made demo sets** and press **Load into the form**.
Or type these values and add the photos from the folders below.

## 1. Product

- Product name: **Amazon Kindle Paperwhite (11th generation, 2023)**
- SKU: `SKU-KINDLE-PW11` · ASIN: `B0DEMOKPW1` · Category: electronics
- Colour: black · Variant: 16GB, with grey cover · Components: e-reader; cover
- Fulfilment route: **FBA** · Returned: **yes**

## 2. Receiving

- Supplier: Amazon Devices distributor · PO number: PO-DEMO-1001
- Cartons ordered / received: 1 / 1 · Units per carton ordered / counted: 1 / 1
- Quantity ordered / received: 1 / 1
- Right product: yes · Carton damage: none · Unit damage: none · Quality flags: none
- Photos: `receiving/1_2023_amazon_kindle_paperwhite_1.jpg`

## 3. Prep (FBA)

- FNSKU: `X00DEMO001` · Prep price: $0.40
- Work order: polybag True, suffocation warning True, expiry date False, handling marks none
- Observed: polybag yes, suffocation warning legible, FNSKU label flat, original barcode covered yes, expiry not required, handling marks not required

## 4. Returns

- Parts that should come back: e-reader; cover
- Returned item photo: `returns/1_2023_amazon_kindle_paperwhite_3.jpg`

## 5. Recovery: fee lines

- refund issued item not returned: $139.99
- fulfilment fee weight tier: $3.22

## What happened when we ran it (real agents, real model calls)

Run `LIVE-021250-1948`, 93 s in total.

| Agent | Result | Model | Why (from the agent's record) |
|---|---|---|---|
| Receiving | **UNCERTAIN** pending review | gemini-3.8-flash (1 calls, 14.8 s) | identity_match: Observed SKU could not be clearly verified from visual evidence.; carton_count: Carton count could not be reliably established from photos.; carton_damage: Carton exterior could not be fully assessed for damage. |
| Prep | **PASS** compliant | rules (0 calls, 0.0 s) | Prep checks completed from available evidence. |
| Pack | skipped | | route='fba' not in ['mfn'] |
| Returns | **PASS** pending review, restock | gemini-3.8-flash (3 calls, 74.8 s) · reference photo from receiving | R13: Identity yes (two or more critical product body features match). all listed parts present. condition Used - Like New; functional test not performed. rules engine route restock (R13: used grade used_like_new is restockable by policy). review: listing_blockers_undetermined. Evaluated from single photograph; single-angle view verified. Confidence calibrated accordingly. |
| Recovery | **FAIL** claim recommended | rules (0 calls, 0.0 s) | refund issued item not returned $139.99 → **CONTRADICTS** (Returns record RTN-bcb71cd4e1e68375 shows the item came back (verdict PASS, disposition pending_review) (finding F-11, D-007)); fulfilment fee weight tier $3.22 → **SILENT** (Prep measured the unit but no fee schedule is looked up to compare the tier (finding F-07)) |

**Final outcome: CLAIM RECOMMENDED** · claimable $139.99 · needs a person: yes
> Recovery contradicted at least one charge (claimable $139.99). Flagged for review: receiving, returns.

Model answers can differ a little between runs; this is one real run.
