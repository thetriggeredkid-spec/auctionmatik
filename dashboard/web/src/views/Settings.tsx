import { useEffect, useState } from "react"
import { api } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Card as UICard, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"

export function Settings() {
  const [s, setS] = useState<any>(null)
  const [dirty, setDirty] = useState(false)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)

  const load = () => api.settings().then((j) => { setS(j); setDirty(false) }).catch((e) => setErr(String(e)))
  useEffect(() => { load() }, [])
  const mut = (fn: (c: any) => void) => { setS((cur: any) => { const c = structuredClone(cur); fn(c); return c }); setDirty(true); setMsg(null) }

  async function save() {
    setBusy(true); setErr(null)
    try { setS(await api.saveSettings(s)); setDirty(false); setMsg("Saved — applies to every evaluation now.") }
    catch (e) { setErr(String(e)) } finally { setBusy(false) }
  }
  async function reset() {
    if (!confirm("Reset ALL settings to defaults?")) return
    setBusy(true)
    try { setS(await api.resetSettings()); setDirty(false); setMsg("Reset to defaults.") } finally { setBusy(false) }
  }

  if (err && !s) return <div className="p-8 text-sm text-muted-foreground">{err}</div>
  if (!s) return <div className="w-full px-4 py-6 lg:px-8"><Skeleton className="h-96 w-full" /></div>

  const order: string[] = s.profile_order?.length ? s.profile_order : Object.keys(s.profiles || {})
  const locs: any[] = s.locations || []
  const eng = s.engine || {}

  return (
    <div className="mx-auto max-w-5xl px-4 py-6 lg:px-8">
      <div className="mb-5 flex items-end justify-between">
        <div><div className="text-xs uppercase tracking-wide text-muted-foreground">Applies to every evaluation</div>
          <h1 className="font-heading text-3xl font-semibold">Settings</h1></div>
        <div className="flex items-center gap-2">
          {msg && <span className="text-xs text-emerald-500">{msg}</span>}
          {err && <span className="text-xs text-destructive">{err}</span>}
          <Button variant="ghost" size="sm" onClick={reset} disabled={busy}>Reset to defaults</Button>
          <Button size="sm" onClick={save} disabled={busy || !dirty}>{busy ? "Saving…" : dirty ? "Save changes" : "Saved"}</Button>
        </div>
      </div>

      <div className="space-y-4">
        <UICard>
          <CardHeader className="flex-row items-center justify-between space-y-0">
            <CardTitle className="text-sm">Location</CardTitle>
            <Button size="sm" variant="secondary" onClick={() => {
              const label = prompt("New location label (e.g. Toronto, ON):")?.trim()
              if (label && !locs.some((l) => l.label === label)) mut((c) => { c.locations = [...(c.locations || []), { label, city: "", province: "", business_tax: 0.05, private_tax: 0 }] })
            }}>+ Add location</Button>
          </CardHeader>
          <CardContent>
            <div className="mb-4 grid max-w-xs gap-1.5">
              <Label className="text-xs">active location</Label>
              <select value={s.active_location || ""} onChange={(e) => mut((c) => { c.active_location = e.target.value })}
                className="h-9 rounded-md border bg-background px-2 text-sm">
                {locs.map((l) => <option key={l.label} value={l.label}>{l.label}</option>)}
              </select>
              <span className="text-[11px] text-muted-foreground">Sets where comps are searched + the off-auction tax (rates are fractions; 0.05 = 5%, private = 0 where untaxed).</span>
            </div>
            <div className="space-y-3">
              {locs.map((l, i) => (
                <div key={i} className="rounded-md border p-3">
                  <div className="mb-2 flex items-center justify-between gap-2">
                    <Input className="max-w-[240px]" value={l.label ?? ""} onChange={(e) => mut((c) => { c.locations[i].label = e.target.value })} />
                    <Button size="sm" variant="ghost" className="text-destructive" onClick={() => mut((c) => {
                      const rm = c.locations[i]; c.locations = c.locations.filter((_: any, j: number) => j !== i)
                      if (c.active_location === rm.label) c.active_location = c.locations[0]?.label
                    })}>Delete</Button>
                  </div>
                  <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                    {[["city", "city (comps)"], ["province", "province"], ["business_tax", "business tax"], ["private_tax", "private tax"]].map(([k, label]) => (
                      <div key={k} className="grid gap-1"><Label className="text-[10px] uppercase">{label}</Label>
                        <Input value={l[k] ?? ""} onChange={(e) => mut((c) => { c.locations[i][k] = e.target.value })} /></div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </UICard>

        <UICard>
          <CardHeader><CardTitle className="text-sm">Buyer profiles</CardTitle></CardHeader>
          <CardContent className="space-y-3">
            {order.map((k) => {
              const p = s.profiles?.[k]; if (!p) return null
              return (
                <div key={k} className="rounded-md border p-3">
                  <div className="mb-2 flex items-center gap-2"><span className="rounded bg-muted px-2 py-0.5 text-xs">{k}</span>
                    <Input className="max-w-[220px]" value={p.label ?? ""} onChange={(e) => mut((c) => { c.profiles[k].label = e.target.value })} /></div>
                  <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                    {[["margin_floor", "margin floor $"], ["margin_scale", "margin scale"], ["repair_buffer", "repair buffer"], ["mech_reserve_factor", "mech reserve ×"]].map(([f, label]) => (
                      <div key={f} className="grid gap-1"><Label className="text-[10px] uppercase">{label}</Label>
                        <Input value={p[f] ?? ""} onChange={(e) => mut((c) => { c.profiles[k][f] = e.target.value })} /></div>
                    ))}
                  </div>
                </div>
              )
            })}
          </CardContent>
        </UICard>

        <div className="grid gap-4 sm:grid-cols-2">
          <UICard>
            <CardHeader><CardTitle className="text-sm">Margin tiers (sell price → margin $)</CardTitle></CardHeader>
            <CardContent className="space-y-2">
              {(s.margin_tiers || []).map((t: any[], i: number) => (
                <div key={i} className="flex items-center gap-2 text-sm">
                  <span className="w-28 text-muted-foreground">{t[3]}</span>
                  <Input className="max-w-[120px]" value={t[2]} onChange={(e) => mut((c) => { c.margin_tiers[i][2] = e.target.value })} />
                </div>
              ))}
            </CardContent>
          </UICard>
          <UICard>
            <CardHeader><CardTitle className="text-sm">Regal fee schedule + GST</CardTitle></CardHeader>
            <CardContent className="space-y-2">
              {(s.fee_schedule || []).map((fee: any[], i: number) => (
                <div key={i} className="flex items-center gap-2 text-sm">
                  <span className="w-28 text-muted-foreground tabular-nums">${fee[0] / 1000}k–{fee[1] >= 1e8 ? "∞" : fee[1] / 1000 + "k"}</span>
                  <Input className="max-w-[120px]" value={fee[2]} onChange={(e) => mut((c) => { c.fee_schedule[i][2] = e.target.value })} />
                </div>
              ))}
              <div className="flex items-center gap-2 pt-1 text-sm"><span className="w-28 text-muted-foreground">GST rate</span>
                <Input className="max-w-[120px]" value={s.gst_rate} onChange={(e) => mut((c) => { c.gst_rate = e.target.value })} /></div>
            </CardContent>
          </UICard>
        </div>

        <UICard>
          <CardHeader><CardTitle className="text-sm">Engine behavior</CardTitle></CardHeader>
          <CardContent className="grid gap-3 sm:grid-cols-2">
            {[["deep_autopull_carfax", "Deep: auto-pull Carfax"], ["deep_autorun_vision", "Deep: auto-run vision"],
              ["deep_autocollect_comps", "Deep: auto-collect comps ($)"], ["deep_vision_comps", "Deep: vision-read comps ($)"],
              ["vin_decode", "VIN decode (NHTSA)"]].map(([k, label]) => (
              <label key={k} className="flex cursor-pointer items-center gap-2 text-sm">
                <input type="checkbox" checked={!!eng[k]} onChange={(e) => mut((c) => { c.engine[k] = e.target.checked })} className="accent-primary" />
                {label}
              </label>
            ))}
            <div className="grid max-w-[160px] gap-1"><Label className="text-[10px] uppercase">vision photo cap</Label>
              <Input value={eng.vision_photo_cap ?? ""} onChange={(e) => mut((c) => { c.engine.vision_photo_cap = e.target.value })} /></div>
          </CardContent>
        </UICard>
      </div>
    </div>
  )
}
