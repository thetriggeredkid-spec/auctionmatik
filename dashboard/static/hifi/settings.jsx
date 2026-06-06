/* ============================================================
   AUCTIONMATIC hi-fi — Settings / profile editor
   Edits buyer profiles, margin tiers, Regal fee schedule, GST, and engine
   toggles. Persists via /api/settings; applies to every evaluation.
   ============================================================ */
const { useState: useStateS, useEffect: useEffectS } = React;

const _PROFILE_FIELDS = [
  ["margin_floor", "margin floor $", "int"],
  ["margin_scale", "margin scale", "float"],
  ["repair_buffer", "repair buffer", "float"],
  ["mech_reserve_factor", "mech reserve ×", "float"],
  ["repair_small_factor", "repair small ×", "float"],
  ["repair_large_factor", "repair large ×", "float"],
  ["hold_time", "hold time", "text"],
  ["diy", "diy ability", "text"],
];

function fieldStyle() {
  return { fontFamily: "Spline Sans Mono, monospace", fontSize: 13.5, width: "100%", padding: "7px 9px",
    borderRadius: "var(--r-sm)", border: "1px solid var(--border)", background: "var(--surface-2)", color: "var(--text)" };
}

function num(v, kind) {
  if (v === "" || v == null) return null;
  const n = kind === "int" ? parseInt(v, 10) : parseFloat(v);
  return isNaN(n) ? null : n;
}

