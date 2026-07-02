"""The daily growth loop — one command that runs the whole traffic machine for a pack:

discover keywords -> score + queue briefs -> generate (capped) -> gates -> publish
-> internal links -> sitemap/robots (+ GSC/IndexNow submit when configured)
-> import search metrics (GSC API when configured) -> resolve stale clicks
-> score the niche -> queue improvement work -> report.

Cron it per pack. Every run is recorded in daily_growth_runs.
"""

from datetime import UTC, datetime

from engine.db.pool import pool
from engine.growth.common import load_pack_context


def daily_growth(pack_slug: str, tenant_id: int = 1, provider_override: str | None = None,
                 skip_publish: bool = False) -> dict:
    from engine.bandit.store import expire_stale
    from engine.growth.discovery import discover_keywords
    from engine.growth.factory import generate_from_briefs
    from engine.growth.indexing import publish_index
    from engine.growth.links import build_links
    from engine.growth.planner import plan_content
    from engine.growth.rules import find_opportunities
    from engine.scorer.score import score_cells

    ctx = load_pack_context(pack_slug, tenant_id)
    limit = int(ctx["traffic"].get("daily_publish_limit", 3))
    report: dict = {"pack": pack_slug, "publish_limit": limit}

    report["discover"] = discover_keywords(pack_slug, tenant_id, provider_override)
    report["plan"] = plan_content(pack_slug, tenant_id)

    pages = generate_from_briefs(pack_slug, limit=limit, tenant_id=tenant_id,
                                 provider_override=provider_override)
    report["generate"] = {
        "attempted": len(pages),
        "published": sum(1 for p in pages if p["status"] == "published"),
        "rejected": sum(1 for p in pages if p["status"] != "published"),
        "slugs": [p["slug"] for p in pages],
    }

    report["links"] = build_links(pack_slug, tenant_id)

    if not skip_publish:
        import subprocess
        from pathlib import Path

        site = Path(__file__).resolve().parents[2] / "site"
        build = subprocess.run(["npm", "run", "build"], cwd=site, capture_output=True, text=True)
        report["site_build"] = "ok" if build.returncode == 0 else "FAILED"
    report["indexing"] = publish_index(pack_slug, tenant_id)

    try:
        from engine.growth.gsc import import_gsc

        report["gsc_import"] = import_gsc(pack_slug, tenant_id=tenant_id)
    except RuntimeError as e:
        report["gsc_import"] = {"skipped": str(e).split(".")[0]}

    report["expired_clicks"] = expire_stale(datetime.now(UTC), tenant_id)
    report["niche_scores"] = [
        {"cell": c.cell_slug, "score": c.score, "recommendation": c.recommendation}
        for c in score_cells(tenant_id)
    ]
    report["opportunities"] = find_opportunities(pack_slug, tenant_id)

    with pool().connection() as conn:
        import json

        conn.execute(
            "INSERT INTO daily_growth_runs (tenant_id, vertical_id, report) VALUES (%s, %s, %s)",
            (tenant_id, ctx["vertical_id"], json.dumps(report)),
        )
    return report
