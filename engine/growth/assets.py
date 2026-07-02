"""Linkable assets — the earn-links-don't-place-links half of link building.

1. WIDGET: a self-contained, embeddable HTML stats table built deterministically from
   the pack's dataset, served from the vertical's own domain. The embed snippet carries
   an attribution link, so every site that embeds it links back. Refreshed by the daily
   loop, so embeds always show live data (the reason to embed ours, not a screenshot).
2. STUDY: a data-study page ("what the numbers say across N tools/teams") compiled from
   deterministic aggregates + an LLM narrative, gated like every other page — the
   standard digital-PR linkbait target for outreach.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

from engine.db.pool import pool
from engine.gateway.client import generate as llm_generate
from engine.gateway.embeddings import get_embedder
from engine.growth.common import load_pack_context, slugify
from engine.pipeline import gates
from engine.pipeline.generate import _emit_page, _vec_to_pg, _write_manifest

SITE_PUBLIC = Path(__file__).resolve().parents[2] / "site" / "public"

STUDY_PROMPT = """You are writing the narrative for a data study titled "{title}".

STRICT RULES:
- Use ONLY the aggregate facts below. Do NOT invent numbers, prices, or percentages.
- Every number you mention must appear in the facts.
- Neutral, analytical tone; never promise outcomes and never use hype language.
- Clear markdown: an intro paragraph, "What the data shows", and a short methodology note
  saying the numbers are computed from the underlying dataset.
- Between two hundred and four hundred words (do not state a word count).

