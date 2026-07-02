"""Numeric-claim extraction + normalization for the grounding verifier.

Normalizes "$1,299", "50%", "50 percent", "40-60%" so a draft number can be matched
against the source facts. Whitelists small ordinals (0-12) and plausible years, or
the verifier would reject harmless phrases like "top 5" and "in 2026".
"""

import re

_NUM_RE = re.compile(r"\d[\d,]*\.?\d*")
_WHITELIST_MAX_ORDINAL = 12


def normalize_number(tok: str) -> str:
    tok = tok.replace(",", "")
    if "." in tok:
        tok = tok.rstrip("0").rstrip(".")
    return tok


def extract_numbers(text: str) -> set[str]:
    """All normalized numeric tokens in a text. Ranges like 40-60 yield both ends."""
    return {normalize_number(m.group(0)) for m in _NUM_RE.finditer(text)}


def is_whitelisted(tok: str) -> bool:
    try:
        val = float(tok)
    except ValueError:
        return False
    if val == int(val) and 0 <= int(val) <= _WHITELIST_MAX_ORDINAL:
        return True
    if val == int(val) and 1990 <= int(val) <= 2035:  # years
        return True
    return False


def unsupported_numbers(draft: str, facts_text: str) -> set[str]:
    """Numbers in the draft that appear nowhere in the facts and aren't whitelisted."""
    fact_nums = extract_numbers(facts_text)
    return {n for n in extract_numbers(draft) if n not in fact_nums and not is_whitelisted(n)}


def supported_fact_numbers_used(draft: str, facts_text: str) -> set[str]:
    """Fact numbers the draft actually uses — the data-density signal."""
    draft_nums = extract_numbers(draft)
    return {n for n in extract_numbers(facts_text) if n in draft_nums and not is_whitelisted(n)}
