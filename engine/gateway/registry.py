"""Role -> model resolution. DB rows (llm_models/llm_roles) override; env defaults
apply when a role has no DB row, so the system works before any config is loaded.
Roles: draft | polish | verify | extract | classify | embed.
"""

from dataclasses import dataclass

from engine.config import settings
from engine.gateway.providers import MockProvider, OpenAIProvider


@dataclass
class ResolvedRole:
    provider: object
    fallback: object | None
    max_tokens: int
    temperature: float


def _provider_for(api_format: str, endpoint: str, model_name: str):
    if api_format == "mock":
        return MockProvider(model_name=model_name)
    return OpenAIProvider(endpoint, model_name)


def resolve(role: str, tenant_id: int = 1, provider_override: str | None = None) -> ResolvedRole:
    if provider_override == "mock":
        return ResolvedRole(MockProvider(), None, 2048, 0.7)

    from engine.db.pool import pool

    with pool().connection() as conn:
        row = conn.execute(
            """
            SELECT m.api_format, m.endpoint_url, m.model_name,
                   f.api_format, f.endpoint_url, f.model_name,
                   r.max_tokens, r.temperature
            FROM llm_roles r
            JOIN llm_models m ON m.id = r.model_id
            LEFT JOIN llm_models f ON f.id = r.fallback_model_id
            WHERE r.tenant_id = %s AND r.role = %s
            """,
            (tenant_id, role),
        ).fetchone()
    if row:
        primary = _provider_for(row[0], row[1], row[2])
        fallback = _provider_for(row[3], row[4], row[5]) if row[3] else None
        return ResolvedRole(primary, fallback, row[6], float(row[7]))

    # env default: local endpoint for every role
    return ResolvedRole(OpenAIProvider(settings().llm_base), None, 2048, 0.7)
