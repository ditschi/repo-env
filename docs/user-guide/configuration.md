# Configuration

## Config file location

| Platform | Path |
|----------|------|
| Linux | `~/.config/repo-env/config.yaml` |
| macOS | `~/Library/Application Support/repo-env/config.yaml` |

Run `renv init` to generate the file interactively, or create it manually.

## Schema

```yaml
# Default source directory scanned by `renv new`
default_source: ~/src

# Default base branch when creating worktrees
default_base_branch: main

# Root directory where environments are stored
environments_root: ~/.local/share/repo-env/envs

# GitHub token (optional; falls back to gh CLI auth if absent)
github_token: ""   # or use REPO_ENV_GITHUB_TOKEN env var

# Parallel job limit for `renv run --parallel`
parallelism: 4
```

## Environment variables

All config keys can be overridden by environment variables using the prefix `REPO_ENV_` and uppercasing the key:

```sh
REPO_ENV_DEFAULT_SOURCE=~/projects renv new web --branch fix/x
REPO_ENV_PARALLELISM=8 renv run web -- make test
```

Environment variables take precedence over config file values.

## Machine state

`renv` stores environment metadata in JSON under the `environments_root`. These files are managed by `renv` and should not be edited manually.
