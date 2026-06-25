"""
ai/llm_client.py
Free LLM client using g4f (gpt4free) — no API key required.
Falls back through multiple free providers automatically.
All calls are synchronous — run from a QThreadPool worker.
"""

from __future__ import annotations

import logging
import re
from typing import List, Dict

from config import config

log = logging.getLogger(__name__)


# ── System prompt ─────────────────────────────────────────────────────────────

_DEFAULT_SYSTEM = (
    "You are Saturday, a smart, friendly, and efficient AI desktop assistant. "
    "You help with tasks, answer questions, control the computer, manage files, "
    "set reminders, and remember important information. "
    "Be concise and helpful. When performing actions, confirm what you did briefly."
)

# ── Preferred provider order (most reliable first) ────────────────────────────
_PREFERRED_PROVIDERS = [
    "DDG",           # DuckDuckGo AI — very stable
    "Blackbox",      # Blackbox AI — reliable
    "DeepInfra",     # DeepInfra — good uptime
    "Pizzagpt",      # PizzaGPT — simple
    "FreeGpt",       # FreeGPT
    "ChatBase",      # ChatBase
    "You",           # You.com
]


class LLMClient:
    """Free LLM client — powered by g4f (no API key required)."""

    def __init__(self) -> None:
        self._refresh()
        self._g4f_client = None
        self._init_client()

    def _refresh(self) -> None:
        self._system_prompt = config.get(
            "ai", "system_prompt", default=_DEFAULT_SYSTEM
        )
        self._temperature = float(config.get("ai", "temperature", default=0.7))
        self._max_tokens = int(config.get("ai", "max_tokens", default=1024))
        self._model = config.get("ai", "model", default="gpt-4o-mini")

    def _init_client(self) -> None:
        """Initialize the g4f client with a RetryProvider."""
        try:
            import g4f
            from g4f.client import Client
            from g4f.Provider import (
                RetryProvider, DDG, Blackbox, DeepInfra,
                FreeGpt, You,
            )

            providers = []
            for name in _PREFERRED_PROVIDERS:
                try:
                    prov = getattr(g4f.Provider, name, None)
                    if prov is not None:
                        providers.append(prov)
                except Exception:
                    pass

            if not providers:
                # Absolute fallback — let g4f pick automatically
                self._g4f_client = Client()
                log.info("g4f client initialized (auto-provider)")
            else:
                self._g4f_client = Client(provider=RetryProvider(providers, shuffle=False))
                log.info("g4f client initialized with %d providers", len(providers))
        except ImportError:
            log.warning("g4f is not installed — AI responses will use fallback mode")
            self._g4f_client = None
        except Exception as exc:
            log.error("g4f init failed: %s", exc)
            self._g4f_client = None

    def chat(self, messages: List[Dict], system: str | None = None) -> str:
        """
        Send a list of {role, content} messages to a free LLM.
        Returns the assistant reply as a string.
        """
        self._refresh()

        full_messages = []
        sys_prompt = system or self._system_prompt
        if sys_prompt:
            full_messages.append({"role": "system", "content": sys_prompt})
        full_messages.extend(messages)

        # Try g4f first
        if self._g4f_client is not None:
            try:
                response = self._g4f_client.chat.completions.create(
                    model=self._model,
                    messages=full_messages,
                    max_tokens=self._max_tokens,
                )
                reply = response.choices[0].message.content or ""
                if reply.strip():
                    log.debug("g4f reply (%d chars)", len(reply))
                    return reply.strip()
            except Exception as exc:
                log.warning("g4f primary failed: %s — trying fallback", exc)
                # Re-init client for next call
                self._init_client()

        # Try again with a fresh client and no provider restriction
        try:
            import g4f
            from g4f.client import Client
            client2 = Client()
            # Try different free models
            for model in ["gpt-4o-mini", "gpt-3.5-turbo", "llama-3-8b", "mistral-7b"]:
                try:
                    response = client2.chat.completions.create(
                        model=model,
                        messages=full_messages,
                        max_tokens=self._max_tokens,
                    )
                    reply = response.choices[0].message.content or ""
                    if reply.strip():
                        log.info("g4f fallback succeeded with model=%s", model)
                        return reply.strip()
                except Exception as e:
                    log.debug("g4f model %s failed: %s", model, e)
                    continue
        except Exception as exc:
            log.error("g4f fallback also failed: %s", exc)

        # Last resort: smart rule-based response
        return self._smart_fallback(full_messages)

    def quick(self, prompt: str) -> str:
        """Single-turn convenience wrapper."""
        return self.chat([{"role": "user", "content": prompt}])

    def _smart_fallback(self, messages: List[Dict]) -> str:
        """
        Rule-based intelligent fallback when no AI provider is available.
        Returns a helpful response based on message content.
        """
        # Get the last user message
        user_msg = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                user_msg = m.get("content", "").lower()
                break

        if not user_msg:
            return "I'm here to help! Could you repeat that?"

        # Time/date
        if any(w in user_msg for w in ["time", "date", "today", "day"]):
            from datetime import datetime
            now = datetime.now()
            return (
                f"It's currently {now.strftime('%I:%M %p')} on "
                f"{now.strftime('%A, %B %d, %Y')}."
            )

        # Greetings
        if any(w in user_msg for w in ["hello", "hi", "hey", "good morning", "good evening", "howdy"]):
            return "Hello! I'm Saturday, your AI assistant. How can I help you today?"

        # How are you
        if any(w in user_msg for w in ["how are you", "how do you do", "what's up"]):
            return "I'm doing great and ready to help you! What can I do for you?"

        # Thank you
        if any(w in user_msg for w in ["thank", "thanks", "appreciate"]):
            return "You're welcome! Is there anything else I can help with?"

        # Capabilities
        if any(w in user_msg for w in ["what can you do", "help me", "capabilities", "features"]):
            return (
                "I can help you with many things! I can:\n"
                "• Open apps and websites\n"
                "• Search the web\n"
                "• Set reminders\n"
                "• Remember important information\n"
                "• Control system volume and take screenshots\n"
                "• Answer questions and have conversations\n"
                "What would you like to do?"
            )

        # Jokes
        if any(w in user_msg for w in ["joke", "funny", "laugh"]):
            return "Why do programmers prefer dark mode? Because light attracts bugs! 😄"

        # Weather (can't actually check)
        if "weather" in user_msg:
            return (
                "I'd love to check the weather for you, but I need an internet connection "
                "to fetch live data. You can check weather.com or your local weather app!"
            )

        # Generic helpful response
        return (
            "I'm Saturday, your AI assistant. I'm having trouble connecting to my AI brain "
            "right now, but I can still help you with opening apps, setting reminders, "
            "searching the web, and controlling your computer. What do you need?"
        )

    @property
    def provider(self) -> str:
        return "g4f-free"
