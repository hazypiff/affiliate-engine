"""Link-building pure logic: widget HTML, study aggregates, outreach draft template."""

from engine.growth.assets import numeric_aggregates, widget_html
from engine.growth.outreach import DRAFT_TEMPLATE

CTX = {
    "domain": "aitoolfacts.example.com",
    "manifest": {"vertical": {"name": "AI & SaaS Tools"}},
    "entities": {
        "kit": {"name": "Kit", "category": "email marketing",
                "pricing_from_usd_month": "25", "g2_rating": "4.4"},
        "getresponse": {"name": "GetResponse", "category": "email marketing",
                        "pricing_from_usd_month": "19", "g2_rating": "4.3"},
    },
}


def test_widget_html_is_selfcontained_with_attribution():
    html = widget_html(CTX)
    assert html.startswith("<!doctype html>")
    assert "<table>" in html and "Kit" in html and "GetResponse" in html
    assert "https://aitoolfacts.example.com/" in html  # the attribution backlink
    assert "http://" not in html.replace("https://", "")  # no external resources


def test_numeric_aggregates_skips_text_columns_and_rounds_once():
    aggs = numeric_aggregates(CTX["entities"])
    assert "category" not in aggs  # text column excluded
    assert aggs["pricing_from_usd_month"] == {"avg": 22.0, "min": 19.0, "max": 25.0}
    assert aggs["g2_rating"]["avg"] == 4.3  # round(4.35,1) -> 4.3 (float repr is 4.3499...)


def test_draft_template_carries_asset_and_reason():
    body = DRAFT_TEMPLATE.format(
        contact_greeting=" sam", site_name="X", site_url="https://x.test/",
        reason_line="I noticed y.example ranks email tools.",
        asset_kind="study", asset_title="The Study", asset_url="https://x.test/study/",
        domain="y.example",
    )
    assert "https://x.test/study/" in body
    assert "I noticed y.example ranks email tools." in body
    assert "Hi sam," in body
