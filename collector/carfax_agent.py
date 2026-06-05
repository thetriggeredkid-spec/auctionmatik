"""
Carfax Agent (local / headful)
The Regal Carfax link redirects to a reCAPTCHA-gated CARFAX Canada SPA, so it
can't be scraped headless. This agent renders it in a REAL browser (your logged-in
Chrome, where reCAPTCHA v3 passes naturally), screenshots the report, and reads it
with the vision model — no brittle DOM selectors, robust to layout changes.

WHY vision-on-screenshot (not DOM scraping): the report is a third-party SPA with
changing markup + reCAPTCHA; a screenshot + vision read is the most durable approach
and reuses our existing vision pipeline.

RUN THIS ON YOUR OWN MACHINE (not the sandbox) — it needs a visible browser:
    pip install playwright
    playwright install chromium          # or rely on channel="chrome" (your installed Chrome)
    python3 -m collector.carfax_agent --contract 37316

It stores structured history into regal_listings.carfax_report and removes the
"unknown service history" guess from the valuation.
"""

import os
import sys
import json
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from db.connection import get_conn, get_cursor

CARFAX_PROMPT = """This is a CARFAX Canada Vehicle History Report screenshot. Extract the facts you can clearly read, as JSON:
{
  "accidents_reported": int or null,
  "total_claims_cad": number or null,
  "service_records_count": int or null,
  "service_detail": "dealer | independent | mixed | none | unknown",
  "registration_history": ["province/region with rough dates if shown"],
  "branding": "none | rebuilt | salvage | stolen | flood | unknown",
  "odometer_consistent": true/false/null,
  "last_reported_km": int or null,
  "notes": "anything else a buyer should know",
  "confidence": "high|medium|low"
}
Only report what is visible. Use null/"unknown" when unsure — do not invent."""


def _carfax_url(regal_id: str, vin: str) -> str:
    return f"https://regalauctions.com/carfax.php?id={regal_id}&vin={vin}&loc=declarations"


def _render_screenshots(url: str, headful: bool = False, out_dir: str = "data/carfax",
                        max_tiles: int = 8) -> list[str]:
    """Render the report and capture it as viewport-sized TILES (scrolling down).

    A full-page screenshot of a long Carfax report exceeds Anthropic's 8000px image
    limit, so we capture bounded viewport tiles instead. Runs in the BACKGROUND
    (headless) by default — no popup. channel="chrome" uses your installed Chrome.
    """
    from playwright.sync_api import sync_playwright
    os.makedirs(out_dir, exist_ok=True)
    vw, vh = 1280, 1500
    shots = []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=not headful,
                                    args=["--disable-blink-features=AutomationControlled"])
        page = browser.new_context(viewport={"width": vw, "height": vh}).new_page()
        page.goto(url, wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(6000)  # let reCAPTCHA + SPA settle and the report render
        total = page.evaluate("Math.max(document.body.scrollHeight, document.documentElement.scrollHeight)")
        y = 0
        for i in range(max_tiles):
            page.evaluate(f"window.scrollTo(0, {y})")
            page.wait_for_timeout(350)
            path = os.path.join(out_dir, f"carfax_{i}.png")
            page.screenshot(path=path)        # viewport-only → dimensions stay well under 8000px
            shots.append(path)
            y += vh
            if y >= total:
                break
        browser.close()
    return shots


def _read_with_vision(screenshot_paths: list[str], vehicle_summary: str = "") -> dict:
    import base64
    import anthropic
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")
    from engine.vision import VISION_MODEL  # reuse the configured triage model
    content = [{"type": "text", "text": f"Vehicle: {vehicle_summary}"}] if vehicle_summary else []
    for path in screenshot_paths:
        with open(path, "rb") as f:
            content.append({"type": "image", "source": {"type": "base64",
                            "media_type": "image/png",
                            "data": base64.standard_b64encode(f.read()).decode("ascii")}})
    content.append({"type": "text", "text": CARFAX_PROMPT})
    client = anthropic.Anthropic(api_key=key)
    resp = client.messages.create(model=VISION_MODEL, max_tokens=900,
                                  messages=[{"role": "user", "content": content}])
    raw = resp.content[0].text
    import re
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    return json.loads(m.group()) if m else {"error": "parse_failed", "raw": raw[:500]}


def fetch_carfax(contract: str, table: str = "regal_listings", headful: bool | None = None) -> dict:
    # Default: background/headless (no popup). Force a visible window with
    # DASHBOARD_CARFAX_HEADFUL=1 if a reCAPTCHA challenge ever needs a human.
    if headful is None:
        headful = os.getenv("DASHBOARD_CARFAX_HEADFUL", "0").lower() in ("1", "true", "yes")
    conn = get_conn()
    cur = get_cursor(conn)
    cur.execute(f"SELECT regal_id, vin, year, make, model FROM {table} WHERE contract = %s LIMIT 1", (contract,))
    row = cur.fetchone()
    if not row:
        raise ValueError(f"contract {contract} not found in {table}")
    url = _carfax_url(row["regal_id"], row["vin"])
    summary = f"{row['year']} {row['make']} {row['model']}"
    print(f"Rendering Carfax for {summary} (contract {contract})\n  {url}")
    shots = _render_screenshots(url, headful=headful)
    print(f"  captured {len(shots)} screenshot(s); reading with vision...")
    report = _read_with_vision(shots, summary)
    cur.execute(f"UPDATE {table} SET carfax_report = %s WHERE contract = %s", (json.dumps(report), contract))
    conn.commit()
    cur.close(); conn.close()
    return report


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Render + read a Regal Carfax report (run locally, headful)")
    ap.add_argument("--contract", required=True)
    ap.add_argument("--table", choices=["regal_listings", "regal_sold"], default="regal_listings")
    ap.add_argument("--show", action="store_true", help="Show the browser window (default: background/headless)")
    args = ap.parse_args()
    result = fetch_carfax(args.contract, table=args.table, headful=args.show)
    print("\nCARFAX report:")
    print(json.dumps(result, indent=2))
