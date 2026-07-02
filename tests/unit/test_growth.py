"""Growth loop pure logic: discovery expansion, opportunity scoring, improvement
rules, sitemap generation, fact tables."""

from engine.growth.discovery import _guess_intent, rule_expansion
from engine.growth.indexing import sitemap_xml
from engine.growth.planner import opportunity_score
from engine.growth.rules import evaluate_page
from engine.growth.templates import facts_table

ENTITIES = {
    "kit": {"name": "Kit", "category": "email marketing", "pricing_from_usd_month": "25"},
    "getresponse": {"name": "GetResponse", "category": "email marketing",
                    "pricing_from_usd_month": "19"},
    "elevenlabs": {"name": "ElevenLabs", "category": "ai voice",
                   "pricing_from_usd_month": "5"},
}


def test_rule_expansion_covers_intents_and_is_deterministic():
    a = rule_expansion(ENTITIES, ["review", "comparison", "alternatives", "best"], ["kit vs x"])
    b = rule_expansion(ENTITIES, ["review", "comparison", "alternatives", "best"], ["kit vs x"])
    assert a == b
    keywords = {i["keyword"] for i in a}
    assert "kit review" in keywords
    assert "kit vs getresponse" in keywords or "getresponse vs kit" in keywords
    assert "best email marketing tools" in keywords


def test_alternatives_ideas_include_category_peers():
    ideas = rule_expansion(ENTITIES, ["alternatives"], [])
    kit_alt = next(i for i in ideas if i["keyword"] == "kit alternatives")
    assert "getresponse" in kit_alt["entity_keys"]  # peer, same category
    assert "elevenlabs" not in kit_alt["entity_keys"]  # different category


def test_guess_intent():
    assert _guess_intent("kit vs getresponse") == "comparison"
    assert _guess_intent("elevenlabs alternatives") == "alternatives"
    assert _guess_intent("best ai voice generator") == "best"
    assert _guess_intent("surfer pricing") == "pricing"


def test_opportunity_score_shape():
    # unknown volume gets neutral 0.5, not zero — the loop must work pre-API
    s = opportunity_score(None, "comparison", affiliate_value=90, topical_fit=1.0, difficulty=None)
    assert 0.4 < s < 0.5
    # entity we have no data on is heavily discounted
    weak = opportunity_score(None, "comparison", 90, topical_fit=0.3, difficulty=None)
    assert weak < 0.15
    # volume and difficulty move the score in the right directions
    assert opportunity_score(2000, "comparison", 90, 1.0, None) > s
    assert opportunity_score(None, "comparison", 90, 1.0, 2.0) < s


def test_improvement_rules_fire_on_the_right_signals():
    base = {"impressions": 0, "serp_clicks": 0, "avg_position": None,
            "offer_clicks": 0, "conversions": 0, "age_days": 10}
    assert evaluate_page(base) == []
    rules = {o["rule"] for o in evaluate_page({**base, "impressions": 500, "serp_clicks": 2})}
    assert "rewrite_title" in rules
    rules = {o["rule"] for o in evaluate_page({**base, "avg_position": 12.0})}
    assert "expand_page" in rules
    rules = {o["rule"] for o in evaluate_page({**base, "impressions": 300, "serp_clicks": 15})}
    assert "improve_cta" in rules
    rules = {o["rule"] for o in evaluate_page({**base, "offer_clicks": 25})}
    assert "offer_issue" in rules
    rules = {o["rule"] for o in evaluate_page({**base, "age_days": 90})}
    assert "kill_or_merge" in rules
    # healthy page with impressions triggers nothing
    healthy = {"impressions": 500, "serp_clicks": 25, "avg_position": 3.2,
               "offer_clicks": 10, "conversions": 2, "age_days": 90}
    assert evaluate_page(healthy) == []


def test_sitemap_xml():
    xml = sitemap_xml(["https://x.test/a/", "https://x.test/b/"], "2026-07-02")
    assert xml.count("<url>") == 2
    assert "https://x.test/a/" in xml and "2026-07-02" in xml
    assert xml.startswith('<?xml version="1.0"')


def test_facts_table_is_grounded_markdown():
    table = facts_table({k: ENTITIES[k] for k in ("kit", "getresponse")})
    assert "| Kit | GetResponse |" in table
    assert "| pricing from usd month | 25 | 19 |" in table
