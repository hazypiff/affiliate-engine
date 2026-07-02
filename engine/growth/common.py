"""Shared growth-loop helpers: pack/vertical lookups used by every stage."""

import re

from engine.db.pool import pool


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def load_pack_context(pack_slug: str, tenant_id: int = 1) -> dict:
    """Pack manifest + vertical + dataset entities, one round trip."""
    with pool().connection() as conn:
        row = conn.execute(
            "SELECT p.manifest, p.vertical_id, v.slug, v.domain FROM niche_packs p "
            "JOIN verticals v ON v.id = p.vertical_id WHERE p.tenant_id = %s AND p.slug = %s",
            (tenant_id, pack_slug),
        ).fetchone()
        if not row:
            raise ValueError(f"pack not installed: {pack_slug}")
        manifest = row[0]
        entities = conn.execute(
            "SELECT r.entity_key, r.data FROM dataset_rows r JOIN datasets d ON d.id = r.dataset_id "
            "WHERE d.tenant_id = %s AND d.slug = %s ORDER BY r.entity_key",
            (tenant_id, manifest["manifest"]["dataset"]["slug"]),
        ).fetchall()
    return {
        "manifest": manifest["manifest"],
        "compliance": manifest["compliance"],
        "pack_dir": manifest["pack_dir"],
        "traffic": manifest["manifest"].get("traffic") or {},
        "vertical_id": row[1],
        "vertical_slug": row[2],
        "domain": row[3],
        "entities": {k: d for k, d in entities},
    }


def ensure_cluster(conn, tenant_id: int, vertical_id: int, name: str) -> int:
    slug = slugify(name) or "general"
    return conn.execute(
        "INSERT INTO keyword_clusters (tenant_id, vertical_id, slug, name) VALUES (%s, %s, %s, %s) "
        "ON CONFLICT (vertical_id, slug) DO UPDATE SET name = EXCLUDED.name RETURNING id",
        (tenant_id, vertical_id, slug, name),
    ).fetchone()[0]
