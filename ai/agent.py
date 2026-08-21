"""
ai/agent.py
Goal -> Plan -> Execute -> Verify -> Report loop.
Orchestrates intent parsing, memory, automation, browser selection,
safety-critical confirmations, and the LLM into a single run(query) call
that returns a human-readable result.
"""

from __future__ import annotations

import logging
import re

from .intent_parser import IntentParser, Intent, SITE_NAMES
from .intent_result import safe_handler, IntentResult, IRREVERSIBLE_ACTIONS
from .llm_client import LLMClient
from automation.resolver import resolve_target, launch_app_id, open_folder, open_setting, open_system_tool
from automation.app_control import _APP_MAP as _STATIC_APP_MAP

log = logging.getLogger(__name__)

_BROWSER_KEYWORDS = {
    "chrome": "chrome",
    "google chrome": "chrome",
    "edge": "edge",
    "microsoft edge": "edge",
    "firefox": "firefox",
    "mozilla": "firefox",
    "brave": "brave",
    "opera": "opera",
}


class Agent:
    """Saturday's top-level reasoning agent."""

    def __init__(
        self,
        llm: LLMClient,
        memory=None,       # MemoryManager
        app_control=None,  # AppControl
        file_ops=None,     # FileOps
        browser=None,      # BrowserControl
        system=None,       # SystemActions
        reminders=None,    # ReminderEngine
    ) -> None:
        self._llm = llm
        self._memory = memory
        self._app = app_control
        self._file = file_ops
        self._browser = browser
        self._system = system
        self._reminders = reminders
        self._parser = IntentParser(llm)
        self._pending_action: dict | None = None
        log.info(
            "Agent: ready — IntentParser and conversation handler share LLMClient backend=%s",
            llm.active_backend if hasattr(llm, "active_backend") else "unknown",
        )

    @property
    def has_pending_action(self) -> bool:
        """Return True if Agent is currently awaiting user input (e.g. browser choice or confirmation)."""
        return self._pending_action is not None

    def clear_pending_action(self) -> None:
        """Cancel and clear any pending multi-turn action / clarification for a fresh task."""
        if self._pending_action:
            log.info("Agent: cleared pending action (%s) for fresh task.", self._pending_action.get("type"))
            self._pending_action = None

    def reset(self) -> None:
        """Reset agent state for a fresh new task."""
        self.clear_pending_action()


    def run(self, query: str) -> str:
        """
        Main entry point — called from a QThreadPool worker.
        Returns a spoken/displayed response string.
        """
        clean_q = query.strip()
        if not clean_q:
            return "I'm listening. What would you like to do?"

        # ── 1. Check for pending multi-turn actions ───────────────────────────
        if self._pending_action:
            action_type = self._pending_action.get("type")
            if action_type == "choose_browser":
                res = self._handle_pending_browser_choice(clean_q)
                if res is not None:
                    return res
            elif action_type == "confirm_action":
                res = self._handle_pending_confirmation(clean_q)
                if res is not None:
                    return res
            elif action_type == "clarify_open":
                res = self._handle_pending_clarify(clean_q)
                if res is not None:
                    return res

        # ── 2. Parse Intent ───────────────────────────────────────────────────
        parsed = self._parser.parse(clean_q)
        intent = parsed.intent
        slots = parsed.slots

        log.info("Agent running intent=%s query=%r slots=%s", intent.name, clean_q[:80], slots)

        try:
            if intent == Intent.MEMORY_STORE:
                return self._handle_memory_store(slots, clean_q)

            elif intent == Intent.MEMORY_RECALL:
                return self._handle_memory_recall(slots, clean_q)

            elif intent == Intent.REMINDER_SET:
                return self._handle_reminder_set(slots, clean_q)

            elif intent == Intent.REMINDER_LIST:
                return self._handle_reminder_list()

            elif intent == Intent.MEDIA_CONTROL:
                return self._handle_media_control(slots, clean_q)

            elif intent == Intent.BROWSER:
                return self._handle_browser(slots, clean_q)

            elif intent == Intent.FILE_OP:
                return self._handle_file_op(slots, clean_q)

            elif intent == Intent.SYSTEM_ACTION:
                return self._handle_system(slots, clean_q)

            elif intent == Intent.APP_OPEN:
                return self._handle_app_open(slots, clean_q)

            else:
                return self._handle_conversation(clean_q)

        except Exception as exc:
            log.error("Agent unhandled error for query %r: %s", clean_q, exc, exc_info=True)
            return "I ran into an unexpected problem. Please check the logs for details."

    # ── Multi-turn Handlers ───────────────────────────────────────────────────

    def _handle_pending_browser_choice(self, query: str) -> str | None:
        """Process user's response when Saturday previously asked which browser to use."""
        q_lower = query.lower().strip()

        # Check for cancel
        if any(w in q_lower for w in ("cancel", "never mind", "nevermind", "stop", "no thanks", "no")):
            self._pending_action = None
            return "Okay, cancelled."

        # Check for default
        if any(w in q_lower for w in ("default", "system default", "any", "standard", "normal")):
            url = self._pending_action.get("url", "")
            service = self._pending_action.get("service", "website")
            self._pending_action = None
            if self._browser and url:
                self._browser.open_url(url)
                return f"Opening {service} in your default browser."
            return "Opening in your default browser."

        # Check for specific browser name
        detected_browser = None
        for name, key in _BROWSER_KEYWORDS.items():
            if name in q_lower:
                detected_browser = key
                break

        if detected_browser:
            url = self._pending_action.get("url", "")
            service = self._pending_action.get("service", "the website")
            self._pending_action = None
            if self._browser:
                self._browser.set_preferred_browser(detected_browser)
                if url:
                    self._browser.open_url_in(detected_browser, url)
                return f"Opening {service} in {detected_browser.title()}. I'll remember {detected_browser.title()} for future web links."
            return f"Opening in {detected_browser.title()}."

        # If user asked an entirely different command, clear pending state and let normal parser handle it
        self._pending_action = None
        return None

    def _handle_pending_confirmation(self, query: str) -> str | None:
        """Process user's response to a safety-critical confirmation request."""
        q_lower = query.lower().strip()
        action_info = self._pending_action
        self._pending_action = None

        # Positive confirmation
        if any(w in q_lower for w in ("yes", "confirm", "proceed", "do it", "sure", "yep", "yeah", "ok", "okay")):
            act_type = action_info.get("action_type")
            if act_type == "system":
                action = action_info.get("action", "")
                raw = action_info.get("raw", "")
                if self._system:
                    return self._system.handle(action, raw)
                return f"System action '{action}' is not available."
            elif act_type == "file_delete":
                name = action_info.get("name", "")
                if self._file:
                    return self._file.delete(name)
                return f"File deletion for '{name}' is not available."

        # Rejection / Cancel
        return "Okay, action cancelled. No changes were made."

    # ── Intent handlers ───────────────────────────────────────────────────────

    @safe_handler
    def _handle_memory_store(self, slots: dict, raw: str) -> str:
        content = slots.get("content", raw)
        if self._memory:
            self._memory.store(content)
            return f"I've remembered that: '{content}'."
        return "Memory system is not available right now."

    @safe_handler
    def _handle_memory_recall(self, slots: dict, raw: str) -> str:
        query = slots.get("query", raw)
        if self._memory:
            memories = self._memory.recall(query, k=3)
            if memories:
                context = "\n".join(f"- {m}" for m in memories[:5])
                prompt = (
                    f"The user asked: {raw}\n\n"
                    f"Relevant memories:\n{context}\n\n"
                    "Give a short, natural reply based on these memories."
                )
                return self._llm.quick(prompt)
            return "I don't have anything stored about that yet."
        return "Memory system is not available right now."

    @safe_handler
    def _handle_reminder_set(self, slots: dict, raw: str) -> str:
        title = slots.get("title", raw)
        time_expr = slots.get("time_expr", "")

        if self._reminders and time_expr:
            try:
                result = self._reminders.add_from_text(title, time_expr)
                return result
            except Exception as exc:
                log.error("Reminder set failed: %s", exc)

        return f"Got it! I'll remind you: '{title}'{f' {time_expr}' if time_expr else ''}."

    @safe_handler
    def _handle_reminder_list(self) -> str:
        if self._reminders:
            items = self._reminders.list_upcoming()
            if items:
                lines = "\n".join(f"• {r}" for r in items[:5])
                return f"You have {len(items)} upcoming reminder(s):\n{lines}"
        return "You have no upcoming reminders."

    @safe_handler
    def _handle_app_open(self, slots: dict, raw: str) -> str:
        if slots.get("url"):
            return self._handle_browser(slots, raw)

        app_name = slots.get("app_name", "")
        if not app_name:
            m = re.search(r"(?:open|launch|start|run|pull up|get)\s+(.+)", raw, re.I)
            app_name = m.group(1).strip() if m else raw

        app_key = app_name.lower().strip()
        browser_slot = slots.get("browser")

        # ── Step 0: Check long-term memory for a previously learned preference ──
        if self._memory:
            pref_key = f"open_preference:{app_key}"
            remembered = self._memory.recall(pref_key, n=1)
            if remembered:
                pref = remembered[0]  # e.g. "app" or "site:https://..."
                log.info("Memory preference for '%s': %s", app_key, pref)
                if pref.startswith("site:"):
                    url = pref[5:]
                    return self._open_url_with_browser(url, app_name.title(), browser_slot)
                elif pref == "app":
                    if self._app and self._app.open_app(app_key):
                        return f"Opening {app_name.title()}."

        # ── Step 1: Resolver — smart disambiguation with cue words ─────────────
        result = resolve_target(
            name=app_key,
            utterance=raw,
            app_map=_STATIC_APP_MAP,
            site_names=SITE_NAMES,
        )

        rtype = result["type"]

        if rtype == "setting":
            target = result["target"]
            label = result.get("label", "Settings")
            ok = open_setting(target)
            if ok:
                return f"Opening {label}."
            return f"Could not open {label}."

        elif rtype == "system_tool":
            target = result["target"]
            label = result.get("label", "System Tool")
            ok = open_system_tool(target)
            if ok:
                return f"Opening {label}."
            return f"Could not open {label}."

        elif rtype == "folder":
            target = result["target"]
            ok = open_folder(target)
            if ok:
                return f"Opening {target.title()} folder."
            return f"Could not open the {target.title()} folder."

        elif rtype == "app":
            # Launched via _APP_MAP / PATH / static map
            target = result["target"]
            launch_via = result.get("launch_via")
            if launch_via == "shell":
                # Dynamic Start Menu AppID
                ok = launch_app_id(target)
                if ok:
                    return f"Opening {app_name.title()}."
            elif self._app:
                ok = self._app.open_app(app_key)
                if ok:
                    return f"Opening {app_name.title()}."
            return f"I found '{app_name}' but couldn't open it — it may not be installed."

        elif rtype == "site":
            url = result["target"]
            return self._open_url_with_browser(url, app_name.title(), browser_slot)

        elif rtype == "clarify":
            # Genuinely ambiguous (e.g. "open claude") — ask once, store forever
            question = result["question"]
            self._pending_action = {
                "type":     "clarify_open",
                "name":     app_key,
                "options":  result["options"],
                "browser":  browser_slot,
            }
            return question

        else:  # unresolved
            return (f"I don't know '{app_name}' yet. "
                    f"Is that an app or a website? You can say "
                    f"'open {app_name} website' or 'open {app_name} app' to be specific.")

    def _open_url_with_browser(self, url: str, label: str, browser_slot: str | None) -> str:
        """Open a URL in the preferred/specified browser, or ask which one."""
        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        if browser_slot and self._browser:
            self._browser.open_url_in(browser_slot, url)
            return f"Opening {label} in {browser_slot.title()}."

        if self._browser:
            pref = self._browser.preferred_browser()
            if pref:
                self._browser.open_url_in(pref, url)
                return f"Opening {label} in {pref.title()}."

            self._pending_action = {
                "type":    "choose_browser",
                "url":     url,
                "service": label,
            }
            prompt = (self._browser.browser_choice_prompt()
                      or "Which browser — Chrome, Edge, Brave, or Firefox?")
            return f"Which browser would you like to open {label} in? {prompt}"

        import webbrowser
        webbrowser.open(url)
        return f"Opening {label}."

    def _handle_pending_clarify(self, query: str) -> str | None:
        """Handle user reply to 'app or website?' clarification."""
        q_lower = query.lower().strip()
        pending = self._pending_action
        name    = pending.get("name", "")
        options = pending.get("options", {})
        browser = pending.get("browser")

        # Cancel
        if any(w in q_lower for w in ("cancel", "never mind", "nevermind", "stop", "no")):
            self._pending_action = None
            return "Okay, cancelled."

        chose_site = any(w in q_lower for w in ("website", "site", "web", "browser", "online", "url"))
        chose_app  = any(w in q_lower for w in ("app", "desktop", "program", "application", "installed"))

        if chose_site and options.get("site"):
            url = options["site"]
            self._pending_action = None
            # Persist preference so we never ask again
            if self._memory:
                self._memory.remember(f"open_preference:{name}", tags="open_preference")
            return self._open_url_with_browser(url, name.title(), browser)

        if chose_app and options.get("app"):
            exe = options["app"]
            self._pending_action = None
            if self._memory:
                self._memory.remember(f"open_preference:{name}=app", tags="open_preference")
            if self._app and self._app.open_app(name):
                return f"Opening {name.title()}."
            return f"Couldn't open the {name.title()} desktop app — it may not be installed."

        # Didn't recognise the answer — re-prompt once
        return f"Sorry, did you want the {name.title()} desktop app or the website? Say 'app' or 'website'."

    @safe_handler
    def _handle_file_op(self, slots: dict, raw: str) -> str:
        op = slots.get("operation", "").lower()
        name = slots.get("name", "")

        # Safety-Critical Policy: Confirm destructive deletions
        if op in ("delete", "remove"):
            if not name:
                m = re.search(r'(?:called|named)\s+"?([^"]+)"?|file\s+([a-z0-9_\-\.]+)', raw, re.I)
                name = m.group(1) or m.group(2) if m else "the file"
            self._pending_action = {
                "type": "confirm_action",
                "action_type": "file_delete",
                "name": name,
                "slots": slots,
                "raw": raw,
            }
            return f"Are you sure you want to delete '{name}'? Say yes to confirm or cancel to abort."

        if self._file:
            return self._file.handle(slots, raw)
        return f"File operation on '{name}' completed."

    @safe_handler
    def _handle_browser(self, slots: dict, raw: str) -> str:
        query = slots.get("query", "")
        url = slots.get("url", "")
        engine = slots.get("engine", "")
        browser_slot = slots.get("browser")

        if url:
            label = url.split("/")[2] if "/" in url else url
            return self._open_url_with_browser(url, label, browser_slot)

        if query:
            if self._browser:
                self._browser.search(query, engine=engine or None)
                target = engine.title() if engine else "the web"
                return f"Searching {target} for '{query}'."

            import webbrowser
            webbrowser.open(f"https://www.google.com/search?q={query.replace(' ', '+')}")
            return f"Searching Google for '{query}'."

        return "What would you like me to search for?"

    @safe_handler
    def _handle_system(self, slots: dict, raw: str) -> str:
        action = slots.get("action", "").lower().strip()

        # Safety-Critical Policy: Confirm shutdown and restart
        if action in ("shutdown", "restart"):
            self._pending_action = {
                "type": "confirm_action",
                "action_type": "system",
                "action": action,
                "raw": raw,
            }
            verb = "shut down" if action == "shutdown" else "restart"
            return f"Are you sure you want to {verb} your computer? Say yes to confirm or cancel to abort."

        if self._system:
            return self._system.handle(action, raw)
        return f"System action '{action}' is not available right now."

    @safe_handler
    def _handle_media_control(self, slots: dict, raw: str) -> str:
        action = slots.get("action", "play").lower().strip()
        target_app = slots.get("target_app", "").lower().strip()
        query = slots.get("query", "").strip()

        # 1. Track / Video / Podcast search query (e.g. "play some lofi beats", "start a video of coding music", "watch cat videos")
        if query:
            if target_app == "spotify":
                if self._browser:
                    self._browser.open_url(f"https://open.spotify.com/search/{query.replace(' ', '%20')}")
                    return f"Playing '{query}' on Spotify."
                elif self._app and self._app.is_installed("spotify"):
                    self._app.open_app("spotify")
                    return f"Opening Spotify for '{query}'."

            # Default to YouTube for music and video playback queries
            if self._browser:
                self._browser.search(query, engine="youtube")
                return f"Playing '{query}' on YouTube."

        # 2. If a specific app was requested with no track query (e.g. "play music on spotify")
        if target_app:
            if self._app and self._app.is_installed(target_app):
                self._app.open_app(target_app)
            if self._system:
                if action in ("play", "pause", "resume", "toggle", "unpause"):
                    self._system.media_play_pause()
                elif action in ("next", "skip"):
                    self._system.media_next()
                elif action in ("previous", "prev", "back"):
                    self._system.media_prev()
                elif action in ("stop",):
                    self._system.media_stop()
            return f"Playing on {target_app.title()}."

        # 3. Virtual media keys (play/pause toggle, skip, prev, stop)
        if self._system:
            if action in ("play", "pause", "resume", "toggle", "unpause"):
                return self._system.media_play_pause()
            elif action in ("next", "skip"):
                return self._system.media_next()
            elif action in ("previous", "prev", "back"):
                return self._system.media_prev()
            elif action in ("stop",):
                return self._system.media_stop()
            elif action == "shuffle":
                return self._system.media_play_pause()

        return "Media controls are not available right now."


    @safe_handler
    def _handle_conversation(self, query: str) -> str:
        """General LLM conversation with memory context injection."""
        messages = []

        if self._memory:
            ctx = self._memory.recall_as_context(query)
            if ctx:
                messages.append({"role": "system", "content": ctx})
            messages.extend(self._memory.get_history())

        messages.append({"role": "user", "content": query})

        reply = self._llm.chat(messages)

        if self._memory:
            self._memory.add_user(query)
            self._memory.add_assistant(reply)

        return reply
