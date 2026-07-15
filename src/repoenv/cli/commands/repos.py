"""``renv repos`` — list all repositories across all environments."""

from __future__ import annotations

from repoenv.adapters import state_store
from repoenv.ui import console


def repos_command() -> None:
    """List all repositories across all environments in multi-column format."""
    registry = state_store.load_registry()
    environments = registry.list()

    # Collect all unique repository names
    all_repos = set()
    for env in environments:
        all_repos.update(env.repo_names())

    console.render_repositories(sorted(all_repos))
