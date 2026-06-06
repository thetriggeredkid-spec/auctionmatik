"""
Auctionmatic dashboard server.

Serves the hi-fi dashboard (recreated from the Claude Design handoff —
"Auctionmatic Detail.html": The Lane + the Verdict Card) and wires it to the
live engine.

    pip install -r requirements.txt
    python3 -m dashboard.server          # http://127.0.0.1:8080

Endpoints:
    GET /                       → the dashboard SPA
    GET /api/health             → {ok, db}
    GET /api/lane?limit=        → deterministic fast pass over recent listings
    GET /api/evaluate?contract=&mode=triage|deep&profile=charles|mechanic
                                → full design-shaped vehicle (AI when mode given)
"""

import os
import time
from flask import Flask, jsonify, request, send_from_directory

from db.connection import get_conn

STATIC = os.path.join(os.path.dirname(__file__), "static")
app = Flask(__name__, static_folder=STATIC, static_url_path="")

# Apply saved settings (edited profiles / margins / fees / GST / toggles) at startup.
try:
    from engine import settings as _settings

    _c = get_conn()
    try:
        _settings.apply_from_db(_c)
    finally:
        _c.close()
except Exception as _e:  # noqa: BLE001
    print(f"[settings] startup apply skipped: {_e}")


_INDEX_CACHE = None


@app.get("/")
def index():
    # Serve the entry page from memory so a transient FS/permission hiccup can never
    # 500 the only way into the app.
    global _INDEX_CACHE
    try:
        if _INDEX_CACHE is None:
            with open(os.path.join(STATIC, "index.html"), encoding="utf-8") as f:
                _INDEX_CACHE = f.read()
        from flask import Response

        return Response(_INDEX_CACHE, mimetype="text/html")
    except Exception:  # noqa: BLE001
        return send_from_directory(STATIC, "index.html")


@app.get("/api/health")
def health():
    db_ok = True
    try:
        conn = get_conn()
        conn.close()
    except Exception:  # noqa: BLE001
        db_ok = False
    return jsonify(ok=True, db=db_ok, ai=bool(os.getenv("ANTHROPIC_API_KEY")))


@app.get("/api/sales")
def api_sales():
    """Index of upcoming sales (Tuesday Timed Auctions + Saturday Super Sales)."""
    from dashboard.mapper import sales

    conn = get_conn()
    try:
        return jsonify(sales=sales(conn))
    finally:
        conn.close()


@app.get("/api/sale")
def api_sale():
    """All vehicles in one sale (ordered by lot); the first `screen` are scored."""
    from dashboard.mapper import sale_vehicles

    date_str = request.args.get("date")
    if not date_str:
        return jsonify(error="date required"), 400
    profile = request.args.get("profile", "charles")
    raw_screen = request.args.get("screen", "60")
    screen_limit = (
        100000
        if raw_screen == "all"
        else max(int(raw_screen) if raw_screen.isdigit() else 60, 0)
    )
    conn = get_conn()
    try:
        sale = sale_vehicles(conn, date_str, screen_limit=screen_limit, profile=profile)
    finally:
        conn.close()
    if not sale:
        return jsonify(error=f"no Tuesday/Saturday sale on {date_str}"), 404
    return jsonify(sale=sale)


@app.get("/api/fetch_comps")
def api_fetch_comps():
    """Live-scrape Facebook Marketplace comps for one vehicle, then re-evaluate.
    Slow (~1–2 min) and uses Apify credits — triggered explicitly from the UI."""
    from dashboard.mapper import fetch_comps

    contract = request.args.get("contract")
    if not contract:
        return jsonify(error="contract required"), 400
    if not os.getenv("APIFY_TOKEN"):
        return (
            jsonify(error="APIFY_TOKEN not set — add it to .env to scan for comps"),
            400,
        )
    profile = request.args.get("profile", "charles")
    conn = get_conn()
    try:
        result = fetch_comps(conn, contract, profile=profile)
    except Exception as e:  # noqa: BLE001
        return jsonify(error=str(e)), 500
    finally:
        conn.close()
    if not result:
        return jsonify(error=f"contract {contract} not found in regal_listings"), 404
    return jsonify(**result)


