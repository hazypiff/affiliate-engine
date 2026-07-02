import json

import typer

app = typer.Typer(help="affiliate-engine CLI", no_args_is_help=True)


@app.command("init-db")
def init_db():
    """Apply pending SQL migrations (idempotent)."""
    from engine.db.migrate import migrate

    applied = migrate()
    typer.echo(f"applied: {applied or 'nothing (up to date)'}")


@app.command("install-pack")
def install_pack(pack_dir: str):
    """Validate and install a niche pack directory into the DB."""
    from engine.packs.installer import install

    counts = install(pack_dir)
    typer.echo(json.dumps({"installed": pack_dir, **counts}))


@app.command("generate")
def generate(
    pack: str = typer.Option(..., help="pack slug, e.g. ai-saas"),
    n: int = typer.Option(3, help="number of pages"),
    provider: str = typer.Option(None, help="'mock' for offline deterministic generation"),
):
    """Generate data-grounded pages for a pack and run all gates."""
    from engine.pipeline.generate import generate_pages

    for r in generate_pages(pack, count=n, provider_override=provider):
        gate_summary = {k: v["passed"] for k, v in r["gates"].items()}
        typer.echo(json.dumps({"slug": r["slug"], "status": r["status"], **gate_summary}))


@app.command("gate-report")
def gate_report_cmd():
    """Summarize page statuses and gate failures."""
    from engine.pipeline.generate import gate_report

    typer.echo(json.dumps(gate_report(), indent=1))


@app.command("publish")
def publish(skip_install: bool = typer.Option(False, help="skip npm install")):
    """Build the static site (next build, output: export)."""
    import os
    import subprocess
    from pathlib import Path

    site = Path(__file__).resolve().parents[1] / "site"
    env = {**os.environ, "NODE_OPTIONS": "--max-old-space-size=2048"}
    if not skip_install and not (site / "node_modules").exists():
        subprocess.run(["npm", "install", "--no-audit", "--no-fund"], cwd=site, env=env, check=True)
    subprocess.run(["npm", "run", "build"], cwd=site, env=env, check=True)
    out = site / "out"
    typer.echo(f"built: {sum(1 for _ in out.rglob('*.html'))} html files in {out}")


@app.command("discover-keywords")
def discover_keywords_cmd(pack: str, provider: str = typer.Option(None)):
    """Expand keyword ideas from the pack's entities, seeds, and (non-mock) the LLM."""
    from engine.growth.discovery import discover_keywords

    typer.echo(json.dumps(discover_keywords(pack, provider_override=provider)))


@app.command("import-volumes")
def import_volumes_cmd(file: str):
    """Fill search_volume/difficulty from CSV (keyword,search_volume[,difficulty])."""
    from engine.growth.discovery import import_volumes

    typer.echo(json.dumps({"updated": import_volumes(file)}))


@app.command("plan-content")
def plan_content_cmd(pack: str):
    """Score keyword ideas and queue content briefs above the pack threshold."""
    from engine.growth.planner import plan_content

    typer.echo(json.dumps(plan_content(pack)))


@app.command("generate-briefs")
def generate_briefs_cmd(pack: str, limit: int = typer.Option(3),
                        provider: str = typer.Option(None)):
    """Generate pages from queued content briefs (highest opportunity first)."""
    from engine.growth.factory import generate_from_briefs

    for r in generate_from_briefs(pack, limit=limit, provider_override=provider):
        gate_summary = {k: v["passed"] for k, v in r.get("gates", {}).items()}
        typer.echo(json.dumps({"slug": r["slug"], "status": r["status"], **gate_summary}))


@app.command("build-links")
def build_links_cmd(pack: str):
    """Build internal topic-cluster links and inject them into emitted pages."""
    from engine.growth.links import build_links

    typer.echo(json.dumps(build_links(pack)))


@app.command("publish-index")
def publish_index_cmd(pack: str):
    """Generate sitemap + robots.txt; submit to GSC/IndexNow when creds are set."""
    from engine.growth.indexing import publish_index

    typer.echo(json.dumps(publish_index(pack)))


@app.command("import-gsc")
def import_gsc_cmd(pack: str, days: int = typer.Option(7)):
    """Import Search Console metrics via API (needs GSC_SA_JSON)."""
    from engine.growth.gsc import import_gsc

    typer.echo(json.dumps(import_gsc(pack, days=days)))


