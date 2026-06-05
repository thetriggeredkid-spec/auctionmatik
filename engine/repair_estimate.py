"""
Repair Estimator
Turns a vision `repair_components` list into a rough repair quote (CAD), used by
the salvage / repair-project path (Mode B) and the Recommendation Engine.

Costs are first-pass Alberta installed (parts + labour) ranges — TUNE with
Charles's shop experience and real quotes. A protection buffer (default +20%,
per Charles) is added on top because hidden damage is the norm on wrecks.

estimate_repair(components, buffer=0.20) ->
{
    "line_items":     [{component, action, severity, matched, contingent,
                        cost_low, cost_high}],
    "unmatched":      [component, ...],          # need a manual quote
    "confirmed_low":  int, "confirmed_high":  int,   # confirmed-damage costs
    "contingent_low": int, "contingent_high": int,   # "inspect" teardown reserve
    "subtotal_low":   int, "subtotal_high":   int,   # confirmed + contingent
    "buffer_pct":     float,
    "total_low":      int, "total_high": int, "total_mid": int,  # CAD, buffer applied
}
"""

DEFAULT_BUFFER = 0.20      # +20% protection for hidden/under-estimated damage
CONTINGENT_FACTOR = 0.30   # "inspect / replace if bent" items: counted at 30% (expected reserve, not full cost). Set 1.0 for worst-case.

# Repair-cost profile (Charles): middle ground — DIY rates on small bolt-on jobs,
# full shop/OEM on big/structural ones. We split by repair size.
SMALL_REPAIR_THRESHOLD = 800   # installed-cost midpoint at/under this = treat as DIY
DIY_FACTOR = 0.65              # DIY saves ~35% (labour) on small jobs; large jobs stay shop rate (1.0)

# component keyword -> (installed_low, installed_high) in CAD dollars (parts + labour)
COMPONENT_COSTS = {
    # Body panels
    "front bumper":      (400, 1200),
    "rear bumper":       (400, 1200),
    "hood":              (450, 1500),
    "fender":            (350, 1000),
    "door":              (500, 1800),
    "quarter panel":     (700, 2200),
    "grille":            (150, 700),
    "underbody":         (100, 450),   # skid plate / cover / splash shield
    "rocker":            (400, 1200),
    "roof":              (800, 2500),
    "tailgate":          (500, 1600),
    "mirror":            (150, 600),
    # Lighting / glass
    "headlight":         (200, 1100),  # LED/adaptive at high end
    "tail light":        (150, 500),
    "fog light":         (100, 350),
    "windshield":        (300, 700),
    "window":            (200, 600),
    # Cooling / engine bay
    "radiator":          (400, 1100),
    "condenser":         (350, 900),
    "cooling fan":       (200, 700),
    "fan":               (200, 700),
    "hose":              (80, 350),
    "intercooler":       (400, 1200),
    # Suspension / steering / wheels
    "suspension":        (600, 2200),  # corner: strut/control arm/knuckle
    "strut":             (300, 900),
    "control arm":       (250, 800),
    "tie rod":           (150, 500),
    "connection rod":    (150, 500),
    "axle":              (400, 1300),
    "cv":                (250, 800),
    "wheel":             (150, 700),   # rim
    "rim":               (150, 700),
    "tire":              (150, 400),
    # Safety / mechanical
    "airbag":            (800, 2200),
    "exhaust":           (150, 1500),
    "engine":            (2500, 7000),
    "transmission":      (2000, 5500),
    # Refinish (paint a panel)
    "paint":             (300, 800),
    "refinish":          (300, 800),
}

# Fallback when a listed component matches nothing in the table.
_OTHER_BODY = (300, 1000)


def _match_cost(component: str) -> tuple[tuple[int, int], bool]:
    """Return ((low, high), matched?) for a free-text component name."""
    name = (component or "").lower()
    # longest keyword first so "front bumper" beats "bumper"-style partials
    for key in sorted(COMPONENT_COSTS, key=len, reverse=True):
        if key in name:
            return COMPONENT_COSTS[key], True
    return _OTHER_BODY, False


def _pick(cost: tuple[int, int], action: str, severity: str) -> tuple[int, int]:
    """Narrow a (low, high) range based on action/severity."""
    low, high = cost
    action = (action or "").lower()
    severity = (severity or "moderate").lower()
    mid = int((low + high) / 2)
    if action == "replace" or severity == "severe":
        return (mid, high)                  # bias to the top of the range
    if action in ("repair", "refinish") or severity == "minor":
        return (low, mid)                   # bias to the bottom of the range
    return (low, int(high * 0.75))          # moderate: trim the top a bit


def _is_contingent(action: str) -> bool:
    """'inspect ...' items aren't confirmed damage — they're a teardown reserve, not full cost."""
    return "inspect" in (action or "").lower()


def estimate_repair(components: list[dict], buffer: float = DEFAULT_BUFFER,
                    small_factor: float = DIY_FACTOR, large_factor: float = 1.0,
                    contingent_factor: float = CONTINGENT_FACTOR) -> dict:
    """
    small_factor: cost multiplier for small bolt-on jobs (<= SMALL_REPAIR_THRESHOLD).
    large_factor: cost multiplier for big/structural jobs (used-parts/DIY profiles < 1.0).
    """
    line_items, unmatched = [], []
    confirmed_low = confirmed_high = 0
    contingent_low = contingent_high = 0
    for comp in components or []:
        if isinstance(comp, dict):
            name = comp.get("component")
            action = comp.get("action", "")
            severity = comp.get("severity", "moderate")
        else:
            name = str(comp)
            action = ""
            severity = "moderate"

        base_cost, matched = _match_cost(name)
        low, high = _pick(base_cost, action, severity)

        # Sourcing/labour profile: small jobs at DIY rate, large/structural at shop/OEM
        # (or used-parts rate if the profile sets large_factor < 1.0).
        factor = small_factor if (low + high) / 2 <= SMALL_REPAIR_THRESHOLD else large_factor
        low, high = int(low * factor), int(high * factor)

        # "Inspect" items are a teardown reserve, not confirmed damage: count a fraction.
        contingent = _is_contingent(action)
        if contingent:
            low, high = int(low * contingent_factor), int(high * contingent_factor)
            contingent_low += low
            contingent_high += high
        else:
            confirmed_low += low
            confirmed_high += high

        if not matched:
            unmatched.append(name)
        line_items.append({"component": name, "action": action, "severity": severity,
                           "matched": matched, "contingent": contingent,
                           "cost_low": low, "cost_high": high})

    sub_low = confirmed_low + contingent_low
    sub_high = confirmed_high + contingent_high
    total_low = int(sub_low * (1 + buffer))
    total_high = int(sub_high * (1 + buffer))
    return {
        "line_items": line_items,
        "unmatched": unmatched,
        "confirmed_low": confirmed_low, "confirmed_high": confirmed_high,
        "contingent_low": contingent_low, "contingent_high": contingent_high,
        "subtotal_low": sub_low,
        "subtotal_high": sub_high,
        "buffer_pct": buffer,
        "total_low": total_low,
        "total_high": total_high,
        "total_mid": (total_low + total_high) // 2,
    }
