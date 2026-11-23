"""Drives the README/quickstart flow for the asciinema recording.

Seeds a throwaway sandbox (one tiny local repo with an `origin` remote, so
`renv run -- git status` shows a real branch/remote comparison rather than a
detached/remote-less repo), then prints each command before running it for
real and letting its actual stdout stream through -- `asciinema rec --command
"..."` captures the genuine output and timing, not synthetic typing.

Forces an English locale so git's own messages (branch/status text) don't
come out in the recording machine's system locale.

Not run directly; see docs/assets/casts/README.md for the full regenerate
command.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

SANDBOX = Path("/tmp/renv-asciinema-quickstart-demo")


def _run(*cmd: str, cwd: Path | None = None, check: bool = True) -> None:
    subprocess.run(cmd, cwd=cwd, check=check, capture_output=True, text=True)


def seed() -> None:
    if SANDBOX.exists():
        subprocess.run(["rm", "-rf", str(SANDBOX)], check=True)
    remote = SANDBOX / "remotes" / "webapp.git"
    remote.mkdir(parents=True)
    _run("git", "init", "-q", "--bare", str(remote))

    clone = SANDBOX / "src" / "webapp"
    clone.parent.mkdir(parents=True)
    _run("git", "clone", "-q", str(remote), str(clone))
    _run("git", "config", "user.email", "demo@example.com", cwd=clone)
    _run("git", "config", "user.name", "demo", cwd=clone)
    (clone / "README.md").write_text("# webapp\n")
    _run("git", "add", "-A", cwd=clone)
    _run("git", "commit", "-q", "-m", "init", cwd=clone)
    _run("git", "push", "-q", "origin", "HEAD:main", cwd=clone)

    (SANDBOX / "envs").mkdir()
    os.environ["REPOENV_HOME"] = str(SANDBOX / "home")
    os.environ["LC_ALL"] = "C.utf8"
    os.environ["LANG"] = "C.utf8"
    _run("renv", "init", "-s", str(SANDBOX / "src"), "-d", str(SANDBOX / "envs"), "-y")


def _type(line: str) -> None:
    print(f"$ {line}", flush=True)
    time.sleep(0.5)


def _stream(*cmd: str, cwd: Path | None = None) -> None:
    subprocess.run(cmd, cwd=cwd, check=False, env=os.environ)
    time.sleep(0.8)


def main() -> None:
    seed()

    _type("renv create web -s ~/src -b feature/my-task --activate")
    _stream("renv", "create", "web", "-s", str(SANDBOX / "src"), "-b", "feature/my-task", "--activate")

    _type("renv ls")
    _stream("renv", "ls")

    _type('cd "$(renv path web)"')
    time.sleep(0.3)
    _type("renv run -- git status")
    env_path = SANDBOX / "envs" / "web"
    _stream("renv", "run", "--", "git", "status", cwd=env_path)


if __name__ == "__main__":
    main()
