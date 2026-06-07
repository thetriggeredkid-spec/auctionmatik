import { useState } from "react"
import { api } from "@/lib/api"
import type { Vehicle } from "@/lib/types"
import { fmt, img } from "@/lib/format"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"

const muted = "text-sm text-muted-foreground"

// ── Max-bid waterfall — a stacked bar showing how the sale value splits into your
//    max bid + the costs (margin, fee, tax) that come off it. ──────────────────
export function Waterfall({ v }: { v: Vehicle }) {
  const value = v.value || 0
  const segs = [
    { label: v.source ? "max buy" : "max bid", amt: v.maxBid || 0, color: "bg-primary", text: "text-primary" },
    { label: "margin", amt: v.margin || 0, color: "bg-amber-500", text: "text-amber-500" },
    ...(v.buyerFee ? [{ label: "auction fee", amt: v.buyerFee || 0, color: "bg-orange-500", text: "text-orange-500" }] : []),
    ...(v.gst ? [{ label: "tax/GST", amt: v.gst || 0, color: "bg-rose-500", text: "text-rose-500" }] : []),
  ]
  const total = Math.max(value, segs.reduce((s, x) => s + x.amt, 0)) || 1
  return (
    <div className="space-y-3">
      <div className="flex items-baseline justify-between">
        <span className={`text-xs uppercase ${muted}`}>{v.valueBasis || "sale value"}</span>
        <span className="font-heading text-lg font-semibold tabular-nums">{fmt(value)}</span>
      </div>
      <div className="flex h-3 w-full overflow-hidden rounded-full bg-muted">
        {segs.map((s, i) => (
          <div key={i} className={s.color} style={{ width: `${(s.amt / total) * 100}%` }} title={`${s.label} ${fmt(s.amt)}`} />
        ))}
      </div>
      <div className="space-y-1.5">
        {segs.map((s, i) => (
          <div key={i} className="flex items-center justify-between text-sm">
            <span className="flex items-center gap-2">
              <span className={`inline-block h-2.5 w-2.5 rounded-sm ${s.color}`} />
              <span className={i === 0 ? "font-medium" : muted}>{s.label}</span>
            </span>
            <span className={`tabular-nums ${i === 0 ? "font-semibold" : muted}`}>{fmt(s.amt)}</span>
          </div>
        ))}
      </div>
      {v.divergence && <p className="border-t pt-2 text-xs text-muted-foreground">{v.divergence}</p>}
    </div>
  )
}

// ── Key adjustments — visual +/− breakdown (was raw text) ────────────────────
export function AdjustmentsViz({ items }: { items: any[] }) {
  const parsed = (items || []).map((a) => {
    const s = String(a.impact || "")
    const neg = s.includes("-") || s.includes("−")
    const isPct = s.includes("%")
    const num = parseFloat(s.replace(/[^0-9.]/g, "")) || 0
    return { ...a, neg, isPct, num }
  })
  const maxDollar = Math.max(1, ...parsed.filter((p) => !p.isPct).map((p) => p.num))
  if (!parsed.length) return null
  return (
    <ul className="space-y-2.5">
      {parsed.map((a, i) => (
        <li key={i} className="grid grid-cols-[1fr_auto] items-center gap-x-4">
          <div className="min-w-0">
            <div className="font-medium">{a.factor}</div>
            <div className="truncate text-xs text-muted-foreground">{a.evidence}</div>
          </div>
          <div className="flex items-center gap-2">
            <div className="hidden h-2 w-24 overflow-hidden rounded bg-muted sm:block">
              <div className={`h-full ${a.neg ? "bg-rose-500" : "bg-emerald-500"}`}
                style={{ width: a.isPct ? "45%" : `${Math.min(100, (a.num / maxDollar) * 100)}%` }} />
            </div>
            <span className={`w-20 text-right font-mono text-sm font-semibold tabular-nums ${a.neg ? "text-rose-500" : "text-emerald-500"}`}>{a.impact}</span>
          </div>
        </li>
      ))}
    </ul>
  )
}

