# Instructions for LLM agents working on affiliate-engine

You are working on a config-driven multi-niche organic-SEO affiliate platform.
Read README.md for the architecture. This file is the contract: what you may
change freely, what you must never break, and how to prove your change works.

## The one-paragraph mental model

Niches are data ("packs" in `packs/`), models are data (`llm_models`/`llm_roles`
rows resolved by `engine/gateway/registry.py`), and revenue optimization is
deterministic math (`engine/bandit/`). The LLM is only the content factory —
never put an LLM in the click/money path. A page is generated from dataset
facts, must pass four gates to publish, and its CTA points at the tracker,
which picks the offer per click via Thompson sampling.

## Invariants — do not break these

1. **Censoring/maturity rule** (`engine/bandit/store.py`, one SQL query): a click
   enters the bandit posterior ONLY when older than its program's attribution
   window. Never count pending clicks as failures; never count conversions
   before the click matures (early-resolving conversions bias fresh arms up —
   the e2e demonstrably drifts to the wrong arm without this).
2. **Gates are publish-blocking.** grounding / density / uniqueness / compliance
   in `engine/pipeline/gates.py`. Never publish a page that fails a gate; never
   weaken a gate to make a test pass — enrich the dataset instead.
3. **`engine/bandit/thompson.py` stays pure math** — zero I/O, zero clocks.
4. **Time is injected.** No `datetime.now()`/`now()` in SQL on time-dependent
   paths; pass `now` explicitly (see `engine/sim/clock.py`, tracker `X-Sim-Now`).
5. **Money is NUMERIC/Decimal in SQL** — never float columns for payout/revenue.
6. **`tenant_id` on every new table and every new query.**
7. **One domain per vertical** (`verticals.domain`) — do not merge verticals
   onto one domain; there is no cross-niche ranking synergy (see README research
   table).
8. **Geo default-deny**: a non-empty `offers.geo_allow` means deny unless listed,
   enforced at the tracker redirect (SSG pages cannot geo-gate).
9. Compliance disclosure text comes from the pack's `compliance.json`; sports
   pages must keep 21+/1-800-GAMBLER lines.

## How to verify any change

```bash
make verify        # ruff + 24 unit/integration tests + full e2e — must pass
make demo-real     # optional: live local LLM (:18080) + embeddings (:8095)
```
The e2e (`tests/e2e/smoke.py`) is the definition of "working": fresh test DB,
both packs, 6 gated pages, `next build`, live tracker, 2,000 simulated clicks
over 400 sim-days with delayed postbacks; asserts ≥50% tail allocation to the
best-EPC arm (and that the best-EPC arm ≠ the best-conversion arm survives).
Test DB routing: `ENGINE_DB=test`. Bandit determinism in e2e: `ENGINE_BANDIT_SEED`.

## Environment expectations

- Postgres w/ pgvector; `DATABASE_URL`/`TEST_DATABASE_URL` in `.env` (never commit).
- Chat endpoint = any OpenAI-compatible server (`LLM_BASE`); llama.cpp quirks are
  handled in `engine/gateway/providers.py` (serial requests, long timeouts,
  fence-stripping, `<think>` removal). Embeddings auto-probe OpenAI vs native.
- Offline development: `--provider mock` everywhere. MockProvider only echoes
  lines after a `FACTS:` marker — keep that marker in pack prompts, and keep
  instruction text free of digits and banned phrases (they leak into echoes and
  legitimately fail gates).

## Adding a niche pack (the intended extension path)

Create `packs/<slug>/{pack.yaml,programs.yaml,compliance.json,prompts/,data/}`
(copy ai-saas as the template), then `engine install-pack packs/<slug>`.
Rules: dataset rows need ≥6 distinct non-whitelisted numeric facts per entity
(whitelist = integers 0–12 and years 1990–2035 — they don't count toward
density); prompt must contain `{entity_name}` and `{facts}`; disclosure strings
in compliance.json must appear verbatim in emitted pages (emit appends them).

## Known sharp edges

- `ENGINE_BANDIT_WINDOW_DAYS` (default 90) is the drift window: at low traffic a
  short window starves arms back to their optimistic priors → over-exploration.
  Size it to volume.
- Small local models keep numbers grounded but can MISLABEL a stat semantically
  (gates can't catch that) — money pages should use a stronger `polish` role.
- Next.js is `output: export`: no middleware/ISR/headers; new page data must go
  through `site/content/*.json` + `manifest.json` (written by the pipeline).
- pgvector: brute-force cosine is intentional at this scale; don't add ANN
  indexes without need (index builds eat RAM).

## Growth loop (engine/growth/)

`engine daily-growth <pack>` = discovery → planner → factory → links → build →
sitemap/GSC → metrics → scorer → rules. Its invariants:
- Discovery is rule-based-first (deterministic, from dataset entities × intents);
  LLM expansion is best-effort extra and OFF under `--provider mock`. Paid keyword
  APIs plug in as providers in `engine/growth/discovery.py` returning idea dicts.
- The factory consumes `content_briefs` by opportunity DESC, capped by the pack's
  `traffic.daily_publish_limit`. Emitted body = LLM draft + deterministic
  `facts_table()` — the table is guaranteed-grounded data density; keep it.
- `find-opportunities` decision logic lives in pure `evaluate_page()`
  (engine/growth/rules.py) — keep it DB-free so thresholds stay unit-testable.
- Never use Google's Indexing API for these pages (job postings/livestreams only);
  sitemaps + GSC submission is the correct channel. GSC/IndexNow calls must stay
  guarded (skip cleanly without creds, record status in indexing_submissions).
- Growth e2e is `tests/e2e/growth.py` (runs in `make e2e`): asserts every stage
  produced work, second run is incremental, and crafted metrics fire the rules.
- LINK BUILDING (engine/growth/{assets,outreach}.py): the system EARNS links via
  assets (embeddable widget with attribution, gated data-study pages) and prepares
  outreach (prospect queue + LLM drafts). NEVER implement automated link placement,
  auto-posting, or auto-sending of outreach — that is Google link-spam policy;
  sending is a human action recorded via `engine mark-outreach`. The widget must
  stay self-contained (no external resources) and keep its attribution link.

## v2 roadmap (documented, unbuilt — pick up here)

Impatient-bandit progressive filter (click→landing→postback Bayesian filter;
see research report §1.3), SQL dataset adapter (Tier-1 owned-DB grounding),
Google Ads / DataForSEO keyword-volume connectors (stubs in discovery.py),
query-level GSC data + cluster scaling rule, rewrite executor (consume
page_opportunities automatically), pack-generator wizard, per-slot contextual
bandits (geo/device), multi-tenant auth/billing.