@app.command("find-opportunities")
def find_opportunities_cmd(pack: str):
    """Apply improvement rules to real traffic data; queue page work."""
    from engine.growth.rules import find_opportunities

    typer.echo(json.dumps(find_opportunities(pack), indent=1))


@app.command("daily-growth")
def daily_growth_cmd(pack: str, provider: str = typer.Option(None),
                     skip_publish: bool = typer.Option(False, help="skip next build")):
    """Run the full daily traffic loop for a pack (cron this)."""
    from engine.growth.daily import daily_growth

    typer.echo(json.dumps(daily_growth(pack, provider_override=provider,
                                       skip_publish=skip_publish), indent=1))


@app.command("gateway-check")
def gateway_check():
    """Hit the live chat endpoint and probe the embedding endpoint."""
    from engine.config import settings as cfg
    from engine.gateway.embeddings import HttpEmbedder
    from engine.gateway.providers import OpenAIProvider

    chat = OpenAIProvider(cfg().llm_base)
    reply = chat.chat([{"role": "user", "content": "Reply with exactly: PONG"}], max_tokens=8)
    typer.echo(f"chat {cfg().llm_base}: {reply.strip()[:40]!r}")
    emb = HttpEmbedder()
    v = emb.embed("gateway check")
    typer.echo(f"embed {cfg().embed_base}: mode={emb._mode} dim={v.shape[0]} norm={float(v @ v):.3f}")


@app.command("serve-tracker")
def serve_tracker(port: int = 8000, host: str = "127.0.0.1"):
    """Run the click/postback tracker."""
    import uvicorn

    uvicorn.run("engine.tracker.app:app", host=host, port=port, log_level="warning")


@app.command("expire")
def expire_cmd():
    """Resolve pending clicks past their attribution window as expired (cron-able)."""
    from datetime import UTC, datetime

    from engine.bandit.store import expire_stale

    typer.echo(json.dumps({"expired": expire_stale(datetime.now(UTC))}))


@app.command("import-metrics")
def import_metrics(file: str):
    """Import search metrics CSV (page_slug,date,impressions,clicks,position[,sessions])."""
    from engine.scorer.importers.gsc_csv import import_csv

    typer.echo(json.dumps({"imported_rows": import_csv(file)}))


@app.command("score-niches")
def score_niches():
    """Compute per-test-cell niche scores and kill/scale recommendations."""
    from engine.scorer.score import score_cells

    for c in score_cells():
        typer.echo(json.dumps({"cell": c.cell_slug, "score": c.score,
                               "recommendation": c.recommendation, **c.metrics}))


@app.command("bandit-report")
def bandit_report():
    """Per-offer click/conversion/revenue table (same data as tracker /report)."""
    from engine.db.pool import pool

    with pool().connection() as conn:
        rows = conn.execute(
            "SELECT o.slug, count(c.id), count(c.id) FILTER (WHERE c.status='converted'), "
            "count(c.id) FILTER (WHERE c.status='expired'), "
            "count(c.id) FILTER (WHERE c.status='pending'), COALESCE(sum(cv.revenue),0)::float "
            "FROM offers o LEFT JOIN clicks c ON c.offer_id = o.id "
            "LEFT JOIN conversions cv ON cv.click_id = c.id "
            "GROUP BY o.slug ORDER BY 6 DESC"
        ).fetchall()
    for r in rows:
        typer.echo(json.dumps({"offer": r[0], "clicks": r[1], "converted": r[2],
                               "expired": r[3], "pending": r[4], "revenue": r[5]}))


@app.command("bandit-sim")
def bandit_sim(steps: int = 600, seed: int = 0):
    """Run the in-memory bandit simulation with the reference ground truth."""
    from engine.sim.simulate import OfferTruth, run_sim

    truths = [
        OfferTruth(1, 0.08, 10.0, 10.0),
        OfferTruth(2, 0.03, 60.0, 60.0),
        OfferTruth(3, 0.05, 20.0, 20.0),
    ]
    r = run_sim(truths, steps=steps, seed=seed)
    typer.echo(
        json.dumps(
            {
                "picks": len(r.picks),
                "conversions": r.conversions,
                "expired": r.expired,
                "revenue": round(r.revenue, 2),
                "allocation_best_arm_last20pct": round(r.allocation(2), 3),
            }
        )
    )


if __name__ == "__main__":
    app()
