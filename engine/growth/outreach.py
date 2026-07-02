"""Prospect + outreach queue. Drafts are machine-written; SENDING IS ALWAYS HUMAN.

Automated link placement is Google's link-spam policy by definition and is
deliberately not implemented — this module only prepares work: who to contact,
why they'd care, and a draft referencing a real asset. `engine mark-sent` /
`mark-linked` record what the human did, feeding the backlink monitoring loop.
"""

import csv
from pathlib import Path

from engine.db.pool import pool
from engine.gateway.client import generate as llm_generate
from engine.growth.common import load_pack_context

DRAFT_TEMPLATE = """Hi{contact_greeting},

I run {site_name} ({site_url}). {reason_line}

We publish a {asset_kind} that might be useful to your readers: {asset_title}
{asset_url}

It's built from our own dataset and updates automatically, so it stays current if
you embed or cite it. Happy to share the underlying data as well.

No worries either way — thanks for the good work on {domain}.
"""


class BacklinkGapProvider:
    """Stub: DataForSEO backlinks API (/v3/backlinks/competitors) or Ahrefs link
    intersect — feed each pack competitor, return {domain, url, reason} prospects.
    Wire credentials and map to import_prospect rows."""

    def discover(self, ctx: dict) -> list[dict]:
        raise NotImplementedError("configure DataForSEO/Ahrefs credentials to enable")


def import_prospects(pack_slug: str, file: str, tenant_id: int = 1) -> dict:
    """CSV: domain[,url,contact,reason]"""
    ctx = load_pack_context(pack_slug, tenant_id)
    added = 0
    with Path(file).open(newline="") as f, pool().connection() as conn:
        for row in csv.DictReader(f):
            cur = conn.execute(
                "INSERT INTO link_prospects (tenant_id, vertical_id, domain, url, contact, "
                "reason, source) VALUES (%s, %s, %s, %s, %s, %s, 'csv') "
                "ON CONFLICT (vertical_id, domain) DO NOTHING",
                (tenant_id, ctx["vertical_id"], row["domain"].strip().lower(),
                 row.get("url", ""), row.get("contact", ""), row.get("reason", "")),
            )
            added += cur.rowcount
    return {"prospects_added": added}


def draft_outreach(pack_slug: str, tenant_id: int = 1, limit: int = 10,
                   provider_override: str | None = None) -> dict:
    ctx = load_pack_context(pack_slug, tenant_id)
    site_name = ctx["manifest"]["vertical"]["name"]
    site_url = f"https://{ctx['domain']}/"

    with pool().connection() as conn:
        asset = conn.execute(
            "SELECT id, kind, title, url FROM link_assets WHERE vertical_id = %s "
            "ORDER BY updated_at DESC LIMIT 1",
            (ctx["vertical_id"],),
        ).fetchone()
        if not asset:
            return {"drafted": 0, "reason": "no link assets — run engine build-assets first"}
        prospects = conn.execute(
            "SELECT id, domain, contact, reason FROM link_prospects "
            "WHERE vertical_id = %s AND status = 'new' ORDER BY id LIMIT %s",
            (ctx["vertical_id"], limit),
        ).fetchall()

        drafted = 0
        for pid, domain, contact, reason in prospects:
            reason_line = (f"I noticed {domain} {reason}." if reason
                           else f"I follow {domain}'s coverage of this space.")
            body = DRAFT_TEMPLATE.format(
                contact_greeting=f" {contact.split('@')[0]}" if contact else "",
                site_name=site_name, site_url=site_url, reason_line=reason_line,
                asset_kind=asset[1], asset_title=asset[2], asset_url=asset[3], domain=domain,
            )
            if provider_override != "mock":
                try:
                    opener = llm_generate(
                        "polish",
                        f"Rewrite this outreach email to be shorter and more specific to a "
                        f"site about: {reason or 'this topic'}. Keep the asset link and the "
                        f"no-pressure tone. Do not add claims or numbers.\n\n{body}",
                        provider_override=provider_override, tenant_id=tenant_id,
                    )
                    body = opener if len(opener) > 80 else body
                except Exception:
                    pass  # template draft is the floor; personalization is best-effort
            subject = f"A live {asset[1]} your {domain} readers might use"
            conn.execute(
                "INSERT INTO outreach_drafts (tenant_id, prospect_id, asset_id, subject, body) "
                "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (prospect_id) DO UPDATE SET "
                "subject = EXCLUDED.subject, body = EXCLUDED.body, asset_id = EXCLUDED.asset_id",
                (tenant_id, pid, asset[0], subject, body),
            )
            conn.execute("UPDATE link_prospects SET status = 'drafted' WHERE id = %s", (pid,))
            drafted += 1
    return {"drafted": drafted, "asset": asset[2]}


def list_drafts(pack_slug: str, tenant_id: int = 1) -> list[dict]:
    ctx = load_pack_context(pack_slug, tenant_id)
    with pool().connection() as conn:
        rows = conn.execute(
            "SELECT p.domain, p.contact, d.subject, d.body FROM outreach_drafts d "
            "JOIN link_prospects p ON p.id = d.prospect_id "
            "WHERE p.vertical_id = %s AND p.status = 'drafted' ORDER BY d.id",
            (ctx["vertical_id"],),
        ).fetchall()
    return [{"domain": r[0], "contact": r[1], "subject": r[2], "body": r[3]} for r in rows]


def set_status(pack_slug: str, domain: str, status: str, tenant_id: int = 1) -> bool:
    assert status in ("sent", "linked", "rejected")
    ctx = load_pack_context(pack_slug, tenant_id)
    with pool().connection() as conn:
        cur = conn.execute(
            "UPDATE link_prospects SET status = %s WHERE vertical_id = %s AND domain = %s",
            (status, ctx["vertical_id"], domain.lower()),
        )
    return cur.rowcount > 0


def import_backlinks(pack_slug: str, file: str, date: str, source: str = "gsc_csv",
                     tenant_id: int = 1) -> dict:
    """Referring-domain snapshot from a CSV export (GSC 'Top linking sites' or any file
    with a domain/site column; falls back to one-domain-per-line)."""
    ctx = load_pack_context(pack_slug, tenant_id)
    path = Path(file)
    domains: set[str] = set()
    total_links = 0
    with path.open(newline="") as f:
        sample = f.read(2048)
        f.seek(0)
        if "," in sample:
            reader = csv.DictReader(f)
            dom_col = next((c for c in (reader.fieldnames or [])
                            if c.lower() in ("site", "domain", "linking site")), None)
            link_col = next((c for c in (reader.fieldnames or [])
                             if "linking pages" in c.lower() or c.lower() == "links"), None)
            for row in reader:
                if dom_col and row.get(dom_col):
                    domains.add(row[dom_col].strip().lower())
                    if link_col and row.get(link_col, "").strip().isdigit():
                        total_links += int(row[link_col])
        else:
            domains = {line.strip().lower() for line in sample.splitlines() if line.strip()}
    with pool().connection() as conn:
        conn.execute(
            "INSERT INTO backlink_snapshots (tenant_id, vertical_id, date, referring_domains, "
            "total_links, source) VALUES (%s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (vertical_id, date, source) DO UPDATE SET "
            "referring_domains = EXCLUDED.referring_domains, total_links = EXCLUDED.total_links",
            (tenant_id, ctx["vertical_id"], date, len(domains), total_links or None, source),
        )
    return {"date": date, "referring_domains": len(domains), "total_links": total_links or None}
