"""
ai/llm_client.py
Multi-provider LLM client — reliability-first rewrite.

Backend selection:
  1. Read  ai.backend_priority  from config  (default: ["ollama", "openai_compat", "rule_based"])
  2. Ping each backend at startup — lock in the first available one.
  3. Log   "LLMClient: active backend = <name>"  at INFO so it's impossible to miss.
  4. If the active backend fails mid-session, fall to the next in the list and log WARNING.
  5. g4f is NOT in the default priority list — data stays local by default.
     Add "g4f" to  ai.backend_priority  in your config to re-enable it.

Config shape (defaults.json / user config):
  "ai": {
    "backend_priority": ["ollama", "openai_compat", "rule_based"],
    "ollama": {
      "base_url": "http://localhost:11434",
      "model": "qwen3:8b",
      "timeout_seconds": 30
    },
    "api_key": "",              # only needed for real OpenAI
    "openai_base_url": "...",   # for openai_compat mode
    "model": "qwen3:8b",       # fallback model name for non-ollama backends
    "temperature": 0.7,
    "max_tokens": 1024,
    "system_prompt": "..."
  }
"""

from __future__ import annotations

import logging
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

# ── g4f preferred provider order (only used if g4f is in backend_priority) ───
_G4F_PROVIDERS = [
    "DDG",
    "Blackbox",
    "DeepInfra",
    "FreeGpt",
    "You",
]


# ─────────────────────────────────────────────────────────────────────────────
#  Ollama backend
# ─────────────────────────────────────────────────────────────────────────────

class _OllamaBackend:
    """Calls a local Ollama server via SDK (preferred) or raw HTTP."""

    name = "ollama"

    def __init__(self, base_url: str, model: str, temperature: float,
                 max_tokens: int, timeout: int = 30) -> None:
        self.base_url    = base_url.rstrip("/")
        self.model       = model
        self.temperature = temperature
        self.max_tokens  = max_tokens
        self.timeout     = timeout
        self._sdk_ok     = self._check_sdk()

    @staticmethod
    def _check_sdk() -> bool:
        try:
            import ollama  # noqa: F401
            return True
        except ImportError:
            return False

    def is_available(self) -> bool:
        """Lightweight ping — called once at startup."""
        try:
            import requests
            resp = requests.get(f"{self.base_url}/api/tags", timeout=3)
            return resp.status_code == 200
        except Exception:
            try:
                import urllib.request
                urllib.request.urlopen(f"{self.base_url}/api/tags", timeout=3)
                return True
            except Exception:
                return False

    def chat(self, messages: List[Dict]) -> str:
        if self._sdk_ok:
            return self._via_sdk(messages)
        return self._via_http(messages)

    def _via_sdk(self, messages: List[Dict]) -> str:
        import ollama
        client = ollama.Client(host=self.base_url)
        response = client.chat(
            model=self.model,
            messages=messages,
            think=False,
            keep_alive="30m",
            options={
                "temperature": self.temperature,
                "num_predict": self.max_tokens,
            },
        )
        return (response.message.content or "").strip()

    def _via_http(self, messages: List[Dict]) -> str:
        import requests
        payload = {
            "model":      self.model,
            "messages":   messages,
            "stream":     False,
            "think":      False,        # skip the reasoning trace -> faster + cleaner for TTS
            "keep_alive": "30m",        # keep the model loaded between requests, avoid reload tax
            "options": {
                "temperature": self.temperature,
                "num_predict": self.max_tokens,
            },
        }
        resp = requests.post(f"{self.base_url}/api/chat",
                             json=payload, timeout=self.timeout)
        resp.raise_for_status()
        return (resp.json()["message"]["content"] or "").strip()

    @property
    def label(self) -> str:
        return f"ollama/{self.model}"


# ─────────────────────────────────────────────────────────────────────────────
#  OpenAI-compatible backend
# ─────────────────────────────────────────────────────────────────────────────

class _OpenAICompatBackend:

    name = "openai_compat"

    def __init__(self, base_url: str, api_key: str, model: str,
                 temperature: float, max_tokens: int) -> None:
        self.base_url    = base_url.rstrip("/")
        self.api_key     = api_key or "ollama"
        self.model       = model
        self.temperature = temperature
        self.max_tokens  = max_tokens

    def is_available(self) -> bool:
        try:
            import requests
            resp = requests.get(
                f"{self.base_url}/models",
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=3,
            )
            return resp.status_code in (200, 401)  # 401 = reachable, key bad
        except Exception:
            return False

    def chat(self, messages: List[Dict]) -> str:
        import requests
        headers = {
            "Content-Type":  "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        payload = {
            "model":       self.model,
            "messages":    messages,
            "temperature": self.temperature,
            "max_tokens":  self.max_tokens,
        }
        resp = requests.post(f"{self.base_url}/chat/completions",
                             json=payload, headers=headers, timeout=60)
        resp.raise_for_status()
        return (resp.json()["choices"][0]["message"]["content"] or "").strip()

    @property
    def label(self) -> str:
        return f"openai_compat/{self.model}"


