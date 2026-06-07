import { useEffect, useState } from "react"
import { api } from "@/lib/api"
import { fmt } from "@/lib/format"
import { Button } from "@/components/ui/button"
import { Card as UICard, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"

const pct = (x: number | null | undefined) => (x == null ? "—" : (x > 0 ? "+" : "") + x + "%")
const biasColor = (b: number | null | undefined) =>
  b == null ? "text-muted-foreground" : Math.abs(b) < 5 ? "text-emerald-500" : Math.abs(b) < 12 ? "text-amber-500" : "text-destructive"

function Metric({ label, agg, sub }: { label: string; agg: any; sub: string }) {
  return (
    <UICard className="flex-1 min-w-[180px]">
      <CardContent className="pt-5">
        <div className="text-xs uppercase tracking-wide text-muted-foreground">{label}</div>
        <div className="font-heading text-3xl font-semibold tabular-nums">{agg?.n ? agg.mae + "%" : "—"}</div>
        <div className={`text-sm ${biasColor(agg?.bias)}`}>{agg?.n ? "bias " + pct(agg.bias) : "no data"}</div>
        <div className="mt-1 text-[11px] text-muted-foreground">{sub} · n={agg?.n ?? 0}</div>
      </CardContent>
    </UICard>
  )
}

function SegTable({ title, rows }: { title: string; rows: any[] }) {
  return (
    <UICard className="flex-1 min-w-[260px]">
      <CardHeader><CardTitle className="text-sm">Bias by {title}</CardTitle></CardHeader>
      <CardContent>
        {rows?.length ? (
          <table className="w-full text-sm">
            <thead className="text-xs uppercase text-muted-foreground"><tr><th className="text-left font-medium">{title}</th><th className="text-right font-medium">n</th><th className="text-right font-medium">MAE</th><th className="text-right font-medium">Bias</th></tr></thead>
            <tbody>{rows.map((s, i) => (
              <tr key={i}><td className="py-1 font-medium">{s.key}</td><td className="py-1 text-right tabular-nums text-muted-foreground">{s.n}</td>
                <td className="py-1 text-right tabular-nums">{s.mae == null ? "—" : s.mae + "%"}</td>
                <td className={`py-1 text-right font-medium tabular-nums ${biasColor(s.bias)}`}>{pct(s.bias)}</td></tr>
            ))}</tbody>
          </table>
        ) : <div className="text-sm text-muted-foreground">No data yet.</div>}
      </CardContent>
    </UICard>
  )
}

export function Calibration() {
  const [d, setD] = useState<any>(null)
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => { api.calibration().then(setD).catch((e) => setErr(String(e))) }, [])
  if (err) return <div className="p-8 text-sm text-muted-foreground">{err}</div>
  if (!d) return <div className="w-full px-4 py-6 lg:px-8"><Skeleton className="h-64 w-full" /></div>

  const r = d.retail || {}, w = d.wholesale || {}
  return (
    <div className="w-full px-4 py-6 lg:px-8">
      <div className="mb-1 flex items-end justify-between">
        <div>
          <div className="text-xs uppercase tracking-wide text-muted-foreground">Engine vs reality · {d.total} outcomes</div>
          <h1 className="font-heading text-3xl font-semibold">Calibration</h1>
        </div>
        <a href={api.calibrationCsvUrl} className="inline-flex h-8 items-center rounded-md border px-3 text-sm hover:bg-muted">⬇ CSV</a>
      </div>
      <p className="mb-6 max-w-3xl text-xs text-muted-foreground">
        Two tracks — they measure different engines, never averaged. MAE = miss size · bias = direction (− low, + high).
      </p>

      <div className="space-y-3">
        <div><div className="text-xs uppercase tracking-wide text-muted-foreground">Track 1 · the one that matters</div>
          <h2 className="font-heading text-xl font-semibold">Deep / retail corrections</h2></div>
        {r.total === 0 ? (
          <UICard><CardContent className="py-6 text-center text-sm text-muted-foreground">
            No retail corrections yet — run a deep appraisal and record the true value in a vehicle's Correct tab.
          </CardContent></UICard>
        ) : (
          <>
            <div className="flex flex-wrap gap-3">
              <Metric label="Retail value error" agg={r.value} sub="engine vs your corrected value" />
              <Metric label="Max-bid error" agg={r.bid} sub="engine vs your corrected bid" />
              <UICard className="flex-1 min-w-[180px]"><CardContent className="pt-5">
                <div className="text-xs uppercase tracking-wide text-muted-foreground">Verdict accuracy</div>
                <div className="font-heading text-3xl font-semibold tabular-nums">{r.verdictAccuracy == null ? "—" : r.verdictAccuracy + "%"}</div>
                <div className="mt-1 text-[11px] text-muted-foreground">n={r.verdictN || 0} · {(r.modes || []).map((m: any) => `${m.mode} ${m.n}`).join(" · ")}</div>
              </CardContent></UICard>
            </div>
            <div className="flex flex-wrap gap-3"><SegTable title="make" rows={r.byMake} /><SegTable title="band" rows={r.byBand} /></div>
          </>
        )}

        <div className="pt-3"><div className="text-xs uppercase tracking-wide text-muted-foreground">Track 2 · triage baseline</div>
          <h2 className="font-heading text-xl font-semibold">Wholesale backtest</h2></div>
        <p className="-mt-1 max-w-3xl text-xs text-muted-foreground">
          Auto-imported from {w.total || 0} past Regal sales: engine max bid vs the hammer price. Margin-affected — a comp/triage baseline, not deep accuracy.
        </p>
        {w.total === 0 ? (
          <div className="text-sm text-muted-foreground">None imported yet.</div>
        ) : (
          <>
            <div className="flex flex-wrap gap-3">
              <Metric label="Max-bid vs hammer" agg={w.bid} sub="margin-affected" />
              <UICard className="flex-1 min-w-[180px]"><CardContent className="pt-5">
                <div className="text-xs uppercase tracking-wide text-muted-foreground">Verdict accuracy</div>
                <div className="font-heading text-3xl font-semibold tabular-nums">{w.verdictAccuracy == null ? "—" : w.verdictAccuracy + "%"}</div>
                <div className="mt-1 text-[11px] text-muted-foreground">n={w.verdictN || 0}</div>
              </CardContent></UICard>
            </div>
            <div className="flex flex-wrap gap-3"><SegTable title="make" rows={w.byMake} /><SegTable title="band" rows={w.byBand} /></div>
          </>
        )}

        {d.samples?.length > 0 && (
          <div className="overflow-hidden rounded-lg border">
            <table className="w-full text-sm">
              <thead className="bg-muted/50 text-xs uppercase text-muted-foreground"><tr>
                <th className="px-3 py-2 text-left font-medium">Vehicle</th><th className="px-3 py-2 text-left font-medium">Track</th>
                <th className="px-3 py-2 text-left font-medium">Mode</th><th className="px-3 py-2 text-right font-medium">Engine val</th>
                <th className="px-3 py-2 text-right font-medium">Truth</th><th className="px-3 py-2 text-right font-medium">Val err</th>
                <th className="px-3 py-2 text-right font-medium">Bid err</th></tr></thead>
              <tbody>{d.samples.map((s: any, i: number) => {
                const truth = s.track === "retail" ? s.correctedValue : s.actualSale
                return (
                  <tr key={i} className="border-t">
                    <td className="px-3 py-2 font-medium">{s.year} {s.make} {s.model}<div className="font-mono text-[10px] text-muted-foreground">#{s.contract}</div></td>
                    <td className="px-3 py-2 text-xs">{s.track}</td><td className="px-3 py-2 text-xs text-muted-foreground">{s.engineMode || "—"}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{fmt(s.engineValue)}</td><td className="px-3 py-2 text-right tabular-nums">{fmt(truth)}</td>
                    <td className={`px-3 py-2 text-right font-medium tabular-nums ${biasColor(s.valueErrPct)}`}>{pct(s.valueErrPct)}</td>
                    <td className={`px-3 py-2 text-right font-medium tabular-nums ${biasColor(s.bidErrPct)}`}>{pct(s.bidErrPct)}</td>
                  </tr>)
              })}</tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
