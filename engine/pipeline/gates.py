"""Publish-blocking gates. A page ships only if every gate passes — this is the
enforcement layer for Google's value-not-method policies (research report §1.2):
grounding (no unsupported numbers), data density (enough real data per page),
uniqueness (no near-duplicate siblings), compliance (disclosures + banned phrases).
"""

from dataclasses import dataclass, field

import numpy as np

from engine.pipeline.numbers import supported_fact_numbers_used, unsupported_numbers


@dataclass
class GateResult:
    passed: bool
    details: dict = field(default_factory=dict)


def grounding_gate(draft: str, facts_text: str) -> GateResult:
    bad = unsupported_numbers(draft, facts_text)
    return GateResult(passed=not bad, details={"unsupported_numbers": sorted(bad)})


def density_gate(draft: str, facts_text: str, min_facts: int) -> GateResult:
    used = supported_fact_numbers_used(draft, facts_text)
    return GateResult(
        passed=len(used) >= min_facts,
        details={"fact_numbers_used": len(used), "required": min_facts},
    )


def uniqueness_gate(
    embedding: np.ndarray, sibling_embeddings: list[np.ndarray], ceiling: float
) -> GateResult:
    """Cosine similarity vs every already-accepted sibling must stay under the ceiling.
    Embeddings are L2-normalized, so dot product == cosine."""
    worst = 0.0
    for sib in sibling_embeddings:
        worst = max(worst, float(embedding @ sib))
    return GateResult(passed=worst < ceiling, details={"max_sibling_cosine": round(worst, 4),
                                                       "ceiling": ceiling})


def compliance_gate(body: str, required_disclosures: list[str], banned_phrases: list[str]) -> GateResult:
    lower = body.lower()
    missing = [d for d in required_disclosures if d.lower() not in lower]
    banned = [p for p in banned_phrases if p.lower() in lower]
    return GateResult(passed=not missing and not banned,
                      details={"missing_disclosures": missing, "banned_phrases_found": banned})


def run_all(
    draft: str,
    body_with_disclosures: str,
    facts_text: str,
    embedding: np.ndarray,
    sibling_embeddings: list[np.ndarray],
    min_facts: int,
    cosine_ceiling: float,
    required_disclosures: list[str],
    banned_phrases: list[str],
) -> dict:
    results = {
        "grounding": grounding_gate(draft, facts_text),
        "density": density_gate(draft, facts_text, min_facts),
        "uniqueness": uniqueness_gate(embedding, sibling_embeddings, cosine_ceiling),
        "compliance": compliance_gate(body_with_disclosures, required_disclosures, banned_phrases),
    }
    return {
        "passed": all(r.passed for r in results.values()),
        "gates": {k: {"passed": r.passed, **r.details} for k, r in results.items()},
    }