# ─────────────────────────────────────────────────────────────────────────────
#  g4f backend  — disabled in default backend_priority; add "g4f" to re-enable
# ─────────────────────────────────────────────────────────────────────────────

class _G4FBackend:

    name = "g4f"

    def __init__(self, model: str, max_tokens: int) -> None:
        self.model      = model
        self.max_tokens = max_tokens
        self._client    = None
        self._init()

    def _init(self) -> None:
        try:
            import g4f
            from g4f.client import Client
            from g4f.Provider import RetryProvider
            providers = [getattr(g4f.Provider, n, None) for n in _G4F_PROVIDERS]
            providers = [p for p in providers if p is not None]
            self._client = (Client(provider=RetryProvider(providers, shuffle=False))
                            if providers else Client())
            log.info("g4f backend ready with %d providers", len(providers))
        except ImportError:
            log.warning("g4f not installed — g4f backend unavailable.")
        except Exception as exc:
            log.error("g4f init error: %s", exc)

    def is_available(self) -> bool:
        return self._client is not None

    def chat(self, messages: List[Dict]) -> str:
        if self._client is None:
            raise RuntimeError("g4f not available")
        try:
            r = self._client.chat.completions.create(
                model=self.model, messages=messages, max_tokens=self.max_tokens
            )
            reply = (r.choices[0].message.content or "").strip()
            if reply:
                return reply
        except Exception as exc:
            log.warning("g4f primary failed: %s", exc)

        import g4f
        from g4f.client import Client
        client2 = Client()
        for m in ["gpt-4o-mini", "gpt-3.5-turbo", "llama-3-8b", "mistral-7b"]:
            try:
                r = client2.chat.completions.create(
                    model=m, messages=messages, max_tokens=self.max_tokens
                )
                reply = (r.choices[0].message.content or "").strip()
                if reply:
                    log.info("g4f fallback succeeded with model=%s", m)
                    return reply
            except Exception:
                continue
        raise RuntimeError("All g4f providers exhausted")

    @property
    def label(self) -> str:
        return "g4f"


# ─────────────────────────────────────────────────────────────────────────────
#  Rule-based fallback  — always available, no network required
# ─────────────────────────────────────────────────────────────────────────────

class _RuleBasedBackend:

    name = "rule_based"

    def is_available(self) -> bool:
        return True

    def chat(self, messages: List[Dict]) -> str:
        return _smart_fallback(messages)

    @property
    def label(self) -> str:
        return "rule_based"


# ─────────────────────────────────────────────────────────────────────────────
#  Rule-based responses
# ─────────────────────────────────────────────────────────────────────────────

def _smart_fallback(messages: List[Dict]) -> str:
    """Keyword-based response when all AI providers are unavailable."""
    user_msg = ""
    for m in reversed(messages):
        if m.get("role") == "user":
            user_msg = m.get("content", "").lower()
            break

    if not user_msg:
        return "I'm here to help! Could you repeat that?"

    if any(w in user_msg for w in ["time", "date", "today", "day"]):
        from datetime import datetime
        now = datetime.now()
        return (
            f"It's currently {now.strftime('%I:%M %p')} on "
            f"{now.strftime('%A, %B %d, %Y')}."
        )
    if any(w in user_msg for w in ["hello", "hi", "hey", "good morning", "good evening"]):
        return "Hello! I'm Saturday, your AI assistant. How can I help you today?"
    if any(w in user_msg for w in ["how are you", "what's up"]):
        return "I'm doing great and ready to help! What can I do for you?"
    if any(w in user_msg for w in ["thank", "thanks", "appreciate"]):
        return "You're welcome! Is there anything else I can help with?"
    if any(w in user_msg for w in ["what can you do", "capabilities", "features"]):
        return (
            "I can help you with many things!\n"
            "• Open apps and websites\n"
            "• Search the web\n"
            "• Set reminders\n"
            "• Remember important information\n"
            "• Control system volume and take screenshots\n"
            "• Answer questions and have conversations\n"
            "What would you like to do?"
        )
    if any(w in user_msg for w in ["joke", "funny", "laugh"]):
        return "Why do programmers prefer dark mode? Because light attracts bugs! 😄"
    if "weather" in user_msg:
        return (
            "I'd love to check the weather for you! You can ask me to open "
            "weather.com or your local weather app."
        )
    return (
        "I'm Saturday. I'm having trouble reaching my AI brain right now, "
        "but I can still help you open apps, set reminders, search the web, "
        "and control your computer. What do you need?"
    )


# ─────────────────────────────────────────────────────────────────────────────
#  Public LLMClient
# ─────────────────────────────────────────────────────────────────────────────

