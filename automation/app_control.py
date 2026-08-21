"""
automation/app_control.py
Open, close, and focus Windows applications.

Smart open logic:
  1. Check _APP_MAP for known executable
  2. Scan common install locations (Program Files, AppData, MS Store)
  3. If not found as a native app, return False so the caller can fall back
     to the website version.
"""

from __future__ import annotations

import logging
import os
import subprocess
import shutil
from pathlib import Path

log = logging.getLogger(__name__)

# ── Known-app → executable map ────────────────────────────────────────────────
_APP_MAP: dict[str, str] = {
    "notepad":              "notepad.exe",
    "calculator":           "calc.exe",
    "explorer":             "explorer.exe",
    "file explorer":        "explorer.exe",
    "paint":                "mspaint.exe",
    "word":                 "winword.exe",
    "excel":                "excel.exe",
    "powerpoint":           "powerpnt.exe",
    # ── Browsers ───────────────────────────────────────────────────────────────
    "chrome":               "chrome.exe",
    "google chrome":        "chrome.exe",
    "firefox":              "firefox.exe",
    "mozilla firefox":      "firefox.exe",
    "edge":                 "msedge.exe",
    "microsoft edge":       "msedge.exe",
    "brave":                "brave.exe",
    "brave browser":        "brave.exe",
    "opera":                "opera.exe",
    "opera gx":             "opera.exe",
    "vivaldi":              "vivaldi.exe",
    # ── System tools ───────────────────────────────────────────────────────────
    "cmd":                  "cmd.exe",
    "command prompt":       "cmd.exe",
    "powershell":           "powershell.exe",
    "terminal":             "wt.exe",
    "windows terminal":     "wt.exe",
    "task manager":         "taskmgr.exe",
    "control panel":        "control.exe",
    "settings":             "ms-settings:",
    "snipping tool":        "SnippingTool.exe",
    "registry editor":      "regedit.exe",
    "regedit":              "regedit.exe",
    # ── Dev tools ──────────────────────────────────────────────────────────────
    "vs code":              "code.exe",
    "vscode":               "code.exe",
    "visual studio code":   "code.exe",
    "visual studio":        "devenv.exe",
    "cursor":               "Cursor.exe",
    "sublime text":         "sublime_text.exe",
    "notepad++":            "notepad++.exe",
    # ── Media & apps ───────────────────────────────────────────────────────────
    "spotify":              "spotify.exe",
    "discord":              "Discord.exe",
    "slack":                "slack.exe",
    "teams":                "teams.exe",
    "microsoft teams":      "teams.exe",
    "zoom":                 "zoom.exe",
    "vlc":                  "vlc.exe",
    "steam":                "steam.exe",
    "epic games":           "EpicGamesLauncher.exe",
    "whatsapp":             "WhatsApp.exe",
    "telegram":             "Telegram.exe",
    "signal":               "Signal.exe",
    "obs":                  "obs64.exe",
    "obs studio":           "obs64.exe",
    "gimp":                 "gimp-2.10.exe",
    "blender":              "blender.exe",
    "figma":                "figma.exe",
    "postman":              "Postman.exe",
    "winrar":               "winrar.exe",
    "7zip":                 "7zFM.exe",
    "7-zip":                "7zFM.exe",
    "pdf":                  "AcroRd32.exe",
    "adobe reader":         "AcroRd32.exe",
    "acrobat":              "Acrobat.exe",
    "photoshop":            "Photoshop.exe",
    "premiere":             "Premiere Pro.exe",
    "after effects":        "AfterFX.exe",
}

# ── Common install roots to search ────────────────────────────────────────────
_SEARCH_ROOTS: list[Path] = [
    Path(os.environ.get("ProgramFiles",      r"C:\Program Files")),
    Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")),
    Path(os.environ.get("LOCALAPPDATA",      r"C:\Users\Default\AppData\Local")),
    Path(os.environ.get("APPDATA",           r"C:\Users\Default\AppData\Roaming")),
]

# MS Store / WindowsApps paths
_WINDOWS_APPS = Path(os.environ.get("ProgramFiles",
                                     r"C:\Program Files")) / "WindowsApps"

