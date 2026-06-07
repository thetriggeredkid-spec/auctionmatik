import { useEffect, useState } from "react"
import { api } from "@/lib/api"
import { fmt } from "@/lib/format"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Card as UICard, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"

type Sale = {
  id: number; year?: number; make?: string; model?: string; trim?: string
  km?: number; condition?: string; salePrice?: number; soldDate?: string | null; notes?: string
}
const BLANK = { year: "", make: "", model: "", trim: "", km: "", condition: "", salePrice: "", soldDate: "", notes: "" }

export function SoldLog() {
  const [sales, setSales] = useState<Sale[] | null>(null)
  const [f, setF] = useState<Record<string, string>>(BLANK)
  const [busy, setBusy] = useState(false)
  const set = (k: string, v: string) => setF((s) => ({ ...s, [k]: v }))
  const load = () => api.personalSales().then(setSales).catch(() => setSales([]))
  useEffect(() => { load() }, [])

  async function add() {
    if (!f.salePrice || !f.make || !f.model) return
    setBusy(true)
    try { await api.addPersonalSale(f); setF(BLANK); await load() } finally { setBusy(false) }
  }
  async function del(id: number) { await api.deletePersonalSale(id); await load() }

  return (
    <div className="mx-auto max-w-5xl px-4 py-6">
      <div className="mb-1 text-xs uppercase tracking-wide text-muted-foreground">
        Your realized sales · {sales?.length ?? 0} on record
      </div>
      <h1 className="mb-2 font-heading text-3xl font-semibold">Sold log</h1>
      <p className="mb-5 max-w-2xl text-sm text-muted-foreground">
        Your own past sales are the strongest comps there are — real transaction prices. They feed the
        deep-mode anchor at full weight for matching year/make/model.
      </p>

      <UICard className="mb-6">
        <CardHeader><CardTitle className="text-sm">Add a sale</CardTitle></CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {[["year", "year", "number"], ["make", "make", "text"], ["model", "model", "text"], ["trim", "trim", "text"],
              ["km", "km", "number"], ["condition", "condition", "text"], ["salePrice", "sale price $", "number"], ["soldDate", "sold date", "date"]].map(
              ([k, label, type]) => (
                <div key={k} className="grid gap-1.5">
                  <Label className="text-xs">{label}</Label>
                  <Input type={type} value={f[k]} onChange={(e) => set(k, e.target.value)} />
                </div>
              ))}
          </div>
          <div className="mt-3 grid gap-1.5">
            <Label className="text-xs">notes</Label>
            <Input value={f.notes} onChange={(e) => set("notes", e.target.value)} placeholder="optional — channel, buyer, anything useful" />
          </div>
          <div className="mt-4 flex items-center justify-between">
            <span className="text-xs text-muted-foreground">make, model + sale price required</span>
            <Button onClick={add} disabled={busy || !f.salePrice || !f.make || !f.model}>{busy ? "Saving…" : "Add sale"}</Button>
          </div>
        </CardContent>
      </UICard>

      {!sales ? <Skeleton className="h-40 w-full" /> : sales.length === 0 ? (
        <div className="text-sm text-muted-foreground">No sales logged yet — add your first above.</div>
      ) : (
        <div className="overflow-hidden rounded-lg border">
          <table className="w-full text-sm">
            <thead className="bg-muted/50 text-xs uppercase text-muted-foreground">
              <tr><th className="px-3 py-2 text-left font-medium">Vehicle</th><th className="px-3 py-2 text-right font-medium">KM</th>
                <th className="px-3 py-2 text-left font-medium">Condition</th><th className="px-3 py-2 text-right font-medium">Sold for</th>
                <th className="px-3 py-2 text-left font-medium">Date</th><th className="px-3 py-2 text-left font-medium">Notes</th><th /></tr>
            </thead>
            <tbody>
              {sales.map((s) => (
                <tr key={s.id} className="border-t">
                  <td className="px-3 py-2 font-medium">{s.year} {s.make} {s.model}{s.trim ? <span className="text-muted-foreground"> {s.trim}</span> : null}</td>
                  <td className="px-3 py-2 text-right tabular-nums text-muted-foreground">{s.km ? s.km.toLocaleString() : "—"}</td>
                  <td className="px-3 py-2 text-xs text-muted-foreground">{s.condition || "—"}</td>
                  <td className="px-3 py-2 text-right font-medium tabular-nums">{fmt(s.salePrice)}</td>
                  <td className="px-3 py-2 text-xs tabular-nums text-muted-foreground">{s.soldDate || "—"}</td>
                  <td className="max-w-[240px] truncate px-3 py-2 text-xs text-muted-foreground">{s.notes}</td>
                  <td className="px-3 py-2 text-right"><Button size="sm" variant="ghost" onClick={() => del(s.id)}>✕</Button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
