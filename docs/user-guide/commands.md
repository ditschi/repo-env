# Commands

All commands are invoked as `renv <command> [OPTIONS] [ARGS]`.

Run `renv --help` or `renv <command> --help` for the latest flags.

---

## `renv init`

First-run setup wizard. Writes the user config file.

```bash
renv init [OPTIONS]
```

Key options:

- `--source/-s DIR`: default source directory of clones
- `--dest/-d DIR`: default destination root for environments
- `--default-branch BRANCH`: fallback default branch
- `--install-completion`: record completion preference
- `--yes/-y`: non-interactive

---

## `renv create`

Create a new environment from repositories in a source directory.

```bash
renv create NAME [OPTIONS]
```

`renv new` remains available as a compatibility alias.

Highlights:

- `--source/-s DIR`, `--dest/-d DIR`
- `--include/-i GLOB` / `--exclude/-x GLOB` (repeatable; CSV also supported)
- `--branch/-b BRANCH` (create branch in each repo)
- `--default-branch/-B BRANCH` (fallback when auto-detect fails)
- `--preserve` (skip fetch/update; use source repos as-is)
- `--activate` (set as default environment)
- `--on-branch-conflict detach|move|fail` (when branch already checked out elsewhere)
- `--dry-run/-n`

### Directory layout

Each environment is a directory under your `--dest` root:

```text
<dest>/<env-name>/
  .repoenv.json          # environment metadata (also the renv-root marker)
  <repo-a>/              # git worktree for repo-a
  <repo-b>/              # git worktree for repo-b
```

The env directory is a container; each repository gets its own subdirectory worktree.

---

## `renv ls`

List all environments and their worktree status.

```bash
renv ls [--json]
```

---

## `renv activate`

Set the default active environment for future commands (when not inside an env directory).

```bash
renv activate NAME
```

---

## `renv config`

Inspect and edit configuration/state.

```bash
renv config [KEY [VALUE]] [--unset] [--json]
```

Examples:

- `renv config` (dump effective config + paths + active env)
- `renv config source ~/src`
- `renv config autocorrect 0.5`

---

## `renv path`

Print the filesystem path to a named environment (suitable for `cd`).

```bash
renv path [ENV] [--repo NAME]
```

---

## `renv run`

Run an arbitrary shell command inside every worktree of an environment.

```bash
renv run [ENV] [OPTIONS] -- COMMAND [ARGS...]
```

Highlights:

- `--jobs/-j N` (parallel workers)
- `--include/-i GLOB` / `--exclude/-x GLOB` (subset selection; CSV supported)
- `--shell` (run via shell to enable pipes/globs)
- `--json`

---

## `renv pr`

Open bulk pull requests for every worktree with unpushed commits.

```bash
renv pr [ENV] --title TITLE [OPTIONS]
```

Highlights:

- `--include/-i GLOB` / `--exclude/-x GLOB` (subset selection; CSV supported)
- `--push` (push branches before creating PRs)
- `--skip-no-diff` (skip repos with no commits vs base)
- `--if-exists skip|fail`

!!! warning "No auto-push"
    `renv pr` never pushes unless `--push` is given.

---

## `renv repair`

Recreate worktrees that are missing or marked failed/stale, using metadata stored in the registry.

```bash
renv repair [ENV] [OPTIONS]
```

Highlights:

- `--include/-i GLOB` / `--exclude/-x GLOB` (subset selection; CSV supported)
- `--on-branch-conflict detach|move|fail`
- `--preserve` (skip fetch/update)
- `--dry-run/-n`

Use after manual deletion of individual worktree directories, or when `renv create`/`add` left some repos in a failed state.

---

## `renv rm`

Remove an environment (deletes worktrees, leaves source clones).

```bash
renv rm [ENV] [--delete-files] [--force] [--dry-run]
```

By default, `renv rm` removes the environment from the registry only. Use `--delete-files` to also remove worktrees and the env directory.

---

## `renv add`

Add repositories to an existing environment.

```bash
renv add [ENV] [OPTIONS]
```

Highlights:

- `--source/-s DIR` (defaults to env source or config)
- `--include/-i GLOB` / `--exclude/-x GLOB`
- `--branch/-b BRANCH`, `--on-branch-conflict detach|move|fail`
- `--preserve`, `--activate`, `--dry-run/-n`

---

## `renv clone`

Clone repositories into the **source** tree so you can run `renv create` / `renv add` later.
Does **not** create or modify any renv environment.

