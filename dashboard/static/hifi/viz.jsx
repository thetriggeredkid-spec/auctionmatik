/* ============================================================
   AUCTIONMATIC hi-fi — signature viz
   Hero verdict block · confidence gauge · max-bid waterfall ·
   AI-vs-rules number line · comps strip
   ============================================================ */
const { useState: useStateV } = React;

/* verdict → token map */
const VMAP = {
  BID:        { key: "BID",        accent: "bid",  fill: "var(--bid-fill)",  label: "Retail flip" },
  BID_TO_FIX: { key: "BID-TO-FIX", accent: "fix",  fill: "var(--fix-fill)",  label: "Repair project" },
  PASS:       { key: "PASS",       accent: "pass", fill: "var(--pass-fill)", label: "Pass" },
};
window.VMAP = VMAP;
const vv = (v) => VMAP[v.verdict] || VMAP.PASS;

/* confidence gauge — three rising bars */
function ConfGauge({ level, onFill }) {
  const n = { low: 1, medium: 2, high: 3 }[level] || 0;
  const col = onFill ? "var(--on-fill)" : "var(--text)";
  return (
    <span className="row gap8" title={"confidence: " + level}>
      <span className="row" style={{ gap: 3, alignItems: "flex-end", height: 18 }}>
        {[9, 13, 18].map((h, i) => (
          <span key={i} style={{
            width: 5, height: h, borderRadius: 2,
            background: i < n ? col : "transparent",
            border: "1.5px solid " + (i < n ? col : (onFill ? "rgba(255,255,255,.35)" : "var(--border-strong)")),
            opacity: onFill ? (i < n ? .95 : .5) : 1,
          }} />
        ))}
      </span>
      <span className="mono" style={{ fontSize: 11.5, textTransform: "uppercase", letterSpacing: ".08em",
        color: onFill ? "var(--on-fill)" : "var(--text-dim)", opacity: onFill ? .85 : 1 }}>{level}</span>
    </span>
  );
}
window.ConfGauge = ConfGauge;

/* hero verdict block */
function Hero({ v, mode, onReappraise }) {
  const m = vv(v);
  const hasCond = v.conditional && v.conditional.amount > 0;
  return (
    <div className="card rise" style={{
      position: "relative", overflow: "hidden", color: "var(--on-fill)",
      background: m.fill, border: "none", padding: "30px 34px 28px",
      boxShadow: "var(--shadow-lg)",
    }}>
      {/* atmospheric layers */}
      <div style={{ position: "absolute", inset: 0, pointerEvents: "none",
        background: "radial-gradient(120% 130% at 85% -20%, rgba(255,255,255,.16), transparent 55%)" }} />
      <div style={{ position: "absolute", inset: 0, pointerEvents: "none", opacity: .5,
        background: "linear-gradient(180deg, transparent, rgba(0,0,0,.18))" }} />

      <div style={{ position: "relative" }}>
        <div className="row between" style={{ alignItems: "flex-start" }}>
          <div className="col" style={{ gap: 10 }}>
            <span className="row gap8" style={{ alignItems: "center" }}>
              <span style={{ width: 9, height: 9, borderRadius: 99, background: "var(--on-fill)", boxShadow: "0 0 0 4px rgba(255,255,255,.18)" }} />
              <span className="eyebrow" style={{ color: "var(--on-fill)", opacity: .82 }}>{m.label} · {mode}</span>
            </span>
            <h1 className="display" style={{ fontSize: 52, letterSpacing: "-0.03em" }}>{m.key}</h1>
          </div>
          <div className="col" style={{ alignItems: "flex-end", gap: 14 }}>
            <ConfGauge level={v.conf} onFill />
            <button className="btn" onClick={onReappraise} style={{
              background: "rgba(255,255,255,.14)", border: "1px solid rgba(255,255,255,.28)", color: "var(--on-fill)",
            }}>↻ Re-appraise</button>
          </div>
        </div>

        <div className="row" style={{ gap: 40, alignItems: "flex-end", marginTop: 22, flexWrap: "wrap" }}>
          <div className="col">
            <span className="eyebrow" style={{ color: "var(--on-fill)", opacity: .8 }}>Max bid</span>
            <span className="num display" style={{ fontSize: 68, lineHeight: .92, letterSpacing: "-0.04em" }}>{window.fmt(v.maxBid)}</span>
          </div>
          <div className="col" style={{ gap: 12, paddingBottom: 8 }}>
            <Stat onFill label={v.valueBasis || "value"} value={window.fmt(v.value)} />
            <Stat onFill label="margin" value={window.fmt(v.margin)} />
          </div>
          <div className="grow" />
        </div>

        {hasCond && (
          <div style={{ marginTop: 22, padding: "16px 18px", borderRadius: "var(--r)",
            background: "rgba(0,0,0,.20)", border: "1px solid rgba(255,255,255,.18)" }}>
            <div className="row between wrap" style={{ gap: 12 }}>
              <span className="row gap8" style={{ alignItems: "center" }}>
                <span style={{ fontSize: 16 }}>⚡</span>
                <span className="eyebrow" style={{ color: "var(--on-fill)", opacity: .9 }}>Conditional bid</span>
              </span>
              <span className="num display" style={{ fontSize: 30 }}>{window.fmt(v.conditional.amount)}</span>
            </div>
            <div style={{ marginTop: 8, fontSize: 14, opacity: .92 }}>
              <b style={{ letterSpacing: ".04em" }}>IF</b> &nbsp;{v.conditional.condition}
            </div>
          </div>
        )}

        <p style={{ marginTop: 20, marginBottom: 0, fontSize: 15, maxWidth: 660, opacity: .94, lineHeight: 1.5 }}>{v.summary}</p>
      </div>
    </div>
  );
}
window.Hero = Hero;

