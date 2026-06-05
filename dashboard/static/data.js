/* ============================================================
   Auctionmatic — sample evaluation data
   Three fully-detailed cases + lane filler. window.VEHICLES.
   ============================================================ */

window.VERDICT = {
  BID:        { key: "BID",        cls: "v-bid",  edge: "e-bid",  mode: "retail flip" },
  BID_TO_FIX: { key: "BID-TO-FIX", cls: "v-fix",  edge: "e-fix",  mode: "repair project" },
  PASS:       { key: "PASS",       cls: "v-pass", edge: "e-pass", mode: "pass" },
};

window.confLevel = function (c) { return { low: 1, medium: 2, high: 3 }[c] || 0; };

/* ---- Case 1: Jeep Wrangler — clean BID (the spec example) ---- */
const JEEP = {
  contract: "37316", regalId: "437316",
  year: 2015, make: "JEEP", model: "WRANGLER", trim: "Sport",
  driveline: "4WD", type: "Sport Utility", km: 140722,
  vin: "1C4BJWDG8FL618478", color: "GREY", engine: "6 Cyl", trans: "Auto",
  seller: "Auto Broker", reserve: 15000, auctionDate: "Jun 4", needsDeep: false,
  decl: { raw: "CH15000",
    chips: [{ code: "CH", label: "Claims ≥ $15k", sev: "hi" }],
    codes: [{ code: "CH15000", label: "Claims Total", meaning: "Cumulative insurance claims ≥ $15,000." }],
    claimsLow: 15000,
    flags: [{ sev: "high", msg: "Cumulative claims ≥ $15,000 — Carfax: one big hit vs many small?" }] },
  verdict: "BID", value: 13750, valueBasis: "as-is retail", maxBid: 10700,
  conf: "medium", margin: 1500,
  summary: "2015 Wrangler ~140k, CH15000 claims but clean title. Strong Wrangler demand; quick flip after windshield + detail.",
  topFlags: ["CH15000 claims — pull Carfax", "Windshield crack ~$350"],
  conditional: null,
  reasoning: "Clean market anchor ~$15,750 from km-normalized engine comps. Deduct ~$1,750 for cumulative claims even though title stays clean — buyers discount CH history. Windshield + detail recon ~$600. Wrangler liquidity is excellent; 2–3 week sell at $14.5k ask is realistic. Net lands comfortably above a $1,500 margin at a $10,700 ceiling.",
  adjustments: [
    { factor: "Clean market anchor", impact: "$15,750", evidence: "km-adj 2014 comp $11,200 floor; engine anchor $15,652" },
    { factor: "CH15000 cumulative claims", impact: "−$1,750", evidence: "claims_total_low=15000; clean title retained" },
    { factor: "Windshield crack", impact: "−$450", evidence: "vision: moderate crack, driver side" },
    { factor: "Wrangler demand premium", impact: "+$200", evidence: "6 comps DOM 1–9 days" },
  ],
  toolsUsed: ["get_carfax_report"],
  rules: { charles: { verdict: "BID", maxBid: 10560, margin: 1500, fee: 535 },
           mechanic: { verdict: "BID", maxBid: 11422, margin: 800, fee: 535 } },
  divergence: "+2.3% vs rules engine $10,560 — within band; both BID",
  recon: [
    { action: "Windshield replacement", decision: "REQUIRED", cost: 450, why: "Visible crack; buyers negotiate $600–800 off" },
    { action: "Full detail", decision: "DO", cost: 150, why: "Supports $14.5k ask" },
    { action: "Touch-up front bumper", decision: "SKIP", cost: 0, why: "Minor scratch; not worth it" },
  ],
  sale: { channel: "Retail (FB / Kijiji)", list: 14500, floor: 13500, days: "14–21" },
  verify: [
    "Pull full Carfax — one big claim vs many small?",
    "Confirm clean title (not yet rebuilt despite CH15000)",
    "Start engine cold — listen for top-end tick",
  ],
  vision: { extGrade: 3, intGrade: 3, rust: "none", hail: "none", flood: false,
    damage: [{ panel: "windshield", type: "crack", sev: "moderate" },
             { panel: "front bumper", type: "scratch", sev: "minor" }],
    mods: [{ type: "Pioneer head unit", quality: "professional" },
           { type: "subwoofer enclosure", quality: "amateur" }],
    conf: "high", analyzed: 30, total: 44, model: "claude-haiku-4-5" },
  comps: { anchor: 15652, conf: "high", source: "retail comp-scrutiny (6 comps, high)",
    used: [
      { y: 2014, mk: "Jeep", md: "Wrangler", km: 134000, ask: 11500, dom: 1, disc: 0, est: 11500, kmAdj: 11200, cond: "unknown", title: "clean", score: 0.83 },
      { y: 2015, mk: "Jeep", md: "Wrangler", km: 152000, ask: 16900, dom: 9, disc: 4, est: 16200, kmAdj: 16700, cond: "good", title: "clean", score: 0.88 },
      { y: 2016, mk: "Jeep", md: "Wrangler", km: 119000, ask: 18400, dom: 5, disc: 2, est: 18000, kmAdj: 16400, cond: "good", title: "clean", score: 0.79 },
    ],
    excluded: [{ y: 2013, mk: "Jeep", md: "Wrangler", ask: 9500, reason: "rebuilt/salvage title — not a clean comp" }] },
  repair: null, carfax: { accidents: 1, claims: 16200, branding: "None", lastKm: 138900, service: "7 records, dealer-maintained" },
  meta: { model: "claude-sonnet-4-6", effort: "low", elapsed: 46.7,
    tokens: { in: 982, cache: 3121, out: 2109 }, cost: 0.04 },
};

