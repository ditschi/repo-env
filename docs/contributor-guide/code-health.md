# Code Health

Code health is measured with **[ai-health](https://github.com/epatel/ai-health)** (MIT, deterministic,
no AI involved) and gated in pre-commit and CI. ai-health estimates a CodeScene-style score from 1 to
10 per file and per project. It is **not** the proprietary CodeScene score. The concepts come from
[CodeScene Code Health](https://codescene.io/docs/guides/technical/code-health.html) and the
"AI-Ready Code" white paper (A. Tornhill, 2026). The paper reports that AI-generated changes to
unhealthy code have at least 60 % more defects; it only studied code with health 7 or higher.
Healthy code is a precondition for agents to work reliably. Tests, coverage and review are still
required.

| Band | Score |
|------|-------|
| healthy | ≥ 9 |
| warning | 4 – 9 |
| alert | < 4 |

**Goal: 10, meaning no findings.** 9.5 is only the minimum on the way there.

## Usage

```sh
nox -s code-health                                  # report (scan) + gate (delta vs merge-base with origin/main)
nox -s code-health -- delta                         # working tree (incl. untracked) vs HEAD
nox -s code-health -- delta --format json           # machine-readable, for agents
nox -s code-health -- scan src --format markdown    # report for one component
nox -s code-health -- scan . --report               # full report in AI-HEALTH.md
nox -s code-health-components                       # component scores (repo/src/tests): merge-base vs HEAD
```

The nox session always passes `--config <repo>/.aihealth.toml`. Without it, `aihealth scan <dir>`
would silently fall back to the defaults. ai-health needs Python ≥ 3.11, so the session runs on 3.12.
Its version is pinned to a commit in exactly one place: the `code-health` dependency group in
`pyproject.toml`, locked in `uv.lock`.

## Profile "strict" (`.aihealth.toml`)

`.aihealth.toml` is the single place to tune the profile (confirmed by the owner, Q15). All keys not
listed use the ai-health defaults of the pinned release.

| Key | Value | Default | Meaning |
|---|---|---|---|
| `thresholds.large_file` | 600 | 1000 | code lines per file |
| `thresholds.primitive_obsession` | 0.3 | 0.6 | share of typed params that are primitive |
| `score.decay` | 8 | 15 | steeper score curve |
| `score.symbol_cap` | 4 | 4 | |
| `score.density_loc` | 100000 | 300 | large files are not relieved through finding density |
| `delta.tolerance` | 0.0 | 0.1 | any degradation fails the gate |
| `scan.exclude` | `tools/code_health/*` | – | the temporary own checker (below) is not scored |

## Gate

| Where | Command | Fails when |
|---|---|---|
| pre-commit `code-health` | `aihealth delta --config .aihealth.toml --staged` | a staged file got worse, or a new file has a finding |
| PR CI, quality job | `delta --base "$(git merge-base origin/<base> HEAD)" --head HEAD` | same, for the whole PR |
| PR CI, quality job | `nox -s code-health-components -- origin/<base>` | the project score of `.`, `src` or `tests` drops |
| PR CI, job summary | `scan . --format markdown` | report only |

The CI checks against the **merge-base**, so changes that landed on `main` later are not counted
against the branch. The tree-sitter grammars (~30 MB, `~/.cache/tree-sitter-language-pack`) are
cached in CI.

### Suppressions

ai-health only supports file-wide suppressions. Use them only where an interface imposes the
signature (CLI/JSON boundaries). The reason must follow ` -- `; without that separator ai-health
silently ignores the suppression. The pre-commit hook `aihealth-suppression-reason` enforces a
reason of at least 10 characters.

```python
# aihealth: disable=primitive_obsession -- typer CLI boundary: options are str/list[str] parameters
```

Current suppressions: `src/repoenv/cli/commands/add.py` and `merge.py` (primitive_obsession, typer
CLI boundary).

### One source per smell

Structural rules are switched off in the linters (owner decision Q9). ruff has no C90/PLR09xx, and
pylint has its design checks (too-many-*, too-many-lines) disabled and no `fail-under` score gate.
ruff is the single linter and formatter (Q8, replaces black/isort/flake8). The pylint sessions
`duplicates` (R0801) and `cyclic_imports` still run; R0801 overlaps with ai-health's duplication
smell and can go once the ai-health gate is established.

## Working with agents

Run `nox -s code-health -- delta --format json` (or the ai-health MCP server) before every commit.
Fix findings instead of suppressing them. The output lists every new or worsened smell with
`path:line` and a fix hint.

## Own checker (cross-check, temporary)

`tools/code_health` (`nox -s code-health-own`, config `code-health.toml`) was built first, from
ruff, complexipy, pylint symilar and AST checks. It stays as a cross-check until the ai-health gate
runs green in CI, then it can be removed. Its thresholds are looser than the CodeScene defaults
(see the Steckbrief, section 4).

### Gate

The gate runs in pre-commit (`--changed HEAD`) and in the PR quality job (`--changed <PR base>`).

1. Every changed file must score **≥ 9.5** (`score.target`).
2. A changed file must **not get worse** than in the base commit. The base tree is exported with
   `git archive` and scored the same way. Renamed files are compared with their old path.
3. The **repo score must not drop** below `min(target, base repo score)`. Once the repo is at the
   target, adding or deleting healthy files (≥ 9.5) may move the mean slightly without failing.

Changed files include untracked files, except under pre-commit (`PRE_COMMIT` is set there). A
missing or failing analyzer is a tool error (exit 2). Unknown smell names in a suppression produce
a warning.
4. **Ratchet baseline** (`code-health-baseline.json`): files that already scored below 9.5 when the
   gate was introduced are grandfathered at their recorded score. Rule 2 still applies to them, so
   any change must keep or improve them. After improving such a file, run `--update-baseline` and
   commit the tighter values. A baseline score may only go up.

A full run (without `--changed`) checks every file against target or baseline. It has no base
comparison.

### Score

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
| many-arguments | function | ruff `PLR0913` | ≤ 4 arguments | looser than CodeScene (4) |
| primitive-obsession | function | AST | ≤ 4 `str/int/float/bool/bytes` params | assumption |
| code-duplication | function | pylint `symilar` (engine of R0801) | ≤ 5 similar lines | assumption (matches `nox -s duplicates`) |
| cognitive-complexity | implementation | complexipy | ≤ 15 | assumption (SonarSource default) |
| nested-complexity | implementation | ruff `PLR1702` | depth ≤ 3 | CodeScene (≥ 4 flagged) |
| bumpy-road | implementation | AST | ≤ 1 bump (block nested ≥ 2 deep) | assumption |
| complex-conditional | implementation | AST | ≤ 3 `and`/`or` per condition | looser than CodeScene (2 branches) |
| large-file | module | tokenize | ≤ 600 code lines | assumption |
| many-functions | module | AST | ≤ 40 functions | assumption |
| low-cohesion | module | AST, LCOM4 per class (≥ 4 methods) | LCOM4 ≤ 2 | assumption |
| brain-class | module | derived | brain method + (≥ 15 methods or > 300 lines) | assumption |
| large-assertion-block | tests | AST | ≤ 3 consecutive assertions | assumption |
| duplicated-assertion-block | tests | AST | identical block of ≥ 3 assertions repeated | assumption |

#### Reused linters, no duplicated checks

* **ruff** supplies cyclomatic complexity (C901), argument count (PLR0913) and nesting depth
  (PLR1702). The checker calls ruff with its own thresholds through `--config` overrides, so
  `ruff.toml` stays unchanged.
* **pylint**'s similarity engine (`symilar`, the engine behind R0801) supplies duplicated code. The
  existing `nox -s duplicates` gate stays as it is.
* **complexipy** (MIT) adds cognitive complexity, which no existing linter provides.
* **Own AST checks** cover what no free tool provides in CodeScene's form: bumpy road, complex
  conditionals in any condition (not only `if`), LCOM4, primitive obsession, assertion blocks and
  large methods measured in code lines.

#### Conventions (assumptions)

* Parameters declared as CLI options (`typer.Option`/`typer.Argument`, see `[cli]`) and
  pytest-injected fixture parameters of `test_*` functions and fixtures are not counted as
  arguments. The framework forces that signature.
* Duplicate detection runs on `src/` and `tools/`. Duplication in tests is covered by the
  assertion-block smells.

### Suppressions

Use suppressions only as an inline comment with a reason of at least 10 characters. Put it on the
line of the smell, the line above it, or the `def` line of the enclosing function:

```python
def parse(token):  # code-health: ignore[complex-method] -- mirrors the grammar table 1:1, see RFC 3986
```

The checker ignores a suppression without a reason and prints a warning. **Fix smells instead of
suppressing them.** Suppressed smells stay visible in the report.

### Working with agents (own checker)

Optional cross-check: `nox -s code-health-own -- --changed --json`. The JSON lists each changed file
with `score`, `smells[]` (`kind`, `line`, `value`, `max`, `deduction`) and `gate.violations`.
The own checker's gate (`gate.passed`) still runs in pre-commit and CI until it is removed.


## Steckbrief Code Health

### 1. Messumfang: was zählt, was nicht, mit Begründung

- **ai-health bewertet** alle von ihm unterstützten Dateien im Repo: Python unter `src/`, `tests/` und `noxfile.py`, dazu Shell-Skripte. Stand: 145 Dateien, rund 10 750 Codezeilen. Tests zählen mit, weil Agents sie genauso ändern wie Produktivcode.
- **Ausgenommen sind:**
  - die ai-health-Default-Excludes, also generierte Dateien und Build-Ordner;
  - `tools/code_health/*`: Der eigene Checker ist eine befristete Gegenprobe und wird entfernt, sobald das ai-health-Gate in der CI grün läuft.
- **Komponenten** für den Score-Vergleich: das ganze Repo (`.`), `src` und `tests`.

### 2. Tools und Versionen, je Sprache

| Tool | Version | Rolle |
|---|---|---|
| ai-health | 0.4.0, gepinnt auf Commit `033d186` | **einzige Quelle** für Smells und Score (tree-sitter-basiert, Python ≥ 3.11) |
| ruff | 0.15.x | einziger Linter und Formatter (E/W/F/I und `ruff format`); keine Strukturregeln |
| pylint | 4.0.x | nur R0801 (Duplikate, auslaufend) und R0401 (zyklische Importe), kein Score-Gate |
| eigener Checker (`tools/code_health`) | – | Gegenprobe: ruff C901/PLR0913/PLR1702, complexipy 9.0, pylint symilar, AST |

- black, isort und flake8 sind entfallen (Q8).
- Die Versionsangabe für ai-health steht nur in der Dependency-Group `code-health` in `pyproject.toml` und ist in `uv.lock` festgeschrieben.

### 3. Abgebildete Smells, mit Zuordnung zu den CodeScene-Kriterien; nicht abgebildete mit Grund

- **Von ai-health abgebildet:** Brain Method, Large Method, Complex Method, Cognitive Complexity, Deep Nesting, Bumpy Road, Excess Arguments, Complex Conditional, Large File, Low Cohesion (LCOM4), Primitive Obsession, Code Duplication.
- **Nicht abgebildet:**
  - **Large/Duplicated Assertion Blocks:** Nur der eigene Checker misst sie, weil ai-health sie nicht kennt. Duplizierte Tests fängt aber die Duplikat-Erkennung von ai-health.
  - **Developer Congestion und Complex Code by Former Contributors:** Das sind Git-Verhaltensmetriken; in einem Ein-Personen-Repo sagen sie nichts aus.
  - **Brain Class:** ai-health hat dafür keinen eigenen Smell. Low Cohesion und Large File decken den Großteil ab.

### 4. Schwellen, Gewichte und Score-Formel

- **ai-health, Profil strict** (vom Owner bestätigt):
  - eigene Werte: large_file 600, primitive_obsession 0.3, decay 8, symbol_cap 4, density_loc 100000, delta.tolerance 0;
  - ai-health-Defaults für den Rest: Methode > 70 Zeilen, CC > 9, kognitive Komplexität > 15, Verschachtelung ≥ 4, Bumpy Road ≥ 2 Bumps, Argumente > 4, Complex Conditional ≥ 2 Operatoren, LCOM4 ≥ 3, Duplikate ab 6 Zeilen bzw. 50 Tokens.
- **Formel ai-health:**
  - Je Smell wird `weight × severity` aufsummiert, mit einem Deckel je Symbol (`symbol_cap`).
  - Daraus folgt der Score über eine Abklingkurve: `decay` 8 macht sie steiler.
  - Der Projekt-Score ist der LOC-gewichtete Mittelwert.
  - Details stehen in `scoring.py` des gepinnten Releases.
- **Eigener Checker:**
  - Start bei 10, Abzug `weight × min(cap, value/max)`, Minimum 1, LOC-gewichtet (Konfiguration: `code-health.toml`).
  - Er ist an mehreren Stellen lockerer als CodeScene: Argumente ab 5 statt 4, Bedingungen ab 4 statt 2 Operatoren, Primitive Obsession absolut statt 30 %, Duplikate ab 6 identischen Zeilen statt 10 Zeilen bei 75 % Ähnlichkeit.

### 5. Bedienung: Befehl, Ausgabeformat, --changed-Modus, Laufzeit

- **Befehl:** `nox -s code-health`. Ohne Argumente erzeugt es den Bericht (`scan`) und prüft `delta` gegen die Merge-Base. Argumente reicht es an `aihealth` weiter.
- **Komponenten-Vergleich:** `nox -s code-health-components`.
- **Ausgabe:** Text, Markdown oder JSON (`--format`); `scan . --report` erzeugt einen vollständigen Bericht.
- **Nur geänderte Dateien:** `delta` (Working Tree gegen HEAD), `delta --staged` (pre-commit) oder `delta --base <ref> --head HEAD` (CI).
- **Laufzeit:** `scan` ca. 1,6 s, `delta` gegen die Merge-Base ca. 4 s, pre-commit-Hook ca. 0,3 s (aus dem uv-Cache).
- Beim ersten Lauf lädt tree-sitter rund 30 MB Grammatiken; in der CI werden sie gecacht.

### 6. Gate: Hook, CI, Ratchet und Baseline, Suppressions

- **pre-commit:**
  - `aihealth delta --staged` (Toleranz 0; neue Dateien dürfen keinen Fund haben);
  - pygrep-Hook für die Begründung bei Suppressions.
- **CI (PR-Quality-Job):**
  - `delta` gegen die Merge-Base;
  - Komponenten-Score von Merge-Base und Head; kein Score von `.`, `src` oder `tests` darf sinken;
  - `scan` als Bericht in der Job-Summary.
- **Ratchet:** ai-health braucht keine Baseline-Datei. Das `delta` gegen die Basis ist die Ratsche. Die eigene Baseline-Datei (`code-health-baseline.json`) ist leer.
- **Suppressions:**
  - nur dateiweit als `# aihealth: disable=<smell> -- <Grund>`;
  - aktuell 2, nämlich `primitive_obsession` in `cli/commands/add.py` und `merge.py`, wegen der typer-CLI-Grenze.

### 7. Ergebnis: Score vorher und nachher, schlechteste Dateien, verbleibende Smells

| Komponente | `main` (ai-health strict) | Branch |
|---|---|---|
| Repo | 6.87 | **7.82** |
| `src` | 7.32 | **8.60** |
| `tests` | 6.31 | **7.03** |

- **Gate:** `delta` gegen `main` meldet IMPROVED, also keine Datei verschlechtert.
- **Eigener Checker:** von 8.93 auf 9.97, 0 Dateien unter 9.5.
- **Schlechteste Dateien (ai-health strict):**
  - `tests/integration/git/test_repair.py` 2.37 und `test_worktree_conflicts.py` 2.58 (Duplikate);
  - `tests/integration/cli/test_merge_branches.py` 3.64;
  - `tests/integration/support/fake_scm.py` 4.13.
- **Verbleibende Funde** (62 Dateien):
  - Duplikate 81×, vor allem in Tests;
  - Excess Arguments 31×, auch durch pytest-Fixtures, die ai-health als Parameter zählt;
  - Primitive Obsession 22×;
  - Complex Method 20×;
  - Complex Conditional 17×;
  - Cognitive Complexity 1×.
- **Davon in `src`:** Primitive Obsession 17×, Complex Method 16×, Complex Conditional 12×, Excess Arguments 10×, Duplikate 3×, Cognitive Complexity 1×.
- Die Refactorings in Richtung 10 brauchen die Freigabe des Owners.

### 8. Skills: geprüfte und übernommene Skills

- **Geprüft:** Die SKILL.md-Dateien von 16 skills.sh-Treffern wurden gelesen.
- **Empfohlen:**
  - `l-mb/python-refactoring-skills@py-complexity`, ohne dessen Setup-Schritt, der Claude-Settings ändert;
  - `wondelai/skills@refactoring-patterns`.
- **Ausgeschieden:** `*@codehealth-mcp`, weil es ein kostenpflichtiges Token braucht.
- **Übernommen:** bisher keine, es fehlt noch die Freigabe.
- ai-health bringt selbst einen MCP-Server und Claude-Code-Hooks mit (`review_changes`, `preview_change`). Sie sind eine Alternative zu Skills, aber noch nicht eingerichtet.

### 9. Erfahrungen

- **Gut:**
  - ai-health läuft deterministisch und schnell.
  - `delta` gegen die Merge-Base ersetzt die Baseline-Datei.
  - Die Fix-Hinweise mit `path:line` helfen Agents direkt.
  - Der Einbau über eine uv-Dependency-Group hält die Version an einer Stelle und läuft offline aus dem Cache.
- **Schwierig:**
  - **Werkzeug-Abhängigkeit:** Refactorings, die für den eigenen Checker gemacht wurden, waren unter ai-health teils schlechter. Beispiele: zusammengefasste Assertions erzeugten neue Duplikate, und ausgelagerte Helfer trieben die Primitive-Obsession-Quote über die Mindestzahl von 10 Parametern. Man sollte sich deshalb früh auf ein Werkzeug festlegen.
  - **Stille Fallstricke:** Ohne `--config` fällt `scan <unterordner>` still auf die Defaults zurück, und eine Suppression ohne ` -- ` greift still nicht.
  - **pytest-Fixtures:** ai-health zählt sie als Argumente. Abhilfe ist `@pytest.mark.usefixtures` für Fixtures, die nur Seiteneffekte haben.
  - **Metrik-Gaming durch Agents:** Agents umgehen Metriken gern, etwa mit `**kwargs` oder Alias-Tricks. Ein Review bleibt nötig.
- **Übertragbar:**
  - Pin auf einen Commit;
  - nox-Session mit festem `--config`;
  - `delta` gegen die Merge-Base in der CI;
  - Komponenten-Vergleich;
  - pygrep-Hook für Suppressions;
  - eine Quelle je Smell, also die Strukturregeln der Linter aus.
- **Projektspezifisch:**
  - Suppressions für typer-CLI-Module;
  - pfadgefilterte PR-Jobs: `.aihealth.toml` steht im Filter.