// ── Comps ─────────────────────────────────────────────────────────────────────
export function CompsPanel({ v, onChange }: { v: Vehicle; onChange: () => void }) {
  const c = v.comps
  if (!c || c.empty) return <p className={muted}>No retail comps. Run a deep appraisal (or the comp-coverage batch) to populate.</p>
  async function flag(id: string) {
    const reason = prompt("Why is this comp bad? (e.g. cracked bumper / rust / wrong trim)")
    if (reason == null) return
    await api.flagComp({ externalId: id, contract: v.contract, reason })
    onChange()
  }
  return (
    <div>
      <p className={`mb-3 ${muted}`}>Anchor <b className="text-foreground">{fmt(c.anchor)}</b> · {c.conf} confidence · {c.used?.length || 0} comps · {c.source}</p>
      <div className="overflow-hidden rounded-md border">
        <table className="w-full text-sm">
          <thead className="bg-muted/50 text-xs uppercase text-muted-foreground"><tr>
            <th className="px-2 py-1.5 text-left font-medium">Comp</th><th className="px-2 py-1.5 text-right font-medium">KM</th>
            <th className="px-2 py-1.5 text-right font-medium">Ask</th><th className="px-2 py-1.5 text-right font-medium">km-adj</th>
            <th className="px-2 py-1.5 text-left font-medium">Cond</th><th className="px-2 py-1.5 text-right font-medium">Score</th><th /></tr></thead>
          <tbody>{(c.used || []).map((cm: any, i: number) => (
            <tr key={i} className="border-t">
              <td className="px-2 py-1.5">
                <div className="flex items-center gap-2">
                  {cm.photo && <img src={img(cm.photo)} alt="" loading="lazy" className="h-9 w-12 shrink-0 rounded bg-muted object-cover"
                    onError={(e) => { (e.currentTarget as HTMLImageElement).style.visibility = "hidden" }} />}
                  <div className="min-w-0">
                    {cm.url ? <a className="text-primary hover:underline" href={cm.url} target="_blank" rel="noopener">{cm.y} {cm.mk} {cm.md}{cm.trim ? " " + cm.trim : ""} ↗</a>
                      : <span>{cm.y} {cm.mk} {cm.md}</span>}
                    <div className="flex items-center gap-1.5 text-[10px] text-muted-foreground">
                      {cm.realized && <Badge variant="default" className="px-1 py-0 text-[9px]">SOLD</Badge>}
                      <span>{cm.src}</span>
                    </div>
                  </div>
                </div>
              </td>
              <td className="px-2 py-1.5 text-right tabular-nums text-muted-foreground">{cm.km ? (cm.km / 1000).toFixed(0) + "k" : "—"}</td>
              <td className="px-2 py-1.5 text-right tabular-nums">{fmt(cm.ask)}</td>
              <td className="px-2 py-1.5 text-right font-medium tabular-nums">{fmt(cm.kmAdj)}</td>
              <td className="px-2 py-1.5 text-xs">{cm.cond}</td>
              <td className="px-2 py-1.5 text-right tabular-nums text-muted-foreground">{cm.score}</td>
              <td className="px-2 py-1.5 text-right">{cm.id && <button className="text-xs text-muted-foreground hover:text-destructive" title="flag bad comp" onClick={() => flag(cm.id)}>⚑</button>}</td>
            </tr>
          ))}</tbody>
        </table>
      </div>
      {c.excluded?.length > 0 && (
        <div className="mt-3 text-xs text-muted-foreground">
          <div className="mb-1 uppercase">Excluded ({c.excluded.length})</div>
          {c.excluded.map((e: any, i: number) => <div key={i}>{e.y} {e.mk} {e.md} — {e.reason}</div>)}
        </div>
      )}
    </div>
  )
}

// ── Past sales ────────────────────────────────────────────────────────────────
export function PastSalesPanel({ v }: { v: Vehicle }) {
  const p = v.pastSales
  if (!p) return <p className={muted}>No similar past Regal sales found.</p>
  return (
    <div>
      <p className={`mb-3 ${muted}`}>Median <b className="text-foreground">{fmt(p.median)}</b> · {p.count} sales ({p.cleanCount} clean) · {p.confidence}{p.fallback ? " · fallback" : ""}</p>
      <div className="overflow-hidden rounded-md border">
        <table className="w-full text-sm">
          <thead className="bg-muted/50 text-xs uppercase text-muted-foreground"><tr>
            <th className="px-2 py-1.5 text-left font-medium">Vehicle</th><th className="px-2 py-1.5 text-right font-medium">KM</th>
            <th className="px-2 py-1.5 text-right font-medium">Sold</th><th className="px-2 py-1.5 text-left font-medium">Date</th>
            <th className="px-2 py-1.5 text-left font-medium">Decl</th></tr></thead>
          <tbody>{(p.rows || []).map((r: any, i: number) => (
            <tr key={i} className="border-t">
              <td className="px-2 py-1.5">{r.url ? <a className="text-primary hover:underline" href={r.url} target="_blank" rel="noopener">{r.y} {r.mk} {r.md} {r.trim} ↗</a> : <>{r.y} {r.mk} {r.md} {r.trim}</>}</td>
              <td className="px-2 py-1.5 text-right tabular-nums text-muted-foreground">{r.km ? (r.km / 1000).toFixed(0) + "k" : "—"}</td>
              <td className="px-2 py-1.5 text-right font-medium tabular-nums">{fmt(r.price)}</td>
              <td className="px-2 py-1.5 text-xs text-muted-foreground">{r.date}</td>
              <td className="px-2 py-1.5 text-xs text-muted-foreground">{r.decl}</td>
            </tr>
          ))}</tbody>
        </table>
      </div>
    </div>
  )
}