/* ---- Case 2: Nissan Pathfinder — PASS with conditional bid ---- */
const PATHFINDER = {
  contract: "37402", regalId: "437402",
  year: 2016, make: "NISSAN", model: "PATHFINDER", trim: "SV",
  driveline: "4WD", type: "Sport Utility", km: 168400,
  vin: "5N1AR2MM7GC601233", color: "WHITE", engine: "6 Cyl", trans: "CVT",
  seller: "Dealer Trade", reserve: 6000, auctionDate: "Jun 4", needsDeep: true,
  decl: { raw: "MR / RS",
    chips: [{ code: "MR", label: "Mechanical", sev: "med" }, { code: "RS", label: "Remark", sev: "lo" }],
    codes: [{ code: "MR", label: "Mechanical Risk", meaning: "Declared mechanical concern." }],
    claimsLow: 0,
    flags: [{ sev: "med", msg: "CVT-equipped Pathfinder — known failure point. Confirm health before any bid." }] },
  verdict: "PASS", value: 5500, valueBasis: "as-is", maxBid: 0,
  conf: "medium", margin: 0,
  summary: "2016 Pathfinder 168k, CVT-equipped with mechanical declaration. Too risky at value — but a clean drivetrain flips the math.",
  topFlags: ["CVT failure risk", "Mechanical declaration (MR)"],
  conditional: { amount: 2500, condition: "pre-bid inspection confirms CVT / drivetrain healthy, nothing major" },
  reasoning: "Healthy these retail ~$8–9k, but the CVT + mechanical declaration is the whole story. A failed CVT is a $4–5k job that erases the deal. At blind value this is a PASS at $5,500. HOWEVER — if a pre-bid inspection confirms the transmission is healthy, the unit is worth a disciplined $2,500 conditional bid for a tidy flip.",
  adjustments: [
    { factor: "Healthy retail anchor", impact: "$8,400", evidence: "4 comps, CVT-healthy units" },
    { factor: "CVT / mechanical risk", impact: "−$2,900", evidence: "MR declaration; 168k on original CVT" },
  ],
  toolsUsed: [],
  rules: { charles: { verdict: "PASS", maxBid: 0, margin: 1500, fee: 535 },
           mechanic: { verdict: "PASS", maxBid: 2200, margin: 800, fee: 535 } },
  divergence: "Both PASS on blind value; mechanic profile would conditional-bid $2,200",
  recon: [
    { action: "CVT diagnostic", decision: "REQUIRED", cost: 120, why: "The entire thesis hinges on this" },
    { action: "Detail", decision: "RESERVE", cost: 150, why: "Only if drivetrain clears" },
  ],
  sale: { channel: "Retail (FB)", list: 8900, floor: 7800, days: "21–30" },
  verify: [
    "PRE-BID CVT inspection — scan for codes, test drive incl. highway",
    "Check for whine / shudder under load",
    "Confirm no transmission service avoidance in history",
  ],
  vision: { extGrade: 3, intGrade: 2, rust: "light", hail: "none", flood: false,
    damage: [{ panel: "rear hatch", type: "dent", sev: "minor" }],
    mods: [], conf: "medium", analyzed: 22, total: 31, model: "claude-haiku-4-5" },
  comps: { anchor: 8400, conf: "medium", source: "retail comp-scrutiny (4 comps, medium)",
    used: [
      { y: 2016, mk: "Nissan", md: "Pathfinder", km: 159000, ask: 9200, dom: 12, disc: 5, est: 8700, kmAdj: 8500, cond: "good", title: "clean", score: 0.81 },
      { y: 2015, mk: "Nissan", md: "Pathfinder", km: 172000, ask: 8400, dom: 22, disc: 8, est: 7700, kmAdj: 7900, cond: "fair", title: "clean", score: 0.84 },
    ],
    excluded: [] },
  repair: null, carfax: null,
  meta: { model: "claude-sonnet-4-6", effort: "medium", elapsed: 51.2,
    tokens: { in: 1102, cache: 2890, out: 1840 }, cost: 0.05 },
};

