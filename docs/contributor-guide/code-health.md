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
   `git archive` and scored the same way. Renamed files are compared with their old path.
3. The **repo score must not drop** below `min(target, base repo score)`. Once the repo is at the
   target, adding or deleting healthy files (≥ 9.5) may move the mean slightly without failing.

Changed files include untracked files, except under pre-commit (`PRE_COMMIT` is set there): only the
staged state is committed, so unrelated scratch files must not block it. A missing or failing
analyzer is a tool error (exit 2), never "no findings". Unknown smell names in a suppression produce
a warning.
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

## Steckbrief Code Health

### 1. Messumfang: was zählt, was nicht, mit Begründung

- **Gemessen:** alle Python-Dateien unter `src/`, `tests/` und `tools/` sowie `noxfile.py` (155 Dateien, rund 11 600 Codezeilen). Tests zählen mit, weil Agents sie genauso ändern wie Produktivcode. Der Checker bewertet sich selbst mit.
- **Ausgenommen:**
  - `src/repoenv/_version.py`: wird von hatch-vcs generiert.
  - `tests/*/resources/*` und `tests/fixtures/*`: Testdaten, kein Code.
  - Markdown, YAML und Shell. Das Repo ist ein reines Python-CLI, die übrigen Dateien sind Konfiguration oder Doku.
- **LOC** zählt nur Codezeilen, also ohne Leerzeilen, Kommentare und Docstrings. Kommentare sollen den Score nicht verschlechtern.

### 2. Tools und Versionen, je Sprache

Nur Python, alle Tools frei bzw. OSS:

| Tool | Version | Rolle | Neu? |
|---|---|---|---|
| ruff | 0.15.20 | C901 (mccabe), PLR0913 (Argumente), PLR1702 (Verschachtelung) | vorhanden |
| pylint `symilar` | 4.0.6 | Duplikate (gleiche Engine wie R0801 in `nox -s duplicates`) | vorhanden |
| complexipy | 9.0.0 (MIT) | kognitive Komplexität | **neu**, kein vorhandener Linter liefert sie |
| Python `ast`/`tokenize` | stdlib | eigene Checks (siehe 3) | — |
| tomli | ≥ 2.0 | TOML nur auf Python 3.10 | neu, winzig |

- **flake8:** Sein mccabe-Plugin würde dieselbe Kennzahl wie ruff C901 messen, deshalb wird es nicht zusätzlich eingesetzt.
- **vulture:** Toter Code ist kein CodeScene-Kriterium. vulture bleibt als eigenes Gate (`dead_code`).
- **lizard, radon/xenon, jscpd:** Nicht übernommen. Sie hätten ruff/pylint nur dupliziert, jscpd bräuchte außerdem Node.

### 3. Abgebildete Smells, mit Zuordnung zu den CodeScene-Kriterien; nicht abgebildete mit Grund

| CodeScene-Kriterium | Smell hier | Quelle |
|---|---|---|
| Complex Method | `complex-method` | ruff C901 |
| Large Method | `large-method` | AST (Codezeilen) |
| Brain Method | `brain-method` | abgeleitet: complex + large |
| Primitive Obsession / viele Argumente | `primitive-obsession`, `many-arguments` | AST / ruff PLR0913 |
| DRY Violations | `code-duplication` | pylint symilar |
| Nested Complexity | `nested-complexity` | ruff PLR1702 |
| Bumpy Road | `bumpy-road` | AST |
| Complex Conditional | `complex-conditional` | AST (alle Bedingungen, nicht nur `if` wie ruff PLR0916) |
| (kognitive Komplexität, Zusatz) | `cognitive-complexity` | complexipy |
| Lines of Code | `large-file` | tokenize |
| Brain/God Class | `brain-class` | abgeleitet |
| Low Cohesion | `low-cohesion` (LCOM4 je Klasse) | AST |
| (viele Funktionen, Zusatz) | `many-functions` | AST |
| Large Assertion Blocks | `large-assertion-block` | AST |
| Duplicated Assertion Blocks | `duplicated-assertion-block` | AST |

Nicht abgebildet:
- **Developer Congestion** und **Complex Code by Former Contributors:** Das sind Git-Verhaltensmetriken, keine Codeeigenschaften. Bei einem Ein-Personen-Repo sagen sie nichts aus.
- **LCOM4 für Module aus freien Funktionen:** CLI-Module mit unabhängigen Commands wären dort immer „inkohäsiv“.
- **Duplikate in Tests:** werden nicht gemessen, sie sind über die Assertion-Block-Smells abgedeckt (Annahme).

