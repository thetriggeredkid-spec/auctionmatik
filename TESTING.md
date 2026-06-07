# Auctionmatik — Testing Handoff

Two parts: a **project summary** (paste as context for any tester) and a **Claude-on-Chrome
testing-agent prompt** (a browser agent that uses the live app like a real user and reports
bugs / UX issues / feature ideas). See `CLAUDE.md` + `PROGRESS.md` for architecture.

---

## Part 1 — Project Summary

### What it is
A **behavioral used-vehicle pricing engine** with a **web dashboard**, built for a Regal
Auctions (Alberta) car flipper. Thesis: book tools (KBB/Black Book/VMR) price the *asset* via
depreciation; this prices the *transaction* using real comps + behavioral/contextual factors.
For any upcoming auction vehicle it outputs a **verdict (BID / BID-TO-FIX / PASS)**, a **retail
value**, and a **max bid**, with full reasoning.

**Architecture — AI-primary hybrid:**
- `engine/appraiser.py` — Claude Sonnet 4.6 is the brain; reasons from assembled evidence.
  Two modes: **triage** (fast) and **deep** (agentic: adaptive thinking, narration, escalation
  tools, operator-correction calibration).
- `engine/advisor.py` — deterministic rules engine running alongside as a **sanity band**.
- In the dashboard: **triage = the deterministic result** (instant, identical to the lane);
  **deep = the AI pass**.

**Stack:** Python 3, PostgreSQL 16 (Docker, port 5433), Flask API, and a **Vite + React + TypeScript
+ Tailwind v4 + shadcn/ui** SPA in `dashboard/web/` (built → `web/dist`, which Flask serves; June 2026
re-platform from the old React-over-Babel UI). `anthropic` (Sonnet reasoning + Haiku vision),
`apify-client` (FB/Kijiji scraping), `playwright` (local Carfax agent).
Run: `cd dashboard/web && npm install && npm run build`, then `python3 -m dashboard.server` →
http://127.0.0.1:8080 (header shows a `build` marker; if the UI looks stale it's browser cache/an
extension, not the code — see CLAUDE.md). **Also new:** the **✦ Appraise** tab deep-appraises any
vehicle off-auction (selector / VIN / pasted FB-Kijiji-AutoTrader ad URL) — see CLAUDE.md + PROGRESS.md.

### Data sources
| Source | Table/Module | Role |
|---|---|---|
| Regal sold history | `regal_sold` | **Past Sales** — actual auction results = wholesale comp pool |
| Regal active listings | `regal_listings` | **The Lane** — current upcoming-sale inventory |
| Facebook Marketplace / Kijiji | `retail_listings` (Apify) | **Comps** — retail asking-price anchor |
| VMR Canada | `collector/vmr.py` (live fetch) | **Book-value sanity check** |
| Carfax Canada | `carfax_report` (local agent) | History (accidents/claims/service/branding) |

### Current functions (what works today)
**The Lane** — structured like Regal: one **sale** at a time, only **upcoming Tuesday Timed
Auctions + Saturday Super Sales**, vehicles in **lot order**, screened deterministically
(cached). Sale selector, sort (lot/verdict/bid/value/km), verdict filters, cover-photo
thumbnails, declaration chips, ⚡ conditional + `deep?` flags, "Screen all".

**Verdict Card** — identity header (+ photo gallery, VMR ↗ / Carfax ↗ / Regal ↗ links),
verdict **hero** (max bid, confidence gauge, conditional-bid card, ↻ Re-appraise), and tabs:
- **Reasoning** — narrated reasoning, **max-bid derivation waterfall**, **VMR sanity-check
  card** (flags >20% divergence), **AI-vs-rules** number line, key adjustments.
- **Comps** — retail comps with photo + click-through link; **⚑ flag a bad comp** → excluded
  from anchors forever; trim/cab-aware matching; **⟳ Scan for comps** (trim-targeted FB scrape)
  when empty.
- **Past Sales** — actual `regal_sold` results for similar units, with Regal links.
- **Vision** — Haiku photo assessment (grades/damage/rust/hail/mods); **⟳ Analyze photos**
  button (enrich gallery + run vision); auto-runs in deep.
