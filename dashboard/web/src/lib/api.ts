// Typed client for the Flask JSON API (proxied at /api in dev, same-origin in prod).
import type { Sale, SaleData, Vehicle } from "./types"

async function get<T>(path: string): Promise<T> {
  const r = await fetch(path, { headers: { Accept: "application/json" } })
  if (!r.ok) throw new Error((await r.json().catch(() => ({})))?.error || `${r.status} ${path}`)
  return r.json()
}

async function send<T>(path: string, method: string, body?: unknown): Promise<T> {
  const r = await fetch(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body == null ? undefined : JSON.stringify(body),
  })
  if (!r.ok) throw new Error((await r.json().catch(() => ({})))?.error || `${r.status} ${path}`)
  return r.json()
}

export const api = {
  sales: () => get<{ sales: Sale[] }>("/api/sales").then((d) => d.sales),
  sale: (date: string, profile: string, screen: number | "all" = 60) =>
    get<{ sale: SaleData }>(`/api/sale?date=${date}&profile=${profile}&screen=${screen}`).then((d) => d.sale),
  evaluate: (contract: string, mode: "triage" | "deep" | "none", profile: string) =>
    get<{ vehicle: Vehicle }>(`/api/evaluate?contract=${contract}&mode=${mode}&profile=${profile}`).then((d) => d.vehicle),
  // re-display a persisted deep result (deep_cache) without recomputing
  evaluateCachedDeep: (contract: string, profile: string) =>
    get<{ vehicle: Vehicle }>(`/api/evaluate?contract=${contract}&mode=deep&profile=${profile}&cached_only=1`).then((d) => d.vehicle),

  calibration: () => get<any>("/api/calibration"),
  settings: () => get<{ settings: any }>("/api/settings").then((d) => d.settings),
  saveSettings: (s: any) => send<{ settings: any }>("/api/settings", "POST", s).then((d) => d.settings),
  resetSettings: () => send<{ settings: any }>("/api/settings/reset", "POST").then((d) => d.settings),

  personalSales: () => get<{ sales: any[] }>("/api/personal_sales").then((d) => d.sales),
  addPersonalSale: (s: any) => send<{ sale: any }>("/api/personal_sales", "POST", s).then((d) => d.sale),
  deletePersonalSale: (id: number) => send<{ ok: boolean }>(`/api/personal_sales/${id}`, "DELETE"),

  // off-auction appraisal
  appraise: (body: any) => send<{ vehicle: Vehicle }>("/api/appraise", "POST", body).then((d) => d.vehicle),
  ingestAd: (url: string) => get<any>(`/api/ingest_ad?url=${encodeURIComponent(url)}`),
  vinDecode: (vin: string) => get<{ decoded: any }>(`/api/vin_decode?vin=${encodeURIComponent(vin)}`).then((d) => d.decoded),
  vpicMakes: () => get<{ makes: string[] }>("/api/vpic/makes").then((d) => d.makes),
  vpicModels: (make: string, year: number) =>
    get<{ models: string[] }>(`/api/vpic/models?make=${encodeURIComponent(make)}&year=${year}`).then((d) => d.models),
  vpicTrims: (year: number, make: string, model: string) =>
    get<{ trims: string[] }>(`/api/vpic/trims?year=${year}&make=${encodeURIComponent(make)}&model=${encodeURIComponent(model)}`).then((d) => d.trims),

  // feedback loop / card actions
  saveFeedback: (body: any) => send<{ feedback: any }>("/api/feedback", "POST", body).then((d) => d.feedback),
  flagComp: (body: { externalId: string; contract: string | null; reason?: string; status?: string }) =>
    send<any>("/api/comp_flag", "POST", body),
  saveOverrides: (contract: string, profile: string, overrides: any) =>
    send<{ vehicle: Vehicle }>("/api/overrides", "POST", { contract, profile, overrides }).then((d) => d.vehicle),
  saveCarfax: (body: any) => send<{ vehicle: Vehicle }>("/api/carfax", "POST", body).then((d) => d.vehicle),
  pullCarfax: (contract: string, profile: string) =>
    send<{ vehicle: Vehicle }>("/api/carfax_pull", "POST", { contract, profile }).then((d) => d.vehicle),
  runVision: (contract: string, profile: string) =>
    send<{ vehicle: Vehicle }>("/api/vision_pull", "POST", { contract, profile }).then((d) => d.vehicle),
  // sale-level batches
  runAll: (date: string, profile: string) => send<{ job: any }>("/api/run_all", "POST", { date, profile }).then((d) => d.job),
  runStatus: (date: string) => get<any>(`/api/run_status?date=${date}`),
  runCancel: (date: string) => send<any>("/api/run_cancel", "POST", { date }),
  refreshListings: () => send<{ job: any; started: boolean }>("/api/refresh_listings", "POST"),
  refreshStatus: () => get<any>("/api/refresh_status"),

  calibrationCsvUrl: "/api/calibration.csv",
}

// SSE helper for the streaming deep appraisal endpoints. Returns the EventSource so the
// caller can close it. onStage/onResult/onError mirror the server's named events.
export function stream(
  url: string,
  handlers: { stage?: (s: string) => void; result?: (v: Vehicle) => void; failed?: (e: any) => void },
): EventSource {
  const es = new EventSource(url)
  es.addEventListener("stage", (e) => handlers.stage?.(JSON.parse((e as MessageEvent).data)))
  es.addEventListener("result", (e) => {
    handlers.result?.(JSON.parse((e as MessageEvent).data))
    es.close()
  })
  es.addEventListener("failed", (e) => {
    handlers.failed?.(JSON.parse((e as MessageEvent).data))
    es.close()
  })
  return es
}
