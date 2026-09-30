# Demo recordings (asciinema + agg)

GIFs generated from a real terminal session instead of a hand-recorded screen capture, so
timing reflects the actual program rather than a typed-out script.

Unlike `docs/assets/vhs/` (which renders tapes through a headless-browser terminal via
[VHS](https://github.com/charmbracelet/vhs)), these use
[asciinema](https://github.com/asciinema/asciinema) to record a real pty session and
[agg](https://github.com/asciinema/agg) to render the `.cast` to a GIF.

## Setup (one time)

```bash
# asciinema v3 and agg both ship static Linux/macOS binaries on their GitHub Releases pages:
#   https://github.com/asciinema/asciinema/releases
#   https://github.com/asciinema/agg/releases
```

`select-record.py` also needs `pexpect` (not a project dependency) — run it via
`uv run --with pexpect --no-project python3 ...` as shown below, so nothing gets added to
`pyproject.toml`.

## Regenerate `select.gif`

`select-record.py` seeds its own throwaway sandbox and drives `renv select` end to end (arrow
keys, enter), so no external setup is needed first. Run from the repo root:

```bash
asciinema rec --overwrite --window-size 100x40 \
  --command "uv run --with pexpect --no-project python3 docs/assets/casts/select-record.py" \
  /tmp/select.cast

agg --rows 22 --theme dracula /tmp/select.cast docs/assets/casts/select.gif
```

Two steps, two different row counts, on purpose:

- **Recording** at a generous 40 rows leaves the real pty plenty of room, so nothing wraps or
  scrolls oddly inside the terminal itself.
- **Rendering** crops the *image* to 22 rows — measured as the deepest row any frame actually
  draws to (the biggest frame is the second `renv select`'s 6-item action list), plus a few
  rows of padding so you can see nothing was cut off, rather than an arbitrary fixed canvas
  with a lot of empty space below the content.

If `select.py`'s output grows taller than that (e.g. another action added to the list),
re-measure rather than guessing: render once at `--rows 40`, extract frames (e.g. `ffmpeg -i
docs/assets/casts/select.gif -vf fps=3 /tmp/frame_%03d.png`), find the deepest frame, and pick
a new `--rows` a few lines below it.

Commit both `select-record.py` (the source of truth) and the regenerated `select.gif`; the
intermediate `.cast` is not checked in.
