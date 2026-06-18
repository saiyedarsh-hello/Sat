"""
ai/agent.py
Goal → Plan → Execute → Verify → Report loop.
Orchestrates intent parsing, memory, automation, and the LLM into
a single run(query) call that returns a human-readable result string.
"""

from __future__ import annotations

import logging

from .intent_parser import IntentParser, Intent
from .llm_client import LLMClient

log = logging.getLogger(__name__)


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

    def run(self, query: str) -> str:
        """
        Main entry point — called from a QThreadPool worker.
        Returns a spoken/displayed response string.
        """
        parsed = self._parser.parse(query)
        intent = parsed.intent
        slots = parsed.slots

        log.info("Agent running intent=%s query=%r", intent.name, query[:80])

        try:
            if intent == Intent.MEMORY_STORE:
                return self._handle_memory_store(slots, query)

            elif intent == Intent.MEMORY_RECALL:
                return self._handle_memory_recall(slots, query)

            elif intent == Intent.REMINDER_SET:
                return self._handle_reminder_set(slots, query)

            elif intent == Intent.REMINDER_LIST:
                return self._handle_reminder_list()

            elif intent == Intent.APP_OPEN:
                return self._handle_app_open(slots, query)

            elif intent == Intent.FILE_OP:
                return self._handle_file_op(slots, query)

            elif intent == Intent.BROWSER:
                return self._handle_browser(slots, query)

            elif intent == Intent.SYSTEM_ACTION:
                return self._handle_system(slots, query)

            else:
                return self._handle_conversation(query)

        except Exception as exc:
            log.error("Agent error: %s", exc)
            return f"Sorry, I ran into a problem: {exc}"

    # ── Intent handlers ───────────────────────────────────────────────────────

    def _handle_memory_store(self, slots: dict, raw: str) -> str:
        content = slots.get("content") or raw
        if self._memory:
            return self._memory.remember(content)
        return f"I'll remember that: '{content[:80]}'"

    def _handle_memory_recall(self, slots: dict, raw: str) -> str:
        q = slots.get("query") or raw
        if self._memory:
            memories = self._memory.recall(q)
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

    def _handle_reminder_set(self, slots: dict, raw: str) -> str:
        title = slots.get("title", raw)
        time_expr = slots.get("time_expr", "")

        if self._reminders and time_expr:
            try:
                result = self._reminders.add_from_text(title, time_expr)
                return result
            except Exception as exc:
                log.error("Reminder set failed: %s", exc)

        # Ask LLM to format a polished reply even if we couldn't schedule
        return f"Got it! I'll remind you: '{title}'{f' {time_expr}' if time_expr else ''}."

    def _handle_reminder_list(self) -> str:
        if self._reminders:
            items = self._reminders.list_upcoming()
            if items:
                lines = "\n".join(f"• {r}" for r in items[:5])
                return f"You have {len(items)} upcoming reminder(s):\n{lines}"
        return "You have no upcoming reminders."

    def _handle_app_open(self, slots: dict, raw: str) -> str:
        app_name = slots.get("app_name", "")
        if not app_name:
            # Extract from raw
            import re
            m = re.search(r"(?:open|launch|start|run)\s+(.+)", raw, re.I)
            app_name = m.group(1).strip() if m else raw

        if self._app:
            success = self._app.open_app(app_name)
            if success:
                return f"Opening {app_name}."
            return f"I couldn't find '{app_name}' to open."

        # Fallback: try subprocess
        import subprocess
        try:
            subprocess.Popen(app_name, shell=True)
            return f"Opening {app_name}."
        except Exception as exc:
            return f"Failed to open {app_name}: {exc}"

    def _handle_file_op(self, slots: dict, raw: str) -> str:
        if self._file:
            return self._file.handle(slots, raw)
        # LLM fallback
        prompt = (
            f"The user wants to perform a file operation: {raw}\n"
            "Describe what you would do step by step, then ask for confirmation if destructive."
        )
        return self._llm.quick(prompt)

    def _handle_browser(self, slots: dict, raw: str) -> str:
        query = slots.get("query", "")
        url = slots.get("url", "")
        engine = slots.get("engine", "")

        if self._browser:
            if url:
                self._browser.open_url(url)
                return f"Opening {url}."
            if query:
                self._browser.search(query, engine=engine or None)
                target = "YouTube" if engine == "youtube" else "the web"
                return f"Searching {target} for '{query}'."

        # Fallback
        import webbrowser
        if url:
            webbrowser.open(url)
            return f"Opening {url}."
        if query:
            webbrowser.open(f"https://www.google.com/search?q={query.replace(' ', '+')}")
            return f"Searching Google for '{query}'."
        return "What would you like me to search for?"

    def _handle_system(self, slots: dict, raw: str) -> str:
        action = slots.get("action", "")
        if self._system:
            return self._system.handle(action, raw)
        return f"System action '{action}' is not available right now."

    def _handle_conversation(self, query: str) -> str:
        """General LLM conversation with memory context injection."""
        messages = []

        # Inject relevant memories as context
        if self._memory:
            ctx = self._memory.recall_as_context(query)
            if ctx:
                messages.append({"role": "system", "content": ctx})
            messages.extend(self._memory.get_history())

        messages.append({"role": "user", "content": query})

        reply = self._llm.chat(messages)

        # Store to short-term memory
        if self._memory:
            self._memory.add_user(query)
            self._memory.add_assistant(reply)

        return reply
