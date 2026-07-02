"""Sitemap generation + search-engine submission.

- sitemap-<vertical>.xml + robots.txt written into site/out/ (deploy artifacts).
- Google: sitemap submission via Search Console API when GSC_SA_JSON (service-account
  file) is configured — it is a crawl HINT, not a ranking guarantee. Google's
  Indexing API is intentionally NOT used: it only covers job postings/livestreams.
- Bing & friends: IndexNow ping when INDEXNOW_KEY is set (key file must be hosted
  at the domain root — the key file is also written next to the sitemap).
Every action is recorded in indexing_submissions, including skips.
"""

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import httpx

from engine.db.pool import pool
from engine.growth.common import load_pack_context

SITE_OUT = Path(__file__).resolve().parents[2] / "site" / "out"


def page_urls(ctx: dict, tenant_id: int = 1) -> list[str]:
    with pool().connection() as conn:
        rows = conn.execute(
            "SELECT slug FROM pages WHERE tenant_id = %s AND vertical_id = %s "
            "AND status = 'published' ORDER BY slug",
            (tenant_id, ctx["vertical_id"]),
        ).fetchall()
    return [f"https://{ctx['domain']}/{ctx['vertical_slug']}/{r[0]}/" for r in rows]


def sitemap_xml(urls: list[str], lastmod: str) -> str:
    items = "\n".join(
        f"  <url><loc>{u}</loc><lastmod>{lastmod}</lastmod></url>" for u in urls
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{items}\n</urlset>\n"
    )


def _record(conn, tenant_id, vertical_id, kind, target, status, detail=None):
    conn.execute(
        "INSERT INTO indexing_submissions (tenant_id, vertical_id, kind, target, status, detail) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (tenant_id, vertical_id, kind, target, status, json.dumps(detail or {})),
    )


def _submit_gsc_sitemap(domain: str, sitemap_url: str) -> str:
    """PUT the sitemap to Search Console. Needs GSC_SA_JSON (service-account key with
    the property delegated). Returns a status string; never raises."""
    sa = os.environ.get("GSC_SA_JSON")
    if not sa or not Path(sa).exists():
        return "skipped_no_creds"
    try:
        from google.auth.transport.requests import AuthorizedSession
        from google.oauth2 import service_account

        creds = service_account.Credentials.from_service_account_file(
            sa, scopes=["https://www.googleapis.com/auth/webmasters"]
        )
        site = f"sc-domain:{domain}"
        url = (f"https://www.googleapis.com/webmasters/v3/sites/"
               f"{httpx.QueryParams({'s': site})['s']}/sitemaps/{sitemap_url}")
        resp = AuthorizedSession(creds).put(url)
        return "submitted" if resp.status_code in (200, 204) else f"error_{resp.status_code}"
    except Exception:
        return "error"


def _submit_indexnow(domain: str, urls: list[str]) -> str:
    key = os.environ.get("INDEXNOW_KEY")
    if not key:
        return "skipped_no_creds"
    try:
        resp = httpx.post(
            "https://api.indexnow.org/indexnow",
            json={"host": domain, "key": key, "urlList": urls[:100]},
            timeout=20,
        )
        return "submitted" if resp.status_code in (200, 202) else f"error_{resp.status_code}"
    except httpx.HTTPError:
        return "error"


def publish_index(pack_slug: str, tenant_id: int = 1) -> dict:
    ctx = load_pack_context(pack_slug, tenant_id)
    urls = page_urls(ctx, tenant_id)
    lastmod = datetime.now(UTC).date().isoformat()

    SITE_OUT.mkdir(parents=True, exist_ok=True)
    sitemap_name = f"sitemap-{ctx['vertical_slug']}.xml"
    (SITE_OUT / sitemap_name).write_text(sitemap_xml(urls, lastmod))

    robots = SITE_OUT / "robots.txt"
    line = f"Sitemap: https://{ctx['domain']}/{sitemap_name}"
    existing = robots.read_text().splitlines() if robots.exists() else ["User-agent: *", "Allow: /"]
    if line not in existing:
        existing.append(line)
    robots.write_text("\n".join(existing) + "\n")

    key = os.environ.get("INDEXNOW_KEY")
    if key:
        (SITE_OUT / f"{key}.txt").write_text(key)

    sitemap_url = f"https://{ctx['domain']}/{sitemap_name}"
    gsc_status = _submit_gsc_sitemap(ctx["domain"], sitemap_url)
    indexnow_status = _submit_indexnow(ctx["domain"], urls)

    with pool().connection() as conn:
        _record(conn, tenant_id, ctx["vertical_id"], "sitemap", sitemap_url,
                "generated" if gsc_status.startswith("skipped") else gsc_status,
                {"urls": len(urls), "gsc": gsc_status})
        _record(conn, tenant_id, ctx["vertical_id"], "indexnow", ctx["domain"],
                indexnow_status, {"urls": min(len(urls), 100)})
    return {"sitemap": sitemap_name, "urls": len(urls), "gsc": gsc_status,
            "indexnow": indexnow_status}
