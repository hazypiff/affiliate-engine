-- affiliate-engine schema v1. tenant_id on every table (multi-tenant-ready from day one).
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS tenants (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    slug        TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS verticals (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id   BIGINT NOT NULL REFERENCES tenants(id),
    slug        TEXT NOT NULL,
    name        TEXT NOT NULL,
    -- one domain per vertical: no cross-niche ranking synergy exists (see research report §1.1)
    domain      TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'active',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, slug)
);

CREATE TABLE IF NOT EXISTS niche_packs (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id    BIGINT NOT NULL REFERENCES tenants(id),
    vertical_id  BIGINT NOT NULL REFERENCES verticals(id),
    slug         TEXT NOT NULL,
    version      TEXT NOT NULL,
    manifest     JSONB NOT NULL,
    installed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, slug)
);

CREATE TABLE IF NOT EXISTS datasets (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id    BIGINT NOT NULL REFERENCES tenants(id),
    vertical_id  BIGINT NOT NULL REFERENCES verticals(id),
    slug         TEXT NOT NULL,
    adapter      TEXT NOT NULL,              -- csv | sql | api
    config       JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, slug)
);

CREATE TABLE IF NOT EXISTS dataset_rows (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id   BIGINT NOT NULL REFERENCES tenants(id),
    dataset_id  BIGINT NOT NULL REFERENCES datasets(id),
    entity_key  TEXT NOT NULL,
    data        JSONB NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (dataset_id, entity_key)
);

CREATE TABLE IF NOT EXISTS affiliate_programs (
    id                 BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id          BIGINT NOT NULL REFERENCES tenants(id),
    vertical_id        BIGINT NOT NULL REFERENCES verticals(id),
    slug               TEXT NOT NULL,
    name               TEXT NOT NULL,
    network            TEXT NOT NULL,        -- partnerstack | direct | mocknet | ...
    payout_model       TEXT NOT NULL,        -- cpa | revshare | hybrid | recurring
    payout             JSONB NOT NULL DEFAULT '{}'::jsonb,
    cookie_window_days INTEGER NOT NULL DEFAULT 30,
    status             TEXT NOT NULL DEFAULT 'active',
    UNIQUE (tenant_id, slug)
);

CREATE TABLE IF NOT EXISTS offers (
    id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id      BIGINT NOT NULL REFERENCES tenants(id),
    program_id     BIGINT NOT NULL REFERENCES affiliate_programs(id),
    slug           TEXT NOT NULL,
    name           TEXT NOT NULL,
    url_template   TEXT NOT NULL,            -- {click_id} substituted at redirect time
    -- nominal payout: the bandit's payout prior until real conversions exist (NUMERIC, never float)
    payout_amount  NUMERIC(12, 2) NOT NULL DEFAULT 0,
    geo_allow      TEXT[] NOT NULL DEFAULT '{}',  -- empty = allow all; else default-deny outside list
    status         TEXT NOT NULL DEFAULT 'active',
    UNIQUE (tenant_id, slug)
);

CREATE TABLE IF NOT EXISTS slots (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id    BIGINT NOT NULL REFERENCES tenants(id),
    vertical_id  BIGINT NOT NULL REFERENCES verticals(id),
    slug         TEXT NOT NULL,
    description  TEXT NOT NULL DEFAULT '',
    UNIQUE (tenant_id, slug)
);

CREATE TABLE IF NOT EXISTS slot_offers (
    slot_id   BIGINT NOT NULL REFERENCES slots(id),
    offer_id  BIGINT NOT NULL REFERENCES offers(id),
    PRIMARY KEY (slot_id, offer_id)
);

CREATE TABLE IF NOT EXISTS test_cells (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id    BIGINT NOT NULL REFERENCES tenants(id),
    vertical_id  BIGINT NOT NULL REFERENCES verticals(id),
    slug         TEXT NOT NULL,
    page_target  INTEGER NOT NULL DEFAULT 30,
    status       TEXT NOT NULL DEFAULT 'testing',   -- testing | scale | kill
    started_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, slug)
);