function SettingsView() {
  const [s, setS] = useStateS(null);
  const [dirty, setDirty] = useStateS(false);
  const [saving, setSaving] = useStateS(false);
  const [msg, setMsg] = useStateS(null);
  const [err, setErr] = useStateS(null);

  useEffectS(() => { load(); }, []);
  function load() {
    fetch("/api/settings").then((r) => r.json()).then((j) => { setS(j.settings); setDirty(false); }).catch(() => setErr("could not load settings"));
  }
  const mut = (fn) => { setS((cur) => { const c = JSON.parse(JSON.stringify(cur)); fn(c); return c; }); setDirty(true); setMsg(null); };

  if (err) return <div className="shell" style={{ paddingTop: 60 }}><span className="dim">{err}</span></div>;
  if (!s) return <LaneLoading />;

  const order = s.profile_order && s.profile_order.length ? s.profile_order : Object.keys(s.profiles);

  function validate() {
    for (const k of order) {
      const p = s.profiles[k];
      if (num(p.margin_floor, "int") == null || num(p.margin_floor, "int") < 0) return `profile "${k}": margin floor must be ≥ 0`;
    }
    for (const t of s.margin_tiers) if (num(t[2], "int") == null) return "margin tiers: each needs a margin $";
    for (const f of s.fee_schedule) if (num(f[2], "int") == null) return "fee schedule: each needs a fee $";
    if (num(s.gst_rate, "float") == null) return "GST must be a number";
    return null;
  }

  async function save() {
    const v = validate();
    if (v) { setErr(v); return; }
    setErr(null); setSaving(true);
    try {
      const r = await fetch("/api/settings", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(s) });
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || "save failed");
      setS(j.settings); setDirty(false); setMsg("Saved — applies to every evaluation now.");
    } catch (e) { setErr(e.message); } finally { setSaving(false); }
  }
  async function reset() {
    if (!window.confirm("Reset ALL settings to defaults?")) return;
    setSaving(true);
    try { const r = await fetch("/api/settings/reset", { method: "POST" }); const j = await r.json(); setS(j.settings); setDirty(false); setMsg("Reset to defaults."); }
    finally { setSaving(false); }
  }

  function addProfile() {
    const key = (window.prompt("New profile key (e.g. wholesaler):") || "").trim().toLowerCase().replace(/[^a-z0-9_]/g, "");
    if (!key || s.profiles[key]) return;
    mut((c) => {
      c.profiles[key] = { label: key, margin_floor: 1500, margin_scale: 1.0, repair_buffer: 0.20,
        hold_time: "low", diy: "some", mech_reserve_factor: 1.0, repair_small_factor: 0.65, repair_large_factor: 1.0 };
      c.profile_order = [...(c.profile_order || Object.keys(c.profiles)), key];
    });
  }
  function delProfile(key) {
    if (order.length <= 1) { setErr("keep at least one profile"); return; }
    if (!window.confirm(`Delete profile "${key}"?`)) return;
    mut((c) => { delete c.profiles[key]; c.profile_order = (c.profile_order || []).filter((k) => k !== key); });
  }

  const locations = s.locations || [];
  function addLocation() {
    const label = (window.prompt("New location label (e.g. Toronto, ON):") || "").trim();
    if (!label || locations.some((l) => l.label === label)) return;
    mut((c) => { c.locations = [...(c.locations || []), { label, city: "", province: "", business_tax: 0.05, private_tax: 0.0 }]; });
  }
  function delLocation(i) {
    if (locations.length <= 1) { setErr("keep at least one location"); return; }
    mut((c) => { const rm = c.locations[i]; c.locations = c.locations.filter((_, j) => j !== i); if (c.active_location === rm.label) c.active_location = (c.locations[0] || {}).label; });
  }

  const Section = ({ title, children, action }) => (
    <div className="card-2" style={{ padding: "20px 22px" }}>
      <div className="row between" style={{ alignItems: "baseline" }}>
        <div className="section-head" style={{ marginBottom: 0 }}><span className="eyebrow">Settings</span><h3>{title}</h3></div>
        {action}
      </div>
      <div style={{ marginTop: 14 }}>{children}</div>
    </div>
  );

  return (
    <div className="shell" style={{ paddingTop: 26 }}>
      <div className="rise row between wrap" style={{ marginBottom: 22, alignItems: "flex-end", gap: 16 }}>
        <div className="col" style={{ gap: 7 }}>
          <span className="eyebrow">Buyer economics & engine config · applies to every evaluation</span>
          <h1 className="display" style={{ fontSize: 34 }}>Settings</h1>
        </div>
        <div className="row gap8" style={{ alignItems: "center" }}>
          {msg && <span className="eyebrow" style={{ color: "var(--bid)" }}>{msg}</span>}
          {err && <span className="eyebrow" style={{ color: "var(--pass)" }}>{err}</span>}
          <button className="btn ghost sm" disabled={saving} onClick={reset} style={{ color: "var(--text-dim)" }}>Reset to defaults</button>
          <button className="btn accent" disabled={saving || !dirty} onClick={save}>
            {saving && <span className="spin" style={{ width: 12, height: 12, borderRadius: 99, border: "2px solid white", borderTopColor: "transparent", display: "inline-block" }} />}
            {saving ? "Saving…" : dirty ? "Save changes" : "Saved"}
          </button>
        </div>
      </div>

      <div className="stack rise">
        {/* LOCATION — drives off-auction tax + where comps are searched */}
        <Section title="Location" action={<button className="btn sm" onClick={addLocation}>+ Add location</button>}>
          <div className="col" style={{ gap: 5, marginBottom: 14, maxWidth: 280 }}>
            <span className="eyebrow" style={{ fontSize: 9.5 }}>active location</span>
            <select value={s.active_location || ""} onChange={(e) => mut((c) => { c.active_location = e.target.value; })} style={fieldStyle()}>
              {locations.map((l) => <option key={l.label} value={l.label}>{l.label}</option>)}
            </select>
            <span className="faint" style={{ fontSize: 11, marginTop: 2 }}>
              Sets where FB/Kijiji comps are searched and the off-auction purchase tax. Tax rates are fractions (0.05 = 5%); private = 0 where private sales aren't taxed (e.g. Alberta).
            </span>
          </div>
          <div className="stack">
            {locations.map((l, i) => (
              <div key={i} className="inset" style={{ padding: "14px 16px" }}>
                <div className="row between wrap" style={{ alignItems: "center", marginBottom: 10, gap: 10 }}>
                  <input value={l.label ?? ""} placeholder="label (e.g. Toronto, ON)" onChange={(e) => mut((c) => { c.locations[i].label = e.target.value; })} style={{ ...fieldStyle(), width: 240 }} />
                  <button className="btn ghost sm" onClick={() => delLocation(i)} style={{ color: "var(--pass)" }}>Delete</button>
                </div>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))", gap: 12 }}>
                  {[["city", "city (for comps)", "text"], ["province", "province", "text"], ["business_tax", "business/dealer tax", "float"], ["private_tax", "private tax", "float"]].map(([f, label, kind]) => (
                    <div key={f} className="col" style={{ gap: 4 }}>
                      <span className="eyebrow" style={{ fontSize: 9.5 }}>{label}</span>
                      <input value={l[f] ?? ""} onChange={(e) => mut((c) => { c.locations[i][f] = kind === "float" ? e.target.value : e.target.value; })} style={fieldStyle()} />
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </Section>

        {/* PROFILES */}
        <Section title="Buyer profiles" action={<button className="btn sm" onClick={addProfile}>+ Add profile</button>}>
          <div className="stack">
            {order.map((key) => {
              const p = s.profiles[key];
              if (!p) return null;
              return (
                <div key={key} className="inset" style={{ padding: "14px 16px" }}>
                  <div className="row between wrap" style={{ alignItems: "center", marginBottom: 10, gap: 10 }}>
                    <div className="row gap8" style={{ alignItems: "center" }}>
                      <span className="chip">{key}</span>
                      <input value={p.label ?? ""} placeholder="label" onChange={(e) => mut((c) => { c.profiles[key].label = e.target.value; })}
                        style={{ ...fieldStyle(), width: 220 }} />
                    </div>
                    <button className="btn ghost sm" onClick={() => delProfile(key)} style={{ color: "var(--pass)" }}>Delete</button>
                  </div>
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: 12 }}>
                    {_PROFILE_FIELDS.map(([f, label, kind]) => (
                      <div key={f} className="col" style={{ gap: 4 }}>
                        <span className="eyebrow" style={{ fontSize: 9.5 }}>{label}</span>
                        <input value={p[f] ?? ""} onChange={(e) => mut((c) => { c.profiles[key][f] = e.target.value; })} style={fieldStyle()} />
                      </div>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        </Section>

        {/* MARGIN TIERS */}
        <Section title="Margin tiers (by sell price)">
          <table className="tbl">
            <thead><tr><th>From $</th><th>To $</th><th>Margin $</th><th>Label</th></tr></thead>
            <tbody>{s.margin_tiers.map((t, i) => (
              <tr key={i}>
                <td><input value={t[0]} onChange={(e) => mut((c) => { c.margin_tiers[i][0] = num(e.target.value, "int") ?? 0; })} style={fieldStyle()} /></td>
                <td><input value={t[1] >= 100000000 ? "" : t[1]} placeholder="∞" onChange={(e) => mut((c) => { c.margin_tiers[i][1] = e.target.value === "" ? 100000000 : num(e.target.value, "int"); })} style={fieldStyle()} /></td>
                <td><input value={t[2]} onChange={(e) => mut((c) => { c.margin_tiers[i][2] = num(e.target.value, "int") ?? 0; })} style={fieldStyle()} /></td>
                <td><input value={t[3] ?? ""} onChange={(e) => mut((c) => { c.margin_tiers[i][3] = e.target.value; })} style={fieldStyle()} /></td>
              </tr>
            ))}</tbody>
          </table>
        </Section>

        {/* FEES + GST */}
        <Section title="Regal buyer fees & GST">
          <table className="tbl">
            <thead><tr><th>From $</th><th>To $</th><th>Fee $</th></tr></thead>
            <tbody>{s.fee_schedule.map((f, i) => (
              <tr key={i}>
                <td><input value={f[0]} onChange={(e) => mut((c) => { c.fee_schedule[i][0] = num(e.target.value, "int") ?? 0; })} style={fieldStyle()} /></td>
                <td><input value={f[1] >= 100000000 ? "" : f[1]} placeholder="∞" onChange={(e) => mut((c) => { c.fee_schedule[i][1] = e.target.value === "" ? 100000000 : num(e.target.value, "int"); })} style={fieldStyle()} /></td>
                <td><input value={f[2]} onChange={(e) => mut((c) => { c.fee_schedule[i][2] = num(e.target.value, "int") ?? 0; })} style={fieldStyle()} /></td>
              </tr>
            ))}</tbody>
          </table>
          <div className="row gap16" style={{ marginTop: 14, alignItems: "center" }}>
            <span className="eyebrow">GST rate</span>
            <input value={s.gst_rate} onChange={(e) => mut((c) => { c.gst_rate = num(e.target.value, "float"); })}
              style={{ ...fieldStyle(), width: 90 }} />
            <span className="faint" style={{ fontSize: 12 }}>e.g. 0.05 = 5%</span>
          </div>
        </Section>

        {/* ENGINE TOGGLES */}
        <Section title="Engine behavior">
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 14 }}>
            <label className="row gap8" style={{ fontSize: 13.5, cursor: "pointer" }}>
              <input type="checkbox" checked={!!s.engine.deep_autopull_carfax} onChange={(e) => mut((c) => { c.engine.deep_autopull_carfax = e.target.checked; })} style={{ accentColor: "var(--accent)" }} />
              Deep: auto-pull Carfax</label>
            <label className="row gap8" style={{ fontSize: 13.5, cursor: "pointer" }}>
              <input type="checkbox" checked={!!s.engine.deep_autorun_vision} onChange={(e) => mut((c) => { c.engine.deep_autorun_vision = e.target.checked; })} style={{ accentColor: "var(--accent)" }} />
              Deep: auto-run vision</label>
            <label className="row gap8" style={{ fontSize: 13.5, cursor: "pointer" }}>
              <input type="checkbox" checked={!!s.engine.deep_autocollect_comps} onChange={(e) => mut((c) => { c.engine.deep_autocollect_comps = e.target.checked; })} style={{ accentColor: "var(--accent)" }} />
              Deep: auto-collect comps <span className="faint" style={{ fontSize: 11 }}>($ Apify)</span></label>
            <label className="row gap8" style={{ fontSize: 13.5, cursor: "pointer" }}>
              <input type="checkbox" checked={!!s.engine.deep_vision_comps} onChange={(e) => mut((c) => { c.engine.deep_vision_comps = e.target.checked; })} style={{ accentColor: "var(--accent)" }} />
              Deep: vision-read comps <span className="faint" style={{ fontSize: 11 }}>($ Haiku, slower — drops wrecked comps)</span></label>
            <label className="row gap8" style={{ fontSize: 13.5, cursor: "pointer" }}>
              <input type="checkbox" checked={!!s.engine.vin_decode} onChange={(e) => mut((c) => { c.engine.vin_decode = e.target.checked; })} style={{ accentColor: "var(--accent)" }} />
              VIN decode <span className="faint" style={{ fontSize: 11 }}>(NHTSA factory spec, cached — fills blank trim/driveline/engine/cab)</span></label>
            <div className="col" style={{ gap: 4 }}>
              <span className="eyebrow" style={{ fontSize: 9.5 }}>vision photo cap</span>
              <input value={s.engine.vision_photo_cap} onChange={(e) => mut((c) => { c.engine.vision_photo_cap = num(e.target.value, "int") ?? 30; })} style={fieldStyle()} /></div>
            <div className="col" style={{ gap: 4 }}>
              <span className="eyebrow" style={{ fontSize: 9.5 }}>prep default limit</span>
              <input value={s.engine.prep_default_limit} onChange={(e) => mut((c) => { c.engine.prep_default_limit = num(e.target.value, "int") ?? 25; })} style={fieldStyle()} /></div>
          </div>
        </Section>
      </div>
    </div>
  );
}
window.SettingsView = SettingsView;
