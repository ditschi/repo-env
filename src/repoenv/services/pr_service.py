"""PR service: bulk pull-request creation across an environment's worktrees."""

from __future__ import annotations

from dataclasses import dataclass, field

from repoenv.adapters import gh_adapter, git_adapter
from repoenv.domain.models import Environment
from repoenv.domain.selection import resolve_selection


@dataclass
class PrPlanItem:
    """One repo's resolved PR intent."""

    repo: str
    head: str
    title: str
    body: str


@dataclass
class PrOutcome:
    """Aggregate result of a bulk PR run."""

    created: list[gh_adapter.PrResult] = field(default_factory=list)
    skipped: list[gh_adapter.PrResult] = field(default_factory=list)


def _render(template: str, *, repo: str, branch: str, env: str) -> str:
    """Expand simple ``{repo}``/``{branch}``/``{env}`` placeholders."""
    return template.format(repo=repo, branch=branch, env=env)


def create_prs(
    env: Environment,
    *,
    title: str,
    body: str,
    base: str | None,
    draft: bool,
    reviewers: list[str],
    labels: list[str],
    assignees: list[str],
    push: bool,
    skip_no_diff: bool,
    if_exists: str,
    include: list[str] | None = None,
    exclude: list[str] | None = None,
) -> PrOutcome:
    """Create PRs for each repo in ``env``. Never pushes unless ``push`` is True."""
    outcome = PrOutcome()
    entries = list(env.repos)
    if include is not None or exclude is not None:
        selected = set(resolve_selection([e.repo for e in entries], include=include, exclude=exclude))
        entries = [e for e in entries if e.repo in selected]

    for entry in entries:
        worktree = entry.worktree_path
        branch = git_adapter.current_branch(worktree) or entry.branch

        if skip_no_diff and not git_adapter.has_diff(worktree, f"{entry.remote}/{entry.base}"):
            outcome.skipped.append(
                gh_adapter.PrResult(entry.repo, "", created=False, skipped=True, reason="no diff")
            )
            continue

        existing = gh_adapter.existing_pr_url(worktree, head=branch)
        if existing and if_exists == "skip":
            outcome.skipped.append(
                gh_adapter.PrResult(entry.repo, existing, created=False, skipped=True, reason="exists")
            )
            continue

        if push:
            git_adapter.push(worktree, remote=entry.remote, branch=branch)

        url = gh_adapter.create_pr(
            worktree,
            title=_render(title, repo=entry.repo, branch=branch, env=env.name),
            body=_render(body, repo=entry.repo, branch=branch, env=env.name),
            base=base or entry.base,
            head=branch,
            draft=draft,
            reviewers=reviewers,
            labels=labels,
            assignees=assignees,
        )
        outcome.created.append(gh_adapter.PrResult(entry.repo, url, created=True))
    return outcome
