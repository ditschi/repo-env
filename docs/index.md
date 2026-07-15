<p align="center">
  <img src="assets/brand/renv-lockup.png" alt="repo-env — renv CLI" width="280">
</p>

# repo-env

> Build and operate isolated **git-worktree environments** across many repositories.

`repo-env` provides the `renv` CLI. An *environment* is a named directory containing one git worktree per selected repository. Create environments from repos matching a glob, run commands across every worktree, and open bulk pull requests — all from one command.

## Why repo-env?

Working across many related repositories is tedious: context-switching between clones, opening the same branch in a dozen repos, forgetting to push before opening PRs. `repo-env` eliminates that friction by giving each logical task its own isolated worktree layer.

- **Safe**: source clones are treated as read-only; destructive operations require explicit flags.
- **Fast**: backed by git worktrees — no extra disk space for tracked objects.
- **Scriptable**: every command is composable in shell pipelines.

## Quick navigation

| I want to… | Go to… |
|---|---|
| Install and get started | [Installation](user-guide/installation.md) → [Quick Start](user-guide/quickstart.md) |
| Follow a full workflow | [Workflow example](user-guide/workflow-example.md) |
| Learn the commands | [Commands](user-guide/commands.md) |
| Understand layout and env resolution | [Concepts](user-guide/concepts.md) |
| Fix broken worktrees / registry | [Troubleshooting](user-guide/troubleshooting.md) |
| Understand config options | [Configuration](user-guide/configuration.md) |
| Contribute to the project | [Development Setup](contributor-guide/dev-setup.md) |
| See what changed | [Changelog](changelog.md) |
