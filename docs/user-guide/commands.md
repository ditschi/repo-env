# Commands

All commands are invoked as `renv <command> [OPTIONS] [ARGS]`.

Run `renv --help` or `renv <command> --help` for the latest flags.

---

## `renv init`

First-run setup wizard. Writes the user config file.

```
renv init [--force]
```

| Flag | Description |
|------|-------------|
| `--force` | Re-run wizard even if config already exists |

---

## `renv create`

Create a new environment from repositories in a source directory.

```
renv create NAME --source DIR --branch BRANCH [OPTIONS]
```

`renv new` remains available as a compatibility alias.

| Option | Description |
|--------|-------------|
| `--source DIR` | Root directory to scan for git repositories |
| `--branch BRANCH` | Worktree branch name to create in each repo |
| `--glob PATTERN` | Filter repos by name glob (default: `*`) |
| `--base BRANCH` | Base branch to create the worktree from (default: `main`) |
| `--no-create` | Dry-run: show what would be created |

---

## `renv ls`

List all environments and their worktree status.

```
renv ls [--json]
```

---

## `renv path`

Print the filesystem path to a named environment (suitable for `cd`).

```
renv path NAME
```

---

## `renv run`

Run an arbitrary shell command inside every worktree of an environment.

```
renv run NAME -- COMMAND [ARGS...]
```

| Option | Description |
|--------|-------------|
| `--fail-fast` | Stop on first non-zero exit code |
| `--parallel` | Run across worktrees in parallel |

---

## `renv pr`

Open bulk pull requests for every worktree with unpushed commits.

```
renv pr NAME --title TITLE [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--title TEXT` | PR title (must follow Conventional Commits if enforced by the target repo) |
| `--body TEXT` | PR body text |
| `--draft` | Open as draft PRs |
| `--base BRANCH` | Target base branch (default: `main`) |

!!! warning "No auto-push"
    `renv pr` never pushes your branches automatically. Push first, then run `renv pr`.

---

## `renv rm`

Remove an environment (deletes worktrees, leaves source clones).

```
renv rm NAME [--force]
```

| Flag | Description |
|------|-------------|
| `--force` | Skip confirmation prompt (dangerous in non-interactive mode; blocked) |
