-- Link building: linkable assets (widgets/studies), prospect + outreach queue
-- (drafts are LLM-written, sending is ALWAYS human — automated link placement is
-- Google link-spam territory and is deliberately not built), backlink monitoring.

CREATE TABLE IF NOT EXISTS link_assets (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id   BIGINT NOT NULL REFERENCES tenants(id),
    vertical_id BIGINT NOT NULL REFERENCES verticals(id),
    kind        TEXT NOT NULL,          -- widget | study
    slug        TEXT NOT NULL,
    title       TEXT NOT NULL,
    url         TEXT NOT NULL,
    embed_code  TEXT NOT NULL DEFAULT '',
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (vertical_id, slug)
);

CREATE TABLE IF NOT EXISTS link_prospects (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id   BIGINT NOT NULL REFERENCES tenants(id),
    vertical_id BIGINT NOT NULL REFERENCES verticals(id),
    domain      TEXT NOT NULL,
    url         TEXT NOT NULL DEFAULT '',
    contact     TEXT NOT NULL DEFAULT '',
    reason      TEXT NOT NULL DEFAULT '',   -- why they'd care (links to competitor X, covers topic Y)
    source      TEXT NOT NULL DEFAULT 'csv',  -- csv | gap | manual
    status      TEXT NOT NULL DEFAULT 'new',  -- new | drafted | sent | linked | rejected
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (vertical_id, domain)
);

CREATE TABLE IF NOT EXISTS outreach_drafts (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id   BIGINT NOT NULL REFERENCES tenants(id),
    prospect_id BIGINT NOT NULL REFERENCES link_prospects(id) UNIQUE,
    asset_id    BIGINT REFERENCES link_assets(id),
    subject     TEXT NOT NULL,
    body        TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS backlink_snapshots (
    id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id         BIGINT NOT NULL REFERENCES tenants(id),
    vertical_id       BIGINT NOT NULL REFERENCES verticals(id),
    date              DATE NOT NULL,
    referring_domains INTEGER NOT NULL,
    total_links       INTEGER,
    source            TEXT NOT NULL DEFAULT 'gsc_csv',   -- gsc_csv | api | manual
    UNIQUE (vertical_id, date, source)
);
