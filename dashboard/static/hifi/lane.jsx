/* ============================================================
   AUCTIONMATIC hi-fi — The Lane (Regal sale screening table)
   Structured the way Regal runs it: one sale at a time (Tuesday Timed
   Auction / Saturday Super Sale), vehicles in lot order.
   ============================================================ */
const { useState: useStateLane } = window.React;

const ACCENT_OF = (v) => "var(--" + (window.VMAP[v.verdict] || window.VMAP.PASS).accent + ")";
const TINT_OF = (v) => "var(--" + (window.VMAP[v.verdict] || window.VMAP.PASS).accent + "-tint)";

const _MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
function fmtSaleDate(iso) {
  if (!iso || iso.indexOf("-") < 0) return iso || "";
  const [y, m, d] = iso.split("-").map(Number);
  return _MONTHS[m - 1] + " " + d;
}

function VerdictPill({ v, small }) {
  const m = window.VMAP[v.verdict] || window.VMAP.PASS;
  return (
    <span className="row" style={{ gap: 7, display: "inline-flex", alignItems: "center",
      background: TINT_OF(v), color: ACCENT_OF(v), padding: small ? "3px 9px" : "4px 11px",
      borderRadius: 100, fontFamily: "Spline Sans Mono, monospace", fontWeight: 600,
      fontSize: small ? 10.5 : 11.5, letterSpacing: ".02em", whiteSpace: "nowrap" }}>
      <span style={{ width: 6, height: 6, borderRadius: 99, background: "currentColor" }} />{m.key}
    </span>
  );
}
window.VerdictPill = VerdictPill;

function UnscoredPill() {
  return (
    <span className="chip" style={{ fontSize: 10, padding: "3px 9px", color: "var(--text-faint)" }}
      title="not yet screened — open to evaluate">○ unscored</span>
  );
}

function ConfMini({ level }) {
  const n = { low: 1, medium: 2, high: 3 }[level] || 0;
  return (
    <span className="row" style={{ gap: 3, alignItems: "flex-end", height: 14 }} title={"confidence · " + level}>
      {[7, 10, 14].map((h, i) => (
        <span key={i} style={{ width: 4, height: h, borderRadius: 1.5,
          background: i < n ? "var(--text)" : "var(--surface-3)" }} />
      ))}
    </span>
  );
}

/* sale selector — horizontal pills, soonest first */
function SaleTabs({ sales, selected, onSelect }) {
  if (!sales || sales.length === 0) return null;
  return (
    <div className="row gap8 wrap" style={{ marginTop: 18 }}>
      {sales.map((s) => {
        const on = s.date === selected;
        return (
          <button key={s.date} onClick={() => onSelect(s.date)} className="row" style={{ cursor: "pointer",
            gap: 8, alignItems: "center", padding: "6px 13px", borderRadius: 100, whiteSpace: "nowrap",
            fontFamily: "Spline Sans Mono, monospace", fontSize: 11.5, fontWeight: 600,
            background: on ? "var(--accent-soft)" : "transparent",
            border: "1px solid " + (on ? "var(--accent)" : "var(--border)"),
            color: on ? "var(--accent-text)" : "var(--text-dim)" }}
            title={s.label}>
            <span style={{ width: 7, height: 7, borderRadius: 99,
              background: s.day === "Sat" ? "var(--fix)" : "var(--accent)" }} />
            {s.day} · {fmtSaleDate(s.date)}
            <span style={{ opacity: .65, fontWeight: 500 }}>· {s.count}</span>
          </button>
        );
      })}
    </div>
  );
}

