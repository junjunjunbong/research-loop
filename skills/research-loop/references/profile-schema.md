# Research Profile schema v0

The agent compiles this YAML after inspecting the project. The user should not have to author it.

```yaml
schema_version: 0
context:
  goal: "Exact user research goal"
  success_criteria:
    - "Primary metric improves beyond the configured minimum delta"
  allowed_paths:
    - config.json
    - src
  protected_paths:
    - data
    - evaluation.py

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
  required_artifacts:
    - results/metrics.json
  compatibility:
    - name: dataset_version
      expected: mock-v1
      parser:
        type: json
        path: results/metrics.json
        key: metadata.dataset_version
    - name: query_count
      expected: 100
      parser:
        type: json
        path: results/metrics.json
        key: metadata.query_count
  min_duration_seconds: 0
  confirmation_runs: 2
  min_delta: 0.01
  noise_tolerance: 0.001

policy:
  campaign_id: 2026-07-15-example
  branch_prefix: autoresearch
  max_experiments: 3
  experiment_timeout_seconds: 1800
  campaign_timeout_seconds: 7200
  allow_gpu: false
  allow_remote: false
  allow_paid: false
  allow_shell: false
  auto_commit: true
```

All paths are relative and confined to the target project or experiment worktree. Commands are argv arrays and are executed with `shell=False`. Compatibility fields are extracted independently so JSON, JSONL, and regex primary metrics can still be validated against authoritative metadata.

