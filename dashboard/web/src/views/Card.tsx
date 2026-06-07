import { useEffect, useState } from "react"
import { Loader2 } from "lucide-react"
import { api, stream } from "@/lib/api"
import type { Mode, Vehicle } from "@/lib/types"
import { fmt, img, km, VERDICT_LABEL, verdictVariant } from "@/lib/format"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card as UICard, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { ScrollArea } from "@/components/ui/scroll-area"
import {
  Waterfall, AdjustmentsViz, CompsPanel, PastSalesPanel, VisionPanel, RepairPanel,
  ReconSalePanel, DeclarationsPanel, CarfaxPanel, CorrectPanel, InputsPanel,
} from "@/views/panels"

const CHECKPOINTS = [
  { label: "Comps", match: ["comp", "live comps"] },
  { label: "Photos", match: ["photo", "vision"] },
  { label: "Screening", match: ["screen"] },
  { label: "Carfax", match: ["carfax"] },
  { label: "VMR", match: ["vmr", "book"] },
  { label: "AI", match: ["appraising", "ai"] },
]
function stageIndex(stages: string[]): number {
  let idx = -1
  for (const s of stages) {
    const low = s.toLowerCase()
    CHECKPOINTS.forEach((c, i) => { if (c.match.some((m) => low.includes(m))) idx = Math.max(idx, i) })
  }
  return idx
}

// High-impact declarations to surface on the hero (value drivers); low-impact (finance
// repo, trade-in, unreserved, repaint, out-of-province, auctioneer note) are excluded.
const KEY_DECL: Record<string, { label: string; variant: "destructive" | "secondary" }> = {
  salvage_route: { label: "Frame / Salvage", variant: "destructive" },
  rebuilt_title: { label: "Rebuilt", variant: "destructive" },
  mechanical_problem: { label: "Mechanical", variant: "destructive" },
  airbag_light: { label: "Airbag/SRS", variant: "destructive" },
  freezing_damage: { label: "Freezing dmg", variant: "destructive" },
  hail_damage: { label: "Hail", variant: "secondary" },
  claims_history: { label: "Claims", variant: "secondary" },
}
function keyDeclBadges(v: Vehicle): { label: string; variant: "destructive" | "secondary"; msg: string }[] {
  const flags = v.decl?.flags || []
  const claimsLow = v.decl?.claimsLow || 0
  const out: { label: string; variant: "destructive" | "secondary"; msg: string }[] = []
  for (const f of flags) {
    const k = KEY_DECL[f.code]
    if (!k) continue
    if (f.code === "claims_history" && claimsLow < 5000) continue  // only CH ≥ $5k
    out.push({ ...k, msg: f.msg })
  }
  return out
}

