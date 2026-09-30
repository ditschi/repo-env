# Renders the README/quickstart flow as an animated GIF.
#
# Requires https://github.com/charmbracelet/vhs (and its own deps: ttyd, ffmpeg).
# Regenerate after any CLI-visible change:
#
#   vhs docs/assets/vhs/quickstart.tape
#
# Run from a throwaway REPOENV_HOME with a small demo source tree already
# populated (see docs/assets/vhs/README.md) -- this tape assumes ~/src has
# 2-3 tiny repos and ~/envs is empty, so the recording stays short and its
# output is deterministic between runs.

Output docs/assets/vhs/quickstart.gif

Set Shell "bash"
Set FontSize 16
Set Width 1200
Set Height 700
Set Theme "Dracula"
Set TypingSpeed 40ms

Type "renv create web -s ~/src -b feature/my-task --activate"
Enter
Sleep 1s

Type "renv ls"
Enter
Sleep 1s

Type "cd \"$(renv path web)\""
Enter
Type "renv run -- git status"
Enter
Sleep 1500ms
