"""
config/config_manager.py
Load, save and encrypt Saturday's configuration.
API keys are stored encrypted using Fernet symmetric encryption.
The encryption key is derived from the machine UUID and stored in the user
profile so it is machine-specific but requires no password.
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet
import base64
import hashlib

# ── Paths ─────────────────────────────────────────────────────────────────────
_APP_DATA = Path(os.getenv("APPDATA", Path.home())) / "Saturday"
_CONFIG_PATH = _APP_DATA / "config.json"
_KEY_PATH = _APP_DATA / ".key"
_DEFAULTS_PATH = Path(__file__).parent / "defaults.json"

_SENSITIVE_KEYS = {"api_key"}


def _app_data_dir() -> Path:
    _APP_DATA.mkdir(parents=True, exist_ok=True)
    return _APP_DATA


def _load_defaults() -> dict:
    with open(_DEFAULTS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


# ── Encryption helpers ────────────────────────────────────────────────────────

def _machine_key() -> bytes:
    """Derive a stable Fernet key from the machine's UUID."""
    machine_id = str(uuid.getnode()).encode()
    digest = hashlib.sha256(machine_id).digest()
    return base64.urlsafe_b64encode(digest)


def _fernet() -> Fernet:
    key_file = _KEY_PATH
    if key_file.exists():
        key = key_file.read_bytes()
    else:
        key = _machine_key()
        _app_data_dir()
        key_file.write_bytes(key)
    return Fernet(key)


def _encrypt_value(value: str) -> str:
    if not value:
        return value
    return _fernet().encrypt(value.encode()).decode()


def _decrypt_value(value: str) -> str:
    if not value:
        return value
    try:
        return _fernet().decrypt(value.encode()).decode()
    except Exception:
        return value  # Already plaintext or corrupted → return as-is


def _deep_encrypt(data: dict, encrypt: bool = True) -> dict:
    """Recursively encrypt/decrypt values whose key is in _SENSITIVE_KEYS."""
    fn = _encrypt_value if encrypt else _decrypt_value
    result = {}
    for k, v in data.items():
        if isinstance(v, dict):
            result[k] = _deep_encrypt(v, encrypt)
        elif k in _SENSITIVE_KEYS and isinstance(v, str):
            result[k] = fn(v)
        else:
            result[k] = v
    return result


# ── Public API ────────────────────────────────────────────────────────────────

class ConfigManager:
    """Singleton configuration manager."""

    _instance: "ConfigManager | None" = None

    def __new__(cls) -> "ConfigManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._data = {}
            cls._instance._loaded = False
        return cls._instance

    # ── Load / Save ───────────────────────────────────────────────────────────

    def load(self) -> None:
        """Load config from disk, merging over defaults."""
        defaults = _load_defaults()
        if _CONFIG_PATH.exists():
            try:
                with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                saved_plain = _deep_encrypt(saved, encrypt=False)
                self._data = self._deep_merge(defaults, saved_plain)
            except Exception:
                self._data = defaults
        else:
            self._data = defaults
        self._loaded = True

    def save(self) -> None:
        """Persist current config to disk (with sensitive keys encrypted)."""
        _app_data_dir()
        encrypted = _deep_encrypt(self._data, encrypt=True)
        with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(encrypted, f, indent=2)

    # ── Accessors ─────────────────────────────────────────────────────────────

    def get(self, *keys: str, default: Any = None) -> Any:
        """Dot-path getter: config.get('ai', 'model')."""
        node = self._data
        for k in keys:
            if not isinstance(node, dict) or k not in node:
                return default
            node = node[k]
        return node

    def set(self, *keys_and_value) -> None:
        """Dot-path setter: config.set('ai', 'model', 'gpt-4o')."""
        *keys, value = keys_and_value
        node = self._data
        for k in keys[:-1]:
            node = node.setdefault(k, {})
        node[keys[-1]] = value

    def all(self) -> dict:
        return self._data

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _deep_merge(base: dict, override: dict) -> dict:
        result = dict(base)
        for k, v in override.items():
            if k in result and isinstance(result[k], dict) and isinstance(v, dict):
                result[k] = ConfigManager._deep_merge(result[k], v)
            else:
                result[k] = v
        return result


# Module-level singleton accessor
config = ConfigManager()