/* ---- Case 3: Chevy Equinox — salvage repair project (BID-TO-FIX) ---- */
const EQUINOX = {
  contract: "37288", regalId: "437288",
  year: 2014, make: "CHEVROLET", model: "EQUINOX", trim: "LT",
  driveline: "AWD", type: "Sport Utility", km: 96500,
  vin: "2GNFLGEK1E6112099", color: "RED", engine: "4 Cyl", trans: "Auto",
  seller: "Insurance", reserve: 3500, auctionDate: "Jun 4", needsDeep: true,
  decl: { raw: "RB / SA",
    chips: [{ code: "SA", label: "Salvage", sev: "hi" }, { code: "RB", label: "Rebuilt path", sev: "hi" }, { code: "FD", label: "Frame", sev: "hi" }],
    codes: [{ code: "SA", label: "Salvage", meaning: "Branded salvage; structural repair required." }],
    claimsLow: 0,
    flags: [{ sev: "high", msg: "Frame rail damage — confirmed structural. Repair-only thesis." }] },
  verdict: "BID_TO_FIX", value: 11200, valueBasis: "after-fix retail", maxBid: 1900,
  conf: "low", margin: 2500,
  summary: "2014 Equinox 96k, salvage + frame damage. Only works as a DIY/used-parts repair project — thin and contingent.",
  topFlags: ["Frame rail — structural", "Salvage title caps resale"],
  conditional: null,
  reasoning: "After-fix retail caps around $11,200 given the rebuilt brand. Repair is dominated by a frame rail replacement; only the used/DIY sourcing path leaves margin. Confirmed work runs $7.1–10.9k with another $1.2–2.5k contingent. This is BID-TO-FIX only for a hands-on buyer at a hard $1,900 ceiling — not a flip.",
  adjustments: [
    { factor: "After-fix retail (rebuilt)", impact: "$11,200", evidence: "rebuilt-title comps, −22% vs clean" },
    { factor: "Frame rail replacement", impact: "−$3,500", evidence: "vision: severe; structural" },
    { factor: "DIY/used sourcing assumed", impact: "+$2,000", evidence: "vs OEM-shop path" },
  ],
  toolsUsed: ["estimate_repair", "get_carfax_report"],
  rules: { charles: { verdict: "BID_TO_FIX", maxBid: 1700, margin: 2500, fee: 535 },
           mechanic: { verdict: "BID_TO_FIX", maxBid: 2400, margin: 1500, fee: 535 } },
  divergence: "AI $1,900 between profiles — within band; all BID-TO-FIX",
  recon: [
    { action: "Frame rail replace", decision: "REQUIRED", cost: 3500, why: "Structural; safety + resale" },
    { action: "Front clip (used)", decision: "DO", cost: 1400, why: "Used-parts sourcing" },
    { action: "Alignment + calibrate", decision: "REQUIRED", cost: 600, why: "Post-structural" },
  ],
  sale: { channel: "Retail (rebuilt-savvy buyer)", list: 11200, floor: 9800, days: "30–45" },
  verify: [
    "Confirm frame damage scope on a lift before bidding",
    "Source used front clip availability + price",
    "Verify airbags intact / not deployed",
  ],
  vision: { extGrade: 2, intGrade: 3, rust: "none", hail: "none", flood: false,
    damage: [{ panel: "frame rail", type: "structural", sev: "severe" },
             { panel: "front bumper", type: "crushed", sev: "severe" },
             { panel: "hood", type: "buckled", sev: "moderate" }],
    mods: [], repairComponents: ["frame rail", "front clip", "radiator support"],
    conf: "medium", analyzed: 28, total: 28, model: "claude-haiku-4-5" },
  comps: { anchor: 11200, conf: "low", source: "wholesale-derived (rebuilt)",
    used: [
      { y: 2014, mk: "Chevrolet", md: "Equinox", km: 102000, ask: 11900, dom: 18, disc: 6, est: 11200, kmAdj: 11400, cond: "rebuilt", title: "rebuilt", score: 0.77 },
    ],
    excluded: [{ y: 2014, mk: "Chevrolet", md: "Equinox", ask: 14500, reason: "clean title — not comparable to rebuilt unit" }] },
  repair: {
    lineItems: [
      { comp: "frame rail", action: "replace", sev: "severe", low: 3000, high: 4000, contingent: false },
      { comp: "front clip", action: "replace (used)", sev: "severe", low: 1200, high: 1900, contingent: false },
      { comp: "radiator support", action: "replace", sev: "moderate", low: 600, high: 1100, contingent: false },
      { comp: "airbag module", action: "inspect", sev: "unknown", low: 800, high: 1600, contingent: true },
      { comp: "alignment / calibration", action: "service", sev: "—", low: 500, high: 900, contingent: false },
    ],
    sourcing: { oem_shop: { low: 9280, high: 14902, mid: 12091 },
                middle:   { low: 7100, high: 10900, mid: 9000 },
                used_diy: { low: 5372, high: 8654,  mid: 7013 } },
    confirmed: { low: 7100, high: 10900 }, contingent: { low: 1192, high: 2459 }, buffer: 0.20 },
  carfax: { accidents: 1, claims: 0, branding: "Salvage → Rebuilt path", lastKm: 95800, service: "Sparse" },
  meta: { model: "claude-sonnet-4-6", effort: "high", elapsed: 58.9,
    tokens: { in: 1340, cache: 3402, out: 2680 }, cost: 0.07 },
};

