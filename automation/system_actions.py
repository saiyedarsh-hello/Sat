"""
automation/system_actions.py
Volume, brightness, screenshot, lock screen, sleep, shutdown, restart.
Uses win32api / ctypes / subprocess for reliable Windows control.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

_SCREENSHOTS_DIR = Path.home() / "Pictures" / "Saturday Screenshots"


class SystemActions:
    """Windows system-level controls."""

    def handle(self, action: str, raw: str) -> str:
        """Dispatch from agent intent slots."""
        a = action.lower().strip()

        if "volume up" in a:
            return self.volume_up()
        if "volume down" in a:
            return self.volume_down()
        if "mute" in a and "unmute" not in a:
            return self.mute()
        if "unmute" in a:
            return self.unmute()
        if "screenshot" in a:
            return self.screenshot()
        if "lock" in a:
            return self.lock()
        if "sleep" in a:
            return self.sleep()
        if "shutdown" in a:
            return self.shutdown()
        if "restart" in a:
            return self.restart()
        if "brightness up" in a:
            return self.brightness_up()
        if "brightness down" in a:
            return self.brightness_down()
        if any(w in a for w in ("play", "pause", "resume", "toggle")):
            return self.media_play_pause()
        if any(w in a for w in ("next", "skip")):
            return self.media_next()
        if any(w in a for w in ("previous", "prev", "back")):
            return self.media_prev()
        if "stop" in a:
            return self.media_stop()

        # Try to extract a percentage
        pct_m = re.search(r"volume\s+(?:to\s+)?(\d{1,3})%?", raw, re.I)
        if pct_m:
            return self.set_volume(int(pct_m.group(1)))

        return f"I don't recognise the system action: {raw}"

    # ── Media playback ────────────────────────────────────────────────────────

    def media_play_pause(self) -> str:
        self._send_key(0xB3)  # VK_MEDIA_PLAY_PAUSE
        return "Toggled media playback."

    def media_next(self) -> str:
        self._send_key(0xB0)  # VK_MEDIA_NEXT_TRACK
        return "Skipped to next track."

    def media_prev(self) -> str:
        self._send_key(0xB1)  # VK_MEDIA_PREV_TRACK
        return "Skipped to previous track."

    def media_stop(self) -> str:
        self._send_key(0xB2)  # VK_MEDIA_STOP
        return "Media playback stopped."

    # ── Volume ────────────────────────────────────────────────────────────────


    def volume_up(self, step: int = 10) -> str:
        self._send_key(0xAF)  # VK_VOLUME_UP
        return "Volume increased."

    def volume_down(self, step: int = 10) -> str:
        self._send_key(0xAE)  # VK_VOLUME_DOWN
        return "Volume decreased."

    def mute(self) -> str:
        self._send_key(0xAD)  # VK_VOLUME_MUTE
        return "Audio muted."

    def unmute(self) -> str:
        self._send_key(0xAD)
        return "Audio unmuted."

    def set_volume(self, level: int) -> str:
        """Set volume to an absolute percentage using nircmd if available."""
        level = max(0, min(100, level))
        try:
            subprocess.run(
                ["nircmd", "setsysvolume", str(int(level / 100 * 65535))],
                check=True, capture_output=True,
            )
        except (FileNotFoundError, subprocess.CalledProcessError):
            # Fallback: press keys
            self._send_key(0xAD)  # Mute
            self._send_key(0xAD)  # Unmute
            for _ in range(level // 2):
                self._send_key(0xAF)
        return f"Volume set to {level}%."

    # ── Screenshot ────────────────────────────────────────────────────────────

    def screenshot(self) -> str:
        _SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = _SCREENSHOTS_DIR / f"saturday_{ts}.png"
        try:
            import PIL.ImageGrab as ImageGrab
            img = ImageGrab.grab()
            img.save(str(path))
            log.info("Screenshot saved: %s", path)
            return f"Screenshot saved to Pictures\\Saturday Screenshots\\{path.name}."
        except Exception:
            pass

        # Fallback: PrintScreen key (VK_SNAPSHOT)
        try:
            self._send_key(0x2C)  # VK_SNAPSHOT
            time.sleep(0.3)
            ps_cmd = (
                f"Add-Type -AssemblyName System.Windows.Forms;"
                f"$img = [System.Windows.Forms.Clipboard]::GetImage();"
                f"if ($img) {{ $img.Save('{str(path).replace('\\', '\\\\')}') }}"
            )
            subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd], capture_output=True)
            return f"Screenshot taken."
        except Exception as exc:
            return f"Screenshot failed: {exc}"


    # ── Lock / Sleep / Shutdown / Restart ─────────────────────────────────────

    def lock(self) -> str:
        try:
            import ctypes
            ctypes.windll.user32.LockWorkStation()
            return "Screen locked."
        except Exception as exc:
            return f"Lock failed: {exc}"

    def sleep(self) -> str:
        try:
            subprocess.run(
                ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"],
                check=True,
            )
            return "Going to sleep."
        except Exception as exc:
            return f"Sleep failed: {exc}"

    def shutdown(self) -> str:
        try:
            subprocess.run(["shutdown", "/s", "/t", "30"], check=True)
            return "Shutting down in 30 seconds. Say 'cancel shutdown' to abort."
        except Exception as exc:
            return f"Shutdown failed: {exc}"

    def cancel_shutdown(self) -> str:
        subprocess.run(["shutdown", "/a"], capture_output=True)
        return "Shutdown cancelled."

    def restart(self) -> str:
        try:
            subprocess.run(["shutdown", "/r", "/t", "30"], check=True)
            return "Restarting in 30 seconds."
        except Exception as exc:
            return f"Restart failed: {exc}"

    # ── Brightness ────────────────────────────────────────────────────────────

    def brightness_up(self) -> str:
        return self._adjust_brightness(+20)

    def brightness_down(self) -> str:
        return self._adjust_brightness(-20)

    def _adjust_brightness(self, delta: int) -> str:
        try:
            import wmi
            c = wmi.WMI(namespace="wmi")
            methods = c.WmiMonitorBrightnessMethods()[0]
            monitors = c.WmiMonitorBrightness()
            current = monitors[0].CurrentBrightness if monitors else 50
            new_val = max(0, min(100, current + delta))
            methods.WmiSetBrightness(new_val, 0)
            return f"Brightness set to {new_val}%."
        except Exception:
            return "Brightness control not available on this display."

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _send_key(vk_code: int) -> None:
        try:
            import ctypes
            KEYEVENTF_KEYUP = 0x0002
            ctypes.windll.user32.keybd_event(vk_code, 0, 0, 0)
            ctypes.windll.user32.keybd_event(vk_code, 0, KEYEVENTF_KEYUP, 0)
        except Exception as exc:
            log.error("keybd_event failed: %s", exc)
