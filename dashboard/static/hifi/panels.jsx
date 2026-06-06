/* ============================================================
   AUCTIONMATIC hi-fi — tab panels + comps strip
   ============================================================ */
const { Stat, ConfGauge, Waterfall, RulesLine } = window; // from viz.jsx (loaded first)
const { useState: useStateP } = React;

/* comps price strip — dots on a price axis with anchor marker */
function CompsStrip({ comps }) {
  const prices = comps.used.map((c) => c.kmAdj);
  const all = [...prices, comps.anchor];
  const lo = Math.min(...all), hi = Math.max(...all);
  const pad = Math.max((hi - lo) * 0.25, 300);
  const min = lo - pad, span = (hi + pad) - min;
  const pos = (x) => ((x - min) / span) * 100;
  return (
    <div style={{ position: "relative", height: 78, margin: "26px 0 8px" }}>
      <div style={{ position: "absolute", top: 44, left: 0, right: 0, height: 1, background: "var(--border)" }} />
      {/* anchor */}
      <div style={{ position: "absolute", left: pos(comps.anchor) + "%", top: 8, bottom: 8, transform: "translateX(-50%)" }}>
        <div style={{ width: 2, height: 52, background: "var(--accent)", margin: "0 auto" }} />
        <div className="num" style={{ position: "absolute", top: -6, left: "50%", transform: "translateX(-50%)",
          fontSize: 12, fontWeight: 700, color: "var(--accent-text)", whiteSpace: "nowrap" }}>
          {window.fmt(comps.anchor)}
        </div>
        <div className="eyebrow" style={{ position: "absolute", top: 56, left: "50%", transform: "translateX(-50%)", fontSize: 9, color: "var(--accent-text)" }}>anchor</div>
      </div>
      {/* comp dots */}
      {comps.used.map((c, i) => (
        <div key={i} title={c.y + " " + c.md + " · " + window.fmt(c.kmAdj)}
          style={{ position: "absolute", left: pos(c.kmAdj) + "%", top: 44, transform: "translate(-50%,-50%)" }}>
          <div style={{ width: 10 + c.score * 8, height: 10 + c.score * 8, borderRadius: 99,
            background: "var(--surface)", border: "2px solid var(--text-faint)" }} />
        </div>
      ))}
      <div className="eyebrow" style={{ position: "absolute", left: 0, top: 62, fontSize: 9 }}>{window.fmt(min)}</div>
      <div className="eyebrow" style={{ position: "absolute", right: 0, top: 62, fontSize: 9 }}>{window.fmt(min + span)}</div>
    </div>
  );
}

