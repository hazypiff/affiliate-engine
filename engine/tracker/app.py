"""Tracker: /go/{slot} redirects (Thompson pick + click log + geo gate) and
/postback/{network} S2S conversion capture. Sim mode: X-Sim-Now header overrides
the clock so the e2e harness can drive delayed conversions without waiting."""

import os
from datetime import datetime

import numpy as np
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse

from engine.bandit import store
from engine.bandit.thompson import select
from engine.sim.clock import RealClock

app = FastAPI(title="affiliate-engine tracker")
clock = RealClock()
# ENGINE_BANDIT_SEED makes selection reproducible (e2e); unset in production
_seed = os.environ.get("ENGINE_BANDIT_SEED")
rng = np.random.default_rng(int(_seed) if _seed else None)


def _now(request: Request) -> datetime:
    sim = request.headers.get("X-Sim-Now")
    if sim:
        return datetime.fromisoformat(sim)
    return clock.now()


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/go/{slot_slug}")
def go(slot_slug: str, request: Request, page: str | None = None, geo: str | None = None):
    now = _now(request)
    # drift window: how far back mature clicks feed the posterior. At low traffic a
    # short window starves arms back to their optimistic prior — size it to volume.
    window_days = int(os.environ.get("ENGINE_BANDIT_WINDOW_DAYS", "90"))
    arms = store.arms_for_slot(slot_slug, geo=geo, now=now, window_days=window_days)
    if not arms:
        # geo default-deny or unknown slot: nothing eligible to redirect to
        raise HTTPException(status_code=404, detail="no eligible offer for slot/geo")
    offer_id = select(arms, rng)
    subid, url = store.record_click(slot_slug, offer_id, now, page_slug=page, geo=geo)
    return RedirectResponse(url, status_code=302)


@app.get("/postback/{network}")
@app.post("/postback/{network}")
async def postback(network: str, request: Request):
    from engine.tracker.postback.adapters import PostbackError, parse

    params = dict(request.query_params)
    if request.method == "POST":
        try:
            params.update(await request.json())
        except Exception:
            pass
    try:
        subid, revenue, raw = parse(network, params)
    except PostbackError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    ok = store.record_conversion(subid, revenue, _now(request), raw=raw)
    return {"recorded": ok}


@app.post("/expire")
def expire(request: Request):
    """Run the attribution-window expiry job (also runnable via cron/CLI)."""
    return {"expired": store.expire_stale(_now(request))}


@app.get("/report")
def report():
    from engine.db.pool import pool

    with pool().connection() as conn:
        rows = conn.execute(
            """
            SELECT o.slug,
                   count(c.id) AS clicks,
                   count(c.id) FILTER (WHERE c.status = 'converted') AS converted,
                   count(c.id) FILTER (WHERE c.status = 'expired')   AS expired,
                   count(c.id) FILTER (WHERE c.status = 'pending')   AS pending,
                   COALESCE(sum(cv.revenue), 0)::float AS revenue
            FROM offers o
            LEFT JOIN clicks c ON c.offer_id = o.id
            LEFT JOIN conversions cv ON cv.click_id = c.id
            GROUP BY o.slug ORDER BY revenue DESC
            """
        ).fetchall()
    return {
        "offers": [
            {"offer": r[0], "clicks": r[1], "converted": r[2], "expired": r[3],
             "pending": r[4], "revenue": r[5]}
            for r in rows
        ]
    }