# ── Known browser exe paths (mirrors browser_control._COMMON_BROWSER_PATHS) ──
_BROWSER_EXE_PATHS: dict[str, list[str]] = {
    "brave.exe": [
        r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\Application\brave.exe"),
    ],
    "chrome.exe": [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ],
    "msedge.exe": [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ],
    "firefox.exe": [
        r"C:\Program Files\Mozilla Firefox\firefox.exe",
        r"C:\Program Files (x86)\Mozilla Firefox\firefox.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Mozilla Firefox\firefox.exe"),
    ],
    "opera.exe": [
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Opera\opera.exe"),
        r"C:\Program Files\Opera\opera.exe",
    ],
    "code.exe": [
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe"),
        r"C:\Program Files\Microsoft VS Code\Code.exe",
    ],
}

def _find_in_windowsapps(exe_name: str) -> str | None:
    """Search the WindowsApps directory for an executable (MS Store apps)."""
    if not _WINDOWS_APPS.exists():
        return None
    name_lower = exe_name.lower()
    try:
        for child in _WINDOWS_APPS.iterdir():
            if not child.is_dir():
                continue
            candidate = child / exe_name
            if candidate.exists():
                return str(candidate)
            # Case-insensitive fallback
            try:
                for f in child.iterdir():
                    if f.name.lower() == name_lower:
                        return str(f)
            except PermissionError:
                continue
    except PermissionError:
        pass
    return None


def _find_exe(exe_name: str) -> str | None:
    """
    Locate an executable on this machine.
    Order: known paths dict → PATH → Program Files roots → WindowsApps.
    Returns the full path string or None.
    """
    # 0. Check browser/app-specific known paths first (fastest)
    for path_str in _BROWSER_EXE_PATHS.get(exe_name.lower(), []):
        if os.path.exists(path_str):
            return path_str

    # 1. Already on PATH?
    found = shutil.which(exe_name)
    if found:
        return found

    # 2. Search common install roots (one level deep for speed)
    name_lower = exe_name.lower()
    for root in _SEARCH_ROOTS:
        if not root.exists():
            continue
        try:
            for child in root.iterdir():
                if not child.is_dir():
                    continue
                candidate = child / exe_name
                if candidate.exists():
                    return str(candidate)
                # Case-insensitive
                try:
                    for f in child.iterdir():
                        if f.name.lower() == name_lower:
                            return str(f)
                except (PermissionError, OSError):
                    continue
        except (PermissionError, OSError):
            continue

    # 3. WindowsApps (MS Store)
    return _find_in_windowsapps(exe_name)


class AppControl:
    """Open, close, and focus Windows applications."""

    def is_installed(self, app_name: str) -> bool:
        """Return True if the app appears to be installed as a native application."""
        key = app_name.lower().strip()
        exe = _APP_MAP.get(key)
        if exe and exe.endswith(":"):
            return True  # protocol URL — always treat as available
        if exe:
            return _find_exe(exe) is not None
        # Unknown app — check if the raw name or name.exe is on PATH / findable
        return (shutil.which(app_name) is not None
                or shutil.which(app_name + ".exe") is not None)

    def open_app(self, app_name: str) -> bool:
        """
        Open an application by name.
        Returns True if successfully launched, False if not found.
        """
        key = app_name.lower().strip()
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

        # Try to find the exe
        if executable:
            full_path = _find_exe(executable)
            if full_path:
                try:
                    subprocess.Popen([full_path])
                    log.info("Launched (found path): %s", full_path)
                    return True
                except Exception as exc:
                    log.warning("Popen failed for %s: %s", full_path, exc)

        # Shell fallback — try a quick Popen without shell=True using exe name directly
        for exe in filter(None, [executable if executable else None]):
            full = _find_exe(exe)
            if full:
                try:
                    subprocess.Popen([full])
                    log.info("Launched (fallback path): %s", full)
                    return True
                except Exception as exc:
                    log.warning("Fallback Popen failed for %s: %s", full, exc)

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
                capture_output=True, check=True,
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
                capture_output=True, text=True,
            )
            names = []
            for line in result.stdout.strip().splitlines():
                parts = line.strip('"').split('","')
                if parts:
                    names.append(parts[0])
            return names
        except Exception:
            return []
