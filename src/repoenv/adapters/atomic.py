"""Atomic file writes with locking and optional backups.

Writes go to a temp file in the same directory and are renamed with
``os.replace`` (atomic on POSIX). A ``filelock`` guards concurrent writers, and
an optional ``.bak`` preserves the last-good version before each mutation.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from filelock import FileLock

from repoenv.adapters.paths import lock_path


def atomic_write_text(target: Path, text: str, *, mode: int = 0o600, backup: bool = False) -> None:
    """Atomically write ``text`` to ``target`` under a file lock.

    - Creates the parent directory if needed.
    - Optionally copies the existing file to ``<target>.bak`` first.
    - Sets file permissions to ``mode`` (default 0600).
    """
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = FileLock(str(lock_path(target)))
    with lock:
        if backup and target.exists():
            backup_path = target.with_suffix(target.suffix + ".bak")
            backup_path.write_text(target.read_text(encoding="utf-8"), encoding="utf-8")
            os.chmod(backup_path, mode)

        fd, tmp_name = tempfile.mkstemp(dir=str(target.parent), prefix=f".{target.name}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(tmp_name, mode)
            os.replace(tmp_name, target)
        except BaseException:
            _silent_unlink(Path(tmp_name))
            raise


def _silent_unlink(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass
