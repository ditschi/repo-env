"""Drives two real `renv select` sessions for the asciinema recording.

Seeds a throwaway sandbox (two tiny local repos + two environments), then
uses pexpect to send the same keystrokes a person would (arrow keys, enter)
with realistic pauses, mirroring the child pty's real output live to our own
stdout so `asciinema record --command "..."` captures genuine timing rather
than synthetic typing speed.

Two short sessions (status, then activate) rather than one longer one so the
demo stays deterministic -- no subshell spawn/exit to synchronize with, and
no dependency on the recording machine's own shell dotfiles/prompt theme.

Not run directly; see docs/assets/casts/README.md for the full regenerate
command (this needs `pexpect`, which isn't a project dependency -- run it via
`uv run --with pexpect --no-project python3 ...`).
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pexpect

SANDBOX = Path("/tmp/renv-asciinema-select-demo")
DOWN = "\x1b[B"
ENTER = "\r"


def _run(*cmd: str, cwd: Path | None = None) -> None:
    subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True)


def seed() -> None:
    if SANDBOX.exists():
        subprocess.run(["rm", "-rf", str(SANDBOX)], check=True)
    for repo in ("src-web/webapp", "src-api/apiserver"):
        path = SANDBOX / repo
        path.mkdir(parents=True)
        _run("git", "init", "-q", "-b", "main", cwd=path)
        _run("git", "config", "user.email", "demo@example.com", cwd=path)
        _run("git", "config", "user.name", "demo", cwd=path)
        (path / "README.md").write_text(f"# {path.name}\n")
        _run("git", "add", "-A", cwd=path)
        _run("git", "commit", "-q", "-m", "init", cwd=path)
    (SANDBOX / "envs").mkdir()

    os.environ["REPOENV_HOME"] = str(SANDBOX / "home")
    _run("renv", "init", "-s", str(SANDBOX / "src-web"), "-d", str(SANDBOX / "envs"), "-y")
    # --preserve + -B: plain local repos with no `origin` remote to fetch from
    # (see the repo's own AGENTS.md "Non-obvious gotchas").
    _run("renv", "create", "web", "-s", str(SANDBOX / "src-web"), "--preserve", "-B", "main")
    _run("renv", "create", "api", "-s", str(SANDBOX / "src-api"), "--preserve", "-B", "main")


def _run_select(*, env_downs: int, action_downs: int, wait_for: str) -> None:
    child = pexpect.spawn("renv select", dimensions=(40, 100), env=os.environ, encoding="utf-8", timeout=10)
    child.logfile = sys.stdout

    child.expect("Pick an environment")
    time.sleep(0.6)
    child.send(DOWN * env_downs)
    time.sleep(0.4)
    child.send(ENTER)

    child.expect("Pick an action")
    time.sleep(0.6)
    child.send(DOWN * action_downs)
    time.sleep(0.4)
    child.send(ENTER)

    child.expect(wait_for)
    time.sleep(1.2)
    child.expect(pexpect.EOF, timeout=5)


def main() -> None:
    seed()

    print("$ renv select", flush=True)
    time.sleep(0.3)
    _run_select(env_downs=1, action_downs=0, wait_for="Environment ")
    time.sleep(1)

    print("\n$ renv select", flush=True)
    time.sleep(0.3)
    _run_select(env_downs=0, action_downs=1, wait_for="Active environment set to")
    time.sleep(1)


if __name__ == "__main__":
    main()
