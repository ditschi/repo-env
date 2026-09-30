# Demo recordings (asciinema + agg)

GIFs generated from a real terminal session instead of a hand-recorded screen capture, so
timing and output reflect the actual program rather than a typed-out script. Regenerate
on-demand when a command's UI changes -- this does **not** run on every docs build.

[asciinema](https://github.com/asciinema/asciinema) records a real pty session to a small
diffable `.cast` (JSON); [agg](https://github.com/asciinema/agg) renders that `.cast` to a GIF.

## Setup (one time)

Both ship as static binaries on their GitHub Releases pages -- no package manager needed:

```bash
# https://github.com/asciinema/asciinema/releases  (asciinema-<target>, chmod +x, put on PATH)
# https://github.com/asciinema/agg/releases         (agg-<target>, chmod +x, put on PATH)
```

Already available in the project [devcontainer](../../../.devcontainer/) -- nothing to install
there.

## Regenerate `quickstart.gif`

`quickstart-record.py` seeds its own throwaway sandbox and drives the README/quickstart flow
end to end (no extra Python deps needed). Run from the repo root:

```bash
asciinema rec --overwrite --cols 100 --rows 30 \
  --command "python3 docs/assets/casts/quickstart-record.py" \
  /tmp/quickstart.cast

agg --rows 20 --theme dracula /tmp/quickstart.cast docs/assets/casts/quickstart.gif
```

## Regenerate `select.gif`

`select-record.py` seeds its own throwaway sandbox and drives `renv select` end to end (arrow
keys, enter). It additionally needs `pexpect` (not a project dependency) to send keystrokes, so
run it via `uv run --with pexpect --no-project`:

```bash
asciinema rec --overwrite --cols 100 --rows 40 \
  --command "uv run --with pexpect --no-project python3 docs/assets/casts/select-record.py" \
  /tmp/select.cast

agg --rows 22 --theme dracula /tmp/select.cast docs/assets/casts/select.gif
```

## Why recording and rendering use different row counts

- **Recording** at a generous height (30-40 rows) leaves the real pty plenty of room, so nothing
  wraps or scrolls oddly inside the terminal itself.
- **Rendering** crops the *image* to the deepest row any frame actually draws to (plus a few rows
  of padding so you can see nothing was cut off), rather than an arbitrary fixed canvas with a
  lot of empty space below the content.

If a script's output grows taller than the current crop (e.g. another action added to
`select`'s list), re-measure rather than guessing: render once at the recording height, extract
frames (e.g. `ffmpeg -i docs/assets/casts/select.gif -vf fps=3 /tmp/frame_%03d.png`), find the
deepest frame, and pick a new `--rows` a few lines below it.

Commit both the `*-record.py` script (the source of truth) and the regenerated `.gif`; the
intermediate `.cast` is not checked in.
