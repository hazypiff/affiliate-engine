#!/usr/bin/env bash
# Real-LLM demo (non-gating): regenerate pages via the live local endpoints
# (chat :18080, embeddings :8095) instead of the mock provider, then show the
# gate verdicts and one generated page. CPU decode is slow — expect ~1-3 min/page.
set -euo pipefail
cd "$(dirname "$0")/.."
ENGINE=.venv/bin/engine

echo "== live endpoints =="
$ENGINE gateway-check

echo "== generating 2 sports pages with the REAL local LLM =="
$ENGINE generate --pack sports-betting --n 2

echo "== gate report =="
$ENGINE gate-report

echo "== sample page =="
FILE=$(ls site/content/sports-betting/*.json | head -1)
.venv/bin/python -c "import json,sys; print(json.load(open('$FILE'))['body'])"
