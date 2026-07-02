"""LLM providers. Everything speaks OpenAI-compatible chat completions, so local
llama.cpp/Ollama/vLLM and any cloud API are interchangeable rows in llm_models.

MockProvider ships in-package (not tests/) because the CLI exposes --provider mock:
deterministic, seeded by the prompt content, and it echoes back facts it finds in
the prompt so the numeric-claim verifier and gates are meaningfully exercised offline.
"""

import hashlib
import json
import re

import httpx


class LLMError(RuntimeError):
    pass


class OpenAIProvider:
    """OpenAI-compatible /v1/chat/completions. llama.cpp quirks handled:
    the model field may be ignored, requests must be serial, timeouts long (CPU decode)."""

    def __init__(self, base_url: str, model_name: str = "default", timeout: float = 300.0):
        self.base_url = base_url.rstrip("/")
        self.model_name = model_name
        self.timeout = timeout

    def chat(self, messages: list[dict], max_tokens: int = 2048, temperature: float = 0.7) -> str:
        payload = {
            "model": self.model_name,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        try:
            resp = httpx.post(
                f"{self.base_url}/v1/chat/completions", json=payload, timeout=self.timeout
            )
            resp.raise_for_status()
            data = resp.json()
            return strip_thinking(data["choices"][0]["message"]["content"])
        except (httpx.HTTPError, KeyError, IndexError, json.JSONDecodeError) as e:
            raise LLMError(f"chat failed against {self.base_url}: {e}") from e


class MockProvider:
    """Deterministic offline provider. Output varies with the prompt (seeded by its
    hash) and embeds the fact lines it finds, so gate logic sees realistic input."""

    def __init__(self, base_url: str = "", model_name: str = "mock", timeout: float = 0):
        self.model_name = model_name

    def chat(self, messages: list[dict], max_tokens: int = 2048, temperature: float = 0.7) -> str:
        prompt = "\n".join(m.get("content", "") for m in messages)
        # letters-only seed: digits in a hex seed would trip the grounding verifier
        seed = hashlib.sha256(prompt.encode()).hexdigest()[:8].translate(
            str.maketrans("0123456789", "ghijklmnop")
        )
        # JSON-mode requests get a minimal valid object
        if "Return JSON" in prompt or "return JSON" in prompt:
            return json.dumps({"ok": True, "seed": seed})
        # echo only the grounded facts (after the FACTS: marker), never instruction bullets
        facts_section = prompt.split("FACTS:", 1)[-1]
        facts = re.findall(r"^- .+$", facts_section, flags=re.MULTILINE)
        body = [f"Deterministic mock draft {seed}.", ""]
        for i, fact in enumerate(facts[:12]):
            body.append(f"Point: {fact.lstrip('- ')} (mock analysis {seed[:4]}).")
        body.append("")
        body.append(f"Summary {seed}: grounded in the facts supplied above.")
        return "\n".join(body)


def strip_thinking(text: str) -> str:
    """Remove <think>...</think> blocks emitted by reasoning models (LFM, Qwen-think)."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    # unterminated think block (max_tokens cut it off): drop everything
    text = re.sub(r"<think>.*\Z", "", text, flags=re.DOTALL)
    return text.strip()


def strip_fences(text: str) -> str:
    text = text.strip()
    m = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, flags=re.DOTALL)
    return m.group(1) if m else text
