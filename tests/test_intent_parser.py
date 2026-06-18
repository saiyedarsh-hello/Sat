import pytest
from ai.intent_parser import IntentParser, Intent

@pytest.fixture
def parser():
    return IntentParser()

def test_memory_store(parser):
    res = parser.parse("remember that my favorite color is blue")
    assert res.intent == Intent.MEMORY_STORE
    assert res.slots.get("content") == "my favorite color is blue"

def test_memory_recall(parser):
    res = parser.parse("what do I know about Python")
    assert res.intent == Intent.MEMORY_RECALL
    assert "python" in res.slots.get("query", "").lower()

def test_reminder_set(parser):
    res = parser.parse("remind me to buy milk in 30 minutes")
    assert res.intent == Intent.REMINDER_SET
    assert "buy milk" in res.slots.get("title", "").lower()
    assert res.slots.get("time_expr") == "in 30 minutes"

def test_app_open(parser):
    res = parser.parse("open notepad")
    assert res.intent == Intent.APP_OPEN
    assert res.slots.get("app_name") == "notepad"

def test_app_open_with_wake_word_and_polite_suffix(parser):
    res = parser.parse("Saturday can you open calculator please")
    assert res.intent == Intent.APP_OPEN
    assert res.slots.get("app_name") == "calculator"

def test_system_action(parser):
    res = parser.parse("volume down")
    assert res.intent == Intent.SYSTEM_ACTION
    assert res.slots.get("action") == "volume down"

def test_browser_search(parser):
    res = parser.parse("search the web for funny cats")
    assert res.intent == Intent.BROWSER
    assert res.slots.get("query") == "funny cats"

def test_browser_open_site(parser):
    res = parser.parse("open youtube")
    assert res.intent == Intent.BROWSER
    assert res.slots.get("url") == "https://www.youtube.com"

def test_youtube_search(parser):
    res = parser.parse("search youtube for lo fi music")
    assert res.intent == Intent.BROWSER
    assert res.slots.get("engine") == "youtube"
    assert res.slots.get("query") == "lo fi music"

def test_file_op(parser):
    res = parser.parse("create a file called test.txt")
    assert res.intent == Intent.FILE_OP
    assert res.slots.get("operation") == "create"
    assert res.slots.get("name") == "test.txt"

def test_conversation_fallback(parser):
    res = parser.parse("hello there how are you")
    assert res.intent == Intent.CONVERSATION
