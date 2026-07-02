"""Search-metrics CSV importer (page_slug,date,impressions,clicks,position[,sessions]).

Export from Google Search Console (Performance -> Pages -> Export) and map the page
URL path to the page slug. A direct GSC API importer is the documented next step:
google-api-python-client + searchanalytics.query with dimensions=['page','date'],
OAuth service-account creds per tenant — same upsert as below, no schema changes.
"""

import csv
from pathlib import Path

from engine.db.pool import pool


def import_csv(file: str | Path, tenant_id: int = 1) -> int:
    n = 0
    with Path(file).open(newline="") as f, pool().connection() as conn:
        for row in csv.DictReader(f):
            page = conn.execute(
                "SELECT id FROM pages WHERE tenant_id = %s AND slug = %s",
                (tenant_id, row["page_slug"].strip()),
            ).fetchone()
            if not page:
                continue
            conn.execute(
                """
                INSERT INTO page_metrics (tenant_id, page_id, date, impressions, serp_clicks,
                                          position, sessions)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (page_id, date) DO UPDATE SET
                    impressions = EXCLUDED.impressions, serp_clicks = EXCLUDED.serp_clicks,
                    position = EXCLUDED.position, sessions = EXCLUDED.sessions
                """,
                (tenant_id, page[0], row["date"], int(row["impressions"]), int(row["clicks"]),
                 float(row["position"]) if row.get("position") else None,
                 int(row.get("sessions") or 0)),
            )
            n += 1
    return n
