"""
ai/llm_client.py
Unified LLM client via LiteLLM.
Supports: Claude (Anthropic), OpenAI, Gemini.
All calls are synchronous — run from a QThreadPool worker.
"""

from __future__ import annotations

import logging
from typing import Iterator

from config import config

log = logging.getLogger(__name__)

_PROVIDER_PREFIX = {
    "claude":  "anthropic/",
    "openai":  "",
    "gemini":  "gemini/",
}


class LLMClient:
    """Thin wrapper around LiteLLM for multi-provider support."""

    def __init__(self) -> None:
        self._refresh()

    def _refresh(self) -> None:
        self._provider = config.get("ai", "provider", default="claude")
        self._model = config.get("ai", "model", default="claude-sonnet-4-5")
        self._api_key = config.get("ai", "api_key", default="")
        self._temperature = float(config.get("ai", "temperature", default=0.7))
        self._max_tokens = int(config.get("ai", "max_tokens", default=1024))
        self._system_prompt = config.get("ai", "system_prompt", default="You are Saturday, a helpful AI desktop assistant.")

    def _litellm_model(self) -> str:
        prefix = _PROVIDER_PREFIX.get(self._provider, "")
        return f"{prefix}{self._model}"

    def _env_key(self) -> dict:
        """Return the appropriate env-key dict for LiteLLM."""
        key_map = {
            "claude":  "ANTHROPIC_API_KEY",
            "openai":  "OPENAI_API_KEY",
            "gemini":  "GEMINI_API_KEY",
        }
        import os
        env_var = key_map.get(self._provider, "OPENAI_API_KEY")
        if self._api_key:
            os.environ[env_var] = self._api_key
        elif not os.getenv(env_var):
            raise RuntimeError(
                f"AI API key is missing. Add your {self._provider} API key in Saturday settings."
            )
        return {}

    def chat(self, messages: list[dict], system: str | None = None) -> str:
        """
        Send a list of {role, content} messages to the LLM.
        Returns the assistant reply as a string.
        """
        self._refresh()
        self._env_key()

        full_messages = []
        sys = system or self._system_prompt
        if sys:
            full_messages.append({"role": "system", "content": sys})
        full_messages.extend(messages)

        try:
            import litellm
            litellm.suppress_debug_info = True
            response = litellm.completion(
                model=self._litellm_model(),
                messages=full_messages,
                temperature=self._temperature,
                max_tokens=self._max_tokens,
                timeout=30,
            )
            reply = response.choices[0].message.content or ""
            log.debug("LLM reply (%d chars)", len(reply))
            return reply.strip()
        except Exception as exc:
            log.error("LLM error: %s", exc)
            raise

    def quick(self, prompt: str) -> str:
        """Single-turn convenience wrapper."""
        return self.chat([{"role": "user", "content": prompt}])

    @property
    def provider(self) -> str:
        return self._provider
