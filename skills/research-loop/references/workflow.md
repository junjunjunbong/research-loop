# Campaign workflow

Assume `PLUGIN_ROOT` points to the installed plugin and `TARGET_REPO` points to the user's project.

## Setup and approval

```bash
uv run --project "$PLUGIN_ROOT" research-loop inspect --repo "$TARGET_REPO"
uv run --project "$PLUGIN_ROOT" research-loop new-campaign --repo "$TARGET_REPO" --profile /tmp/research-profile.yaml --base <git-ref>
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

## Evidence, candidates, and experiment

```bash
research-loop evidence --repo "$TARGET_REPO" --operator improve --parent-id baseline
research-loop candidate-add --repo "$TARGET_REPO" --spec /tmp/candidate.yaml
research-loop candidate-rank --repo "$TARGET_REPO"
research-loop prepare --repo "$TARGET_REPO" --id <experiment-id> --candidate-id <recommended-candidate-id>
```

The command returns the isolated worktree. Edit only that worktree, stage only approved paths, and make one hypothesis-focused commit. Then:

```bash
research-loop execute --repo "$TARGET_REPO" --id <experiment-id> --mode smoke
research-loop execute --repo "$TARGET_REPO" --id <experiment-id> --mode full
research-loop evaluate --repo "$TARGET_REPO" --id <experiment-id>
research-loop record --repo "$TARGET_REPO" --id <experiment-id>
research-loop status --repo "$TARGET_REPO"
```

A confirmation uses a new experiment/candidate ID, the `confirm` operator, and the champion as primary parent. The runner creates an empty commit so the Git tree stays identical. `keep` is available only after the configured number of compatible full runs with the same Git tree hash.

## Legacy upgrade

```bash
research-loop upgrade --repo "$TARGET_REPO" --check
research-loop upgrade --repo "$TARGET_REPO" --apply
```

Always inspect `--check` first. Migrated schema v0 campaigns remain readable, while DAG candidates require a new schema v1 campaign.