// ── Vision ────────────────────────────────────────────────────────────────────
export function VisionPanel({ v, profile, photos, onUpdate }: { v: Vehicle; profile: string; photos?: string[]; onUpdate: (v: Vehicle) => void }) {
  const [busy, setBusy] = useState(false)
  const va = v.vision
  const pics = photos || v.photos || (v.photo ? [v.photo] : [])
  async function run() {
    if (!v.contract) return
    setBusy(true)
    try { onUpdate(await api.runVision(v.contract, profile)) } finally { setBusy(false) }
  }
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3">
        {v.contract && <Button size="sm" variant="secondary" onClick={run} disabled={busy}>{busy ? "Reading photos…" : va ? "Re-run vision" : "Run vision"}</Button>}
        {!va && <span className={muted}>Vision runs on a deep appraisal (or click Run vision).</span>}
      </div>
      {pics.length > 0 && (
        <div className="flex gap-2 overflow-x-auto pb-1">
          {pics.slice(0, 12).map((p, i) => (
            <img key={i} src={img(p)} alt="" loading="lazy" className="h-24 shrink-0 rounded-md border bg-muted object-cover"
              onError={(e) => { (e.currentTarget as HTMLImageElement).style.visibility = "hidden" }} />
          ))}
        </div>
      )}
      {!va ? null : (
        <>
          <div className="flex flex-wrap gap-x-6 gap-y-1 text-sm">
            <span>ext <b>{va.extGrade}/5</b></span><span>int <b>{va.intGrade}/5</b></span>
            <span>rust {va.rust}</span><span>hail {va.hail}</span>
            {va.flood && <Badge variant="destructive">flood/frame</Badge>}
            <span className="text-muted-foreground">{va.analyzed}/{va.total} photos · {va.model}</span>
          </div>
          {va.dashLights?.length > 0 && <div className="text-sm">Dash lights: {va.dashLights.map((l: string) => <Badge key={l} variant="destructive" className="mr-1">{l}</Badge>)}</div>}
          {va.damage?.length > 0 && <ul className="text-sm text-muted-foreground">{va.damage.map((d: any, i: number) => <li key={i}>· {d.sev} {d.panel} {d.type}</li>)}</ul>}
          {va.mods?.length > 0 && <div className={muted}>Mods: {va.mods.map((m: any) => `${m.type} (${m.quality})`).join(", ")}</div>}
        </>
      )}
    </div>
  )
}

// ── Repair ────────────────────────────────────────────────────────────────────
export function RepairPanel({ v }: { v: Vehicle }) {
  const r = v.repair
  if (!r) return <p className={muted}>No repair estimate (clean vehicle).</p>
  return (
    <div className="space-y-3 text-sm">
      <div className="flex gap-4">
        {Object.entries(r.sourcing || {}).map(([k, e]: any) => (
          <div key={k}><div className="text-xs uppercase text-muted-foreground">{k}</div><div className="font-medium tabular-nums">{fmt(e.low)}–{fmt(e.high)}</div></div>
        ))}
      </div>
      <ul className="space-y-1">{(r.lineItems || []).map((li: any, i: number) => (
        <li key={i} className="flex justify-between"><span>{li.comp} <span className="text-muted-foreground">({li.action}, {li.sev}){li.contingent ? " · contingent" : ""}</span></span><span className="tabular-nums">{fmt(li.low)}–{fmt(li.high)}</span></li>
      ))}</ul>
    </div>
  )
}

