# Installation

## Requirements

- **Python 3.10 or newer** (3.12 recommended; tested on 3.10–3.15)
- **Git 2.38+** (worktree support)
- **Linux or macOS** (POSIX-only)
- **GitHub CLI (`gh`)** — optional, required only for GitHub/GHES PRs in `renv pr` ([install](https://cli.github.com/))

## Recommended: uv tool

```bash
uv tool install repo-env
renv --help
```

## Alternative: pipx

```bash
pipx install repo-env
renv --help
```

## Alternative: pip (virtual environment)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install repo-env
renv --help
```

## Verify installation

```bash
renv --version
```

## SCM providers for `renv clone`

GitHub / GitHub Enterprise, Azure DevOps and Gitea/Forgejo discovery work out of the box.
GitLab and Bitbucket need their client library via an extra:

| Extra | Adds |
|-------|------|
| `repo-env[gitlab]` | GitLab.com and self-managed GitLab (`python-gitlab`) |
| `repo-env[bitbucket]` | Bitbucket Cloud and Bitbucket Server/Data Center (`atlassian-python-api`) |
| `repo-env[all]` | All of the above |

```bash
uv tool install 'repo-env[all]'
```

`renv clone` tells you which extra to install when a host needs one that is missing.

## PR provider authentication

`renv pr` supports GitHub/GHES, GitLab, Bitbucket Cloud, Bitbucket Server/Data Center,
Azure DevOps, and Gitea/Forgejo. Non-GitHub providers use REST APIs and the
[configured credentials](configuration.md#credentials); no CLI or discovery extras are required.

GitHub/GHES retains the GitHub CLI workflow:

```bash
gh auth login
gh auth status
```

## Shell completion

Install into your shell's completion directory (detects the shell from `$SHELL`, prompts once):

```bash
renv --install-completion
```

Or specify explicitly, and restart your shell (or `source` its rc file) afterward:

=== "bash"

    ```bash
    renv --install-completion bash
    ```

=== "zsh"

    ```bash
    renv --install-completion zsh
    ```

=== "fish"

    ```bash
    renv --install-completion fish
    ```

## Upgrading

```bash
uv tool upgrade repo-env   # or: pipx upgrade repo-env
```

## Next steps

- [Quick Start](quickstart.md)
- [Workflow example](workflow-example.md)
