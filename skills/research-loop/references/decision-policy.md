# Decision policy

- `promising`: one valid full run improves its parent, becomes champion, or reaches the campaign target, but identical-tree confirmation is incomplete.
- `keep`: the configured number of compatible full runs for one Git tree confirms the result, or a valid baseline is recorded as the campaign anchor.
- `discard`: the primary metric regresses from its parent beyond noise tolerance.
- `inconclusive`: the change is within the configured uncertainty or improvement threshold.
- `crash`: the approved command times out or exits unsuccessfully and produces no valid run.
- `invalid`: comparison conditions changed, an artifact is missing, the metric parser fails, the run is too short, no baseline exists, or a smoke run is presented as a performance result.

Compatibility checks are part of the Evaluation Contract. Dataset version, evaluation configuration, query count, seed policy, or any other comparison-critical value should be represented by an explicit parser and expected value. Do not infer compatibility from filenames.

Metric extraction failure is `invalid`, not `crash`, when execution itself completed. A failed process is `crash`. Record every attempted full run exactly once.

Schema v1 and v2 record `delta_vs_baseline`, `delta_vs_parent`, and `delta_vs_champion` separately. `target_reached` never overrides a parent regression. Campaign success requires both `target_reached` and `confirmed` on the selected champion.
