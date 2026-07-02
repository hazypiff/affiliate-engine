"""DB-backed arm stats + click/conversion recording for the tracker.

The censoring rule lives in exactly ONE place: the posterior-input query below.
A click enters the posterior only once it is MATURE — older than its program's
attribution window, so its outcome is fully determined (converted, or de facto
expired). Counting conversions as they arrive while failures wait out the window
biases the estimate upward for recently-clicked arms (conversions resolve in days,
failures only at expiry) — the e2e sim demonstrably drifts to the wrong arm that way.
Maturity-gated counting is the unbiased baseline from the delayed-bandit literature;
the progressive-signal Bayesian filter (impatient bandits) is the documented v2 upgrade.
All time-dependent SQL takes an explicit `now` (injected clock; testable without sleeps).
"""

import uuid
from datetime import datetime, timedelta

from engine.bandit.thompson import ArmStats
from engine.db.pool import pool


def arms_for_slot(slot_slug: str, tenant_id: int = 1, geo: str | None = None,
                  window_days: int = 90, now: datetime | None = None) -> list[ArmStats]:
    """Eligible offers for a slot with MATURITY-GATED posterior inputs (see module doc).
    geo + default-deny is enforced here: geo_allow empty = open; else geo must be listed."""
    if now is None:
        from datetime import UTC

        now = datetime.now(UTC)
    with pool().connection() as conn:
        rows = conn.execute(
            """
            SELECT o.id, o.payout_amount, o.geo_allow,
                   count(c.id) FILTER (
                       WHERE c.clicked_at <= %(now)s - make_interval(days => p.cookie_window_days)
                         AND c.status = 'converted') AS converted,
                   -- mature and not converted = failure, whether or not the expiry job ran yet
                   count(c.id) FILTER (
                       WHERE c.clicked_at <= %(now)s - make_interval(days => p.cookie_window_days)
                         AND c.status IN ('expired', 'pending')) AS expired,
                   count(c.id) FILTER (
                       WHERE c.clicked_at > %(now)s - make_interval(days => p.cookie_window_days)
                   ) AS pending,
                   COALESCE(sum(cv.revenue) FILTER (
                       WHERE c.clicked_at <= %(now)s - make_interval(days => p.cookie_window_days)
                   ), 0) AS revenue
            FROM slots s
            JOIN slot_offers so ON so.slot_id = s.id
            JOIN offers o ON o.id = so.offer_id AND o.status = 'active'
            JOIN affiliate_programs p ON p.id = o.program_id
            LEFT JOIN clicks c ON c.offer_id = o.id AND c.slot_id = s.id
                 AND c.clicked_at >= %(since)s
            LEFT JOIN conversions cv ON cv.click_id = c.id
            WHERE s.tenant_id = %(tenant_id)s AND s.slug = %(slot)s
            GROUP BY o.id, o.payout_amount, o.geo_allow
            """,
            {
                "tenant_id": tenant_id,
                "slot": slot_slug,
                "now": now,
                "since": now - timedelta(days=window_days),
            },
        ).fetchall()

    arms = []
    for oid, payout, geo_allow, converted, expired, pending, revenue in rows:
        if geo_allow:  # non-empty allowlist -> default deny
            if geo is None or geo.upper() not in geo_allow:
                continue
        arms.append(
            ArmStats(
                offer_id=oid,
                converted=converted,
                expired=expired,
                pending=pending,
                total_revenue=float(revenue),
                nominal_payout=float(payout),
            )
        )
    return arms


def record_click(slot_slug: str, offer_id: int, now: datetime, tenant_id: int = 1,
                 page_slug: str | None = None, geo: str | None = None,
                 device: str | None = None) -> tuple[str, str]:
    """Insert a pending click; returns (subid, destination_url)."""
    subid = uuid.uuid4().hex
    with pool().connection() as conn:
        slot_id = conn.execute(
            "SELECT id FROM slots WHERE tenant_id = %s AND slug = %s", (tenant_id, slot_slug)
        ).fetchone()[0]
        page_row = None
        if page_slug:
            page_row = conn.execute(
                "SELECT id FROM pages WHERE tenant_id = %s AND slug = %s", (tenant_id, page_slug)
            ).fetchone()
        url_template = conn.execute(
            "SELECT url_template FROM offers WHERE id = %s", (offer_id,)
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO clicks (tenant_id, slot_id, offer_id, page_id, subid, geo, device, "
            "status, clicked_at) VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending', %s)",
            (tenant_id, slot_id, offer_id, page_row[0] if page_row else None, subid, geo,
             device, now),
        )
    return subid, url_template.replace("{click_id}", subid)


def record_conversion(subid: str, revenue: float, now: datetime, raw: dict | None = None) -> bool:
    """S2S postback: resolve the pending click, write the conversion. Idempotent."""
    import json

    with pool().connection() as conn:
        row = conn.execute(
            "SELECT id, tenant_id, offer_id, status FROM clicks WHERE subid = %s", (subid,)
        ).fetchone()
        if not row or row[3] != "pending":
            return False
        click_id, tenant_id, offer_id, _ = row
        conn.execute(
            "UPDATE clicks SET status = 'converted', resolved_at = %s WHERE id = %s",
            (now, click_id),
        )
        conn.execute(
            "INSERT INTO conversions (tenant_id, click_id, offer_id, revenue, converted_at, raw) "
            "VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (click_id) DO NOTHING",
            (tenant_id, click_id, offer_id, revenue, now, json.dumps(raw or {})),
        )
    return True


def expire_stale(now: datetime, tenant_id: int = 1) -> int:
    """Resolve pending clicks older than their program's attribution window as expired."""
    with pool().connection() as conn:
        cur = conn.execute(
            """
            UPDATE clicks c SET status = 'expired', resolved_at = %(now)s
            FROM offers o JOIN affiliate_programs p ON p.id = o.program_id
            WHERE c.offer_id = o.id AND c.tenant_id = %(tenant_id)s AND c.status = 'pending'
              AND c.clicked_at < %(now)s - make_interval(days => p.cookie_window_days)
            """,
            {"now": now, "tenant_id": tenant_id},
        )
        return cur.rowcount