```bash
renv clone [OPTIONS]
```

Clones land under `--source` (default: config `source`) using a `host/owner/repo` layout:

```text
~/src/
  github.com/
    my-org/
      service-a/
      service-b/
  github.company.com/
    team/
      internal-tool/
```

### Selecting repositories

- `--url/-u URL` (required, repeatable; CSV supported): a host (`https://github.com`),
  host+owner (`https://github.com/my-org`), or a full repo URL
  (`https://github.com/owner/repo`, `git@github.com:owner/repo.git`).
- `--include/-i PATTERN` / `--exclude/-x PATTERN`: `owner/repo` globs (repeatable; CSV
  supported). Examples: `myself/test-*`, `owner/repo2`, `prefix-*/*`, `**` (match
  everything reachable). Each pattern must contain exactly one `/` (except `**`).
- When `--include` is omitted, every repo reachable via `--url` is included.

Wildcard owner globs (e.g. `company-*/*`) query GitHub via `gh` and are scoped to
orgs you belong to. `--role` controls which memberships count (default: `member`):

| Value | Meaning |
|-------|---------|
| `member` | Active org memberships (any role) |
| `owner` | Active memberships where you are an org admin |
| `any` | Active and pending memberships, any role |

If the default role finds nothing and you did not pass `--role` explicitly, `renv`
automatically retries with `--role any`. When repos are matched with the default role,
orgs that were skipped are reported.

### Syncing existing clones

| Flag | Behavior |
|------|----------|
| *(none)* | Skip repos that already exist locally |
| `--update` | `git fetch`, then fast-forward the current branch to `origin/<branch>` |
| `--reset-default` | Check out the upstream default branch |
| `--force` | Allow `--update` / `--reset-default` to discard local changes or diverged commits |

Both `--update` and `--reset-default` refuse to touch a dirty or diverged repo unless
`--force` is also given.

### Other options

- `--source/-s DIR`, `--protocol ssh|https` (default: `gh`’s `git_protocol`, per host)
- `--jobs/-j N` (parallel clones/updates)
- `--dry-run/-n`

### Examples

```bash
# One repo
renv clone -u https://github.com/owner/repo

# Enterprise host, repo glob
renv clone -u https://github.company.com --include 'my-team/project-*'

# All repos in orgs matching a prefix (active memberships only)
renv clone -u https://github.com --include 'company-*/*'

# Sync everything already cloned under ~/src
renv clone -u https://github.com --include '**' --update
```

Requires [GitHub CLI](https://cli.github.com/) (`gh`) when discovery needs the API
(wildcard owner or repo globs). Full repo URLs clone directly without `gh`.

---

## `renv merge`

Combine two environments into a newly created environment.

```bash
renv merge NAME LEFT RIGHT [OPTIONS]
```

Highlights:

- `--op union|intersect|difference` (default: `union`)
- `--dest/-d DIR`, `--alias/-a NAME`, `--dry-run/-n`

---

## `renv repos`

List all repository names across every registered environment (multi-column).

```bash
renv repos
```

---

## `renv rename`

Rename an environment in the registry and update its metadata.

```bash
renv rename OLD NEW
```

---

## `renv sync`

Fetch updates from each repository's remote for an environment.

```bash
renv sync [ENV]
```

---

## `renv status` / `renv check`

Report per-repo health: present/missing worktrees and dirty state. `check` is an alias for `status`.

```bash
renv status [ENV] [--json]
```

Start here when something looks wrong — see [Troubleshooting](troubleshooting.md).

---

## `renv prune`

Run `git worktree prune` across an environment's source repositories.

```bash
renv prune [ENV]
```

Use when git remembers worktrees whose directories were removed manually.

---

## `renv import`

Register an environment from worktrees already present on disk.

```bash
renv import DIRECTORY [OPTIONS]
```

Highlights:

- `--name NAME` (default: directory basename)
- `--source DIR`, `--alias NAME`

---

## `renv sh`

Open an interactive subshell with the environment context loaded (`REPOENV_ACTIVE`, prompt marker).

```bash
renv sh [ENV]
```

---

## `renv completion`

Print a shell completion script to stdout (for manual installation in dotfiles).

```bash
renv completion [bash|zsh|fish]
```

See [Installation](installation.md) for setup examples.

---

## Optional `[ENV]` argument

Most commands accept an optional environment name. When omitted, resolution follows [Concepts → Environment resolution](concepts.md#environment-resolution). Use `-` or rely on CWD inside an environment directory.
