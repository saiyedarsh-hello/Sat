"""
ai/intent_parser.py
Routes a user utterance to one of:
  - MEMORY_STORE   ("remember that …", "note that …")
  - MEMORY_RECALL  ("what do I know about …", "recall …", "do you remember …")
  - REMINDER_SET   ("remind me to … at/in …", "ping me in 20 mins about …")
  - REMINDER_LIST  ("what are my reminders")
  - APP_OPEN       ("open brave", "pull up vs code", "can you launch spotify")
  - FILE_OP        ("create / rename / delete file …")
  - BROWSER        ("search for …", "look up …", "open url …")
  - SYSTEM_ACTION  ("volume up/down", "screenshot", "lock", "sleep", "shutdown")
  - CONVERSATION   (general questions, negative/distractors, chat)

Uses:
  1. Negative / Distractor / Question filter (prevents false positives on statements like
     "I don't want to open Chrome", "should I delete this file", "what happens if I shut down")
  2. Fast regex pattern matcher (handles phrasing variance, slang, polite preambles)
  3. LLM fallback for ambiguous / multi-step queries
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum, auto

log = logging.getLogger(__name__)

# Polite & colloquial prefixes to clean
_POLITE_PREFIX_RE = re.compile(
    r"^\s*(?:hey\s+|yo\s+|ok\s+|okay\s+)?(?:saturday|assistant|jarvis)[, ]+|"
    r"^\s*(?:please|can you|could you|would you mind|would you|will you|let's|i need to|i want to|i'm gonna need|yo)\s+",
    re.I,
)
_POLITE_SUFFIX_RE = re.compile(
    r"\s+(?:please|for me|for us|right now|now|real quick|a bit|asap)\s*$",
    re.I,
)
_APP_NAME_STOP_RE = re.compile(
    r"\s+(?:please|for me|for us|right now|now|real quick|and then|then)\b.*$",
    re.I,
)

# Known web services and URLs
SITE_NAMES: dict[str, str] = {
    "whatsapp":   "https://web.whatsapp.com",
    "youtube":    "https://www.youtube.com",
    "google":     "https://www.google.com",
    "gmail":      "https://mail.google.com",
    "github":     "https://github.com",
    "chatgpt":    "https://chatgpt.com",
    "instagram":  "https://www.instagram.com",
    "facebook":   "https://www.facebook.com",
    "x":          "https://x.com",
    "twitter":    "https://x.com",
    "linkedin":   "https://www.linkedin.com",
    "reddit":     "https://www.reddit.com",
    "netflix":    "https://www.netflix.com",
    "spotify":    "https://open.spotify.com",
    "discord":    "https://discord.com/app",
    "slack":      "https://slack.com",
    "telegram":   "https://web.telegram.org",
}

_BROWSER_NAMES = ("chrome", "google chrome", "firefox", "edge", "microsoft edge", "brave", "opera")


class Intent(Enum):
    MEMORY_STORE  = auto()
    MEMORY_RECALL = auto()
    REMINDER_SET  = auto()
    REMINDER_LIST = auto()
    MEDIA_CONTROL = auto()
    BROWSER       = auto()
    FILE_OP       = auto()
    SYSTEM_ACTION = auto()
    APP_OPEN      = auto()
    CONVERSATION  = auto()


@dataclass
class ParsedIntent:
    intent: Intent
    slots: dict = field(default_factory=dict)
    raw: str = ""


# ── Negative & Distractor Guards ──────────────────────────────────────────────
_DISTRACTOR_PATTERNS = [
    # Explicit negative desires: "I don't want to open Chrome", "won't stop talking about Spotify", "I wouldn't open edge"
    re.compile(
        r"\b(don'?t|do not|didn'?t|did not|won'?t|wouldn'?t|will not|never|shouldn'?t|needn'?t|stop|not going to)\s+"
        r"(?:want to\s+|like to\s+|need to\s+|bother to\s+)?(open|launch|start|run|delete|remove|shutdown|shut down|restart|mute|unmute|screenshot|remind|remember|create)\b",
        re.I,
    ),
    # Hypothetical / advisory questions: "what happens if I shut down", "what happens when you shut down", "should I delete this file"
    re.compile(
        r"^(what happens if|what happens when|what if|should i|is it safe to|how do i|why would i|can you tell me if)\b",
        re.I,
    ),
    # Third-person statements: "my friend won't stop talking about...", "she asked me to remind her"
    re.compile(
        r"^(my friend|my mom|my dad|my boss|she|he|they|someone|everybody)\b",
        re.I,
    ),
    # Past tense commentary: "I already took a screenshot", "we already opened it"
    re.compile(
        r"^(i already|we already|i just|we just)\b",
        re.I,
    ),
    # Conversational question asking definition (excluding personal 'my/our' memory inquiries):
    re.compile(
        r"\b(?:remind me,?\s+)?what(?:'s| is| are)\s+(?:a |an |the )?(?!my |our |i )[a-z0-9 _\-]+(?:\s+again)?\??$",
        re.I,
    ),
    # "remember when..." conversational nostalgia: "remember when I told you..."
    re.compile(
        r"^remember\s+(?:when|how|back\s+when)\b",
        re.I,
    ),
    # "No need to open anything", "no need to delete" — implicit negation via "no need"
    re.compile(
        r"^no need to\b",
        re.I,
    ),
]


# ── Intent Regex Patterns (Specific intents FIRST, generic APP_OPEN LAST) ──────

_PATTERNS: list[tuple[Intent, re.Pattern]] = [
    # 1. Memory recall (must precede memory store to capture "do you remember", "what is my...")
    (Intent.MEMORY_RECALL, re.compile(
        r"\b(recall|what (do i|did i|have i|is my|was my|are my)|tell me about (my|the)|"
        r"do you remember|remind me (what|who|when|where))\b", re.I)),

    # 2. Memory store
    (Intent.MEMORY_STORE, re.compile(
        r"\b(remember that|note that|save that|store that|keep in mind that|don'?t forget that|"
        r"remember|note|save|store)\b", re.I)),

    # 3. Reminder setting (including "remind me in 5 mins to...", "ping me in 20 mins about...", "in an hour", "tomorrow at 9")
    (Intent.REMINDER_SET, re.compile(
        r"\b(remind me (?:to|about|that|in|at|on|tomorrow)?|set (?:a )?reminder|alert me|notify me|ping me)\b", re.I)),

    # 4. Reminder listing
    (Intent.REMINDER_LIST, re.compile(
        r"\b(list (?:my )?reminders|show reminders|what(?:'?s| are) (?:my )?reminders|"
        r"any reminders)\b", re.I)),

    # 5. Media Control ("play music", "start a video", "play some lofi", "put on jazz", "play Bohemian Rhapsody on spotify", "pause", "resume", "skip", "next song")
    (Intent.MEDIA_CONTROL, re.compile(
        r"\b(play\s+(?:a\s+|the\s+|some\s+)?(?:video|music|song|track|audio|podcast|playlist|tune|album|stream)|"
        r"start\s+(?:a\s+|the\s+)?(?:video|music|song|track|playback|stream)|"
        r"watch\s+(?:a\s+|the\s+)?(?:video|movie|clip|show|trailer)|"
        r"put\s+on\s+(?:some\s+|the\s+)?(?:music|songs|tunes|video|lo-?fi|jazz)|"
        r"listen\s+to\s+(?:some\s+|the\s+)?(?:music|songs|podcast|lo-?fi|jazz)|"
        r"(?:play|pause|resume|stop|skip|next|prev|previous)\s+on\s+[a-z0-9_]+|"
        r"play\s+(?:.+?)\s+on\s+(?:spotify|youtube|apple\s+music|soundcloud|netflix)|"
        r"pause\s+(?:the\s+)?(?:music|song|track|audio|playback)|"
        r"resume\s+(?:the\s+)?(?:music|song|track|audio|playback)|"
        r"stop\s+(?:the\s+)?(?:music|song|track|audio|playback)|"
        r"skip\s+(?:the\s+|this\s+)?(?:song|track)?|next\s+(?:song|track)|previous\s+(?:song|track)|prev\s+(?:song|track)|"
        r"pause|resume|unpause|toggle\s+playback|shuffle\s+(?:music|songs)|"
        r"play\s+[a-z0-9_\-\s]{2,})\b", re.I)),

    # 6. Browser / Search ("search python tutorials on github", "search shoes on amazon", "look up best cameras on reddit", "google quantum physics", URLs)
    (Intent.BROWSER, re.compile(
        r"\b(search\s+(?:for\s+)?(?:.+?)\s+(?:on|in)\s+[a-z0-9_\-\.]+|"
        r"look\s+up\s+(?:.+?)\s+(?:on|in)\s+[a-z0-9_\-\.]+|"
        r"find\s+(?:.+?)\s+(?:on|in)\s+[a-z0-9_\-\.]+|"
        r"(?:on|in)\s+[a-z0-9_\-\.]+,?\s+search\s+(?:for\s+)?(?:.+)|"
        r"(?:youtube|google|github|reddit|amazon|wikipedia|bing)\s+search|"
        r"search\s+(?:for|the\s+web|google|youtube|bing|duckduckgo|github|reddit|amazon|wikipedia)|"
        r"google\s+|look\s+up\s+|look\s+it\s+up|browse\s+|find\s+info\s+on\s+|what(?:'s| is) the latest on\s+|"
        r"go\s+to\s+(?:https?://|www\.|[a-z0-9_\-]+\.(?:com|org|io|net|edu|gov|dev|ai)))\b", re.I)),


    # 7. File operations ("delete my temp file", "delete the file test.txt", "create a file called x", "remove folder y")
    (Intent.FILE_OP, re.compile(
        r"\b(create|make|new|rename|move|copy|delete|remove)\s+"
        r"(?:(?:a|an|the|my|this|that)\s+)?(?:[a-z0-9_\-\.\s]+\s+)?"
        r"(?:file|folder|directory|document|text file|temp file|docs?)\b|"
        r"\b(create|make|delete|remove|rename|move|copy)\s+(?:(?:a|an|the|my)\s+)?(?:file|folder|directory|doc)\s+(?:called|named)\b|"
        r"\b(?:delete|remove|create|make)\s+[a-z0-9_\-]+\.(?:txt|py|json|md|csv|pdf|docx?|html|log|tmp|bak)\b",
        re.I)),


    # 8. System actions ("turn the volume up", "screenshot this", "mute", "shut down", "lock")
    (Intent.SYSTEM_ACTION, re.compile(
        r"\b(turn (?:the )?volume (?:up|down)|volume (?:up|down|set)|turn (?:it )?up|turn (?:it )?down|"
        r"unmute|mute|screenshot|screen shot|take a screenshot|can you screenshot|"
        r"lock (?:the )?(?:screen|computer|pc)|sleep|shut\s*down|shutdown|restart|"
        r"brightness (?:up|down|set))\b", re.I)),

    # 9. Generic App Open (Runs LAST so specific actions are never stolen by open/start/launch)
    (Intent.APP_OPEN, re.compile(
        r"\b(open|opening|launch|launching|start|starting|run|running|execute|pull up|bring up|load|"
        r"get\s+[a-z0-9_\-\.\s]+\s+(?:open|going)|gonna need\s+[a-z0-9_\-\.\s]+|i need\s+[a-z0-9_\-\.\s]+\s+open)\b", re.I)),
]


class IntentParser:
    """Fast rule-based intent classifier with negative filtering and LLM fallback."""

    def __init__(self, llm_client=None) -> None:
        self._llm = llm_client

    def parse(self, utterance: str) -> ParsedIntent:
        raw_text = utterance.strip()
        text = self._clean_utterance(raw_text)
        if not text:
            return ParsedIntent(Intent.CONVERSATION, raw=text)

        # 1. Negative / Distractor / Question guard check
        if self._is_distractor_or_conversation(raw_text, text):
            log.debug("Distractor / question guard matched for %r -> routing to CONVERSATION", raw_text)
            return ParsedIntent(Intent.CONVERSATION, raw=raw_text)

        # 2. Fast regex match across intent patterns
        for intent, pattern in _PATTERNS:
            if pattern.search(text):
                slots = self._extract_slots(intent, text)
                log.debug("Intent matched: %s for %r (slots=%s)", intent.name, text[:60], slots)
                return ParsedIntent(intent=intent, slots=slots, raw=raw_text)

        # 3. LLM fallback for ambiguous cases
        if self._llm:
            try:
                log.debug("Regex failed, trying LLM fallback...")
                prompt = (
                    "You are an intent classifier. Given the user's text, classify it into exactly ONE of the following intents:\n"
                    "MEMORY_STORE, MEMORY_RECALL, REMINDER_SET, REMINDER_LIST, MEDIA_CONTROL, APP_OPEN, FILE_OP, BROWSER, SYSTEM_ACTION, CONVERSATION.\n\n"
                    "Also extract relevant slots if needed:\n"
                    "- MEDIA_CONTROL: action (play/pause/resume/stop/skip), query, target_app\n"
                    "- APP_OPEN: app_name, browser (optional)\n"
                    "- BROWSER: query, url, engine (e.g., youtube, github, amazon, reddit), browser (optional)\n"
                    "- SYSTEM_ACTION: action\n"
                    "- MEMORY_STORE: content\n"
                    "- REMINDER_SET: title, time_expr\n"
                    "- FILE_OP: operation, name\n\n"
                    "Provide your response EXACTLY in this format, with no other text or markdown:\n"
                    "INTENT: <INTENT_NAME>\n"
                    "SLOT: <key>=<value>\n\n"
                    f"User text: \"{text}\""
                )
                response = self._llm.quick(prompt)

                lines = response.strip().split('\n')
                intent_name = "CONVERSATION"
                slots = {}
                for line in lines:
                    line = line.strip().replace("`", "")
                    if line.startswith("INTENT:"):
                        intent_name = line.split(":", 1)[1].strip().upper()
                    elif line.startswith("SLOT:"):
                        slot_str = line.split(":", 1)[1].strip()
                        if "=" in slot_str:
                            k, v = slot_str.split("=", 1)
                            slots[k.strip()] = v.strip()

                if hasattr(Intent, intent_name) and intent_name != "CONVERSATION":
                    intent_enum = getattr(Intent, intent_name)
                    log.info("LLM Intent matched: %s (slots: %s)", intent_enum.name, slots)
                    return ParsedIntent(intent=intent_enum, slots=slots, raw=raw_text)
            except Exception as e:
                log.warning("LLM fallback failed: %s", e)

        log.debug("No pattern matched — defaulting to CONVERSATION")
        return ParsedIntent(Intent.CONVERSATION, raw=raw_text)

    # ── Guard Helpers ─────────────────────────────────────────────────────────

    def _is_distractor_or_conversation(self, raw: str, cleaned: str) -> bool:
        """Return True if the text is a negative statement, question, or distractor."""
        for pattern in _DISTRACTOR_PATTERNS:
            if pattern.search(raw) or pattern.search(cleaned):
                return True
        return False

    # ── Text Cleaning & Slot extraction ───────────────────────────────────────

    def _clean_utterance(self, utterance: str) -> str:
        text = utterance.strip()
        previous = None
        while previous != text:
            previous = text
            text = _POLITE_PREFIX_RE.sub("", text).strip()
        return text.strip(" ,.?")

    def _clean_slot_text(self, value: str) -> str:
        value = _APP_NAME_STOP_RE.sub("", value).strip()
        value = _POLITE_SUFFIX_RE.sub("", value).strip()
        value = re.sub(r"^(?:the|a|an|my|our|this)\s+", "", value, flags=re.I).strip()
        return value.strip(" ,.?")


    def _extract_browser_slot(self, text: str) -> str | None:
        t = text.lower()
        for b in _BROWSER_NAMES:
            if f"in {b}" in t or f"on {b}" in t or f"using {b}" in t or f"with {b}" in t:
                if "chrome" in b:
                    return "chrome"
                if "edge" in b:
                    return "edge"
                return b
        return None

    def _resolve_deictic_reference(self) -> str | None:
        """Resolve pronouns like 'this', 'that', 'it' from the system clipboard."""
        try:
            from PySide6.QtWidgets import QApplication
            cb = QApplication.clipboard()
            if cb:
                text = cb.text()
                if text and len(text.strip()) > 0 and len(text.strip()) < 500:
                    log.info("Resolved deictic reference from clipboard: %r", text[:60])
                    return text.strip()
        except Exception:
            pass
        return None


    def _extract_slots(self, intent: Intent, text: str) -> dict:
        slots: dict = {}
        t = text.lower()

        # Check for specified browser across intents (e.g. "open whatsapp in chrome")
        browser_slot = self._extract_browser_slot(text)
        if browser_slot:
            slots["browser"] = browser_slot

        if intent == Intent.APP_OPEN:
            url_m = re.search(r"(https?://[^\s]+|www\.[^\s]+|[a-z0-9\-_]+\.(?:com|org|net|io|edu|gov))", t)
            if url_m:
                slots["url"] = url_m.group(1)
            else:
                m = re.search(
                    r"\b(?:open|opening|launch|launching|start|starting|run|running|execute|pull up|bring up|load|gonna need|i need|get)\s+([a-z0-9 _\-\.]+)",
                    t,
                )
                if m:
                    raw_app = m.group(1)
                    raw_app = re.sub(r"\s+(?:open|going|running|for me|real quick|please)$", "", raw_app, flags=re.I)
                    for b in _BROWSER_NAMES:
                        raw_app = re.sub(rf"\s+(?:in|on|using|with)\s+{re.escape(b)}.*$", "", raw_app, flags=re.I)
                    slots["app_name"] = self._clean_slot_text(raw_app)

        elif intent == Intent.MEMORY_STORE:
            stripped = re.sub(
                r"^(remember|note|save|store|keep in mind|don'?t forget)\s*(that\s*)?",
                "", text, flags=re.I,
            ).strip()
            slots["content"] = stripped

        elif intent == Intent.MEMORY_RECALL:
            stripped = re.sub(
                r"^(recall|tell me about|what (do i|did i|have i|is my|was my)|do you remember|remind me (what|who|when|where))\s*",
                "", text, flags=re.I,
            ).strip()
            slots["query"] = stripped

        elif intent == Intent.MEDIA_CONTROL:
            action = "play"
            for verb in ("pause", "resume", "unpause", "stop", "skip", "next", "previous", "prev", "shuffle"):
                if re.search(rf"\b{verb}\b", t):
                    action = "play" if verb in ("unpause",) else verb
                    break
            slots["action"] = action

            app_m = re.search(r"\b(?:on|in)\s+([a-z0-9_\-]+)\b", t)
            if app_m:
                slots["target_app"] = app_m.group(1).strip()

            content_m = re.search(
                r"\b(?:play|start\s+(?:a\s+)?video\s+(?:of|about)?|watch|put\s+on|listen\s+to)\s+(?:a\s+|an\s+|the\s+|some\s+)?(.+?)(?:\s+(?:on|in)\s+[a-z0-9_\-]+)?$",
                text,
                re.I,
            )
            if content_m:
                q = content_m.group(1).strip()
                clean_q = re.sub(r"^(?:music|song|track|audio|video|playback|stream)$", "", q, flags=re.I).strip()
                if clean_q:
                    slots["query"] = self._clean_slot_text(clean_q)

        elif intent == Intent.REMINDER_SET:
            time_m = re.search(
                r"\b(at\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?|"
                r"in\s+(?:\d+|an?)\s*(?:sec|second|min|minute|hr|hour|day)s?|"
                r"tomorrow(?:\s+(?:morning|afternoon|evening|at\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?))?)\b",
                t,
            )
            slots["time_expr"] = time_m.group(0) if time_m else ""
            title = text
            if time_m:
                title = title.replace(time_m.group(0), " ").strip()
            title = re.sub(
                r"\b(remind me|set (?:a )?reminder (?:for|to|about|that)?|"
                r"alert me (?:to|when|about)?|notify me (?:to|about)?|ping me)\b",
                "", title, flags=re.I,
            ).strip()
            title = re.sub(r"^(?:about|to|that)\s+", "", title, flags=re.I).strip(" .,;")
            slots["title"] = title or text

        elif intent == Intent.BROWSER:
            # 1. Site search: "search <query> on/in <site>" or "look up <query> on/in <site>"
            site_m = re.search(
                r"\b(?:search\s+(?:the\s+web\s+)?(?:for\s+)?|look\s+up\s+|find\s+)(.+?)\s+(?:on|in)\s+([a-z0-9_\-\.]+)\b",
                text,
                re.I,
            )
            if site_m:
                slots["query"] = self._clean_slot_text(site_m.group(1))
                slots["engine"] = site_m.group(2).lower().strip()
            else:
                # 2. Site prefix: "on/in <site> search <query>"
                prefix_site_m = re.search(
                    r"\b(?:(?:on|in)\s+)?([a-z0-9_\-\.]+),?\s+search\s+(?:for\s+)?(.+)",
                    text,
                    re.I,
                )
                if prefix_site_m and prefix_site_m.group(1).lower() in ("youtube", "google", "github", "reddit", "amazon", "wikipedia", "bing", "x", "twitter", "imdb", "ebay", "spotify", "netflix", "duckduckgo", "stackoverflow"):
                    slots["engine"] = prefix_site_m.group(1).lower().strip()
                    slots["query"] = self._clean_slot_text(prefix_site_m.group(2))
                else:
                    # 3. Standard search query: "search for <query>", "google <query>", "look up <query>"
                    q_m = re.search(
                        r"\b(?:search\s+(?:the\s+web\s+)?(?:for\s+)?|google\s+|look\s+up\s+|find\s+info\s+on\s+|what's the latest on\s+)(.+)",
                        text,
                        re.I,
                    )
                    if q_m:
                        query_str = q_m.group(1)
                        query_str = re.sub(r"\s*,?\s*look it up.*$", "", query_str, flags=re.I)
                        query_val = self._clean_slot_text(query_str)
                        if query_val.lower() in {"this", "that", "it"}:
                            slots["query"] = self._resolve_deictic_reference() or query_val
                        else:
                            slots["query"] = query_val

            url_m = re.search(r"(https?://[^\s]+|www\.[^\s]+|[a-z0-9\-_]+\.(?:com|org|net|io|edu|gov))", t)
            if url_m and not slots.get("url"):
                slots["url"] = url_m.group(1)

        elif intent == Intent.SYSTEM_ACTION:
            for kw in ("volume up", "volume down", "turn the volume up", "turn the volume down",
                       "unmute", "mute", "screenshot", "screen shot", "take a screenshot",
                       "lock", "sleep", "shut down", "shutdown", "restart", "brightness up", "brightness down"):
                if kw in t:
                    if "volume up" in kw:
                        slots["action"] = "volume up"
                    elif "volume down" in kw:
                        slots["action"] = "volume down"
                    elif "screenshot" in kw:
                        slots["action"] = "screenshot"
                    elif "shut" in kw:
                        slots["action"] = "shutdown"
                    else:
                        slots["action"] = kw
                    break

        elif intent == Intent.FILE_OP:
            for kw in ("create", "make", "new", "rename", "move", "copy",
                       "delete", "remove"):
                if re.search(rf"\b{kw}\b", t):
                    slots["operation"] = "delete" if kw in ("delete", "remove") else ("create" if kw in ("create", "make", "new") else kw)
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
            else:
                ext_m = re.search(r"\b([a-z0-9_\-]+\.[a-z0-9]{1,5})\b", text, re.I)
                if ext_m:
                    slots["name"] = ext_m.group(1).strip()
                else:
                    phrase_m = re.search(
                        r"\b(?:create|make|new|rename|move|copy|delete|remove)\s+"
                        r"(?:(?:a|an|the|my|this|that)\s+)?"
                        r"(.+?)(?:\s+(?:file|folder|directory|document|text file|temp file))?$",
                        text,
                        re.I,
                    )
                    if phrase_m:
                        extracted = phrase_m.group(1).strip()
                        extracted = re.sub(r"\b(?:file|folder|directory|document)\b", "", extracted, flags=re.I).strip()
                        slots["name"] = self._clean_slot_text(extracted)


        return slots
