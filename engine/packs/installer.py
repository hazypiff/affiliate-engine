"""Pack installer: validates a pack dir and upserts it into the DB (idempotent)."""

import json
from pathlib import Path

import yaml

from engine.datasets.base import get_adapter
from engine.db.pool import pool
from engine.packs.schema import ComplianceSpec, PackManifest, ProgramSpec

DEFAULT_TENANT = ("default", "Default Tenant")


def load_pack(pack_dir: str | Path) -> tuple[PackManifest, list[ProgramSpec], ComplianceSpec]:
    d = Path(pack_dir)
    manifest = PackManifest.model_validate(yaml.safe_load((d / "pack.yaml").read_text()))
    programs = [
        ProgramSpec.model_validate(p) for p in yaml.safe_load((d / "programs.yaml").read_text())
    ]
    compliance = ComplianceSpec.model_validate(json.loads((d / "compliance.json").read_text()))
    return manifest, programs, compliance


def install(pack_dir: str | Path) -> dict:
    d = Path(pack_dir)
    manifest, programs, compliance = load_pack(d)

    counts = {"programs": 0, "offers": 0, "dataset_rows": 0, "slots": 0}
    with pool().connection() as conn:
        tenant_id = conn.execute(
            "INSERT INTO tenants (slug, name) VALUES (%s, %s) "
            "ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name RETURNING id",
            DEFAULT_TENANT,
        ).fetchone()[0]

        v = manifest.vertical
        vertical_id = conn.execute(
            "INSERT INTO verticals (tenant_id, slug, name, domain) VALUES (%s, %s, %s, %s) "
            "ON CONFLICT (tenant_id, slug) DO UPDATE SET name = EXCLUDED.name, "
            "domain = EXCLUDED.domain RETURNING id",
            (tenant_id, v.slug, v.name, v.domain),
        ).fetchone()[0]

        full_manifest = {
            "manifest": manifest.model_dump(),
            "compliance": compliance.model_dump(),
            "pack_dir": str(d.resolve()),
        }
        conn.execute(
            "INSERT INTO niche_packs (tenant_id, vertical_id, slug, version, manifest) "
            "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (tenant_id, slug) DO UPDATE SET "
            "version = EXCLUDED.version, manifest = EXCLUDED.manifest, installed_at = now()",
            (tenant_id, vertical_id, manifest.slug, manifest.version, json.dumps(full_manifest)),
        )

        ds = manifest.dataset
        dataset_id = conn.execute(
            "INSERT INTO datasets (tenant_id, vertical_id, slug, adapter, config) "
            "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (tenant_id, slug) DO UPDATE SET "
            "adapter = EXCLUDED.adapter, config = EXCLUDED.config RETURNING id",
            (tenant_id, vertical_id, ds.slug, ds.adapter,
             json.dumps({"file": str((d / ds.file).resolve()), "entity_key": ds.entity_key})),
        ).fetchone()[0]

        adapter = get_adapter(ds.adapter, {"file": d / ds.file, "entity_key": ds.entity_key})
        for entity_key, data in adapter.rows():
            conn.execute(
                "INSERT INTO dataset_rows (tenant_id, dataset_id, entity_key, data) "
                "VALUES (%s, %s, %s, %s) ON CONFLICT (dataset_id, entity_key) DO UPDATE SET "
                "data = EXCLUDED.data, updated_at = now()",
                (tenant_id, dataset_id, entity_key, json.dumps(data)),
            )
            counts["dataset_rows"] += 1

        slot_ids = []
        for s in manifest.slots:
            sid = conn.execute(
                "INSERT INTO slots (tenant_id, vertical_id, slug, description) "
                "VALUES (%s, %s, %s, %s) ON CONFLICT (tenant_id, slug) DO UPDATE SET "
                "description = EXCLUDED.description RETURNING id",
                (tenant_id, vertical_id, s.slug, s.description),
            ).fetchone()[0]
            slot_ids.append(sid)
            counts["slots"] += 1

        for prog in programs:
            program_id = conn.execute(
                "INSERT INTO affiliate_programs (tenant_id, vertical_id, slug, name, network, "
                "payout_model, payout, cookie_window_days) VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (tenant_id, slug) DO UPDATE SET name = EXCLUDED.name, "
                "network = EXCLUDED.network, payout = EXCLUDED.payout, "
                "cookie_window_days = EXCLUDED.cookie_window_days RETURNING id",
                (tenant_id, vertical_id, prog.slug, prog.name, prog.network, prog.payout_model,
                 json.dumps(prog.payout), prog.cookie_window_days),
            ).fetchone()[0]
            counts["programs"] += 1
            for offer in prog.offers:
                offer_id = conn.execute(
                    "INSERT INTO offers (tenant_id, program_id, slug, name, url_template, "
                    "payout_amount, geo_allow) VALUES (%s, %s, %s, %s, %s, %s, %s) "
                    "ON CONFLICT (tenant_id, slug) DO UPDATE SET name = EXCLUDED.name, "
                    "url_template = EXCLUDED.url_template, payout_amount = EXCLUDED.payout_amount, "
                    "geo_allow = EXCLUDED.geo_allow RETURNING id",
                    (tenant_id, program_id, offer.slug, offer.name, offer.url_template,
                     offer.payout_amount, offer.geo_allow),
                ).fetchone()[0]
                counts["offers"] += 1
                # v1: every pack offer is eligible in every pack slot
                for sid in slot_ids:
                    conn.execute(
                        "INSERT INTO slot_offers (slot_id, offer_id) VALUES (%s, %s) "
                        "ON CONFLICT DO NOTHING",
                        (sid, offer_id),
                    )

        conn.execute(
            "INSERT INTO test_cells (tenant_id, vertical_id, slug, page_target) "
            "VALUES (%s, %s, %s, %s) ON CONFLICT (tenant_id, slug) DO NOTHING",
            (tenant_id, vertical_id, manifest.test_cell.slug, manifest.test_cell.page_target),
        )
    return counts
