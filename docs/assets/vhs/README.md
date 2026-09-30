# Demo recordings

GIFs for the docs, generated deterministically from checked-in [VHS](https://github.com/charmbracelet/vhs)
`.tape` scripts instead of hand-recorded screen captures, so they can be regenerated on demand
whenever CLI output changes rather than going stale silently.

## Setup (one time)

```bash
go install github.com/charmbracelet/vhs@latest   # needs ttyd + ffmpeg on PATH too
```

## Regenerate

```bash
SB=$(mktemp -d)
mkdir -p "$SB/src" "$SB/envs"
# ... seed 2-3 tiny demo repos under $SB/src (see tests/integration/support/gitfixtures.py
# for the same pattern the test suite uses) ...
REPOENV_HOME="$SB/home" renv init -s "$SB/src" -d "$SB/envs" -y
cd "$SB" && vhs /path/to/docs/assets/vhs/quickstart.tape
```

Commit the regenerated `.gif` alongside the `.tape` change.

## `select.tape`

Unlike `quickstart.tape`, this one needs no manual sandbox setup — it's self-contained via
`select-setup.sh`, sourced from a `Hide` block in the tape itself. Regenerate with:

```bash
vhs docs/assets/vhs/select.tape   # run from the repo root
```
