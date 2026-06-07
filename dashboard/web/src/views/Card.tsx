import { useState } from "react"
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

export function Card({ vehicle, mode, profile, onBack }: {
  vehicle: Vehicle; mode: Mode; profile: string; onBack: () => void
}) {
  const [v, setV] = useState<Vehicle>(vehicle)
  const [running, setRunning] = useState(false)
  const [stage, setStage] = useState<string | null>(null)

  function reeval(m: "triage" | "deep") {
    if (!v.contract) return
    api.evaluate(v.contract, m, profile).then(setV).catch(() => {})
  }
  function runDeep() {
    if (!v.contract) return
    setRunning(true); setStage("starting")
    stream(`/api/evaluate_stream?contract=${v.contract}&mode=deep&profile=${profile}&force=1`, {
      stage: setStage,
      result: (res) => { setV(res); setRunning(false); setStage(null) },
      failed: () => { setRunning(false); setStage("failed") },
    })
  }

  const photos = v.photos || (v.photo ? [v.photo] : [])
  const tabs: [string, React.ReactNode][] = [
    ["Comps", <CompsPanel v={v} onChange={() => reeval(v.engineMode === "deep" ? "deep" : "triage")} />],
    ["Past sales", <PastSalesPanel v={v} />],
    ["Vision", <VisionPanel v={v} profile={profile} onUpdate={setV} />],
    ["Repair", <RepairPanel v={v} />],
    ["Recon & sale", <ReconSalePanel v={v} />],
    ["Declarations", <DeclarationsPanel v={v} />],
    ["Carfax", <CarfaxPanel v={v} profile={profile} onUpdate={setV} />],
    ["Inputs", <InputsPanel v={v} profile={profile} onUpdate={setV} />],
    ["Correct", <CorrectPanel v={v} />],
  ]

  return (
    <div className="mx-auto max-w-5xl px-4 py-6">
      <button onClick={onBack} className="mb-4 text-sm text-muted-foreground hover:text-foreground">← back</button>

      <div className="mb-2 flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h1 className="font-heading text-3xl font-semibold">{v.year} {v.make} {v.model}</h1>
        {v.trim && <span className="text-lg text-muted-foreground">{v.trim}</span>}
        {v.contract && <span className="font-mono text-xs text-muted-foreground">#{v.contract}</span>}
      </div>
      <div className="mb-5 flex flex-wrap gap-x-4 gap-y-1 text-sm text-muted-foreground">
        <span>{km(v.km)}</span><span>{v.driveline}</span><span>{v.engine}</span><span>{v.color}</span>
        {v.regalUrl && <a className="text-primary hover:underline" href={v.regalUrl} target="_blank" rel="noopener">Regal ↗</a>}
        {v.carfaxUrl && <a className="text-primary hover:underline" href={v.carfaxUrl} target="_blank" rel="noopener">Carfax ↗</a>}
      </div>

      {photos.length > 0 && (
        <div className="mb-6 flex gap-2 overflow-x-auto">
          {photos.slice(0, 10).map((p, i) => (
            <img key={i} src={p} alt="" className="h-40 shrink-0 rounded-lg object-cover"
              onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = "none" }} />
          ))}
        </div>
      )}

      <div className="grid gap-5 md:grid-cols-[1.4fr_1fr]">
        <UICard>
          <CardHeader className="flex-row items-center justify-between gap-3 space-y-0">
            <div className="flex items-center gap-3">
              {v.verdict ? <Badge variant={verdictVariant(v.verdict)} className="text-base">{VERDICT_LABEL[v.verdict] || v.verdict}</Badge> : <Badge variant="outline">not scored</Badge>}
              <span className="text-xs text-muted-foreground">{v.engineMode === "deep" ? "deep AI" : v.engineMode === "triage" ? "triage" : "rules"}{v.conf ? ` · ${v.conf}` : ""}</span>
            </div>
            {v.contract && <Button size="sm" onClick={runDeep} disabled={running}>{running ? (stage || "appraising…") : "Run deep"}</Button>}
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
        <UICard className="mt-5">
          <CardHeader><CardTitle className="text-sm">Reasoning</CardTitle></CardHeader>
          <CardContent>
            <p className="whitespace-pre-wrap text-sm leading-relaxed text-muted-foreground">{v.reasoning}</p>
            {Array.isArray(v.adjustments) && v.adjustments.length > 0 && (
              <ul className="mt-3 space-y-1 border-t pt-3 text-sm">
                {v.adjustments.map((a: any, i: number) => (
                  <li key={i} className="flex gap-2"><span className="w-16 shrink-0 text-right font-mono">{a.impact}</span><span className="font-medium">{a.factor}</span><span className="text-muted-foreground">— {a.evidence}</span></li>
                ))}
              </ul>
            )}
          </CardContent>
        </UICard>
      )}

      <Tabs defaultValue="Comps" className="mt-6">
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
