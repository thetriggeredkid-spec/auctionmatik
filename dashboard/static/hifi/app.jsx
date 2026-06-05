/* ============================================================
   AUCTIONMATIC hi-fi — app shell (Lane + Detail card)
   Wired to the live engine via /api/lane + /api/evaluate.
   Falls back to bundled sample data (window.VEHICLES) when the
   API is unreachable (e.g. opening index.html as a static file).
   ============================================================ */
const { useState: useStateApp, useEffect: useEffectApp } = React;

// pull cross-file components into scope (viz.jsx + panels.jsx + lane.jsx loaded first)
const { Hero, Lane, SettingsView } = window;
const { P_Reasoning, P_Comps, P_Vision, P_Repair, P_Recon, P_Declarations, P_Verify, P_Carfax, P_PastSales, P_Correct, P_Inputs } = window;

const cap = (s) => s.charAt(0) + s.slice(1).toLowerCase();

/* ---- live engine API client ---- */
const API = {
  async sales() {
    const r = await fetch(`/api/sales`, { headers: { Accept: "application/json" } });
    if (!r.ok) throw new Error("sales " + r.status);
    const j = await r.json();
    return j.sales || [];
  },
  async sale(date, profile, screen) {
    const q = `date=${date}&profile=${profile}` + (screen ? `&screen=${screen}` : "");
    const r = await fetch(`/api/sale?${q}`, { headers: { Accept: "application/json" } });
    if (!r.ok) throw new Error("sale " + r.status);
    const j = await r.json();
    return j.sale;
  },
  async evaluate(contract, mode, profile) {
    const r = await fetch(`/api/evaluate?contract=${encodeURIComponent(contract)}&mode=${mode}&profile=${profile}`,
      { headers: { Accept: "application/json" } });
    const j = await r.json();
    if (!r.ok) throw new Error(j.error || ("evaluate " + r.status));
    return j.vehicle;
  },
  evaluateStream(contract, mode, profile, { onProgress, onResult, onError, force }) {
    const es = new EventSource(`/api/evaluate_stream?contract=${encodeURIComponent(contract)}&mode=${mode}&profile=${profile}${force ? "&force=1" : ""}`);
    let settled = false;
    es.addEventListener("progress", (e) => { if (!settled) { try { onProgress(JSON.parse(e.data)); } catch (_) {} } });
    es.addEventListener("result", (e) => { if (settled) return; settled = true; es.close(); try { onResult(JSON.parse(e.data)); } catch (_) { onError("bad result"); } });
    es.addEventListener("failed", (e) => { if (settled) return; settled = true; es.close(); let m = "unknown"; try { m = JSON.parse(e.data); } catch (_) {} onError(m); });
    es.onerror = () => { if (settled) return; settled = true; es.close(); onError("connection lost"); };
    return es;
  },
  async fetchComps(contract, profile) {
    const r = await fetch(`/api/fetch_comps?contract=${encodeURIComponent(contract)}&profile=${profile}`,
      { headers: { Accept: "application/json" } });
    const j = await r.json();
    if (!r.ok) throw new Error(j.error || ("fetch_comps " + r.status));
    return j.vehicle;
  },
  async flagComp(externalId, contract, reason) {
    const r = await fetch("/api/comp_flag", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ externalId, contract, reason }) });
    if (!r.ok) throw new Error("comp_flag " + r.status);
    return r.json();
  },
  async saveFeedback(data) {
    const r = await fetch("/api/feedback", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data) });
    const j = await r.json();
    if (!r.ok) throw new Error(j.error || ("feedback " + r.status));
    return j.feedback;
  },
  async saveCarfax(data) {
    const r = await fetch("/api/carfax", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data) });
    const j = await r.json();
    if (!r.ok) throw new Error(j.error || ("carfax " + r.status));
    return j.vehicle;
  },
  async pullCarfax(contract, profile) {
    const r = await fetch("/api/carfax_pull", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ contract, profile }) });
    const j = await r.json();
    if (!r.ok) throw new Error(j.error || ("carfax_pull " + r.status));
    return j.vehicle;
  },
  async pullVision(contract, profile) {
    const r = await fetch("/api/vision_pull", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ contract, profile }) });
    const j = await r.json();
    if (!r.ok) throw new Error(j.error || ("vision_pull " + r.status));
    return j.vehicle;
  },
  async saveOverrides(contract, overrides, profile) {
    const r = await fetch("/api/overrides", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ contract, overrides, profile }) });
    const j = await r.json();
    if (!r.ok) throw new Error(j.error || ("overrides " + r.status));
    return j.vehicle;
  },
  async prepSale(date, profile, opts) {
    const r = await fetch("/api/prep_sale", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ date, profile, ...opts }) });
    const j = await r.json();
    if (!r.ok) throw new Error(j.error || ("prep_sale " + r.status));
    return j.job;
  },
  async prepStatus(date) {
    const r = await fetch(`/api/prep_status?date=${date}`, { headers: { Accept: "application/json" } });
    const j = await r.json();
    return j.job || null;
  },
  async prepCancel(date) {
    await fetch("/api/prep_cancel", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ date }) });
  },
};

