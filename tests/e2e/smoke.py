"""End-to-end smoke: fresh test DB -> install packs -> generate (mock LLM + fake
embeddings) -> gates -> publish -> live tracker -> simulated clicks with DELAYED
postbacks -> bandit shifts allocation to the best-EPC offer -> scorer reports.

Run: make e2e   (not collected by pytest — this is the deliberate slow path)
"""

import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import requests

ROOT = Path(__file__).resolve().parents[2]
ENGINE = str(ROOT / ".venv" / "bin" / "engine")
ENV = {**os.environ, "ENGINE_DB": "test", "ENGINE_BANDIT_WINDOW_DAYS": "365",
       "ENGINE_BANDIT_SEED": "7"}
PORT = 8011
BASE = f"http://127.0.0.1:{PORT}"

# ground truth: charlie converts MOST, bravo earns most per click (EPC 66 vs 42 vs 20)
# — a click-optimizing or conversion-optimizing bandit would pick charlie; only
# revenue-weighted Thompson picks bravo.
TRUTH = {
    "alpha": {"conv": 0.08, "payout": 250.0},
    "bravo": {"conv": 0.22, "payout": 300.0},
    "charlie": {"conv": 0.28, "payout": 150.0},
}
START = datetime(2026, 1, 1, tzinfo=UTC)
STEP = timedelta(days=1)
# horizon must be long enough for explored arms to MATURE (30d attribution window):
# transient optimism toward under-sampled arms is Thompson exploration working as
# designed; convergence is asserted after exploration has had time to resolve.
STEPS = 400
CLICKS_PER_STEP = 5


def run(cmd, **kw):
    return subprocess.run(cmd, env=ENV, check=True, capture_output=True, text=True, **kw).stdout


def offer_of(location: str) -> str:
    for name in TRUTH:
        if name in location:
            return name
    raise AssertionError(f"unknown offer url: {location}")


def main():
    print("[1/7] fresh test DB")
    subprocess.run(
        ["docker", "exec", "nj-pg", "psql", "-U", "njbot", "-d", "affiliate_engine_test",
         "-c", "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"],
        check=True, capture_output=True,
    )
    run([ENGINE, "init-db"])

    print("[2/7] install packs")
    run([ENGINE, "install-pack", str(ROOT / "packs" / "ai-saas")])
    run([ENGINE, "install-pack", str(ROOT / "packs" / "sports-betting")])

    print("[3/7] generate 6 pages (mock provider) + gates")
    run([ENGINE, "generate", "--pack", "ai-saas", "--provider", "mock", "--n", "3"])
    run([ENGINE, "generate", "--pack", "sports-betting", "--provider", "mock", "--n", "3"])
    report = json.loads(run([ENGINE, "gate-report"]))
    assert report["counts"].get("published") == 6, report
    assert not report["failures"], report

    print("[4/7] publish (next build)")
    out = run([ENGINE, "publish", "--skip-install"] if (ROOT / "site" / "node_modules").exists()
              else [ENGINE, "publish"])
    assert "built:" in out, out
    html = (ROOT / "site" / "out" / "sports-betting" / "trend-report-nba-bos.html").read_text()
    assert "1-800-GAMBLER" in html and "application/ld+json" in html

    print("[5/7] tracker + simulated delayed traffic")
    proc = subprocess.Popen(
        [ENGINE, "serve-tracker", "--port", str(PORT)], env=ENV,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(50):
            try:
                requests.get(f"{BASE}/health", timeout=1)
                break
            except requests.ConnectionError:
                time.sleep(0.2)

        rng = np.random.default_rng(42)
        picks: list[str] = []
        future: list[tuple[datetime, str, float]] = []
        session = requests.Session()

        for step in range(STEPS):
            now = START + STEP * step
            hdr = {"X-Sim-Now": now.isoformat()}
            # deliver due postbacks
            due = [f for f in future if f[0] <= now]
            future = [f for f in future if f[0] > now]
            for _, subid, payout in due:
                session.get(f"{BASE}/postback/mocknet",
                            params={"subid": subid, "payout": payout}, headers=hdr, timeout=5)
            session.post(f"{BASE}/expire", headers=hdr, timeout=5)

            for _ in range(CLICKS_PER_STEP):
                r = session.get(f"{BASE}/go/sb-hero-cta",
                                params={"geo": "NJ", "page": "trend-report-nba-bos"},
                                headers=hdr, timeout=5, allow_redirects=False)
                assert r.status_code == 302, r.text
                loc = r.headers["location"]
                name = offer_of(loc)
                picks.append(name)
                subid = loc.split("subid=")[1]
                truth = TRUTH[name]
                if rng.random() < truth["conv"]:
                    delay = int(rng.integers(1, 11))  # 1-10 days, inside the 30d window
                    future.append((now + STEP * delay, subid, truth["payout"]))

        tail = picks[int(len(picks) * 0.8):]
        shares = {k: tail.count(k) / len(tail) for k in TRUTH}
        rep = session.get(f"{BASE}/report", timeout=5).json()
        print("    tail allocation:", shares)
        print("    offers:", json.dumps(rep["offers"]))
        expired = sum(o["expired"] for o in rep["offers"])
        converted = sum(o["converted"] for o in rep["offers"])
        assert converted > 0, "no conversions recorded"
        assert expired > 0, "expiry job never resolved a click"
        assert max(shares, key=shares.get) == "bravo", f"best-EPC arm not preferred: {shares}"
        assert shares["bravo"] >= 0.5, f"weak convergence: {shares}"
    finally:
        proc.terminate()
        proc.wait(timeout=10)

    print("[6/7] metrics import + niche scorer")
    csv = ROOT / "site" / "content" / "_e2e_metrics.csv"
    csv.write_text(
        "page_slug,date,impressions,clicks,position,sessions\n"
        "trend-report-nba-bos,2026-01-20,400,18,7.2,15\n"
        "trend-report-mlb-lad,2026-01-20,250,9,9.1,8\n"
        "review-gamma,2026-01-20,120,4,11.4,3\n"
    )
    imported = json.loads(run([ENGINE, "import-metrics", str(csv)]))
    assert imported["imported_rows"] == 3
    scores = [json.loads(line) for line in run([ENGINE, "score-niches"]).splitlines()]
    assert len(scores) == 2
    for s in scores:
        assert s["recommendation"] in {"scale", "continue", "kill"}
        assert 0 <= s["score"] <= 1
    sports = next(s for s in scores if s["cell"] == "sports-betting-cell-1")
    assert sports["offer_clicks"] > 0 and sports["revenue"] > 0, sports
    print("    scores:", json.dumps(scores))

    print("[7/7] e2e PASSED")


if __name__ == "__main__":
    sys.exit(main())
