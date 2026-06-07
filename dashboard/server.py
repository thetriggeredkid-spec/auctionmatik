"""
Auctionmatic dashboard server.

Serves the Vite + React + TypeScript + shadcn SPA (built to dashboard/web/dist;
falls back to the legacy dashboard/static if dist is absent) and wires it to the
live engine via the JSON /api.

    pip install -r requirements.txt
    cd dashboard/web && npm run build    # build the SPA (first run / after UI changes)
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

# Serve the built Vite + shadcn SPA (dashboard/web/dist) in production. If it hasn't
# been built yet, fall back to the legacy buildless dashboard (dashboard/static) so the
# server never comes up blank. Build the new UI with: cd dashboard/web && npm run build
_WEB_DIST = os.path.join(os.path.dirname(__file__), "web", "dist")
_LEGACY_STATIC = os.path.join(os.path.dirname(__file__), "static")
STATIC = (
    _WEB_DIST
    if os.path.exists(os.path.join(_WEB_DIST, "index.html"))
    else _LEGACY_STATIC
)
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

        # Never cache index.html — it points at hash-busted JS/CSS, so the browser must
        # re-fetch it to pick up a new build (otherwise you're stuck on the old bundle until
        # a hard refresh). The hashed assets themselves are immutable + cached by Flask static.
        return Response(
            _INDEX_CACHE,
            mimetype="text/html",
            headers={"Cache-Control": "no-store, must-revalidate"},
        )
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


# Hosts whose images we'll proxy (comp/listing CDNs). Facebook CDN images are
# referrer-locked + 403 when hotlinked from the browser; fetching them server-side
# (and streaming) lets comp thumbnails render. Restricted to known image CDNs (SSRF guard).
_IMG_HOSTS = (
    "fbcdn.net",
    "cloudfront.net",
    "kijiji.ca",
    "autoscout24.net",
    "akamaized.net",
    "licdn.com",
)


# Only raster image types are served — never image/svg+xml (an SVG served same-origin
# can carry <script> → XSS). Hardening headers below prevent sniffing/script execution.
_IMG_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp", "image/avif"}


_IMG_MAX_BYTES = 8 * 1024 * 1024  # 8 MiB cap on a proxied image


def _resolves_public(host: str) -> bool:
    """True only if EVERY DNS result for host is a global/public IP — rejects an allowlisted
    domain that (via misconfig or DNS rebinding) points at a private/loopback/link-local/CGNAT
    address. Defense-in-depth on top of the host allowlist."""
    import socket
    import ipaddress

    try:
        infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except OSError:
        return False
    if not infos:
        return False
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            return False
        if (
            not ip.is_global
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_private
            or ip.is_reserved
        ):
            return False
    return True


@app.get("/api/img")
def api_img():
    """Proxy an external listing/comp image server-side (browser can't hotlink FB CDN)."""
    import requests
    from urllib.parse import urlparse
    from flask import Response

    url = request.args.get("u", "")
    # Match on the real connect host (hostname, not netloc — which includes user@/:port and
    # is spoofable, e.g. https://fbcdn.net@169.254.169.254/). Require exact or dotted-suffix.
    host = (urlparse(url).hostname or "").lower().rstrip(".")
    if not url.startswith("https://") or not any(
        host == h or host.endswith("." + h) for h in _IMG_HOSTS
    ):
        return jsonify(error="disallowed url"), 400
    if not _resolves_public(host):
        return jsonify(error="disallowed host"), 400
    try:
        # No redirects (a 30x could bounce to an internal host); stream + cap the body so a
        # huge/slow response can't exhaust memory.
        r = requests.get(
            url,
            timeout=12,
            allow_redirects=False,
            stream=True,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        ctype = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        clen = r.headers.get("Content-Length")
        if r.status_code != 200 or ctype not in _IMG_TYPES:
            r.close()
            return ("", 415 if ctype not in _IMG_TYPES else 404)
        if clen and clen.isdigit() and int(clen) > _IMG_MAX_BYTES:
            r.close()
            return ("", 413)
        buf = bytearray()
        for chunk in r.iter_content(8192):
            buf.extend(chunk)
            if len(buf) > _IMG_MAX_BYTES:
                r.close()
                return ("", 413)
        return Response(
            bytes(buf),
            mimetype=ctype,
            headers={
                "Cache-Control": "public, max-age=86400",
                "X-Content-Type-Options": "nosniff",
                "Content-Disposition": 'inline; filename="img"',
                "Content-Security-Policy": "default-src 'none'; sandbox",
            },
        )
    except Exception:  # noqa: BLE001
        return ("", 404)


@app.get("/api/sales")
def api_sales():
    """Index of upcoming sales (Tuesday Timed Auctions + Saturday Super Sales)."""
    from dashboard.mapper import sales

    conn = get_conn()
    try:
        _maybe_auto_refresh(
            conn
        )  # auto re-scrape when a sale is ≤2 days out + data is stale
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
    from dashboard.mapper import evaluate, get_cached_deep

    contract = request.args.get("contract")
    if not contract:
        return jsonify(error="contract required"), 400
    mode = request.args.get("mode", "triage")
    profile = request.args.get("profile", "charles")
    ai_mode = mode if mode in ("triage", "deep") else None
    # cached_only: re-display a persisted deep result without recomputing (no AI cost).
    # If none is cached, fall back to the fast deterministic pass so the card still renders.
    cached_only = request.args.get("cached_only") in ("1", "true", "yes")
    conn = get_conn()
    try:
        if ai_mode == "deep" and cached_only:
            vehicle = get_cached_deep(conn, contract, profile) or evaluate(
                conn, contract, profile=profile, ai_mode=None
            )
        else:
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


# ── Off-auction appraisal: any vehicle (manual selector / VIN / scraped ad) ──


def _build_subject(d: dict):
    """(vehicle spec, appraise_subject kwargs) from a request body/args dict."""

    def _int(x):
        try:
            return int(x)
        except (TypeError, ValueError):
            return None

    veh = {
        "year": _int(d.get("year")),
        "make": (d.get("make") or "").strip().upper() or None,
        "model": (d.get("model") or "").strip().upper() or None,
        "trim": (d.get("trim") or "").strip() or None,
        "driveline": (d.get("driveline") or "").strip() or None,
        "engine": (d.get("engine") or "").strip() or None,
        "cab": (d.get("cab") or "").strip() or None,
        "odometer_km": _int(d.get("km") or d.get("odometer_km")),
        "vin": (d.get("vin") or "").strip().upper() or None,
    }
    photos = d.get("photos") or []
    if isinstance(photos, str):
        photos = [p for p in photos.split(",") if p.strip()]
    mode = d.get("mode")
    ai_mode = (
        None if mode == "none" else (mode if mode in ("triage", "deep") else "deep")
    )
    return veh, {
        "seller_type": d.get("seller_type") or "private",
        "photos": photos,
        "asking_price_dollars": d.get("asking_price") or d.get("asking"),
        "source": d.get("source") or "manual",
        "ad_url": d.get("ad_url") or d.get("adUrl"),
        "profile": d.get("profile") or "charles",
        "ai_mode": ai_mode,
    }


@app.post("/api/appraise")
def api_appraise():
    """Deep-appraise any vehicle (not a Regal lot). Body = spec + seller_type + asking_price."""
    from dashboard.mapper import appraise_subject

    d = request.get_json(silent=True) or {}
    veh, kw = _build_subject(d)
    if not (veh["make"] and veh["model"]):
        return jsonify(error="make and model required"), 400
    conn = get_conn()
    try:
        v = appraise_subject(conn, veh, **kw)
    except Exception as e:  # noqa: BLE001
        return jsonify(error=str(e)), 500
    finally:
        conn.close()
    return jsonify(vehicle=v)


@app.get("/api/appraise_stream")
def api_appraise_stream():
    """SSE: stream stage progress for an off-auction deep appraisal, then the result."""
    import json as _json
    import queue
    import threading
    from flask import Response, stream_with_context
    from dashboard.mapper import appraise_subject

    veh, kw = _build_subject(request.args)
    if not (veh["make"] and veh["model"]):
        return jsonify(error="make and model required"), 400

    q: "queue.Queue" = queue.Queue()

    def work():
        conn = get_conn()
        try:
            v = appraise_subject(
                conn, veh, progress=lambda s: q.put(("stage", s)), **kw
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
            ev = "failed" if kind == "error" else kind
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


@app.get("/api/vpic/makes")
def api_vpic_makes():
    from collector.vpic_options import makes

    return jsonify(makes=makes())


@app.get("/api/vpic/models")
def api_vpic_models():
    from collector.vpic_options import models

    try:
        year = int(request.args.get("year"))
    except (TypeError, ValueError):
        return jsonify(models=[])
    return jsonify(models=models(request.args.get("make", ""), year))


@app.get("/api/vpic/trims")
def api_vpic_trims():
    from collector.vpic_options import trims

    try:
        year = int(request.args.get("year"))
    except (TypeError, ValueError):
        return jsonify(trims=[])
    return jsonify(
        trims=trims(year, request.args.get("make", ""), request.args.get("model", ""))
    )


@app.get("/api/ingest_ad")
def api_ingest_ad():
    """Scrape a pasted ad URL (FB/Kijiji/AutoTrader) → subject spec + price + photos + seller type."""
    from collector.ad_ingest import ingest_ad

    url = request.args.get("url", "").strip()
    if not url:
        return jsonify(error="url required"), 400
    try:
        return jsonify(ingest_ad(url))
    except Exception as e:  # noqa: BLE001
        return jsonify(error=str(e)), 502


@app.get("/api/vin_decode")
def api_vin_decode():
    """Decode a VIN → spec fields (for the selector's VIN shortcut)."""
    from collector.vin_decode import decode_vin

    conn = get_conn()
    try:
        decoded = decode_vin(request.args.get("vin"), conn=conn)
    finally:
        conn.close()
    return jsonify(decoded=decoded)


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


# ── Run all: deep-appraise every car in a sale (cached, resumable, cancellable) ──
_RUN_JOBS: dict = {}


@app.post("/api/run_all")
def api_run_all():
    from dashboard.mapper import sale_contracts, evaluate

    data = request.get_json(silent=True) or {}
    date_str = data.get("date")
    if not date_str:
        return jsonify(error="date required"), 400
    profile = data.get("profile", "charles")
    job = _RUN_JOBS.get(date_str)
    if job and job["status"] == "running":
        return jsonify(error="a run is already in progress", job=_job_view(job)), 409

    conn = get_conn()
    try:
        contracts = sale_contracts(conn, date_str, 1000)
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
    _RUN_JOBS[date_str] = job

    def run():
        conn2 = get_conn()
        try:
            for c in contracts:
                if job["cancel"]:
                    job["status"] = "cancelled"
                    break
                job["current"] = c
                try:
                    # use_deep_cache=True → already-deep cars are instant (resumable); only
                    # missing ones compute. store_deep persists each so opens stay instant.
                    v = evaluate(
                        conn2,
                        c,
                        profile=profile,
                        ai_mode="deep",
                        use_deep_cache=True,
                        store_deep=True,
                    )
                    st = {
                        "contract": c,
                        "verdict": (v or {}).get("verdict"),
                        "maxBid": (v or {}).get("maxBid"),
                    }
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


@app.get("/api/run_status")
def api_run_status():
    job = _RUN_JOBS.get(request.args.get("date"))
    return jsonify(status="idle") if not job else jsonify(job=_job_view(job))


@app.post("/api/run_cancel")
def api_run_cancel():
    data = request.get_json(silent=True) or {}
    job = _RUN_JOBS.get(data.get("date"))
    if job and job["status"] == "running":
        job["cancel"] = True
        return jsonify(ok=True)
    return jsonify(ok=False)


# ── Refresh Regal listings (re-scrape) — manual + auto when a sale is imminent ──
_REFRESH_JOB: dict = {}


def _refresh_view() -> dict:
    j = _REFRESH_JOB
    return {
        "status": j.get("status", "idle"),
        "error": j.get("error"),
        "elapsed": round(time.time() - j["started"], 1) if j.get("started") else 0,
        "finished": j.get("finished"),
    }


def _start_refresh() -> bool:
    """Kick a background re-scrape of regal_listings (one at a time). Returns False if already running."""
    if _REFRESH_JOB.get("status") == "running":
        return False
    _REFRESH_JOB.clear()
    _REFRESH_JOB.update({"status": "running", "started": time.time()})

    def run():
        try:
            from collector.regal_listings import collect

            collect()
            from dashboard.mapper import _DET_CACHE

            _DET_CACHE.clear()  # fresh lots/photos → re-screen
            _REFRESH_JOB["status"] = "done"
        except Exception as e:  # noqa: BLE001
            _REFRESH_JOB["status"] = "error"
            _REFRESH_JOB["error"] = str(e)
        finally:
            _REFRESH_JOB["finished"] = time.time()

    _threading.Thread(target=run, daemon=True).start()
    return True


def _maybe_auto_refresh(conn) -> None:
    """Regal republishes the lane ~2 days before a sale. If the soonest sale is ≤2 days out and our
    listings are >24h stale, kick one background re-scrape (throttled by the running flag).
    """
    import datetime as _dt

    if _REFRESH_JOB.get("status") == "running":
        return
    try:
        from db.connection import get_cursor

        cur = get_cursor(conn)
        cur.execute(
            "SELECT min(auction_date) d, max(last_updated_at) u FROM regal_listings "
            "WHERE auction_date >= CURRENT_DATE"
        )
        row = cur.fetchone()
        cur.close()
    except Exception:  # noqa: BLE001
        return
    if not row or not row.get("d"):
        return
    days = (row["d"] - _dt.date.today()).days
    u = row.get("u")
    stale = (u is None) or (
        _dt.datetime.now(_dt.timezone.utc) - u
    ).total_seconds() > 86400
    if days <= 2 and stale:
        _start_refresh()


@app.post("/api/refresh_listings")
def api_refresh_listings():
    started = _start_refresh()
    return jsonify(job=_refresh_view(), started=started)


@app.get("/api/refresh_status")
def api_refresh_status():
    return jsonify(_refresh_view())


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
