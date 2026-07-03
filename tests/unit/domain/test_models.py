from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from repoenv.domain.models import Environment, RepoEntry


def test_environment_repo_names() -> None:
    env = Environment(name="x", path=Path("/tmp/e"), source=Path("/tmp/s"))
    env.repos.append(
        RepoEntry(
            repo="alpha",
            worktree_path=Path("/tmp/e/alpha"),
            base="main",
            branch="main",
        )
    )
    assert env.repo_names() == ["alpha"]


def test_strict_string_identity_fields() -> None:
    with pytest.raises(ValidationError):
        RepoEntry(
            repo=True,
            worktree_path=Path("/tmp/e/alpha"),
            base="main",
            branch="main",
        )
