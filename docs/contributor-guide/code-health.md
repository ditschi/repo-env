# Code Health

`nox -s code-health` computes a **CodeScene-inspired code health score from 1 to 10** for every
Python file. It uses free/OSS tools only. This is **not** the proprietary CodeScene score: it
reuses the concepts of [CodeScene Code Health](https://codescene.io/docs/guides/technical/code-health.html)
and the "AI-Ready Code" white paper (A. Tornhill, 2026). The paper reports that AI-generated changes
to unhealthy code have at least 60 % more defects, and it only studied code with health 7 or higher.
Healthy code is a precondition for agents to work reliably. Tests, coverage and review are still
required.

| Band | Score |
|------|-------|
| green (healthy) | ≥ 9.0 |
| yellow | 4.0 – 8.9 |
| red | < 4.0 |

**Repo target: ≥ 9.5, aiming for 10.**

## Usage

```sh
nox -s code-health                                 # all files: table + gate against the baseline
nox -s code-health -- --changed                    # only files changed vs merge-base with origin/main
nox -s code-health -- --changed HEAD               # uncommitted changes only (what pre-commit runs)
nox -s code-health -- --changed origin/main --json # machine-readable, for agents and CI
nox -s code-health -- --update-baseline            # rewrite the ratchet baseline
```

Without nox: `python -m tools.code_health …`. You need the `code-quality` extra installed.

Exit codes: `0` gate passed, `1` gate failed, `2` tool error (for example a missing analyzer).

## Gate

The gate runs in pre-commit (`--changed HEAD`) and in the PR quality job (`--changed <PR base>`).

1. Every changed file must score **≥ 9.5** (`score.target`).
2. A changed file must **not get worse** than in the base commit. The base tree is exported with
   `git archive` and scored the same way.
3. The **repo score must not drop**.
4. **Ratchet baseline** (`code-health-baseline.json`): files that already scored below 9.5 when the
   gate was introduced are grandfathered at their recorded score. Rule 2 still applies to them, so
   any change must keep or improve them. After improving such a file, run `--update-baseline` and
   commit the tighter values. A baseline score may only go up.

A full run (without `--changed`) checks every file against target or baseline. It has no base
comparison.

## Score

Every file starts at `10.0`. Each smell subtracts `weight × min(cap, value / max)`, where `value` is
the measured metric and `max` the largest allowed value. A smell is reported when
`value > max`. The minimum file score is `1.0`. The repo score is the **LOC-weighted mean**
(code lines without blank lines, comments or docstrings). The worst file is reported separately.

Thresholds and weights live in [`code-health.toml`](https://github.com/ditschi/repo-env/blob/main/code-health.toml),
which is versioned and reviewed like code.

| Smell | Level | Source | Default (`max`) | Origin |
|-------|-------|--------|-----------------|--------|
| complex-method | function | ruff `C901` (mccabe) | CC ≤ 9 | CodeScene |
| large-method | function | AST | ≤ 70 code lines | assumption |
| brain-method | function | derived | complex **and** large | assumption |
| many-arguments | function | ruff `PLR0913` | ≤ 4 arguments | CodeScene (≥ 5 flagged) |
| primitive-obsession | function | AST | ≤ 4 `str/int/float/bool/bytes` params | assumption |
| code-duplication | function | pylint `symilar` (engine of R0801) | ≤ 5 similar lines | assumption (matches `nox -s duplicates`) |
| cognitive-complexity | implementation | complexipy | ≤ 15 | assumption (SonarSource default) |
| nested-complexity | implementation | ruff `PLR1702` | depth ≤ 3 | CodeScene (≥ 4 flagged) |
| bumpy-road | implementation | AST | ≤ 1 bump (block nested ≥ 2 deep) | assumption |
| complex-conditional | implementation | AST | ≤ 3 `and`/`or` per condition | CodeScene (≥ 4 flagged) |
| large-file | module | tokenize | ≤ 600 code lines | assumption |
| many-functions | module | AST | ≤ 40 functions | assumption |
| low-cohesion | module | AST, LCOM4 per class (≥ 4 methods) | LCOM4 ≤ 2 | assumption |
| brain-class | module | derived | brain method + (≥ 15 methods or > 300 lines) | assumption |
| large-assertion-block | tests | AST | ≤ 3 consecutive assertions | assumption |
| duplicated-assertion-block | tests | AST | identical block of ≥ 3 assertions repeated | assumption |

### Reused linters, no duplicated checks

* **ruff** supplies cyclomatic complexity (C901), argument count (PLR0913) and nesting depth
  (PLR1702). The checker calls ruff with its own thresholds through `--config` overrides, so
  `ruff.toml` stays unchanged.
* **pylint**'s similarity engine (`symilar`, the engine behind R0801) supplies duplicated code. The
  existing `nox -s duplicates` gate stays as it is.
* **complexipy** (MIT) adds cognitive complexity, which no existing linter provides.
* **Own AST checks** cover what no free tool provides in CodeScene's form: bumpy road, complex
  conditionals in any condition (not only `if`), LCOM4, primitive obsession, assertion blocks and
  large methods measured in code lines.

### Conventions (assumptions)

* Parameters declared as CLI options (`typer.Option`/`typer.Argument`, see `[cli]`) and
  pytest-injected fixture parameters of `test_*` functions and fixtures are not counted as
  arguments. The framework forces that signature.
* Duplicate detection runs on `src/` and `tools/`. Duplication in tests is covered by the
  assertion-block smells.

## Suppressions

Use suppressions only as an inline comment with a reason of at least 10 characters. Put it on the
line of the smell, the line above it, or the `def` line of the enclosing function:

```python
def parse(token):  # code-health: ignore[complex-method] -- mirrors the grammar table 1:1, see RFC 3986
```

The checker ignores a suppression without a reason and prints a warning. **Fix smells instead of
suppressing them.** Suppressed smells stay visible in the report.

## Working with agents

Run `nox -s code-health -- --changed --json` before every commit. The JSON lists each changed file
with `score`, `smells[]` (`kind`, `line`, `value`, `max`, `deduction`) and `gate.violations`.
Refactor until `gate.passed` is `true`.