function ThemeToggle({ theme, setTheme }) {
  return (
    <div className="seg" role="group" aria-label="theme">
      <button className={theme === "dark" ? "on" : ""} onClick={() => setTheme("dark")}>◑ dark</button>
      <button className={theme === "light" ? "on" : ""} onClick={() => setTheme("light")}>◔ light</button>
    </div>
  );
}

function TopBar({ theme, setTheme, mode, setMode, profile, setProfile, view, setView, idx, setIdx,
  count, live, onReload, profileList }) {
  return (
    <div style={{ position: "sticky", top: 0, zIndex: 50,
      background: "color-mix(in oklch, var(--bg), transparent 12%)",
      backdropFilter: "blur(14px)", borderBottom: "1px solid var(--border)" }}>
      <div className="shell" style={{ paddingTop: 0, paddingBottom: 0 }}>
        <div className="row between" style={{ height: 60 }}>
          <div className="row gap16">
            <span className="row gap8" style={{ alignItems: "center" }}>
              <span style={{ width: 22, height: 22, borderRadius: 6, background: "var(--accent)",
                display: "grid", placeItems: "center", color: "white", fontWeight: 800, fontSize: 13 }}>A</span>
              <span style={{ fontWeight: 700, letterSpacing: "-0.02em", fontSize: 16 }}>Auctionmatic</span>
              <span className="chip" title={live ? "wired to the live engine" : "sample data — engine API unreachable"}
                style={{ fontSize: 9, padding: "1px 7px", color: live ? "var(--bid)" : "var(--text-faint)",
                  background: live ? "var(--bid-tint)" : "var(--surface-2)", borderColor: "transparent" }}>
                {live ? "● live" : "○ sample"}
              </span>
            </span>
            <span className="seg">
              <button className={view === "lane" ? "on" : ""} onClick={() => setView("lane")}>▤ lane</button>
              <button className={view === "card" ? "on" : ""} onClick={() => setView("card")}>▦ card</button>
              <button className={view === "calib" ? "on" : ""} onClick={() => setView("calib")}>◎ calibration</button>
              <button className={view === "settings" ? "on" : ""} onClick={() => setView("settings")}>⚙ settings</button>
            </span>
          </div>
          <div className="row gap16">
            <span className="seg">
              {["triage", "deep"].map((mm) => <button key={mm} className={mode === mm ? "on" : ""} onClick={() => setMode(mm)}>{mm}</button>)}
            </span>
            <span className="seg">
              {(profileList && profileList.length ? profileList : ["charles", "mechanic"]).map((p) =>
                <button key={p} className={profile === p ? "on" : ""} onClick={() => setProfile(p)}>{p}</button>)}
            </span>
            {view === "card" && count > 0 && (
              <div className="row gap6">
                <button className="icon-btn" onClick={() => setIdx((idx - 1 + count) % count)}>‹</button>
                <span className="mono dim" style={{ fontSize: 12, minWidth: 64, textAlign: "center" }}>{idx + 1}/{count}</span>
                <button className="icon-btn" onClick={() => setIdx((idx + 1) % count)}>›</button>
              </div>
            )}
            {live && view === "lane" && (
              <button className="icon-btn" title="reload the lane" onClick={onReload}>↻</button>
            )}
            <ThemeToggle theme={theme} setTheme={setTheme} />
          </div>
        </div>
      </div>
    </div>
  );
}

