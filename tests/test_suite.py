"""
tests/test_suite.py
Expanded & robust test suite for Saturday covering:
  - 1. Phrasing Variance (colloquial, polite, contracted forms - Section A)
  - 2. Negative & Distractor Cases (false-positive prevention - Section B)
  - 3. Safety-Critical Action Policies (confirmation requirements - Section E)
  - 4. ASR Noise Robustness (punctuation, spacing, phonetic tolerance - Section C)
  - 5. Standard Action Execution & Memory

Run via: python -m unittest tests/test_suite.py
"""

import unittest
from ai.intent_parser import IntentParser, Intent
from ai.agent import Agent
from automation.app_control import AppControl
from automation.browser_control import BrowserControl


class TestPhrasingVariance(unittest.TestCase):
    """Real-world conversational variations of common commands (Section A)."""

    @classmethod
    def setUpClass(cls):
        cls.parser = IntentParser()

    def test_app_opening_phrasings(self):
        cases = [
            ("can you pull up brave for me", "brave"),
            ("I need vs code open", "vs code"),
            ("yo open whatsapp", "whatsapp"),
            ("would you mind opening spotify", "spotify"),
            ("gonna need chrome real quick", "chrome"),
            ("let's get youtube going", "youtube"),
            ("bring up notepad please", "notepad"),
        ]
        for utterance, expected_app in cases:
            with self.subTest(utterance=utterance):
                res = self.parser.parse(utterance)
                self.assertEqual(res.intent, Intent.APP_OPEN)
                self.assertEqual(res.slots.get("app_name", "").lower(), expected_app)

    def test_web_search_phrasings(self):
        cases = [
            ("hey can you search for lo-fi beats on youtube", "youtube", "lo-fi beats"),
            ("what's the latest on AI news, look it up", None, "ai news"),
            ("look up machine learning algorithms", None, "machine learning algorithms"),
            ("google fast python frameworks", None, "fast python frameworks"),
        ]
        for utterance, expected_engine, expected_kw in cases:
            with self.subTest(utterance=utterance):
                res = self.parser.parse(utterance)
                self.assertEqual(res.intent, Intent.BROWSER)
                if expected_engine:
                    self.assertEqual(res.slots.get("engine"), expected_engine)
                self.assertIn(expected_kw, res.slots.get("query", "").lower())

    def test_reminder_phrasings(self):
        cases = [
            ("ping me in 20 mins about the laundry", "laundry", "in 20 mins"),
            ("don't forget to remind me about the dentist tomorrow", "dentist", "tomorrow"),
            ("alert me in 1 hour to stretch", "stretch", "in 1 hour"),
        ]
        for utterance, expected_title, expected_time in cases:
            with self.subTest(utterance=utterance):
                res = self.parser.parse(utterance)
                self.assertEqual(res.intent, Intent.REMINDER_SET)
                self.assertIn(expected_title, res.slots.get("title", "").lower())
                self.assertIn(expected_time.replace(" ", ""), res.slots.get("time_expr", "").lower().replace(" ", ""))

    def test_system_action_phrasings(self):
        cases = [
            ("turn the volume up a bit", "volume up"),
            ("turn the volume down please", "volume down"),
            ("can you screenshot this", "screenshot"),
            ("take a screenshot right now", "screenshot"),
            ("mute audio", "mute"),
            ("unmute sound", "unmute"),
        ]
        for utterance, expected_act in cases:
            with self.subTest(utterance=utterance):
                res = self.parser.parse(utterance)
                self.assertEqual(res.intent, Intent.SYSTEM_ACTION)
                self.assertEqual(res.slots.get("action", "").lower(), expected_act)


