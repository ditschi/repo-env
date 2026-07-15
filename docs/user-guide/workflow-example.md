# Workflow example

End-to-end flow: create an environment, work across repos, open PRs, tear down.

Assumes clones live in `~/src` and environments in `~/envs`. Adjust paths to match your `renv init` answers.

## 1. One-time setup

```bash
renv init -s ~/src -d ~/envs -y
eval "$(renv completion)"    # optional; add to shell rc
```

## 2. Create and activate

```bash
renv create web \
  -s ~/src \
  -d ~/envs \
  -b feature/my-task \
  -i "service-*" \
  --activate

renv ls
renv status web
```

## 3. Work in the environment

```bash
cd "$(renv path web)"

# Run across all worktrees (ENV optional when active or inside env dir)
renv run -- git status
renv run -- make test
renv run -j 4 -- git pull --ff-only

# Subshell with env context loaded
renv sh web
```

## 4. Add another repo later

```bash
renv add web -s ~/src -i "new-service" -b feature/my-task
```

## 5. Sync and check health

```bash
renv sync web
renv status web
```

If a worktree folder was deleted by mistake:

```bash
renv repair web
```

## 6. Open pull requests

Requires [GitHub CLI](https://cli.github.com/) (`gh auth login`).

```bash
# Push yourself in each repo, then:
renv pr web --title "feat: migrate X to Y" --draft

# Or let renv push first:
renv pr web --title "feat: migrate X to Y" --push --skip-no-diff
```

## 7. Tear down

```bash
# Remove registry entry only (worktrees stay on disk)
renv rm web

# Remove registry + delete worktrees and env directory
renv rm web --delete-files --force
```

Source clones under `~/src` are never deleted by `renv rm`.

## Next steps

- [Concepts](concepts.md) — layout, resolution, aliases
- [Troubleshooting](troubleshooting.md) — recovery commands
- [Commands](commands.md) — full command reference
