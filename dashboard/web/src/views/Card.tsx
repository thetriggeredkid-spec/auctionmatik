import { useEffect, useState } from "react"
import { api, stream } from "@/lib/api"
import type { Mode, Vehicle } from "@/lib/types"
import { fmt, km, VERDICT_LABEL, verdictVariant } from "@/lib/format"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card as UICard, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import {
  Waterfall, CompsPanel, PastSalesPanel, VisionPanel, RepairPanel, ReconSalePanel,
  DeclarationsPanel, CarfaxPanel, CorrectPanel, InputsPanel,
} from "@/views/panels"

export function Card({ vehicle, mode, profile, onBack, onPrev, onNext, hasPrev, hasNext, position }: {
  vehicle: Vehicle; mode: Mode; profile: string; onBack: () => void
  onPrev?: () => void; onNext?: () => void; hasPrev?: boolean; hasNext?: boolean; position?: string
}) {
  const [v, setV] = useState<Vehicle>(vehicle)
  const [running, setRunning] = useState(false)
  const [stages, setStages] = useState<string[]>([])

  // re-sync when paging to another vehicle (App passes key=contract, but guard anyway)
  useEffect(() => { setV(vehicle); setRunning(false); setStages([]) }, [vehicle])

  // arrow keys page through the lane
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
    api.evaluate(v.contract, "triage", profile).then((res) => { setV(res); setRunning(false); setStages([]) })
      .catch(() => { setRunning(false); setStages([]) })
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
  const runLabel = mode === "deep" ? "Run deep" : "Run triage"

  const photos = v.photos || (v.photo ? [v.photo] : [])
  const tabs: [string, React.ReactNode][] = [
    ["Comps", <CompsPanel v={v} onChange={() => (v.engineMode === "deep" ? runDeep() : runTriage())} />],
    ["Past sales", <PastSalesPanel v={v} />],
    ["Vision", <VisionPanel v={v} profile={profile} photos={photos} onUpdate={setV} />],
    ["Repair", <RepairPanel v={v} />],
    ["Recon & sale", <ReconSalePanel v={v} />],
    ["Declarations", <DeclarationsPanel v={v} />],
    ["Carfax", <CarfaxPanel v={v} profile={profile} onUpdate={setV} />],
    ["Inputs", <InputsPanel v={v} profile={profile} onUpdate={setV} />],
    ["Correct", <CorrectPanel v={v} />],
  ]

  return (
    <div className="mx-auto max-w-5xl space-y-6 px-4 py-6">
      {/* top bar: back + paging */}
      <div className="flex items-center justify-between">
        <button onClick={onBack} className="text-sm text-muted-foreground hover:text-foreground">← back to lane</button>
        {(onPrev || onNext) && (
          <div className="flex items-center gap-2">
            <Button size="sm" variant="outline" onClick={onPrev} disabled={!hasPrev}>← Prev</Button>
            {position && <span className="text-xs tabular-nums text-muted-foreground">{position}</span>}
            <Button size="sm" variant="outline" onClick={onNext} disabled={!hasNext}>Next →</Button>
          </div>
        )}
      </div>

      {/* identity */}
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

      {photos.length > 0 && (
        <div className="flex gap-2 overflow-x-auto pb-1">
          {photos.slice(0, 10).map((p, i) => (
            <img key={i} src={p} alt="" className="h-40 shrink-0 rounded-lg border object-cover"
              onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = "none" }} />
          ))}
        </div>
      )}

      {/* deep-run progress — the visual cue while streaming */}
      {running && (
        <UICard className="border-primary/50">
          <CardContent className="py-4">
            <div className="flex items-center gap-2 text-sm font-medium">
              <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-primary border-t-transparent" />
              {mode === "deep" ? "Running deep appraisal…" : "Screening…"}
            </div>
            {stages.length > 0 && (
              <ol className="mt-3 space-y-1 text-sm">
                {stages.map((s, i) => {
                  const last = i === stages.length - 1
                  return (
                    <li key={i} className={`flex items-center gap-2 ${last ? "text-foreground" : "text-muted-foreground"}`}>
                      <span>{s === "failed" ? "✗" : last ? "▸" : "✓"}</span>{s}
                    </li>
                  )
                })}
              </ol>
            )}
            <div className="mt-3 h-1 w-full overflow-hidden rounded bg-muted">
              <div className="h-full w-1/3 animate-pulse rounded bg-primary" />
            </div>
          </CardContent>
        </UICard>
      )}

      {/* verdict + waterfall */}
      <div className="grid gap-5 md:grid-cols-[1.4fr_1fr]">
        <UICard>
          <CardHeader className="flex-row items-center justify-between gap-3 space-y-0">
            <div className="flex items-center gap-3">
              {v.verdict ? <Badge variant={verdictVariant(v.verdict)} className="text-base">{VERDICT_LABEL[v.verdict] || v.verdict}</Badge> : <Badge variant="outline">not scored</Badge>}
              <span className="text-xs text-muted-foreground">{v.engineMode === "deep" ? "deep AI" : v.engineMode === "triage" ? "triage" : "rules"}{v.conf ? ` · ${v.conf}` : ""}</span>
            </div>
            {v.contract && (
              <Button size="sm" onClick={mode === "deep" ? runDeep : runTriage} disabled={running}>{running ? "…" : runLabel}</Button>
            )}
          </CardHeader>
          <CardContent>
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

      {v.reasoning && (
        <UICard>
          <CardHeader><CardTitle className="text-sm">Reasoning</CardTitle></CardHeader>
          <CardContent>
            <p className="whitespace-pre-wrap text-sm leading-relaxed text-muted-foreground">{v.reasoning}</p>
            {Array.isArray(v.adjustments) && v.adjustments.length > 0 && (
              <ul className="mt-4 space-y-1.5 border-t pt-4 text-sm">
                {v.adjustments.map((a: any, i: number) => (
                  <li key={i} className="flex gap-3"><span className="w-16 shrink-0 text-right font-mono font-medium">{a.impact}</span><span className="font-medium">{a.factor}</span><span className="text-muted-foreground">— {a.evidence}</span></li>
                ))}
              </ul>
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
