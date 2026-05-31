# Auctionmatik — Valuation Methodology

**Version:** 0.3 (Session 2)
**Status:** Draft — implementation-ready for Phase 1

This document is the specification for the valuation engine. Every factor the engine considers, how it is observed, and how it adjusts the output is defined here. When the methodology changes, this document changes first.

---

## 0. Core Thesis

Existing tools (KBB, Black Book, MMR) price the **asset** using depreciation curves and structured attributes. Real transaction prices are determined by behavioral and contextual factors those tools ignore: seller urgency, listing quality, specific options, condition nuance, market trajectory, buyer dynamics, and regional demand.

This engine prices the **transaction** — the specific deal between a specific buyer and seller, in a specific market, at a specific moment.

---

## 1. Sale Type Classification

Every transaction is classified into one of three types. This classification determines which baseline the engine uses.

| Type | Definition | Sources |
|---|---|---|
| **Retail** | End consumer purchasing at or near market value | Facebook Marketplace, Kijiji (private sale, priced at market) |
| **Wholesale** | Dealer or reseller purchasing below retail, intending to resell | Regal Auctions, any private sale clearly below market |
| **Distressed** | Forced or urgent sale — repo, estate, non-running, damaged | Regal Auctions (Finance Repo), Kijiji/FB listings with urgency language |

Classification is inferred from source, seller type, listing language, and price relative to comps. It is not always binary — a private Facebook sale at 85% of market sits between retail and wholesale.

**Why this matters:** A 2019 F-150 that sold for $28k at Regal (wholesale) and one that sold for $34k on Kijiji (retail) are not comparable data points for the same question. They answer different questions. The engine maintains separate baselines for each type.

---

## 2. Base Price Layer

### 2.1 Comp Pool Definition

The base price for a vehicle is derived from **recent comparable sales**, not a depreciation formula.

**Base grouping (primary):** `Year / Make / Model / Trim / Drivetrain`

Examples:
- 2019 Ford F-150 XLT 4WD
- 2018 Toyota RAV4 LE AWD
- 2016 Honda Civic EX FWD

**Fallback when comp count is low (<10 comps in base group):** Drop to `Year / Make / Model / Drivetrain`, then `Year / Make / Model`.

**Comp recency weighting:** Transactions from the last 30 days are weighted 3x. Last 90 days are weighted 1.5x. Beyond 90 days are weighted 1x. The market right now matters more than the market six months ago.

**Minimum viable comp pool:** 10 transactions to produce a confident estimate. Below 10, the engine produces a wider range and flags low confidence.

### 2.2 Market Reference

The base is set from **what is currently listed and what has recently sold** — not MSRP, not book value. A Toyota RAV4 in the same year and mileage as a Lincoln MKZ is worth significantly more despite lower MSRP, because the market has validated its reliability premium through thousands of transactions. The engine learns this from actual comp data, not assumptions.

This also means the engine must compare across **competitor models** — a buyer shopping for a 2018 midsize SUV is cross-shopping RAV4 against CR-V against Escape against Rogue. The availability and pricing of those alternatives sets the ceiling for each.

### 2.3 Regional Baseline

Baselines are maintained per **region** (province/city tier). See Section 7 for location logic. A Calgary baseline is separate from a national baseline.

---

## 3. Vehicle Identity & Attributes

These are the structured facts about the vehicle — what it is, independent of condition.

### 3.1 Core Identity

| Field | Notes |
|---|---|
| Year | Model year |
| Make | Manufacturer |
| Model | Model name |
| Trim | Factory trim level (XLT, EX, Lariat, etc.) — critical for accurate comps |
| Drivetrain | FWD / RWD / AWD / 4WD |
| Body style | 4D Sedan / Crew Cab / Hatchback / SUV / etc. |
| Engine | Displacement + configuration (e.g., 2.0L 4-cyl, 5.0L V8) |
| Transmission | Automatic / Manual / CVT / DCT |
| Fuel type | Gas / Diesel / Hybrid / EV / PHEV |
| Exterior color | Factory color name where possible |
| Interior color | Black / Tan / Grey / Other |
| Interior material | Cloth / Leatherette / Leather / Alcantara |
| VIN | Full VIN — decoded via NHTSA API for factory build spec |

### 3.2 High-Value Options

