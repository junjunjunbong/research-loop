---
name: research-loop
license: Apache-2.0
description: "Run a bounded autonomous research campaign in an existing Git project. Use only when the user explicitly names or invokes the research-loop skill. Do not trigger from a task's similarity to research, experimentation, optimization, or autonomous iteration."
---

# Research Loop

## Invocation Gate

Proceed only when the user explicitly names the `research-loop` skill or invokes its client command. A research repository, an experimentation request, or a task that otherwise matches this description is not sufficient authorization to activate the skill automatically. If the skill was selected without an explicit user invocation, stop using it and handle the request normally.

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
4. Compile a schema v2 profile that follows `references/profile-schema.md`. Classify the problem shape, recommend an initial Selector, give evidence-backed rationale, and define only deterministic transitions the user is willing to approve. Store secret names only in `required_env`; never store secret values.
5. Run `new-campaign --base <git-ref>`, then `validate`. Use `setup` only for legacy schema v0 profiles; schema v1 remains supported for existing campaigns.
6. If the authoritative command, metric source, comparison direction, compatibility checks, or allowed paths remain ambiguous, ask the user only about those blockers.
7. Run `plan` and show the exact commands, metric source, modification scope, resource class, experiment count, timeout, initial Selector, rationale, and transition rules to the user.
8. Call `approve` only after the user explicitly approves that plan hash. Approval for a different plan, old plan, or general project work is insufficient.

Setup may inspect a dirty repository, but planning and campaign execution require an existing clean Git commit. Never initialize Git, commit user work, stash, or clean the target project automatically.

## Campaign

Follow `references/workflow.md` exactly.

- Create and record a baseline first when none exists.
- After the baseline, register explicit hypotheses with `hypothesis-add`. Each hypothesis must state a prediction, a falsification criterion, a family, and recorded origin evidence.
- After each result, run `proposal-context`, call `evidence` for the parents you build on, and author one slot-diverse proposal of 4–6 items following `references/proposal-guide.md`.
- Apply the critic checklist, then run `proposal-validate` and `portfolio-lint`. Register only accepted items — `hypothesis-add` first, then `candidate-add` — and call `candidate-rank`. The runner's recommendation is authoritative for deterministic trace quotas and tie breaking.
- Use `prepare --candidate-id` to create the recommended experiment branch and isolated external worktree.
- Edit only the approved paths in that worktree. Make one minimal hypothesis commit before any smoke or full run.
- Run the approved smoke command. Treat it only as plumbing validation.
- Run the approved full command, then `evaluate` and `record`.
- Add Hypothesis Evidence with `hypothesis-evidence-add`, explicitly recording the observation, source, relation, rationale, and updated assessment. The runner validates provenance; the agent owns the scientific interpretation.
- Check `status` after every recorded result. Do not stop before the explicit count, budget, deadline, or target is reached.
- Keep every experiment branch. Never merge a winning branch automatically.

Generate hypotheses dynamically from the actual code and evidence. Score alignment, expected impact, feasibility, information gain, and novelty with a short evidence-backed reason. Prefer high expected gain, low complexity, and a change that isolates one causal factor. External papers and pull requests may supply mechanisms — never code — under the external-ideas rules in `references/proposal-guide.md`.

Use four logical traces in schema v2: `diagnose` tests a discriminating observation, `exploit` improves a supported direction, `explore` tests an orthogonal family, and `confirm` reruns an identical code tree. A `recombine` candidate records two logical source parents but has one primary Git parent; never merge or cherry-pick automatically.

Treat the Strategy Contract as immutable after the first ledger row. The runner may change Selectors only through pre-approved deterministic transitions. If the research direction requires a transition outside that contract, preserve the Campaign and create a new one.

Use the status policy in `references/decision-policy.md`. Never guess a metric from logs when the Evaluation Contract names another source.

## Recovery

On resume, resolve the active campaign from `.research/index.json`, read its `handoff.md`, `state.md`, and latest Research Ledger row, then run `status` and verify the base Git state. Re-render the plan if the profile, command, policy, or frozen base commit changed; stale approval must not be reused.

Update the checkpoint after setup, approval, experiment preparation, before and after long commands, after a result, when the user changes direction, and before handoff.

## Safety

Follow `references/safety.md`. v0.3 permits only local `light` or `local_cpu` argv execution without a shell. GPU, remote, paid, Slurm, SSH, Kubernetes, destructive Git, dataset mutation outside approved paths, and automatic merge are out of scope. Network use is agent-side retrieval only, behind an approved `knowledge_access` policy per `references/retrieval-guide.md`; the runner never fetches.

## References

- `references/profile-schema.md` — generated Research Profile contract.
- `references/proposal-guide.md` — slot-diverse proposal generation and the critic checklist.
- `references/retrieval-guide.md` — approved agent-side paper/PR retrieval into the Knowledge Pack.
- `references/workflow.md` — exact setup, baseline, experiment, and recovery flow.
- `references/decision-policy.md` — result validity and status meanings.
- `references/safety.md` — approval, Git, resource, path, and credential boundaries.
