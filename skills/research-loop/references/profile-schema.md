# Research Profile schema v1

The agent compiles this YAML after inspecting the project. The user should not have to author it.

```yaml
schema_version: 1
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

policy:
  campaign_id: 2026-07-16-example
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

All paths are relative and confined to the target project or experiment worktree. Commands are argv arrays executed with `shell=False`. `new-campaign --base <git-ref>` resolves the base to an immutable commit included in the approval hash.

## Candidate specification

```yaml
candidate_id: improve-bottleneck
hypothesis_id: h-bottleneck
statement: "One atomic, measurable claim."
family: bottleneck-family
operator: improve              # draft | improve | debug | confirm | recombine
trace: exploit                 # exploit | explore | confirm
primary_parent_id: baseline
source_parent_ids: [baseline]
evidence:
  - experiment_id: baseline
    reason: "Observed bottleneck in the authoritative artifact"
scores:
  alignment: {value: 0.9, reason: "Directly addresses the measured gap"}
  impact: {value: 0.8, reason: "Large share of the objective"}
  feasibility: {value: 0.8, reason: "Small approved-path change"}
  information_gain: {value: 0.7, reason: "Separates one causal factor"}
  novelty: {value: 0.6, reason: "Not covered by siblings"}
estimated_cost: 1              # 1 | 2 | 3
```

`recombine` requires exactly two source parents but still one primary Git parent. A `confirm` candidate must use the current champion, the `confirm` trace, and an unchanged Git tree.

Schema v0 profiles remain readable and can be moved into the multi-campaign control plane with `upgrade --check` followed by `upgrade --apply`. DAG features require a new schema v1 campaign.