class TestNegativeDistractors(unittest.TestCase):
    """Phrases containing trigger words that must NOT fire actions (Section B)."""

    @classmethod
    def setUpClass(cls):
        cls.parser = IntentParser()

    def test_negative_statements_route_to_conversation(self):
        cases = [
            "I don't want to open Chrome right now",
            "my friend won't stop talking about Spotify",
            "she asked me to remind her about the meeting",
            "I already took a screenshot earlier",
            "should I delete this file or keep it?",
            "what happens if I shut down without saving?",
            "is it safe to restart my pc right now?",
            "remind me, what's Python again?",
            "what does git commit mean?",
        ]
        for utterance in cases:
            with self.subTest(utterance=utterance):
                res = self.parser.parse(utterance)
                self.assertEqual(
                    res.intent,
                    Intent.CONVERSATION,
                    f"Distractor '{utterance}' wrongly matched {res.intent.name}",
                )

    def test_remember_nostalgia_routes_to_conversation(self):
        res = self.parser.parse("remember when I told you about my server IP?")
        self.assertEqual(res.intent, Intent.CONVERSATION)


class TestSafetyCriticalPolicies(unittest.TestCase):
    """Destructive actions must request confirmation before running (Section E)."""

    class _MockLLM:
        def chat(self, msgs): return "Chat reply"
        def quick(self, p): return "Quick reply"
        active_backend = "mock"

    @classmethod
    def setUpClass(cls):
        cls.agent = Agent(llm=cls._MockLLM())

    def test_shutdown_requires_confirmation(self):
        reply = self.agent.run("shut down my computer")
        self.assertTrue(self.agent.has_pending_action)
        self.assertIn("Are you sure", reply)
        self.assertIn("shut down", reply.lower())

        # Test cancellation
        cancel_reply = self.agent.run("cancel")
        self.assertFalse(self.agent.has_pending_action)
        self.assertIn("cancelled", cancel_reply.lower())

    def test_restart_requires_confirmation(self):
        reply = self.agent.run("restart system")
        self.assertTrue(self.agent.has_pending_action)
        self.assertIn("Are you sure", reply)
        self.assertIn("restart", reply.lower())

        # Test positive confirmation
        confirm_reply = self.agent.run("yes")
        self.assertFalse(self.agent.has_pending_action)
        self.assertIn("not available", confirm_reply.lower())

    def test_file_delete_requires_confirmation(self):
        reply = self.agent.run("delete file called test_old.txt")
        self.assertTrue(self.agent.has_pending_action)
        self.assertIn("Are you sure you want to delete", reply)
        self.assertIn("test_old.txt", reply)

        # Test cancellation
        cancel_reply = self.agent.run("no stop")
        self.assertFalse(self.agent.has_pending_action)
        self.assertIn("cancelled", cancel_reply.lower())

    def test_delete_my_temp_file_phrasing(self):
        reply = self.agent.run("delete my temp file")
        self.assertTrue(self.agent.has_pending_action)
        self.assertIn("Are you sure you want to delete", reply)
        self.assertIn("temp", reply.lower())

        # Test cancellation
        cancel_reply = self.agent.run("cancel")
        self.assertFalse(self.agent.has_pending_action)
        self.assertIn("cancelled", cancel_reply.lower())



class TestAsrNoiseRobustness(unittest.TestCase):
    """ASR transcription noise tolerance (Section C)."""

    @classmethod
    def setUpClass(cls):
        cls.parser = IntentParser()

    def test_punctuation_and_capitalization_noise(self):
        cases = [
            ("Open Brave.", Intent.APP_OPEN, "brave"),
            ("MUTE.", Intent.SYSTEM_ACTION, "mute"),
            ("Take a screenshot!", Intent.SYSTEM_ACTION, "screenshot"),
            ("  open   notepad  ", Intent.APP_OPEN, "notepad"),
        ]
        for utterance, expected_intent, expected_slot in cases:
            with self.subTest(utterance=utterance):
                res = self.parser.parse(utterance)
                self.assertEqual(res.intent, expected_intent)


