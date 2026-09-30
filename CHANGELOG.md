# Changelog

All notable changes to this project will be documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
This file is updated automatically by `cz bump` — do not edit manually except before the first tagged release.

## [0.1.0] - 2026-09-30

First public release of `repo-env` / the `renv` CLI.

### Added

- `renv` CLI for managing multi-repository git worktree environments
- `renv clone` — clone repositories into the source tree (`host/owner/repo` layout) via
  `--url` and `owner/repo` `--include`/`--exclude` globs; GitHub discovery through `gh`
  when globs need the API; `--update`, `--reset-default`, and `--force` for existing clones
- `renv select` — interactive picker (arrow keys) for choosing an environment and then an
  action to run against it: `status`, `activate`, `sh`, `sync`, `path`, `rm`
- Commands: `init`, `create`, `add`, `merge`, `ls`, `repos`, `path`, `run`, `rm`, `rename`, `sync`, `status`, `check`, `prune`, `repair`, `import`, `pr`, `sh`, `select`, `clone`, `activate`, `config`
- Environment resolution: explicit name, environment alias, config alias, CWD-in-env, `REPOENV_ACTIVE`, persisted active env
- User config (`repoenv.yaml`) and registry (`registry.json`) under `REPOENV_HOME`
- Per-environment metadata in `.repoenv.json` (includes reproduction marker)
- Branch conflict strategies: `--on-branch-conflict detach|move|fail` (`create`/`add`/`repair`), defaulting to `move` on `merge`
- `renv add` without `--branch` joins the branch an environment's other repos are already on, instead of landing detached
- `renv merge` preserves each side's task branch (reporting conflicts) instead of recreating detached worktrees
- Named repo groups (`renv config groups.<name> <pattern>`) usable as `--include/--exclude @name`, mixable with literal globs
- Tab-completion for environment names/aliases, repo names (with base-dir prefix narrowing), and `@group` names
- Per-repo failure reasons shown by default on `create`/`add`/`status`, not just with `--json`
- Bulk PR creation via GitHub CLI (`gh`); optional `--push`
- `autocorrect` for unknown subcommands: read-only commands (`ls`, `repos`, `path`, `status`, `check`) correct
  immediately, state-changing ones require opt-in
- `--debug`/`REPOENV_DEBUG=1` to show full tracebacks; unexpected errors print a short message otherwise
- Demo recordings and a devcontainer (`uv`, `nox`, `gh`, `asciinema`, `agg` preinstalled) for contributors
- Integration, performance, and multi-Python (3.10–3.14) test coverage
- Documentation site (MkDocs Material) with user and contributor guides

[0.1.0]: https://github.com/ditschi/repo-env/releases/tag/v0.1.0
