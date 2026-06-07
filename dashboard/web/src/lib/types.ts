// Shapes returned by the Flask /api (see dashboard/mapper._to_design, sales, calibration).
// Kept pragmatic/loose during the migration — the index signature carries fields a given
// view doesn't yet read.

export type Verdict = "BID" | "BID_TO_FIX" | "PASS" | null

export interface Vehicle {
  contract: string | null
  lot?: string
  lotNum?: number
  photo?: string | null
  photos?: string[]
  year?: number | null
  make?: string
  model?: string
  trim?: string
  cab?: string | null
  bed?: string | null
  driveline?: string
  type?: string
  km?: number
  vin?: string
  color?: string
  engine?: string
  trans?: string
  seller?: string
  reserve?: number | null
  auctionDate?: string
  regalUrl?: string | null
  carfaxUrl?: string | null

  verdict?: Verdict
  value?: number | null
  maxBid?: number | null
  conf?: "high" | "medium" | "low" | null
  valueBasis?: string
  engineMode?: string
  margin?: number
  buyerFee?: number
  gst?: number
  summary?: string
  topFlags?: string[]
  reasoning?: string | null
  conditional?: { amount: number; condition: string } | null
  needsDeep?: boolean
  deepReason?: string | null
  scored?: boolean
  deepReady?: boolean

  // off-auction appraisal extras
  source?: string | null
  adUrl?: string | null
  askingPrice?: number | null
  dealLabel?: string | null
  purchaseCtx?: { kind: string; label: string; tax_rate: number; auction_fee: boolean }
  vinFilled?: string[]

  // nested panels (loose for now)
  decl?: any
  comps?: any
  vision?: any
  repair?: any
  recon?: any[]
  sale?: any
  verify?: string[]
  carfax?: any
  pastSales?: any
  feedback?: any
  vmr?: any
  inputs?: any
  overridden?: string[]
  rules?: any
  divergence?: string
  adjustments?: any[]
  toolsUsed?: string[]
  meta?: { model?: string; effort?: string; elapsed?: number; cost?: number; tokens?: any }
  aiError?: string

  [key: string]: any
}

export interface Sale {
  date: string
  day: string
  label: string
  count: number
}

export interface SaleData extends Sale {
  screened: number
  vehicles: Vehicle[]
}

export type Mode = "triage" | "deep"
export type ViewName = "lane" | "card" | "appraise" | "sold" | "calib" | "settings"
