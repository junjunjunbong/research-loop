---
name: research-loop
license: Apache-2.0
description: "Bootstrap and run a bounded autonomous research campaign in an existing Git project. Use when a user wants the agent to inspect a research codebase, compile a goal into project-specific execution and evaluation contracts, establish a baseline, and iteratively test hypotheses. Do NOT use for ordinary bug fixes, code review, one-off commands, or when the user has not asked for autonomous experimentation."
---

# Research Loop

Turn the user's Research Goal and the current Git project into an approved, auditable local experiment campaign.

This is a modified, unofficial derivative informed by NVIDIA's `nemo-rl-auto-research` and `nemo-rl-session-memory` skills. The original snapshots and attribution are preserved under `vendor/nvidia/`. This skill is not affiliated with, endorsed by, or verified by NVIDIA.

The user does not create a domain module, evaluator module, or environment adapter. Inspect the project, compile a Research Profile, and ask only for facts that cannot be established safely from repository evidence. Optional research knowledge may inform hypotheses, but it is never required to start the loop.

Resolve the plugin root as the directory two levels above this file. Run the deterministic helper with:

```bash
uv run --project "$PLUGIN_ROOT" research-loop <command> --repo "$TARGET_REPO"
```

## Setup

1. Preserve the user's Research Goal verbatim, including success criteria, priorities, protected areas, cost limits, and stop rules.
2. Run `inspect` before asking project-structure questions.
3. Read the candidate entrypoints, evaluators, configs, CI, README, and package metadata. Treat filenames as evidence, never as an authoritative command by themselves.
4. Compile a profile that follows `references/profile-schema.md`. Store secret names only in `required_env`; never store secret values.
5. Run `setup`, then `validate`.
6. If the authoritative command, metric source, comparison direction, compatibility checks, or allowed paths remain ambiguous, ask the user only about those blockers.
7. Run `plan` and show the exact commands, metric source, modification scope, resource class, experiment count, and timeout to the user.
8. Call `approve` only after the user explicitly approves that plan hash. Approval for a different plan, old plan, or general project work is insufficient.

Setup may inspect a dirty repository, but planning and campaign execution require an existing clean Git commit. Never initialize Git, commit user work, stash, or clean the target project automatically.

## Campaign

Follow `references/workflow.md` exactly.

- Create and record a baseline first when none exists.
- Form one concrete hypothesis from the goal, repository, baseline, and Research Ledger.
- Use `prepare` to create the experiment branch and isolated external worktree.
- Edit only the approved paths in that worktree. Make one minimal hypothesis commit before any smoke or full run.
- Run the approved smoke command. Treat it only as plumbing validation.
- Run the approved full command, then `evaluate` and `record`.
- Check `status` after every recorded result. Do not stop before the explicit count, budget, deadline, or target is reached.
- Keep every experiment branch. Never merge a winning branch automatically.

Generate hypotheses dynamically from the actual code and evidence. Do not require a retrieval pack or any other domain pack. Prefer high expected gain, low complexity, and a change that isolates one causal factor.

Use the status policy in `references/decision-policy.md`. Never guess a metric from logs when the Evaluation Contract names another source.

## Recovery

On resume, read `.research/handoff.md`, `.research/state.md`, and the latest Research Ledger row, then run `status` and verify the base Git state. Re-render the plan if the profile, command, policy, or base commit changed; stale approval must not be reused.

Update the checkpoint after setup, approval, experiment preparation, before and after long commands, after a result, when the user changes direction, and before handoff.

## Safety

Follow `references/safety.md`. v0 permits only local `light` or `local_cpu` argv execution without a shell. GPU, remote, paid, Slurm, SSH, Kubernetes, destructive Git, dataset mutation outside approved paths, and automatic merge are out of scope.

## References

- `references/profile-schema.md` — generated Research Profile contract.
- `references/workflow.md` — exact setup, baseline, experiment, and recovery flow.
- `references/decision-policy.md` — result validity and status meanings.
- `references/safety.md` — approval, Git, resource, path, and credential boundaries.

