"""
ai/intent_parser.py
Routes a user utterance to one of:
  - MEMORY_STORE   ("remember …", "note that …")
  - MEMORY_RECALL  ("what do I know about …", "recall …")
  - REMINDER_SET   ("remind me to … at/in …")
  - REMINDER_LIST  ("what are my reminders")
  - APP_OPEN       ("open notepad / chrome / …")
  - FILE_OP        ("create / rename / delete file …")
  - BROWSER        ("search for … / open url …")
  - SYSTEM_ACTION  ("volume up/down", "screenshot", "lock", "sleep")
  - CONVERSATION   (everything else → goes to LLM)

Uses a fast keyword/regex classifier first; falls back to the LLM for
ambiguous cases to avoid a round-trip on obvious intents.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum, auto

log = logging.getLogger(__name__)

_POLITE_PREFIX_RE = re.compile(
    r"^\s*(?:hey\s+)?(?:saturday|assistant|jarvis)[, ]+|"
    r"^\s*(?:please|can you|could you|would you|will you)\s+",
    re.I,
)
_POLITE_SUFFIX_RE = re.compile(r"\s+(?:please|for me|for us|right now|now)\s*$", re.I)
_APP_NAME_STOP_RE = re.compile(
    r"\s+(?:please|for me|for us|right now|now|and then|then)\b.*$",
    re.I,
)
_SITE_NAMES = {
    "youtube": "https://www.youtube.com",
    "google": "https://www.google.com",
    "gmail": "https://mail.google.com",
    "github": "https://github.com",
    "chatgpt": "https://chatgpt.com",
    "whatsapp": "https://web.whatsapp.com",
    "instagram": "https://www.instagram.com",
    "facebook": "https://www.facebook.com",
    "x": "https://x.com",
    "twitter": "https://x.com",
    "linkedin": "https://www.linkedin.com",
    "reddit": "https://www.reddit.com",
    "netflix": "https://www.netflix.com",
}


class Intent(Enum):
    MEMORY_STORE  = auto()
    MEMORY_RECALL = auto()
    REMINDER_SET  = auto()
    REMINDER_LIST = auto()
    APP_OPEN      = auto()
    FILE_OP       = auto()
    BROWSER       = auto()
    SYSTEM_ACTION = auto()
    CONVERSATION  = auto()


@dataclass
class ParsedIntent:
    intent: Intent
    slots: dict = field(default_factory=dict)
    raw: str = ""


# ── Keyword patterns ──────────────────────────────────────────────────────────

_PATTERNS: list[tuple[Intent, re.Pattern]] = [
    (Intent.MEMORY_STORE,  re.compile(
        r"\b(remember|note|save|store|keep in mind|don'?t forget)\b", re.I)),
    (Intent.MEMORY_RECALL, re.compile(
        r"\b(recall|what (do i|did i|have i)|tell me about|what is|what was|who is|"
        r"do you remember|remind me (what|who|when|where))\b", re.I)),
    (Intent.REMINDER_SET,  re.compile(
        r"\b(remind me|set (a )?reminder|alert me|notify me)\b", re.I)),
    (Intent.REMINDER_LIST, re.compile(
        r"\b(list (my )?reminders|show reminders|what('?s| are) (my )?reminders|"
        r"any reminders)\b", re.I)),
    (Intent.BROWSER,       re.compile(
        r"\b(search (for|the web|google)|google|look up|browse|youtube search|"
        r"search youtube|open (http|www|the (website|site|url)|youtube|google|"
        r"gmail|github|chatgpt|whatsapp|instagram|facebook|x|twitter|linkedin|"
        r"reddit|netflix))\b", re.I)),
    (Intent.APP_OPEN,      re.compile(
        r"\b(open|launch|start|run|execute)\s+\w", re.I)),
    (Intent.FILE_OP,       re.compile(
        r"\b(create|make|new|rename|move|copy|delete|remove)\s+(a\s+)?"
        r"(file|folder|directory|document)\b", re.I)),
    (Intent.SYSTEM_ACTION, re.compile(
        r"\b(volume (up|down|mute|unmute|set)|screenshot|screen shot|"
        r"lock (the )?(screen|computer|pc)|sleep|shutdown|restart|"
        r"brightness (up|down|set))\b", re.I)),
]


class IntentParser:
    """Fast rule-based intent classifier with LLM fallback for ambiguity."""

    def __init__(self, llm_client=None) -> None:
        self._llm = llm_client  # optional, used for fallback only

    def parse(self, utterance: str) -> ParsedIntent:
        text = self._clean_utterance(utterance)
        if not text:
            return ParsedIntent(Intent.CONVERSATION, raw=text)

        for intent, pattern in _PATTERNS:
            if pattern.search(text):
                slots = self._extract_slots(intent, text)
                log.debug("Intent matched: %s for %r", intent.name, text[:60])
                return ParsedIntent(intent=intent, slots=slots, raw=text)

        log.debug("No pattern matched — defaulting to CONVERSATION")
        return ParsedIntent(Intent.CONVERSATION, raw=text)

    # ── Slot extraction ───────────────────────────────────────────────────────

    def _clean_utterance(self, utterance: str) -> str:
        text = utterance.strip()
        previous = None
        while previous != text:
            previous = text
            text = _POLITE_PREFIX_RE.sub("", text).strip()
        return text.strip(" ,.")

    def _clean_slot_text(self, value: str) -> str:
        value = _APP_NAME_STOP_RE.sub("", value).strip()
        value = _POLITE_SUFFIX_RE.sub("", value).strip()
        return value.strip(" ,.")

    def _extract_slots(self, intent: Intent, text: str) -> dict:
        slots: dict = {}
        t = text.lower()

        if intent == Intent.APP_OPEN:
            m = re.search(
                r"\b(?:open|launch|start|run|execute)\s+([a-z0-9 _\-\.]+)", t
            )
            if m:
                slots["app_name"] = self._clean_slot_text(m.group(1))

        elif intent == Intent.MEMORY_STORE:
            # Strip the trigger phrase and keep the fact
            stripped = re.sub(
                r"^(remember|note|save|store|keep in mind|don'?t forget)\s*(that\s*)?",
                "", text, flags=re.I,
            ).strip()
            slots["content"] = stripped

        elif intent == Intent.MEMORY_RECALL:
            # Keep everything after the trigger phrase
            stripped = re.sub(
                r"^(recall|tell me about|what (do i|did i|have i) know about|"
                r"what is|what was|who is|do you remember)\s*", "",
                text, flags=re.I,
            ).strip()
            slots["query"] = stripped

        elif intent == Intent.REMINDER_SET:
            # Try to extract time
            time_m = re.search(
                r"\b(at\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?|"
                r"in\s+\d+\s+(?:minute|hour|day)s?)\b", t
            )
            slots["time_expr"] = time_m.group(0) if time_m else ""
            # Title = everything before time expression
            title = re.sub(
                r"\b(remind me to|set (a )?reminder (for|to)|alert me (to|when)|notify me)\b",
                "", text, flags=re.I,
            ).strip()
            if time_m:
                title = title[: title.lower().find(time_m.group(0))].strip()
            slots["title"] = title.strip(".,;") or text

        elif intent == Intent.BROWSER:
            youtube_m = re.search(
                r"\b(?:search youtube for|youtube search|search on youtube for)\s+(.+)",
                t,
            )
            if youtube_m:
                slots["query"] = self._clean_slot_text(youtube_m.group(1))
                slots["engine"] = "youtube"
            q_m = re.search(
                r"\b(?:search\s+(?:the web\s+)?(?:for\s+)?|google\s+|look up\s+)(.+)",
                t,
            )
            if q_m and not slots.get("query"):
                slots["query"] = self._clean_slot_text(q_m.group(1))
            url_m = re.search(r"(https?://[^\s]+|www\.[^\s]+)", t)
            if url_m:
                slots["url"] = url_m.group(1)
            site_m = re.search(r"\bopen\s+([a-z0-9]+)\b", t)
            if site_m and not slots.get("url") and not slots.get("query"):
                site = site_m.group(1)
                if site in _SITE_NAMES:
                    slots["url"] = _SITE_NAMES[site]

        elif intent == Intent.SYSTEM_ACTION:
            for kw in ("volume up", "volume down", "mute", "unmute",
                       "screenshot", "lock", "sleep", "shutdown", "restart",
                       "brightness up", "brightness down"):
                if kw in t:
                    slots["action"] = kw
                    break

        elif intent == Intent.FILE_OP:
            for kw in ("create", "make", "new", "rename", "move", "copy",
                       "delete", "remove"):
                if kw in t:
                    slots["operation"] = kw
                    break
            name_m = re.search(
                r'(?:called|named)\s+"?([^"]+?)"?$|"([^"]+)"|\'([^\']+)\'',
                text,
                re.I,
            )
            if name_m:
                slots["name"] = self._clean_slot_text(
                    name_m.group(1) or name_m.group(2) or name_m.group(3) or ""
                )

        return slots