function Stat({ label, value, onFill, accent }) {
  return (
    <div className="col" style={{ gap: 2 }}>
      <span className="eyebrow" style={{ color: onFill ? "var(--on-fill)" : "var(--text-faint)", opacity: onFill ? .78 : 1 }}>{label}</span>
      <span className="num" style={{ fontSize: 22, fontWeight: 600, color: accent || (onFill ? "var(--on-fill)" : "var(--text)") }}>{value}</span>
    </div>
  );
}
window.Stat = Stat;

/* ---- max-bid derivation waterfall ----
   Margin, auction fee and GST are shown as SEPARATE bars (fee + GST are exact,
   passed from the engine as v.buyerFee / v.gst). Whatever's left between value and
   max bid after margin/fee/GST is the reconditioning & reserve — labelled as such,
   not lumped into "fees". */
function computeWaterfall(v) {
  const anchor = (v.comps && v.comps.anchor) || v.value;
  const fee = v.buyerFee || 0;
  const gst = v.gst || 0;
  const steps = [];
  steps.push({ label: v.repair ? "After-fix retail" : "Market anchor", val: anchor, type: "base" });

  // value (as-is or after-fix) relative to the anchor = condition/claims/history
  const cond = v.value - anchor;
  if (Math.abs(cond) >= 50) {
    steps.push({ label: cond < 0 ? "Claims & condition" : "Upside", delta: cond, type: cond < 0 ? "sub" : "add" });
  }
  let running = v.value;

  if (v.verdict === "PASS") {
    // Costs exceed value → no viable bid. One honest reduction to the (often $0) ceiling.
    if (Math.abs(running - v.maxBid) >= 1) {
      steps.push({ label: "Below viable bid → PASS", delta: -(running - v.maxBid), type: "sub" });
    }
  } else {
    if (v.repair) {
      const rmid = Math.round((v.repair.sourcing.used_diy.low + v.repair.sourcing.used_diy.high) / 2);
      steps.push({ label: "Repair (DIY / used)", delta: -rmid, type: "sub" });
      running -= rmid;
    }
    // Reconditioning & reserve = the remainder once margin + fee + GST are taken out.
    const recon = Math.round(running - v.margin - fee - gst - v.maxBid);
    if (recon >= 1) { steps.push({ label: "Recon & reserve", delta: -recon, type: "sub" }); running -= recon; }
    if (v.margin > 0) { steps.push({ label: "Your margin", delta: -v.margin, type: "sub" }); running -= v.margin; }
    if (fee > 0) { steps.push({ label: "Auction fee", delta: -fee, type: "sub" }); running -= fee; }
    if (gst > 0) { steps.push({ label: "GST (5%)", delta: -gst, type: "sub" }); running -= gst; }
    // any tiny leftover (rounding, or an AI max bid that doesn't perfectly reconcile)
    const resid = Math.round(running - v.maxBid);
    if (Math.abs(resid) >= 5) steps.push({ label: "Other", delta: -resid, type: resid < 0 ? "add" : "sub" });
  }
  steps.push({ label: "Max bid", val: v.maxBid, type: "total" });
  return steps;
}

