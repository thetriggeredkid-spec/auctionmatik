/* ============================================================
   AUCTIONMATIC hi-fi — Appraise ANY vehicle (off-auction)
   Input methods: (1) VMR-style year/make/model/trim selector, (2) VIN decode.
   (Ad-URL paste arrives in Phase D.) Runs the same deep appraisal as a Regal lot
   but with no auction fee and jurisdiction tax, and renders into the verdict card.
   ============================================================ */
const { useState: useStateA, useEffect: useEffectA } = React;

function AppraiseView({ mode, profile }) {
  const blank = { year: "", make: "", model: "", trim: "", driveline: "", engine: "",
    cab: "", km: "", vin: "", seller_type: "private", asking_price: "" };
  const [f, setF] = useStateA(blank);
  const [makes, setMakes] = useStateA([]);
  const [models, setModels] = useStateA([]);
  const [trims, setTrims] = useStateA([]);
  const [vinMsg, setVinMsg] = useStateA(null);
  const [adUrl, setAdUrl] = useStateA("");
  const [adMsg, setAdMsg] = useStateA(null);
  const [extra, setExtra] = useStateA({ source: "manual", photos: [], ad_url: "" });  // from ad ingest
  const [result, setResult] = useStateA(null);
  const [evalState, setEvalState] = useStateA(null);   // null | loading | done | error
  const [progress, setProgress] = useStateA(null);
  const [err, setErr] = useStateA(null);
  const set = (k, v) => setF((s) => ({ ...s, [k]: v }));

  async function fetchAd() {
    if (!adUrl) return;
    setAdMsg("fetching ad…"); setErr(null);
    try {
      const j = await (await fetch(`/api/ingest_ad?url=${encodeURIComponent(adUrl)}`)).json();
      if (j.error) { setAdMsg("could not read ad: " + j.error); return; }
      const v = j.vehicle || {};
      setF((s) => ({ ...s,
        year: v.year || "", make: v.make || "", model: v.model || "", trim: v.trim || "",
        driveline: v.driveline || "", engine: v.engine || "", cab: v.cab || "",
        km: v.odometer_km || "", vin: v.vin || "",
        seller_type: j.seller_type || s.seller_type,
        asking_price: j.asking_price_dollars || "" }));
      setExtra({ source: j.source || "ad", photos: j.photos || [], ad_url: j.listing_url || adUrl });
      setAdMsg(`loaded from ${j.source} · ${(j.photos || []).length} photos — review & run`);
    } catch { setAdMsg("fetch failed"); }
  }

  useEffectA(() => { fetch("/api/vpic/makes").then((r) => r.json()).then((j) => setMakes(j.makes || [])).catch(() => {}); }, []);
  useEffectA(() => {
    if (f.year && f.make) fetch(`/api/vpic/models?make=${encodeURIComponent(f.make)}&year=${f.year}`).then((r) => r.json()).then((j) => setModels(j.models || [])).catch(() => {});
  }, [f.year, f.make]);
  useEffectA(() => {
    if (f.year && f.make && f.model) fetch(`/api/vpic/trims?year=${f.year}&make=${encodeURIComponent(f.make)}&model=${encodeURIComponent(f.model)}`).then((r) => r.json()).then((j) => setTrims(j.trims || [])).catch(() => {});
  }, [f.year, f.make, f.model]);

  async function decodeVin() {
    if (!f.vin) return;
    setVinMsg("decoding…");
    try {
      const j = await (await fetch(`/api/vin_decode?vin=${encodeURIComponent(f.vin)}`)).json();
      const d = j.decoded;
      if (!d) { setVinMsg("no decode (check the VIN)"); return; }
      setF((s) => ({ ...s, year: d.year || s.year, make: d.make || s.make, model: d.model || s.model,
        trim: d.trim || s.trim, driveline: d.driveline || s.driveline, engine: d.engine || s.engine, cab: d.cab || s.cab }));
      setVinMsg("filled from VIN ✓");
    } catch { setVinMsg("decode failed"); }
  }

  function run() {
    if (!f.make || !f.model) { setErr("make and model are required"); return; }
    setErr(null); setResult(null); setEvalState("loading"); setProgress("starting");
    const params = new URLSearchParams({
      ...f, mode: mode === "triage" ? "triage" : "deep", profile,
      source: extra.source, ad_url: extra.ad_url, photos: (extra.photos || []).join(","),
    });
    const es = new EventSource("/api/appraise_stream?" + params.toString());
    es.addEventListener("stage", (e) => setProgress(JSON.parse(e.data)));
    es.addEventListener("result", (e) => { setResult(JSON.parse(e.data)); setEvalState("done"); es.close(); });
    es.addEventListener("failed", (e) => { setErr(JSON.parse(e.data)); setEvalState("error"); es.close(); });
    es.onerror = () => { es.close(); if (evalState === "loading") { setEvalState("error"); setErr("stream interrupted"); } };
  }

  // Result → reuse the full verdict card. Contract is null (no Regal lot); the contract-only
  // actions (flag comp, save feedback, carfax pull, overrides) are inert no-ops here.
  if (result) {
    const noop = () => {};
    return (
      <DetailView v={result} mode={mode} profile={profile} setView={() => setResult(null)}
        evalState="done" deepProgress={null}
        onReappraise={() => run()} onScanComps={noop} scanState={{}}
        onFlagComp={noop} onSaveFeedback={noop} onSaveCarfax={noop}
        onPullCarfax={noop} pullState={{}} onRunVision={noop} visionState={{}} onSaveOverrides={noop} />
    );
  }

  const fs = { fontFamily: "Spline Sans Mono, monospace", fontSize: 14, width: "100%", padding: "9px 11px",
    borderRadius: "var(--r-sm)", border: "1px solid var(--border)", background: "var(--surface-2)", color: "var(--text)" };
  const Field = ({ k, label, list, type = "text", ph }) => (
    <div className="col" style={{ gap: 5 }}>
      <span className="eyebrow">{label}</span>
      <input list={list} type={type} value={f[k]} placeholder={ph || ""} onChange={(e) => set(k, e.target.value)} style={fs} />
    </div>
  );

  return (
    <div className="shell" style={{ paddingTop: 26 }}>
      <div className="rise col" style={{ gap: 7, marginBottom: 8 }}>
        <span className="eyebrow">Appraise any vehicle · off-auction (no buyer fee; tax per your location)</span>
        <h1 className="display" style={{ fontSize: 34 }}>Appraise</h1>
      </div>
      <div className="faint rise" style={{ fontSize: 12, marginBottom: 20, maxWidth: 720, lineHeight: 1.55 }}>
        Paste an ad (Facebook / Kijiji / AutoTrader), or enter a vehicle / VIN, set the seller type and
        asking price, and run the same deep appraisal used for Regal lots — comps, vision, VMR and the
        AI brain — with the private/dealer economics for your active location (set in Settings).
      </div>

      <div className="card-2 rise" style={{ padding: "18px 20px", marginBottom: 16, borderColor: "var(--accent)" }}>
        <div className="row gap8" style={{ alignItems: "flex-end" }}>
          <div className="col" style={{ gap: 5, flex: 1 }}>
            <span className="eyebrow">Paste an ad URL — Facebook · Kijiji · AutoTrader</span>
            <input value={adUrl} placeholder="https://www.facebook.com/marketplace/item/… or kijiji.ca/… or autotrader.ca/…"
              onChange={(e) => setAdUrl(e.target.value)} style={fs} />
          </div>
          <button className="btn accent" onClick={fetchAd} disabled={!adUrl}>Fetch ad</button>
        </div>
        {adMsg && <div className="eyebrow" style={{ marginTop: 8, color: "var(--bid)" }}>{adMsg}</div>}
        {extra.photos.length > 0 && (
          <div className="row gap8" style={{ marginTop: 10, overflowX: "auto" }}>
            {extra.photos.slice(0, 8).map((p, i) => (
              <img key={i} src={p} alt="" style={{ height: 52, borderRadius: 6, flexShrink: 0 }}
                onError={(e) => { e.currentTarget.style.display = "none"; }} />
            ))}
          </div>
        )}
      </div>

      <datalist id="dl-makes">{makes.map((m) => <option key={m} value={m} />)}</datalist>
      <datalist id="dl-models">{models.map((m) => <option key={m} value={m} />)}</datalist>
      <datalist id="dl-trims">{trims.map((t) => <option key={t} value={t} />)}</datalist>

      <div className="card-2 rise" style={{ padding: "18px 20px", marginBottom: 16 }}>
        <div className="row gap8" style={{ alignItems: "flex-end" }}>
          <div className="col" style={{ gap: 5, flex: 1, maxWidth: 320 }}>
            <span className="eyebrow">VIN (shortcut — autofills the spec)</span>
            <input value={f.vin} placeholder="1C4HJXEG5JW287140" onChange={(e) => set("vin", e.target.value)} style={fs} />
          </div>
          <button className="btn" onClick={decodeVin}>Decode VIN</button>
          {vinMsg && <span className="eyebrow" style={{ color: "var(--bid)" }}>{vinMsg}</span>}
        </div>
      </div>

      <div className="card-2 rise" style={{ padding: "18px 20px", marginBottom: 16 }}>
        <span className="eyebrow">Vehicle</span>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: 12, marginTop: 10 }}>
          <Field k="year" label="year" type="number" ph="2018" />
          <Field k="make" label="make" list="dl-makes" ph="TOYOTA" />
          <Field k="model" label="model" list="dl-models" ph="RAV4" />
          <Field k="trim" label="trim" list="dl-trims" ph="XLE" />
          <Field k="km" label="odometer (km)" type="number" ph="95000" />
          <Field k="driveline" label="driveline" ph="AWD" />
          <Field k="engine" label="engine" ph="2.5L I4" />
          <Field k="cab" label="cab (trucks)" ph="crew" />
        </div>
      </div>

      <div className="card-2 rise" style={{ padding: "18px 20px", marginBottom: 18 }}>
        <span className="eyebrow">Purchase</span>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 12, marginTop: 10 }}>
          <div className="col" style={{ gap: 5 }}>
            <span className="eyebrow">seller type (sets tax)</span>
            <select value={f.seller_type} onChange={(e) => set("seller_type", e.target.value)} style={fs}>
              <option value="private">private</option>
              <option value="dealer">dealer / business</option>
            </select>
          </div>
          <Field k="asking_price" label="asking price $" type="number" ph="24000" />
        </div>
      </div>

      <div className="row between" style={{ alignItems: "center" }}>
        <span className="faint" style={{ fontSize: 12 }}>
          {evalState === "loading" ? "Appraising — this takes ~60–90s for a deep run." : "make + model required"}
          {err && <span style={{ color: "var(--pass)" }}> · {typeof err === "string" ? err : (err.error || "error")}</span>}
        </span>
        <button className="btn accent" disabled={evalState === "loading" || !f.make || !f.model} onClick={run}>
          {evalState === "loading" ? "Appraising…" : "Run deep appraisal"}
        </button>
      </div>

      {evalState === "loading" && (
        <div className="card-2 rise" style={{ padding: 20, marginTop: 18, textAlign: "center" }}>
          <span className="spin" style={{ width: 16, height: 16, borderRadius: 99, border: "2px solid var(--accent)", borderTopColor: "transparent", display: "inline-block", marginRight: 10 }} />
          <span className="dim" style={{ fontSize: 13 }}>{typeof progress === "string" ? progress : "working"}…</span>
        </div>
      )}
    </div>
  );
}
