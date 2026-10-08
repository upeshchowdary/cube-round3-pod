// Static content for the Pod 05 cover page (Round 3 · five-agent integration).

export interface CoverAgent {
  slug: string
  index: string
  name: string
  stage: string
  owner: string
  when: string
  summary: string
  checks: string[]
  handsOn: string
  image: string
  caption: string
}

export const agents: CoverAgent[] = [
  {
    slug: 'receiving',
    index: '01',
    name: 'Receiving Manager',
    stage: 'Receiving',
    owner: 'Lanke Kiran Teja',
    when: 'First stage for every unit',
    summary:
      'Checks what arrived from the supplier against the purchase-order line, and keeps a supplier shortfall separate from any later channel loss.',
    checks: ['identity_match', 'carton_count', 'quantity', 'carton_damage', 'unit_damage', 'quality_flags'],
    handsOn: 'Condition on arrival · supplier-shortfall evidence',
    image: '/cover/receiving.webp',
    caption: 'Inbound cartons checked against the PO line.',
  },
  {
    slug: 'prep',
    index: '02',
    name: 'Prep Manager',
    stage: 'Prep',
    owner: 'Mohammad Suhana',
    when: 'FBA units',
    summary:
      'Checks a unit is prepped the way the channel requires — polybag, suffocation warning, FNSKU label, barcode cover, expiry, handling marks.',
    checks: ['polybag_sealed', 'suffocation_warning', 'fnsku_label_placement', 'original_barcode_covered', 'expiry_legible', 'handling_marks'],
    handsOn: 'Compliance proof that can dispute an inbound-defect fee',
    image: '/cover/prep.webp',
    caption: 'Prep compliance, check by check.',
  },
  {
    slug: 'pack',
    index: '03',
    name: 'Pack Manager',
    stage: 'Pack',
    owner: 'Nikhil Agarwal',
    when: 'Merchant-fulfilled units',
    summary:
      'Checks the open box against the order before it is sealed: right items, right quantities, nothing extra. Occlusion is UNCERTAIN, never a seal.',
    checks: ['items_present', 'quantities_correct', 'no_extra_items'],
    handsOn: 'What was actually sent · seal or stop-and-fix',
    image: '/cover/pack.webp',
    caption: 'The box, reconciled before the tape goes on.',
  },
  {
    slug: 'returns',
    index: '04',
    name: 'Returns Manager',
    stage: 'Returns',
    owner: 'Kasaraneni Upesh Chowdary',
    when: 'Only if the unit came back',
    summary:
      'Inspects a returned unit from its photos — identity, completeness, Amazon condition grade — and deterministic rules, never the model, choose restock, refurbish, liquidate or dispose.',
    checks: ['identity_match', 'completeness', 'condition'],
    handsOn: 'Condition and disposition · packing-error vs customer-swap signal',
    image: '/cover/returns.webp',
    caption: 'Identity, completeness and grade from the photos.',
  },
  {
    slug: 'recovery',
    index: '05',
    name: 'Recovery Manager',
    stage: 'Recovery',
    owner: 'Vishruth Jeelakapally',
    when: 'Final stage for every unit',
    summary:
      'Has no camera. Reads every earlier record against the channel fee report and decides charge by charge: contradicted (claim), supported, or silent — and silent is never claimed.',
    checks: ['charge_<line_id> · one per fee line'],
    handsOn: 'A claim that cites the exact upstream records',
    image: '/cover/recovery.webp',
    caption: 'Every claim cites the evidence behind it.',
  },
]

export const flowSteps = [
  {
    index: '01',
    tag: 'Route',
    title: 'The orchestrator routes each unit',
    detail:
      'Receiving always runs. FBA units go through Prep, merchant-fulfilled units through Pack, Returns only if something came back, and Recovery closes every workflow.',
  },
  {
    index: '02',
    tag: 'Hand off',
    title: 'Every stage sees all earlier evidence',
    detail:
      'Agents never call each other. The orchestrator validates each output — schema, tenant, content hash — stores it, and passes the whole chain forward.',
  },
  {
    index: '03',
    tag: 'Decide',
    title: 'One traceable final outcome',
    detail:
      'Status and outcome are derived from the evidence and any human overrides: CLEAN, CLAIM_RECOMMENDED, EXCEPTION, NEEDS_REVIEW or INCOMPLETE. Failures are recorded, never success.',
  },
]

export const pillars = [
  {
    title: 'One contract',
    body: 'Agent Input in, Agent Output with an Evidence Record out — PASS, FAIL or UNCERTAIN, per check.',
  },
  {
    title: 'One owner of state',
    body: 'The orchestrator owns routing, retries, overrides and the final outcome. Agents only judge.',
  },
  {
    title: 'One evidence trail',
    body: 'Outcome → contributing records → checks → evidence refs → the sha256 of the exact input.',
  },
]

export const facts = [
  { value: '5', label: 'agents in one flow' },
  { value: '100', label: 'workflows hand-off checked' },
  { value: '0', label: 'broken evidence links' },
  { value: '129', label: 'automated tests passing' },
]

export const team = agents.map((a) => ({ name: a.owner, role: a.name }))
