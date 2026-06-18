"""
automation/browser_control.py
Open URLs and perform web searches using the default browser.
"""

from __future__ import annotations

import logging
import subprocess
import webbrowser

log = logging.getLogger(__name__)

_SEARCH_ENGINES = {
    "google":    "https://www.google.com/search?q=",
    "bing":      "https://www.bing.com/search?q=",
    "duckduckgo":"https://duckduckgo.com/?q=",
    "youtube":   "https://www.youtube.com/results?search_query=",
}


class BrowserControl:
    """Open URLs and launch web searches."""

    def __init__(self, default_engine: str = "google") -> None:
        self._engine = default_engine.lower()

    def open_url(self, url: str) -> bool:
        """Open a URL in the default browser."""
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        try:
            webbrowser.open(url)
            log.info("Opened URL: %s", url)
            return True
        except Exception as exc:
            log.error("open_url failed: %s", exc)
            return False

    def search(self, query: str, engine: str | None = None) -> bool:
        """Search the web for `query` using the specified (or default) engine."""
        eng = (engine or self._engine).lower()
        base = _SEARCH_ENGINES.get(eng, _SEARCH_ENGINES["google"])
        encoded = query.replace(" ", "+")
        url = base + encoded
        return self.open_url(url)

    def search_youtube(self, query: str) -> bool:
        return self.search(query, engine="youtube")

    def open_new_tab(self, url: str) -> bool:
        """Open URL in a new browser tab."""
        try:
            webbrowser.open_new_tab(url)
            return True
        except Exception:
            return self.open_url(url)