class LLMClient:
    """
    Reliability-first multi-provider LLM client for Saturday.

    Backend is selected ONCE at startup by iterating ai.backend_priority and
    pinging each candidate.  The chosen backend is logged at INFO level and
    cached — no per-request health probing.

    Mid-session failures fall to the next backend in the priority list and
    emit a WARNING so silent quality degradation is no longer possible.
    """

    def __init__(self) -> None:
        self._backends: List = []
        self._active_idx: int = 0
        self._system_prompt: str = _DEFAULT_SYSTEM
        self._build()

    # ── Build + select ────────────────────────────────────────────────────────

    def _build(self) -> None:
        """Instantiate backends for the configured priority list and ping each."""
        priority: List[str] = config.get(
            "ai", "backend_priority",
            default=["ollama", "openai_compat", "rule_based"],
        )
        temperature  = float(config.get("ai", "temperature",   default=0.7))
        max_tokens   = int(config.get("ai",   "max_tokens",    default=1024))
        sys_prompt   = config.get("ai", "system_prompt",       default=_DEFAULT_SYSTEM)

        # Ollama — prefer structured block, fall back to flat keys
        ollama_cfg     = config.get("ai", "ollama") or {}
        ollama_url     = (ollama_cfg.get("base_url")
                          or config.get("ai", "ollama_base_url",
                                        default="http://localhost:11434"))
        ollama_model   = (ollama_cfg.get("model")
                          or config.get("ai", "model", default="qwen3:8b"))
        ollama_timeout = int(ollama_cfg.get("timeout_seconds", 30))

        # OpenAI-compat
        openai_url   = config.get("ai", "openai_base_url",
                                   default="http://localhost:11434/v1")
        api_key      = config.get("ai", "api_key",  default="")
        compat_model = config.get("ai", "model",    default="qwen3:8b")

        self._system_prompt = sys_prompt

        # Build ordered backend list
        self._backends = []
        for name in priority:
            n = name.lower().strip()
            if n == "ollama":
                self._backends.append(
                    _OllamaBackend(ollama_url, ollama_model, temperature,
                                   max_tokens, ollama_timeout)
                )
            elif n in ("openai_compat", "openai"):
                self._backends.append(
                    _OpenAICompatBackend(openai_url, api_key, compat_model,
                                         temperature, max_tokens)
                )
            elif n == "g4f":
                self._backends.append(_G4FBackend("gpt-4o-mini", max_tokens))
            elif n == "rule_based":
                self._backends.append(_RuleBasedBackend())
            else:
                log.warning("LLMClient: unknown backend name '%s' in backend_priority — skipping.", name)

        # Guarantee rule_based is always the last resort
        if not any(isinstance(b, _RuleBasedBackend) for b in self._backends):
            self._backends.append(_RuleBasedBackend())

        # Ping each candidate; lock in the first available
        self._active_idx = self._select_backend()

        log.info(
            "LLMClient: active backend = %s  (priority order: %s)",
            self.active_backend,
            " -> ".join(b.name for b in self._backends),
        )

    def _select_backend(self) -> int:
        """Return the index of the first backend that responds to a ping."""
        for i, backend in enumerate(self._backends):
            try:
                if backend.is_available():
                    log.debug("LLMClient: '%s' is reachable ✓", backend.name)
                    return i
                log.debug("LLMClient: '%s' not reachable — skipping.", backend.name)
            except Exception as exc:
                log.debug("LLMClient: '%s' ping error: %s — skipping.", backend.name, exc)
        return len(self._backends) - 1  # rule_based guaranteed to be last

    # ── Public API ────────────────────────────────────────────────────────────

    @property
    def active_backend(self) -> str:
        """Human-readable label of the currently active backend."""
        if self._backends:
            return self._backends[self._active_idx].label
        return "none"

    def chat(self, messages: List[Dict], system: str | None = None) -> str:
        """Send a message list and return the assistant's reply."""
        sys_prompt = system or self._system_prompt
        full: List[Dict] = []
        if sys_prompt:
            full.append({"role": "system", "content": sys_prompt})
        full.extend(messages)

        # Try backends starting from the active one; fall over on failure
        n = len(self._backends)
        for attempt in range(n):
            idx     = (self._active_idx + attempt) % n
            backend = self._backends[idx]
            try:
                reply = backend.chat(full)
                if reply:
                    if attempt > 0:
                        log.warning(
                            "LLMClient: fell over from '%s' → '%s' after failure.",
                            self._backends[self._active_idx].name,
                            backend.name,
                        )
                        self._active_idx = idx
                    log.debug("LLMClient: reply via %s (%d chars)", backend.name, len(reply))
                    return reply
            except Exception as exc:
                log.warning(
                    "LLMClient: backend '%s' failed (%s) — trying next.",
                    backend.name, exc,
                )

        return _smart_fallback(full)

    def quick(self, prompt: str) -> str:
        """Single-turn convenience wrapper."""
        return self.chat([{"role": "user", "content": prompt}])

    def warm_up(self) -> None:
        """
        Call once when the app starts, before the user says anything.
        Pre-loads the active model into memory with keep_alive so live queries are instant.
        """
        try:
            log.info("LLMClient: warming up backend '%s'...", self.active_backend)
            self.quick("hi")
            log.info("LLMClient: warm-up complete.")
        except Exception as exc:
            log.debug("LLMClient: warm-up skipped/failed: %s", exc)

    @property
    def provider(self) -> str:
        """Alias for active_backend — kept for backward compat."""
        return self.active_backend

    def reload(self) -> None:
        """Re-read config and re-select backend (called after Settings save)."""
        log.info("LLMClient: reloading configuration...")
        self._build()