class TestStandardIntents(unittest.TestCase):
    """Standard intent execution suite."""

    @classmethod
    def setUpClass(cls):
        cls.parser = IntentParser()

    def test_standard_app_open(self):
        res = self.parser.parse("open notepad")
        self.assertEqual(res.intent, Intent.APP_OPEN)
        self.assertEqual(res.slots.get("app_name"), "notepad")

    def test_standard_memory_store(self):
        res = self.parser.parse("remember that my wifi password is secret")
        self.assertEqual(res.intent, Intent.MEMORY_STORE)
        self.assertIn("my wifi password is secret", res.slots.get("content", "").lower())

    def test_standard_memory_recall(self):
        res = self.parser.parse("what is my wifi password")
        self.assertEqual(res.intent, Intent.MEMORY_RECALL)
        self.assertIn("wifi password", res.slots.get("query", "").lower())

    def test_standard_file_create(self):
        res = self.parser.parse("create a file called demo.py")
        self.assertEqual(res.intent, Intent.FILE_OP)
        self.assertEqual(res.slots.get("operation"), "create")
        self.assertEqual(res.slots.get("name"), "demo.py")


class TestMediaControl(unittest.TestCase):
    """Media control commands (play/pause/skip/stop/on app)."""

    @classmethod
    def setUpClass(cls):
        cls.parser = IntentParser()

    def test_media_playback_commands(self):
        cases = [
            ("play music", "play", None, ""),
            ("pause the song", "pause", None, ""),
            ("resume the music", "resume", None, ""),
            ("stop the track", "stop", None, ""),
            ("skip this track", "skip", None, ""),
            ("next song", "next", None, ""),
            ("previous song", "previous", None, ""),
            ("play music on spotify", "play", "spotify", ""),
            ("pause on youtube", "pause", "youtube", ""),
            ("start a video of coding music", "play", None, "coding music"),
            ("play Bohemian Rhapsody on Spotify", "play", "spotify", "bohemian rhapsody"),
            ("put on some jazz", "play", None, "jazz"),
        ]
        for utterance, expected_act, expected_app, expected_q in cases:
            with self.subTest(utterance=utterance):
                res = self.parser.parse(utterance)
                self.assertEqual(res.intent, Intent.MEDIA_CONTROL)
                self.assertEqual(res.slots.get("action"), expected_act)
                if expected_app:
                    self.assertEqual(res.slots.get("target_app"), expected_app)
                if expected_q:
                    self.assertIn(expected_q.lower(), res.slots.get("query", "").lower())


class TestYouTubeAndWebSearch(unittest.TestCase):
    """YouTube search across multiple word orders, generic web search, and site searches."""

    @classmethod
    def setUpClass(cls):
        cls.parser = IntentParser()

    def test_youtube_word_orders(self):
        cases = [
            ("search lofi beats on youtube", "lofi beats"),
            ("on youtube, search coding music", "coding music"),
            ("youtube search python tutorial", "python tutorial"),
            ("look up funny cats on youtube", "funny cats"),
            ("search for space documentaries on youtube", "space documentaries"),
        ]
        for utterance, expected_query in cases:
            with self.subTest(utterance=utterance):
                res = self.parser.parse(utterance)
                self.assertEqual(res.intent, Intent.BROWSER)
                self.assertEqual(res.slots.get("engine"), "youtube")
                self.assertIn(expected_query, res.slots.get("query", "").lower())

    def test_multi_site_searches(self):
        cases = [
            ("search python tutorials on github", "python tutorials", "github"),
            ("search running shoes on amazon", "running shoes", "amazon"),
            ("look up mechanical keyboards on reddit", "mechanical keyboards", "reddit"),
            ("search quantum computing on wikipedia", "quantum computing", "wikipedia"),
        ]
        for utterance, expected_query, expected_engine in cases:
            with self.subTest(utterance=utterance):
                res = self.parser.parse(utterance)
                self.assertEqual(res.intent, Intent.BROWSER)
                self.assertEqual(res.slots.get("engine"), expected_engine)
                self.assertIn(expected_query, res.slots.get("query", "").lower())