@app.get("/api/evaluate")
def api_evaluate():
    from dashboard.mapper import evaluate

    contract = request.args.get("contract")
    if not contract:
        return jsonify(error="contract required"), 400
    mode = request.args.get("mode", "triage")
    profile = request.args.get("profile", "charles")
    ai_mode = mode if mode in ("triage", "deep") else None
    conn = get_conn()
    try:
        vehicle = evaluate(conn, contract, profile=profile, ai_mode=ai_mode)
    except Exception as e:  # noqa: BLE001
        return jsonify(error=str(e)), 500
    finally:
        conn.close()
    if not vehicle:
        return jsonify(error=f"contract {contract} not found in regal_listings"), 404
    return jsonify(vehicle=vehicle)


@app.get("/api/evaluate_stream")
def api_evaluate_stream():
    """Server-Sent Events: stream stage progress during a (deep) evaluation, then the result."""
    import json as _json
    import queue
    import threading
    from flask import Response, stream_with_context
    from dashboard.mapper import evaluate

    contract = request.args.get("contract")
    mode = request.args.get("mode", "deep")
    profile = request.args.get("profile", "charles")
    force = request.args.get("force") in (
        "1",
        "true",
        "yes",
    )  # explicit re-appraise → recompute
    ai_mode = mode if mode in ("triage", "deep") else None
    if not contract:
        return jsonify(error="contract required"), 400

    q: "queue.Queue" = queue.Queue()

    def work():
        conn = get_conn()
        try:
            v = evaluate(
                conn,
                contract,
                profile=profile,
                ai_mode=ai_mode,
                use_deep_cache=not force,
                progress=lambda stage: q.put(("progress", stage)),
            )
            q.put(("result", v))
        except Exception as e:  # noqa: BLE001
            q.put(("error", str(e)))
        finally:
            conn.close()
            q.put(("__done__", None))

    @stream_with_context
    def gen():
        threading.Thread(target=work, daemon=True).start()
        while True:
            kind, payload = q.get()
            if kind == "__done__":
                break
            ev = (
                "failed" if kind == "error" else kind
            )  # avoid EventSource's reserved "error"
            yield f"event: {ev}\ndata: {_json.dumps(payload)}\n\n"

    return Response(
        gen(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.post("/api/feedback")
def api_feedback():
    """Record an operator correction / actual sale price for a contract."""
    from dashboard.mapper import save_feedback

    data = request.get_json(silent=True) or {}
    contract = data.get("contract")
    if not contract:
        return jsonify(error="contract required"), 400
    conn = get_conn()
    try:
        fb = save_feedback(conn, contract, data)
    finally:
        conn.close()
    return jsonify(feedback=fb)


@app.get("/api/personal_sales")
def api_personal_sales_list():
    """Your hand-entered past sales (realized retail comps)."""
    from dashboard.mapper import list_personal_sales

    conn = get_conn()
    try:
        return jsonify(sales=list_personal_sales(conn))
    finally:
        conn.close()


@app.post("/api/personal_sales")
def api_personal_sales_add():
    from dashboard.mapper import add_personal_sale

    data = request.get_json(silent=True) or {}
    conn = get_conn()
    try:
        sale = add_personal_sale(conn, data)
    finally:
        conn.close()
    if not sale:
        return jsonify(error="sale price required"), 400
    return jsonify(sale=sale)


@app.delete("/api/personal_sales/<int:sale_id>")
def api_personal_sales_delete(sale_id):
    from dashboard.mapper import delete_personal_sale

    conn = get_conn()
    try:
        delete_personal_sale(conn, sale_id)
    finally:
        conn.close()
    return jsonify(ok=True)


@app.post("/api/vision_pull")
def api_vision_pull():
    """Enrich the listing's photos + read them with the vision model, then re-evaluate."""
    from dashboard.mapper import run_vision

    data = request.get_json(silent=True) or {}
    contract = data.get("contract")
    if not contract:
        return jsonify(error="contract required"), 400
    profile = data.get("profile", "charles")
    conn = get_conn()
    try:
        vehicle = run_vision(conn, contract, profile=profile)
    except Exception as e:  # noqa: BLE001
        return jsonify(error=str(e)), 500
    finally:
        conn.close()
    if not vehicle:
        return jsonify(error=f"contract {contract} not found"), 404
    return jsonify(vehicle=vehicle)


@app.post("/api/carfax")
def api_carfax():
    """Save operator-entered Carfax facts for a contract and re-evaluate with them."""
    from dashboard.mapper import save_carfax

    data = request.get_json(silent=True) or {}
    contract = data.get("contract")
    if not contract:
        return jsonify(error="contract required"), 400
    profile = data.get("profile", "charles")
    conn = get_conn()
    try:
        vehicle = save_carfax(conn, contract, data, profile=profile)
    finally:
        conn.close()
    if not vehicle:
        return jsonify(error=f"contract {contract} not found"), 404
    return jsonify(vehicle=vehicle)


@app.post("/api/carfax_pull")
def api_carfax_pull():
    """Auto-pull the Carfax for one vehicle via the local headful browser agent,
    then re-evaluate. Requires a real browser on the host (run the dashboard locally).
    """
    from dashboard.mapper import pull_carfax

    data = request.get_json(silent=True) or {}
    contract = data.get("contract")
    if not contract:
        return jsonify(error="contract required"), 400
    profile = data.get("profile", "charles")
    conn = get_conn()
    try:
        vehicle = pull_carfax(conn, contract, profile=profile)
    except Exception as e:  # noqa: BLE001
        return jsonify(error=str(e)), 500
    finally:
        conn.close()
    if not vehicle:
        return jsonify(error=f"contract {contract} not found"), 404
    return jsonify(vehicle=vehicle)


import threading as _threading

_PREP_JOBS: dict = (
    {}
)  # date -> {status, total, done, current, results, started, cancel}


@app.post("/api/prep_sale")
def api_prep_sale():
    """Start a background batch-enrichment job over the first N (by lot) of a sale.
    Default bundle: photos + vision. Carfax / comps are opt-in (slow / costly)."""
    from dashboard.mapper import sale_contracts, prep_one

    data = request.get_json(silent=True) or {}
    date_str = data.get("date")
    if not date_str:
        return jsonify(error="date required"), 400
    from engine import settings as _st

    profile = data.get("profile", "charles")
    default_limit = _st.engine_flag("prep_default_limit", 25)
    limit = min(max(int(data.get("limit", default_limit)), 1), 200)
    do_vision = data.get("vision", True)
    do_carfax = bool(data.get("carfax", False))
    do_comps = bool(data.get("comps", False))

    job = _PREP_JOBS.get(date_str)
    if job and job["status"] == "running":
        return (
            jsonify(
                error="a prep job is already running for this sale", job=_job_view(job)
            ),
            409,
        )

    conn = get_conn()
    try:
        contracts = sale_contracts(conn, date_str, limit)
    finally:
        conn.close()
    if not contracts:
        return jsonify(error=f"no Tuesday/Saturday sale on {date_str}"), 404

    job = {
        "status": "running",
        "total": len(contracts),
        "done": 0,
        "current": None,
        "results": [],
        "started": time.time(),
        "cancel": False,
        "date": date_str,
    }
    _PREP_JOBS[date_str] = job

    def run():
        conn2 = get_conn()
        try:
            for c in contracts:
                if job["cancel"]:
                    job["status"] = "cancelled"
                    break
                job["current"] = c
                try:
                    st = prep_one(
                        conn2,
                        c,
                        vision=do_vision,
                        carfax=do_carfax,
                        comps=do_comps,
                        profile=profile,
                    )
                except Exception as e:  # noqa: BLE001
                    st = {"contract": c, "error": str(e)}
                job["results"].append(st)
                job["done"] += 1
            if job["status"] == "running":
                job["status"] = "done"
        finally:
            job["current"] = None
            conn2.close()

    _threading.Thread(target=run, daemon=True).start()
    return jsonify(job=_job_view(job))


def _job_view(job: dict) -> dict:
    return {
        "status": job["status"],
        "total": job["total"],
        "done": job["done"],
        "current": job["current"],
        "date": job["date"],
        "elapsed": round(time.time() - job["started"], 1),
        "results": job["results"][-12:],
    }


@app.get("/api/prep_status")
def api_prep_status():
    date_str = request.args.get("date")
    job = _PREP_JOBS.get(date_str)
    if not job:
        return jsonify(status="idle")
    return jsonify(job=_job_view(job))


@app.post("/api/prep_cancel")
def api_prep_cancel():
    data = request.get_json(silent=True) or {}
    job = _PREP_JOBS.get(data.get("date"))
    if job and job["status"] == "running":
        job["cancel"] = True
        return jsonify(ok=True)
    return jsonify(ok=False)


@app.get("/api/settings")
def api_settings_get():
    from engine import settings as st

    conn = get_conn()
    try:
        return jsonify(settings=st.load(conn))
    finally:
        conn.close()


@app.post("/api/settings")
def api_settings_post():
    from engine import settings as st

    patch = request.get_json(silent=True) or {}
    conn = get_conn()
    try:
        merged = st.save(conn, patch)
        from dashboard.mapper import _DET_CACHE, clear_all_deep_cache

        _DET_CACHE.clear()  # pricing config changed → re-screen fresh
        clear_all_deep_cache(conn)  # margins/profiles changed → all deep results stale
    except Exception as e:  # noqa: BLE001
        return jsonify(error=str(e)), 400
    finally:
        conn.close()
    return jsonify(settings=merged)


@app.post("/api/settings/reset")
def api_settings_reset():
    from engine import settings as st

    conn = get_conn()
    try:
        merged = st.reset(conn)
        from dashboard.mapper import _DET_CACHE, clear_all_deep_cache

        _DET_CACHE.clear()
        clear_all_deep_cache(conn)
    finally:
        conn.close()
    return jsonify(settings=merged)


@app.get("/api/calibration")
def api_calibration():
    """Engine-vs-reality calibration stats from recorded operator corrections."""
    from dashboard.mapper import calibration

    conn = get_conn()
    try:
        return jsonify(calibration(conn))
    finally:
        conn.close()


@app.get("/api/calibration.csv")
def api_calibration_csv():
    from flask import Response
    from dashboard.mapper import calibration_csv

    conn = get_conn()
    try:
        csv_text = calibration_csv(conn)
    finally:
        conn.close()
    return Response(
        csv_text,
        mimetype="text/csv",
        headers={
            "Content-Disposition": "attachment; filename=auctionmatik_calibration.csv"
        },
    )


@app.post("/api/overrides")
def api_overrides():
    """Save operator input corrections (trim/cab/km/grades/declarations) and re-evaluate."""
    from dashboard.mapper import save_overrides

    data = request.get_json(silent=True) or {}
    contract = data.get("contract")
    if not contract:
        return jsonify(error="contract required"), 400
    profile = data.get("profile", "charles")
    overrides = data.get("overrides") or {}
    conn = get_conn()
    try:
        vehicle = save_overrides(conn, contract, overrides, profile=profile)
    except Exception as e:  # noqa: BLE001
        return jsonify(error=str(e)), 500
    finally:
        conn.close()
    if not vehicle:
        return jsonify(error=f"contract {contract} not found"), 404
    return jsonify(vehicle=vehicle)


@app.post("/api/comp_flag")
def api_comp_flag():
    """Flag a retail comp as bad (excluded from future anchors) or good."""
    from dashboard.mapper import flag_comp

    data = request.get_json(silent=True) or {}
    external_id = data.get("externalId")
    if not external_id:
        return jsonify(error="externalId required"), 400
    conn = get_conn()
    try:
        flag_comp(
            conn,
            external_id,
            data.get("contract"),
            status=data.get("status", "bad"),
            reason=data.get("reason"),
        )
    finally:
        conn.close()
    return jsonify(ok=True)


if __name__ == "__main__":
    port = int(os.getenv("DASHBOARD_PORT", "8080"))
    print(f"Auctionmatic dashboard → http://127.0.0.1:{port}")
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)
