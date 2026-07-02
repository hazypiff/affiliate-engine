-- Growth loop: keyword discovery -> briefs -> pages -> links -> indexing -> improvement.

CREATE TABLE IF NOT EXISTS keyword_seeds (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id   BIGINT NOT NULL REFERENCES tenants(id),
    vertical_id BIGINT NOT NULL REFERENCES verticals(id),
    keyword     TEXT NOT NULL,
    source      TEXT NOT NULL DEFAULT 'pack',   -- pack | manual
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (vertical_id, keyword)
);

CREATE TABLE IF NOT EXISTS keyword_clusters (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id   BIGINT NOT NULL REFERENCES tenants(id),
    vertical_id BIGINT NOT NULL REFERENCES verticals(id),
    slug        TEXT NOT NULL,
    name        TEXT NOT NULL,
    UNIQUE (vertical_id, slug)
);

CREATE TABLE IF NOT EXISTS keyword_ideas (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id     BIGINT NOT NULL REFERENCES tenants(id),
    vertical_id   BIGINT NOT NULL REFERENCES verticals(id),
    cluster_id    BIGINT REFERENCES keyword_clusters(id),
    keyword       TEXT NOT NULL,
    intent        TEXT NOT NULL,                -- review | comparison | alternatives | best | pricing | how-to
    entity_keys   TEXT[] NOT NULL DEFAULT '{}',
    search_volume INTEGER,                      -- null until a volume provider/CSV fills it
    difficulty    NUMERIC(6, 3),
    source        TEXT NOT NULL,                -- rules | llm | googleads | dataforseo | csv
    status        TEXT NOT NULL DEFAULT 'new',  -- new | planned | published | rejected
    discovered_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (vertical_id, keyword)
);

CREATE TABLE IF NOT EXISTS content_briefs (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id       BIGINT NOT NULL REFERENCES tenants(id),
    vertical_id     BIGINT NOT NULL REFERENCES verticals(id),
    keyword_idea_id BIGINT NOT NULL REFERENCES keyword_ideas(id) UNIQUE,
    page_type       TEXT NOT NULL,
    title           TEXT NOT NULL,
    slug            TEXT NOT NULL,
    entity_keys     TEXT[] NOT NULL,
    outline         JSONB NOT NULL DEFAULT '{}'::jsonb,
    opportunity     NUMERIC(8, 4) NOT NULL,
    status          TEXT NOT NULL DEFAULT 'queued',   -- queued | generated | failed
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (vertical_id, slug)
);

CREATE TABLE IF NOT EXISTS internal_links (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id    BIGINT NOT NULL REFERENCES tenants(id),
    from_page_id BIGINT NOT NULL REFERENCES pages(id),
    to_page_id   BIGINT NOT NULL REFERENCES pages(id),
    anchor       TEXT NOT NULL,
    UNIQUE (from_page_id, to_page_id)
);

CREATE TABLE IF NOT EXISTS page_opportunities (
    id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id  BIGINT NOT NULL REFERENCES tenants(id),
    page_id    BIGINT NOT NULL REFERENCES pages(id),
    rule       TEXT NOT NULL,        -- rewrite_title | expand_page | improve_cta | offer_issue | kill_or_merge | scale_cluster
    detail     JSONB NOT NULL DEFAULT '{}'::jsonb,
    status     TEXT NOT NULL DEFAULT 'open',   -- open | done | dismissed
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS page_opportunities_open_uniq
    ON page_opportunities (page_id, rule) WHERE status = 'open';

CREATE TABLE IF NOT EXISTS indexing_submissions (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id    BIGINT NOT NULL REFERENCES tenants(id),
    vertical_id  BIGINT NOT NULL REFERENCES verticals(id),
    kind         TEXT NOT NULL,     -- sitemap | indexnow
    target       TEXT NOT NULL,
    status       TEXT NOT NULL,     -- generated | submitted | skipped_no_creds | error
    detail       JSONB NOT NULL DEFAULT '{}'::jsonb,
    submitted_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS daily_growth_runs (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id   BIGINT NOT NULL REFERENCES tenants(id),
    vertical_id BIGINT NOT NULL REFERENCES verticals(id),
    ran_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    report      JSONB NOT NULL
);
