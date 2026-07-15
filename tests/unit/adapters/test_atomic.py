from __future__ import annotations

from pathlib import Path

from filelock import FileLock

from repoenv.adapters import atomic
from repoenv.adapters.paths import lock_path


def test_atomic_write_unlinks_lock_file_after_release(tmp_path: Path, monkeypatch) -> None:
    """Lock path must not be unlinked while the FileLock context is still held."""
    events: list[str] = []
    target = tmp_path / "data.json"
    lock_file = lock_path(target)

    real_exit = FileLock.__exit__

    def tracking_exit(self, exc_type, exc, tb):
        events.append("release")
        return real_exit(self, exc_type, exc, tb)

    real_unlink = atomic._silent_unlink

    def tracking_unlink(path: Path) -> None:
        events.append("unlink")
        real_unlink(path)

    monkeypatch.setattr(FileLock, "__exit__", tracking_exit)
    monkeypatch.setattr(atomic, "_silent_unlink", tracking_unlink)

    atomic.atomic_write_text(target, '{"ok": true}\n')

    assert target.read_text(encoding="utf-8") == '{"ok": true}\n'
    assert not lock_file.exists()
    assert events == ["release", "unlink"]