FACTS:
{facts}
"""


def numeric_aggregates(entities: dict[str, dict]) -> dict[str, dict]:
    """Per numeric column: avg/min/max across entities, rounded once so the facts
    block, the rendered table, and the gates all see identical values."""
    cols: dict[str, list[float]] = {}
    for data in entities.values():
        for k, v in data.items():
            try:
                cols.setdefault(k, []).append(float(str(v).replace(",", "")))
            except ValueError:
                continue
    out = {}
    for k, vals in cols.items():
        if len(vals) >= max(2, len(entities) // 2):
            out[k] = {"avg": round(sum(vals) / len(vals), 1),
                      "min": round(min(vals), 1), "max": round(max(vals), 1)}
    return out


def widget_html(ctx: dict, max_entities: int = 8, max_cols: int = 5) -> str:
    entities = dict(list(ctx["entities"].items())[:max_entities])
    cols: list[str] = []
    for d in entities.values():
        for k in d:
            if k not in cols and k != "name":
                cols.append(k)
    cols = cols[:max_cols]
    head = "".join(f"<th>{c.replace('_', ' ')}</th>" for c in cols)
    rows = "".join(
        "<tr><td>{}</td>{}</tr>".format(
            d.get("name", k), "".join(f"<td>{d.get(c, '—')}</td>" for c in cols)
        )
        for k, d in entities.items()
    )
    name = ctx["manifest"]["vertical"]["name"]
    return (
        "<!doctype html><meta charset='utf-8'>"
        "<style>body{font-family:system-ui;margin:8px;font-size:14px}"
        "table{border-collapse:collapse;width:100%}"
        "th,td{border:1px solid #e2e8f0;padding:4px 8px;text-align:left}"
        "footer{margin-top:6px;font-size:12px;color:#475569}</style>"
        f"<table><tr><th>name</th>{head}</tr>{rows}</table>"
        f"<footer>Data: <a href='https://{ctx['domain']}/' rel='noopener'>{name}</a>, "
        f"updated {datetime.now(UTC).date().isoformat()}</footer>"
    )


def build_widget(pack_slug: str, tenant_id: int = 1) -> dict:
    ctx = load_pack_context(pack_slug, tenant_id)
    slug = f"{ctx['vertical_slug']}-stats"
    out = SITE_PUBLIC / "widgets"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{slug}.html").write_text(widget_html(ctx))

    url = f"https://{ctx['domain']}/widgets/{slug}.html"
    title = f"{ctx['manifest']['vertical']['name']} live stats widget"
    embed = (
        f'<iframe src="{url}" width="100%" height="320" loading="lazy" '
        f'title="{title}"></iframe>\n'
        f'<p>Source: <a href="https://{ctx["domain"]}/">{ctx["manifest"]["vertical"]["name"]}</a></p>'
    )
    with pool().connection() as conn:
        conn.execute(
            "INSERT INTO link_assets (tenant_id, vertical_id, kind, slug, title, url, embed_code) "
            "VALUES (%s, %s, 'widget', %s, %s, %s, %s) "
            "ON CONFLICT (vertical_id, slug) DO UPDATE SET title = EXCLUDED.title, "
            "url = EXCLUDED.url, embed_code = EXCLUDED.embed_code, updated_at = now()",
            (tenant_id, ctx["vertical_id"], slug, title, url, embed),
        )
    return {"widget": slug, "url": url}


def build_study(pack_slug: str, tenant_id: int = 1,
                provider_override: str | None = None) -> dict:
    ctx = load_pack_context(pack_slug, tenant_id)
    entities = ctx["entities"]
    aggs = numeric_aggregates(entities)
    if not aggs:
        return {"study": None, "reason": "no numeric columns to aggregate"}

    vname = ctx["manifest"]["vertical"]["name"]
    title = f"{vname} Data Study: What the Numbers Say"
    slug = slugify(f"{ctx['vertical_slug']}-data-study")
    facts_lines = []
    for col, a in aggs.items():
        label = col.replace("_", " ")
        facts_lines.append(f"- average {label}: {a['avg']}")
        facts_lines.append(f"- lowest {label}: {a['min']}")
        facts_lines.append(f"- highest {label}: {a['max']}")
    facts = "\n".join(facts_lines)

    draft = llm_generate("draft", STUDY_PROMPT.replace("{title}", title).replace("{facts}", facts),
                         provider_override=provider_override, tenant_id=tenant_id)
    table = ["### Aggregates", "", "| metric | average | lowest | highest |", "|---|---|---|---|"]
    table += [f"| {c.replace('_', ' ')} | {a['avg']} | {a['min']} | {a['max']} |"
              for c, a in aggs.items()]
    content = draft + "\n\n" + "\n".join(table)
    disclosures = ctx["compliance"]["required_disclosures"]
    body = content + "\n\n---\n\n" + "\n\n".join(f"*{d}*" for d in disclosures)

    embedder = get_embedder(provider_override)
    emb = embedder.embed(content)
    verdict = gates.run_all(
        draft=content, body_with_disclosures=body, facts_text=facts, embedding=emb,
        sibling_embeddings=[], min_facts=ctx["manifest"].get("min_facts_per_page", 6),
        cosine_ceiling=ctx["manifest"].get("uniqueness_cosine_ceiling", 0.85),
        required_disclosures=disclosures,
        banned_phrases=ctx["compliance"].get("banned_phrases", []),
    )
    status = "published" if verdict["passed"] else "rejected"

    with pool().connection() as conn:
        cell = conn.execute(
            "SELECT id FROM test_cells WHERE tenant_id = %s AND slug = %s",
            (tenant_id, ctx["manifest"]["test_cell"]["slug"]),
        ).fetchone()
        conn.execute(
            """
            INSERT INTO pages (tenant_id, vertical_id, test_cell_id, slug, title, page_type,
                               entity_key, status, body_md, meta, gate_results, embedding,
                               published_at)
            VALUES (%s, %s, %s, %s, %s, 'study', '_study', %s, %s, %s, %s, %s,
                    CASE WHEN %s = 'published' THEN now() END)
            ON CONFLICT (tenant_id, vertical_id, slug) DO UPDATE SET
                title = EXCLUDED.title, status = EXCLUDED.status, body_md = EXCLUDED.body_md,
                gate_results = EXCLUDED.gate_results, embedding = EXCLUDED.embedding,
                published_at = EXCLUDED.published_at
            """,
            (tenant_id, ctx["vertical_id"], cell[0] if cell else None, slug, title, status,
             body, json.dumps({"aggregates": aggs}), json.dumps(verdict), _vec_to_pg(emb),
             status),
        )
        if verdict["passed"]:
            url = f"https://{ctx['domain']}/{ctx['vertical_slug']}/{slug}/"
            conn.execute(
                "INSERT INTO link_assets (tenant_id, vertical_id, kind, slug, title, url) "
                "VALUES (%s, %s, 'study', %s, %s, %s) "
                "ON CONFLICT (vertical_id, slug) DO UPDATE SET title = EXCLUDED.title, "
                "url = EXCLUDED.url, updated_at = now()",
                (tenant_id, ctx["vertical_id"], slug, title, url),
            )

    if verdict["passed"]:
        _emit_page(ctx["vertical_slug"], slug, title, {"type": "study", "slots": []},
                   body, disclosures, {"aggregates": list(aggs)})
        _write_manifest()
    return {"study": slug, "status": status,
            "gates": {k: v["passed"] for k, v in verdict["gates"].items()}}
