# affiliate-engine

**Dynamic multi-niche organic-SEO affiliate platform.** Niches are installable config
("niche packs"), LLM models are config (a role-based gateway), and revenue optimization
is deterministic math (Thompson sampling with censored delayed-conversion accounting).
Add a niche = add a folder. No code changes.

Built from two adversarially-verified deep-research passes (2025–2026 sources; ~210
research agents, 50 claims 3-vote verified). The research findings are implemented in
code, not just documented — see [Research basis](#research-basis).

```
niche pack (config) ──► keyword discovery ──► opportunity scoring ──► content briefs
      │                  (rules + LLM +          volume × intent ×        │
      │                   API connectors)        value × fit / diff       ▼
dataset adapter ─────────────────────────► page factory ─► GATES ─► static site (Next.js export)
 (CSV / SQL / API)                          (LLM draft +     │       one DOMAIN per vertical
                                             fact tables)    │        │ internal links, sitemap,
                                                             │        │ robots, GSC/IndexNow submit
                                            rejected ◄───────┘        │ CTA links
                                                                      ▼
                        GSC metrics ◄─────────────────────────── tracker (FastAPI)
                             │                                    /go/{slot} ─ Thompson ─► 302+subid
                             ▼                                    /postback ◄── S2S conversions
                    improvement rules ──► page work queue         expiry job (attribution windows)
                    (rewrite_title, expand_page, improve_cta,          │
                     offer_issue, kill_or_merge)                       ▼
                             ▲                            niche scorer (kill/continue/scale)
                             └────────── engine daily-growth runs ALL of this, daily, per pack
```

## Why it's built this way (research → code)

| Verified finding (2025–2026) | Implementation |
|---|---|
| Google ranks "starkly different" site sections as standalone sites — no cross-niche synergy | One domain per vertical (`verticals.domain`); shared engine, isolated ranking surfaces |
| Scaled-content/thin-affiliation policies judge *value*, not production method | Publish-blocking gates: grounding (no unsupported numbers), data density floor, embedding-uniqueness ceiling, compliance |
| Click-rewarded bandits converge on high-CTR low-payout offers | Redirector ingests conversion postbacks + revenue; EV sampling = P(convert) × payout |
| Pending clicks counted as failures starve slow-converting arms; early-resolving conversions bias estimates UP | Maturity-gated posterior: a click enters only when older than its attribution window (outcome final). Verified in e2e — the biased version measurably drifts to the wrong arm |
| Thompson sampling is delay-robust (additive regret cost) | Vanilla TS base; progressive-signal "impatient bandit" filter is the documented v2 upgrade |
| US sportsbook affiliate cost is deal-type-driven: CPA reg $0 (NJ)/$200 (MI)/$350 (CO) vs $2k–$11.2k revshare licensing | sports-betting pack ships CPA-first NJ/MI/CO config with geo default-deny at the redirect |
| AI-SaaS = lowest-friction niche; verified July-2026 commissions | ai-saas pack ships Kit 50%, GetResponse 40–60%, ElevenLabs 22%, Surfer 75–125% CPA, Instantly 20% |
| No published niche kill/scale thresholds survived verification | Scorer thresholds are config; calibrate from your own first cells |

## Components

- `engine/gateway/` — role-based LLM registry (draft/polish/verify/extract/classify/embed).
  Everything speaks OpenAI-compatible APIs: local llama.cpp/Ollama/vLLM or any cloud key
  are interchangeable DB rows. Deterministic MockProvider + hash-based fake embeddings
  make the whole pipeline testable offline. Embedding client auto-probes
  `/v1/embeddings` vs llama.cpp-native `/embedding`.
- `engine/pipeline/` — facts → grounded draft → 4 gates → static-site content.
  The numeric-claim verifier normalizes `$1,299` / `50 percent` / `40-60%` and
  whitelists ordinals/years (fixture-tested).
- `engine/bandit/` — pure-math Thompson sampling (`thompson.py`, zero I/O) + the
  DB store where the censoring rule lives in exactly one SQL query.
- `engine/tracker/` — FastAPI: `/go/{slot}` (bandit pick, geo default-deny, click log,
  302 with subid), `/postback/{network}` (adapter-parsed S2S), `/expire`, `/report`.
  `X-Sim-Now` header + injected clocks make time fully testable.
- `engine/scorer/` — progressive niche test-cell scoring (publish rate → impressions →
  CTR → EPC) with kill/continue/scale output; GSC CSV importer (API importer documented).
- `packs/` — the two shipped packs; `engine/packs/` validates (pydantic) and installs.
- `site/` — Next.js 15 static export, `/[vertical]/[slug]`, JSON-LD, FTC + gambling
  disclosures, `rel="sponsored nofollow"` CTAs. Plain JSX, 4 dependencies.
- `sql/` — 16-table schema, `tenant_id` on every table (multi-tenant-ready), NUMERIC
  money end-to-end, pgvector for page embeddings.

## Recommended local model

The engine's `draft`/`extract` roles are built and tested against
**[hazypiff/LFM2.5-8B-A1B-fastagent-stage2](https://huggingface.co/hazypiff/LFM2.5-8B-A1B-fastagent-stage2)** —
an agentic/tool-calling fine-tune of LFM2.5-8B-A1B (MoE, ~1B active params, fast on
CPU) made for this system. GGUF quants ship in the repo:

```bash
# download (Q4_K_M for CPU boxes; Q5_K_M if you have headroom)
huggingface-cli download hazypiff/LFM2.5-8B-A1B-fastagent-stage2 lfm-stage2-Q4_K_M.gguf --local-dir models/

# serve it where the engine expects it (LLM_BASE in .env)
llama-server -m models/lfm-stage2-Q4_K_M.gguf --port 18080 -c 8192

# embeddings for the uniqueness gate (EMBED_BASE): any 768-dim embedding server works;
# tested with embeddinggemma-300m via llama.cpp --embedding
```

Any OpenAI-compatible endpoint works instead (Ollama, vLLM, cloud APIs) — models are
config rows, not code. Use a stronger cloud model for the `polish` role on money pages.

## Quickstart

```bash
cp .env.example .env            # set DATABASE_URL, LLM_BASE, EMBED_BASE
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
engine init-db
engine install-pack packs/ai-saas
engine install-pack packs/sports-betting
engine generate --pack ai-saas --provider mock --n 3    # offline; drop --provider for real LLM
engine gate-report
engine publish                  # next build -> site/out/ (deploy to Cloudflare Pages)
engine serve-tracker            # :8000 — /go, /postback, /expire, /report
engine score-niches
```

`make verify` = ruff + unit + integration + full e2e. `make demo-real` = live-LLM demo.

## The traffic loop (one command, cron it)

```bash
engine daily-growth ai-saas        # the whole machine, once per day per pack:
# discover keywords -> score -> queue briefs -> generate (daily_publish_limit)
# -> gates -> internal links -> next build -> sitemap/robots -> GSC/IndexNow submit
# -> GSC metrics import -> expire clicks -> niche scores -> improvement queue -> report
```

Each stage is also its own command: `discover-keywords`, `import-volumes` (CSV
volume/difficulty fill until Google Ads/DataForSEO connectors are wired),
`plan-content`, `generate-briefs`, `build-links`, `publish-index`, `import-gsc`
(needs `GSC_SA_JSON` service-account; CSV importer works without), `find-opportunities`.

Traffic design notes from the research: sitemaps are the correct indexing channel —
Google's Indexing API only covers job postings/livestreams and is deliberately not
used; internal links are emitted as crawlable `<a>` in the static HTML; keyword ideas
come free and deterministic from your own dataset (entity × intent) before any paid
API is involved. Improvement rules turn GSC data into a work queue: high impressions +
low CTR → rewrite title; position 8–20 → expand page; SERP clicks but no CTA clicks →
improve CTA; CTA clicks but no conversions → offer issue; 60+ days with zero
impressions → kill or merge.

## Adding a niche (no code)

```
packs/<slug>/
  pack.yaml        # vertical + domain, dataset ref, page types, slots, test cell, gate thresholds
  programs.yaml    # affiliate programs + offers (payout priors, geo_allow)
  compliance.json  # required disclosures, banned phrases, geo_default_deny
  prompts/*.txt    # grounded draft prompt ({entity_name}, {facts})
  data/*.csv       # the dataset (or point at a SQL/API adapter)
engine install-pack packs/<slug>
```
The density gate will refuse niches with thin data — that is by design; bring data.

## Verified results (this machine, 2026-07-02)

- `make verify` → **PASSED**: ruff clean; 24 unit+integration tests; e2e green.
- Bandit unit sim: converges to the best-EPC arm (not best-conversion) in ≥4/5 seeds
  under 1–30-step delays with censoring; all-pending arm provably keeps its prior.
- Full e2e (fresh DB → packs → 6 gated pages → `next build` → live tracker → 2,000
  HTTP clicks over a simulated 400 days with 1–10-day delayed postbacks + expiry):
  tail allocation **97.25%** to the best-EPC offer; conversions and expirations both
  recorded; scorer output: sports cell EPC $64.8/click → "scale".
- Real-LLM demo (local LFM 8B + embeddinggemma): 1 page published with every number
  verified against the dataset; 1 page correctly rejected by the density gate.
  Known limit: a small model can mislabel a stat while using real numbers — route
  money pages through a `polish` role on a stronger model.

## System info (build/verify environment)

- Ubuntu (kernel 6.17), Python 3.13.7, Node 22.22, Docker 29.5.3.
- Postgres 16 + pgvector 0.8.2 (existing container; databases `affiliate_engine`,
  `affiliate_engine_test`).
- Chat LLM: llama.cpp server (LFM2.5-8B-A1B) at `127.0.0.1:18080`, OpenAI-compatible.
- Embeddings: embeddinggemma 768-dim at `127.0.0.1:8095` (OpenAI mode auto-detected).
- Footprint: site node_modules ≈ 270 MB; Python venv ≈ 190 MB; DB < 50 MB.

## Deliberately out of scope in v1

Live domain deploys (site/out is Cloudflare Pages-ready), real affiliate-network
signups/postbacks, traffic-channel bots, GSC OAuth (CSV import now), the impatient-bandit
progressive filter (v2), pack-generator wizard, dashboards, multi-tenant auth/billing.
`tenant_id` is already on every table so multi-tenancy is additive, not a rewrite.

## Compliance notes

FTC affiliate disclosure on every page (compliance gate blocks publishing without it).
Sports-betting pages carry 21+/1-800-GAMBLER and geo default-deny at the redirect;
US sportsbook affiliates must register per state BEFORE sending paid traffic
(NJ free / MI $200 / CO $350 for CPA deals; revshare triggers real licensing).
Program TOS vary on AI-generated content — review before enabling a network.
