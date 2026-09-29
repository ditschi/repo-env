# Configuration

## Config file location

`renv` stores its config and registry under a single home directory.

- **Default**: platform config dir for app name `repoenv` (Linux: `~/.config/repoenv/`)
- **Override**: set `REPOENV_HOME` to relocate everything (CI, multiple profiles)

Important files (relative to `REPOENV_HOME`):

- `repoenv.yaml` — user-authored config
- `registry.json` — machine-owned environment registry (includes the active environment)

Run `renv init` to generate the file interactively, or create it manually.

## Schema

```yaml
# Default source directory for `renv create` / `renv add` (overridable by flags)
source: ~/src

# Default destination root for new environments
dest: ~/envs

# Fallback default branch when auto-detection fails
default_branch: develop

# Record completion preference (`renv init`; scripts are still user-managed)
install_completion: false

# Auto-correct unknown subcommands after N seconds (git-like behavior)
# autocorrect: 0.5
autocorrect: null

# Optional shorthand: alias name -> environment name (see Concepts)
aliases:
  web: ado

# Optional named repo selections: group name -> glob (or comma-separated globs)
groups:
  backend: "*/backend-*"
```

## Aliases

Two alias mechanisms exist; see [Concepts](concepts.md#aliases-two-kinds) for resolution order.

| Mechanism | How to set | Example |
|-----------|------------|---------|
| **Config alias** | YAML `aliases:` or `renv config aliases.web ado` | type `web`, runs env `ado` |
| **Environment alias** | `renv create --alias`, `renv import --alias`, `renv merge --alias` | env `ado` also known as `web` |

Manage config aliases:

```bash
renv config aliases.web ado
renv config aliases.web --unset
renv config aliases.web          # read one alias
```

## Repo groups

Save a glob (or comma-separated globs) under a short name for reuse with `--include`/`--exclude`
on `create`/`add`/`repair` — see [Concepts](concepts.md#selecting-repos):

```bash
renv config groups.backend '*/backend-*'
renv config groups.backend --unset
renv config groups.backend          # read one group
renv create svc --include @backend
```

## Environment variables

`REPOENV_HOME` relocates config, registry, and state:

```bash
REPOENV_HOME=/tmp/repoenv-profile renv ls
```

Inside `renv sh`, `REPOENV_ACTIVE` is set for subshell context.

## Machine state

Per-environment metadata lives in `.repoenv.json` inside the environment directory (also the renv-root marker). It may include a `marker` block with a reproducible `renv create …` command.

Lock files (`.lock`) guard concurrent JSON writes; see [Troubleshooting](troubleshooting.md).