function IdentityHeader({ v, onBack, regalUrl }) {
  const meta = [
    ["VIN", v.vin ? "…" + v.vin.slice(-6) : "—"], ["odometer", (v.km || 0).toLocaleString() + " km"],
    ...(v.cab ? [["cab", v.cab]] : []),
    ...(v.bed ? [["bed", v.bed]] : []),
    ["driveline", v.driveline], ["engine", v.engine], ["transmission", v.trans || "—"],
    ["colour", v.color], ["reserve", window.fmt(v.reserve)], ["seller", v.seller || "—"],
    ["auction", v.auctionDate || "—"],
  ];
  return (
    <div className="rise" style={{ padding: "26px 2px 26px" }}>
      <div className="row between wrap" style={{ gap: 12 }}>
        <button className="btn ghost sm" onClick={onBack} style={{ paddingLeft: 6 }}>‹ The Lane</button>
        <div className="row gap6">
          {v.vmr && v.vmr.url && <a className="btn ghost" href={v.vmr.url} target="_blank" rel="noopener"
            style={{ fontSize: 12.5 }}>VMR ↗</a>}
          {v.carfaxUrl && <a className="btn ghost" href={v.carfaxUrl} target="_blank" rel="noopener"
            style={{ fontSize: 12.5 }}>Carfax ↗</a>}
          <a className="btn ghost" href={regalUrl || "#"} target={regalUrl ? "_blank" : undefined} rel="noopener"
            onClick={(e) => { if (!regalUrl) e.preventDefault(); }} style={{ fontSize: 12.5 }}>View Regal listing ↗</a>
        </div>
      </div>
      <div className="row gap8" style={{ marginTop: 14 }}><span className="eyebrow">Contract #{v.contract} · {v.type || "Vehicle"}</span></div>
      <h1 className="display" style={{ fontSize: 40, marginTop: 8, whiteSpace: "nowrap" }}>
        {v.year} {cap(v.make)} {cap(v.model)}
        {v.trim && <span className="dim" style={{ fontWeight: 500 }}> {v.trim}</span>}
      </h1>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(120px, 1fr))", gap: "14px 24px", marginTop: 24 }}>
        {meta.map(([k, val], i) => (
          <div key={i} className="col" style={{ gap: 3 }}>
            <span className="eyebrow" style={{ fontSize: 9.5 }}>{k}</span>
            <span className="num" style={{ fontSize: 14 }}>{val}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function TabRail({ tabs, active, setActive }) {
  return (
    <div className="row" style={{ gap: 2, borderBottom: "1px solid var(--border)", overflowX: "auto", marginBottom: 26 }}>
      {tabs.map((t) => (
        <button key={t} onClick={() => setActive(t)} style={{
          fontFamily: "Hanken Grotesk, sans-serif", fontSize: 13.5, fontWeight: 600, cursor: "pointer",
          background: "transparent", border: "none", padding: "13px 16px", whiteSpace: "nowrap",
          color: active === t ? "var(--text)" : "var(--text-faint)",
          borderBottom: "2px solid " + (active === t ? "var(--accent)" : "transparent"),
          marginBottom: -1, transition: "color .15s",
        }}>{t}</button>
      ))}
    </div>
  );
}

/* live stage checklist + elapsed timer for the streamed deep appraisal */
function DeepProgress({ progress }) {
  const [now, setNow] = useStateApp(Date.now());
  useEffectApp(() => { const t = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(t); }, []);
  const stages = [];
  (progress.stages || []).forEach((s) => { if (stages[stages.length - 1] !== s) stages.push(s); });
  if (!stages.length) stages.push("Starting…");
  const elapsed = Math.max(0, Math.round((now - progress.startedAt) / 1000));
  const clock = Math.floor(elapsed / 60) + ":" + String(elapsed % 60).padStart(2, "0");
  return (
    <div className="rise card-2" style={{ margin: "0 0 18px", padding: "16px 18px" }}>
      <div className="row between" style={{ alignItems: "center" }}>
        <span className="row gap8" style={{ alignItems: "center" }}>
          <span className="spin" style={{ width: 14, height: 14, borderRadius: 99,
            border: "2px solid var(--accent)", borderTopColor: "transparent", display: "inline-block" }} />
          <span className="eyebrow">Deep AI appraisal</span>
        </span>
        <span className="num dim" style={{ fontSize: 13 }}>{clock}</span>
      </div>
      <div className="col" style={{ gap: 7, marginTop: 12 }}>
        {stages.map((s, i) => {
          const current = i === stages.length - 1;
          return (
            <div key={i} className="row gap8" style={{ alignItems: "center", fontSize: 13.5 }}>
              {current
                ? <span className="spin" style={{ width: 12, height: 12, borderRadius: 99,
                    border: "2px solid var(--accent)", borderTopColor: "transparent", display: "inline-block" }} />
                : <span style={{ color: "var(--bid)", width: 12, textAlign: "center" }}>✓</span>}
              <span style={{ color: current ? "var(--text)" : "var(--text-dim)" }}>{s}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* slim banner while the live engine runs */
function EvalBanner({ state, mode }) {
  if (!state || state === "done") return null;
  const err = state.startsWith && state.startsWith("error");
  return (
    <div className="rise" style={{ margin: "0 0 18px", padding: "12px 16px", borderRadius: "var(--r)",
      display: "flex", alignItems: "center", gap: 12,
      background: err ? "var(--pass-tint)" : "var(--accent-soft)",
      border: "1px solid " + (err ? "var(--pass)" : "var(--accent)") }}>
      {!err && <span className="spin" style={{ width: 14, height: 14, borderRadius: 99,
        border: "2px solid var(--accent)", borderTopColor: "transparent", display: "inline-block" }} />}
      <span style={{ fontSize: 13.5, color: err ? "var(--pass)" : "var(--accent-text)" }}>
        {err ? state.replace(/^error:?\s*/, "Evaluation failed — ") || "Evaluation failed."
          : (mode === "deep" ? "Running the deep AI appraisal (this can take ~60–90s)…" : "Re-pricing…")}
      </span>
    </div>
  );
}

/* vehicle photo gallery — cover + thumbnail strip */
function Gallery({ photos }) {
  const [i, setI] = useStateApp(0);
  if (!photos || !photos.length) return null;
  const cur = photos[Math.min(i, photos.length - 1)];
  return (
    <div className="rise" style={{ margin: "0 0 10px" }}>
      <div style={{ position: "relative", borderRadius: "var(--r-lg)", overflow: "hidden",
        border: "1px solid var(--border)", background: "var(--surface-2)", aspectRatio: "16 / 9", maxHeight: 440 }}>
        <img src={cur} alt="vehicle" style={{ width: "100%", height: "100%", objectFit: "cover", display: "block" }}
          onError={(e) => { e.currentTarget.style.opacity = 0.15; }} />
      </div>
      {photos.length > 1 && (
        <div className="row gap6" style={{ marginTop: 8, overflowX: "auto", paddingBottom: 4 }}>
          {photos.slice(0, 16).map((p, j) => (
            <img key={j} src={p} alt="" loading="lazy" onClick={() => setI(j)}
              style={{ width: 76, height: 56, objectFit: "cover", borderRadius: 8, cursor: "pointer", flexShrink: 0,
                border: "2px solid " + (j === i ? "var(--accent)" : "transparent"), opacity: j === i ? 1 : 0.65 }} />
          ))}
        </div>
      )}
    </div>
  );
}

/* neutral hero for a not-yet-evaluated vehicle (never the red PASS default) */
function PendingHero({ evaluating }) {
  return (
    <div className="card rise" style={{ padding: "30px 34px", border: "1px solid var(--border)" }}>
      <span className="row gap8" style={{ alignItems: "center" }}>
        {evaluating && <span className="spin" style={{ width: 13, height: 13, borderRadius: 99,
          border: "2px solid var(--accent)", borderTopColor: "transparent", display: "inline-block" }} />}
        <span className="eyebrow">{evaluating ? "Evaluating…" : "Not yet evaluated"}</span>
      </span>
      <div className="num display" style={{ fontSize: 52, color: "var(--text-faint)", marginTop: 10 }}>—</div>
    </div>
  );
}

function DetailView({ v, mode, profile, setView, evalState, deepProgress, onReappraise, onScanComps, scanState, onFlagComp, onSaveFeedback, onSaveCarfax, onPullCarfax, pullState, onRunVision, visionState, onSaveOverrides }) {
  const [tab, setTab] = useStateApp("Reasoning");
  const deep = mode === "deep";
  const tabs = ["Reasoning", "Inputs"];
  if (v.comps) tabs.push("Comps");
  if (v.pastSales) tabs.push("Past Sales");
  tabs.push("Vision");
  if (deep && v.repair) tabs.push("Repair");
  if (deep && v.recon) tabs.push("Recon & sale");
  tabs.push("Declarations");
  if (v.verify && v.verify.length) tabs.push("Verify");
  tabs.push("Carfax");
  tabs.push("Correct");
  const activeTab = tabs.includes(tab) ? tab : "Reasoning";

  const panels = {
    "Reasoning": <P_Reasoning v={v} mode={mode} />,
    "Inputs": <P_Inputs v={v} onSave={(o) => onSaveOverrides(v.contract, o)} />,
    "Comps": v.comps ? <P_Comps v={v} onScan={() => onScanComps(v.contract)} scanState={scanState}
      onFlag={(id, reason) => onFlagComp(id, v.contract, reason)} /> : null,
    "Past Sales": v.pastSales ? <P_PastSales v={v} /> : null,
    "Vision": <P_Vision v={v} onRun={() => onRunVision(v.contract)} runState={visionState} />,
    "Repair": v.repair ? <P_Repair v={v} /> : null,
    "Recon & sale": v.recon ? <P_Recon v={v} /> : null,
    "Declarations": <P_Declarations v={v} />,
    "Verify": v.verify ? <P_Verify v={v} /> : null,
    "Carfax": <P_Carfax v={v} onSave={(d) => onSaveCarfax(v.contract, d)}
      onPull={() => onPullCarfax(v.contract)} pullState={pullState} />,
    "Correct": <P_Correct v={v} onSave={(d) => onSaveFeedback(v.contract, d)} />,
  };

  return (
    <div className="shell">
      <IdentityHeader v={v} onBack={() => setView("lane")} regalUrl={v.regalUrl} />
      <Gallery photos={v.photos} />
      {evalState === "loading" && deepProgress
        ? <DeepProgress progress={deepProgress} />
        : <EvalBanner state={evalState} mode={mode} />}
      <div>{v.verdict
        ? <Hero v={v} mode={mode} onReappraise={() => onReappraise(v.contract, mode === "deep" ? "deep" : "lite")} />
        : <PendingHero evaluating={evalState === "loading"} />}</div>

      <div style={{ marginTop: 34 }}>
        <TabRail tabs={tabs} active={activeTab} setActive={setTab} />
        <div key={activeTab} className="rise">{panels[activeTab]}</div>
      </div>

      <div className="row between wrap" style={{ marginTop: 40, paddingTop: 20, borderTop: "1px solid var(--border)", gap: 12 }}>
        {v.meta ? (
          <div className="row gap24 wrap" style={{ fontSize: 11.5 }}>
            <span className="eyebrow">{v.meta.model}</span>
            <span className="eyebrow">effort · {v.meta.effort}</span>
            <span className="eyebrow">◴ {v.meta.elapsed}s</span>
            {v.meta.tokens && <span className="eyebrow">tok {v.meta.tokens.in}/{v.meta.tokens.cache}/{v.meta.tokens.out}</span>}
            {v.meta.cost != null && <span className="eyebrow">≈ ${v.meta.cost.toFixed(2)}</span>}
          </div>
        ) : (
          <span className="eyebrow">{deep ? "Press ↻ Re-appraise to run the deep AI pass" : "Triage result · switch to deep for the full analysis"}</span>
        )}
        <span className="eyebrow">Auctionmatic</span>
      </div>
    </div>
  );
}

function LaneLoading() {
  return (
    <div className="shell" style={{ paddingTop: 80, textAlign: "center" }}>
      <span className="spin" style={{ width: 26, height: 26, borderRadius: 99,
        border: "3px solid var(--accent)", borderTopColor: "transparent", display: "inline-block" }} />
      <div className="eyebrow" style={{ marginTop: 16 }}>Screening the lane…</div>
    </div>
  );
}

/* ◎ Calibration — engine vs reality, from recorded corrections */
function CalibrationView({ onOpen }) {
  const [data, setData] = useStateApp(null);
  const [err, setErr] = useStateApp(null);
  useEffectApp(() => {
    fetch("/api/calibration", { headers: { Accept: "application/json" } })
      .then((r) => r.json()).then(setData).catch(() => setErr("could not load calibration"));
  }, []);

  if (err) return <div className="shell" style={{ paddingTop: 60 }}><span className="dim">{err}</span></div>;
  if (!data) return <LaneLoading />;

  const pct = (x) => x == null ? "—" : (x > 0 ? "+" : "") + x + "%";
  const biasColor = (b) => b == null ? "var(--text-dim)" : Math.abs(b) < 5 ? "var(--bid)" : Math.abs(b) < 12 ? "var(--fix)" : "var(--pass)";
  const dir = (b) => b == null ? "" : b < 0 ? " (engine low)" : " (engine high)";

  const Metric = ({ label, agg, sub }) => (
    <div className="card-2" style={{ padding: "18px 20px", flex: 1, minWidth: 180 }}>
      <span className="eyebrow">{label}</span>
      <div className="num display" style={{ fontSize: 30, marginTop: 6 }}>{agg && agg.n ? agg.mae + "%" : "—"}</div>
      <div className="num" style={{ fontSize: 13, marginTop: 4, color: biasColor(agg && agg.bias) }}>
        {agg && agg.n ? "bias " + pct(agg.bias) + dir(agg.bias) : "no data yet"}
      </div>
      <div className="faint" style={{ fontSize: 11, marginTop: 4 }}>{sub} · n={agg ? agg.n : 0}</div>
    </div>
  );
  const SegTable = ({ title, rows, keyLabel }) => (
    <div className="card-2" style={{ padding: "20px 22px", flex: 1, minWidth: 280 }}>
      <div className="section-head"><span className="eyebrow">Bias by</span><h3>{title}</h3></div>
      {rows && rows.length ? (
        <table className="tbl"><thead><tr><th>{keyLabel}</th><th>n</th><th>MAE</th><th>Bias</th></tr></thead>
          <tbody>{rows.map((s, i) => (
            <tr key={i}>
              <td style={{ fontWeight: 600 }}>{s.key}</td>
              <td className="num dim">{s.n}</td>
              <td className="num">{s.mae == null ? "—" : s.mae + "%"}</td>
              <td className="num" style={{ color: biasColor(s.bias), fontWeight: 600 }}>{pct(s.bias)}</td>
            </tr>))}</tbody>
        </table>
      ) : <div className="dim" style={{ fontSize: 13 }}>No data yet.</div>}
    </div>
  );

  return (
    <div className="shell" style={{ paddingTop: 26 }}>
      <div className="rise row between wrap" style={{ marginBottom: 22, alignItems: "flex-end", gap: 16 }}>
        <div className="col" style={{ gap: 7 }}>
          <span className="eyebrow">Engine vs reality · {data.total} recorded correction{data.total === 1 ? "" : "s"}</span>
          <h1 className="display" style={{ fontSize: 34 }}>Calibration</h1>
        </div>
        <a className="btn" href="/api/calibration.csv">⬇ Export CSV</a>
      </div>

      {data.total === 0 ? (
        <div className="card-2 rise" style={{ padding: 28, textAlign: "center" }}>
          <div style={{ fontSize: 14, marginBottom: 6 }}>No corrections recorded yet.</div>
          <div className="dim" style={{ fontSize: 13, maxWidth: 460, margin: "0 auto", lineHeight: 1.55 }}>
            As you record actual sale prices + corrections in each vehicle's <b>Correct</b> tab, this
            page shows where the engine is systematically off — by make and by price band — to guide
            methodology tuning.
          </div>
        </div>
      ) : (
        <div className="stack">
          <div className="row gap16 wrap rise">
            <Metric label="Retail value error" agg={data.value} sub="engine vs corrected value" />
            <Metric label="Max-bid error" agg={data.bid} sub="engine vs corrected/actual" />
            <div className="card-2" style={{ padding: "18px 20px", flex: 1, minWidth: 180 }}>
              <span className="eyebrow">Verdict accuracy</span>
              <div className="num display" style={{ fontSize: 30, marginTop: 6 }}>
                {data.verdictAccuracy == null ? "—" : data.verdictAccuracy + "%"}</div>
              <div className="faint" style={{ fontSize: 11, marginTop: 8 }}>n={data.verdictN}</div>
            </div>
          </div>
          <div className="faint rise" style={{ fontSize: 12, marginTop: -4 }}>
            MAE = average miss size · Bias = average direction (negative = engine under-values, positive = over-values).
          </div>

          <div className="row gap16 wrap">
            <SegTable title="make" rows={data.byMake} keyLabel="Make" />
            <SegTable title="price band" rows={data.byBand} keyLabel="Band" />
          </div>

          <div className="card rise" style={{ overflow: "hidden", marginTop: 4 }}>
            <table className="tbl">
              <thead><tr><th style={{ paddingLeft: 20 }}>Vehicle</th><th>Engine val</th><th>Truth</th>
                <th>Val err</th><th>Engine bid</th><th>Bid err</th><th>Note</th></tr></thead>
              <tbody>{data.samples.map((s, i) => {
                const truth = s.correctedValue != null ? s.correctedValue : s.actualSale;
                return (
                  <tr key={i} className="lane-row" style={{ cursor: "pointer" }} onClick={() => onOpen && onOpen(s.contract)}>
                    <td style={{ paddingLeft: 20, fontWeight: 600 }}>{s.year} {s.make} {s.model}
                      <div className="num faint" style={{ fontSize: 10 }}>#{s.contract}</div></td>
                    <td className="num">{window.fmt(s.engineValue)}</td>
                    <td className="num">{window.fmt(truth)}</td>
                    <td className="num" style={{ color: biasColor(s.valueErrPct), fontWeight: 600 }}>{pct(s.valueErrPct)}</td>
                    <td className="num dim">{window.fmt(s.engineMaxBid)}</td>
                    <td className="num" style={{ color: biasColor(s.bidErrPct), fontWeight: 600 }}>{pct(s.bidErrPct)}</td>
                    <td className="dim" style={{ fontSize: 12, maxWidth: 280, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{s.notes}</td>
                  </tr>);
              })}</tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

function App() {
  const [theme, setTheme] = useStateApp(() => localStorage.getItem("am-theme") || "dark");
  const [mode, setMode] = useStateApp("triage");
  const [profile, setProfile] = useStateApp("charles");
  const [view, setView] = useStateApp("lane");
  const [idx, setIdx] = useStateApp(0);

  const [sales, setSales] = useStateApp([]);        // sale index
  const [selected, setSelected] = useStateApp(null); // selected sale date
  const [saleMeta, setSaleMeta] = useStateApp(null); // {label,day,date,count,screened}
  const [vehicles, setVehicles] = useStateApp(window.VEHICLES); // current rows (nav source)
  const [live, setLive] = useStateApp(false);
  const [saleLoading, setSaleLoading] = useStateApp(false);
  const [screening, setScreening] = useStateApp(false);
  const [evalState, setEvalState] = useStateApp({}); // "contract|profile" -> loading|done|error
  const [deepResults, setDeepResults] = useStateApp({}); // "contract|profile" -> deep result (per profile, survives sale reloads)
  const [scanState, setScanState] = useStateApp({}); // contract -> comp-scan status
  const [pullState, setPullState] = useStateApp({}); // contract -> carfax-pull status
  const [visionState, setVisionState] = useStateApp({}); // contract -> vision-run status
  const [deepProgress, setDeepProgress] = useStateApp({}); // "contract|profile" -> {stages, startedAt}
  const [prep, setPrep] = useStateApp(null); // active prep job view for the selected sale
  const [profileList, setProfileList] = useStateApp(["charles", "mechanic"]); // from settings

  useEffectApp(() => { document.documentElement.setAttribute("data-theme", theme); localStorage.setItem("am-theme", theme); }, [theme]);
  useEffectApp(() => { window.scrollTo(0, 0); }, [view, idx]);
  // returning from Settings: refresh the profile toggle + drop cached rows (config may have changed)
  const prevView = React.useRef ? React.useRef(view) : { current: view };
  useEffectApp(() => {
    if (prevView.current === "settings" && view !== "settings") { refreshProfiles(); if (live && selected) loadSale(selected, null); }
    prevView.current = view;
  }, [view]);

  // load the sales index + profile list on mount
  useEffectApp(() => {
    API.sales()
      .then((sx) => { if (sx && sx.length) { setSales(sx); setLive(true); setSelected(sx[0].date); } })
      .catch(() => { /* offline → keep bundled sample data */ });
    fetch("/api/settings").then((r) => r.json()).then((j) => {
      const s = j.settings; if (!s) return;
      const ord = (s.profile_order && s.profile_order.length) ? s.profile_order : Object.keys(s.profiles || {});
      if (ord.length) { setProfileList(ord); if (!ord.includes("charles")) setProfile(ord[0]); }
    }).catch(() => {});
  }, []);

  function refreshProfiles() {
    fetch("/api/settings").then((r) => r.json()).then((j) => {
      const s = j.settings; if (!s) return;
      const ord = (s.profile_order && s.profile_order.length) ? s.profile_order : Object.keys(s.profiles || {});
      if (ord.length) { setProfileList(ord); if (!ord.includes(profile)) setProfile(ord[0]); }
    }).catch(() => {});
  }

  function loadSale(date, screen) {
    if (!date) return;
    if (screen) setScreening(true); else setSaleLoading(true);
    API.sale(date, profile, screen)
      .then((s) => { setSaleMeta(s); setVehicles(s.vehicles); })
      .catch(() => {})
      .finally(() => { setScreening(false); setSaleLoading(false); });
  }
  // Load the selected sale only when it changes or the profile changes — NOT on
  // every lane/card toggle (that was discarding already-evaluated rows and forcing
  // a re-evaluation each time you opened a card).
  useEffectApp(() => { if (live && selected) loadSale(selected, null); },
    [selected, profile, live]);

  // Per-(contract,profile) keys so each buyer profile is fully independent — switching
  // profile never clobbers or blocks the other's result, and a deep run for one profile
  // can finish in the background without touching the other.
  const dkey = (contract, p = profile) => contract + "|" + p;

  const baseV = vehicles[idx];
  const curKey = baseV ? dkey(baseV.contract) : null;
  // In deep mode, layer this profile's cached deep result over the base (deterministic) row.
  const v = (baseV && mode === "deep" && deepResults[curKey])
    ? { ...baseV, ...deepResults[curKey] } : baseV;
  const sale = (live && saleMeta)
    ? { ...saleMeta, vehicles }
    : { label: "Sample cases", day: "", date: "", count: vehicles.length, screened: vehicles.length, vehicles };

  // deterministic/quick re-eval (lite/triage) merges into the base row in `vehicles`.
  function _applyEval(contract, full) {
    setVehicles((vs) => vs.map((x) => (x.contract === contract ? { ...x, ...full, scored: true } : x)));
  }

  // forget any cached deep result(s) for a contract (all profiles) — used after an input
  // change (overrides/carfax/vision/comp-flag) so the deep re-runs with the new inputs.
  function _invalidateDeep(contract) {
    setDeepResults((s) => {
      const c = { ...s };
      Object.keys(c).forEach((k) => { if (k.startsWith(contract + "|")) delete c[k]; });
      return c;
    });
  }

  // Streamed deep run for a specific (contract, profile). Writes ONLY that profile's
  // slot, so it's safe to leave running in the background after switching profiles.
  // `force` bypasses the server cache (explicit ↻ Re-appraise only).
  function reappraiseDeep(contract, runProfile, force = false) {
    const k = dkey(contract, runProfile);
    setEvalState((s) => ({ ...s, [k]: "loading" }));
    setDeepProgress((s) => ({ ...s, [k]: { stages: [], startedAt: Date.now() } }));
    const clearProg = () => setDeepProgress((s) => { const c = { ...s }; delete c[k]; return c; });
    API.evaluateStream(contract, "deep", runProfile, {
      force,
      onProgress: (stage) => setDeepProgress((s) => {
        const p = s[k] || { stages: [], startedAt: Date.now() };
        return { ...s, [k]: { ...p, stages: [...p.stages, stage] } };
      }),
      onResult: (full) => { setDeepResults((s) => ({ ...s, [k]: full })); setEvalState((s) => ({ ...s, [k]: "done" })); clearProg(); },
      onError: (err) => { setEvalState((s) => ({ ...s, [k]: "error: " + (err && err.error ? err.error : err) })); clearProg(); },
    });
  }

  async function reappraise(contract, runMode) {
    if (runMode === "deep") { _invalidateDeep(contract); reappraiseDeep(contract, profile, true); return; }  // explicit → fresh run
    const k = dkey(contract);
    setEvalState((s) => ({ ...s, [k]: "loading" }));
    try {
      _applyEval(contract, await API.evaluate(contract, runMode, profile));
      setEvalState((s) => ({ ...s, [k]: "done" }));
    } catch (e) {
      setEvalState((s) => ({ ...s, [k]: "error: " + (e.message || "unknown") }));
    }
  }

  // Opening / switching: triage shows the per-profile deterministic base row. deep loads
  // this profile's result once (streaming hits the server cache fast) and keeps it; a
  // background run for another profile never affects the one on screen.
  useEffectApp(() => {
    if (view !== "card" || !live || !baseV) return;
    const k = curKey;
    if (mode === "deep") {
      if (deepResults[k] || evalState[k] === "loading") return;  // already have it / in flight
      reappraiseDeep(baseV.contract, profile, false);
    } else {
      if (evalState[k] === "loading") return;
      if (baseV.scored) return;        // already has the lane's deterministic verdict
      reappraise(baseV.contract, "lite");
    }
  }, [view, idx, mode, profile, live, deepResults]);

  async function scanComps(contract) {
    setScanState((s) => ({ ...s, [contract]: "loading" }));
    try {
      const full = await API.fetchComps(contract, profile);
      // merge the freshly-scraped comps in without clobbering an existing AI verdict
      setVehicles((vs) => vs.map((x) => (x.contract === contract ? { ...x, comps: full.comps, pastSales: full.pastSales } : x)));
      _invalidateDeep(contract);   // comp pool changed → deep must re-run
      setScanState((s) => ({ ...s, [contract]: "done" }));
    } catch (e) {
      setScanState((s) => ({ ...s, [contract]: "error: " + (e.message || "unknown") }));
    }
  }

  // merge the WHOLE re-evaluated (deterministic) vehicle into the base row, and drop any
  // cached deep result — inputs changed, so the deep re-runs with them.
  function _mergeRepriced(contract, full) {
    if (!full) return;
    setVehicles((vs) => vs.map((x) => (x.contract === contract ? { ...x, ...full, scored: true } : x)));
    _invalidateDeep(contract);
  }

  async function flagComp(externalId, contract, reason) {
    const k = dkey(contract);
    setEvalState((s) => ({ ...s, [k]: "loading" }));   // show the re-pricing banner
    try {
      await API.flagComp(externalId, contract, reason);
      _mergeRepriced(contract, await API.evaluate(contract, "lite", profile));
      setEvalState((s) => ({ ...s, [k]: "done" }));
    } catch (e) {
      setEvalState((s) => ({ ...s, [k]: "error: " + (e.message || "unknown") }));
    }
  }

  async function saveFeedback(contract, data) {
    const fb = await API.saveFeedback({ contract, ...data });
    setVehicles((vs) => vs.map((x) => (x.contract === contract ? { ...x, feedback: fb } : x)));
    return fb;
  }

  async function saveCarfax(contract, data) {
    const full = await API.saveCarfax({ contract, profile, ...data });
    _mergeRepriced(contract, full);   // engine re-priced with the Carfax
    return full;
  }

  async function saveOverrides(contract, overrides) {
    const full = await API.saveOverrides(contract, overrides, profile);
    _mergeRepriced(contract, full);   // engine re-priced with corrected inputs
    return full;
  }

  async function pullCarfax(contract) {
    setPullState((s) => ({ ...s, [contract]: "loading" }));
    try {
      _mergeRepriced(contract, await API.pullCarfax(contract, profile));
      setPullState((s) => ({ ...s, [contract]: "done" }));
    } catch (e) {
      setPullState((s) => ({ ...s, [contract]: "error: " + (e.message || "unknown") }));
    }
  }

  async function runVision(contract) {
    setVisionState((s) => ({ ...s, [contract]: "loading" }));
    try {
      _mergeRepriced(contract, await API.pullVision(contract, profile));
      setVisionState((s) => ({ ...s, [contract]: "done" }));
    } catch (e) {
      setVisionState((s) => ({ ...s, [contract]: "error: " + (e.message || "unknown") }));
    }
  }

  function openCard(i) { setIdx(i); setView("card"); }
  function selectSale(d) { setSelected(d); setIdx(0); setPrep(null); }

  // poll a running prep job; when it finishes, reload the sale so enriched rows refresh
  useEffectApp(() => {
    if (!prep || prep.status !== "running") return;
    const t = setInterval(async () => {
      const j = await API.prepStatus(selected).catch(() => null);
      if (j) {
        setPrep(j);
        if (j.status !== "running") { clearInterval(t); if (view === "lane") loadSale(selected, null); }
      }
    }, 2500);
    return () => clearInterval(t);
  }, [prep && prep.status, selected]);

  async function startPrep(opts) {
    try { setPrep(await API.prepSale(selected, profile, opts)); }
    catch (e) { /* surfaced via banner next poll */ }
  }
  function cancelPrep() { API.prepCancel(selected); }

  // open a card by contract (from the calibration table) — load it if not in the current list
  async function openByContract(contract) {
    const existing = vehicles.findIndex((x) => x.contract === contract);
    if (existing >= 0) { openCard(existing); return; }
    try {
      const full = await API.evaluate(contract, "lite", profile);
      setVehicles((vs) => { const next = [...vs, { ...full, scored: true, _mode: "lite", _profile: profile }];
        setIdx(next.length - 1); return next; });
      setView("card");
    } catch (e) { /* ignore */ }
  }

  return (
    <div>
      <TopBar theme={theme} setTheme={setTheme} mode={mode} setMode={setMode}
        profile={profile} setProfile={setProfile} view={view} setView={setView}
        idx={idx} setIdx={setIdx} count={vehicles.length} live={live} profileList={profileList}
        onReload={() => loadSale(selected, null)} />
      {view === "settings"
        ? <SettingsView />
        : view === "calib"
        ? <CalibrationView onOpen={openByContract} />
        : view === "lane"
        ? (saleLoading
          ? <LaneLoading />
          : <Lane sale={sale} sales={sales} selected={selected} onSelectSale={selectSale}
            onOpen={openCard} onScreenAll={() => loadSale(selected, "all")} screening={screening} mode={mode}
            prep={prep} onPrep={startPrep} onPrepCancel={cancelPrep} />)
        : (v
          ? <DetailView key={"d" + idx} v={v} mode={mode} profile={profile} setView={setView}
            evalState={evalState[curKey]} deepProgress={deepProgress[curKey]} onReappraise={reappraise}
            onScanComps={scanComps} scanState={scanState[v.contract]}
            onFlagComp={flagComp} onSaveFeedback={saveFeedback} onSaveCarfax={saveCarfax}
            onPullCarfax={pullCarfax} pullState={pullState[v.contract]}
            onRunVision={runVision} visionState={visionState[v.contract]} onSaveOverrides={saveOverrides} />
          : <LaneLoading />)}
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
