# Commit Convention

`repo-env` uses **[Conventional Commits 1.0](https://www.conventionalcommits.org/)**.

## Why

- Enables **automatic version bumping** (`cz bump` infers patch / minor / major from commit types).
- Generates a **structured changelog** (`cz changelog`).
- Makes the Git history machine- and human-readable.

## Format

```
<type>(<scope>): <short summary>

[optional body]

[optional footer(s)]
```

### Types

| Type | Triggers | Use for |
|------|----------|---------|
| `feat` | minor bump | New user-visible feature |
| `fix` | patch bump | Bug fix |
| `docs` | patch bump | Documentation only |
| `refactor` | patch bump | Code restructure, no behaviour change |
| `perf` | patch bump | Performance improvement |
| `test` | patch bump | Adding / fixing tests |
| `build` | patch bump | Build system, deps |
| `ci` | patch bump | CI/CD changes |
| `chore` | patch bump | Maintenance (e.g. version bumps, tool configs) |
| `revert` | patch bump | Reverts a previous commit |

### Breaking changes

Append `!` after the type, or add `BREAKING CHANGE:` in the footer:

```
feat!: remove --legacy flag
```

```
feat(cli): redesign pr command

BREAKING CHANGE: --push flag removed; use `git push` before `renv pr`
```

Breaking changes trigger a **major** version bump.

### Scopes (optional but encouraged)

Use the package sub-directory or domain concept as scope:

```
feat(cli): add --parallel flag to run command
fix(adapters/git): handle detached HEAD state
docs(contributor-guide): add release process
```

### Summary rules

- Lowercase, no period at the end.
- Imperative mood: "add X" not "adds X" or "added X".
- ≤ 72 characters.

## Enforcement

### PR title (primary gate — squash merges)

Because the repo uses **squash merges**, the PR title becomes the commit on `main`. The CI job `Lint PR title` (`amannn/action-semantic-pull-request`) rejects PRs whose titles do not follow Conventional Commits.

### Local commit-msg hook (contributor helper)

The `commitizen` `commit-msg` pre-commit hook validates each local commit:

```sh
# Installed automatically by: pre-commit install --hook-type commit-msg
git commit -m "oops bad message"   # → rejected with helpful error
git commit -m "fix(cli): handle empty source dir"  # → accepted
```

### Interactive commit helper

```sh
cz commit   # guided prompt that writes a valid message for you
```

## Examples

```
feat(cli): add --glob filter to renv create
fix(adapters/git): avoid crash when worktree already exists
docs: add configuration reference page
ci: add multi-python test matrix (3.12/3.13/3.14)
chore: bump commitizen to 3.29
feat!: require explicit --source flag; drop positional arg
```
