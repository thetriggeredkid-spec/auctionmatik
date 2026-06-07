import { useEffect, useState } from "react"
import { api } from "@/lib/api"
import type { Sale, SaleData, Vehicle } from "@/lib/types"
import { fmt, km, VERDICT_LABEL, verdictVariant } from "@/lib/format"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"

export function Lane({ profile, onLoaded, onOpen }: {
  profile: string
  onLoaded: (vehicles: Vehicle[]) => void
  onOpen: (index: number) => void
}) {
  const [sales, setSales] = useState<Sale[] | null>(null)
  const [date, setDate] = useState<string>("")
  const [sale, setSale] = useState<SaleData | null>(null)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    api.sales().then((s) => {
      setSales(s)
      if (s.length) setDate(s[0].date)
    }).catch((e) => setErr(String(e)))
  }, [])

  useEffect(() => {
    if (!date) return
    setLoading(true); setSale(null); setErr(null)
    api.sale(date, profile)
      .then((s) => { setSale(s); onLoaded(s.vehicles || []) })
      .catch((e) => setErr(String(e)))
      .finally(() => setLoading(false))
  }, [date, profile])

  if (err) return <div className="p-8 text-sm text-muted-foreground">{err}</div>

  return (
    <div className="mx-auto max-w-6xl px-4 py-6">
      <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="text-xs uppercase tracking-wide text-muted-foreground">The lane</div>
          <h1 className="font-heading text-3xl font-semibold">
            {sale ? `${sale.label} · ${sale.date}` : "Upcoming sale"}
          </h1>
        </div>
        <div className="flex items-center gap-2">
          <select value={date} onChange={(e) => setDate(e.target.value)}
            className="h-9 rounded-md border bg-background px-3 text-sm">
            {(sales || []).map((s) => (
              <option key={s.date} value={s.date}>{s.day} {s.date} · {s.label} ({s.count})</option>
            ))}
          </select>
          {sale && (
            <span className="text-xs text-muted-foreground">{sale.screened}/{sale.count} screened</span>
          )}
        </div>
      </div>

      {loading || !sales ? (
        <div className="space-y-2">{Array.from({ length: 8 }).map((_, i) => <Skeleton key={i} className="h-16 w-full" />)}</div>
      ) : (
        <div className="overflow-hidden rounded-lg border">
          <table className="w-full text-sm">
            <thead className="bg-muted/50 text-xs uppercase text-muted-foreground">
              <tr>
                <th className="px-3 py-2 text-left font-medium">Lot</th>
                <th className="px-3 py-2 text-left font-medium">Vehicle</th>
                <th className="px-3 py-2 text-right font-medium">KM</th>
                <th className="px-3 py-2 text-left font-medium">Verdict</th>
                <th className="px-3 py-2 text-right font-medium">Value</th>
                <th className="px-3 py-2 text-right font-medium">Max bid</th>
                <th className="px-3 py-2"></th>
              </tr>
            </thead>
            <tbody>
              {(sale?.vehicles || []).map((v, i) => (
                <tr key={v.contract}
                  className="cursor-pointer border-t hover:bg-muted/40"
                  onClick={() => onOpen(i)}>
                  <td className="px-3 py-2 font-mono text-xs text-muted-foreground">{v.lot || "—"}</td>
                  <td className="px-3 py-2">
                    <div className="flex items-center gap-2">
                      {v.photo && <img src={v.photo} alt="" className="h-9 w-12 shrink-0 rounded object-cover"
                        onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = "none" }} />}
                      <div>
                        <div className="font-medium">{v.year} {v.make} {v.model}{v.trim ? ` ${v.trim}` : ""}</div>
                        <div className="font-mono text-[10px] text-muted-foreground">#{v.contract}</div>
                      </div>
                    </div>
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-muted-foreground">{km(v.km)}</td>
                  <td className="px-3 py-2">
                    {v.verdict ? (
                      <div className="flex items-center gap-1.5">
                        <Badge variant={verdictVariant(v.verdict)}>{VERDICT_LABEL[v.verdict] || v.verdict}</Badge>
                        {v.deepReady && <span title="deep result ready" className="text-xs text-primary">deep ✓</span>}
                        {v.needsDeep && <span title={v.deepReason || "worth a deep run"} className="text-xs text-amber-500">⚑</span>}
                      </div>
                    ) : <span className="text-xs text-muted-foreground">not scored</span>}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">{fmt(v.value)}</td>
                  <td className="px-3 py-2 text-right font-medium tabular-nums">{fmt(v.maxBid)}</td>
                  <td className="px-3 py-2 text-right">
                    <Button size="sm" variant="ghost" onClick={(e) => { e.stopPropagation(); onOpen(i) }}>Open →</Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