// ── Recon & sale ──────────────────────────────────────────────────────────────
export function ReconSalePanel({ v }: { v: Vehicle }) {
  return (
    <div className="space-y-4 text-sm">
      <div>
        <div className="mb-1 text-xs uppercase text-muted-foreground">Recon plan</div>
        {(v.recon || []).length ? <ul className="space-y-1">{v.recon!.map((it: any, i: number) => (
          <li key={i} className="flex gap-2"><Badge variant="outline" className="shrink-0">{it.decision}</Badge><span className="tabular-nums">{fmt(it.cost)}</span><span className="text-muted-foreground">{it.action} — {it.why}</span></li>
        ))}</ul> : <p className={muted}>No recon work.</p>}
      </div>
      {v.sale && <div>
        <div className="mb-1 text-xs uppercase text-muted-foreground">Sale plan</div>
        <p>{v.sale.channel} · list {fmt(v.sale.list)} / floor {fmt(v.sale.floor)} · {v.sale.days}</p>
      </div>}
    </div>
  )
}

// ── Declarations ──────────────────────────────────────────────────────────────
export function DeclarationsPanel({ v }: { v: Vehicle }) {
  const d = v.decl
  if (!d) return <p className={muted}>No declarations.</p>
  return (
    <div className="space-y-3 text-sm">
      {d.raw && <div className="font-mono text-xs text-muted-foreground">{d.raw}</div>}
      <div className="flex flex-wrap gap-1.5">{(d.chips || []).map((ch: any, i: number) => (
        <Badge key={i} variant={ch.sev === "hi" ? "destructive" : ch.sev === "med" ? "secondary" : "outline"}>{ch.code} {ch.label}</Badge>
      ))}</div>
      {(d.flags || []).map((fl: any, i: number) => <div key={i} className="text-muted-foreground">⚑ {fl.msg}</div>)}
      {(d.codes || []).map((co: any, i: number) => <div key={i} className="text-xs"><b>{co.code}</b> {co.label} — <span className="text-muted-foreground">{co.meaning}</span></div>)}
    </div>
  )
}

// ── Carfax ────────────────────────────────────────────────────────────────────
export function CarfaxPanel({ v, profile, onUpdate }: { v: Vehicle; profile: string; onUpdate: (v: Vehicle) => void }) {
  const cf = v.carfax
  const [busy, setBusy] = useState(false)
  async function pull() {
    if (!v.contract) return
    setBusy(true)
    try { onUpdate(await api.pullCarfax(v.contract, profile)) } catch (e) { alert(String(e)) } finally { setBusy(false) }
  }
  return (
    <div className="space-y-3 text-sm">
      <div className="flex gap-2">
        {v.carfaxUrl && <a className="text-primary hover:underline" href={v.carfaxUrl} target="_blank" rel="noopener">Open Carfax ↗</a>}
        {v.contract && <Button size="sm" variant="secondary" onClick={pull} disabled={busy}>{busy ? "Pulling…" : "⟳ Auto-pull"}</Button>}
      </div>
      {cf ? (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
          <Stat label="accidents" value={String(cf.accidents)} />
          <Stat label="claims" value={fmt(cf.claims)} />
          <Stat label="branding" value={cf.branding} />
          <Stat label="last km" value={cf.lastKm ? cf.lastKm.toLocaleString() : "—"} />
          <Stat label="service" value={cf.service} />
          <Stat label="source" value={cf.source} />
        </div>
      ) : <p className={muted}>No Carfax on file. Auto-pull (local agent) or open the link above.</p>}
    </div>
  )
}

