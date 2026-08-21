"""
automation/resolver.py
Smart app vs. website vs. system-setting vs. system-tool vs. special-folder resolution layer.

Priority order:
  0. Special Windows Settings (Mouse, Display, Sound, Bluetooth, Wi-Fi, Updates, etc. via ms-settings:)
  1. Windows System Tools & Applets (Task Manager, Device Manager, Disk Management, Control Panel, etc.)
  2. Special Windows Folders (Documents, Downloads, Desktop, Pictures, Videos, Music)
  3. Memory-backed preference (if user has answered this before, use that)
  4. Explicit cue words in utterance/captured name ("website", "desktop app", etc.)
  5. Known-ambiguous registry → ask the user (clarify)
  6. Unambiguous single-registry match (_APP_MAP or SITE_NAMES)
  7. Dynamic Windows Start Menu lookup (catches anything not hardcoded)
  8. Unknown word + "website" cue → safe guess at https://<clean_name>.com
  9. Truly unresolved → ask user & log the gap
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# ── Cue / filler words that should never pollute the actual entity name ────────
_TRAILING_CUES = {"website", "site", "app", "program", "application",
                  "desktop", "folder", "section", "page", "window", "tab"}
_LEADING_FILLER = {"the", "a", "an", "my", "our", "this"}

# ── Site / App cue words for utterance routing ────────────────────────────────
_SITE_CUES = {"website", "site", ".com", ".net", ".org", ".io",
              "in the browser", "online", "on the web", "in browser", "web app"}
_APP_CUES  = {"app", "program", "application", "desktop", "native",
              "installed", "installed app"}
_FOLDER_CUES = {"folder", "section", "directory"}


def clean_entity_name(raw: str) -> tuple[str, list[str]]:
    """
    Strips filler/cue words from a captured entity name and returns (clean_name, cues_found).
    
    Examples:
      "nike website"           -> ("nike", ["website"])
      "the documents section"  -> ("documents", ["section"])
      "my downloads folder"    -> ("downloads", ["folder"])
      "spotify app"            -> ("spotify", ["app"])
      "brave"                  -> ("brave", [])
    """
    words = raw.strip().split()
    cues_found = []

    # Strip trailing cue words (can be more than one, e.g. "nike website page")
    while words and words[-1].lower() in _TRAILING_CUES:
        cues_found.append(words.pop().lower())

    # Strip leading filler words
    while words and words[0].lower() in _LEADING_FILLER:
        words.pop(0)

    clean_name = " ".join(words).lower().strip()
    return clean_name, cues_found


# ── Windows Settings Sub-pages Map (ms-settings:) ─────────────────────────────
_SETTINGS_MAP: dict[str, str] = {
    # Devices & Peripherals
    "mouse":                      "ms-settings:mousetouchpad",
    "touchpad":                   "ms-settings:devices-touchpad",
    "keyboard":                   "ms-settings:keyboard",
    "bluetooth":                  "ms-settings:bluetooth",
    "printers":                   "ms-settings:printers",
    "printer":                    "ms-settings:printers",
    "scanners":                   "ms-settings:printers",
    "usb":                        "ms-settings:usb",
    "sound":                      "ms-settings:sound",
    "audio":                      "ms-settings:sound",
    "volume":                     "ms-settings:sound",
    "mic":                        "ms-settings:privacy-microphone",
    "microphone":                 "ms-settings:privacy-microphone",
    "camera":                     "ms-settings:privacy-webcam",
    "webcam":                     "ms-settings:privacy-webcam",

    # Display & Personalization
    "display":                    "ms-settings:display",
    "screen":                     "ms-settings:display",
    "resolution":                 "ms-settings:display",
    "graphics":                   "ms-settings:display-advancedgraphics",
    "night light":                "ms-settings:nightlight",
    "personalization":            "ms-settings:personalization-background",
    "background":                 "ms-settings:personalization-background",
    "wallpaper":                  "ms-settings:personalization-background",
    "lock screen":                "ms-settings:lockscreen",
    "colors":                     "ms-settings:colors",
    "color":                      "ms-settings:colors",
    "dark mode":                  "ms-settings:colors",
    "light mode":                 "ms-settings:colors",
    "themes":                     "ms-settings:themes",
    "fonts":                      "ms-settings:fonts",
    "taskbar":                    "ms-settings:taskbar",
    "start menu":                 "ms-settings:personalization-start",

    # Network & Internet
    "network":                    "ms-settings:network",
    "internet":                   "ms-settings:network",
    "wifi":                       "ms-settings:network-wifi",
    "wi-fi":                      "ms-settings:network-wifi",
    "ethernet":                   "ms-settings:network-ethernet",
    "vpn":                        "ms-settings:network-vpn",
    "hotspot":                    "ms-settings:network-mobilehotspot",
    "mobile hotspot":             "ms-settings:network-mobilehotspot",
    "airplane mode":              "ms-settings:network-airplanemode",
    "flight mode":                "ms-settings:network-airplanemode",
    "proxy":                      "ms-settings:network-proxy",
    "data usage":                 "ms-settings:datausage",

    # System & Power
    "power":                      "ms-settings:powersleep",
    "sleep":                      "ms-settings:powersleep",
    "battery":                    "ms-settings:batterysaver",
    "battery saver":              "ms-settings:batterysaver",
    "storage":                    "ms-settings:storagesense",
    "notifications":              "ms-settings:notifications",
    "notification":               "ms-settings:notifications",
    "focus assist":               "ms-settings:quiethours",
    "do not disturb":             "ms-settings:quiethours",
    "multitasking":               "ms-settings:multitasking",
    "project":                    "ms-settings:project",
    "projection":                 "ms-settings:project",
    "clipboard":                  "ms-settings:clipboard",
    "about":                      "ms-settings:about",
    "system info":                "ms-settings:about",
    "specs":                      "ms-settings:about",

    # Apps
    "apps":                       "ms-settings:appsfeatures",
    "installed apps":             "ms-settings:appsfeatures",
    "apps and features":          "ms-settings:appsfeatures",
    "default apps":               "ms-settings:defaultapps",
    "startup apps":               "ms-settings:startupapps",
    "startup":                    "ms-settings:startupapps",

    # Update & Security
    "windows update":             "ms-settings:windowsupdate",
    "update":                     "ms-settings:windowsupdate",
    "updates":                    "ms-settings:windowsupdate",
    "security":                   "ms-settings:windowsdefender",
    "windows security":           "ms-settings:windowsdefender",
    "defender":                   "ms-settings:windowsdefender",
    "antivirus":                  "ms-settings:windowsdefender",
    "firewall":                   "ms-settings:windowsdefender",
    "recovery":                   "ms-settings:recovery",
    "backup":                     "ms-settings:backup",
    "troubleshoot":               "ms-settings:troubleshoot",
    "location":                   "ms-settings:privacy-location",

    # Time & Language
    "date and time":              "ms-settings:dateandtime",
    "date":                       "ms-settings:dateandtime",
    "time":                       "ms-settings:dateandtime",
    "language":                   "ms-settings:regionlanguage",
    "region":                     "ms-settings:regionlanguage",
    "typing":                     "ms-settings:typing",
    "speech":                     "ms-settings:speech",

    # Gaming
    "game bar":                   "ms-settings:gaming-gamebar",
    "gaming":                     "ms-settings:gaming-gamebar",
    "game mode":                  "ms-settings:gaming-gamemode",

    # Accounts & Accessibility
    "accounts":                   "ms-settings:yourinfo",
    "account":                    "ms-settings:yourinfo",
    "sign in":                    "ms-settings:signinoptions",
    "sign in options":            "ms-settings:signinoptions",
    "accessibility":              "ms-settings:easeofaccess-display",
    "ease of access":             "ms-settings:easeofaccess-display",
    "magnifier":                  "ms-settings:easeofaccess-magnifier",
}

# ── Windows System Administration Tools & Applets ─────────────────────────────
_SYSTEM_TOOLS_MAP: dict[str, tuple[str, str]] = {
    "task manager":               ("taskmgr.exe", "Task Manager"),
    "device manager":             ("devmgmt.msc", "Device Manager"),
    "disk management":            ("diskmgmt.msc", "Disk Management"),
    "computer management":        ("compmgmt.msc", "Computer Management"),
    "services":                   ("services.msc", "Services"),
    "event viewer":               ("eventvwr.msc", "Event Viewer"),
    "resource monitor":           ("resmon.exe", "Resource Monitor"),
    "performance monitor":        ("perfmon.msc", "Performance Monitor"),
    "registry editor":            ("regedit.exe", "Registry Editor"),
    "regedit":                    ("regedit.exe", "Registry Editor"),
    "system configuration":       ("msconfig.exe", "System Configuration"),
    "msconfig":                   ("msconfig.exe", "System Configuration"),
    "system information":         ("msinfo32.exe", "System Information"),
    "msinfo32":                   ("msinfo32.exe", "System Information"),
    "directx":                    ("dxdiag.exe", "DirectX Diagnostic Tool"),
    "dxdiag":                     ("dxdiag.exe", "DirectX Diagnostic Tool"),
    "control panel":              ("control.exe", "Control Panel"),
    "network connections":        ("ncpa.cpl", "Network Connections"),
    "sound control panel":        ("mmsys.cpl", "Sound Properties"),
    "system properties":          ("sysdm.cpl", "System Properties"),
    "power options":              ("powercfg.cpl", "Power Options"),
    "programs and features":      ("appwiz.cpl", "Programs and Features"),
    "date and time properties":   ("timedate.cpl", "Date and Time Properties"),
    "mouse properties":           ("main.cpl", "Mouse Properties"),
    "game controllers":           ("joy.cpl", "Game Controllers"),
    "internet options":           ("inetcpl.cpl", "Internet Options"),
}


def resolve_setting(name: str, utterance: str) -> dict | None:
    """
    Resolve any Windows Settings sub-page query into an exact ms-settings: URI.
    Handles 'mouse settings', 'open sound settings', 'display preferences', 'wifi options', etc.
    """
    clean = name.lower().strip()
    utt = utterance.lower().strip()

    # If asking for general settings
    if clean in ("settings", "windows settings", "pc settings") or utt in ("open settings", "launch settings"):
        return {"type": "setting", "target": "ms-settings:", "label": "Windows Settings"}

    # Extract topic by stripping keyword suffixes
    topic = re.sub(r"\b(?:settings|options|preferences|properties|config|configuration|panel)\b", "", clean).strip()
    topic = re.sub(r"^(?:the|my|a|an)\s+", "", topic).strip()

    # 1. Exact match on topic
    if topic in _SETTINGS_MAP:
        return {"type": "setting", "target": _SETTINGS_MAP[topic], "label": f"{topic.title()} Settings"}

    # 2. Exact match on clean name
    if clean in _SETTINGS_MAP:
        return {"type": "setting", "target": _SETTINGS_MAP[clean], "label": f"{clean.title()} Settings"}

    # 3. Substring match against known settings
    if topic:
        for k, uri in _SETTINGS_MAP.items():
            if topic == k or topic in k or k in topic:
                return {"type": "setting", "target": uri, "label": f"{k.title()} Settings"}

    # 4. If utterance specifically asked for settings/options, try dynamic URI
    if any(w in utt for w in ("settings", "preferences", "options")) and topic:
        clean_topic = topic.replace(" ", "")
        return {"type": "setting", "target": f"ms-settings:{clean_topic}", "label": f"{topic.title()} Settings"}

    return None


def open_setting(uri: str) -> bool:
    """Open a Windows Settings URI natively."""
    try:
        os.startfile(uri)
        log.info("Opened Windows Setting: %s", uri)
        return True
    except Exception as exc:
        try:
            subprocess.Popen(["explorer.exe", uri])
            log.info("Opened Windows Setting via explorer: %s", uri)
            return True
        except Exception as exc2:
            log.error("Failed to open setting %s: %s / %s", uri, exc, exc2)
            return False


def open_system_tool(cmd: str) -> bool:
    """Launch a Windows system management tool or applet."""
    try:
        os.startfile(cmd)
        log.info("Opened Windows System Tool: %s", cmd)
        return True
    except Exception as exc:
        try:
            subprocess.Popen([cmd], shell=True)
            log.info("Opened Windows System Tool via shell: %s", cmd)
            return True
        except Exception as exc2:
            log.error("Failed to open system tool %s: %s / %s", cmd, exc, exc2)
            return False


# ── Special Windows Folders ───────────────────────────────────────────────────
_FOLDER_MAP: dict[str, str] = {
    "documents": "shell:Personal",
    "downloads": "shell:Downloads",
    "desktop":   "shell:Desktop",
    "pictures":  "shell:My Pictures",
    "videos":    "shell:My Video",
    "music":     "shell:My Music",
}


def open_folder(folder_key: str) -> bool:
    """Open a special Windows folder in File Explorer."""
    try:
        key = folder_key.lower().strip()
        target = _FOLDER_MAP.get(key, f"shell:{key}")
        subprocess.Popen(["explorer.exe", target])
        log.info("Opened folder: %s (%s)", folder_key, target)
        return True
    except Exception as exc:
        log.error("open_folder failed for %s: %s", folder_key, exc)
        return False


# ── Things that exist as BOTH an app and a website ───────────────────────────
_AMBIGUOUS: dict[str, dict] = {
    "claude":       {"app": None,               "site": "https://claude.ai"},
    "chatgpt":      {"app": None,               "site": "https://chatgpt.com"},
    "spotify":      {"app": "spotify.exe",      "site": "https://open.spotify.com"},
    "whatsapp":     {"app": "WhatsApp.exe",     "site": "https://web.whatsapp.com"},
    "discord":      {"app": "Discord.exe",      "site": "https://discord.com/app"},
    "slack":        {"app": "slack.exe",        "site": "https://slack.com"},
    "telegram":     {"app": "Telegram.exe",     "site": "https://web.telegram.org"},
    "notion":       {"app": "notion.exe",       "site": "https://notion.so"},
    "figma":        {"app": "figma.exe",        "site": "https://figma.com"},
    "linear":       {"app": None,               "site": "https://linear.app"},
    "gmail":        {"app": None,               "site": "https://mail.google.com"},
    "google drive": {"app": None,               "site": "https://drive.google.com"},
    "google docs":  {"app": None,               "site": "https://docs.google.com"},
    "reddit":       {"app": None,               "site": "https://www.reddit.com"},
    "netflix":      {"app": "Netflix.exe",      "site": "https://www.netflix.com"},
    "youtube":      {"app": None,               "site": "https://www.youtube.com"},
    "instagram":    {"app": None,               "site": "https://www.instagram.com"},
    "twitter":      {"app": None,               "site": "https://twitter.com"},
    "x":            {"app": None,               "site": "https://x.com"},
    "facebook":     {"app": None,               "site": "https://www.facebook.com"},
    "github":       {"app": None,               "site": "https://github.com"},
    "linkedin":     {"app": None,               "site": "https://www.linkedin.com"},
}

# ── Unresolved targets log ────────────────────────────────────────────────────
_UNRESOLVED_LOG = Path("logs") / "unresolved_targets.log"


# ── Public API ────────────────────────────────────────────────────────────────

def resolve_target(
    name: str,
    utterance: str,
    app_map: dict[str, str],
    site_names: dict[str, str],
) -> dict:
    """
    Determine how to open `name` based on the full `utterance`.

    Returns exactly one of:
      {"type": "setting",     "target": "<ms-settings:...>", "label": "..."}
      {"type": "system_tool", "target": "<cmd or .msc>",     "label": "..."}
      {"type": "folder",      "target": "<folder_key>"}
      {"type": "app",         "target": "<exe or command>"}
      {"type": "site",        "target": "<url>"}
      {"type": "clarify",     "question": "...", "options": {"app": ..., "site": ...}}
      {"type": "unresolved",  "name": name}
    """
    clean_name, embedded_cues = clean_entity_name(name)
    all_cues = set(embedded_cues)
    key = clean_name or name.lower().strip()
    utterance_lower = utterance.lower()

    # ── Step 0: Windows Settings sub-pages check (e.g. "mouse settings", "sound settings")
    setting_res = resolve_setting(name, utterance)
    if setting_res:
        return setting_res

    # ── Step 1: Windows System Tools & Admin Applets (e.g. "device manager", "task manager")
    if key in _SYSTEM_TOOLS_MAP:
        cmd, label = _SYSTEM_TOOLS_MAP[key]
        return {"type": "system_tool", "target": cmd, "label": label}
    if name.lower().strip() in _SYSTEM_TOOLS_MAP:
        cmd, label = _SYSTEM_TOOLS_MAP[name.lower().strip()]
        return {"type": "system_tool", "target": cmd, "label": label}

    # ── Step 2: Special folder check (e.g. "documents", "downloads", "desktop")
    if key in _FOLDER_MAP or any(c in all_cues for c in _FOLDER_CUES):
        if key in _FOLDER_MAP:
            return {"type": "folder", "target": key}

    # ── Step 3: Explicit cue words (embedded in name OR elsewhere in utterance)
    site_cue = "website" in all_cues or "site" in all_cues or any(cue in utterance_lower for cue in _SITE_CUES)
    app_cue  = "app" in all_cues or "program" in all_cues or "application" in all_cues or any(cue in utterance_lower for cue in _APP_CUES)

    if site_cue:
        if key in site_names:
            return {"type": "site", "target": site_names[key]}
        if key in _AMBIGUOUS and _AMBIGUOUS[key].get("site"):
            return {"type": "site", "target": _AMBIGUOUS[key]["site"]}
        guessed = f"https://{key.replace(' ', '')}.com"
        log.info("Resolver: unknown site '%s' — guessing %s", key, guessed)
        return {"type": "site", "target": guessed}

    if app_cue:
        if key in app_map:
            return {"type": "app", "target": app_map[key]}
        if key in _AMBIGUOUS and _AMBIGUOUS[key].get("app"):
            return {"type": "app", "target": _AMBIGUOUS[key]["app"]}

    # ── Step 4: Known-ambiguous check
    if key in _AMBIGUOUS:
        entry = _AMBIGUOUS[key]
        app_target  = entry.get("app")
        site_target = entry.get("site")

        if app_target and not site_target:
            return {"type": "app", "target": app_target}
        if site_target and not app_target:
            return {"type": "site", "target": site_target}

        return {
            "type":     "clarify",
            "question": f"Do you want the {key.title()} desktop app or the website?",
            "options":  {"app": app_target, "site": site_target},
        }

    # ── Step 5: Unambiguous single-registry match
    if key in app_map:
        return {"type": "app", "target": app_map[key]}
    if key in site_names:
        return {"type": "site", "target": site_names[key]}

    # ── Step 6: Dynamic Windows Start Menu lookup
    dynamic = _check_installed_apps(key)
    if dynamic:
        log.info("Resolver: dynamic match for '%s' → AppID=%s", key, dynamic)
        return {"type": "app", "target": dynamic, "launch_via": "shell"}

    # ── Step 7: Truly unresolved
    _log_unresolved(key, utterance)
    return {"type": "unresolved", "name": key}


def _check_installed_apps(name: str) -> Optional[str]:
    """
    Query the Windows Start Menu app registry via PowerShell.
    Slower (~200-500ms), only used as a fallback after static maps miss.
    Returns the AppID string if found, else None.
    """
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-StartApps | Select-Object Name, AppID | ConvertTo-Json -Compress"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return None

        apps = json.loads(result.stdout)
        if isinstance(apps, dict):
            apps = [apps]

        name_lower = name.lower()
        for app in apps:
            app_name = (app.get("Name") or "").lower()
            if name_lower in app_name or app_name in name_lower:
                return app.get("AppID")

    except (subprocess.TimeoutExpired, json.JSONDecodeError, Exception) as exc:
        log.debug("Dynamic app lookup failed: %s", exc)
    return None


def launch_app_id(app_id: str) -> bool:
    """Launch a Windows Store / registered app by its AppID."""
    try:
        subprocess.Popen(
            ["explorer.exe", f"shell:AppsFolder\\{app_id}"]
        )
        log.info("Launched AppID: %s", app_id)
        return True
    except Exception as exc:
        log.error("launch_app_id failed for %s: %s", app_id, exc)
        return False


def _log_unresolved(name: str, utterance: str) -> None:
    """Log every resolution miss so you can see real coverage gaps over time."""
    try:
        _UNRESOLVED_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(_UNRESOLVED_LOG, "a", encoding="utf-8") as f:
            f.write(f"{name} | {utterance}\n")
    except Exception:
        pass