### 4. Schwellen, Gewichte und Score-Formel

- **Formel:** Jede Datei startet bei 10.0, jeder Smell zieht `weight × min(cap, value / max)` ab, das Minimum ist 1.0.
- **Repo-Score:** LOC-gewichteter Mittelwert; die schlechteste Datei wird zusätzlich ausgewiesen.
- **Konfiguration:** alle Werte in `code-health.toml` (versioniert, `version = 1`); die Tabelle oben unter „Score“ nennt die Defaults.
- **Wie CodeScene:** CC > 9, Verschachtelung ≥ 4, Funktion > 70 Zeilen, Bumpy Road ab 2 Bumps der Tiefe 2, Datei > 600 Zeilen, Assertion-Blöcke ab 4.
- **Lockerer als die CodeScene-Standardwerte für Python** (nachträglich vom Owner bestätigt, Checker bewusst nicht mehr angepasst):
  - Argumente: hier ab 5 markiert, CodeScene ab 4.
  - Complex Conditional: hier ab 4 `and`/`or`, CodeScene ab 2 Verzweigungen.
  - Primitive Obsession: hier ≥ 5 primitive Parameter (absolut), CodeScene 30 % Anteil.
  - Duplikate: hier ≥ 6 identische Zeilen, CodeScene 10 Zeilen bei 75 % Ähnlichkeit.
  - Duplizierte Assertion-Blöcke: hier ab 3 Assertions, CodeScene 4.
- **Gegenprobe mit CodeScene-Schwellen** (Argumente max 3, Conditional max 1, Duplikate ab 10 Zeilen; Prozent- und Ähnlichkeitsregeln nicht nachgebildet): Repo **9.44** statt 9.97, 22 Dateien unter 9.5. Schlechteste Datei: `tests/integration/support/fake_scm.py` mit 5.40. Treffer: 43 × `many-arguments` (4 Argumente), 24 × `complex-conditional` (2–3 Operatoren).
- **Annahmen:**
  - Large Method > 70 Zeilen, kognitive Komplexität > 15, ≥ 2 Bumps.
  - Datei > 600 Codezeilen, > 40 Funktionen, LCOM4 ≥ 3.
  - ≥ 4 Assertions am Stück, Duplikat-Blöcke ab 3 Assertions, Code-Duplikate ab 6 Zeilen.
  - Gewichte zwischen 0.2 (Assertion-Block) und 1.5 (Brain Method/Class).
- **Ausgenommen von Argument-Zählungen** (vom Framework erzwungene Signaturen):
  - `typer.Option`/`typer.Argument`-Parameter;
  - pytest-injizierte Parameter von `test_*`-Funktionen und Fixtures.

### 5. Bedienung: Befehl, Ausgabeformat, --changed-Modus, Laufzeit

- **Befehl:** `nox -s code-health [-- --changed [BASE]] [--json] [--update-baseline]`. Ohne nox: `python -m tools.code_health`.
- **Ausgabe:** Tabelle mit Score, LOC und Datei; darunter die Smells mit Zeile, Messwert, Schwelle und Abzug.
- **`--json`:** liefert `repo_score`, `worst_file`, `files[].smells[]` und `gate.violations`.
- **`--changed`:** prüft nur die Dateien, die sich gegenüber BASE geändert haben. BASE ist standardmäßig die merge-base mit `origin/main`, sonst `main` oder `HEAD`. Der Basis-Stand wird per `git archive` exportiert und parallel bewertet.
- **Laufzeit:** Vollscan ca. 5 s, `--changed` ca. 5–7 s. Den größten Anteil hat pylint symilar mit rund 4,5 s; ruff, complexipy und die AST-Checks brauchen zusammen unter 1 s.
- **Exit-Codes:** 0 bestanden, 1 Gate verletzt, 2 Tool-Fehler.

### 6. Gate: Hook, CI, Ratchet und Baseline, Suppressions

- **Pre-commit:** der Hook `code-health` (`--changed HEAD`).
- **CI:** im PR-Job „Quality gates“ als `--changed <PR-Base-SHA>`, mit `fetch-depth: 0`.
- **Regeln:**
  - Geänderte Dateien müssen ≥ 9.5 haben.
  - Keine Datei darf schlechter werden als in der Basis.
  - Der Repo-Score darf nicht unter `min(Ziel, Basis-Score)` sinken.
  - Ein Vollscan prüft gegen `code-health-baseline.json`.
