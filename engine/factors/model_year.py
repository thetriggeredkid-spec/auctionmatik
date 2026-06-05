"""
Model Year Intelligence Factor
Applies value adjustments for:
  1. Generation gap — a 2018 RAV4 is NOT comparable to a 2019 RAV4 (different gen)
  2. Known reliability issues — e.g. 2014-2016 Nissan Rogue CVT discount

Data source: data/model_year_intel.json (maintained by Charles)

Returns {delta_pct, dollar_impact, reasoning} like all factor modules.
Also exposes get_generation() and get_cross_gen_penalty() for use in comps.py
to adjust similarity scoring across generation boundaries.
"""

import os
import json

_INTEL_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "data", "model_year_intel.json")
_intel_cache = None


def _load_intel() -> dict:
    global _intel_cache
    if _intel_cache is None:
        try:
            with open(_INTEL_PATH, "r") as f:
                data = json.load(f)
                # Remove metadata key
                _intel_cache = {k: v for k, v in data.items() if not k.startswith("_")}
        except (FileNotFoundError, json.JSONDecodeError):
            _intel_cache = {}
    return _intel_cache


def _lookup_vehicle(make: str, model: str) -> dict | None:
    """Look up a vehicle in the intel database. Returns entry or None."""
    intel = _load_intel()
    key = f"{(make or '').upper().strip()} {(model or '').upper().strip()}"
    return intel.get(key)


def get_generation(make: str, model: str, year: int) -> dict | None:
    """
    Return the generation dict for a given make/model/year.
    Returns None if not in database or year not in any known generation.
    """
    entry = _lookup_vehicle(make, model)
    if not entry:
        return None
    for gen in entry.get("generations", []):
        start, end = gen["years"][0], gen["years"][-1]
        if start <= year <= end:
            return gen
    return None


def get_cross_gen_comp_penalty(make: str, model: str, subject_year: int, comp_year: int) -> float:
    """
    Return a similarity penalty (0.0 to 1.0, where 1.0 = full deduction) when
    a comp is from a different generation than the subject vehicle.

    Used in comps.py to downweight cross-generation comps in similarity scoring.
    Returns 0.0 if same generation or no intel available.
    """
    entry = _lookup_vehicle(make, model)
    if not entry:
        return 0.0

    subject_gen = get_generation(make, model, subject_year)
    comp_gen = get_generation(make, model, comp_year)

    if subject_gen is None or comp_gen is None:
        return 0.0

    if subject_gen.get("gen") == comp_gen.get("gen"):
        return 0.0

    # Penalty is the cross_gen_penalty_pct from the database (as a positive fraction)
    penalty_pct = abs(entry.get("cross_gen_penalty_pct", 0))
    return penalty_pct / 100.0


def _get_known_issue_delta(entry: dict, year: int) -> tuple[float, list[str]]:
    """
    Find the most severe known issue for the given year.
    Returns (delta_pct, [reasoning strings]).
    """
    issues = entry.get("known_issues", [])
    if not issues:
        return 0.0, []

    applicable = []
    for issue in issues:
        start, end = issue["years"][0], issue["years"][-1]
        if start <= year <= end:
            applicable.append(issue)

    if not applicable:
        return 0.0, []

    # Apply the most severe issue (don't stack — the severe one dominates)
    # In practice most vehicles only have one issue per year range
    worst = min(applicable, key=lambda x: x["value_impact_pct"])
    delta = worst["value_impact_pct"]
    reasons = [f"{i['issue']} ({i['severity']} severity, {i['value_impact_pct']:+.0f}%): {i['detail']}"
               for i in applicable]

    return delta, reasons


def evaluate(vehicle: dict, comp_pool: dict, base_median: int) -> dict:
    """
    Standard factor interface.

    Returns:
        {
            factor: "model_year",
            label: str,
            delta_pct: float,
            dollar_impact: int,
            reasoning: str,
            flags: [],
            generation: dict | None,
            known_issues: [str],
        }
    """
    make = vehicle.get("make", "")
    model = vehicle.get("model", "")
    year = vehicle.get("year")

    entry = _lookup_vehicle(make, model)

    if not entry or not year:
        return {
            "factor": "model_year",
            "label": "Model Year",
            "delta_pct": 0.0,
            "dollar_impact": 0,
            "reasoning": "No model year intelligence available for this vehicle — no adjustment applied.",
            "flags": [],
            "generation": None,
            "known_issues": [],
            "sub_factors": [],
        }

    sub_factors = []
    total_delta = 0.0
    reasoning_parts = []
    flags = []

    # ── Check generation ─────────────────────────────────────────────────────
    gen = get_generation(make, model, year)
    gen_name = gen.get("name", f"Gen {gen.get('gen')}") if gen else "unknown"
    gen_years = f"{gen['years'][0]}–{gen['years'][-1]}" if gen else ""
    gen_notes = gen.get("notes", "") if gen else ""

    # Check if comp pool is heavily cross-generational
    cross_gen_comps = 0
    total_comps = len(comp_pool.get("comp_list", []))
    for comp in comp_pool.get("comp_list", []):
        comp_year = comp.get("year")
        if comp_year and get_generation(make, model, comp_year) != gen:
            cross_gen_comps += 1

    if gen:
        reasoning_parts.append(
            f"Vehicle is {gen_name} ({gen_years}). "
            + (f"{gen_notes} " if gen_notes else "")
        )
        if cross_gen_comps > 0 and total_comps > 0:
            pct_cross = cross_gen_comps / total_comps * 100
            reasoning_parts.append(
                f"{cross_gen_comps}/{total_comps} comps ({pct_cross:.0f}%) are from a different generation "
                f"— those comp prices are less representative and downweighted in similarity scoring."
            )

    # ── Check known reliability issues ───────────────────────────────────────
    issue_delta, issue_reasons = _get_known_issue_delta(entry, year)

    if issue_delta != 0.0:
        total_delta += issue_delta
        reasoning_parts.extend(issue_reasons)
        dollar = int(base_median * issue_delta / 100)
        sub_factors.append({
            "factor": "model_year_reliability",
            "label": "Known Reliability Issue",
            "delta_pct": issue_delta,
            "dollar_impact": dollar,
            "reasoning": "; ".join(issue_reasons),
        })
        flags.append({
            "code": "KNOWN_RELIABILITY_ISSUE",
            "severity": "warning",
            "message": f"{year} {make} {model}: " + issue_reasons[0][:120],
        })

    dollar_impact = int(base_median * total_delta / 100)

    return {
        "factor": "model_year",
        "label": "Model Year / Generation",
        "delta_pct": total_delta,
        "dollar_impact": dollar_impact,
        "reasoning": " ".join(reasoning_parts) if reasoning_parts else "No model year adjustments for this vehicle.",
        "flags": flags,
        "generation": gen,
        "known_issues": issue_reasons,
        "sub_factors": sub_factors,
    }