/* batch enrich a sale: photos + vision (default), optional Carfax / comps */
function PrepControl({ prep, onPrep, onCancel }) {
  const [open, setOpen] = useStateLane(false);
  const [carfax, setCarfax] = useStateLane(false);
  const [comps, setComps] = useStateLane(false);
  const [limit, setLimit] = useStateLane(25);
  const running = prep && prep.status === "running";

  if (running) {
    return (
      <span className="row gap8" style={{ alignItems: "center" }}>
        <span className="spin" style={{ width: 11, height: 11, borderRadius: 99,
          border: "2px solid var(--accent)", borderTopColor: "transparent", display: "inline-block" }} />
        <span className="eyebrow">prepping {prep.done}/{prep.total}{prep.current ? " · #" + prep.current : ""}</span>
        <button className="btn ghost sm" onClick={onCancel} style={{ color: "var(--text-dim)" }}>stop</button>
      </span>
    );
  }
  return (
    <span style={{ position: "relative" }}>
      <button className="btn sm" onClick={() => setOpen((o) => !o)}>⚙ Prep sale ▾</button>
      {open && (
        <div className="card" style={{ position: "absolute", right: 0, top: 38, zIndex: 60, width: 250,
          padding: 14, boxShadow: "var(--shadow-lg)" }}>
          <div className="eyebrow" style={{ marginBottom: 8 }}>Pre-enrich first
            <input type="number" value={limit} min={1} max={200} onChange={(e) => setLimit(+e.target.value || 25)}
              className="num" style={{ width: 46, margin: "0 5px", padding: "2px 5px", fontSize: 12,
                background: "var(--surface-2)", border: "1px solid var(--border)", borderRadius: 5, color: "var(--text)" }} />
            by lot</div>
          <label className="row gap8" style={{ fontSize: 13, padding: "5px 0", cursor: "default" }}>
            <input type="checkbox" checked readOnly style={{ accentColor: "var(--accent)" }} /> Photos + vision</label>
          <label className="row gap8" style={{ fontSize: 13, padding: "5px 0", cursor: "pointer" }}>
            <input type="checkbox" checked={carfax} onChange={(e) => setCarfax(e.target.checked)}
              style={{ accentColor: "var(--accent)" }} /> Carfax <span className="faint" style={{ fontSize: 11 }}>(slow)</span></label>
          <label className="row gap8" style={{ fontSize: 13, padding: "5px 0", cursor: "pointer" }}>
            <input type="checkbox" checked={comps} onChange={(e) => setComps(e.target.checked)}
              style={{ accentColor: "var(--accent)" }} /> Scan comps <span className="faint" style={{ fontSize: 11 }}>($ Apify)</span></label>
          <button className="btn accent sm" style={{ width: "100%", marginTop: 10, justifyContent: "center" }}
            onClick={() => { setOpen(false); onPrep({ limit, carfax, comps }); }}>Start prep</button>
        </div>
      )}
    </span>
  );
}

