# Quickstart

## 1. Install the runner

```bash
uv sync --extra dev
uv run research-loop --help
```

## 2. Prepare a target

Use an existing project with at least one commit. Setup may inspect dirty state, but `plan`, `prepare`, and `execute` require the base checkout to be clean.

```bash
uv run research-loop inspect --repo /path/to/project
```

Give the inspection result, the user's exact goal, and verified project evidence to the Research Loop Skill. It compiles a YAML profile following the bundled schema.

## 3. Materialize and approve

```bash
uv run research-loop setup --repo /path/to/project --profile /tmp/research-profile.yaml
uv run research-loop validate --repo /path/to/project
uv run research-loop plan --repo /path/to/project
```

Present the complete dry run. Only after explicit user approval:

```bash
uv run research-loop approve --repo /path/to/project --plan-hash <hash>
```

## 4. Run the campaign

Use the exact baseline and experiment sequence in the Skill's `references/workflow.md`. Run `status` after every recorded result and read `.research/handoff.md` when resuming.