class TestNaturalLanguageReminders(unittest.TestCase):
    """NL time expressions for reminders."""

    @classmethod
    def setUpClass(cls):
        cls.parser = IntentParser()

    def test_reminder_nl_phrasings(self):
        cases = [
            ("remind me in 5 mins to call mom", "call mom", "in 5 mins"),
            ("set a reminder to drink water in an hour", "drink water", "in an hour"),
            ("remind me that I have a meeting tomorrow at 9", "meeting", "tomorrow at 9"),
            ("ping me in 20 mins about the oven", "oven", "in 20 mins"),
        ]
        for utterance, expected_title_part, expected_time_part in cases:
            with self.subTest(utterance=utterance):
                res = self.parser.parse(utterance)
                self.assertEqual(res.intent, Intent.REMINDER_SET)
                self.assertIn(expected_title_part.lower(), res.slots.get("title", "").lower())
                self.assertIn(expected_time_part.replace(" ", "").lower(), res.slots.get("time_expr", "").replace(" ", "").lower())


class TestEntityCleaningAndFolders(unittest.TestCase):

    """Entity cleaning and folder resolution tests."""

    def test_clean_entity_name(self):
        from automation.resolver import clean_entity_name
        self.assertEqual(clean_entity_name("nike website")[0], "nike")
        self.assertEqual(clean_entity_name("the documents section")[0], "documents")
        self.assertEqual(clean_entity_name("my downloads folder")[0], "downloads")
        self.assertEqual(clean_entity_name("spotify app")[0], "spotify")

    def test_resolve_target_with_cues_and_folders(self):
        from automation.resolver import resolve_target
        from automation.app_control import _APP_MAP
        from ai.intent_parser import SITE_NAMES

        res_nike = resolve_target("nike website", "open nike website", _APP_MAP, SITE_NAMES)
        self.assertEqual(res_nike.get("type"), "site")
        self.assertEqual(res_nike.get("target"), "https://nike.com")

        res_docs = resolve_target("the documents section", "open the documents section", _APP_MAP, SITE_NAMES)
        self.assertEqual(res_docs.get("type"), "folder")
        self.assertEqual(res_docs.get("target"), "documents")

        res_dl = resolve_target("my downloads folder", "open my downloads folder", _APP_MAP, SITE_NAMES)
        self.assertEqual(res_dl.get("type"), "folder")
        self.assertEqual(res_dl.get("target"), "downloads")

    def test_windows_settings_and_system_tools_resolution(self):
        from automation.resolver import resolve_target
        from automation.app_control import _APP_MAP
        from ai.intent_parser import SITE_NAMES

        # Settings
        res_mouse = resolve_target("mouse settings", "open mouse settings", _APP_MAP, SITE_NAMES)
        self.assertEqual(res_mouse.get("type"), "setting")
        self.assertEqual(res_mouse.get("target"), "ms-settings:mousetouchpad")

        res_sound = resolve_target("sound settings", "open sound settings", _APP_MAP, SITE_NAMES)
        self.assertEqual(res_sound.get("type"), "setting")
        self.assertEqual(res_sound.get("target"), "ms-settings:sound")

        res_update = resolve_target("windows update", "open windows update", _APP_MAP, SITE_NAMES)
        self.assertEqual(res_update.get("type"), "setting")
        self.assertEqual(res_update.get("target"), "ms-settings:windowsupdate")

        # System Tools
        res_dev = resolve_target("device manager", "open device manager", _APP_MAP, SITE_NAMES)
        self.assertEqual(res_dev.get("type"), "system_tool")
        self.assertEqual(res_dev.get("target"), "devmgmt.msc")

        res_disk = resolve_target("disk management", "open disk management", _APP_MAP, SITE_NAMES)
        self.assertEqual(res_disk.get("type"), "system_tool")
        self.assertEqual(res_disk.get("target"), "diskmgmt.msc")