function Waterfall({ v }) {
  const steps = computeWaterfall(v);
  const m = vv(v);
  // compute running totals + scale
  let run = 0; const nodes = steps.map((s) => {
    if (s.type === "base") { run = s.val; return { ...s, from: 0, to: run }; }
    if (s.type === "total") { return { ...s, from: 0, to: s.val }; }
    const from = run; run += s.delta; return { ...s, from, to: run };
  });
  const max = Math.max(...nodes.map((n) => Math.max(n.from, n.to)), 1);
  const pct = (x) => (x / max) * 100;
  return (
    <div className="col" style={{ gap: 13 }}>
      {nodes.map((n, i) => {
        const isBaseOrTotal = n.type === "base" || n.type === "total";
        const lo = Math.min(n.from, n.to), hi = Math.max(n.from, n.to);
        const left = isBaseOrTotal ? 0 : pct(lo);
        const width = isBaseOrTotal ? pct(n.to) : pct(hi - lo);
        const color = n.type === "base" ? "var(--text-faint)"
          : n.type === "total" ? m.fill
          : n.type === "add" ? "var(--bid)" : "var(--pass)";
        return (
          <div key={i} className="row" style={{ gap: 14, alignItems: "center" }}>
            <span className="dim" style={{ width: 150, fontSize: 12.5, textAlign: "right", flexShrink: 0,
              fontWeight: isBaseOrTotal ? 700 : 400, color: isBaseOrTotal ? "var(--text)" : "var(--text-dim)" }}>{n.label}</span>
            <div style={{ position: "relative", flex: 1, height: isBaseOrTotal ? 30 : 22 }}>
              <div style={{ position: "absolute", left: left + "%", width: "max(2px," + width + "%)", top: 0, bottom: 0,
                background: color, borderRadius: 5, opacity: isBaseOrTotal ? 1 : .85,
                boxShadow: n.type === "total" ? "var(--shadow)" : "none" }} />
            </div>
            <span className="num" style={{ width: 92, textAlign: "right", flexShrink: 0, fontSize: 13.5,
              fontWeight: isBaseOrTotal ? 700 : 500,
              color: n.type === "add" ? "var(--bid)" : n.type === "sub" ? "var(--pass)" : "var(--text)" }}>
              {n.type === "base" ? window.fmt(n.to) : n.type === "total" ? window.fmt(n.to)
                : (n.delta < 0 ? "−" : "+") + window.fmt(Math.abs(n.delta)).replace("$", "$")}
            </span>
          </div>
        );
      })}
    </div>
  );
}
window.Waterfall = Waterfall;

/* ---- AI vs rules-engine number line ---- */
function RulesLine({ v }) {
  const r = v.rules;
  const aiBid = v.maxBid;
  const vals = [r.charles.maxBid, r.mechanic.maxBid, aiBid].filter((x) => x > 0);
  if (vals.length === 0) return <div className="dim" style={{ fontSize: 13 }}>All profiles PASS on blind value — no bid ceiling.</div>;
  const lo = Math.min(...vals), hi = Math.max(...vals);
  const pad = Math.max((hi - lo) * 0.5, 400);
  const min = lo - pad, span = (hi + pad) - min;
  const pos = (x) => ((x - min) / span) * 100;
  const markers = [
    { label: "rules · charles", x: r.charles.maxBid, kind: "rule" },
    { label: "rules · mechanic", x: r.mechanic.maxBid, kind: "rule" },
    { label: "AI", x: aiBid, kind: "ai" },
  ];
  return (
    <div className="col" style={{ gap: 6 }}>
      <div style={{ position: "relative", height: 64, marginTop: 18 }}>
        {/* band between rule values */}
        <div style={{ position: "absolute", top: 30, height: 4, borderRadius: 4,
          left: pos(Math.min(r.charles.maxBid, r.mechanic.maxBid)) + "%",
          width: (pos(Math.max(r.charles.maxBid, r.mechanic.maxBid)) - pos(Math.min(r.charles.maxBid, r.mechanic.maxBid))) + "%",
          background: "var(--accent-soft)", border: "1px solid var(--accent)" }} />
        <div style={{ position: "absolute", top: 32, left: 0, right: 0, height: 1, background: "var(--border)" }} />
        {markers.map((mk, i) => (
          <div key={i} style={{ position: "absolute", left: pos(mk.x) + "%", top: 0, transform: "translateX(-50%)", textAlign: "center" }}>
            <div className="num" style={{ fontSize: 12.5, fontWeight: 600, marginBottom: 4,
              color: mk.kind === "ai" ? "var(--accent-text)" : "var(--text-dim)" }}>{window.fmt(mk.x)}</div>
            <div style={{ width: mk.kind === "ai" ? 14 : 10, height: mk.kind === "ai" ? 14 : 10, borderRadius: 99, margin: "0 auto",
              background: mk.kind === "ai" ? "var(--accent)" : "var(--surface)",
              border: "2px solid " + (mk.kind === "ai" ? "var(--accent)" : "var(--border-strong)") }} />
            <div className="eyebrow" style={{ fontSize: 9, marginTop: 6, whiteSpace: "nowrap" }}>{mk.label}</div>
          </div>
        ))}
      </div>
      <div className="dim" style={{ fontSize: 12.5, marginTop: 4 }}>{v.divergence}</div>
    </div>
  );
}
window.RulesLine = RulesLine;