Options are recorded as present/absent flags. Each has a percentage delta associated with it (see Section 6). OEM factory options are treated differently from aftermarket equivalents — OEM is generally more desirable and commands a higher premium.

**Universal (applies to most vehicles):**
- Sunroof / moonroof / panoramic roof
- Navigation (value declining on post-2018 vehicles as Apple CarPlay/Android Auto proliferated)
- Premium audio (Bose, B&O, Harman Kardon, etc.)
- Heated front seats
- Heated steering wheel
- Remote start (OEM)
- Blind spot monitoring / rear cross-traffic
- Lane departure / lane keep assist
- Parking sensors / 360 camera
- Power tailgate / liftgate
- Cold weather package (significant premium in Alberta)
- Technology/safety package (bundled ADAS)

**Truck/SUV specific:**
- Towing package (factory — includes transmission cooler, upgraded hitch receiver, brake controller wiring)
- Max tow package
- Bed liner (spray-in vs. drop-in — spray-in is OEM-preferred)
- Tonneau cover
- Running boards / nerf bars
- Diesel engine (strong premium, especially on work trucks)
- Third row seating
- 4-corner air suspension

**Performance/enthusiast:**
- Sport/performance package
- Limited slip differential
- Track package
- Upgraded brake package

### 3.3 Modifications

OEM options are preferred by most buyers. Aftermarket modifications introduce uncertainty (quality of install, voided warranty, unknown history) and in many cases reduce value. The engine tracks modifications separately from options and applies a bias toward negative delta unless evidence suggests the specific mod adds value for the specific vehicle/market.

**The default treatment for aftermarket modifications is neutral (0% delta).** Most mods neither add nor subtract value in aggregate — the pool of buyers who want a modded vehicle and the pool who don't roughly cancel out. What matters is whether the mod is desirable, well-executed, and raises or lowers suspicion.

**Modifications with specific signal flags:**

| Modification | Delta tendency | Key signal |
|---|---|---|
| Full vehicle wrap | Slight negative (-2% to -4%) | Raises suspicion that seller is hiding paint damage or prior repair underneath; not inherently bad but introduces doubt |
| Aftermarket remote start | Neutral (0%) | Too inexpensive to move the needle; buyers treat it as background noise |
| Performance intake / oil cooler / similar engine mods | Neutral (0%) | Benign and broadly acceptable. Not niche enough to restrict buyer pool. Engine mods done by previous owner are accepted as background noise by most buyers. |
| Aftermarket sound system (professionally installed) | Slight positive (+1-2%) | Broadly appreciated. |
| Aftermarket sound system (DIY / unprofessional install) | Neutral to slight negative (0% to -2%) | Buyers assume wiring issues could surface later. Install quality matters. |
| Aftermarket bumper (truck) | Context-dependent | Could indicate unreported/reported prior accident — flag as accident risk. If bumper is visibly desirable (ARB, Warn, etc.) and truck-market appropriate, slight positive (+2-3%). Unknown quality bumper = slight negative. |
| Lift kit (truck) | Neutral to slight negative (-0% to -5%) | Narrows buyer pool. Buyers who want OEM reliability and easier servicing are excluded. Alberta truck market is more receptive than most, but still a net pool reduction. Poorly done lifts are red flags. |
| Lift kit (car/SUV) | Negative (-5% to -10%) | Unusual, signals non-standard use, reduces buyer pool significantly |
| Aftermarket wheels | Neutral (-2% to +2%) | Style-dependent. Cheap aftermarket wheels are a negative. High-quality branded wheels (BBS, HRE, etc.) on appropriate vehicles can be slight positive. OEM wheels being absent/replaced raises question of what happened to originals. |
| Spray-in bed liner | Slight positive (+1% to +3%) | Buyers perceive it as protective; adds perceived value on trucks |
| Performance exhaust | Neutral to slight negative | Positive for buyer subset shopping performance; negative or neutral for reliability-focused mainstream buyer. Net effect near zero. |
| ECU tune / flash | Slight negative (-2% to -4%) | Reliability-focused buyers discount it. Also may affect warranty validity. |
| Lowering springs / coilovers | Slight negative (-3% to -5%) | Narrows pool; raises questions about how the car was driven |
| Window tint (professional) | Neutral | Minor positive for privacy/heat but too ubiquitous to move price |
| Aftermarket stereo / head unit | Neutral to slight negative | Removes OEM integration; some buyers prefer OEM look |
| Running boards / nerf bars | Slight positive (+1% to +2%) on trucks/SUVs | Practical accessory; broadly desirable |
| Tonneau cover (soft or hard) | Slight positive (+1% to +3%) on trucks | Utility accessory; most truck buyers appreciate it |

