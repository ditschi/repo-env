## Summary

<!-- PR title must follow Conventional Commits: type(scope): summary -->
<!-- Examples:                                                          -->
<!--   feat(cli): add --parallel flag to renv run                      -->
<!--   fix(adapters/git): handle detached HEAD state                   -->
<!--   docs: add configuration reference                               -->
<!--   ci: add multi-Python test matrix                                -->

_Describe what this PR does and why._

## Type of change

- [ ] `feat` — new feature
- [ ] `fix` — bug fix
- [ ] `docs` — documentation only
- [ ] `refactor` — code restructure, no behaviour change
- [ ] `test` — adding/fixing tests
- [ ] `ci` / `build` / `chore` — tooling / infra
- [ ] `feat!` / `fix!` — **breaking change** (also add `BREAKING CHANGE:` in footer)

## Checklist

- [ ] PR title follows [Conventional Commits](https://www.conventionalcommits.org/) (enforced by CI)
- [ ] `nox -s tests` passes locally
- [ ] New code has type hints; `nox -s check_types` passes
- [ ] New public functions have Google-style docstrings (rendered by mkdocstrings)
- [ ] If docs changed: `nox -s docs` builds without warnings
