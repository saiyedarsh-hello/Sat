"""
automation/file_ops.py
Create, rename, move, copy, and delete files and folders.
All destructive operations go to the Recycle Bin (send2trash) when available.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
from pathlib import Path

log = logging.getLogger(__name__)

_HOME = Path.home()
_DESKTOP = _HOME / "Desktop"
_DOCUMENTS = _HOME / "Documents"


def _resolve_path(name: str) -> Path:
    """Resolve a user-provided path string relative to Desktop, Documents, Home, or Windows Temp."""
    clean_name = re.sub(r"\b(?:file|folder|directory|document)\b", "", name, flags=re.I).strip() or name.strip()

    if clean_name.lower() in ("temp", "tmp", "temporary"):
        import tempfile
        return Path(tempfile.gettempdir())

    p = Path(clean_name)
    if p.is_absolute():
        return p
    # Try Desktop first, then Documents, then Home
    for base in (_DESKTOP, _DOCUMENTS, _HOME):
        candidate = base / p
        if candidate.exists():
            return candidate
        if not p.suffix:
            for ext in (".txt", ".tmp", ".log", ".md", ".json", ".csv"):
                cand_ext = base / f"{clean_name}{ext}"
                if cand_ext.exists():
                    return cand_ext
    return _DESKTOP / p  # default: relative to Desktop



class FileOps:
    """Safe file-system operations with trash-bin support."""

    def handle(self, slots: dict, raw: str) -> str:
        """Dispatch to the right operation from intent parser slots."""
        op = slots.get("operation", "").lower()
        name = slots.get("name", "")

        if not op:
            return self._llm_describe(raw)

        if op in ("create", "make", "new"):
            return self.create(name, raw)
        if op == "delete" or op == "remove":
            return self.delete(name)
        if op == "rename":
            return self.rename_from_text(raw)
        if op in ("move", "copy"):
            return self.move_copy_from_text(op, raw)
        return f"I'm not sure how to perform the file operation: {raw}"

    # ── Operations ────────────────────────────────────────────────────────────

    def create(self, name: str, raw: str = "") -> str:
        if not name:
            # Try to extract from raw text
            m = re.search(r'(?:called|named)\s+"?([^"]+)"?', raw, re.I)
            name = m.group(1).strip() if m else "new_file.txt"

        # Decide file vs folder
        is_folder = any(
            kw in raw.lower() for kw in ("folder", "directory", "dir")
        ) or "." not in name

        target = _resolve_path(name)

        try:
            if is_folder:
                target.mkdir(parents=True, exist_ok=True)
                log.info("Created folder: %s", target)
                return f"Created folder '{target.name}' on your Desktop."
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.touch(exist_ok=True)
                log.info("Created file: %s", target)
                return f"Created file '{target.name}' on your Desktop."
        except Exception as exc:
            log.error("Create failed: %s", exc)
            return f"Failed to create '{name}': {exc}"

    def delete(self, name: str) -> str:
        if not name:
            return "Please tell me which file or folder to delete."
        target = _resolve_path(name)
        if not target.exists():
            return f"I couldn't find '{name}' to delete."
        try:
            try:
                import send2trash
                send2trash.send2trash(str(target))
                log.info("Sent to trash: %s", target)
                return f"Moved '{target.name}' to the Recycle Bin."
            except ImportError:
                if target.is_dir():
                    shutil.rmtree(target)
                else:
                    target.unlink()
                log.info("Deleted: %s", target)
                return f"Deleted '{target.name}'."
        except Exception as exc:
            log.error("Delete failed: %s", exc)
            return f"Failed to delete '{name}': {exc}"

    def rename_from_text(self, raw: str) -> str:
        m = re.search(
            r'rename\s+"?([^"]+)"?\s+to\s+"?([^"]+)"?', raw, re.I
        )
        if not m:
            return "Please say: rename 'old name' to 'new name'."
        old_name, new_name = m.group(1).strip(), m.group(2).strip()
        old = _resolve_path(old_name)
        if not old.exists():
            return f'I couldn\'t find \'{old_name}\'.'
        new = old.parent / new_name
        try:
            old.rename(new)
            log.info("Renamed %s → %s", old, new)
            return f'Renamed "{old_name}" to "{new_name}".'
        except Exception as exc:
            return f"Rename failed: {exc}"

    def move_copy_from_text(self, op: str, raw: str) -> str:
        m = re.search(
            r'(?:move|copy)\s+"?([^"]+)"?\s+to\s+"?([^"]+)"?', raw, re.I
        )
        if not m:
            return f'Please say: {op} "source" to "destination".'
        src_name, dst_name = m.group(1).strip(), m.group(2).strip()
        src = _resolve_path(src_name)
        dst = Path(dst_name) if Path(dst_name).is_absolute() else _HOME / dst_name
        if not src.exists():
            return f'I couldn\'t find "{src_name}".'
        try:
            dst.mkdir(parents=True, exist_ok=True)
            fn = shutil.copy2 if op == "copy" else shutil.move
            fn(str(src), str(dst / src.name))
            log.info("%s %s → %s", op, src, dst)
            return f'{op.capitalize()}d "{src.name}" to "{dst}".'
        except Exception as exc:
            return f"{op.capitalize()} failed: {exc}"

    def _llm_describe(self, raw: str) -> str:
        return f"I understood you want to do a file operation: '{raw}'. Could you be more specific?"
