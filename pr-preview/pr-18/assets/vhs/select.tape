# Renders the `renv select` interactive picker as an animated GIF.
#
# Requires https://github.com/charmbracelet/vhs (and its own deps: ttyd, ffmpeg).
# Regenerate after any select-command UI change, run from the repo root:
#
#   vhs docs/assets/vhs/select.tape
#
# Unlike quickstart.tape, this one is self-contained: the Hide block below
# sources select-setup.sh, which seeds its own throwaway sandbox (two tiny
# local repos + two environments), so no external setup is needed first.

Output docs/assets/vhs/select.gif

Set Shell "bash"
Set FontSize 16
Set Width 1200
Set Height 700
Set Theme "Dracula"
Set TypingSpeed 40ms

Env REPOENV_HOME "/tmp/renv-vhs-select-demo/home"

Hide
Type "source docs/assets/vhs/select-setup.sh && clear"
Enter
Sleep 500ms
Show

Type "renv select"
Enter
Sleep 1s
Down
Sleep 500ms
Enter
Sleep 800ms
Down
Down
Sleep 500ms
Enter
Sleep 1500ms
Type "exit"
Enter
Sleep 1s
