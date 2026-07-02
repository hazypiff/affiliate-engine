"""Google Search Console API importer (page x date -> page_metrics).

Setup: create a GCP service account, enable the Search Console API, add the
service-account email as a user on the property, save the JSON key, and set
GSC_SA_JSON=/path/to/key.json. Property form: sc-domain:<domain>.
Falls back cleanly: without creds this raises with instructions and the CSV
importer (`engine import-metrics`) remains available.
"""

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import quote, urlparse

from engine.db.pool import pool
from engine.growth.common import load_pack_context


def import_gsc(pack_slug: str, days: int = 7, tenant_id: int = 1) -> dict:
    sa = os.environ.get("GSC_SA_JSON")
    if not sa or not Path(sa).exists():
        raise RuntimeError(
            "GSC_SA_JSON not configured. Create a service account with Search Console API "
            "access, add it to the property, set GSC_SA_JSON=/path/key.json. "
            "Until then: engine import-metrics <csv> (GSC Performance export)."
        )
    from google.auth.transport.requests import AuthorizedSession
    from google.oauth2 import service_account

    ctx = load_pack_context(pack_slug, tenant_id)
    creds = service_account.Credentials.from_service_account_file(
        sa, scopes=["https://www.googleapis.com/auth/webmasters.readonly"]
    )
    session = AuthorizedSession(creds)
    site = quote(f"sc-domain:{ctx['domain']}", safe="")
    end = datetime.now(UTC).date()
    start = end - timedelta(days=days)

    rows, start_row = [], 0
    while True:
        resp = session.post(
            f"https://searchconsole.googleapis.com/webmasters/v3/sites/{site}/searchAnalytics/query",
            json={
                "startDate": start.isoformat(),
                "endDate": end.isoformat(),
                "dimensions": ["page", "date"],
                "rowLimit": 1000,
                "startRow": start_row,
            },
        )
        resp.raise_for_status()
        batch = resp.json().get("rows", [])
        rows.extend(batch)
        if len(batch) < 1000:
            break
        start_row += 1000

    imported = 0
    with pool().connection() as conn:
        for r in rows:
            page_url, date = r["keys"][0], r["keys"][1]
            slug = urlparse(page_url).path.rstrip("/").rsplit("/", 1)[-1]
            page = conn.execute(
                "SELECT id FROM pages WHERE tenant_id = %s AND vertical_id = %s AND slug = %s",
                (tenant_id, ctx["vertical_id"], slug),
            ).fetchone()
            if not page:
                continue
            conn.execute(
                """
                INSERT INTO page_metrics (tenant_id, page_id, date, impressions, serp_clicks,
                                          position)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (page_id, date) DO UPDATE SET
                    impressions = EXCLUDED.impressions, serp_clicks = EXCLUDED.serp_clicks,
                    position = EXCLUDED.position
                """,
                (tenant_id, page[0], date, int(r.get("impressions", 0)),
                 int(r.get("clicks", 0)), float(r.get("position", 0)) or None),
            )
            imported += 1
    return {"api_rows": len(rows), "imported": imported, "window_days": days}
