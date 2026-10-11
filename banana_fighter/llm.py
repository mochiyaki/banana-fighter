"""One thin wrapper around the Anthropic SDK for structured JSON calls.

Both the LLM agent (one call per move) and the LLM optimizer (one call per iteration) go
through `structured_call`, so refusal handling, fallbacks, caching, and telemetry live here.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("banana_fighter.llm")

FALLBACK_BETA = "server-side-fallback-2026-07-01"


def make_client():
    """Return an Anthropic client, or None when neither the SDK nor credentials are available."""
    try:
        import anthropic
    except ImportError:
        log.warning("anthropic SDK not installed; LLM agent/optimizer unavailable")
        return None
    try:
        return anthropic.Anthropic()
    except anthropic.AnthropicError as e:  # missing credentials
        log.warning("no Anthropic credentials (%s); LLM agent/optimizer unavailable", e)
        return None


def _supports_server_fallbacks(model: str) -> bool:
    return model.startswith(("claude-opus-5", "claude-fable", "claude-mythos"))


@dataclass
class LLMResult:
    data: dict[str, Any] | None   # parsed JSON, None on refusal / parse failure
    text: str
    usage: dict[str, Any] = field(default_factory=dict)
    refused: bool = False
    error: str | None = None


def structured_call(
    client: Any,
    *,
    model: str,
    system: str,
    user: str,
    schema: dict[str, Any],
    effort: str = "high",
    max_tokens: int = 16000,
) -> LLMResult:
    """Call Claude with a JSON-schema constrained output. Never raises on API problems; the
    caller decides how to degrade (the harness falls back to the rule-based path)."""
    import anthropic

    kwargs: dict[str, Any] = dict(
        model=model,
        max_tokens=max_tokens,
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user}],
        output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
    )
    try:
        if _supports_server_fallbacks(model):
            # Server-side fallback: if the safety classifier declines, Anthropic re-runs the
            # request on its recommended substitute model inside the same call.
            response = client.beta.messages.create(betas=[FALLBACK_BETA], fallbacks="default", **kwargs)
        else:
            response = client.messages.create(**kwargs)
    except anthropic.RateLimitError as e:
        return LLMResult(None, "", error=f"rate limited: {e.message}")
    except anthropic.APIStatusError as e:
        return LLMResult(None, "", error=f"api error {e.status_code}: {e.message}")
    except anthropic.APIConnectionError as e:
        return LLMResult(None, "", error=f"connection error: {e}")

    usage = {
        "input_tokens": getattr(response.usage, "input_tokens", None),
        "output_tokens": getattr(response.usage, "output_tokens", None),
        "cache_read_input_tokens": getattr(response.usage, "cache_read_input_tokens", None),
        "model": getattr(response, "model", model),
    }
    if response.stop_reason == "refusal":
        details = getattr(response, "stop_details", None)
        return LLMResult(None, "", usage, refused=True,
                         error=f"refusal: {getattr(details, 'category', None)} {getattr(details, 'explanation', '')}".strip())
    text = next((b.text for b in response.content if b.type == "text"), "")
    try:
        return LLMResult(json.loads(text), text, usage)
    except json.JSONDecodeError as e:
        return LLMResult(None, text, usage, error=f"bad json: {e}")
