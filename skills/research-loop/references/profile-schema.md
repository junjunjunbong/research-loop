# Research Profile schema v2

The agent compiles this YAML after inspecting the project. The user should not have to author it.

```yaml
schema_version: 2
context:
  goal: "Exact user research goal"
  success_criteria:
    - "Primary metric reaches the target and the identical code tree is confirmed"
  allowed_paths: [config.json, src]
  protected_paths: [data, evaluation.py]
  research_surface:           # optional descriptive abstraction; approval-bound via context
    editable_components:
      - name: scorer
        interface: experiment.py:score
        allowed_changes: [internal_logic, configuration]
    invariants:
      - "evaluation data and the metric parser stay unchanged"
    forbidden_data_flows:
      - {from: test_dataset, to: training_pipeline}

environment:
  package_manager: uv
  resource_class: light       # light | local_cpu
  cwd: .
  commands:
    smoke: [python3, experiment.py, --smoke]
    full: [python3, experiment.py]
  timeout_seconds: 1800
  required_env: []            # names only; never values

evaluation:
  primary_metric:
    name: score
    direction: maximize       # maximize | minimize
    parser:
      type: json              # json | jsonl | regex
      path: results/metrics.json
      key: metrics.score
  required_artifacts: [results/metrics.json]
  compatibility:
    - name: dataset_version
      expected: mock-v1
      parser:
        type: json
        path: results/metrics.json
        key: metadata.dataset_version
  min_duration_seconds: 0
  confirmation_runs: 2
  acceptance:
    min_parent_delta: 0.01
    noise_tolerance: 0.001
  target:
    type: relative_improvement  # relative_improvement | absolute_improvement | metric_value
    value: 0.05

strategy:
  problem_shape:
    objective: mixed             # diagnose | optimize | mixed
    search_space: unstructured_code  # structured_parameters | unstructured_code | mixed
    fidelity: single             # single | multi
    noise: unknown               # low | high | unknown
  rationale:
    - "Competing causes should be separated before optimization."
  initial_selector: diagnostic   # diagnostic | balanced | optimization
  transitions:
    - id: diagnostic-to-balanced
      priority: 10
      from: diagnostic
      to: balanced
      trigger:
        type: experiments_recorded_gte
        value: 2

policy:
  campaign_id: 2026-07-17-example
  branch_prefix: autoresearch
  max_experiments: 6
  experiment_timeout_seconds: 1800
  campaign_timeout_seconds: 10800
  allow_gpu: false
  allow_remote: false
  allow_paid: false
  allow_shell: false
  auto_commit: true
  knowledge_access:           # optional; omit for no external idea supply
    mode: local_pack          # none | local_pack | agent_retrieval
    allow_network: false      # true required (and allowed) only for agent_retrieval
    allowed_source_types: [paper, pull_request, issue, user_note, repository_artifact]
    max_sources_per_round: 20
    max_record_bytes: 16384
    retrieval_cutoff: ""      # optional ISO date; used by agent retrieval
```

All paths are relative and confined to the target project or experiment worktree. Commands are argv arrays executed with `shell=False`. `new-campaign --base <git-ref>` resolves the base to an immutable commit included in the approval hash. The Strategy Contract is also approval-bound and becomes immutable after the first ledger row.

Supported transition triggers are `baseline_recorded`, `experiments_recorded_gte`, `promising_results_gte`, `consecutive_inconclusive_gte`, `target_reached`, and `remaining_experiments_lte`. The runner applies at most one matching rule after each recorded result, using the lowest numeric priority first. Confirmation remains a global obligation rather than a Selector.

`context.research_surface` is descriptive, not executable: it tells hypothesis generation which components may change, which invariants must hold, and which data flows are forbidden. It is hashed with the rest of `context` and shown in the dry run; verification still runs only through `environment.commands` and the evaluation compatibility parsers.

`policy.knowledge_access` is approval-bound like the rest of the policy: it appears in the dry run and its change invalidates approval. When it is present with a mode other than `none`, every `idea_sources` entry must match a record registered in the campaign Knowledge Pack (`pack-add`, verified by `pack-verify`); when it is absent, hash-pinned `idea_sources` are still accepted but no pack exists. `allow_network` governs agent-side retrieval only — the runner never fetches.

## Hypothesis specification

```yaml
hypothesis_id: h-bottleneck
statement: "The candidate pool is the primary recall bottleneck."
prediction: "Pre-rerank recall will increase when the pool is widened."
falsification_criteria: "The baseline already contains every relevant document before reranking."
family: candidate-pool
origin_evidence:
  - experiment_id: baseline
    reason: "Authoritative baseline error analysis"
idea_sources:                     # optional external idea provenance; ideas only, never code
  - source_type: paper            # paper | pull_request | issue | user_note | repository_artifact
    locator: "archive:2401.00001v2"
    content_sha256: "..."         # immutable revision and/or content_sha256 required
    claim: "A lightweight gate stabilizes outputs."
    applicability: "This project exposes a comparable scoring path."
    license: unknown
```

`origin_evidence` stays mandatory: external sources explain where an idea came from; recorded local evidence explains why it is worth testing here.

## Candidate specification

```yaml
candidate_id: diagnose-bottleneck
hypothesis_id: h-bottleneck
statement: "Measure pre-rerank recall without changing the dataset or evaluator."
family: candidate-pool
operator: diagnose              # draft | diagnose | improve | debug | confirm | recombine
trace: diagnose                 # diagnose | exploit | explore | confirm
primary_parent_id: baseline
source_parent_ids: [baseline]
evidence:
  - experiment_id: baseline
    reason: "Observed bottleneck in the authoritative artifact"
scores:
  alignment: {value: 0.9, reason: "Directly addresses the measured gap"}
  impact: {value: 0.2, reason: "Diagnostic rather than an immediate improvement"}
  feasibility: {value: 0.8, reason: "Small approved-path change"}
  information_gain: {value: 0.9, reason: "Separates competing causes"}
  novelty: {value: 0.6, reason: "Not covered by siblings"}
estimated_cost: 1
```

## Hypothesis Evidence specification

```yaml
event_id: diagnose-bottleneck-supports
hypothesis_id: h-bottleneck
experiment_id: diagnose-bottleneck
relation: supports              # supports | weakens | falsifies | inconclusive
observation: "Pre-rerank recall is below the target."
source:
  type: artifact                # primary_metric | run_log | artifact
  path: results/diagnostics.json
rationale: "The observation matches the declared prediction."
assessment: supported           # open | supported | contested | falsified
```

The agent owns the relation and assessment. The runner verifies that the experiment is recorded and that the selected metric, run log, or confined artifact exists.

Schema v0 and v1 campaigns remain readable and executable. There is no v1-to-v2 migration; create a new schema v2 Campaign to use Strategy Contracts and Hypothesis Evidence.