- **Ratchet:** Die Baseline hielt anfangs 33 Dateien unter 9.5 fest. Seit dem Refactoring ist sie **leer**, es ist also keine Datei mehr unter 9.5 zugelassen.
- **Suppressions:** nur inline als `# code-health: ignore[<smell>] -- <Begründung ≥ 10 Zeichen>`. Ohne Begründung werden sie ignoriert und erzeugen eine Warnung. Unterdrückte Smells bleiben im Report sichtbar. Aktuell gibt es **0** Suppressions.

### 7. Ergebnis: Score vorher und nachher, schlechteste Dateien, verbleibende Smells

- **Vorher** (`main`, 138 Dateien): Repo **8.93**, 33 Dateien unter 9.5.
  - Schlechteste: `services/environment_service.py` 1.00, `services/clone_service.py` 6.35, `cli/commands/add.py` 6.92, `cli/commands/create.py` 7.26.
- **Nachher** (155 Dateien inkl. Checker und neuer Tests): Repo **9.97**, **0** Dateien unter 9.5.
  - Schlechteste: `tests/integration/git/test_create_command_git_flow.py` mit 9.60.
- **Verbleibende Smells** (15 Dateien, alle ≥ 9.6):
  - je einmal `many-arguments` mit 5 Argumenten in `git_adapter.add_worktree`, `scm/rest.request`, `repo_url.build_clone_url` und einem Test-Helper;
  - einmal `cognitive-complexity` 16 in `rm_command`;
  - 9 große Assertion-Blöcke in Integrationstests.
- **Hotspots:** Die größten haben jetzt alle 10.0 (environment_service, clone_service, pr_service, create/add/merge, resolve, didyoumean, config).
- **Tests:** Alle Unit- und Integrationstests sind grün, das Verhalten ist unverändert.

### 8. Skills: geprüfte und übernommene Skills

- **Geprüft:** Die SKILL.md-Dateien von 16 skills.sh-Treffern wurden gelesen.
- **Shortlist:**
  - `l-mb/python-refactoring-skills@py-complexity` (empfohlen, ohne dessen Setup-Schritt, der Claude-Settings ändert)
  - `wondelai/skills@refactoring-patterns` (empfohlen)
  - `l-mb/…@py-refactor`
  - `l-mb/…@py-code-health`
  - `github/awesome-copilot@refactor-method-complexity-reduce`
  - `kucherenko/jscpd@dry-refactoring`
  - `fastapi/typer@typer`
- **Ausgeschieden:** `*@codehealth-mcp`, weil es ein kostenpflichtiges Token braucht.
- **Übernommen:** bisher keine. Installiert wird erst nach Freigabe durch den Owner.

### 9. Erfahrungen

- **Gut:**
  - Die vorhandenen Linter sind über `--config`-Overrides wiederverwendet. Es gibt keine zweite Konfiguration und keine doppelte Messung.
  - Der Basisvergleich per `git archive` macht „nicht schlechter werden“ ohne Baseline-Merge-Konflikte prüfbar.
  - `--json` mit Zeilennummern und Abzug pro Smell eignet sich gut für Agents: Vier parallele Agents haben die Hotspots in getrennten Datei-Gruppen ohne Rückfragen auf 10 gebracht.
- **Schwierig:**
  - complexipy (Rust-Extension) ist nicht thread-safe; es gab Segfaults, bis die Aufrufe serialisiert wurden.
  - pylint symilar ist der Laufzeit-Engpass.
  - Agents neigen zum Metrik-Gaming. Beispiele: `**kwargs: Unpack[TypedDict]` statt Parameterobjekt, oder `staticmethod`-Aliase gegen LCOM4. Beides wurde im Review zurückgebaut. Ein Review bleibt also nötig.
  - Unsere additive Formel ist strenger als CodeScene: Eine Datei mit vielen Smells fällt bis auf 1.0.
- **Übertragbar:**
  - Formel „Start 10, gewichtete Abzüge, LOC-gewichteter Mittelwert“;
  - Gate-Logik aus Basisvergleich und Ratchet;
  - Suppressions nur mit Begründung;
  - AST-Checks für Bumpy Road, Assertion-Blöcke und LCOM4 bei anderen Python-Repos.
- **Projektspezifisch:**
  - Die Typer-Ausnahme, weil CLI-Optionen als Funktionsparameter deklariert werden.
  - Die pytest-Fixture-Ausnahme.
  - Duplikat-Messung nur in `src/` und `tools/`.
