// Static descriptions of the five Pod 05 agents. Everything numeric or stateful in the UI comes from the
// orchestrator API (/health, /workflows, /workflows/{id}/evidence); this file holds no sample results.

export interface ExampleAgentItem {
  slug: string
  title: string
  stage: string
  id: string
  owner: string
  mode: string
  status: 'INTEGRATED' | 'STARTER STUB'
  description: string
  details?: {
    checks: string[]
    stages: string[]
    responsibilities: string[]
  }
}

// `id`, `owner`, `mode` and `status` are fallbacks only: the pages prefer the live values from /health.
export const exampleAgents: ExampleAgentItem[] = [
  {
    slug: 'receiving',
    title: 'Receiving Manager',
    stage: 'Receiving',
    id: 'receiving-manager-rcv0138@2',
    owner: '@KiranTejz20005',
    mode: 'INPROC',
    status: 'INTEGRATED',
    description: 'Checks what arrived from the supplier against the purchase-order line: identity, cartons, quantity, damage and quality flags.',
    details: {
      checks: ['identity_match', 'carton_count', 'quantity', 'carton_damage', 'unit_damage', 'quality_flags'],
      stages: ['First stage for every unit', 'unit_scope = po_line (finding F-08)'],
      responsibilities: ['Supplier shortfall recorded separately from channel loss (finding F-10)'],
    },
  },
  {
    slug: 'prep',
    title: 'Prep Manager',
    stage: 'Prep',
    id: 'prep-manager@1.0.0',
    owner: '@mdsuhana231-gif',
    mode: 'INPROC',
    status: 'INTEGRATED',
    description: 'FBA units only. Checks Amazon prep: polybag, suffocation warning, FNSKU label, original barcode covered, expiry, handling marks. Deterministic rules over the recorded prep observations; with only photo captures and no observations, every check is UNCERTAIN (no vision model).',
    details: {
      checks: ['polybag_sealed', 'suffocation_warning', 'fnsku_label_placement', 'original_barcode_covered', 'expiry_legible', 'handling_marks'],
      stages: ['Runs when route = fba'],
      responsibilities: ['Its verdict lets Recovery dispute an inbound-defect fee'],
    },
  },
  {
    slug: 'pack',
    title: 'Pack Manager',
    stage: 'Pack',
    id: 'pack-manager-nikhil@2.0.0',
    owner: '@nikhilagarwal03',
    mode: 'INPROC',
    status: 'INTEGRATED',
    description: 'Merchant-fulfilled units only. Checks the open box against the order before sealing: right items, right quantities, nothing extra; seal or stop-and-fix.',
    details: {
      checks: ['items_present', 'quantities_correct', 'no_extra_items'],
      stages: ['Runs when route = mfn'],
      responsibilities: ['Deterministic reconciliation over vision observations', 'Occlusion becomes UNCERTAIN, never a seal'],
    },
  },
  {
    slug: 'returns',
    title: 'Returns Manager',
    stage: 'Returns',
    id: 'returns-manager-rtn0045@2',
    owner: '@upeshchowdary',
    mode: 'INPROC',
    status: 'INTEGRATED',
    description: 'Checks a returned unit from its photos: identity, completeness and Amazon condition grade; deterministic rules (never the model) pick restock, refurbish, liquidate or dispose.',
    details: {
      checks: ['identity_match', 'completeness', 'condition'],
      stages: ['Runs when the unit was returned', 'Reference photo: Pack, then Receiving, then its own'],
      responsibilities: ['Flags a likely packing error when Pack also failed', 'Identity + disposition feed Recovery (D-007, finding F-11)'],
    },
  },
  {
    slug: 'recovery',
    title: 'Recovery Manager',
    stage: 'Recovery',
    id: 'recovery-vishruth@1',
    owner: '@vishruth-16',
    mode: 'INPROC',
    status: 'INTEGRATED',
    description: 'No camera. Reads every earlier record against the fee report and decides charge by charge: CONTRADICTS (claim, with cited records), SUPPORTS, or SILENT (never claimed).',
    details: {
      checks: ['one charge_<line_id> check per fee line'],
      stages: ['Final stage; re-runs on resume when upstream evidence or an override changed (D-012)'],
      responsibilities: ['Weight-tier fees SILENT (F-07)', 'Zero amounts never claimed (F-09)', 'Supplier shortfall is not channel loss (F-10)'],
    },
  },
]
