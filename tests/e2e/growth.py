"""Growth-loop e2e: fresh test DB -> install pack -> daily-growth (mock, no site
rebuild) -> assert every stage produced work -> feed crafted metrics -> assert the
improvement rules queue the right page work. Run via `make e2e` after smoke.py."""

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE = str(ROOT / ".venv" / "bin" / "engine")
ENV = {**os.environ, "ENGINE_DB": "test"}


def run(cmd):
    return subprocess.run(cmd, env=ENV, check=True, capture_output=True, text=True).stdout


def main():
    print("[1/5] fresh test DB + pack")
    subprocess.run(
        ["docker", "exec", "nj-pg", "psql", "-U", "njbot", "-d", "affiliate_engine_test",
         "-c", "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"],
        check=True, capture_output=True,
    )
    run([ENGINE, "init-db"])
    run([ENGINE, "install-pack", str(ROOT / "packs" / "ai-saas")])

    print("[2/5] daily-growth (mock provider, skip site rebuild)")
    report = json.loads(run([ENGINE, "daily-growth", "ai-saas", "--provider", "mock",
                             "--skip-publish"]))
    assert report["discover"]["new_keywords"] > 10, report["discover"]
    assert report["plan"]["briefs_queued"] > 5, report["plan"]
    assert 0 < report["generate"]["published"] <= report["publish_limit"], report["generate"]
    assert report["links"]["links"] > 0, report["links"]
    assert report["indexing"]["urls"] == report["generate"]["published"]
    assert report["indexing"]["gsc"] == "skipped_no_creds"
    assert "skipped" in report["gsc_import"]
    sitemap = ROOT / "site" / "out" / "sitemap-ai-saas.xml"
    assert sitemap.exists() and "<urlset" in sitemap.read_text()

    print("[3/5] second run is incremental (no duplicate keywords, more pages)")
    report2 = json.loads(run([ENGINE, "daily-growth", "ai-saas", "--provider", "mock",
                              "--skip-publish"]))
    assert report2["discover"]["new_keywords"] == 0, report2["discover"]
    assert report2["generate"]["published"] > 0

    print("[4/5] crafted metrics -> improvement rules fire")
    slugs = report["generate"]["slugs"] + report2["generate"]["slugs"]
    csv = ROOT / "site" / "content" / "_growth_e2e_metrics.csv"
    csv.write_text(
        "page_slug,date,impressions,clicks,position,sessions\n"
        f"{slugs[0]},2026-01-20,500,2,4.0,2\n"      # high impressions, CTR 0.4% -> rewrite_title
        f"{slugs[1]},2026-01-20,300,15,12.0,12\n"   # position 12 -> expand_page; clicks no CTA -> improve_cta
    )
    run([ENGINE, "import-metrics", str(csv)])
    opps = json.loads(run([ENGINE, "find-opportunities", "ai-saas"]))
    rules = {(o["page"], o["rule"]) for o in opps["queue"]}
    assert (slugs[0], "rewrite_title") in rules, opps
    assert (slugs[1], "expand_page") in rules, opps
    assert (slugs[1], "improve_cta") in rules, opps
    # idempotent: re-running opens nothing new
    again = json.loads(run([ENGINE, "find-opportunities", "ai-saas"]))
    assert again["new_opportunities"] == 0

    print("[5/6] link building: assets -> prospects -> drafts -> snapshot")
    assets = json.loads(run([ENGINE, "build-assets", "ai-saas", "--with-study",
                             "--provider", "mock"]))
    assert assets["study"]["status"] == "published", assets
    widget_file = ROOT / "site" / "public" / "widgets" / "ai-saas-stats.html"
    assert widget_file.exists() and "aitoolfacts" in widget_file.read_text()

    pcsv = ROOT / "site" / "content" / "_e2e_prospects.csv"
    pcsv.write_text("domain,url,contact,reason\n"
                    "blog-a.example,,ed@blog-a.example,ranks email tools\n"
                    "blog-b.example,,,covers saas pricing\n")
    assert json.loads(run([ENGINE, "import-prospects", "ai-saas", str(pcsv)]))[
        "prospects_added"] == 2
    drafted = json.loads(run([ENGINE, "draft-outreach", "ai-saas", "--provider", "mock"]))
    assert drafted["drafted"] == 2, drafted
    queue = [json.loads(line) for line in run([ENGINE, "outreach-queue", "ai-saas"]).splitlines()]
    assert len(queue) == 2 and "ranks email tools" in queue[0]["body"]
    assert json.loads(run([ENGINE, "mark-outreach", "ai-saas", "blog-a.example",
                           "--status", "sent"]))["updated"]
    bcsv = ROOT / "site" / "content" / "_e2e_backlinks.csv"
    bcsv.write_text("Site,Linking pages,Target pages\nref-a.example,10,2\nref-b.example,3,1\n")
    snap = json.loads(run([ENGINE, "import-backlinks", "ai-saas", str(bcsv),
                           "--date", "2026-01-25"]))
    assert snap["referring_domains"] == 2 and snap["total_links"] == 13

    print("[6/6] growth run rows recorded")
    out = subprocess.run(
        ["docker", "exec", "nj-pg", "psql", "-U", "njbot", "-d", "affiliate_engine_test",
         "-tAc", "SELECT count(*) FROM daily_growth_runs"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    assert int(out) == 2, out

    print("growth e2e PASSED")


if __name__ == "__main__":
    sys.exit(main())
