# Quick Start

## 1. First-run setup

```bash
renv init
```

The wizard asks for your source directory (where git clones live) and destination root for environments. Settings are stored in `~/.config/repoenv/repoenv.yaml` on Linux (see [Configuration](configuration.md)).

## 2. Create an environment

```bash
renv create web -s ~/src -b feature/my-task --activate
```

`renv` scans `~/src` for git repositories, creates a worktree on branch `feature/my-task` in each match, and registers the environment `web`. `--activate` sets it as the default for future commands.

## 3. List environments

```bash
renv ls
```

## 4. Navigate to an environment

```bash
cd "$(renv path web)"
```

Inside an environment directory you can omit the env name on most commands.

## 5. Run a command across all worktrees

```bash
renv run web -- git status
renv run -- make test          # same, when active or cwd is inside web
```

## 6. Open bulk pull requests

Requires [GitHub CLI](https://cli.github.com/) (`gh auth login`).

```bash
renv pr web --title "feat: migrate X to Y" --draft
renv pr web --title "feat: migrate X to Y" --push   # push branches first
```

`renv pr` never pushes unless `--push` is given.

## 7. Tear down an environment

```bash
renv rm web --delete-files    # remove registry + worktrees + env dir
renv rm web                   # registry-only (files stay on disk)
```

Source clones under `~/src` are never deleted.

## Next steps

- [Workflow example](workflow-example.md) — full create → PR → rm walkthrough
- [Concepts](concepts.md) — layout and environment resolution
- [Commands reference](commands.md)
- [Configuration](configuration.md)