/* ---- lane filler (lighter rows) ---- */
const FILLER = [
  { contract: "37355", year: 2018, make: "TOYOTA", model: "COROLLA", trim: "LE",
    km: 88200, driveline: "FWD", color: "SILVER", engine: "4 Cyl",
    decl: { chips: [] }, verdict: "BID", value: 14900, maxBid: 12100, conf: "high",
    margin: 1500, needsDeep: false, conditional: null,
    summary: "Clean low-risk Corolla. Easy retail flip, no recon.", topFlags: [] },
  { contract: "37361", year: 2017, make: "FORD", model: "F-150", trim: "XLT",
    km: 121000, driveline: "4WD", color: "BLUE", engine: "6 Cyl",
    decl: { chips: [{ code: "HD", label: "Hail", sev: "med" }] },
    verdict: "BID_TO_FIX", value: 24500, maxBid: 17800, conf: "medium",
    margin: 2500, needsDeep: true, conditional: null,
    summary: "Hail dimples across hood/roof. PDR brings it back; truck demand strong.", topFlags: ["Hail — PDR estimate"] },
  { contract: "37370", year: 2013, make: "DODGE", model: "GRAND CARAVAN", trim: "SXT",
    km: 198400, driveline: "FWD", color: "BLACK", engine: "6 Cyl",
    decl: { chips: [{ code: "HD", label: "High km", sev: "lo" }] },
    verdict: "PASS", value: 4200, maxBid: 0, conf: "high",
    margin: 0, needsDeep: false,
    conditional: { amount: 1200, condition: "no transmission codes + clean test drive" },
    summary: "198k minivan, thin demand. No margin at value — small conditional only.", topFlags: ["High km", "Soft segment"] },
];

window.VEHICLES = [JEEP, PATHFINDER, EQUINOX, ...FILLER];
window.fmt = function (n) {
  if (n == null) return "—";
  return "$" + n.toLocaleString("en-US");
};
window.vehName = function (v) { return v.year + " " + v.make + " " + v.model; };