- **Repair** — line-item repair quote + 3 sourcing strategies (Mode B).
- **Recon & sale** — recon ROI plan + sale plan.
- **Declarations** — decoded Regal codes (FD/RS/MP/HD/CH####/TI/FR/OOP…) + flags.
- **Verify** — pre-bid checklist.
- **Carfax** — working report link + **manual entry** + **⟳ Auto-pull** (headless browser
  agent); deep auto-pulls when missing; engine re-prices on save.
- **Correct** — the **training loop**: record actual sale price + corrected value/max-bid/
  verdict + notes → stored, and fed to the AI as **calibration** on future similar vehicles.

**Controls:** triage/deep mode · charles/mechanic profile · light/dark theme (persists) ·
prev/next nav. **Methodology:** comp-scrutiny (not blind median), Mode A (retail flip) vs Mode B
(repair project), claims as a value-scaled fraction (Carfax overrides the CH band), truck config
(cab/bed/trim/engine) as primary value drivers, finance-repo NOT penalized, prices in CAD cents
internally.

### Known limitations / rough edges
- AI **deep is slow** (~60–90s); triage is instant.
- **Carfax & Vision auto-pull need a local browser**; on a server they degrade to manual entry.
- **`retail_listings` is sparse** for many models → Comps tab empty until you Scan (Apify
  credits, ~1–2 min).
- Lane shows **only Tue/Sat** upcoming sales; unscheduled listings are excluded by design.
- Vision samples **30 photos** per read (cap). Desktop-only; single-user; no auth.

### Future features (not yet implemented)
1. **Vision-on-comps** — auto-assess each comp's photos to catch damaged comps (vs. manual ⚑).
2. **Editable human-in-the-loop overrides** — tweak condition grades / repair costs → re-appraise.
3. **Settings / profile editor** — margin floors, fee schedule, sourcing factors, profiles.
4. **Chrome-extension version** — runs Carfax/VMR in your real browser session (no server captcha).
5. **Server-side Carfax** — hybrid worker queue or managed scraping browser.
6. **Bulk/concurrent lane screening** — rate-limited deep-screen of a whole sale.
7. **Deep-run streaming UI** — live progress during the AI pass.
8. **Outcome-analytics / auto-tuning** — mine `listing_feedback` for systemic error patterns.
9. **VMR persistence + marker on the rules line**; raise vision photo cap; store trim/body on scrape.
10. **Mobile/responsive layout; multi-user/auth.**

---

## Part 2 — Claude-on-Chrome Testing-Agent Prompt

> Paste Part 1 alongside this so the agent has the spec. Make sure the dashboard is running and
> the agent's Chrome can reach the URL. Note: deep/scan/vision/carfax actions spend real
> AI/Apify credits — the prompt caps them to 1–2 tries.

```
You are a QA + UX tester for "Auctionmatik," a web dashboard that prices used vehicles for
auction bidding. You're driving a real Chrome browser — act like an actual user: navigate,
click everything, type into forms, read what renders, and take screenshots. You CANNOT see
the code or use a terminal; judge the app purely by using it. Be thorough, skeptical, and
specific. Don't change anything server-side — just exercise it, find bugs, and recommend
improvements. The human will paste a project summary (intended functions + future-features
list) alongside this — use it as your spec for "expected behavior."

## Start here
The app is already running at:  http://127.0.0.1:8080
Open it. You should land on "The Lane." Spend a minute orienting before testing.

## What the UI is (so you know what to look for — but also explore on your own)
- Top bar: logo, a lane / card toggle, a triage/deep toggle, a charles/mechanic profile
  toggle, prev-next, a dark/light theme toggle, and a live/sample status chip.
- The Lane: a heading, a row of SALE pills (e.g. "Tue · Jun 2 · 421"), a sort control
  (lot / verdict / max bid / value / km), verdict filter chips (All / BID / BID-TO-FIX / PASS),
  a sale banner showing "screened X / N" with a "Screen all" button, and a table of vehicles
  (lot #, photo, vehicle, km, declaration chips, verdict pill, max bid, value, confidence, › ).
- A Verdict Card (opens when you click a row): a "‹ The Lane" back link, VMR / Carfax / Regal
  links, an identity header + photo gallery, a big colored VERDICT hero (verdict, max bid,
  confidence, value, margin, sometimes a conditional-bid card, and a Re-appraise button),
  then a row of tabs: Reasoning, Comps, Past Sales, Vision, Repair, Recon & sale, Declarations,
  Verify, Carfax, Correct.

## How to test — drive these flows like a user
1. The Lane: switch between sale pills; confirm only Tuesday/Saturday sales appear and rows are
   in lot order. Try every sort and filter. Click "Screen all" and watch it score more rows.
2. Open several cards. CRITICAL CHECK: the verdict/max-bid on the card must MATCH what the lane
   row showed (in triage). Go back to the lane and confirm the row reflects what you just saw
   (and didn't reset). Re-open the same card — it should not re-run from scratch.
3. Toggle triage <-> deep on a card. Deep runs the AI and is SLOW (~60-90s) — confirm there's a
   clear "evaluating" state and it doesn't look frozen or broken. Toggle charles <-> mechanic and
   confirm the numbers change sensibly. Toggle dark/light and reload — theme should persist.
4. Click through EVERY tab on a few different vehicles (pick varied ones: a clean BID, a
   PASS, a salvage/BID-TO-FIX, a truck). On each tab judge: does it render, are the numbers
   coherent, are links live, are empty/loading/error states handled?
   - Reasoning: does the "derivation waterfall" visually add up to the max bid? Is there a VMR
     sanity-check card, and does it flag big gaps?
   - Comps: do comp links open the real ad? Try the flag (⚑) on a comp (give a reason) — does it
     disappear and the value update? If the tab is empty, try "Scan for comps".
   - Past Sales: real sold rows with working Regal links?
   - Vision: if empty, click "Analyze photos" (~20s) and confirm grades/photos appear.
   - Carfax: try the "View report" link; type values into the manual entry and Save — does the
     engine re-price? Try "Auto-pull Carfax" once.
   - Correct: enter an actual sale price + corrected value + notes, Save, navigate away and back —
     did it persist?
5. Edge/abuse: rapidly switch modes/profiles/sales; open and back out quickly; submit empty
   forms; double-click buttons; very long sales. Look for stuck spinners, stale data, flicker,
   duplicated requests, or anything that breaks.

## Caution on slow / costly actions
Some buttons trigger real work: deep mode (AI, ~60-90s), "Scan for comps" (live scrape, ~1-2 min),
"Analyze photos" (~20s), "Auto-pull Carfax" (~15-30s). Exercise each of these ONCE or TWICE to
verify they work and have proper loading states — don't spam them.

## What to scrutinize (think like a flipper screening hundreds of cars fast)
- Bugs: wrong/garbled numbers, lane-vs-card mismatch, data that goes stale after an action,
  broken or wrong links, layout breakage, overlapping text, things that silently do nothing,
  spinners that never resolve, values in the wrong units, a verdict color that doesn't match
  the result.
- UX friction: confusing labels, hidden or unclear buttons, missing loading/empty/error states,
  no feedback after an action, too many clicks, anything slow without a progress indicator,
  small tap targets, poor scannability of the lane.
- Trust/coherence: do the engine's value and max bid look defensible vs the VMR card and Past
  Sales on the same screen? Call out obvious over/under-valuations.
- Gaps: features a real bidder would expect that are missing or awkward.

## Report
Deliver one report:
1. Bugs — each with: severity (P0 blocker / P1 major / P2 minor), the exact CLICK PATH to
   reproduce, expected vs. actual, and a screenshot.
2. UX issues — ranked by impact, each with a concrete suggested fix and a screenshot where useful.
3. Feature suggestions — prioritized, one-line rationale each.
4. Top 5 quick wins — highest value, lowest effort.
Cite specifics (which sale, which vehicle/lot #, which tab/button) and attach screenshots.
You are testing and recommending only — do not attempt to modify the app.
```