/* ---------------- panels ---------------- */
function P_Reasoning({ v, mode }) {
  const deep = mode === "deep";
  const hasDeepReasoning = deep && v.reasoning;
  return (
    <div className="stack">
      <p style={{ marginTop: 0, fontSize: 15.5, lineHeight: 1.6, color: "var(--text)" }}>{hasDeepReasoning ? v.reasoning : v.summary}</p>
      {!hasDeepReasoning && v.topFlags && v.topFlags.length > 0 && (
        <div className="card-2" style={{ padding: 16 }}>
          <span className="eyebrow">Top flags</span>
          <div className="col" style={{ gap: 6, marginTop: 8 }}>
            {v.topFlags.map((f, i) => <div key={i} style={{ fontSize: 14 }}>• {f}</div>)}
          </div>
        </div>
      )}

      <div className="card-2" style={{ padding: "22px 24px" }}>
        <div className="section-head"><span className="eyebrow">Derivation</span><h3>How we reach the ceiling</h3></div>
        <Waterfall v={v} />
      </div>

      {v.vmr && (() => {
        const diff = (v.value && v.vmr.retail) ? (v.value - v.vmr.retail) / v.vmr.retail : 0;
        const off = Math.abs(diff) >= 0.2;
        return (
          <div className="card-2" style={{ padding: "22px 24px" }}>
            <div className="section-head"><span className="eyebrow">Sanity check</span><h3>VMR Canada book value</h3></div>
            <div className="row gap32 wrap" style={{ alignItems: "center" }}>
              <Stat label="VMR retail" value={window.fmt(v.vmr.retail)} />
              <Stat label="VMR wholesale" value={window.fmt(v.vmr.ws)} />
              <Stat label="engine value" value={window.fmt(v.value)} accent={off ? "var(--pass)" : undefined} />
              <a className="chip" href={v.vmr.url} target="_blank" rel="noopener"
                title={v.vmr.matched ? "matched trim" : "trim median (no exact match)"}>{v.vmr.trim} ↗</a>
            </div>
            {off && (
              <div style={{ marginTop: 12, padding: "10px 14px", borderRadius: "var(--r)",
                background: "var(--pass-tint)", border: "1px solid var(--pass)", color: "var(--pass)", fontSize: 13 }}>
                ⚑ Engine value is {Math.round(Math.abs(diff) * 100)}% {diff < 0 ? "below" : "above"} VMR retail —
                re-check the comps (trim / cab match, pool depth).
              </div>)}
            {!v.vmr.matched && <div className="dim" style={{ fontSize: 12, marginTop: 8 }}>
              No exact trim match on VMR — showing the trim median; treat as rough.</div>}
          </div>
        );
      })()}

      {deep && v.adjustments && (
        <div className="card-2" style={{ padding: "22px 24px" }}>
          <span className="eyebrow">Key adjustments</span>
          <table className="tbl" style={{ marginTop: 14 }}>
            <thead><tr><th>Factor</th><th>Impact</th><th>Evidence</th></tr></thead>
            <tbody>{v.adjustments.map((a, i) => (
              <tr key={i}>
                <td style={{ fontWeight: 600 }}>{a.factor}</td>
                <td className="num" style={{ fontWeight: 600 }}>{a.impact}</td>
                <td className="dim" style={{ fontSize: 12.5 }}>{a.evidence}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      )}

      {deep && v.rules && (
        <div className="card-2" style={{ padding: "22px 24px" }}>
          <div className="section-head"><span className="eyebrow">Sanity band</span><h3>AI vs rules engine</h3></div>
          <RulesLine v={v} />
          {v.toolsUsed && v.toolsUsed.length > 0 && (
            <div className="row gap8 wrap" style={{ marginTop: 18 }}>
              <span className="eyebrow">Tools fired</span>
              {v.toolsUsed.map((t, i) => <span key={i} className="chip">{t}</span>)}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function P_Comps({ v, onScan, scanState, onFlag }) {
  const c = v.comps;
  if (!c || c.empty) {
    const loading = scanState === "loading";
    const err = typeof scanState === "string" && scanState.indexOf("error") === 0;
    const done = scanState === "done";
    return (
      <div className="card-2" style={{ padding: 26, textAlign: "center" }}>
        <div style={{ fontSize: 14, marginBottom: 8 }}>No Facebook / Kijiji retail comps for this model yet.</div>
        <div className="dim" style={{ fontSize: 13, maxWidth: 460, margin: "0 auto 18px", lineHeight: 1.55 }}>
          The engine anchored from <b>{c ? c.source : "wholesale data"}</b> instead. Scan Facebook
          Marketplace for live listings of this make/model, or see <b>Past Sales</b> for actual Regal
          auction results.
        </div>
        <button className="btn accent" disabled={loading} onClick={onScan} style={{ margin: "0 auto" }}>
          {loading && <span className="spin" style={{ width: 12, height: 12, borderRadius: 99,
            border: "2px solid white", borderTopColor: "transparent", display: "inline-block" }} />}
          {loading ? "Scanning Marketplace… (~1–2 min)" : "⟳ Scan for comps"}
        </button>
        {err && <div style={{ color: "var(--pass)", fontSize: 12.5, marginTop: 12 }}>{scanState.replace(/^error:?\s*/, "Scan failed — ")}</div>}
        {done && <div className="dim" style={{ fontSize: 12.5, marginTop: 12 }}>Scan complete — no comparable Marketplace listings found nearby. Try again later or check Past Sales.</div>}
      </div>
    );
  }
  return (
    <div className="stack">
      <div className="row gap24 wrap" style={{ alignItems: "center" }}>
        <Stat label="reasoned anchor" value={window.fmt(c.anchor)} accent="var(--accent-text)" />
        <div className="col" style={{ gap: 2 }}>
          <span className="eyebrow">confidence</span><ConfGauge level={c.conf} />
        </div>
        <span className="chip">{c.source}</span>
      </div>
      <CompsStrip comps={c} />
      <p className="dim" style={{ fontSize: 12.5, marginTop: -2 }}>
        Open each ad (↗) and check the photos. If a comp is damaged / wrong-trim / mispriced, flag it
        (⚑) — it's dropped from the anchor now and excluded from every future valuation.
      </p>
      <table className="tbl">
        <thead><tr><th>Vehicle</th><th>km</th><th>Asking</th><th>DOM</th><th>Est sale</th><th>km-adj</th><th>Title</th><th>Sim</th><th></th></tr></thead>
        <tbody>{c.used.map((cm, i) => (
          <tr key={i}>
            <td style={{ fontWeight: 600 }}>
              <div className="row gap8" style={{ alignItems: "center" }}>
                {cm.photo && <img src={cm.photo} alt="" loading="lazy"
                  style={{ width: 42, height: 31, objectFit: "cover", borderRadius: 5, flexShrink: 0 }}
                  onError={(e) => { e.currentTarget.style.display = "none"; }} />}
                <div style={{ minWidth: 0 }}>
                  {cm.url
                    ? <a href={cm.url} target="_blank" rel="noopener" style={{ color: "var(--accent-text)", textDecoration: "none" }}>{cm.y} {cm.mk} {cm.md}{cm.trim ? " " + cm.trim : ""} ↗</a>
                    : <span>{cm.y} {cm.mk} {cm.md}{cm.trim ? " " + cm.trim : ""}</span>}
                  <div className="row gap8" style={{ alignItems: "center", marginTop: 2 }}>
                    {cm.realized && <span className="chip" style={{ fontSize: 9, background: "var(--bid-tint)", borderColor: "transparent", color: "var(--bid)" }}>SOLD · full weight</span>}
                    {cm.src && <span className="eyebrow" style={{ fontSize: 9 }}>{cm.src}{cm.trim ? "" : " · trim n/a"}</span>}
                  </div>
                </div>
              </div>
            </td>
            <td className="num dim">{(cm.km / 1000).toFixed(0)}k</td>
            <td className="num">{window.fmt(cm.ask)}</td>
            <td className="num dim">{cm.dom}d · {cm.disc}%</td>
            <td className="num">{window.fmt(cm.est)}</td>
            <td className="num" style={{ fontWeight: 600 }}>{window.fmt(cm.kmAdj)}</td>
            <td><span className="chip" style={{ fontSize: 10 }}>{cm.title}</span></td>
            <td className="num">{cm.score}</td>
            <td style={{ textAlign: "right" }}>
              {cm.id && onFlag && (
                <button className="btn ghost sm" title="flag this comp as bad (exclude it)"
                  onClick={() => { const r = window.prompt("Why is this comp bad? (e.g. cracked bumper / rust / wrong trim)"); if (r !== null) onFlag(cm.id, r); }}
                  style={{ padding: "3px 8px", color: "var(--pass)" }}>⚑</button>)}
            </td>
          </tr>
        ))}</tbody>
      </table>
      {c.excluded && c.excluded.length > 0 && (
        <div className="card-2" style={{ padding: 16 }}>
          <span className="eyebrow">Excluded</span>
          {c.excluded.map((e, i) => (
            <div key={i} className="dim" style={{ fontSize: 13, marginTop: 6 }}>
              <span style={{ textDecoration: "line-through" }}>{e.y} {e.mk} {e.md} · {window.fmt(e.ask)}</span> — {e.reason}
              {e.url && <a href={e.url} target="_blank" rel="noopener" style={{ color: "var(--accent-text)", textDecoration: "none", marginLeft: 6 }}>↗</a>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function Grade({ label, n }) {
  return (
    <div className="col" style={{ gap: 6 }}>
      <span className="eyebrow">{label}</span>
      <span className="row" style={{ gap: 3 }}>
        {[1,2,3,4,5].map((i) => (
          <span key={i} style={{ width: 16, height: 6, borderRadius: 2,
            background: i <= n ? "var(--accent)" : "var(--surface-3)" }} />
        ))}
      </span>
    </div>
  );
}

function P_Vision({ v, onRun, runState }) {
  const vis = v.vision;
  if (!vis) {
    const loading = runState === "loading";
    const err = typeof runState === "string" && runState.indexOf("error") === 0;
    return (
      <div className="card-2" style={{ padding: 26, textAlign: "center" }}>
        <div style={{ fontSize: 14, marginBottom: 8 }}>No photo analysis yet.</div>
        <div className="dim" style={{ fontSize: 13, maxWidth: 440, margin: "0 auto 16px", lineHeight: 1.55 }}>
          Pull the listing's photos from Regal and read them with the vision model (grades, damage,
          rust, hail, mods). <b>Deep</b> mode runs this automatically.
        </div>
        <button className="btn accent" disabled={loading} onClick={() => onRun && onRun()}>
          {loading && <span className="spin" style={{ width: 12, height: 12, borderRadius: 99,
            border: "2px solid white", borderTopColor: "transparent", display: "inline-block" }} />}
          {loading ? "Analyzing photos… (~20s)" : "⟳ Analyze photos"}
        </button>
        {err && <div style={{ color: "var(--pass)", fontSize: 12.5, marginTop: 12 }}>{runState.replace(/^error:?\s*/, "Failed — ")}</div>}
      </div>
    );
  }
  return (
    <div className="stack">
      <div className="row gap16 wrap" style={{ alignItems: "flex-end" }}>
        {(v.photos && v.photos[0])
          ? <img src={v.photos[0]} alt="vehicle" style={{ width: 240, height: 165, objectFit: "cover", borderRadius: "var(--r)", border: "1px solid var(--border)" }} />
          : <div className="media" style={{ width: 240, height: 165 }}><span>main walk-around</span></div>}
        <div className="col gap8" style={{ flex: 1, minWidth: 200 }}>
          <div className="row gap32 wrap">
            <Grade label="exterior" n={vis.extGrade} />
            <Grade label="interior" n={vis.intGrade} />
          </div>
          <div className="row gap16 wrap" style={{ marginTop: 6 }}>
            <span className="chip">rust · {vis.rust}</span>
            <span className="chip">hail · {vis.hail}</span>
            <span className={"chip " + (vis.flood ? "hi" : "")}>{vis.flood ? "⚠ flood / frame" : "frame · clear"}</span>
            {(vis.dashLights || []).map((l, i) => (
              <span key={i} className="chip hi" title="illuminated dashboard warning light">⚠ {l}</span>
            ))}
          </div>
          <span className="eyebrow" style={{ fontSize: 11.5, marginTop: 4 }}>{vis.analyzed}/{vis.total} photos · {vis.model} · {vis.conf} conf</span>
        </div>
      </div>
      <div className="row gap6 wrap">{(v.photos && v.photos.length > 1)
        ? v.photos.slice(1, 9).map((p, i) => <img key={i} src={p} alt="" loading="lazy" style={{ width: 84, height: 60, objectFit: "cover", borderRadius: "var(--r)", border: "1px solid var(--border)" }} />)
        : [1, 2, 3, 4, 5, 6].map((i) => <div key={i} className="media" style={{ width: 84, height: 60 }}><span>#{i}</span></div>)}</div>
      <div className="row gap24 wrap" style={{ alignItems: "flex-start" }}>
        <div className="card-2" style={{ padding: 18, flex: 1, minWidth: 240 }}>
          <span className="eyebrow">Damage</span>
          <div className="col" style={{ gap: 8, marginTop: 10 }}>
            {vis.damage.map((d, i) => (
              <div key={i} className="row between"><span style={{ fontSize: 13.5 }}>{d.panel} · {d.type}</span>
                <span className={"chip sev-" + d.sev}>{d.sev}</span></div>
            ))}
          </div>
        </div>
        <div className="card-2" style={{ padding: 18, flex: 1, minWidth: 240 }}>
          <span className="eyebrow">Aftermarket / repair</span>
          <div className="col" style={{ gap: 8, marginTop: 10 }}>
            {vis.mods.length ? vis.mods.map((mo, i) => (
              <div key={i} style={{ fontSize: 13.5 }}>{mo.type} <span className="dim">· {mo.quality}</span></div>
            )) : <span className="dim" style={{ fontSize: 13 }}>None detected</span>}
            {vis.repairComponents && vis.repairComponents.map((r, i) => (
              <div key={i} style={{ fontSize: 13.5, color: "var(--pass)" }}>↳ {r}</div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function P_Repair({ v }) {
  const rp = v.repair;
  return (
    <div className="stack">
      <table className="tbl">
        <thead><tr><th>Component</th><th>Action</th><th>Severity</th><th>Cost range</th><th></th></tr></thead>
        <tbody>{rp.lineItems.map((li, i) => (
          <tr key={i}>
            <td style={{ fontWeight: 600 }}>{li.comp}</td>
            <td className="dim">{li.action}</td>
            <td><span className={"chip sev-" + (li.sev === "severe" ? "severe" : li.sev === "moderate" ? "moderate" : "")}>{li.sev}</span></td>
            <td className="num">{window.fmt(li.low)} – {window.fmt(li.high)}</td>
            <td>{li.contingent && <span className="chip med">contingent</span>}</td>
          </tr>
        ))}</tbody>
      </table>
      <div className="row gap16 wrap">
        {[["OEM / shop", "oem_shop"], ["Middle", "middle"], ["Used / DIY", "used_diy"]].map(([lab, key]) => {
          const best = key === "used_diy";
          return (
            <div key={key} className="card-2" style={{ flex: 1, minWidth: 150, padding: 18,
              borderColor: best ? "var(--bid)" : "var(--border)", background: best ? "var(--bid-tint)" : "var(--surface-2)" }}>
              <div className="row between"><span className="eyebrow">{lab}</span>{best && <span className="chip" style={{ background: "var(--bid)", color: "white", fontSize: 9 }}>strategy</span>}</div>
              <div className="num display" style={{ fontSize: 24, marginTop: 8 }}>{window.fmt(rp.sourcing[key].mid)}</div>
              <div className="num dim" style={{ fontSize: 12 }}>{window.fmt(rp.sourcing[key].low)} – {window.fmt(rp.sourcing[key].high)}</div>
            </div>
          );
        })}
      </div>
      <div className="row gap24 wrap card-2" style={{ padding: 16 }}>
        <Stat label="confirmed" value={window.fmt(rp.confirmed.low) + " – " + window.fmt(rp.confirmed.high)} />
        <Stat label="contingent" value={window.fmt(rp.contingent.low) + " – " + window.fmt(rp.contingent.high)} />
        <Stat label="buffer" value={(rp.buffer * 100).toFixed(0) + "%"} />
      </div>
    </div>
  );
}

const DEC_MAP = { REQUIRED: "med", DO: "", SKIP: "", RESERVE: "med" };
function P_Recon({ v }) {
  let total = 0;
  return (
    <div className="stack">
      <table className="tbl">
        <thead><tr><th>Action</th><th>Decision</th><th>Cost</th><th>Running</th><th>Why</th></tr></thead>
        <tbody>{v.recon.map((r, i) => { total += r.cost || 0; return (
          <tr key={i}>
            <td style={{ fontWeight: 600 }}>{r.action}</td>
            <td><span className={"chip " + DEC_MAP[r.decision]}>{r.decision}</span></td>
            <td className="num">{r.cost ? window.fmt(r.cost) : "—"}</td>
            <td className="num dim">{window.fmt(total)}</td>
            <td className="dim" style={{ fontSize: 12.5 }}>{r.why}</td>
          </tr>
        ); })}</tbody>
      </table>
      <div className="card-2" style={{ padding: "20px 24px" }}>
        <div className="section-head"><span className="eyebrow">Sale plan</span><h3>{v.sale.channel}</h3></div>
        <div className="row gap32 wrap">
          <Stat label="list price" value={window.fmt(v.sale.list)} />
          <Stat label="floor price" value={window.fmt(v.sale.floor)} />
          <Stat label="days to sell" value={v.sale.days} />
        </div>
      </div>
    </div>
  );
}

function P_Declarations({ v }) {
  const d = v.decl;
  return (
    <div className="stack">
      {d.chips && d.chips.length > 0 && (
        <div className="row gap8 wrap">{d.chips.map((c, i) => <span key={i} className={"chip " + (c.sev === "hi" ? "hi" : c.sev === "med" ? "med" : "")}>{c.code} · {c.label}</span>)}</div>
      )}
      {d.codes && d.codes.map((c, i) => (
        <div key={i} className="card-2" style={{ padding: 16 }}>
          <span className="num" style={{ fontWeight: 700 }}>{c.code}</span> <span className="dim">— {c.label}</span>
          <div style={{ fontSize: 13.5, marginTop: 4 }}>{c.meaning}</div>
        </div>
      ))}
      {d.flags && d.flags.map((f, i) => (
        <div key={i} style={{ padding: "13px 16px", borderRadius: "var(--r)", display: "flex", gap: 10,
          background: f.sev === "high" ? "var(--pass-tint)" : "var(--fix-tint)",
          border: "1px solid " + (f.sev === "high" ? "var(--pass)" : "var(--fix)") }}>
          <span style={{ color: f.sev === "high" ? "var(--pass)" : "var(--fix)" }}>⚑</span>
          <span style={{ fontSize: 13.5 }}>{f.msg}</span>
        </div>
      ))}
    </div>
  );
}

function P_Verify({ v }) {
  return (
    <div className="card-2" style={{ padding: "8px 8px" }}>
      {v.verify.map((c, i) => (
        <label key={i} className="row gap16" style={{ padding: "13px 16px", cursor: "pointer",
          borderTop: i ? "1px solid var(--hairline)" : "none" }}>
          <input type="checkbox" style={{ width: 18, height: 18, accentColor: "var(--accent)", flexShrink: 0 }} />
          <span style={{ fontSize: 14.5 }}>{c}</span>
        </label>
      ))}
    </div>
  );
}

function P_Carfax({ v, onSave, onPull, pullState }) {
  const cf = v.carfax || {};
  const pulling = pullState === "loading";
  const pullErr = typeof pullState === "string" && pullState.indexOf("error") === 0;
  const [acc, setAcc] = useStateP(cf.accidents ?? "");
  const [claims, setClaims] = useStateP(cf.claims ?? "");
  const [km, setKm] = useStateP(cf.lastKm ?? "");
  const [brand, setBrand] = useStateP(cf.branding && cf.branding !== "None" ? cf.branding : "");
  const [svc, setSvc] = useStateP(cf.service && cf.service !== "—" ? cf.service : "");
  const [saving, setSaving] = useStateP(false);
  const [saved, setSaved] = useStateP(!!v.carfax);

  async function save() {
    setSaving(true);
    try {
      await onSave({ accidents: acc, totalClaims: claims, lastKm: km, branding: brand, service: svc });
      setSaved(true);
    } finally { setSaving(false); }
  }
  const fs = { fontFamily: "Spline Sans Mono, monospace", fontSize: 14, width: "100%", padding: "9px 11px",
    borderRadius: "var(--r-sm)", border: "1px solid var(--border)", background: "var(--surface-2)", color: "var(--text)" };
  const Field = ({ label, value, set, money }) => (
    <div className="col" style={{ gap: 5 }}>
      <span className="eyebrow">{label}</span>
      <div style={{ position: "relative" }}>
        {money && <span className="num dim" style={{ position: "absolute", left: 11, top: 9, fontSize: 14 }}>$</span>}
        <input value={value} placeholder="—" onChange={(e) => set(e.target.value)}
          style={{ ...fs, paddingLeft: money ? 22 : 11 }} />
      </div>
    </div>
  );

  return (
    <div className="stack">
      <div className="card-2" style={{ padding: "16px 18px" }}>
        <div className="row between wrap" style={{ alignItems: "center", gap: 12 }}>
          <div className="col" style={{ gap: 3 }}>
            <span className="eyebrow">Carfax Canada {cf.source ? "· " + cf.source : ""}</span>
            <span className="dim" style={{ fontSize: 13 }}>
              {v.carfax ? "Recorded — the engine prices the history in." : "Auto-pull it, or open the report and key in the facts below."}
            </span>
          </div>
          <div className="row gap8 wrap">
            {v.carfaxUrl && <a className="btn ghost" href={v.carfaxUrl} target="_blank" rel="noopener">View report ↗</a>}
            <button className="btn accent" disabled={pulling} onClick={() => onPull && onPull()}
              title="Render the Carfax in a real browser and read it (runs on your machine)">
              {pulling && <span className="spin" style={{ width: 12, height: 12, borderRadius: 99,
                border: "2px solid white", borderTopColor: "transparent", display: "inline-block" }} />}
              {pulling ? "Pulling… (opens a browser)" : "⟳ Auto-pull Carfax"}
            </button>
          </div>
        </div>
        {pullErr && <div style={{ color: "var(--pass)", fontSize: 12.5, marginTop: 10 }}>
          {pullState.replace(/^error:?\s*/, "Auto-pull failed — ")} · enter it manually below.</div>}
        {cf.notes && <div className="dim" style={{ fontSize: 12.5, marginTop: 10 }}>{cf.notes}</div>}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 16 }}>
        <Field label="accidents reported" value={acc} set={setAcc} />
        <Field label="total claims" value={claims} set={setClaims} money />
        <Field label="last reported km" value={km} set={setKm} />
        <Field label="title branding" value={brand} set={setBrand} />
      </div>
      <div className="col" style={{ gap: 5 }}>
        <span className="eyebrow">service history (summary)</span>
        <textarea value={svc} onChange={(e) => setSvc(e.target.value)} rows={2}
          placeholder="e.g. 7 records, dealer-maintained / sparse / none" style={{ ...fs, resize: "vertical", lineHeight: 1.5 }} />
      </div>
      <div className="row between" style={{ alignItems: "center" }}>
        <span className="eyebrow">{saved ? "saved · engine re-priced" : "not entered yet"}</span>
        <button className="btn accent" disabled={saving} onClick={save}>
          {saving && <span className="spin" style={{ width: 12, height: 12, borderRadius: 99,
            border: "2px solid white", borderTopColor: "transparent", display: "inline-block" }} />}
          {saving ? "Saving…" : "Save Carfax & re-evaluate"}
        </button>
      </div>
    </div>
  );
}

/* past sales — actual sold results from regal_sold (the wholesale comp pool) */
function P_PastSales({ v }) {
  const p = v.pastSales;
  return (
    <div className="stack">
      <div className="row gap24 wrap" style={{ alignItems: "center" }}>
        <Stat label="median sold" value={p.median != null ? window.fmt(p.median) : "—"} />
        <div className="col" style={{ gap: 2 }}>
          <span className="eyebrow">confidence</span><ConfGauge level={p.confidence} />
        </div>
        <span className="chip">{p.count} sold comps · {p.cleanCount} clean</span>
        {p.fallback && <span className="chip med">model-only fallback</span>}
      </div>
      <p className="dim" style={{ fontSize: 13, marginTop: -2 }}>
        Actual Regal auction results for similar units (year ±2, same make / model). Click a row to open its market report.
      </p>
      <table className="tbl">
        <thead><tr><th>Vehicle</th><th>km</th><th>Sold for</th><th>Sold</th><th>Declarations</th><th>Tier</th><th></th></tr></thead>
        <tbody>{p.rows.map((c, i) => (
          <tr key={i} onClick={() => c.url && window.open(c.url, "_blank")}
            className={c.url ? "lane-row" : ""} style={{ cursor: c.url ? "pointer" : "default" }}>
            <td style={{ fontWeight: 600 }}>{c.y} {c.mk} {c.md} <span className="dim" style={{ fontWeight: 400 }}>{c.trim}</span></td>
            <td className="num dim">{c.km ? (c.km / 1000).toFixed(0) + "k" : "—"}</td>
            <td className="num" style={{ fontWeight: 600 }}>{window.fmt(c.price)}</td>
            <td className="num dim" style={{ fontSize: 12.5 }}>{c.date}</td>
            <td className="dim" style={{ fontSize: 12 }}>{c.decl || "—"}</td>
            <td><span className={"chip " + (c.tier === "distressed" ? "hi" : "")} style={{ fontSize: 10 }}>{c.tier}</span></td>
            <td className="lane-go faint" style={{ textAlign: "right", paddingRight: 10 }}>{c.url ? "↗" : ""}</td>
          </tr>
        ))}</tbody>
      </table>
    </div>
  );
}

/* correct & record — the training loop: log the actual sale + the right call */
function P_Correct({ v, onSave }) {
  const fb = v.feedback || {};
  const [actual, setActual] = useStateP(fb.actualSale ?? "");
  const [val, setVal] = useStateP(fb.correctedValue ?? "");
  const [bid, setBid] = useStateP(fb.correctedMaxBid ?? "");
  const [vc, setVc] = useStateP(fb.verdictCorrect ?? null);
  const [notes, setNotes] = useStateP(fb.notes ?? "");
  const [saving, setSaving] = useStateP(false);
  const [savedAt, setSavedAt] = useStateP(fb.updatedAt || null);

  async function save() {
    setSaving(true);
    try {
      const f = await onSave({
        year: v.year, make: v.make, model: v.model,
        engineVerdict: v.verdict, engineValue: v.value, engineMaxBid: v.maxBid,
        engineMode: v.engineMode,   // which engine produced this call → splits calibration tracks
        actualSale: actual === "" ? null : actual,
        correctedValue: val === "" ? null : val,
        correctedMaxBid: bid === "" ? null : bid,
        verdictCorrect: vc, notes,
      });
      setSavedAt((f && f.updatedAt) || "just now");
    } finally { setSaving(false); }
  }

  const fieldStyle = {
    fontFamily: "Spline Sans Mono, monospace", fontSize: 14, width: "100%",
    padding: "9px 11px", borderRadius: "var(--r-sm)", border: "1px solid var(--border)",
    background: "var(--surface-2)", color: "var(--text)",
  };
  const Money = ({ label, value, set, hint }) => (
    <div className="col" style={{ gap: 5 }}>
      <span className="eyebrow">{label}</span>
      <div style={{ position: "relative" }}>
        <span className="num dim" style={{ position: "absolute", left: 11, top: 9, fontSize: 14 }}>$</span>
        <input type="number" inputMode="numeric" value={value} placeholder="—"
          onChange={(e) => set(e.target.value)} style={{ ...fieldStyle, paddingLeft: 22 }} />
      </div>
      {hint && <span className="faint" style={{ fontSize: 10.5 }}>{hint}</span>}
    </div>
  );

  return (
    <div className="stack">
      <div className="card-2" style={{ padding: "16px 18px" }}>
        <span className="eyebrow">Engine's call (for reference){v.engineMode ? " · " + (v.engineMode === "rules" ? "deterministic" : v.engineMode) : ""}</span>
        {v.engineMode === "rules" && (
          <div className="faint" style={{ fontSize: 11, marginTop: 4, lineHeight: 1.5 }}>
            This is the deterministic/triage call. For calibration that matters, run a <b>deep</b>
            appraisal first, then record your correction against it.
          </div>
        )}
        <div className="row gap24 wrap" style={{ marginTop: 8 }}>
          <Stat label="verdict" value={v.verdict || "—"} />
          <Stat label={v.valueBasis || "value"} value={window.fmt(v.value)} />
          <Stat label="max bid" value={window.fmt(v.maxBid)} />
        </div>
      </div>

      <p className="dim" style={{ fontSize: 13, margin: "2px 0", lineHeight: 1.55 }}>
        Record what actually happened and the correct call. The engine learns from this — your
        corrections are fed to the AI as calibration on the next appraisal of similar vehicles.
      </p>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 16 }}>
        <Money label="actual sold price" value={actual} set={setActual} hint="what it hammered for" />
        <Money label="true retail value" value={val} set={setVal} hint="your corrected value" />
        <Money label="correct max bid" value={bid} set={setBid} hint="what you'd have bid" />
      </div>

      <div className="col" style={{ gap: 6 }}>
        <span className="eyebrow">Was the engine's verdict right?</span>
        <div className="row gap8">
          <button className="btn" onClick={() => setVc(true)} style={vc === true
            ? { background: "var(--bid-tint)", borderColor: "var(--bid)", color: "var(--bid)" } : {}}>✓ Right</button>
          <button className="btn" onClick={() => setVc(false)} style={vc === false
            ? { background: "var(--pass-tint)", borderColor: "var(--pass)", color: "var(--pass)" } : {}}>✗ Wrong</button>
        </div>
      </div>

      <div className="col" style={{ gap: 6 }}>
        <span className="eyebrow">What did the engine miss? (the lesson)</span>
        <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={3}
          placeholder="e.g. anchored to a duct-taped, rusty comp — that ad was cheap because it was damaged, not because the market is soft"
          style={{ ...fieldStyle, resize: "vertical", lineHeight: 1.5 }} />
      </div>

      <div className="row between" style={{ alignItems: "center" }}>
        <span className="eyebrow">{savedAt ? "saved · " + savedAt : "not yet recorded"}</span>
        <button className="btn accent" disabled={saving} onClick={save}>
          {saving && <span className="spin" style={{ width: 12, height: 12, borderRadius: 99,
            border: "2px solid white", borderTopColor: "transparent", display: "inline-block" }} />}
          {saving ? "Saving…" : "Save correction"}
        </button>
      </div>
    </div>
  );
}

/* editable inputs — correct what the engine reads, then re-appraise. Persists. */
function P_Inputs({ v, onSave }) {
  const i = v.inputs || {};
  const ov = new Set(v.overridden || []);
  const [f, setF] = useStateP({ ...i });
  const [saving, setSaving] = useStateP(false);
  const [savedAt, setSavedAt] = useStateP(null);
  const set = (k, val) => setF((s) => ({ ...s, [k]: val }));

  async function save(reset) {
    setSaving(true);
    try { await onSave(reset ? {} : f); setSavedAt(reset ? "reset" : "saved"); if (reset) setF({ ...i }); }
    finally { setSaving(false); }
  }
  const fs = { fontFamily: "Spline Sans Mono, monospace", fontSize: 14, width: "100%", padding: "8px 10px",
    borderRadius: "var(--r-sm)", border: "1px solid var(--border)", background: "var(--surface-2)", color: "var(--text)" };
  const dot = (k) => ov.has(k) ? <span style={{ color: "var(--accent-text)" }} title="overridden"> ●</span> : null;
  const Txt = ({ k, label }) => (
    <div className="col" style={{ gap: 5 }}>
      <span className="eyebrow">{label}{dot(k)}</span>
      <input value={f[k] ?? ""} placeholder="—" onChange={(e) => set(k, e.target.value)} style={fs} />
    </div>
  );
  const Grade = ({ k, label }) => (
    <div className="col" style={{ gap: 5 }}>
      <span className="eyebrow">{label}{dot(k)}</span>
      <select value={f[k] ?? ""} onChange={(e) => set(k, e.target.value)} style={fs}>
        <option value="">—</option>
        {[1, 2, 3, 4, 5].map((n) => <option key={n} value={n}>{n} {["", "· poor", "· below avg", "· average", "· above avg", "· exceptional"][n]}</option>)}
      </select>
    </div>
  );

  return (
    <div className="stack">
      <p className="dim" style={{ fontSize: 13, margin: "2px 0", lineHeight: 1.55 }}>
        Fix what the engine read from the listing (a wrong/missing trim, km, condition, declaration).
        Corrections <b>persist</b> and apply to every future evaluation — lane and deep. A <span style={{ color: "var(--accent-text)" }}>●</span> marks an overridden field.
      </p>

      <div className="card-2" style={{ padding: "18px 20px" }}>
        <span className="eyebrow">Spec</span>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 14, marginTop: 10 }}>
          <Txt k="trim" label="trim" /><Txt k="cab" label="cab" /><Txt k="bed" label="bed" />
          <Txt k="driveline" label="driveline" /><Txt k="engine" label="engine" /><Txt k="km" label="odometer (km)" />
        </div>
      </div>

      <div className="card-2" style={{ padding: "18px 20px" }}>
        <span className="eyebrow">Condition grades (1–5)</span>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 14, marginTop: 10 }}>
          <Grade k="exterior_grade" label="exterior" /><Grade k="interior_grade" label="interior" /><Grade k="mechanical_grade" label="mechanical" />
        </div>
      </div>

      <div className="card-2" style={{ padding: "18px 20px" }}>
        <span className="eyebrow">Declarations & remarks</span>
        <div className="col" style={{ gap: 12, marginTop: 10 }}>
          <Txt k="declarations" label="declaration codes (e.g. AA;RS;CH15000)" />
          <div className="col" style={{ gap: 5 }}>
            <span className="eyebrow">condition / auctioneer remarks{dot("condition_notes")}</span>
            <textarea value={f.condition_notes ?? ""} onChange={(e) => set("condition_notes", e.target.value)} rows={2}
              placeholder="e.g. FREEZING DAMAGE; CEL on; rust on rear quarter" style={{ ...fs, resize: "vertical", lineHeight: 1.5 }} />
          </div>
        </div>
      </div>

      <div className="row between" style={{ alignItems: "center" }}>
        <button className="btn ghost sm" disabled={saving} onClick={() => save(true)} style={{ color: "var(--text-dim)" }}>Reset to scraped</button>
        <span className="row gap8" style={{ alignItems: "center" }}>
          {savedAt && <span className="eyebrow">{savedAt === "reset" ? "reset · re-appraised" : "saved · re-appraised"}</span>}
          <button className="btn accent" disabled={saving} onClick={() => save(false)}>
            {saving && <span className="spin" style={{ width: 12, height: 12, borderRadius: 99,
              border: "2px solid white", borderTopColor: "transparent", display: "inline-block" }} />}
            {saving ? "Saving…" : "Save & re-appraise"}
          </button>
        </span>
      </div>
    </div>
  );
}

Object.assign(window, { CompsStrip, P_Reasoning, P_Comps, P_Vision, P_Repair, P_Recon, P_Declarations, P_Verify, P_Carfax, P_PastSales, P_Correct, P_Inputs });
