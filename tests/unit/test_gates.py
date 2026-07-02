import numpy as np

from engine.gateway.embeddings import FakeEmbedder
from engine.pipeline import gates
from engine.pipeline.numbers import (
    extract_numbers,
    normalize_number,
    supported_fact_numbers_used,
    unsupported_numbers,
)

FACTS = "\n".join(
    [
        "- affiliate commission: 50% recurring first 12 months",
        "- pricing from usd month: 25",
        "- cookie window days: 90",
        "- standout feature: creator automations",
        "- rating: 4.5",
        "- users: 1,299,000",
        "- languages supported: 32",
        "- integrations: 140",
    ]
)


def test_normalize_number():
    assert normalize_number("1,299") == "1299"
    assert normalize_number("50.0") == "50"
    assert normalize_number("4.50") == "4.5"


def test_extract_numbers_handles_currency_percent_ranges():
    nums = extract_numbers("costs $1,299 with 40-60% commission and 4.5 stars")
    assert {"1299", "40", "60", "4.5"} <= nums


def test_unsupported_numbers_flags_invented_values():
    draft = "It pays 50% and costs $25/month, serving 999,999 customers."
    bad = unsupported_numbers(draft, FACTS)
    assert bad == {"999999"}


def test_whitelist_allows_ordinals_and_years():
    draft = "Top 5 pick for 2026: pays 50% with a 90-day cookie window at $25."
    assert unsupported_numbers(draft, FACTS) == set()


def test_density_counts_distinct_fact_numbers():
    draft = (
        "Pays 50% for 12 months, from $25/month, 90-day cookie, 4.5 rating, "
        "1,299,000 users, 32 languages, 140 integrations."
    )
    used = supported_fact_numbers_used(draft, FACTS)
    assert len(used) >= 6  # whitelisted small numbers (12) intentionally do not count
    assert gates.density_gate(draft, FACTS, min_facts=6).passed


def test_density_fails_thin_pages():
    assert not gates.density_gate("A tool that exists and is nice.", FACTS, min_facts=6).passed


def test_uniqueness_gate_blocks_near_duplicates():
    e = FakeEmbedder()
    a = e.embed("kit review email marketing 50% recurring commission creators")
    dup = e.embed("kit review email marketing 50% recurring commission creators")
    other = e.embed("elevenlabs voice cloning api dubbing 32 languages review")
    assert not gates.uniqueness_gate(a, [dup], ceiling=0.85).passed
    assert gates.uniqueness_gate(a, [other], ceiling=0.85).passed
    assert gates.uniqueness_gate(a, [], ceiling=0.85).passed


def test_compliance_gate():
    disclosures = ["This page contains affiliate links."]
    banned = ["guaranteed win"]
    good = "Review body.\n\n*This page contains affiliate links.*"
    assert gates.compliance_gate(good, disclosures, banned).passed
    assert not gates.compliance_gate("Review body, no disclosure.", disclosures, banned).passed
    assert not gates.compliance_gate(good + " A guaranteed WIN!", disclosures, banned).passed


def test_run_all_shape():
    e = FakeEmbedder()
    draft = (
        "Pays 50% for 12 months, from $25/month, 90-day cookie, 4.5 rating, "
        "1,299,000 users, 32 languages, 140 integrations."
    )
    body = draft + "\n\n*This page contains affiliate links.*"
    verdict = gates.run_all(
        draft=draft,
        body_with_disclosures=body,
        facts_text=FACTS,
        embedding=e.embed(draft),
        sibling_embeddings=[],
        min_facts=6,
        cosine_ceiling=0.85,
        required_disclosures=["This page contains affiliate links."],
        banned_phrases=["guaranteed win"],
    )
    assert verdict["passed"] is True
    assert set(verdict["gates"]) == {"grounding", "density", "uniqueness", "compliance"}
    assert np.isclose(verdict["gates"]["uniqueness"]["max_sibling_cosine"], 0.0)
