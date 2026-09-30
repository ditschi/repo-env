#!/usr/bin/env bash
# Seeds the throwaway sandbox that select.tape records `renv select` against:
# two tiny local repos (no remote) and two environments built from them.
# Sourced by select.tape's Hide block so REPOENV_HOME (set via the tape's own
# `Env` directive) stays exported into the recorded shell.
set -uo pipefail

SANDBOX=/tmp/renv-vhs-select-demo
rm -rf "$SANDBOX"
mkdir -p "$SANDBOX/src-web/webapp" "$SANDBOX/src-api/apiserver" "$SANDBOX/envs"

for repo in "$SANDBOX/src-web/webapp" "$SANDBOX/src-api/apiserver"; do
  git -C "$repo" init -q -b main
  git -C "$repo" config user.email demo@example.com
  git -C "$repo" config user.name demo
  touch "$repo/README.md"
  git -C "$repo" add -A
  git -C "$repo" commit -q -m init
done

renv init -s "$SANDBOX/src-web" -d "$SANDBOX/envs" -y >/dev/null
# --preserve + -B: these are plain local repos with no `origin` remote to
# fetch from (see the repo's own AGENTS.md "Non-obvious gotchas").
renv create web -s "$SANDBOX/src-web" --preserve -B main >/dev/null
renv create api -s "$SANDBOX/src-api" --preserve -B main >/dev/null