CREATE TABLE IF NOT EXISTS pages (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id     BIGINT NOT NULL REFERENCES tenants(id),
    vertical_id   BIGINT NOT NULL REFERENCES verticals(id),
    test_cell_id  BIGINT REFERENCES test_cells(id),
    slug          TEXT NOT NULL,
    title         TEXT NOT NULL,
    page_type     TEXT NOT NULL,
    entity_key    TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'draft',   -- draft | gated | published | rejected
    body_md       TEXT NOT NULL DEFAULT '',
    meta          JSONB NOT NULL DEFAULT '{}'::jsonb,
    gate_results  JSONB NOT NULL DEFAULT '{}'::jsonb,
    embedding     vector(768),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    published_at  TIMESTAMPTZ,
    UNIQUE (tenant_id, vertical_id, slug)
);

CREATE TABLE IF NOT EXISTS page_metrics (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id    BIGINT NOT NULL REFERENCES tenants(id),
    page_id      BIGINT NOT NULL REFERENCES pages(id),
    date         DATE NOT NULL,
    impressions  INTEGER NOT NULL DEFAULT 0,
    serp_clicks  INTEGER NOT NULL DEFAULT 0,
    position     NUMERIC(6, 2),
    sessions     INTEGER NOT NULL DEFAULT 0,
    UNIQUE (page_id, date)
);

CREATE TABLE IF NOT EXISTS clicks (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id   BIGINT NOT NULL REFERENCES tenants(id),
    slot_id     BIGINT NOT NULL REFERENCES slots(id),
    offer_id    BIGINT NOT NULL REFERENCES offers(id),
    page_id     BIGINT REFERENCES pages(id),
    subid       TEXT NOT NULL UNIQUE,
    geo         TEXT,
    device      TEXT,
    -- censored delayed-conversion accounting: pending clicks are NEVER treated as failures.
    status      TEXT NOT NULL DEFAULT 'pending',   -- pending | converted | expired
    clicked_at  TIMESTAMPTZ NOT NULL,
    resolved_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS clicks_offer_status_idx ON clicks (offer_id, status, clicked_at);
CREATE INDEX IF NOT EXISTS clicks_pending_idx ON clicks (status, clicked_at) WHERE status = 'pending';

CREATE TABLE IF NOT EXISTS conversions (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id     BIGINT NOT NULL REFERENCES tenants(id),
    click_id      BIGINT NOT NULL REFERENCES clicks(id) UNIQUE,
    offer_id      BIGINT NOT NULL REFERENCES offers(id),
    revenue       NUMERIC(12, 2) NOT NULL,
    converted_at  TIMESTAMPTZ NOT NULL,
    raw           JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS llm_models (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id     BIGINT NOT NULL REFERENCES tenants(id),
    slug          TEXT NOT NULL,
    endpoint_url  TEXT NOT NULL,
    api_format    TEXT NOT NULL DEFAULT 'openai',   -- openai | mock
    model_name    TEXT NOT NULL DEFAULT 'default',
    context_len   INTEGER NOT NULL DEFAULT 8192,
    cost_per_mtok NUMERIC(10, 4) NOT NULL DEFAULT 0,
    active        BOOLEAN NOT NULL DEFAULT true,
    UNIQUE (tenant_id, slug)
);

CREATE TABLE IF NOT EXISTS llm_roles (
    id                 BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id          BIGINT NOT NULL REFERENCES tenants(id),
    role               TEXT NOT NULL,   -- draft | polish | verify | extract | classify | embed
    model_id           BIGINT NOT NULL REFERENCES llm_models(id),
    fallback_model_id  BIGINT REFERENCES llm_models(id),
    max_tokens         INTEGER NOT NULL DEFAULT 2048,
    temperature        NUMERIC(3, 2) NOT NULL DEFAULT 0.7,
    UNIQUE (tenant_id, role)
);

CREATE TABLE IF NOT EXISTS niche_scores (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id     BIGINT NOT NULL REFERENCES tenants(id),
    test_cell_id  BIGINT NOT NULL REFERENCES test_cells(id),
    computed_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    window_days   INTEGER NOT NULL DEFAULT 30,
    metrics       JSONB NOT NULL,
    score         NUMERIC(8, 4) NOT NULL,
    recommendation TEXT NOT NULL   -- scale | continue | kill
);
