"""Page factory: consumes queued content_briefs and produces gated pages.

Successor of the row-driven generator: a brief carries the target keyword, page type,
title, and the entities whose facts ground the page. The emitted body is
LLM draft + deterministic facts table + disclosures; all of it must pass the gates.
"""

import json
from pathlib import Path

from engine.db.pool import pool
from engine.gateway.client import generate as llm_generate
from engine.gateway.embeddings import get_embedder
from engine.growth.common import load_pack_context
from engine.growth.templates import TEMPLATES, facts_table
from engine.pipeline import gates
from engine.pipeline.generate import SITE_CONTENT, _emit_page, _pg_to_vec, _vec_to_pg, _write_manifest


def _facts_block(entities: dict[str, dict]) -> str:
    parts = []
    for key, data in entities.items():
        parts.append(f"{data.get('name', key)}:")
        parts.extend(f"- {k.replace('_', ' ')}: {v}" for k, v in data.items() if v != "")
        parts.append("")
    return "\n".join(parts).strip()


def _prompt_for(page_type: str, pack_dir: Path) -> str:
    override = pack_dir / "prompts" / f"{page_type}.txt"
    if override.exists():
        return override.read_text()
    if page_type not in TEMPLATES:
        raise ValueError(f"no template for page type: {page_type}")
    return TEMPLATES[page_type]


def generate_from_briefs(pack_slug: str, limit: int = 3, tenant_id: int = 1,
                         provider_override: str | None = None) -> list[dict]:
    ctx = load_pack_context(pack_slug, tenant_id)
    manifest = ctx["manifest"]
    compliance = ctx["compliance"]
    pack_dir = Path(ctx["pack_dir"])
    slots = manifest["page_types"][0].get("slots", [])

    with pool().connection() as conn:
        cell = conn.execute(
            "SELECT id FROM test_cells WHERE tenant_id = %s AND slug = %s",
            (tenant_id, manifest["test_cell"]["slug"]),
        ).fetchone()
        cell_id = cell[0] if cell else None
        briefs = conn.execute(
            "SELECT id, keyword_idea_id, page_type, title, slug, entity_keys, outline, opportunity "
            "FROM content_briefs WHERE vertical_id = %s AND status = 'queued' "
            "ORDER BY opportunity DESC, id LIMIT %s",
            (ctx["vertical_id"], limit),
        ).fetchall()
        siblings = [
            _pg_to_vec(r[0])
            for r in conn.execute(
                "SELECT embedding::text FROM pages WHERE tenant_id = %s AND vertical_id = %s "
                "AND status = 'published' AND embedding IS NOT NULL",
                (tenant_id, ctx["vertical_id"]),
            ).fetchall()
        ]

    embedder = get_embedder(provider_override)
    results = []
    for brief_id, idea_id, page_type, title, slug, entity_keys, outline, _opp in briefs:
        entities = {k: ctx["entities"][k] for k in entity_keys if k in ctx["entities"]}
        if not entities:
            _set_brief(brief_id, idea_id, "failed", "rejected")
            results.append({"slug": slug, "status": "failed", "gates": {}})
            continue
        facts = _facts_block(entities)
        keyword = (outline or {}).get("keyword", slug.replace("-", " "))
        names = ", ".join(d.get("name", k) for k, d in entities.items())
        prompt = (_prompt_for(page_type, pack_dir)
                  .replace("{keyword}", keyword)
                  .replace("{entity_name}", names)
                  .replace("{facts}", facts))
        draft = llm_generate("draft", prompt, provider_override=provider_override,
                             tenant_id=tenant_id)
        content = draft + "\n\n" + facts_table(entities)
        disclosures = compliance["required_disclosures"]
        body = content + "\n\n---\n\n" + "\n\n".join(f"*{d}*" for d in disclosures)
        emb = embedder.embed(content)

        verdict = gates.run_all(
            draft=content,
            body_with_disclosures=body,
            facts_text=facts,
            embedding=emb,
            sibling_embeddings=siblings,
            min_facts=manifest.get("min_facts_per_page", 6),
            cosine_ceiling=manifest.get("uniqueness_cosine_ceiling", 0.85),
            required_disclosures=disclosures,
            banned_phrases=compliance.get("banned_phrases", []),
        )
        status = "published" if verdict["passed"] else "rejected"

        with pool().connection() as conn:
            conn.execute(
                """
                INSERT INTO pages (tenant_id, vertical_id, test_cell_id, slug, title, page_type,
                                   entity_key, status, body_md, meta, gate_results, embedding,
                                   published_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        CASE WHEN %s = 'published' THEN now() END)
                ON CONFLICT (tenant_id, vertical_id, slug) DO UPDATE SET
                    title = EXCLUDED.title, status = EXCLUDED.status,
                    body_md = EXCLUDED.body_md, meta = EXCLUDED.meta,
                    gate_results = EXCLUDED.gate_results, embedding = EXCLUDED.embedding,
                    published_at = EXCLUDED.published_at
                """,
                (tenant_id, ctx["vertical_id"], cell_id, slug, title, page_type,
                 entity_keys[0], status, body,
                 json.dumps({"keyword": keyword, "brief_id": brief_id,
                             "entity_keys": entity_keys}),
                 json.dumps(verdict), _vec_to_pg(emb), status),
            )

        if verdict["passed"]:
            siblings.append(emb)
            _emit_page(ctx["vertical_slug"], slug, title,
                       {"type": page_type, "slots": slots}, body, disclosures,
                       {"keyword": keyword, "entities": list(entities)})
            _set_brief(brief_id, idea_id, "generated", "published")
        else:
            _set_brief(brief_id, idea_id, "failed", "rejected")
        results.append({"slug": slug, "status": status, "gates": verdict["gates"]})

    _write_manifest()
    return results


def _set_brief(brief_id: int, idea_id: int, brief_status: str, idea_status: str) -> None:
    with pool().connection() as conn:
        conn.execute("UPDATE content_briefs SET status = %s WHERE id = %s",
                     (brief_status, brief_id))
        conn.execute("UPDATE keyword_ideas SET status = %s WHERE id = %s",
                     (idea_status, idea_id))


__all__ = ["generate_from_briefs", "SITE_CONTENT"]
