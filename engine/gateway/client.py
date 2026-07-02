import json

from engine.gateway.providers import LLMError, strip_fences
from engine.gateway.registry import resolve


def generate(
    role: str,
    prompt: str,
    system: str | None = None,
    tenant_id: int = 1,
    provider_override: str | None = None,
) -> str:
    r = resolve(role, tenant_id, provider_override)
    messages = ([{"role": "system", "content": system}] if system else []) + [
        {"role": "user", "content": prompt}
    ]
    try:
        return r.provider.chat(messages, max_tokens=r.max_tokens, temperature=r.temperature)
    except LLMError:
        if r.fallback is None:
            raise
        return r.fallback.chat(messages, max_tokens=r.max_tokens, temperature=r.temperature)


def generate_json(role: str, prompt: str, **kw) -> dict:
    """JSON-mode with defensive parsing: strip fences, retry once with a nudge."""
    out = generate(role, prompt, **kw)
    try:
        return json.loads(strip_fences(out))
    except json.JSONDecodeError:
        retry = generate(role, prompt + "\n\nReturn ONLY valid JSON, no prose, no fences.", **kw)
        return json.loads(strip_fences(retry))
