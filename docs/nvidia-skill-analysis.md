# NVIDIA skill analysis

Analyzed snapshot: NVIDIA `skills` commit `1700ebd31ba862df5b6992403764c989f2bda66b`, imported 2026-07-15.

## `nemo-rl-auto-research`

### Purpose and lifecycle

The skill runs iterative NeMo-RL or NeMo-gym research against a user objective with Git branches and an untracked TSV as the durable experiment journal. Its lifecycle is: inspect Git and recipe context, translate stop rules into monitored limits, verify data/runtime inputs, create a campaign prefix and ledger, establish an unmodified baseline, choose one hypothesis, make a minimal committed change, launch a bounded run, extract the recipe's authoritative metric, record the result, report progress, and continue until an explicit stop condition is met.

### Baseline, hypothesis, and Git strategy

The baseline has its own branch and empty commit from a deliberate base revision. Every idea gets another branch under a shared prefix, one hypothesis-focused commit, and optional fix commits. Branches are retained even when weak or crashing. A new idea may branch from the baseline for clean A/B comparison or from the best known result for cumulative progress; parent commit is always recorded.

Hypotheses are selected from observed bottlenecks and should maximize expected objective gain while limiting complexity. The exploration reference covers prompt/rollout format, batching, sequence/precision, sync/async training, backend correctness, reward/data, hardware-aware pruning, and crash triage.

### Metrics, decisions, and stopping

The TSV connects index, branch, parent and result commits, recipe, metric, memory, elapsed time, launcher, job ID, exact command, log path, status, and description. Metric values must come from the recipe's authoritative validation or task signal. Results are `keep`, `discard`, or `crash`; a smoke run is explicitly insufficient evidence for discard.

User-specified experiment counts, campaign deadlines, per-run timeouts, and target metrics dominate. Attempt counts include failed ideas. With no explicit stop rule, the generic fallback is a baseline plus up to three low-risk experiments.

### NeMo-RL coupling

The source skill assumes NeMo-RL recipes, RL training entrypoints, reward/rollout semantics, actor-learner layouts, GRPO/DPO/SFT, NeMo-gym, backend choices, GPU topology, and NeMo-RL/Kubernetes launchers. Those details cannot be treated as general research contracts.

### Reusable principles

The reusable core is baseline-first comparison, one concrete hypothesis, minimal committed change, deliberate parent selection, authoritative metrics, per-attempt branches, exact command/artifact logging, explicit validity and decision, preserved failures, enforced budgets, progress reporting, checkpointing, and non-destructive Git behavior.

## `nemo-rl-session-memory`

### Structure

One timestamped directory is created under `session/`. `session_state.md` stores the stable goal, current subtask, loaded skills, status, plan, assumptions, blockers, and next actions. `timeline.md` is append-only evidence of major actions and results. `files.md` distinguishes inspected, changed, and generated files. `handoff.md` gives a compact resume point, next actions, and risks.

### Checkpoints and recovery

Checkpoints occur after enough inspection to form a plan, before and after meaningful edits, before long commands or branch changes, when the user redirects work, at handoff, and periodically during long sessions. Recovery reads handoff first, then state and recent timeline, verifies important claims against live Git/files, and records mismatches.

### Auto-research connection

The Auto Research skill requires session memory before branching and around plans, edits, launches, result transitions, direction changes, and handoff. It protects the overall campaign goal and stop rule from context compaction or disconnects.

## Generalized v0 mapping

Research Loop preserves baseline, hypothesis, minimal change, run, evaluate, log, decision, checkpoint, and explicit stop rules. It replaces RL recipe, reward, rollout, actor-learner, GRPO/DPO/SFT, NeMo-gym, and NeMo-RL launcher assumptions with a generated Research Profile containing an Execution Contract and Evaluation Contract.

Session memory is flattened into one project-local `.research/` control plane because the campaign itself is already the durable unit: `state.md` and `handoff.md` provide recovery, `experiments.tsv` is the Research Ledger, and per-experiment manifests preserve commands and artifacts.

