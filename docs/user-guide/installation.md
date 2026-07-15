# Installation

## Requirements

- **Python 3.10 or newer** (3.12 recommended; tested on 3.10–3.14)
- **Git 2.38+** (worktree support)
- **Linux or macOS** (POSIX-only)
- **GitHub CLI (`gh`)** — optional, required only for `renv pr` ([install](https://cli.github.com/))

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

## GitHub CLI (for `renv pr`)

```bash
gh auth login
gh auth status
```

## Shell completion

Add to `~/.bashrc` / `~/.zshrc` / `~/.config/fish/config.fish`:

```bash
eval "$(renv completion)"          # auto-detects shell from $SHELL
```

Or specify explicitly:

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