**Modification tolerance varies by vehicle type.** The same mod lands differently depending on what kind of buyer the vehicle attracts:

| Vehicle type | Mod tolerance |
|---|---|
| Jeep Wrangler / off-road capable trucks | High — buyer pool actively expects and appreciates tasteful mods |
| Performance / sports cars | Moderate — depends heavily on whether the mod is desirable to that enthusiast community |
| Pickup trucks (general) | Moderate — practical accessories positive, appearance mods neutral |
| Family SUVs / crossovers | Low — buyers want OEM reliability, mods introduce uncertainty |
| Economy sedans / hatchbacks | Low — mods narrow the already mainstream buyer pool |
| Luxury vehicles | Very low — OEM is the expectation; any mod is a negative signal |

**Important:** The engine does not hard-code these deltas permanently. Each modification type is flagged and given a starting default. As transaction outcomes accumulate, the model refines the actual market delta per modification type per vehicle class.

---

## 4. Condition Schema

### 4.1 Philosophy

Condition is the most price-sensitive variable for older/cheaper vehicles and matters progressively less as vehicle value increases. A minor dent on a $3,000 Civic is a significant percentage of the car's value; the same dent on a $60,000 truck is noise.

Self-reported condition (Facebook, Kijiji) is biased upward by motivated sellers. The engine should treat seller-stated condition as a starting point and apply a downward skepticism adjustment, then look for contradicting signals (described issues, photo evidence, listing history, price reductions) to calibrate.

### 4.2 Grading Scale

Each condition area (Exterior, Interior, Mechanical) is graded **1–5**:

| Grade | Label | Meaning |
|---|---|---|
| 5 | Exceptional | No visible wear or flaws for age; better than expected |
| 4 | Above average | Minor cosmetic wear only; no damage |
| 3 | Average | Normal wear for age and mileage; no damage |
| 2 | Below average | Visible wear but no specific damage events |
| 1 | Poor | Visible wear and age issues throughout |

**Grades 1–5 reflect wear and age, not damage.** A grade 1 car isn't damaged — it's just heavily used and showing it.

### 4.3 Damage Evaluation

**Any specific identifiable damage is recorded separately from the grade as a cost-to-repair estimate.**

