# Quick Start

## 1. First-run setup

```sh
renv init
```

The setup wizard asks for your source directory (where all your git clones live) and stores the answer in the user config file (`~/.config/repo-env/config.yaml` on Linux).

## 2. Create an environment

```sh
renv create web --source ~/src --branch feature/my-task
```

`renv` scans `~/src` for git repositories, creates a worktree at the branch `feature/my-task` inside each one, and links them all under a named environment called `web`.

## 3. List environments

```sh
renv ls
```

## 4. Navigate to an environment

```sh
cd "$(renv path web)"
```

## 5. Run a command across all worktrees

```sh
renv run web -- git status
renv run web -- make test
```

## 6. Open bulk pull requests

```sh
renv pr web --title "feat: migrate X to Y" --draft
```

`renv pr` never auto-pushes. It opens a PR for every worktree that has unpushed commits, using the PR title as the commit message summary.

## 7. Tear down an environment

```sh
renv rm web
```

Removes all worktrees; leaves the source clones untouched.

## Next steps

- Read the full [Commands reference](commands.md).
- Understand all [Configuration options](configuration.md).
