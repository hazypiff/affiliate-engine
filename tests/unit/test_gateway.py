
import numpy as np
import pytest

from engine.gateway.client import generate, generate_json
from engine.gateway.embeddings import FakeEmbedder
from engine.gateway.providers import LLMError, MockProvider, OpenAIProvider, strip_fences
from engine.gateway.registry import ResolvedRole


def test_mock_provider_is_deterministic_and_prompt_sensitive():
    p = MockProvider()
    a = p.chat([{"role": "user", "content": "facts:\n- Kit pays 50% year one"}])
    b = p.chat([{"role": "user", "content": "facts:\n- Kit pays 50% year one"}])
    c = p.chat([{"role": "user", "content": "facts:\n- Surfer pays 125% CPA"}])
    assert a == b
    assert a != c
    assert "Kit pays 50% year one" in a  # echoes facts so gates see grounded text


def test_strip_fences():
    assert strip_fences('```json\n{"a": 1}\n```') == '{"a": 1}'
    assert strip_fences('{"a": 1}') == '{"a": 1}'


def test_generate_with_mock_override_no_db():
    out = generate("draft", "facts:\n- test fact", provider_override="mock")
    assert "test fact" in out


def test_generate_json_with_mock():
    out = generate_json("verify", "Check this. Return JSON.", provider_override="mock")
    assert out["ok"] is True


def test_fallback_chain(monkeypatch):
    class DeadProvider:
        def chat(self, *a, **kw):
            raise LLMError("dead")

    resolved = ResolvedRole(DeadProvider(), MockProvider(), 512, 0.5)
    monkeypatch.setattr("engine.gateway.client.resolve", lambda *a, **kw: resolved)
    out = generate("draft", "facts:\n- fallback fact")
    assert "fallback fact" in out


def test_fallback_none_reraises(monkeypatch):
    class DeadProvider:
        def chat(self, *a, **kw):
            raise LLMError("dead")

    resolved = ResolvedRole(DeadProvider(), None, 512, 0.5)
    monkeypatch.setattr("engine.gateway.client.resolve", lambda *a, **kw: resolved)
    with pytest.raises(LLMError):
        generate("draft", "x")


def test_fake_embedder_similarity_orders_by_token_overlap():
    e = FakeEmbedder()
    a = e.embed("draftkings sportsbook cpa new jersey bonus")
    b = e.embed("draftkings sportsbook cpa new jersey promo")
    c = e.embed("elevenlabs voice ai text to speech api pricing")
    assert np.isclose(np.linalg.norm(a), 1.0, atol=1e-5)
    assert float(a @ b) > float(a @ c)


def test_openai_provider_wraps_errors():
    p = OpenAIProvider("http://127.0.0.1:1", timeout=0.2)
    with pytest.raises(LLMError):
        p.chat([{"role": "user", "content": "hi"}])
