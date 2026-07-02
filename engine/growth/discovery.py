"""Keyword discovery with a provider interface.

Providers, in priority order:
1. RuleExpansion (always on, deterministic, free): combinatorial ideas from the pack's
   own dataset entities x intents — "kit review", "kit vs getresponse",
   "best email marketing tools", "elevenlabs alternatives", "surfer pricing".
2. LLMExpansion (skipped under --provider mock): long-tail ideas via the `extract` role.
3. Paid connectors (Google Ads KeywordPlanIdeaService, DataForSEO, Semrush/Ahrefs):
   interface stubs below — wire credentials, return the same idea dicts, done.
   Search volume/difficulty stay NULL until a volume source fills them
   (see `engine import-volumes`, CSV: keyword,search_volume,difficulty).

Every idea: {keyword, intent, entity_keys, source} -> upserted into keyword_ideas,
clustered by the primary entity's dataset `category`.
"""

import json

from engine.db.pool import pool
from engine.gateway.client import generate
from engine.gateway.providers import strip_fences
from engine.growth.common import ensure_cluster, load_pack_context

VALID_INTENTS = {"review", "comparison", "alternatives", "best", "pricing", "how-to"}


def rule_expansion(entities: dict, intents: list[str], seeds: list[str]) -> list[dict]:
    ideas = []
    ents = [(k, d.get("name", k), d.get("category", "general")) for k, d in entities.items()]
    by_cat: dict[str, list] = {}
    for k, name, cat in ents:
        by_cat.setdefault(cat, []).append((k, name))

    for k, name, cat in ents:
        if "review" in intents:
            ideas.append({"keyword": f"{name.lower()} review", "intent": "review",
                          "entity_keys": [k], "source": "rules"})
        if "alternatives" in intents:
            # an alternatives page needs the entity PLUS its category peers to compare
            peers = [pk for pk, _ in by_cat.get(cat, []) if pk != k][:3]
            ideas.append({"keyword": f"{name.lower()} alternatives", "intent": "alternatives",
                          "entity_keys": [k, *peers], "source": "rules"})
        if "pricing" in intents:
            ideas.append({"keyword": f"{name.lower()} pricing", "intent": "pricing",
                          "entity_keys": [k], "source": "rules"})
    if "comparison" in intents:
        for cat, members in by_cat.items():
            for (ka, na), (kb, nb) in zip(members, members[1:]):
                ideas.append({"keyword": f"{na.lower()} vs {nb.lower()}", "intent": "comparison",
                              "entity_keys": [ka, kb], "source": "rules"})
    if "best" in intents:
        for cat, members in by_cat.items():
            if len(members) >= 2:
                ideas.append({"keyword": f"best {cat} tools", "intent": "best",
                              "entity_keys": [k for k, _ in members[:6]], "source": "rules"})
    for s in seeds:
        ideas.append({"keyword": s.lower(), "intent": _guess_intent(s),
                      "entity_keys": _match_entities(s, ents), "source": "rules"})
    return ideas


def _guess_intent(keyword: str) -> str:
    kw = keyword.lower()
    if " vs " in kw:
        return "comparison"
    if "alternative" in kw:
        return "alternatives"
    if kw.startswith("best "):
        return "best"
    if "pricing" in kw or "cost" in kw:
        return "pricing"
    if kw.startswith("how ") or kw.startswith("how-to"):
        return "how-to"
    return "review"


def _match_entities(keyword: str, ents: list[tuple]) -> list[str]:
    kw = keyword.lower()
    return [k for k, name, _ in ents if name.lower() in kw]


def llm_expansion(ctx: dict, provider_override: str | None) -> list[dict]:
    if provider_override == "mock":
        return []  # rule expansion already covers deterministic testing
    traffic = ctx["traffic"]
    names = [d.get("name", k) for k, d in ctx["entities"].items()]
    prompt = (
        "You generate SEO keyword ideas for an affiliate site.\n"
        f"Audience: {traffic.get('audience', '')}\nCountry: {traffic.get('country', 'US')}\n"
        f"Tools/entities covered: {', '.join(names)}\n"
        f"Seed keywords: {', '.join(traffic.get('seed_keywords', []))}\n"
        f"Allowed intents: {', '.join(traffic.get('intents', []))}\n\n"
        "Return JSON: a list of up to 15 objects {\"keyword\": str, \"intent\": str, "
        "\"entities\": [entity names mentioned]}. Only keywords a buyer would search. "
        "Return ONLY the JSON array."
    )
    try:
        out = generate("extract", prompt, provider_override=provider_override)
        items = json.loads(strip_fences(out))
    except Exception:
        return []  # LLM expansion is best-effort; rules are the floor
    ents = [(k, d.get("name", k), "") for k, d in ctx["entities"].items()]
    ideas = []
    for it in items if isinstance(items, list) else []:
        kw = str(it.get("keyword", "")).strip().lower()
        intent = str(it.get("intent", "")).strip().lower()
        if not kw or intent not in VALID_INTENTS:
            continue
        ideas.append({"keyword": kw, "intent": intent,
                      "entity_keys": _match_entities(kw, ents), "source": "llm"})
    return ideas


class GoogleAdsProvider:
    """Stub: wire google-ads.yaml creds + KeywordPlanIdeaService.generate_keyword_ideas,
    map to idea dicts with search_volume from avg_monthly_searches."""

    def discover(self, ctx: dict) -> list[dict]:
        raise NotImplementedError("configure Google Ads API credentials to enable")


class DataForSEOProvider:
    """Stub: POST /v3/keywords_data/google_ads/search_volume with login creds."""

    def discover(self, ctx: dict) -> list[dict]:
        raise NotImplementedError("configure DataForSEO credentials to enable")


def discover_keywords(pack_slug: str, tenant_id: int = 1,
                      provider_override: str | None = None) -> dict:
    ctx = load_pack_context(pack_slug, tenant_id)
    intents = ctx["traffic"].get("intents", list(VALID_INTENTS))
    seeds = ctx["traffic"].get("seed_keywords", [])
    ideas = rule_expansion(ctx["entities"], intents, seeds)
    ideas += llm_expansion(ctx, provider_override)

    inserted = 0
    with pool().connection() as conn:
        for idea in ideas:
            primary = idea["entity_keys"][0] if idea["entity_keys"] else None
            cat = ctx["entities"].get(primary, {}).get("category", "general") if primary else "general"
            cluster_id = ensure_cluster(conn, tenant_id, ctx["vertical_id"], cat)
            cur = conn.execute(
                """
                INSERT INTO keyword_ideas (tenant_id, vertical_id, cluster_id, keyword, intent,
                                           entity_keys, source)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (vertical_id, keyword) DO NOTHING
                """,
                (tenant_id, ctx["vertical_id"], cluster_id, idea["keyword"], idea["intent"],
                 idea["entity_keys"], idea["source"]),
            )
            inserted += cur.rowcount
    return {"candidates": len(ideas), "new_keywords": inserted}


def import_volumes(file: str, tenant_id: int = 1) -> int:
    """CSV volume/difficulty fill-in: keyword,search_volume[,difficulty]."""
    import csv
    from pathlib import Path

    n = 0
    with Path(file).open(newline="") as f, pool().connection() as conn:
        for row in csv.DictReader(f):
            cur = conn.execute(
                "UPDATE keyword_ideas SET search_volume = %s, difficulty = %s "
                "WHERE tenant_id = %s AND keyword = %s",
                (int(row["search_volume"]), float(row["difficulty"]) if row.get("difficulty") else None,
                 tenant_id, row["keyword"].strip().lower()),
            )
            n += cur.rowcount
    return n
