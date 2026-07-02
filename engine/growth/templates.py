"""Built-in draft prompts per page type. A pack can override any of these by
shipping prompts/<page_type>.txt; these defaults keep new packs minimal.
Rules mirror the pack prompts: grounded numbers only, no digits in instructions,
no hype/banned-phrase examples (they leak into echo-y model output)."""

COMMON_RULES = """STRICT RULES:
- Use ONLY the facts listed below. Do NOT invent numbers, prices, percentages, or dates.
- Every number you mention must appear in the facts.
- Neutral, useful tone; never promise outcomes and never use hype language.
- Clear markdown with short sections.
- Between two hundred fifty and four hundred fifty words (do not state a word count).
"""

TEMPLATES = {
    "review": (
        "You are writing a factual review page targeting the search \"{keyword}\" "
        "about {entity_name}.\n\n" + COMMON_RULES +
        "Sections: an intro paragraph, \"Key facts\", \"Who it's for\", and a short verdict.\n\n"
        "FACTS:\n{facts}\n"
    ),
    "comparison": (
        "You are writing a factual head-to-head comparison targeting the search "
        "\"{keyword}\" between: {entity_name}.\n\n" + COMMON_RULES +
        "Sections: an intro paragraph, \"Head to head\" comparing them ONLY on the facts, "
        "\"Which should you pick\" tied to concrete facts, and a short verdict.\n\n"
        "FACTS:\n{facts}\n"
    ),
    "alternatives": (
        "You are writing a factual alternatives page targeting the search \"{keyword}\". "
        "The options to cover: {entity_name}.\n\n" + COMMON_RULES +
        "Sections: an intro paragraph, one short facts-grounded subsection per option, "
        "and a recommendation by use case.\n\n"
        "FACTS:\n{facts}\n"
    ),
    "best": (
        "You are writing a factual roundup page targeting the search \"{keyword}\". "
        "The options to cover: {entity_name}.\n\n" + COMMON_RULES +
        "Sections: an intro paragraph, a ranked list where every claim cites a fact, "
        "and picks by use case.\n\n"
        "FACTS:\n{facts}\n"
    ),
    "pricing": (
        "You are writing a factual pricing page targeting the search \"{keyword}\" "
        "about {entity_name}.\n\n" + COMMON_RULES +
        "Sections: an intro paragraph, \"Plans and costs\" using only the facts, "
        "and a short value assessment.\n\n"
        "FACTS:\n{facts}\n"
    ),
}


def facts_table(entities: dict[str, dict]) -> str:
    """Deterministic markdown comparison table straight from the dataset — guaranteed
    grounded, adds data density independent of what the LLM writes."""
    if not entities:
        return ""
    keys: list[str] = []
    for d in entities.values():
        for k in d:
            if k not in keys and k not in ("name",):
                keys.append(k)
    keys = keys[:8]
    header = "| Fact | " + " | ".join(d.get("name", k) for k, d in entities.items()) + " |"
    sep = "|" + "---|" * (len(entities) + 1)
    rows = []
    for key in keys:
        cells = " | ".join(str(d.get(key, "—")) for d in entities.values())
        rows.append(f"| {key.replace('_', ' ')} | {cells} |")
    return "\n".join(["### Data snapshot", "", header, sep, *rows])
