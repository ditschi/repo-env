# Concepts

How `renv` organizes repositories, environments, and configuration.

## Source vs destination

| Term | Meaning |
|------|---------|
| **Source** | Directory tree of your **read-only clones** (`--source` / config `source`). `renv create` and `renv add` scan here for git repos. |
| **Destination (`dest`)** | Root directory where **environment folders** are created (`--dest` / config `dest`). |
| **Environment** | Named folder under `dest` containing one worktree subdirectory per selected repo. |

```text
~/src/                          # source (clones — never modified by renv)
  service-a/
  service-b/

~/envs/                         # dest
  web/                          # environment "web"
    .repoenv.json               # metadata + renv-root marker
    service-a/                  # git worktree
    service-b/                  # git worktree
```

Source clones stay untouched. All day-to-day work happens in worktrees under the environment directory.

## Registry and on-disk state

`renv` keeps two layers of state:

1. **`registry.json`** (under `REPOENV_HOME`) — list of known environments, repo entries, and the **active** environment name.
2. **`.repoenv.json`** inside each environment directory — per-env metadata and an optional `marker` block with the `renv create …` command used to reproduce the env.

Lock files (`.lock`) next to JSON files guard concurrent writes. They include PID/host/user diagnostics and are removed after successful writes.

## Environment resolution

When a command accepts an optional `[ENV]` argument, `renv` picks an environment in this order:

1. **Explicit name** on the command line (`renv run web -- …`)
2. **Environment alias** stored on the environment (`renv create --alias …`, or `renv import --alias …`)
3. **Config alias** from `repoenv.yaml` / `renv config aliases.<name> …` (maps a short name to an environment name)
4. **Current directory** — if CWD is inside an environment path (wins over the active env; a hint is printed when they differ)
5. **`REPOENV_ACTIVE`** — set by `renv sh` for subshell context
6. **Active environment** — set by `renv activate` or `renv create --activate`

If none match, the command fails with a hint to pass a name, `cd` into an env, or run `renv activate`.

## Aliases (two kinds)

| Kind | Set via | Example | Resolves |
|------|---------|---------|----------|
| **Environment alias** | `renv create --alias`, `renv import --alias`, `renv merge --alias` | env `ado` also answers to `web` | `renv run web` → env `ado` |
| **Config alias** | `repoenv.yaml` `aliases:` or `renv config aliases.web ado` | shorthand `web` → env name `ado` | same as typing the env name |

Both are checked when resolving an environment selector. Use config aliases for stable shortcuts in scripts; use `--alias` when the alias is intrinsic to one environment.

## Worktrees and branches

Each repo worktree is a normal git worktree linked to the source clone. With `--branch`, `renv` creates a new branch from the detected default branch. Without `--branch`, worktrees start detached at the default branch tip.

`renv add` is the exception: if `--branch` is omitted there, and the environment already has repos
on a branch `renv` itself created, the new repo joins that same branch instead of landing detached
— so "I forgot a repo" doesn't require re-typing `--branch`. Explicit `--branch` always wins.

If a local branch already exists and is unused, `renv` attaches it automatically. If the branch is checked out elsewhere, use `--on-branch-conflict detach|move|fail` (default: `detach` for `create`/`add`/`repair`, `move` for `merge` — merging is explicitly about consolidating branches, and git only allows one worktree per branch, so the source environment's worktree goes detached as its branch relocates into the merged one).

Before each worktree creation, `renv` runs `git worktree prune` in the source repo to drop stale metadata.

## Selecting repos

`--include`/`--exclude` take shell-style globs, matched against the repo's path relative to
`source` (so nested clones like `github.com/org/repo` are selected with e.g. `*/org/*`). Multiple
values are OR-ed; comma-separated values in one flag work the same as repeating the flag.

A value starting with `@` is a **repo group** — a saved pattern (or comma-separated patterns) set
with `renv config groups.<name> <pattern>` — and mixes freely with literal globs:
`--include @backend,*/frontend-*`. Groups and repo names both tab-complete.

## Safety model

- Source clones: treated as read-only.
- `renv rm`: registry-only by default; `--delete-files` removes worktrees and the env directory.
- `renv pr`: never pushes unless `--push` is given; requires the GitHub CLI (`gh`).

See [Troubleshooting](troubleshooting.md) for recovery when disk and registry diverge.
