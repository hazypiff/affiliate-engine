"""Content planner: scores keyword ideas, queues briefs for the winners.

opportunity = volume_norm * intent_weight * affiliate_value_norm * topical_fit / difficulty

- volume_norm: search_volume/1000 capped at 1.0; UNKNOWN volume gets a neutral 0.5
  so the loop works before any volume provider is wired.
- intent_weight: buyer proximity (comparison/best highest).
- affiliate_value_norm: best nominal payout among the vertical's active offers / $100 cap.
- topical_fit: 1.0 when the keyword maps to known dataset entities, else 0.3 —
  we can only build data-grounded pages for entities we have facts on.
- difficulty: keyword_ideas.difficulty (0-1] if known, else 1.0 (neutral).
Briefs are created only above the pack's min_opportunity_score, and only for intents
the page factory can build (how-to needs no entity data and is deferred).
"""

import json

from engine.db.pool import pool
from engine.growth.common import load_pack_context, slugify

INTENT_WEIGHTS = {"comparison": 1.0, "best": 1.0, "alternatives": 0.95,
                  "review": 0.9, "pricing": 0.8, "how-to": 0.5}
BUILDABLE_INTENTS = {"review", "comparison", "alternatives", "best", "pricing"}


def opportunity_score(search_volume: int | None, intent: str, affiliate_value: float,
                      topical_fit: float, difficulty: float | None) -> float:
    volume_norm = 0.5 if search_volume is None else min(1.0, search_volume / 1000.0)
    value_norm = min(1.0, affiliate_value / 100.0)
    diff = float(difficulty) if difficulty else 1.0
    return round(volume_norm * INTENT_WEIGHTS.get(intent, 0.5) * value_norm * topical_fit / diff, 4)


def _title_for(intent: str, keyword: str, names: list[str]) -> str:
    if intent == "review" and names:
        return f"{names[0]} Review: Features, Pricing & Verdict"
    if intent == "comparison" and len(names) >= 2:
        return f"{names[0]} vs {names[1]}: Which Should You Pick?"
    if intent == "alternatives" and names:
        return f"{names[0]} Alternatives: Data-Backed Options"
    if intent == "pricing" and names:
        return f"{names[0]} Pricing: What It Actually Costs"
    return keyword.title()


def _outline_for(intent: str) -> list[str]:
    base = {
        "review": ["intro", "key facts", "who it's for", "verdict"],
        "comparison": ["intro", "head-to-head facts", "which to pick", "verdict"],
        "alternatives": ["intro", "why look elsewhere", "options with facts", "recommendation"],
        "best": ["intro", "ranked options with facts", "how we compare", "picks by use case"],
        "pricing": ["intro", "plans and costs", "value assessment"],
    }
    return base.get(intent, ["intro", "facts", "summary"])


def plan_content(pack_slug: str, tenant_id: int = 1, limit: int = 50) -> dict:
    ctx = load_pack_context(pack_slug, tenant_id)
    min_score = float(ctx["traffic"].get("min_opportunity_score", 0.35))

    with pool().connection() as conn:
        best_payout = conn.execute(
            "SELECT COALESCE(max(o.payout_amount), 0) FROM offers o "
            "JOIN affiliate_programs p ON p.id = o.program_id WHERE p.vertical_id = %s",
            (ctx["vertical_id"],),
        ).fetchone()[0]
        ideas = conn.execute(
            "SELECT id, keyword, intent, entity_keys, search_volume, difficulty "
            "FROM keyword_ideas WHERE vertical_id = %s AND status = 'new' "
            "ORDER BY id LIMIT %s",
            (ctx["vertical_id"], limit),
        ).fetchall()

        queued, skipped = 0, 0
        for idea_id, keyword, intent, entity_keys, volume, difficulty in ideas:
            known = [k for k in entity_keys if k in ctx["entities"]]
            fit = 1.0 if known else 0.3
            score = opportunity_score(volume, intent, float(best_payout), fit, difficulty)
            buildable = intent in BUILDABLE_INTENTS and (known or intent == "best")
            if score < min_score or not buildable:
                conn.execute(
                    "UPDATE keyword_ideas SET status = 'rejected' WHERE id = %s", (idea_id,)
                )
                skipped += 1
                continue
            names = [ctx["entities"][k].get("name", k) for k in known]
            conn.execute(
                """
                INSERT INTO content_briefs (tenant_id, vertical_id, keyword_idea_id, page_type,
                                            title, slug, entity_keys, outline, opportunity)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (keyword_idea_id) DO NOTHING
                """,
                (tenant_id, ctx["vertical_id"], idea_id, intent,
                 _title_for(intent, keyword, names), slugify(keyword), known or entity_keys,
                 json.dumps({"sections": _outline_for(intent), "keyword": keyword}), score),
            )
            conn.execute("UPDATE keyword_ideas SET status = 'planned' WHERE id = %s", (idea_id,))
            queued += 1
    return {"scored": len(ideas), "briefs_queued": queued, "rejected": skipped,
            "min_score": min_score}
