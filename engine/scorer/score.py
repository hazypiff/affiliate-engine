"""Niche test-cell scoring: a progressive composite over the signals available so far
(publish rate -> impressions -> CTR -> EPC), mirroring the impatient-bandit idea of
acting on partial signals instead of waiting for the full horizon.

Thresholds are CONFIG, not published truth: no external kill/scale numbers survived
verification (research report §1.4) — calibrate from your own first cells' trajectories.
"""

import json
from dataclasses import dataclass

from engine.db.pool import pool

# soft caps for normalization: value/cap clamped to 1.0
CAPS = {"impressions_per_page": 200.0, "ctr": 0.05, "epc_per_click": 2.0}
WEIGHTS = {"publish_rate": 0.15, "impressions": 0.25, "ctr": 0.20, "epc": 0.40}
KILL_BELOW = 0.15
SCALE_ABOVE = 0.55


@dataclass
class CellScore:
    cell_slug: str
    metrics: dict
    score: float
    recommendation: str


def _norm(value: float, cap: float) -> float:
    return max(0.0, min(1.0, value / cap)) if cap else 0.0


def score_cells(tenant_id: int = 1, window_days: int = 30) -> list[CellScore]:
    results = []
    with pool().connection() as conn:
        cells = conn.execute(
            "SELECT id, slug, page_target FROM test_cells WHERE tenant_id = %s", (tenant_id,)
        ).fetchall()
        for cell_id, slug, target in cells:
            pages = conn.execute(
                "SELECT count(*) FILTER (WHERE status = 'published'), count(*) "
                "FROM pages WHERE test_cell_id = %s",
                (cell_id,),
            ).fetchone()
            published, total = pages
            m = conn.execute(
                "SELECT COALESCE(sum(pm.impressions),0), COALESCE(sum(pm.serp_clicks),0), "
                "COALESCE(sum(pm.sessions),0) FROM page_metrics pm "
                "JOIN pages p ON p.id = pm.page_id WHERE p.test_cell_id = %s",
                (cell_id,),
            ).fetchone()
            impressions, serp_clicks, sessions = int(m[0]), int(m[1]), int(m[2])
            rev = conn.execute(
                "SELECT COALESCE(sum(cv.revenue),0)::float, count(c.id) FROM clicks c "
                "JOIN conversions cv ON cv.click_id = c.id "
                "JOIN pages p ON p.id = c.page_id WHERE p.test_cell_id = %s",
                (cell_id,),
            ).fetchone()
            revenue = float(rev[0])

            all_clicks = conn.execute(
                "SELECT count(*) FROM clicks c JOIN pages p ON p.id = c.page_id "
                "WHERE p.test_cell_id = %s",
                (cell_id,),
            ).fetchone()[0]

            publish_rate = published / target if target else 0.0
            impressions_pp = impressions / published if published else 0.0
            ctr = serp_clicks / impressions if impressions else 0.0
            epc = revenue / all_clicks if all_clicks else 0.0

            score = round(
                WEIGHTS["publish_rate"] * min(1.0, publish_rate)
                + WEIGHTS["impressions"] * _norm(impressions_pp, CAPS["impressions_per_page"])
                + WEIGHTS["ctr"] * _norm(ctr, CAPS["ctr"])
                + WEIGHTS["epc"] * _norm(epc, CAPS["epc_per_click"]),
                4,
            )
            # progressive: with no search metrics yet, don't kill on the missing signals
            has_search_signal = impressions > 0
            if not has_search_signal:
                recommendation = "continue"
            elif score < KILL_BELOW:
                recommendation = "kill"
            elif score > SCALE_ABOVE:
                recommendation = "scale"
            else:
                recommendation = "continue"

            metrics = {
                "published": published, "total_pages": total, "publish_rate": round(publish_rate, 3),
                "impressions": impressions, "serp_clicks": serp_clicks, "sessions": sessions,
                "offer_clicks": all_clicks, "revenue": round(revenue, 2),
                "epc_per_click": round(epc, 4), "ctr": round(ctr, 4),
            }
            conn.execute(
                "INSERT INTO niche_scores (tenant_id, test_cell_id, window_days, metrics, score, "
                "recommendation) VALUES (%s, %s, %s, %s, %s, %s)",
                (tenant_id, cell_id, window_days, json.dumps(metrics), score, recommendation),
            )
            results.append(CellScore(slug, metrics, score, recommendation))
    return results