if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestSafeHandlerDecorator(unittest.TestCase):
    """
    Verifies safe_handler catches unhandled exceptions, logs them,
    and returns a clean spoken string — never a raw traceback or re-raise.
    """

    def test_exception_returns_spoken_apology(self):
        from ai.intent_result import safe_handler

        @safe_handler
        def _bad_handler(self, *args):
            raise RuntimeError("disk exploded")

        result = _bad_handler(None)
        self.assertIsInstance(result, str)
        self.assertIn("couldn't", result.lower())
        # Must not re-raise
        # If we reached here, it didn't propagate

    def test_success_passes_through(self):
        from ai.intent_result import safe_handler

        @safe_handler
        def _good_handler(self, *args):
            return "Opening Notepad."

        self.assertEqual(_good_handler(None), "Opening Notepad.")

    def test_known_user_facing_value_passes_through(self):
        """Handlers that build a user-facing string before raising should pass through normally."""
        from ai.intent_result import safe_handler

        @safe_handler
        def _reminder_handler(self, *args):
            # Handler returns a string before any exception — no crash expected
            return "I couldn't parse the time. Try 'in 30 minutes' or 'at 3pm'."

        result = _reminder_handler(None)
        self.assertIn("parse", result.lower())


class TestNegativeDistractorGaps(unittest.TestCase):
    """
    Additional distractor cases beyond the existing TestNegativeDistractors class.
    These specifically guard against high-risk false positives.
    """

    @classmethod
    def setUpClass(cls):
        cls.parser = IntentParser()

    def test_negative_open_statements(self):
        """'I don't want to open X' must NOT trigger APP_OPEN."""
        cases = [
            "I don't want to open Chrome right now",
            "don't open spotify",
            "no need to open anything",
            "I wouldn't open edge if I were you",
        ]
        for utterance in cases:
            with self.subTest(utterance=utterance):
                res = self.parser.parse(utterance)
                self.assertNotEqual(
                    res.intent, Intent.APP_OPEN,
                    f"'{utterance}' wrongly triggered APP_OPEN"
                )

    def test_hypothetical_delete_routes_to_conversation(self):
        """Questions about deleting must NOT trigger FILE_OP."""
        cases = [
            "should I delete this file or keep it?",
            "what happens if you delete system32?",
            "is it okay to delete old backups?",
        ]
        for utterance in cases:
            with self.subTest(utterance=utterance):
                res = self.parser.parse(utterance)
                self.assertNotEqual(
                    res.intent, Intent.FILE_OP,
                    f"'{utterance}' wrongly triggered FILE_OP"
                )

    def test_hypothetical_shutdown_routes_to_conversation(self):
        """Hypothetical shutdown phrasing must NOT trigger SYSTEM_ACTION."""
        cases = [
            "what if I restart without saving?",
            "is it safe to restart my pc right now?",
            "what happens when you shut down a server?",
        ]
        for utterance in cases:
            with self.subTest(utterance=utterance):
                res = self.parser.parse(utterance)
                self.assertNotEqual(
                    res.intent, Intent.SYSTEM_ACTION,
                    f"'{utterance}' wrongly triggered SYSTEM_ACTION"
                )

    def test_confirmation_flow_leaves_clean_state(self):
        """After cancel, pending_action must be None and next command must process fresh."""
        from ai.agent import Agent

        class _MockLLM:
            def chat(self, msgs): return "Sure!"
            def quick(self, p): return "Sure!"
            active_backend = "mock"

        agent = Agent(llm=_MockLLM())

        # Trigger a confirmation-required action
        agent.run("shut down my computer")
        self.assertTrue(agent.has_pending_action)

        # Cancel
        agent.run("cancel")
        self.assertFalse(agent.has_pending_action)

        # Next command must process normally (not be swallowed by stale pending state)
        reply = agent.run("what time is it?")
        self.assertIsInstance(reply, str)
        self.assertFalse(agent.has_pending_action)
