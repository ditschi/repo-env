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

# Optional SCM provider per self-hosted host for clone/PR: "<kind> [<base-url>]"
providers:
  git.company.com: gitlab
  bitbucket.company.com: bitbucket-server https://bitbucket.company.com/bitbucket
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

## SCM providers

`renv clone` and `renv pr` need to know which product serves a host.
PR creation resolves each worktree's configured remote independently, so an
environment can contain repositories from different providers.
Well-known hosts (`github.com`, `gitlab.com`, `bitbucket.org`, `dev.azure.com`,
`codeberg.org`) are built in; other hosts are probed (hostname hints such as `github.*` or
`gitlab.*` are tried first). Pin a host to skip probing, or when the server lives under a
sub-path:

```bash
renv config providers.git.company.com gitlab
renv config providers.bitbucket.company.com 'bitbucket-server https://bitbucket.company.com/bitbucket'
renv config providers.tfs.company.com 'azure-devops https://tfs.company.com/tfs'
```

Kinds: `github`, `gitlab`, `bitbucket-cloud`, `bitbucket-server`, `azure-devops`, `gitea`.

### Credentials

API credentials are looked up per host, without prompting:

1. Environment variables:

    | Provider | Variables |
    |----------|-----------|
    | GitHub.com | `GH_TOKEN`, `GITHUB_TOKEN` |
    | GitHub Enterprise | `GH_ENTERPRISE_TOKEN`, `GITHUB_ENTERPRISE_TOKEN` |
    | GitLab | `GITLAB_TOKEN`, `GL_TOKEN` |
    | Bitbucket | `BITBUCKET_TOKEN` (+ `BITBUCKET_USERNAME` for app passwords / API tokens) |
    | Azure DevOps | `AZURE_DEVOPS_EXT_PAT`, `AZURE_DEVOPS_TOKEN` |
    | Gitea / Forgejo | `GITEA_TOKEN`, `FORGEJO_TOKEN` |

2. GitHub only: `gh auth token --hostname <host>` if the GitHub CLI is installed.
3. Your git credential helper for `https://<host>` (`git credential fill`), i.e. the same
   credentials your HTTPS clones already use (Git Credential Manager, libsecret, keychain, …).
4. Anonymous — enough for public repositories; listing your organizations needs a token.

Non-GitHub PR operations require credentials with repository read and PR/MR write
permissions (for example GitLab `api`, Azure DevOps Code read/write, or the equivalent
Bitbucket/Gitea permissions). GitHub/GHES PRs use `gh` authentication instead of
the credential-helper fallback. No git push occurs unless `--push` is supplied.

## Environment variables

`REPOENV_HOME` relocates config, registry, and state:

```bash
REPOENV_HOME=/tmp/repoenv-profile renv ls
```

Inside `renv sh`, `REPOENV_ACTIVE` is set for subshell context.

## Machine state

Per-environment metadata lives in `.repoenv.json` inside the environment directory (also the renv-root marker). It may include a `marker` block with a reproducible `renv create …` command.

Lock files (`.lock`) guard concurrent JSON writes; see [Troubleshooting](troubleshooting.md).
