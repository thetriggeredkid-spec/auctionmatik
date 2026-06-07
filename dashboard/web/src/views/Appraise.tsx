import { useEffect, useState } from "react"
import { api, stream } from "@/lib/api"
import type { Mode, Vehicle } from "@/lib/types"
import { Card } from "@/views/Card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Card as UICard, CardContent, CardHeader, CardTitle } from "@/components/ui/card"

type Form = {
  year: string; make: string; model: string; trim: string; driveline: string
  engine: string; cab: string; km: string; vin: string
  seller_type: string; asking_price: string
}
const BLANK: Form = {
  year: "", make: "", model: "", trim: "", driveline: "", engine: "", cab: "",
  km: "", vin: "", seller_type: "private", asking_price: "",
}

export function Appraise({ mode, profile }: { mode: Mode; profile: string }) {
  const [f, setF] = useState<Form>(BLANK)
  const [makes, setMakes] = useState<string[]>([])
  const [models, setModels] = useState<string[]>([])
  const [trims, setTrims] = useState<string[]>([])
  const [adUrl, setAdUrl] = useState("")
  const [adMsg, setAdMsg] = useState<string | null>(null)
  const [vinMsg, setVinMsg] = useState<string | null>(null)
  const [extra, setExtra] = useState<{ source: string; photos: string[]; ad_url: string }>({ source: "manual", photos: [], ad_url: "" })
  const [result, setResult] = useState<Vehicle | null>(null)
  const [stage, setStage] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const set = (k: keyof Form, v: string) => setF((s) => ({ ...s, [k]: v }))

  useEffect(() => { api.vpicMakes().then(setMakes).catch(() => {}) }, [])
  useEffect(() => {
    if (f.year && f.make) api.vpicModels(f.make, Number(f.year)).then(setModels).catch(() => {})
  }, [f.year, f.make])
  useEffect(() => {
    if (f.year && f.make && f.model) api.vpicTrims(Number(f.year), f.make, f.model).then(setTrims).catch(() => {})
  }, [f.year, f.make, f.model])

  async function fetchAd() {
    if (!adUrl) return
    setAdMsg("fetching ad…"); setErr(null)
    try {
      const j = await api.ingestAd(adUrl)
      if (j.error) { setAdMsg("could not read ad: " + j.error); return }
      const v = j.vehicle || {}
      setF((s) => ({
        ...s, year: v.year || "", make: v.make || "", model: v.model || "", trim: v.trim || "",
        driveline: v.driveline || "", engine: v.engine || "", cab: v.cab || "",
        km: v.odometer_km || "", vin: v.vin || "",
        seller_type: j.seller_type || s.seller_type, asking_price: j.asking_price_dollars || "",
      }))
      setExtra({ source: j.source || "ad", photos: j.photos || [], ad_url: j.listing_url || adUrl })
      setAdMsg(`loaded from ${j.source} · ${(j.photos || []).length} photos — review & run`)
    } catch { setAdMsg("fetch failed") }
  }

  async function decodeVin() {
    if (!f.vin) return
    setVinMsg("decoding…")
    try {
      const d = await api.vinDecode(f.vin)
      if (!d) { setVinMsg("no decode (check the VIN)"); return }
      setF((s) => ({
        ...s, year: d.year || s.year, make: d.make || s.make, model: d.model || s.model,
        trim: d.trim || s.trim, driveline: d.driveline || s.driveline, engine: d.engine || s.engine, cab: d.cab || s.cab,
      }))
      setVinMsg("filled from VIN ✓")
    } catch { setVinMsg("decode failed") }
  }

  function run() {
    if (!f.make || !f.model) { setErr("make and model are required"); return }
    setErr(null); setResult(null); setBusy(true); setStage("starting")
    const params = new URLSearchParams({
      ...f, mode: mode === "triage" ? "triage" : "deep", profile,
      source: extra.source, ad_url: extra.ad_url, photos: extra.photos.join(","),
    })
    stream(`/api/appraise_stream?${params.toString()}`, {
      stage: setStage,
      result: (v) => { setResult(v); setBusy(false); setStage(null) },
      failed: (e) => { setErr(typeof e === "string" ? e : e?.error || "failed"); setBusy(false) },
    })
  }

  if (result) return <Card vehicle={result} mode={mode} profile={profile} onBack={() => setResult(null)} />

  return (
    <div className="mx-auto max-w-3xl px-4 py-6 lg:px-8">
      <div className="mb-2 text-xs uppercase tracking-wide text-muted-foreground">Off-auction · no buyer fee · tax per your location</div>
      <h1 className="mb-5 font-heading text-3xl font-semibold">Appraise any vehicle</h1>

      <datalist id="dl-makes">{makes.map((m) => <option key={m} value={m} />)}</datalist>
      <datalist id="dl-models">{models.map((m) => <option key={m} value={m} />)}</datalist>
      <datalist id="dl-trims">{trims.map((t) => <option key={t} value={t} />)}</datalist>

      <UICard className="mb-4 border-primary/40">
        <CardHeader><CardTitle className="text-sm">Paste an ad — Facebook · Kijiji · AutoTrader</CardTitle></CardHeader>
        <CardContent>
          <div className="flex items-end gap-2">
            <div className="flex-1">
              <Input value={adUrl} placeholder="https://facebook.com/marketplace/item/… · kijiji.ca/… · autotrader.ca/…"
                onChange={(e) => setAdUrl(e.target.value)} />
            </div>
            <Button onClick={fetchAd} disabled={!adUrl}>Fetch ad</Button>
          </div>
          {adMsg && <div className="mt-2 text-xs text-primary">{adMsg}</div>}
          {extra.photos.length > 0 && (
            <div className="mt-3 flex gap-2 overflow-x-auto">
              {extra.photos.slice(0, 8).map((p, i) => (
                <img key={i} src={p} alt="" className="h-12 shrink-0 rounded"
                  onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = "none" }} />
              ))}
            </div>
          )}
        </CardContent>
      </UICard>

      <UICard className="mb-4">
        <CardHeader><CardTitle className="text-sm">VIN shortcut</CardTitle></CardHeader>
        <CardContent>
          <div className="flex items-end gap-2">
            <div className="flex-1"><Input value={f.vin} placeholder="1C4HJXEG5JW287140" onChange={(e) => set("vin", e.target.value)} /></div>
            <Button variant="secondary" onClick={decodeVin}>Decode</Button>
          </div>
          {vinMsg && <div className="mt-2 text-xs text-primary">{vinMsg}</div>}
        </CardContent>
      </UICard>

      <UICard className="mb-4">
        <CardHeader><CardTitle className="text-sm">Vehicle</CardTitle></CardHeader>
        <CardContent className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Field label="year" k="year" f={f} set={set} type="number" />
          <Field label="make" k="make" f={f} set={set} list="dl-makes" />
          <Field label="model" k="model" f={f} set={set} list="dl-models" />
          <Field label="trim" k="trim" f={f} set={set} list="dl-trims" />
          <Field label="km" k="km" f={f} set={set} type="number" />
          <Field label="driveline" k="driveline" f={f} set={set} />
          <Field label="engine" k="engine" f={f} set={set} />
          <Field label="cab (trucks)" k="cab" f={f} set={set} />
        </CardContent>
      </UICard>

      <UICard className="mb-5">
        <CardHeader><CardTitle className="text-sm">Purchase</CardTitle></CardHeader>
        <CardContent className="grid grid-cols-2 gap-3">
          <div className="grid gap-1.5">
            <Label className="text-xs">seller type (sets tax)</Label>
            <select value={f.seller_type} onChange={(e) => set("seller_type", e.target.value)}
              className="h-9 rounded-md border bg-background px-3 text-sm">
              <option value="private">private</option>
              <option value="dealer">dealer / business</option>
            </select>
          </div>
          <Field label="asking price $" k="asking_price" f={f} set={set} type="number" />
        </CardContent>
      </UICard>

      <div className="flex items-center justify-between">
        <span className="text-xs text-muted-foreground">
          {busy ? `appraising… ${stage || ""}` : "make + model required"}
          {err && <span className="text-destructive"> · {err}</span>}
        </span>
        <Button onClick={run} disabled={busy || !f.make || !f.model}>
          {busy ? "Appraising…" : "Run deep appraisal"}
        </Button>
      </div>
    </div>
  )
}

function Field({ label, k, f, set, type = "text", list }: {
  label: string; k: keyof Form; f: Form; set: (k: keyof Form, v: string) => void; type?: string; list?: string
}) {
  return (
    <div className="grid gap-1.5">
      <Label className="text-xs">{label}</Label>
      <Input type={type} list={list} value={f[k]} onChange={(e) => set(k, e.target.value)} />
    </div>
  )
}
