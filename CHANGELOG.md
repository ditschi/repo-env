# Changelog

All notable changes to this project will be documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
This file is updated automatically by `cz bump` — do not edit manually except before the first tagged release.

## [Unreleased]

### Added

- `renv clone` — clone repositories into the source tree (`host/owner/repo` layout) via
  `--url` and `owner/repo` `--include`/`--exclude` globs; GitHub discovery through `gh`
  when globs need the API; `--update`, `--reset-default`, and `--force` for existing clones

## [0.1.0] - 2026-07-13

First public release of `repo-env` / the `renv` CLI.

### Added

- `renv` CLI for managing multi-repository git worktree environments
- Commands: `init`, `create`, `add`, `merge`, `ls`, `repos`, `path`, `run`, `rm`, `rename`, `sync`, `status`, `check`, `prune`, `repair`, `import`, `pr`, `sh`, `completion`, `activate`, `config`
- Environment resolution: explicit name, environment alias, config alias, CWD-in-env, `REPOENV_ACTIVE`, persisted active env
- User config (`repoenv.yaml`) and registry (`registry.json`) under `REPOENV_HOME`
- Per-environment metadata in `.repoenv.json` (includes reproduction marker)
- Branch conflict strategies: `--on-branch-conflict detach|move|fail`
- Bulk PR creation via GitHub CLI (`gh`); optional `--push`
- Shell completion for environment names; `autocorrect` for unknown subcommands
- Integration, performance, and multi-Python (3.10–3.14) test coverage
- Documentation site (MkDocs Material) with user and contributor guides

### Changed

- N/A (initial release)

### Fixed

- N/A (initial release)

[Unreleased]: https://github.com/ditschi/repo-env/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/ditschi/repo-env/releases/tag/v0.1.0