export function Card({ vehicle, mode, profile, onBack, onPrev, onNext, hasPrev, hasNext, position }: {
  vehicle: Vehicle; mode: Mode; profile: string; onBack: () => void
  onPrev?: () => void; onNext?: () => void; hasPrev?: boolean; hasNext?: boolean; position?: string
}) {
  const [v, setV] = useState<Vehicle>(vehicle)
  const [running, setRunning] = useState(false)
  const [stages, setStages] = useState<string[]>([])

  useEffect(() => { setV(vehicle); setRunning(false); setStages([]) }, [vehicle])
  useEffect(() => {
    if (vehicle.contract && vehicle.engineMode !== "deep") {
      api.evaluateCachedDeep(vehicle.contract, profile)
        .then((res) => { if (res?.engineMode === "deep") setV(res) }).catch(() => {})
    }
  }, [vehicle.contract, profile])
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement)?.tagName?.match(/INPUT|TEXTAREA|SELECT/)) return
      if (e.key === "ArrowLeft" && hasPrev) onPrev?.()
      if (e.key === "ArrowRight" && hasNext) onNext?.()
    }
    window.addEventListener("keydown", h)
    return () => window.removeEventListener("keydown", h)
  }, [hasPrev, hasNext, onPrev, onNext])

  function runTriage() {
    if (!v.contract) return
    setRunning(true); setStages(["screening"])
    api.evaluate(v.contract, "triage", profile).then((res) => { setV(res); setRunning(false); setStages([]) }).catch(() => { setRunning(false); setStages([]) })
  }
  function runDeep() {
    if (!v.contract) return
    setRunning(true); setStages([])
    stream(`/api/evaluate_stream?contract=${v.contract}&mode=deep&profile=${profile}&force=1`, {
      stage: (s) => setStages((p) => [...p, s]),
      result: (res) => { setV(res); setRunning(false); setStages([]) },
      failed: () => { setRunning(false); setStages((p) => [...p, "failed"]) },
    })
  }

  const photos = v.photos || (v.photo ? [v.photo] : [])
  const idx = stageIndex(stages)
  const failed = stages.includes("failed")
  const keyDecls = keyDeclBadges(v)
  const tabs: [string, React.ReactNode][] = [
    ["Comps", <CompsPanel v={v} onChange={() => (v.engineMode === "deep" ? runDeep() : runTriage())} />],
    ["Past sales", <PastSalesPanel v={v} />],
    ["Repair", <RepairPanel v={v} />],
    ["Recon & sale", <ReconSalePanel v={v} />],
    ["Declarations", <DeclarationsPanel v={v} />],
    ["Carfax", <CarfaxPanel v={v} profile={profile} onUpdate={setV} />],
    ["Inputs", <InputsPanel v={v} profile={profile} onUpdate={setV} />],
    ["Correct", <CorrectPanel v={v} />],
  ]

  return (
    <div className="w-full px-4 py-6 lg:px-8">
      <div className="mb-4 flex items-center justify-between">
        <button onClick={onBack} className="text-sm text-muted-foreground hover:text-foreground">← back to lane</button>
        {(onPrev || onNext) && (
          <div className="flex items-center gap-2">
            <Button size="sm" variant="outline" onClick={onPrev} disabled={!hasPrev}>← Prev</Button>
            {position && <span className="text-xs tabular-nums text-muted-foreground">{position}</span>}
            <Button size="sm" variant="outline" onClick={onNext} disabled={!hasNext}>Next →</Button>
          </div>
        )}
      </div>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_340px]">
        {/* LEFT: analysis */}
        <div className="space-y-6">
          <div className="space-y-1.5">
            <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
              <h1 className="font-heading text-3xl font-semibold">{v.year} {v.make} {v.model}</h1>
              {v.trim && <span className="text-lg text-muted-foreground">{v.trim}</span>}
              {v.contract && <span className="font-mono text-xs text-muted-foreground">#{v.contract}</span>}
              {v.lot && <Badge variant="outline" className="font-mono">lot {v.lot}</Badge>}
            </div>
            <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm text-muted-foreground">
              <span>{km(v.km)}</span><span>{v.driveline}</span><span>{v.engine}</span><span>{v.color}</span>
              {v.regalUrl && <a className="text-primary hover:underline" href={v.regalUrl} target="_blank" rel="noopener">Regal ↗</a>}
              {v.carfaxUrl && <a className="text-primary hover:underline" href={v.carfaxUrl} target="_blank" rel="noopener">Carfax ↗</a>}
            </div>
          </div>

          {running && (
            <UICard className="border-primary/50">
              <CardContent className="py-4">
                <div className="mb-2 flex gap-1">
                  {CHECKPOINTS.map((c, i) => (
                    <div key={c.label} className="flex-1">
                      <div className={`h-1.5 rounded-full ${i <= idx ? (failed ? "bg-destructive" : "bg-sky-500") : "bg-muted"}`} />
                      <div className={`mt-1 text-center text-[10px] ${i <= idx ? "text-foreground" : "text-muted-foreground"}`}>{c.label}</div>
                    </div>
                  ))}
                </div>
                <div className="flex h-5 items-center gap-2 text-xs text-muted-foreground">
                  {!failed && <Loader2 className="size-3 animate-spin" />}
                  <span className="truncate">{failed ? "failed — try again" : (stages[stages.length - 1] || "starting…")}</span>
                </div>
              </CardContent>
            </UICard>
          )}

          <div className="grid gap-5 xl:grid-cols-[1.4fr_1fr]">
            <UICard>
              <CardHeader className="flex-row items-center justify-between gap-3 space-y-0">
                <div className="flex items-center gap-3">
                  {v.verdict ? <Badge variant={verdictVariant(v.verdict)} className="text-base">{VERDICT_LABEL[v.verdict] || v.verdict}</Badge> : <Badge variant="outline">not scored</Badge>}
                  <span className="text-xs text-muted-foreground">{v.engineMode === "deep" ? "deep AI" : v.engineMode === "triage" ? "triage" : "rules"}{v.conf ? ` · ${v.conf}` : ""}</span>
                </div>
                {v.contract && <Button size="sm" onClick={mode === "deep" ? runDeep : runTriage} disabled={running}>{running ? "…" : mode === "deep" ? "Run deep" : "Run triage"}</Button>}
              </CardHeader>
              <CardContent>
                {keyDecls.length > 0 && (
                  <div className="mb-3 flex flex-wrap gap-1.5">
                    {keyDecls.map((d, i) => <Badge key={i} variant={d.variant} title={d.msg}>⚠ {d.label}</Badge>)}
                  </div>
                )}
                <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
                  <Stat label={v.valueBasis || "value"} value={fmt(v.value)} />
                  <Stat label={v.source ? "max buy" : "max bid"} value={fmt(v.maxBid)} big />
                  {v.askingPrice != null && <Stat label="asking" value={fmt(v.askingPrice)} sub={v.dealLabel || ""} />}
                </div>
                {v.summary && <p className="mt-4 text-sm leading-relaxed text-muted-foreground">{v.summary}</p>}
                {v.conditional?.amount ? <p className="mt-2 text-sm">Conditional: bid {fmt(v.conditional.amount)} if {v.conditional.condition}</p> : null}
              </CardContent>
            </UICard>

            <UICard>
              <CardHeader><CardTitle className="text-sm">{v.source ? "Max-buy" : "Max-bid"} derivation</CardTitle></CardHeader>
              <CardContent><Waterfall v={v} /></CardContent>
            </UICard>
          </div>

          {(v.reasoning || (v.adjustments && v.adjustments.length > 0)) && (
            <UICard>
              <CardHeader><CardTitle className="text-sm">Reasoning</CardTitle></CardHeader>
              <CardContent className="space-y-4">
                {v.reasoning && <p className="whitespace-pre-wrap text-sm leading-relaxed text-muted-foreground">{v.reasoning}</p>}
                {Array.isArray(v.adjustments) && v.adjustments.length > 0 && (
                  <div className="border-t pt-4">
                    <div className="mb-3 text-xs uppercase tracking-wide text-muted-foreground">Key adjustments</div>
                    <AdjustmentsViz items={v.adjustments} />
                  </div>
                )}
              </CardContent>
            </UICard>
          )}

          <Tabs defaultValue="Comps">
            <TabsList className="flex flex-wrap">
              {tabs.map(([name]) => <TabsTrigger key={name} value={name}>{name}</TabsTrigger>)}
            </TabsList>
            {tabs.map(([name, node]) => (
              <TabsContent key={name} value={name} className="mt-4">
                <UICard><CardContent className="pt-6">{node}</CardContent></UICard>
              </TabsContent>
            ))}
          </Tabs>
        </div>

        {/* RIGHT: photos (vertical scroll) + vision */}
        <div className="lg:sticky lg:top-20 lg:self-start">
          <ScrollArea className="h-auto lg:h-[calc(100svh-7rem)]">
            <div className="space-y-3 pr-3">
              {photos.length > 0 ? photos.map((p, i) => (
                <img key={i} src={img(p)} alt="" loading="lazy"
                  className="w-full rounded-lg border bg-muted object-cover"
                  onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = "none" }} />
              )) : <div className="rounded-lg border border-dashed p-6 text-center text-sm text-muted-foreground">No photos</div>}
              <UICard>
                <CardHeader><CardTitle className="text-sm">Vision</CardTitle></CardHeader>
                <CardContent><VisionPanel v={v} profile={profile} photos={[]} onUpdate={setV} /></CardContent>
              </UICard>
            </div>
          </ScrollArea>
        </div>
      </div>
    </div>
  )
}

function Stat({ label, value, sub, big }: { label: string; value: string; sub?: string; big?: boolean }) {
  return (
    <div>
      <div className="text-xs uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className={`font-heading font-semibold tabular-nums ${big ? "text-2xl" : "text-xl"}`}>{value}</div>
      {sub && <div className="text-xs text-muted-foreground">{sub}</div>}
    </div>
  )
}