function Lane({ sale, sales, selected, onSelectSale, onOpen, onScreenAll, screening, mode, prep, onPrep, onPrepCancel }) {
  const [sort, setSort] = useStateLane("lot");
  const [filter, setFilter] = useStateLane(null);

  const vehicles = (sale && sale.vehicles) || [];
  const order = { BID: 0, BID_TO_FIX: 1, PASS: 2 };
  const counts = { BID: 0, BID_TO_FIX: 0, PASS: 0 };
  vehicles.forEach((v) => { if (v.verdict) counts[v.verdict]++; });

  let rows = vehicles.map((v, i) => ({ v, i }));
  if (filter) rows = rows.filter((r) => r.v.verdict === filter);
  if (sort === "lot") rows.sort((a, b) => (a.v.lotNum || 0) - (b.v.lotNum || 0));
  if (sort === "verdict") rows.sort((a, b) => ((order[a.v.verdict] ?? 9) - (order[b.v.verdict] ?? 9)) || (b.v.maxBid || 0) - (a.v.maxBid || 0));
  if (sort === "max bid") rows.sort((a, b) => (b.v.maxBid || 0) - (a.v.maxBid || 0));
  if (sort === "value") rows.sort((a, b) => (b.v.value || 0) - (a.v.value || 0));
  if (sort === "km") rows.sort((a, b) => (a.v.km || 0) - (b.v.km || 0));

  const FILTERS = [["BID", counts.BID], ["BID_TO_FIX", counts.BID_TO_FIX], ["PASS", counts.PASS]];
  const moreToScreen = sale && sale.screened < sale.count;

  return (
    <div className="shell" style={{ paddingTop: 26 }}>
      {/* header */}
      <div className="rise" style={{ marginBottom: 22 }}>
        <div className="row between wrap" style={{ alignItems: "flex-end", gap: 16 }}>
          <div className="col" style={{ gap: 7 }}>
            <span className="eyebrow">Regal Auctions · upcoming sales</span>
            <h1 className="display" style={{ fontSize: 34 }}>The Lane</h1>
          </div>
          <div className="row gap8 wrap" style={{ alignItems: "center" }}>
            <span className="eyebrow" style={{ marginRight: 2 }}>sort</span>
            <div className="seg">
              {["lot", "verdict", "max bid", "value", "km"].map((s) => (
                <button key={s} className={sort === s ? "on" : ""} onClick={() => setSort(s)}>{s}</button>
              ))}
            </div>
          </div>
        </div>

        <SaleTabs sales={sales} selected={selected} onSelect={onSelectSale} />

        {/* current-sale banner */}
        {sale && (
          <div className="row between wrap" style={{ marginTop: 18, gap: 12, alignItems: "center" }}>
            <div className="row gap8" style={{ alignItems: "baseline" }}>
              <span style={{ width: 9, height: 9, borderRadius: 99, alignSelf: "center",
                background: sale.day === "Sat" ? "var(--fix)" : "var(--accent)" }} />
              <h3 style={{ fontSize: 17 }}>{sale.label}</h3>
              <span className="eyebrow">{sale.day} · {fmtSaleDate(sale.date)} · {sale.count} vehicles</span>
            </div>
            <div className="row gap8 wrap" style={{ alignItems: "center" }}>
              <span className="eyebrow">{screening ? "screening…" : `screened ${sale.screened} / ${sale.count}`}</span>
              {moreToScreen && (
                <button className="btn sm" disabled={screening} onClick={onScreenAll}>
                  {screening && <span className="spin" style={{ width: 11, height: 11, borderRadius: 99,
                    border: "2px solid var(--accent)", borderTopColor: "transparent", display: "inline-block" }} />}
                  Screen all
                </button>
              )}
              {onPrep && <PrepControl prep={prep} onPrep={onPrep} onCancel={onPrepCancel} />}
            </div>
          </div>
        )}

        {/* verdict filter chips */}
        <div className="row gap8 wrap" style={{ marginTop: 16 }}>
          <button onClick={() => setFilter(null)} className="chip" style={{ cursor: "pointer",
            border: "1px solid " + (filter === null ? "var(--text)" : "var(--border)"),
            color: filter === null ? "var(--text)" : "var(--text-dim)", fontWeight: 600 }}>
            All · {vehicles.length}
          </button>
          {FILTERS.map(([k, n]) => {
            const fake = { verdict: k };
            const on = filter === k;
            return (
              <button key={k} onClick={() => setFilter(on ? null : k)} className="row" style={{ cursor: "pointer",
                gap: 7, alignItems: "center", padding: "4px 11px", borderRadius: 100, whiteSpace: "nowrap",
                fontFamily: "Spline Sans Mono, monospace", fontSize: 11.5, fontWeight: 600,
                background: on ? TINT_OF(fake) : "transparent",
                border: "1px solid " + (on ? "transparent" : "var(--border)"),
                color: on ? ACCENT_OF(fake) : "var(--text-dim)" }}>
                <span style={{ width: 6, height: 6, borderRadius: 99, background: ACCENT_OF(fake) }} />
                {(window.VMAP[k] || {}).key} · {n}
              </button>
            );
          })}
        </div>
      </div>

      {/* table */}
      <div className="card rise" style={{ overflow: "hidden" }}>
        <table className="tbl" style={{ tableLayout: "fixed" }}>
          <colgroup>
            <col style={{ width: 92 }} /><col /><col style={{ width: 64 }} /><col style={{ width: 116 }} />
            <col style={{ width: 116 }} /><col style={{ width: 94 }} /><col style={{ width: 82 }} />
            <col style={{ width: 50 }} /><col style={{ width: 54 }} />
          </colgroup>
          <thead>
            <tr>
              <th style={{ paddingLeft: 22 }}>Lot</th><th>Vehicle</th><th>km</th><th>Declarations</th>
              <th>Verdict</th><th>Max bid</th><th>Value</th><th>Conf</th><th></th>
            </tr>
          </thead>
          <tbody>
            {rows.map(({ v, i }) => (
              <tr key={i} onClick={() => onOpen(i)} style={{ cursor: "pointer", opacity: (v.scored || v.verdict) ? 1 : .72 }}
                className="lane-row">
                <td style={{ paddingLeft: 22, borderLeft: "3px solid " + (v.verdict ? ACCENT_OF(v) : "var(--border-strong)") }}>
                  <div className="num" style={{ fontSize: 13, fontWeight: 700 }}>{v.lot || "—"}</div>
                  <div className="num faint" style={{ fontSize: 10 }}>#{v.contract}</div>
                </td>
                <td style={{ overflow: "hidden" }}>
                  <div className="row gap8" style={{ alignItems: "center" }}>
                    {v.photo
                      ? <img src={v.photo} alt="" loading="lazy"
                          style={{ width: 48, height: 36, objectFit: "cover", borderRadius: 6, flexShrink: 0, background: "var(--surface-3)" }}
                          onError={(e) => { e.currentTarget.style.visibility = "hidden"; }} />
                      : <div style={{ width: 48, height: 36, borderRadius: 6, flexShrink: 0, background: "var(--surface-3)" }} />}
                    <div style={{ minWidth: 0 }}>
                      <div style={{ fontWeight: 600, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                        {window.vehName(v)} <span className="dim" style={{ fontWeight: 400 }}>{v.trim || ""}</span>
                      </div>
                      <div className="eyebrow" style={{ fontSize: 9.5, marginTop: 2 }}>{v.driveline} · {v.color}</div>
                    </div>
                  </div>
                </td>
                <td className="num dim" style={{ fontSize: 13 }}>{v.km ? (v.km / 1000).toFixed(0) + "k" : "—"}</td>
                <td>
                  <div className="row gap6" style={{ flexWrap: "wrap" }}>
                    {v.decl && v.decl.chips && v.decl.chips.length
                      ? v.decl.chips.map((c, j) => (
                        <span key={j} className={"chip " + (c.sev === "hi" ? "hi" : c.sev === "med" ? "med" : "")}
                          style={{ fontSize: 9.5, padding: "2px 7px" }} title={c.label}>{c.code}</span>))
                      : <span className="faint" style={{ fontSize: 12 }}>—</span>}
                  </div>
                </td>
                <td>{v.verdict ? <VerdictPill v={v} small /> : <UnscoredPill />}</td>
                <td className="num" style={{ fontWeight: 700, fontSize: 14.5 }}>{v.maxBid != null ? window.fmt(v.maxBid) : "—"}</td>
                <td className="num dim" style={{ fontSize: 13 }}>{v.value != null ? window.fmt(v.value) : "—"}</td>
                <td>{v.conf ? <ConfMini level={v.conf} /> : null}</td>
                <td>
                  <div className="row gap6" style={{ justifyContent: "flex-end", paddingRight: 14 }}>
                    {v.conditional && v.conditional.amount > 0 && (
                      <span title={"conditional bid " + window.fmt(v.conditional.amount)} style={{ color: "var(--cond)", fontSize: 14 }}>⚡</span>)}
                    {v.deepReady && (
                      <span style={{ color: "var(--bid)", fontSize: 11 }} title="deep appraisal pre-computed (overnight) — opens instantly">deep ✓</span>)}
                    {!v.deepReady && v.needsDeep && mode !== "deep" && (
                      <span className="chip med" style={{ fontSize: 8.5, padding: "1px 6px" }}
                        title={v.deepReason ? "deep run recommended — " + v.deepReason : "deep run recommended"}>deep?</span>)}
                    <span className="lane-go faint" style={{ fontSize: 15 }}>›</span>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="rise" style={{ marginTop: 18, color: "var(--text-faint)", fontSize: 12 }}>
        <span className="eyebrow">{rows.length} shown</span>
        <span style={{ margin: "0 10px" }}>·</span>
        in lot order — click any row to open its verdict card
      </div>
    </div>
  );
}
window.Lane = Lane;
