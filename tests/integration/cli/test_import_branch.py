"""``renv import`` must record the real branch name, not a raw commit SHA.

Before this, ``import_command`` used ``git rev-parse HEAD`` (a commit SHA) as
the value for ``RepoEntry.branch``, so adopting a hand-made worktree checked
out on a real branch like ``feature/x`` silently mislabeled it as a 40-char
hash -- which would then leak into things like ``renv pr``'s ``{branch}``
template.
"""

from __future__ import annotations

from repoenv.adapters import state_store
from repoenv.domain.models import RepoEntry
from tests.integration.support.gitfixtures import run_git
from tests.integration.support.renv_helpers import Renv


def _import_hand_made_alpha(renv: Renv, *worktree_add_opts: str) -> RepoEntry:
    """Add an ``alpha`` worktree by hand, ``renv import`` its directory as ``adopted``; return its entry."""
    clone = renv.repos.make_bare_and_clone("alpha")
    manual_env_dir = renv.worktrees / "hand-made"
    manual_env_dir.mkdir(parents=True)
    run_git(["worktree", "add", *worktree_add_opts, str(manual_env_dir / "alpha")], cwd=clone)

    renv.ok("import", str(manual_env_dir), "--name", "adopted", "--source", str(renv.source))

    env = state_store.load_registry().get("adopted")
    assert env is not None
    return next(e for e in env.repos if e.repo == "alpha")


def test_import_records_real_branch_name_not_sha(renv: Renv) -> None:
    entry = _import_hand_made_alpha(renv, "-b", "feature/manual")
    assert entry.branch == "feature/manual"
    assert len(entry.source_sha or "") == 40


def test_import_detached_worktree_labels_it_clearly(renv: Renv) -> None:
    entry = _import_hand_made_alpha(renv, "--detach")
    assert entry.branch.startswith("detached@")
    assert entry.source_sha is not None
    assert entry.branch != entry.source_sha
