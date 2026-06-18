"""
automation/app_control.py
Open, close, and focus Windows applications.
Uses subprocess for common apps and pywinauto for window management.
"""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)

# Common app name → executable map
_APP_MAP: dict[str, str] = {
    "notepad":          "notepad.exe",
    "calculator":       "calc.exe",
    "explorer":         "explorer.exe",
    "file explorer":    "explorer.exe",
    "paint":            "mspaint.exe",
    "word":             "winword.exe",
    "excel":            "excel.exe",
    "powerpoint":       "powerpnt.exe",
    "chrome":           "chrome.exe",
    "google chrome":    "chrome.exe",
    "firefox":          "firefox.exe",
    "edge":             "msedge.exe",
    "microsoft edge":   "msedge.exe",
    "cmd":              "cmd.exe",
    "command prompt":   "cmd.exe",
    "powershell":       "powershell.exe",
    "terminal":         "wt.exe",
    "windows terminal": "wt.exe",
    "task manager":     "taskmgr.exe",
    "control panel":    "control.exe",
    "settings":         "ms-settings:",
    "snipping tool":    "SnippingTool.exe",
    "vs code":          "code.exe",
    "vscode":           "code.exe",
    "visual studio code": "code.exe",
    "spotify":          "spotify.exe",
    "discord":          "discord.exe",
    "slack":            "slack.exe",
    "teams":            "teams.exe",
    "zoom":             "zoom.exe",
}


class AppControl:
    """Open, close, and focus Windows applications."""

    def open_app(self, app_name: str) -> bool:
        """
        Open an application by name.
        Returns True if successfully launched, False otherwise.
        """
        key = app_name.lower().strip()

        # Check known map
        executable = _APP_MAP.get(key, "")

        # Protocol URLs (ms-settings:, etc.)
        if executable.endswith(":"):
            try:
                os.startfile(executable)
                log.info("Opened protocol: %s", executable)
                return True
            except Exception as exc:
                log.error("Protocol open failed: %s", exc)
                return False

        # Try mapped executable first, then raw name
        for exe in filter(None, [executable, key if ".exe" in key else None, app_name]):
            try:
                subprocess.Popen(exe, shell=True)
                log.info("Launched: %s", exe)
                return True
            except Exception:
                continue

        log.warning("Could not open app: %s", app_name)
        return False

    def close_app(self, app_name: str) -> bool:
        """Terminate a process by name."""
        key = app_name.lower().strip()
        executable = _APP_MAP.get(key, key)
        if not executable.endswith(".exe"):
            executable += ".exe"
        try:
            subprocess.run(
                ["taskkill", "/F", "/IM", executable],
                capture_output=True,
                check=True,
            )
            log.info("Closed: %s", executable)
            return True
        except subprocess.CalledProcessError as exc:
            log.error("Close app failed: %s", exc)
            return False

    def focus_app(self, app_name: str) -> bool:
        """Bring an open application window to the foreground."""
        try:
            from pywinauto import Desktop
            windows = Desktop(backend="uia").windows()
            key = app_name.lower()
            for win in windows:
                try:
                    if key in win.window_text().lower():
                        win.set_focus()
                        return True
                except Exception:
                    continue
        except ImportError:
            log.debug("pywinauto not available — cannot focus window.")
        except Exception as exc:
            log.error("Focus app failed: %s", exc)
        return False

    def list_running(self) -> list[str]:
        """Return a list of running process names."""
        try:
            result = subprocess.run(
                ["tasklist", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
            )
            names = []
            for line in result.stdout.strip().splitlines():
                parts = line.strip('"').split('","')
                if parts:
                    names.append(parts[0])
            return names
        except Exception:
            return []
