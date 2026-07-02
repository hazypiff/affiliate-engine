"""Internal link builder: wires every published page into its topic cluster.

Relatedness = shared dataset entities (a "best X" hub naturally links to the
reviews/comparisons of its members). Links land in the internal_links table AND in
the emitted page JSON (a "Related" section the static site renders as crawlable
<a> links — that is what Google needs for discovery and topical structure).
"""

import json

from engine.db.pool import pool
from engine.growth.common import load_pack_context
from engine.pipeline.generate import SITE_CONTENT

MAX_LINKS_PER_PAGE = 4


def _entity_set(entity_key: str, meta: dict) -> set[str]:
    keys = set(meta.get("entity_keys") or [])
    keys.add(entity_key)
    return keys


def build_links(pack_slug: str, tenant_id: int = 1) -> dict:
    ctx = load_pack_context(pack_slug, tenant_id)
    with pool().connection() as conn:
        pages = conn.execute(
            "SELECT id, slug, title, entity_key, meta FROM pages "
            "WHERE tenant_id = %s AND vertical_id = %s AND status = 'published' ORDER BY id",
            (tenant_id, ctx["vertical_id"]),
        ).fetchall()

        links_written = 0
        related_by_slug: dict[str, list[dict]] = {}
        for pid, slug, title, ekey, meta in pages:
            mine = _entity_set(ekey, meta or {})
            scored = []
            for qid, qslug, qtitle, qekey, qmeta in pages:
                if qid == pid:
                    continue
                shared = len(mine & _entity_set(qekey, qmeta or {}))
                if shared:
                    scored.append((shared, qid, qslug, qtitle))
            scored.sort(key=lambda t: (-t[0], t[1]))
            top = scored[:MAX_LINKS_PER_PAGE]
            conn.execute("DELETE FROM internal_links WHERE from_page_id = %s", (pid,))
            for _, qid, qslug, qtitle in top:
                conn.execute(
                    "INSERT INTO internal_links (tenant_id, from_page_id, to_page_id, anchor) "
                    "VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
                    (tenant_id, pid, qid, qtitle),
                )
                links_written += 1
            related_by_slug[slug] = [{"slug": s, "title": t} for _, _, s, t in top]

    # inject into emitted page JSON so the static site renders crawlable links
    updated_files = 0
    for slug, related in related_by_slug.items():
        f = SITE_CONTENT / ctx["vertical_slug"] / f"{slug}.json"
        if f.exists():
            data = json.loads(f.read_text())
            data["related"] = related
            f.write_text(json.dumps(data, indent=1))
            updated_files += 1
    return {"pages": len(pages), "links": links_written, "files_updated": updated_files}
