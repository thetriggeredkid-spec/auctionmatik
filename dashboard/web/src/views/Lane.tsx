import { useEffect, useMemo, useRef, useState } from "react"
import { Search, RefreshCw, Play, Loader2 } from "lucide-react"
import { api } from "@/lib/api"
import type { Sale, SaleData, Vehicle } from "@/lib/types"
import { fmt, img, km, VERDICT_LABEL, verdictVariant } from "@/lib/format"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"

export function Lane({ profile, date, setDate, onLoaded, onOpen }: {
  profile: string
  date: string
  setDate: (d: string) => void
  onLoaded: (vehicles: Vehicle[]) => void
  onOpen: (index: number) => void
}) {
  const [sales, setSales] = useState<Sale[] | null>(null)
  const [sale, setSale] = useState<SaleData | null>(null)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [q, setQ] = useState("")
  const [runJob, setRunJob] = useState<any>(null)   // {status,done,total,current}
  const [refreshing, setRefreshing] = useState(false)
  const poll = useRef<number | null>(null)

  function reload() {
    if (!date) return
    api.sale(date, profile).then((s) => { setSale(s); onLoaded(s.vehicles || []) }).catch(() => {})
  }

  async function runAll() {
    if (!date || !sale) return
    if (!confirm(`Deep-appraise all ${sale.count} vehicles? ~$${(sale.count * 0.04).toFixed(2)} and a few minutes (cached cars are skipped; you can cancel).`)) return
    try {
      const job = await api.runAll(date, profile); setRunJob(job)
      poll.current = window.setInterval(async () => {
        const r = await api.runStatus(date).catch(() => null)
        const j = r?.job || (r?.status === "idle" ? null : r)
        setRunJob(j)
        if (!j || j.status !== "running") { clearInterval(poll.current!); poll.current = null; reload() }
      }, 2500)
    } catch (e) { setErr(String(e)) }
  }
  async function cancelRun() { if (date) await api.runCancel(date).catch(() => {}) }

  async function refresh() {
    setRefreshing(true)
    try {
      await api.refreshListings()
      const iv = window.setInterval(async () => {
        const r = await api.refreshStatus().catch(() => null)
        if (!r || r.status !== "running") { clearInterval(iv); setRefreshing(false); api.sales().then(setSales); reload() }
      }, 2500)
    } catch { setRefreshing(false) }
  }

  useEffect(() => () => { if (poll.current) clearInterval(poll.current) }, [])

  useEffect(() => {
    api.sales().then((s) => {
      setSales(s)
      if (!date && s.length) setDate(s[0].date)   // only default when nothing was selected
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

  const rows = useMemo(() => {
    const list = sale?.vehicles || []
    if (!q.trim()) return list.map((v, i) => ({ v, i }))
    const needle = q.toLowerCase()
    return list.map((v, i) => ({ v, i })).filter(({ v }) =>
      `${v.year} ${v.make} ${v.model} ${v.trim} ${v.lot} ${v.contract}`.toLowerCase().includes(needle))
  }, [sale, q])

  if (err) return <div className="p-8 text-sm text-muted-foreground">{err}</div>

  return (
    <div className="w-full px-4 py-6 lg:px-8">
      <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="text-xs uppercase tracking-wide text-muted-foreground">The lane</div>
          <h1 className="font-heading text-3xl font-semibold">{sale ? `${sale.label} · ${sale.date}` : "Upcoming sale"}</h1>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative">
            <Search className="absolute left-2.5 top-2.5 size-4 text-muted-foreground" />
            <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search make / model / lot / #"
              className="w-56 pl-8" />
          </div>
          <Select value={date} onValueChange={(v) => v && setDate(v)}>
            <SelectTrigger className="w-[260px]"><SelectValue placeholder="Pick a sale" /></SelectTrigger>
            <SelectContent>
              {(sales || []).map((s) => (
                <SelectItem key={s.date} value={s.date}>{s.day} {s.date} · {s.label} ({s.count})</SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button variant="outline" size="sm" onClick={refresh} disabled={refreshing} title="Re-scrape Regal listings (lots + photos)">
            <RefreshCw className={`size-4 ${refreshing ? "animate-spin" : ""}`} /> Refresh
          </Button>
          {runJob?.status === "running" ? (
            <Button variant="destructive" size="sm" onClick={cancelRun}>Cancel ({runJob.done}/{runJob.total})</Button>
          ) : (
            <Button size="sm" onClick={runAll} disabled={!sale}><Play className="size-4" /> Run all (deep)</Button>
          )}
          {sale && <span className="text-xs text-muted-foreground">{sale.screened}/{sale.count} screened</span>}
        </div>
      </div>

      {runJob?.status === "running" && (
        <div className="mb-4 rounded-lg border border-primary/50 p-3">
          <div className="mb-2 flex items-center gap-2 text-sm">
            <Loader2 className="size-4 animate-spin" />
            Deep-appraising the sale — {runJob.done}/{runJob.total}
            {runJob.current && <span className="font-mono text-xs text-muted-foreground">#{runJob.current}</span>}
          </div>
          <div className="h-1.5 w-full overflow-hidden rounded bg-muted">
            <div className="h-full rounded bg-sky-500 transition-all"
              style={{ width: `${runJob.total ? (runJob.done / runJob.total) * 100 : 0}%` }} />
          </div>
        </div>
      )}

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
              {rows.map(({ v, i }) => (
                <tr key={v.contract} className="cursor-pointer border-t hover:bg-muted/40" onClick={() => onOpen(i)}>
                  <td className="px-3 py-2 font-mono text-xs text-muted-foreground">{v.lot || "—"}</td>
                  <td className="px-3 py-2">
                    <div className="flex items-center gap-2">
                      {v.photo && <img src={img(v.photo)} alt="" loading="lazy" className="h-9 w-12 shrink-0 rounded bg-muted object-cover"
                        onError={(e) => { (e.currentTarget as HTMLImageElement).style.visibility = "hidden" }} />}
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
                        {v.deepReady && <span title="deep result ready" className="text-xs text-sky-500">deep ✓</span>}
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
