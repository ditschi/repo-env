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
nox -s code-health                                  # delta: working tree (incl. untracked) vs HEAD
nox -s code-health -- delta --base origin/main      # all changes of a branch
nox -s code-health -- delta --format json           # machine-readable, for agents
nox -s code-health -- scan src --format markdown    # report for one component
nox -s code-health -- scan . --report               # full report in AI-HEALTH.md
nox -s code-health-tests                            # the same for tests/ (tests/.aihealth.toml), default `delta tests`
nox -s code-health-components                       # component scores (repo/src/tests): merge-base vs working tree
```

The nox sessions pass the matching `--config` to `scan` and `delta`: without it, `aihealth scan <dir>`
would read `<dir>/.aihealth.toml` and silently fall back to the defaults, and tests use their own
config. ai-health needs Python ≥ 3.11, so the session runs on 3.12.
Its version is pinned to a commit in exactly one place: the `code-health` dependency group in
`pyproject.toml`, locked in `uv.lock`.

## Profile "strict" (`.aihealth.toml`, `tests/.aihealth.toml`)

Production code uses `.aihealth.toml` (profile confirmed by the owner, Q15); it excludes `tests/`.
Test code uses `tests/.aihealth.toml`: the same profile, but **Primitive Obsession is off**
(`weights.primitive_obsession = 0`, owner decision Q18.1). ai-health has no config inheritance, so
the shared values must be kept in sync in both files. All keys not listed use the ai-health
defaults of the pinned release.

| Key | Value | Default | Meaning |
|---|---|---|---|
| `thresholds.large_file` | 600 | 1000 | code lines per file |
| `thresholds.primitive_obsession` | 0.3 | 0.6 | share of typed params that are primitive |
| `score.decay` | 8 | 15 | steeper score curve |
| `score.symbol_cap` | 4 | 4 | |
| `score.density_loc` | 100000 | 300 | large files are not relieved through finding density |
| `delta.tolerance` | 0.0 | 0.1 | any degradation fails the gate |
| `scan.exclude` (`.aihealth.toml`) | `tests/*` | – | tests are scored with `tests/.aihealth.toml` |
| `weights.primitive_obsession` (`tests/.aihealth.toml`) | 0 | 0.75 | Primitive Obsession off in tests |

## Gate

| Where | Command | Fails when |
|---|---|---|
| pre-commit `code-health`, `code-health-tests` | `aihealth delta --config .aihealth.toml --staged`, `… --config tests/.aihealth.toml --staged tests` | a staged file got worse, or a new file has a finding |
| PR CI, quality job | `delta --base "$(git merge-base origin/<base> HEAD)" --head HEAD` (once per config) | same, for the whole PR |
| PR CI, quality job | `nox -s code-health-components -- origin/<base>` | the project score of `.`, `src` or `tests` drops |
| PR CI, job summary | `scan . …` and `scan tests …` | report only |

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

Current suppressions (primitive_obsession): `src/repoenv/cli/commands/add.py` and `merge.py` (typer CLI
boundary).

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

## Steckbrief Code Health

### 1. Messumfang: was zählt, was nicht, mit Begründung

- **ai-health bewertet** alle von ihm unterstützten Dateien im Repo: Python unter `src/` und `tests/`, dazu `noxfile.py`, `vulture_whitelist.py` und `docs/assets/casts/*.py` (Shell-Skripte gibt es derzeit keine). Stand: 70 Dateien mit 5 104 Codezeilen ohne Tests, 72 Testdateien mit 4 655 Codezeilen. Tests zählen mit, weil Agents sie genauso ändern wie Produktivcode.
- **Ausgenommen sind:**
  - nur die ai-health-Default-Excludes, also generierte Dateien und Build-Ordner.
- **Zwei Konfigurationen:** Produktivcode mit `.aihealth.toml` (ohne `tests/`), Tests mit `tests/.aihealth.toml` (gleiches Profil, Primitive Obsession aus, Q18.1).
- **Komponenten** für den Score-Vergleich: `.` (alles außer `tests/`), `src` und `tests`.

### 2. Tools und Versionen, je Sprache

| Tool | Version | Rolle |
|---|---|---|
| ai-health | 0.4.0, gepinnt auf Commit `033d186` | **einzige Quelle** für Smells und Score (tree-sitter-basiert, Python ≥ 3.11) |
| ruff | 0.15.x | einziger Linter und Formatter (E/W/F/I und `ruff format`); keine Strukturregeln |
| pylint | 4.0.x | nur R0801 (Duplikate, auslaufend) und R0401 (zyklische Importe), kein Score-Gate |

- black, isort und flake8 sind entfallen (Q8).
- Die Versionsangabe für ai-health steht nur in der Dependency-Group `code-health` in `pyproject.toml` und ist in `uv.lock` festgeschrieben.

### 3. Abgebildete Smells, mit Zuordnung zu den CodeScene-Kriterien; nicht abgebildete mit Grund

- **Von ai-health abgebildet:** Brain Method, Large Method, Complex Method, Cognitive Complexity, Deep Nesting, Bumpy Road, Excess Arguments, Complex Conditional, Large File, Low Cohesion (LCOM4), Primitive Obsession, Code Duplication.
- **Nicht abgebildet:**
  - **Large/Duplicated Assertion Blocks:** ai-health kennt sie nicht; duplizierte Tests fängt aber seine Duplikat-Erkennung. Bewusst kein eigener Check (keine zusätzliche Logik).
  - **Developer Congestion und Complex Code by Former Contributors:** Das sind Git-Verhaltensmetriken; in einem Ein-Personen-Repo sagen sie nichts aus.
  - **Brain Class:** ai-health hat dafür keinen eigenen Smell. Low Cohesion und Large File decken den Großteil ab.

### 4. Schwellen, Gewichte und Score-Formel

- **ai-health, Profil strict** (vom Owner bestätigt):
  - eigene Werte: large_file 600, primitive_obsession 0.3, decay 8, symbol_cap 4, density_loc 100000, delta.tolerance 0;
  - in Tests (`tests/.aihealth.toml`) zusätzlich `weights.primitive_obsession = 0` (Q18.1); ohne Config-Vererbung stehen die gemeinsamen Werte in beiden Dateien;
  - ai-health-Defaults für den Rest: Methode > 70 Zeilen, CC > 9, kognitive Komplexität > 15, Verschachtelung ≥ 4, Bumpy Road ≥ 2 Bumps, Argumente > 4, Complex Conditional ≥ 2 Operatoren, LCOM4 ≥ 3, Duplikate ab 6 Zeilen bzw. 50 Tokens.
- **Formel ai-health:**
  - Je Smell wird `weight × severity` aufsummiert, mit einem Deckel je Symbol (`symbol_cap`).
  - Daraus folgt der Score über eine Abklingkurve: `decay` 8 macht sie steiler.
  - Der Projekt-Score ist der LOC-gewichtete Mittelwert.
  - Details stehen in `scoring.py` des gepinnten Releases.

### 5. Bedienung: Befehl, Ausgabeformat, --changed-Modus, Laufzeit

- **Befehl:** `nox -s code-health`. Die Session installiert die gepinnte Version und reicht Argumente an `aihealth` durch (Default `delta`); einzige Zutat ist `--config` für `scan`/`delta`.
- **Tests:** `nox -s code-health-tests` (gleiche Session mit `tests/.aihealth.toml`, Default `delta tests`).
- **Komponenten-Vergleich:** `nox -s code-health-components`.
- **Ausgabe:** Text, Markdown oder JSON (`--format`); `scan . --report` erzeugt einen vollständigen Bericht.
- **Nur geänderte Dateien:** `delta` (Working Tree gegen HEAD), `delta --staged` (pre-commit) oder `delta --base <ref> --head HEAD` (CI).
- **Laufzeit:** `scan` ca. 1,6 s, `delta` gegen die Merge-Base ca. 4 s, pre-commit-Hook ca. 0,3 s (aus dem uv-Cache).
- Beim ersten Lauf lädt tree-sitter rund 30 MB Grammatiken; in der CI werden sie gecacht.

### 6. Gate: Hook, CI, Ratchet und Baseline, Suppressions

- **pre-commit:**
  - `aihealth delta --staged`, je einmal pro Config (Toleranz 0; neue Dateien dürfen keinen Fund haben);
  - pygrep-Hook für die Begründung bei Suppressions.
- **CI (PR-Quality-Job):**
  - `delta` gegen die Merge-Base;
  - Komponenten-Score von Merge-Base und Arbeitsstand (in der CI identisch mit dem PR-Head); kein Score von `.`, `src` oder `tests` darf sinken;
  - `scan` als Bericht in der Job-Summary.
- **Ratchet:** ai-health braucht keine Baseline-Datei. Das `delta` gegen die Basis ist die Ratsche.
- **Suppressions:**
  - nur dateiweit als `# aihealth: disable=<smell> -- <Grund>`;
  - aktuell 2, beide `primitive_obsession` an der typer-CLI-Grenze: `cli/commands/add.py` und `merge.py`.

### 7. Ergebnis: Score vorher und nachher, schlechteste Dateien, verbleibende Smells

| Komponente | `main` (ai-health strict) | Branch |
|---|---|---|
| Repo, ohne Tests (`.aihealth.toml`) | 7.47 | **8.75** |
| `src` | 7.32 | **8.66** |
| `tests` (`tests/.aihealth.toml`) | 6.47 | **9.95** |

Werte mit der aufgeteilten Konfiguration (Tests ohne Primitive Obsession); mit nur einer Config für alles lag das Repo bei 6.87 → 9.32.

- **Gate:** `delta` gegen die Basis meldet IMPROVED, also keine Datei verschlechtert.
- **Welle 1 (Tests):** fertig. 2 Testdateien haben noch Funde, alle übrigen stehen bei 10.
- **Eigener Checker:** wurde zuerst gebaut (Score 8.93 → 9.97) und nach der Owner-Entscheidung für ai-health wieder entfernt (keine zusätzliche Logik).
- **Schlechteste Dateien (ai-health strict),** alle in `src`:
  - `cli/commands/pr.py` 6.08, `add.py` 6.46, `repair.py` 6.63, `create.py` 6.74;
  - `domain/repo_url.py` 6.78.
- **Verbleibende Funde,** fast alle in `src` (30 Dateien):
  - Primitive Obsession 18×;
  - Complex Method 15×;
  - Complex Conditional 11×;
  - Excess Arguments 10×;
  - Duplikate 5×;
  - Cognitive Complexity 1×.
- **Suppressions:** 2, `primitive_obsession` in `add.py` und `merge.py` (typer-CLI-Grenze).
- Welle 2 (`src`) braucht die Freigabe des Owners.

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
  - **Eigener Checker:** Er war Aufwand, der mit ai-health überflüssig wurde, und widersprach ai-health bei Test-Assertions. Er ist wieder entfernt; besser gleich ein vorhandenes Werkzeug wählen.
  - **Werkzeug-Abhängigkeit:** Refactorings, die für den eigenen Checker gemacht wurden, waren unter ai-health teils schlechter. Beispiele: zusammengefasste Assertions erzeugten neue Duplikate, und ausgelagerte Helfer trieben die Primitive-Obsession-Quote über die Mindestzahl von 10 Parametern. Man sollte sich deshalb früh auf ein Werkzeug festlegen.
  - **Stille Fallstricke:** Ohne `--config` fällt `scan <unterordner>` still auf die Defaults zurück, und eine Suppression ohne ` -- ` greift still nicht.
  - **pytest-Fixtures:** ai-health zählt sie als Argumente. Abhilfe ist `@pytest.mark.usefixtures` für Fixtures, die nur Seiteneffekte haben.
  - **Metrik-Gaming durch Agents:** Agents umgehen Metriken gern, etwa mit `**kwargs` oder Alias-Tricks. Ein Review bleibt nötig.
- **Übertragbar:**
  - Pin auf einen Commit;
  - dünne nox-Session, die nur durchreicht und `--config` setzt;
  - `delta` gegen die Merge-Base in der CI;
  - Komponenten-Vergleich;
  - pygrep-Hook für Suppressions;
  - eine Quelle je Smell, also die Strukturregeln der Linter aus.
- **Projektspezifisch:**
  - Suppressions für typer-CLI-Module;
  - pfadgefilterte PR-Jobs: beide `.aihealth.toml` stehen im Filter.

### Verbliebene eigene Logik (und warum)

- **`nox -s code-health` / `code-health-tests`:** dieselbe Funktion mit der jeweiligen Config; installiert die gepinnte Gruppe und reicht an `aihealth` durch. Einzige Zutat: `--config` für `scan`/`delta`, weil ai-health sonst bei Unterordnern still auf die Defaults zurückfällt.
- **`nox -s code-health-components`** (rund 35 Zeilen): ai-health vergleicht Dateien (`delta`), aber keine Komponenten-Scores zweier Commits. Der vom Owner beschlossene Komponenten-Vergleich (Q6) braucht deshalb einen Export der Basis und zwei `scan --format json`.
- **CI:** `git merge-base` in der Shell. Im `pull_request`-Checkout (Merge-Commit) entspricht das der Basis-Spitze; der Ausdruck bleibt aber auch bei anderen Checkouts und lokal korrekt (ein Branch hinter `main` bekommt keine fremden Änderungen angerechnet).
- **pre-commit:** ein pygrep-Hook (nur eine Regex, kein Code) für die Begründung bei Suppressions.