When a vehicle has identifiable damage, we do not lower the grade number — we record the damage with a dollar range representing what it costs to fully correct it. This is intentionally an **overestimate** of repair cost (buyer's perspective, not lowest-possible-shop-quote). The estimate represents what a typical buyer would pay to have it fixed properly.

Damage is recorded as a list of items, each with:
- Damage type (dent, rust, tear, mechanical fault, etc.)
- Location (driver front fender, passenger seat, engine, etc.)
- Severity (minor / moderate / severe)
- Estimated repair cost range (low, high) in CAD

**Reference repair cost ranges (Alberta market, 2025):**

*Exterior:*
| Damage | Repair Range |
|---|---|
| Minor door ding / small dent (PDR candidate) | $150–350 |
| Fender dent (conventional repair) | $500–900 |
| Bumper scuff / scratch (repaint) | $400–800 |
| Bumper replacement (plastic, painted) | $900–1,800 |
| Hood replacement + paint | $1,200–2,500 |
| Windshield chip repair | $80–150 |
| Windshield replacement | $300–600 |
| Surface rust (treatment + touch-up) | $300–700 |
| Structural rust (frame/rocker panels) | $2,000–8,000+ |
| Full panel respray | $800–2,000 |

*Wheels/tires:*
| Damage | Repair Range |
|---|---|
| Curb rash on alloy wheel (1 wheel refurb) | $150–300 |
| Wheel replacement (per wheel, OEM alloy) | $300–600 |
| Full winter wheel set (cheap steel + tires) | $700–1,200 |
| Cheap winter rims (visual fix: wheel covers) | $80–150 |
| Tire replacement (per tire, mid-range) | $150–250 |

*Interior:*
| Damage | Repair Range |
|---|---|
| Seat tear / burn (repair) | $200–500 |
| Seat replacement (reupholster) | $800–1,800 |
| Carpet staining (professional clean) | $150–350 |
| Carpet replacement | $500–1,200 |
| Headliner sag / stain (replacement) | $300–700 |
| Smoke odor treatment | $200–600 |
| Dashboard crack (cosmetic repair) | $300–800 |

*Mechanical:*
| Damage | Repair Range |
|---|---|
| Spark plug replacement (full set, 4-cyl) | $200–400 |
| Spark plug replacement (full set, V8) | $400–700 |
| Brake pads + rotors (1 axle) | $400–700 |
| Battery replacement | $200–400 |
| Timing belt/chain service | $800–2,500 |
| Transmission service (fluid/filter) | $300–600 |
| Transmission rebuild/replacement | $3,000–8,000 |
| Engine misfire diagnosis + repair | $300–1,500 |
| AC recharge | $150–300 |
| Strut/shock replacement (pair) | $600–1,400 |
| Catalytic converter replacement | $1,500–4,000 |

**These ranges are starting points and will be refined as we accumulate regional data.**

### 4.4 Damage Proportionality

The impact of damage on price is not linear — it is proportional to vehicle value and buyer expectations for that class.

A $10,000 repair on a Ferrari is a minor fender incident. The same $10,000 on a $3,000 Civic exceeds the car's value and should be reflected as such. The engine calculates repair cost as a percentage of current market value and applies the delta accordingly.

Additionally, buyer sensitivity to damage history varies by vehicle class:
- High-value vehicles: buyers care significantly about any damage history, even fully repaired
- Mid-range vehicles: buyers care moderately; full repair with documentation mitigates most of the discount
- Low-value beaters: buyers accept damage as given; history report has low influence on price

### 4.5 Mileage Assessment

Mileage is not graded against age-based averages. It is compared against **current market listings of the same Year/Make/Model/Trim** to determine where this vehicle sits in the active supply.

| Band | Percentile in active market listings |
|---|---|
| Very low | Bottom 10% of mileage for active comps |
| Low | 10–30th percentile |
| Average | 30–70th percentile |
| High | 70–90th percentile |
| Very high | Top 10% of mileage for active comps |

A vehicle in the bottom 10% of mileage for its comp pool commands a meaningful premium. A vehicle in the top 10% faces a meaningful discount — buyers can easily find lower-mileage alternatives.

---

## 5. History & Documentation

### 5.1 Accident & Damage History

| Field | Values |
|---|---|
| Accident history | Clean / Minor (no structural/airbag) / Major (structural or airbag deployment) / Unknown |
| Declared total loss / Rebuilt title | Yes / No / Unknown |
| Damage amount (largest incident) | Dollar value from report |
| Damage-to-value ratio | Damage amount ÷ vehicle value at time of incident |

**Damage-to-value ratio is more meaningful than the raw dollar amount.** A $10k repair on a vehicle worth $80k at the time is a very different signal from a $10k repair on a vehicle worth $12k. The engine uses the ratio, not the raw number.

**The rule of thumb for accident impact:** A vehicle loses approximately **1/3 to 1/2 of the claim amount** in current market value, depending on vehicle class, severity, quality of repair, and how long ago it occurred. This is the starting delta before class adjustments are applied.

Example: A vehicle with a $12,000 historical claim → $4,000–$6,000 discount to current market value, adjusted for class sensitivity.

**Near-total-loss claims** (claim amount ≥ 70% of vehicle value at time of incident) are treated differently from standard accidents. The appropriate adjustment here is approximately **1/4 off the peak high end of the retail range** — meaning the ceiling of what the vehicle can sell for is compressed downward, not just the midpoint. This also triggers a "reduced buyer pool" flag — the vehicle will be harder to sell at any price, which widens the downside of the estimated range and extends expected days-on-market.

**Rebuilt title** is treated as a separate, more severe category — not just a higher claim amount. Many buyers refuse rebuilt titles entirely, dramatically narrowing the buyer pool. The engine applies a dedicated rebuilt-title discount independent of claim amount.

**Service history gap following an accident** is read as: repair was likely completed off the books (cash shop, informal repair, or private work). It is not treated as "vehicle may be unrepaired" — that would require other corroborating signals (visible damage, structural misalignment, etc.). However, off-books repair carries a trust discount because repair quality cannot be verified.

**Buyer sensitivity by class:**

| Class | History sensitivity |
|---|---|
| Under $5k | Low sensitivity. Buyers at this price point expect imperfection and prioritize immediate mechanical condition over history. Large accidents and rebuilt titles still matter, but minor incidents are largely ignored. |
| $5k–$15k | Moderate sensitivity. Accidents are factored in, claim-amount rule applies. Near-total-loss claims compress the ceiling and flag as hard-to-sell. Rebuilt titles cause significant buyer pool reduction. |
| $15k–$40k | High sensitivity. Any accident history applies a measurable discount. Buyers at this level expect clean history and will walk for alternatives. |
| $40k+ / Enthusiast | Very high sensitivity. Even minor, fully repaired accidents carry a permanent discount. Provenance matters. |

### 5.2 Odometer Integrity

Flags that suggest potential odometer rollback or inconsistency:
- Significant gaps in service history with no explanation
- Kilometre readings at service visits that don't progress consistently
- Mileage/year combination that appears implausibly low (e.g., 40k km on a 12-year-old daily driver with full dealer service history)
- Title transfers with inconsistent odometer declarations

**These are flagged as risk signals, not definitive fraud indicators.** The engine applies a confidence discount to the mileage band when rollback risk is elevated.

### 5.3 Service History Quality

| Signal | Value |
|---|---|
| Dealer-serviced throughout | Highest trust — consistent records, OEM parts assumed |
| Mixed dealer + third party | Moderate trust |
| Third party only | Acceptable — lower cost but less documentation |
| Self-serviced (owner-maintained) | Variable — depends on owner competence |
| Sparse / no history | Risk flag — unknown what was or wasn't done |

Dealer service history commands a premium especially on German/European vehicles where manufacturer service intervals are complex and skipping them has known long-term consequences.

### 5.4 Additional History Fields

| Field | Values |
|---|---|
| Number of previous owners | 1 / 2 / 3 / 4+ |
| Owner type | Personal / Fleet / Rental / Lease return |
| Safety inspection | Current CVIP (AB) / Recent (<6 months) / Expired / None |
| Lien on title | None / Present / Unknown |
| Carfax / CARCO available | Yes (attached) / Seller claims yes / No |
| Service records available | Full dealer history / Partial / None |

**Fleet/rental history signals:** Higher-than-average mileage for age, consistent service (positive), but harder use and less owner attachment to maintenance quality. Lease returns tend to be well-maintained due to inspection requirements at turn-in.

---

## 6. Delta Model

### 6.1 Structure

The engine outputs a **transaction range** centered on an adjusted price:

```
Adjusted Price = Base Median × ∏(1 + δᵢ)
```

Where each δᵢ is a percentage adjustment from one factor. Adjustments multiply rather than add, so they scale appropriately across vehicle values.

The output is a range: `[Adjusted Price × (1 - uncertainty), Adjusted Price × (1 + uncertainty)]`

Uncertainty width narrows as comp count increases and widens when data is thin.

### 6.2 Delta Categories

Deltas are grouped into categories. Within each category, individual factors contribute their percentage adjustment.

**Vehicle Attributes (what it is):**
| Factor | Typical Range | Notes |
|---|---|---|
| Color premium/discount | -5% to +3% | Model-dependent. Some colors (white, grey, black) are neutral. Unpopular colors (yellow, orange on non-sport cars) take a discount. |
| Diesel engine premium | +8% to +15% | Strong in Alberta. Work trucks especially. |
| Manual transmission | -5% to +8% | Negative for most vehicles, positive for performance/enthusiast |
| High-value options (sunroof, leather, etc.) | +1% to +4% per option | Caps at ~12% total — buyers discount redundant options |
| Cold weather package | +2% to +5% | Alberta-specific premium |
| Towing package (OEM, truck) | +3% to +6% | |
| Aftermarket modifications | -3% to +2% | Default near-neutral to negative; refines with data |

**Condition:**
| Factor | Typical Range | Notes |
|---|---|---|
| Exterior grade (5 = exceptional) | -6% to +4% | Relative to grade 3 baseline |
| Interior grade | -4% to +3% | |
| Mechanical grade | -8% to +5% | Mechanical condition carries more weight |
| Damage repair cost | Deducted at 1.2x–1.5x of repair estimate | Buyer pays a premium for the hassle, not just the repair cost |

**Mileage:**
| Band | Delta |
|---|---|
| Very low (bottom 10% of comps) | +6% to +10% |
| Low (10–30th percentile) | +2% to +5% |
| Average | 0% |
| High (70–90th percentile) | -4% to -8% |
| Very high (top 10% of comps) | -8% to -15% |

**History:**
| Factor | Delta | Notes |
|---|---|---|
| Clean history, full records | +2% to +4% | Positive signal, not just absence of negative |
| Minor accident (repaired, no structural) | -3% to -8% | Class-dependent — high for luxury/enthusiast, low for economy |
| Major accident (structural/airbag) | -12% to -25% | Permanent discount regardless of repair quality |
| Odometer integrity risk | -5% to -10% | |
| Rental/fleet history | -3% to -6% | |
| No service records | -3% to -5% | |

**Market Context:**
| Factor | Delta | Notes |
|---|---|---|
| Low comp supply (seller's market) | +3% to +8% | Fewer alternatives = seller leverage |
| High comp supply (buyer's market) | -3% to -8% | Many alternatives = buyer leverage |
| Brand/model reliability premium | +5% to +20% | Encoded from comp data — Toyota, Honda, etc. command premiums the engine learns from transaction history, not from assumptions |
| Seller urgency signals | -3% to -10% | Urgency language, price reductions, days on market |
| Days on market | -0.2% per day after 14 days | After 2 weeks, every additional day reflects soft demand |

**Location:**
See Section 7.

### 6.3 Vehicle Class Sensitivity

Percentage deltas are calibrated differently by vehicle class. A condition factor that moves a $5k economy car by 8% should behave differently on a $60k luxury truck:

| Class | Value Range | Key delta drivers |
|---|---|---|
| Economy beater | <$5k | Mechanical condition dominates. Minor accident history largely irrelevant to buyers. Rebuilt title and large claims still apply a discount, but smaller. Condition and "does it run well" matter most. |
| Mid-range used | $8k–$25k | Balanced — condition, history, options all meaningful |
| Near-new / certified | $25k–$50k | History and options dominate. Minor condition issues discounted. |
| Luxury / high-value | $50k+ | Brand reputation, history, spec-matching buyer expectations |
| Enthusiast / collector | Varies | Rarity, originality, specific options and colors, provenance |

The engine applies a **class multiplier** to each delta category. Damage history on a $4k economy car is discounted by ~60%. The same damage history on a $40k car is applied at full weight.

---

## 7. Location Factors

### 7.1 City Tier

| Tier | Characteristics | Effect |
|---|---|---|
| Major city (Calgary, Edmonton) | High buyer density, high listing volume, more competition | Lower listing prices, higher sale prices relative to asking. Buyers are informed and have options. |
| Mid-size city (Lethbridge, Red Deer, etc.) | Moderate volume, less competition | Mixed — some motivated sellers, some overpriced. |
| Rural / small town | Low buyer density, variable listing prices, buyers won't drive for a deal | Lower effective selling prices — sellers accept less because the pool is thin. Occasional outliers (someone pricing too high because they don't know the market). |

**The engine does not apply a flat city discount/premium.** It reads the actual comp pool for the area and lets the data express regional pricing. The city tier is used to interpret the comp pool (thin rural data gets less weight, wide urban data gets more).

### 7.2 Alberta-Specific Premiums

The engine is initially calibrated for the Alberta market. Factors with outsized regional relevance:
- **4WD/AWD premium:** Strong preference vs. national average. FWD vehicles take a steeper discount than in temperate markets.
- **Diesel truck premium:** Higher than national due to ranching/oilfield demand.
- **Cold weather package:** Meaningfully valued.
- **Rust premium for rust-free vehicles:** Alberta's dry climate means rust-free vehicles from BC coast or Ontario salt belt are discounted; Alberta-only vehicles command a trust premium.

---

## 8. Listing & Seller Signals

These factors are not about the vehicle — they are about the *transaction environment*. They affect price but not value.

### 8.1 Urgency — What We Can and Cannot Know

**True seller urgency is almost never visible from a listing alone.** It surfaces in conversation — a seller who answers immediately, drops price fast on the phone, or volunteers that they need to sell quickly. The engine cannot observe this directly from listing data.

What the engine *can* observe are **proxy signals** that correlate with urgency or its absence:

**Negative urgency signals (seller is motivated to move):**
- Listing price is at or below the comp median — well-priced vehicles attract high demand, creating buyer FOMO and often selling at or near asking with multiple interested parties
- Price reductions from original ask — seller has already signaled flexibility
- Days on market beyond 14 days — declining interest, seller likely becoming more negotiable
- Relist detected (same VIN appearing as a fresh listing) — previous attempt failed
- Description explicitly states "feeler ad" or "not in a rush to sell" — inverse urgency, seller will hold price

**Note on FOMO dynamics:** A well-priced listing generates more inquiries than the seller can handle. Buyers who see high demand signal (multiple messages, quick response, "I have other interested people") often pay closer to asking — or over asking — because scarcity is real. An overpriced listing gets fewer inquiries, buyers know the seller is sitting, and low-ball offers are more likely to succeed. The engine uses price-relative-to-comp as the primary demand proxy.

**Positive price signals (seller has leverage):**
- Listed significantly below comp median with no obvious reason → investigate for hidden defects, but also could be a genuine deal
- Listing explicitly states "firm" price — lower probability of successful negotiation

**Dealer selling through auction = retail exit failure.** When a dealer or known flipper lists a vehicle at auction (Regal, Openline, etc.), this is a strong signal that retail attempts have failed and the seller is willing to exit at breakeven or a slight loss for cashflow. This is distinct from a private individual using auction as their first sales channel. Detection signals: vehicle also appearing on Facebook/Kijiji from same seller, Carfax showing prior auction platform appearance, seller type identified as dealer/broker in listing.

### 8.2 Dealer vs. Private Seller

Dealer listings (franchise and independent) are consistently marked above private market pricing to:
- Anticipate negotiation (dealers expect to discount from sticker)
- Justify a dealer premium (warranty, financing, certification, reconditioning)

**Dealer asking prices are not reliable comps for private market value.** The engine applies a systematic adjustment to dealer listings before using them as data points:

| Seller type | Comp adjustment |
|---|---|
| Private seller | 0% — used as-is |
| Independent dealer | -8% to -12% — de-inflate to estimated private market equivalent |
| Franchise dealer | -10% to -15% — higher markup expectation, certification premium included |

Dealer transaction data (when actual sale price is known) is used at full weight. It's the asking prices that need adjustment, not the sale prices.

### 8.3 Other Listing Signals

| Signal | How observed | Effect |
|---|---|---|
| Price reductions | Listing history showing dropped price | Strong negative delta — seller has already accepted they won't get original ask |
| Days on market | Listing age at time of sale | Negative delta after 14 days, compounding (-0.2% per day) |
| Relist detected | Same VIN appearing as a new listing | Signals failed prior attempt; apply urgency discount |
| Photo count | Number of listing images | <5 photos = risk flag (hiding something, or unsophisticated seller) |
| Photo quality | Resolution, lighting, coverage | Very poor quality shifts risk to buyer |
| Description quality | Length, specificity, disclosed issues | Sellers who disclose issues tend to be honest; short/vague descriptions increase buyer uncertainty |
| History report attached | Carfax/CARCO linked in listing | Positive transparency signal |
| "Feeler ad" / "not in a rush" | Explicit in listing text | Inverse urgency — seller will hold price, less negotiating room |

---

## 9. Brand & Model Perception Layer

The engine does not assume any brand or model is worth more or less than another. **It learns this from actual transaction data.** A Toyota RAV4 and Lincoln MKZ in the same year and mileage will show different market values because buyers have voted with their money.

What the engine does encode:
- Reliability perception score (derived from comp data: how much premium does the market actually pay for Toyota vs. Lincoln in the same segment?)
- Cross-shopping sensitivity (is this model's price ceiling set by a competitor model that buyers consider equivalent?)
- Model-specific known issues (e.g., a specific engine generation known for timing chain failure — flagged as a mechanical risk discount)

These are not hard-coded assumptions. They are learned parameters that start as neutral and adjust as comp data accumulates.

---

## 10. Buyer Margin & Max Bid Calculation

When the engine is used by a buyer intending to resell (dealer, flipper, auction buyer), it produces a second output: **maximum buy price** given a target margin.

### 10.1 Margin Tiers (User-Configurable)

Default tiers (user can override per vehicle or globally):

| Estimated retail sell price | Minimum margin |
|---|---|
| Under $15,000 | $1,500 |
| $15,000 – $20,000 | $2,500 |
| $20,000 – $35,000 | $3,500 |
| Over $35,000 | $5,000 |

### 10.2 Max Bid Calculation

For auction purchases (e.g., Regal Auctions), the engine calculates the true cost of acquisition including all fees:

```
Max Bid = (Estimated Sell Price - Minimum Margin - Buyer Fee) / (1 + Tax Rate)
```

At Regal Auctions (Alberta):
- Buyer's fee: ~$535 for vehicles in the $10k–$15k range (refer to Regal fee schedule — scales with price)
- Tax: 5% GST applied to (purchase price + buyer's fee)

Example (the 2015 Jeep Wrangler case):
- Estimated retail sell price: $14,500
- Minimum margin: $1,500
- Buyer's fee: $535
- Tax rate: 5%
- Max bid = ($14,500 - $1,500 - $535) / 1.05 = **$11,871** (~$11,900 rounded)

---

## 11. Output Format (Per Valuation)

For each valuation, the engine produces:

```
{
  "vehicle": "2018 Toyota RAV4 XLE AWD",
  "sale_type": "retail",
  "base_median": 24500,
  "adjusted_estimate": 26100,
  "range_low": 24300,
  "range_high": 27800,
  "confidence": "medium",  // low / medium / high based on comp count
  "comp_count": 14,
  "factors": [
    {
      "factor": "mileage_band",
      "label": "Low mileage (18th percentile for active comps)",
      "delta_pct": +3.5,
      "dollar_impact": +858,
      "reasoning": "68,000 km vs. median 94,000 km in comp pool"
    },
    {
      "factor": "exterior_condition",
      "label": "Above average exterior (grade 4)",
      "delta_pct": +2.0,
      "dollar_impact": +490,
      "reasoning": "No visible damage, paint above average for age"
    },
    {
      "factor": "damage_repair",
      "label": "Windshield chip",
      "delta_pct": -0.4,
      "dollar_impact": -98,
      "repair_estimate_range": [80, 150],
      "reasoning": "Minor — buyer pays $80-150 to repair"
    },
    {
      "factor": "history",
      "label": "Clean history, full dealer records",
      "delta_pct": +2.5,
      "dollar_impact": +613,
      "reasoning": "Full Toyota dealer service history attached; clean Carfax"
    },
    {
      "factor": "market_context",
      "label": "Low supply — 4 active comps",
      "delta_pct": +4.0,
      "dollar_impact": +980,
      "reasoning": "Only 4 active RAV4 XLE AWD listings in Calgary; seller has leverage"
    }
    // ... additional factors
  ]
}
```

Every factor is visible, every dollar impact is traceable. No black box.

---

## 11. Future Enhancements (Roadmap)

### Vision Model
A computer vision layer that:
- Detects and classifies visible damage from listing photos (dents, rust, scratches, interior wear)
- Verifies trim level and options by identifying visual indicators (sunroof, wheel type, interior trim, badge)
- Flags photo quality and coverage gaps (missing interior shots, angles that hide common damage areas)
- Estimates repair cost from damage classification

This layer will sit on top of the existing schema — the damage fields it produces feed directly into Section 4.3.

### ML Refinement
Once we have 1,000+ transactions with actual outcomes vs. model predictions:
- Factor weights will shift from manually-calibrated defaults to data-derived coefficients
- Class-specific sensitivity multipliers will be calibrated per vehicle class
- Brand/model perception scores will be derived from transaction data rather than estimated
- Regional and seasonal patterns will be encoded automatically

### Seasonal Adjustments
Convertibles, AWD vehicles, and trucks have meaningful seasonal pricing patterns. Once we have 12+ months of transaction data, seasonal adjustment curves will be added per vehicle type.

---

## 12. Open Questions

1. **Competitor model cross-shopping:** How do we define which models compete? Do we build this as a static table per segment, or learn it from co-listing patterns?
2. **Damage reference table:** The repair cost ranges in Section 4.3 are estimates. These should be validated against local Alberta shop quotes and updated quarterly.
3. **Urgency detection:** True urgency is only observable in conversation, not from listing text. The engine currently uses price-relative-to-comp and listing behavior as proxies. Consider whether to add a phone/conversation annotation field for cases where urgency is confirmed manually.
4. **Modification delta refinement:** Starting defaults are conservative. As transaction outcomes accumulate, refine per modification type and per vehicle class from actual data.
