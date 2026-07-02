"""Generation pipeline: pack manifest -> entity plan -> grounded draft -> gates -> emit.

Pages that pass every gate are marked published and written to site/content/ for the
Next.js build; failures are stored with their gate_results for `engine gate-report`.
"""

import json
import re
from pathlib import Path

from engine.db.pool import pool
from engine.gateway.client import generate as llm_generate
from engine.gateway.embeddings import get_embedder
from engine.pipeline import gates

SITE_CONTENT = Path(__file__).resolve().parents[2] / "site" / "content"


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _facts_block(data: dict) -> str:
    return "\n".join(f"- {k.replace('_', ' ')}: {v}" for k, v in data.items() if v != "")


def _load_pack(conn, pack_slug: str, tenant_id: int) -> dict:
    row = conn.execute(
        "SELECT p.manifest, p.vertical_id, v.slug FROM niche_packs p "
        "JOIN verticals v ON v.id = p.vertical_id "
        "WHERE p.tenant_id = %s AND p.slug = %s",
        (tenant_id, pack_slug),
    ).fetchone()
    if not row:
        raise ValueError(f"pack not installed: {pack_slug}")
    return {"manifest": row[0], "vertical_id": row[1], "vertical_slug": row[2]}


def _vec_to_pg(vec) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in vec.tolist()) + "]"


def _pg_to_vec(text: str):
    import numpy as np

    return np.asarray(json.loads(text), dtype=np.float32)


def generate_pages(
    pack_slug: str, count: int = 3, provider_override: str | None = None, tenant_id: int = 1
) -> list[dict]:
    import numpy as np  # noqa: F401  (used via _pg_to_vec)

    with pool().connection() as conn:
        pack = _load_pack(conn, pack_slug, tenant_id)
        manifest = pack["manifest"]["manifest"]
        compliance = pack["manifest"]["compliance"]
        pack_dir = Path(pack["manifest"]["pack_dir"])
        vertical_id = pack["vertical_id"]
        vertical_slug = pack["vertical_slug"]
        page_type = manifest["page_types"][0]
        prompt_template = (pack_dir / page_type["prompt"]).read_text()

        cell = conn.execute(
            "SELECT id FROM test_cells WHERE tenant_id = %s AND slug = %s",
            (tenant_id, manifest["test_cell"]["slug"]),
        ).fetchone()
        cell_id = cell[0] if cell else None

        rows = conn.execute(
            "SELECT r.entity_key, r.data FROM dataset_rows r "
            "JOIN datasets d ON d.id = r.dataset_id "
            "WHERE d.tenant_id = %s AND d.slug = %s ORDER BY r.entity_key LIMIT %s",
            (tenant_id, manifest["dataset"]["slug"], count),
        ).fetchall()

        siblings = [
            _pg_to_vec(r[0])
            for r in conn.execute(
                "SELECT embedding::text FROM pages "
                "WHERE tenant_id = %s AND vertical_id = %s AND status = 'published' "
                "AND embedding IS NOT NULL",
                (tenant_id, vertical_id),
            ).fetchall()
        ]

    embedder = get_embedder(provider_override)
    results = []
    for entity_key, data in rows:
        name = data.get("name", entity_key)
        facts = _facts_block(data)
        prompt = prompt_template.replace("{entity_name}", name).replace("{facts}", facts)
        draft = llm_generate("draft", prompt, provider_override=provider_override,
                             tenant_id=tenant_id)

        disclosures = compliance["required_disclosures"]
        body = draft + "\n\n---\n\n" + "\n\n".join(f"*{d}*" for d in disclosures)
        emb = embedder.embed(draft)

        verdict = gates.run_all(
            draft=draft,
            body_with_disclosures=body,
            facts_text=facts,
            embedding=emb,
            sibling_embeddings=siblings,
            min_facts=manifest.get("min_facts_per_page", 6),
            cosine_ceiling=manifest.get("uniqueness_cosine_ceiling", 0.85),
            required_disclosures=disclosures,
            banned_phrases=compliance.get("banned_phrases", []),
        )

        slug = _slugify(f"{page_type['type']}-{entity_key}")
        title = f"{name} {page_type['type'].replace('-', ' ').title()}"
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
                (tenant_id, vertical_id, cell_id, slug, title, page_type["type"], entity_key,
                 status, body, json.dumps({"entity": data}), json.dumps(verdict),
                 _vec_to_pg(emb), status),
            )

        if verdict["passed"]:
            siblings.append(emb)
            _emit_page(vertical_slug, slug, title, page_type, body, disclosures, data)
        results.append({"slug": slug, "status": status, "gates": verdict["gates"]})

    _write_manifest()
    return results


def _emit_page(vertical_slug, slug, title, page_type, body, disclosures, entity_data):
    out_dir = SITE_CONTENT / vertical_slug
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{slug}.json").write_text(
        json.dumps(
            {
                "vertical": vertical_slug,
                "slug": slug,
                "title": title,
                "pageType": page_type["type"],
                "body": body,
                "disclosures": disclosures,
                "slots": page_type.get("slots", []),
                "entity": entity_data,
            },
            indent=1,
        )
    )


def _write_manifest():
    SITE_CONTENT.mkdir(parents=True, exist_ok=True)
    entries = []
    for p in sorted(SITE_CONTENT.glob("*/*.json")):
        entries.append({"vertical": p.parent.name, "slug": p.stem})
    (SITE_CONTENT / "manifest.json").write_text(json.dumps(entries, indent=1))


def gate_report(tenant_id: int = 1) -> dict:
    with pool().connection() as conn:
        rows = conn.execute(
            "SELECT status, count(*) FROM pages WHERE tenant_id = %s GROUP BY status", (tenant_id,)
        ).fetchall()
        failures = conn.execute(
            "SELECT slug, gate_results FROM pages WHERE tenant_id = %s AND status = 'rejected'",
            (tenant_id,),
        ).fetchall()
    return {
        "counts": {r[0]: r[1] for r in rows},
        "failures": [{"slug": f[0], "gates": f[1]["gates"]} for f in failures],
    }