// ── Correct (feedback) ────────────────────────────────────────────────────────
export function CorrectPanel({ v }: { v: Vehicle }) {
  const fb = v.feedback || {}
  const [actual, setActual] = useState(fb.actualSale ?? "")
  const [val, setVal] = useState(fb.correctedValue ?? "")
  const [bid, setBid] = useState(fb.correctedMaxBid ?? "")
  const [vc, setVc] = useState<boolean | null>(fb.verdictCorrect ?? null)
  const [notes, setNotes] = useState(fb.notes ?? "")
  const [saved, setSaved] = useState<string | null>(fb.updatedAt ?? null)
  const [busy, setBusy] = useState(false)

  async function save() {
    if (!v.contract) return
    setBusy(true)
    try {
      const f = await api.saveFeedback({
        contract: v.contract, year: v.year, make: v.make, model: v.model,
        engineVerdict: v.verdict, engineValue: v.value, engineMaxBid: v.maxBid, engineMode: v.engineMode,
        actualSale: actual === "" ? null : actual, correctedValue: val === "" ? null : val,
        correctedMaxBid: bid === "" ? null : bid, verdictCorrect: vc, notes,
      })
      setSaved(f?.updatedAt || "just now")
    } finally { setBusy(false) }
  }
  return (
    <div className="space-y-4">
      <p className={muted}>Record what actually happened + the right call. Feeds the AI as calibration on similar vehicles{v.engineMode === "rules" ? " — run a deep appraisal first for a deep correction." : "."}</p>
      <div className="grid grid-cols-3 gap-3">
        <div className="grid gap-1.5"><Label className="text-xs">actual sold $</Label><Input type="number" value={actual} onChange={(e) => setActual(e.target.value)} /></div>
        <div className="grid gap-1.5"><Label className="text-xs">true retail $</Label><Input type="number" value={val} onChange={(e) => setVal(e.target.value)} /></div>
        <div className="grid gap-1.5"><Label className="text-xs">correct max bid $</Label><Input type="number" value={bid} onChange={(e) => setBid(e.target.value)} /></div>
      </div>
      <div className="flex items-center gap-2">
        <Label className="text-xs">verdict right?</Label>
        <Button size="sm" variant={vc === true ? "default" : "outline"} onClick={() => setVc(true)}>✓ Right</Button>
        <Button size="sm" variant={vc === false ? "destructive" : "outline"} onClick={() => setVc(false)}>✗ Wrong</Button>
      </div>
      <div className="grid gap-1.5"><Label className="text-xs">what did the engine miss?</Label>
        <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={3} className="rounded-md border bg-background p-2 text-sm" /></div>
      <div className="flex items-center justify-between">
        <span className="text-xs text-muted-foreground">{saved ? "saved · " + saved : "not yet recorded"}</span>
        <Button onClick={save} disabled={busy || !v.contract}>{busy ? "Saving…" : "Save correction"}</Button>
      </div>
    </div>
  )
}

// ── Inputs (editable spec + re-appraise) ──────────────────────────────────────
export function InputsPanel({ v, profile, onUpdate }: { v: Vehicle; profile: string; onUpdate: (v: Vehicle) => void }) {
  const i = v.inputs || {}
  const [f, setF] = useState<Record<string, any>>({ ...i })
  const [busy, setBusy] = useState(false)
  const set = (k: string, val: string) => setF((s) => ({ ...s, [k]: val }))
  async function save(reset = false) {
    if (!v.contract) return
    setBusy(true)
    try { onUpdate(await api.saveOverrides(v.contract, profile, reset ? {} : f)); if (reset) setF({ ...i }) } finally { setBusy(false) }
  }
  if (!v.contract) return <p className={muted}>Editable inputs apply to Regal lots.</p>
  const fields = [["trim", "trim"], ["cab", "cab"], ["bed", "bed"], ["driveline", "driveline"], ["engine", "engine"], ["km", "odometer (km)"],
    ["exterior_grade", "ext grade"], ["interior_grade", "int grade"], ["mechanical_grade", "mech grade"]]
  return (
    <div className="space-y-3">
      <p className={muted}>Fix what the engine read (wrong/missing trim, km, grades, declarations). Persists + re-appraises.</p>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        {fields.map(([k, label]) => (
          <div key={k} className="grid gap-1.5"><Label className="text-xs">{label}{(v.overridden || []).includes(k) ? " ●" : ""}</Label>
            <Input value={f[k] ?? ""} onChange={(e) => set(k, e.target.value)} /></div>
        ))}
      </div>
      <div className="grid gap-1.5"><Label className="text-xs">declarations</Label><Input value={f.declarations ?? ""} onChange={(e) => set("declarations", e.target.value)} /></div>
      <div className="grid gap-1.5"><Label className="text-xs">condition / remarks</Label>
        <textarea value={f.condition_notes ?? ""} onChange={(e) => set("condition_notes", e.target.value)} rows={2} className="rounded-md border bg-background p-2 text-sm" /></div>
      <div className="flex gap-2">
        <Button onClick={() => save(false)} disabled={busy}>{busy ? "Saving…" : "Save & re-appraise"}</Button>
        <Button variant="ghost" onClick={() => save(true)} disabled={busy}>Reset to scraped</Button>
      </div>
    </div>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return <div><div className="text-xs uppercase text-muted-foreground">{label}</div><div className="font-medium">{value}</div></div>
}
