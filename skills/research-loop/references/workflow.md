# Campaign workflow

Assume `PLUGIN_ROOT` points to the installed plugin and `TARGET_REPO` points to the user's project.

## Setup and approval

```bash
uv run --project "$PLUGIN_ROOT" research-loop inspect --repo "$TARGET_REPO"
uv run --project "$PLUGIN_ROOT" research-loop setup --repo "$TARGET_REPO" --profile /tmp/research-profile.yaml
uv run --project "$PLUGIN_ROOT" research-loop validate --repo "$TARGET_REPO"
uv run --project "$PLUGIN_ROOT" research-loop plan --repo "$TARGET_REPO"
uv run --project "$PLUGIN_ROOT" research-loop approve --repo "$TARGET_REPO" --plan-hash <approved-hash>
```

Do not call `approve` until the user has seen and explicitly accepted that exact plan.

## Baseline

```bash
research-loop prepare --repo "$TARGET_REPO" --id baseline --baseline --hypothesis "Record the unmodified authoritative baseline."
research-loop execute --repo "$TARGET_REPO" --id baseline --mode smoke
research-loop execute --repo "$TARGET_REPO" --id baseline --mode full
research-loop evaluate --repo "$TARGET_REPO" --id baseline
research-loop record --repo "$TARGET_REPO" --id baseline
```

## Experiment

```bash
research-loop prepare --repo "$TARGET_REPO" --id <experiment-id> --hypothesis-id <hypothesis-id> --hypothesis "<one concrete claim>"
```

The command returns the isolated worktree. Edit only that worktree, stage only approved paths, and make one hypothesis-focused commit. Then:

```bash
research-loop execute --repo "$TARGET_REPO" --id <experiment-id> --mode smoke
research-loop execute --repo "$TARGET_REPO" --id <experiment-id> --mode full
research-loop evaluate --repo "$TARGET_REPO" --id <experiment-id>
research-loop record --repo "$TARGET_REPO" --id <experiment-id>
research-loop status --repo "$TARGET_REPO"
```

A repeated run intended to confirm an improvement uses a new experiment ID and the same hypothesis ID. `keep` is available only after the configured number of valid improvements for that hypothesis ID.

