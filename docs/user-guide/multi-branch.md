# Multi-branch environments

Sometimes you need to work on **several branches of the same repository at once** —
for example to apply the same change to multiple release lines, or to compare a
fix across `main` and `develop`. `renv` supports this by letting a single repo
appear multiple times in one environment, once per base branch.

## The `--from` flag

`renv create` and `renv add` accept `--from/-f`, which names the **base branch(es)**
to start each worktree from. It is repeatable and also accepts a comma-separated
list, so these are equivalent:

```bash
renv create web --from main --from develop
renv create web --from main,develop
```

- **One** `--from` value → the classic layout: one worktree per repo, directory
  named after the repo (`web/alpha`).
- **Multiple** `--from` values → one worktree per repo **per** base branch.

`--from` replaces the former `--default-branch/-B` flag. When you omit `--from`,
`renv` falls back to the configured `default_branch` (or auto-detects the remote
default), exactly as before.

## Flat layout with a base-branch postfix

Worktrees always use a **flat** directory layout. When a repo yields more than one
worktree, the base branch is appended as a postfix (slashes are sanitised to `-`):

```text
<dest>/hotfix/
  .repoenv.json
  alpha-main/            # worktree of alpha, based on main
  alpha-develop/         # worktree of alpha, based on develop
  beta-main/
  beta-develop/
```

If you also pass `--branch/-b`, the created branch is postfixed by the base too, so
the new branches stay unique:

```bash
renv create hotfix -i "alpha,beta" --from main,develop -b fix/cve-123
# alpha-main     -> branch fix/cve-123-main     (from main)
# alpha-develop  -> branch fix/cve-123-develop  (from develop)
# beta-main      -> branch fix/cve-123-main
# beta-develop   -> branch fix/cve-123-develop
```

With a **single** base branch nothing is postfixed (the classic behaviour):
`renv create web --from main -b feature/x` creates `web/alpha` on branch
`feature/x`.

## Example workflow

```bash
# Create worktrees for one repo on two release lines, each on its own fix branch.
renv create hotfix -s ~/src -i payments \
    --from release/1.0 --from release/2.0 \
    --branch fix/cve-123 --activate

# Apply and verify the change in every worktree at once.
renv run hotfix -- ./apply-patch.sh
renv run hotfix -- pytest -q

# Inspect: each worktree shows its directory and checked-out branch.
renv status hotfix

# Open one PR per worktree, each targeting its own base branch.
renv pr hotfix --title "fix: patch CVE-123" --push
```

Add another branch-worktree later with `renv add`:

```bash
renv add hotfix -i payments --from release/3.0 --branch fix/cve-123
# -> payments-release-3.0 on branch fix/cve-123
```

## How commands treat duplicate repos

- **`renv run` / `renv status`** label each worktree by its **directory name**
  (`alpha-develop`), which is unique within the environment, and `status` also
  shows the checked-out branch.
- **`renv pr`** creates one pull request per worktree, each based on that
  worktree's source branch.
- **`renv add`** without `--from` keeps the classic "skip if the repo is already
  present" behaviour. With `--from`, adding a base that already has a worktree in
  the environment is skipped as already present; adding a **new** base creates a
  new postfixed worktree.

## Edge cases

- **Base branch already checked out in the source clone.** Creating a *new*
  branch from it (the common case with `--branch`) is unaffected. Without
  `--branch`, `renv` makes a detached checkout at the base commit to avoid git's
  "branch already checked out" error; use `--branch` if you want to commit.
- **Branch names with slashes** (`release/1.0`) are sanitised to `-` for the
  directory name (`alpha-release-1.0`); the real branch keeps its slash.
- **`--preserve`** branches from the *local* base ref, so the base branch must
  exist locally in the source clone (no fetch is performed).
