"""
automation/browser_control.py
Open URLs and perform web searches with browser-choice support.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import webbrowser
from pathlib import Path

from config import config

log = logging.getLogger(__name__)

_SEARCH_ENGINES = {
    "google":        "https://www.google.com/search?q=",
    "bing":          "https://www.bing.com/search?q=",
    "duckduckgo":    "https://duckduckgo.com/?q=",
    "youtube":       "https://www.youtube.com/results?search_query=",
    "github":        "https://github.com/search?q=",
    "reddit":        "https://www.reddit.com/search/?q=",
    "amazon":        "https://www.amazon.com/s?k=",
    "wikipedia":     "https://en.wikipedia.org/wiki/Special:Search?search=",
    "stackoverflow": "https://stackoverflow.com/search?q=",
    "twitter":       "https://x.com/search?q=",
    "x":             "https://x.com/search?q=",
    "spotify":       "https://open.spotify.com/search/",
    "netflix":       "https://www.netflix.com/search?q=",
    "imdb":          "https://www.imdb.com/find?q=",
    "ebay":          "https://www.ebay.com/sch/i.html?_nkw=",
}


# Standard installation paths for Windows browsers
_COMMON_BROWSER_PATHS: dict[str, list[str]] = {
    "chrome": [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ],
    "edge": [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ],
    "firefox": [
        r"C:\Program Files\Mozilla Firefox\firefox.exe",
        r"C:\Program Files (x86)\Mozilla Firefox\firefox.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Mozilla Firefox\firefox.exe"),
    ],
    "brave": [
        r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\Application\brave.exe"),
    ],
    "opera": [
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Opera\opera.exe"),
        r"C:\Program Files\Opera\opera.exe",
    ],
}

BROWSER_DISPLAY_NAMES = {
    "chrome":  "Google Chrome",
    "edge":    "Microsoft Edge",
    "firefox": "Mozilla Firefox",
    "brave":   "Brave",
    "opera":   "Opera",
}


def _find_browser_exe(key: str) -> str | None:
    """Find executable for a browser key by checking PATH and standard install directories."""
    clean_key = key.lower().strip()
    for k in _COMMON_BROWSER_PATHS:
        if k in clean_key:
            clean_key = k
            break

    # 1. Check known absolute paths
    for path_str in _COMMON_BROWSER_PATHS.get(clean_key, []):
        if os.path.exists(path_str):
            return path_str

    # 2. Check PATH
    exe_name = f"{clean_key}.exe" if not clean_key.endswith(".exe") else clean_key
    found = shutil.which(exe_name)
    if found:
        return found
    if clean_key == "edge":
        return shutil.which("msedge.exe")
    return None


def _installed_browsers() -> list[str]:
    """Return list of short browser keys that are installed on this PC."""
    installed = []
    for key in ("chrome", "edge", "firefox", "brave", "opera"):
        if _find_browser_exe(key):
            installed.append(key)
    return installed


class BrowserControl:
    """Open URLs and launch web searches with optional browser selection."""

    def __init__(self, default_engine: str = "google") -> None:
        self._engine = default_engine.lower()

    # ── Browser choice helpers ────────────────────────────────────────────────

    def preferred_browser(self) -> str:
        """Return the user's preferred browser key (empty = unconfigured)."""
        return (config.get("preferred_browser", default="") or "").lower().strip()

    def browser_choice_prompt(self) -> str:
        """Return a question string asking which installed browser the user wants."""
        installed = _installed_browsers()
        if not installed:
            # Fallback to general list
            installed = ["chrome", "edge", "firefox"]

        names = [BROWSER_DISPLAY_NAMES.get(k, k.title()) for k in installed]
        if len(names) == 1:
            return f"Would you like to open it in {names[0]}?"
        options = ", ".join(names[:-1]) + f", or {names[-1]}"
        return f"Which browser would you like me to open it in — {options}?"

    def set_preferred_browser(self, name: str) -> None:
        """Persist the user's browser choice to config."""
        key = name.lower().strip()
        for k in ("chrome", "edge", "firefox", "brave", "opera"):
            if k in key:
                key = k
                break
        config.set("preferred_browser", key)
        log.info("Preferred browser configured as: %s", key)

    # ── Open URL ─────────────────────────────────────────────────────────────

    def open_url(self, url: str) -> bool:
        """Open URL using preferred browser if set, otherwise system default."""
        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        pref = self.preferred_browser()
        if pref:
            return self.open_url_in(pref, url, allow_fallback=True)

        return self._open_system_default(url)

    def open_url_in(self, browser_key: str, url: str, allow_fallback: bool = True) -> bool:
        """Open URL in a specific named browser executable."""
        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        exe_path = _find_browser_exe(browser_key)
        if exe_path:
            try:
                subprocess.Popen([exe_path, url])
                log.info("Launched %s in %s (%s)", url, browser_key, exe_path)
                return True
            except Exception as exc:
                log.error("Failed to launch %s via %s: %s", browser_key, exe_path, exc)

        if allow_fallback:
            log.warning("Browser '%s' not found locally — using system default browser", browser_key)
            return self._open_system_default(url)

        return False

    def _open_system_default(self, url: str) -> bool:
        """Directly open system default browser (never recurses)."""
        try:
            webbrowser.open(url)
            log.info("Opened URL in system default browser: %s", url)
            return True
        except Exception as exc:
            log.error("Default browser open failed: %s", exc)
            return False

    # ── Search ───────────────────────────────────────────────────────────────

    def search(self, query: str, engine: str | None = None) -> bool:
        """Search the web or a specific site for `query`."""
        clean_q = query.strip()
        eng = (engine or self._engine).lower().strip()

        # 1. Known search engine or site
        if eng in _SEARCH_ENGINES:
            base = _SEARCH_ENGINES[eng]
            url = base + clean_q.replace(" ", "+")
            log.info("Searching %s for %r: %s", eng, clean_q, url)
            return self.open_url(url)

        # 2. Dynamic site search (e.g. nike -> site:nike.com <query>)
        if eng:
            domain = eng if "." in eng else f"{eng.replace(' ', '')}.com"
            url = f"https://www.google.com/search?q=site%3A{domain}+{clean_q.replace(' ', '+')}"
            log.info("Searching site %s for %r: %s", domain, clean_q, url)
            return self.open_url(url)

        base = _SEARCH_ENGINES["google"]
        url = base + clean_q.replace(" ", "+")
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
