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
```

All paths are relative and confined to the target project or experiment worktree. Commands are argv arrays executed with `shell=False`. `new-campaign --base <git-ref>` resolves the base to an immutable commit included in the approval hash. The Strategy Contract is also approval-bound and becomes immutable after the first ledger row.

Supported transition triggers are `baseline_recorded`, `experiments_recorded_gte`, `promising_results_gte`, `consecutive_inconclusive_gte`, `target_reached`, and `remaining_experiments_lte`. The runner applies at most one matching rule after each recorded result, using the lowest numeric priority first. Confirmation remains a global obligation rather than a Selector.

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
```

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
