"""Integration: censored accounting in the DB store (runs against the test database)."""

import os
from datetime import UTC, datetime, timedelta

import pytest

os.environ["ENGINE_DB"] = "test"

from engine.bandit import store  # noqa: E402
from engine.db.pool import pool, reset_pool  # noqa: E402

NOW = datetime(2026, 1, 1, tzinfo=UTC)


@pytest.fixture(scope="module", autouse=True)
def fresh_db():
    reset_pool()
    with pool().connection() as conn:
        conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public")
    from engine.db.migrate import migrate

    migrate()
    with pool().connection() as conn:
        tenant_id = conn.execute(
            "INSERT INTO tenants (slug, name) VALUES ('default', 'T') RETURNING id"
        ).fetchone()[0]
        vertical_id = conn.execute(
            "INSERT INTO verticals (tenant_id, slug, name, domain) "
            "VALUES (%s, 'v', 'V', 'v.test') RETURNING id",
            (tenant_id,),
        ).fetchone()[0]
        program_id = conn.execute(
            "INSERT INTO affiliate_programs (tenant_id, vertical_id, slug, name, network, "
            "payout_model, cookie_window_days) VALUES (%s, %s, 'p', 'P', 'mocknet', 'cpa', 30) "
            "RETURNING id",
            (tenant_id, vertical_id),
        ).fetchone()[0]
        offer_id = conn.execute(
            "INSERT INTO offers (tenant_id, program_id, slug, name, url_template, payout_amount, "
            "geo_allow) VALUES (%s, %s, 'o', 'O', 'https://x.test?subid={click_id}', 100, "
            "'{NJ}') RETURNING id",
            (tenant_id, program_id),
        ).fetchone()[0]
        slot_id = conn.execute(
            "INSERT INTO slots (tenant_id, vertical_id, slug) VALUES (%s, %s, 's') RETURNING id",
            (tenant_id, vertical_id),
        ).fetchone()[0]
        conn.execute("INSERT INTO slot_offers VALUES (%s, %s)", (slot_id, offer_id))
    yield
    reset_pool()


def test_geo_default_deny():
    assert store.arms_for_slot("s", geo=None, now=NOW) == []
    assert store.arms_for_slot("s", geo="TX", now=NOW) == []
    assert len(store.arms_for_slot("s", geo="NJ", now=NOW)) == 1


def test_immature_clicks_stay_out_of_posterior_and_expiry_resolves_them():
    subid, url = store.record_click("s", _offer(), NOW, geo="NJ")
    assert subid in url

    arm = store.arms_for_slot("s", geo="NJ", now=NOW)[0]
    assert arm.pending == 1 and arm.converted == 0 and arm.expired == 0
    assert arm.posterior() == (1.0, 1.0)  # untouched prior while immature

    # postback arrives on day 2, but the click only enters the posterior once MATURE
    # (past the 30-day window) — early-resolving conversions must not bias the estimate
    assert store.record_conversion(subid, 100.0, NOW + timedelta(days=2))
    arm = store.arms_for_slot("s", geo="NJ", now=NOW + timedelta(days=2))[0]
    assert arm.converted == 0 and arm.pending == 1
    arm = store.arms_for_slot("s", geo="NJ", now=NOW + timedelta(days=31))[0]
    assert arm.converted == 1 and arm.pending == 0
    assert arm.payout_estimate() == 100.0
    assert not store.record_conversion(subid, 100.0, NOW)  # idempotent

    # a second click never converts: mature counts as failure even BEFORE the expiry
    # job runs, and the job then resolves it durably
    subid2, _ = store.record_click("s", _offer(), NOW + timedelta(days=1), geo="NJ")
    arm = store.arms_for_slot("s", geo="NJ", now=NOW + timedelta(days=32))[0]
    assert arm.expired == 1  # de facto expired (mature + still pending)
    assert store.expire_stale(NOW + timedelta(days=32)) == 1
    arm = store.arms_for_slot("s", geo="NJ", now=NOW + timedelta(days=32))[0]
    assert arm.expired == 1
    # late postback after expiry is refused (censored forever)
    assert not store.record_conversion(subid2, 100.0, NOW + timedelta(days=33))


def _offer() -> int:
    with pool().connection() as conn:
        return conn.execute("SELECT id FROM offers LIMIT 1").fetchone()[0]
