"""Self-improvement rules: turn real traffic data into a work queue
(page_opportunities). Pure decision logic in evaluate_page() so it unit-tests
without a database; thresholds are module constants pending self-calibration."""

import json
from datetime import UTC, datetime

from engine.db.pool import pool
from engine.growth.common import load_pack_context

MIN_IMPRESSIONS_FOR_CTR_RULE = 100
LOW_CTR = 0.01
STRIKING_DISTANCE = (8.0, 20.0)
MIN_SERP_CLICKS_FOR_CTA_RULE = 10
MIN_OFFER_CLICKS_FOR_OFFER_RULE = 20
DEAD_PAGE_AGE_DAYS = 60


def evaluate_page(m: dict) -> list[dict]:
    """m: impressions, serp_clicks, avg_position, offer_clicks, conversions, age_days.
    Returns [{rule, detail}] — order = priority."""
    opps = []
    ctr = (m["serp_clicks"] / m["impressions"]) if m["impressions"] else 0.0
    if m["impressions"] >= MIN_IMPRESSIONS_FOR_CTR_RULE and ctr < LOW_CTR:
        opps.append({"rule": "rewrite_title",
                     "detail": {"impressions": m["impressions"], "ctr": round(ctr, 4)}})
    if m["avg_position"] and STRIKING_DISTANCE[0] <= m["avg_position"] <= STRIKING_DISTANCE[1]:
        opps.append({"rule": "expand_page",
                     "detail": {"avg_position": round(m["avg_position"], 1),
                                "action": "add depth, tables, internal links"}})
    if m["serp_clicks"] >= MIN_SERP_CLICKS_FOR_CTA_RULE and m["offer_clicks"] == 0:
        opps.append({"rule": "improve_cta",
                     "detail": {"serp_clicks": m["serp_clicks"], "offer_clicks": 0}})
    if m["offer_clicks"] >= MIN_OFFER_CLICKS_FOR_OFFER_RULE and m["conversions"] == 0:
        opps.append({"rule": "offer_issue",
                     "detail": {"offer_clicks": m["offer_clicks"],
                                "action": "check offer terms / bandit arms / postbacks"}})
    if m["age_days"] > DEAD_PAGE_AGE_DAYS and m["impressions"] == 0:
        opps.append({"rule": "kill_or_merge", "detail": {"age_days": m["age_days"]}})
    return opps


def find_opportunities(pack_slug: str, tenant_id: int = 1) -> dict:
    ctx = load_pack_context(pack_slug, tenant_id)
    now = datetime.now(UTC)
    with pool().connection() as conn:
        rows = conn.execute(
            """
            SELECT p.id, p.slug, p.created_at,
                   COALESCE(sum(pm.impressions), 0), COALESCE(sum(pm.serp_clicks), 0),
                   avg(pm.position),
                   (SELECT count(*) FROM clicks c WHERE c.page_id = p.id),
                   (SELECT count(*) FROM conversions cv JOIN clicks c2 ON c2.id = cv.click_id
                    WHERE c2.page_id = p.id)
            FROM pages p LEFT JOIN page_metrics pm ON pm.page_id = p.id
            WHERE p.tenant_id = %s AND p.vertical_id = %s AND p.status = 'published'
            GROUP BY p.id
            """,
            (tenant_id, ctx["vertical_id"]),
        ).fetchall()

        opened = 0
        queue = []
        for pid, slug, created_at, impressions, serp_clicks, avg_pos, oclicks, convs in rows:
            metrics = {
                "impressions": int(impressions), "serp_clicks": int(serp_clicks),
                "avg_position": float(avg_pos) if avg_pos is not None else None,
                "offer_clicks": int(oclicks), "conversions": int(convs),
                "age_days": (now - created_at).days,
            }
            for opp in evaluate_page(metrics):
                cur = conn.execute(
                    "INSERT INTO page_opportunities (tenant_id, page_id, rule, detail) "
                    "VALUES (%s, %s, %s, %s) "
                    "ON CONFLICT (page_id, rule) WHERE status = 'open' DO NOTHING",
                    (tenant_id, pid, opp["rule"], json.dumps(opp["detail"])),
                )
                if cur.rowcount:
                    opened += 1
                    queue.append({"page": slug, **opp})
    return {"pages_checked": len(rows), "new_opportunities": opened, "queue": queue}
