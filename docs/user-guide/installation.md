# Installation

## Requirements

- Python 3.12 or newer
- Git 2.38+ (worktree `--orphan` support)
- Linux or macOS (POSIX-only)

## Recommended: uv tool

```sh
uv tool install repo-env
renv --help
```

## Alternative: pipx

```sh
pipx install repo-env
renv --help
```

## Alternative: pip (virtual environment)

```sh
python -m venv .venv && source .venv/bin/activate
pip install repo-env
renv --help
```

## Verify installation

```sh
renv --version
```

## Shell completion

Add to `~/.bashrc` / `~/.zshrc` / `~/.config/fish/config.fish`:

```sh
eval "$(renv completion)"          # auto-detects shell from $SHELL
```

Or specify explicitly:

=== "bash"

    ```sh
    renv --install-completion bash
    ```

=== "zsh"

    ```sh
    renv --install-completion zsh
    ```

=== "fish"

    ```sh
    renv --install-completion fish
    ```

## Upgrading

```sh
uv tool upgrade repo-env   # or: pipx upgrade repo-env
```
