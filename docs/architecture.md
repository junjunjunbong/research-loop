# Architecture

## Boundary

Research Loop is installed as a plugin and operates on a separate target repository. It never copies plugin code into that project. The generated `.research/` directory is a local project-specific control plane; experiment source changes live only in external Git worktrees.

## Components

The Agent Skill interprets the user's goal, reads repository evidence, compiles the Research Profile, forms hypotheses, and presents approval or ambiguity questions. The Python runner owns deterministic and safety-critical operations: schema validation, approval hashing, Git worktree creation, bounded process execution, authoritative metric parsing, compatibility validation, ledger writes, and checkpoints.

The Research Profile is split into four contracts:

- research context: exact goal, success criteria, modification scope, and protected paths
- environment: approved local argv, cwd, package manager, resource class, timeout, and required environment-variable names
- evaluation: metric parser, comparison direction, required artifacts, compatibility parsers, and confirmation policy
- loop policy: campaign identity, Git branch prefix, experiment count, wall-clock limits, and forbidden resource modes

## Approval integrity

`plan` hashes the normalized profile plus the absolute target repository and committed base revision. `approve` records only an exact rendered hash. Every prepare or execute transition recomputes the contract; a changed command, metric, policy, resource class, goal, or base commit invalidates approval.

Dynamic state such as ledger rows and whether a baseline already exists is shown in the dry run but excluded from the contract hash, so recording an approved experiment does not invalidate the rest of the same campaign.

## Git isolation

The base checkout must be clean and is never switched or edited. Each attempt receives `autoresearch/<campaign>/<experiment>` and a worktree under `~/.cache/research-loop/worktrees/<repo-hash>/<campaign>/`. Experiment branches are preserved regardless of result. The runner performs no merge or destructive Git operation.

## Result validity

Execution and evaluation are separate. A process manifest captures argv, commit, timing, exit code, timeout, resource class, and log path. Evaluation then validates mode, exit status, duration, required artifacts, compatibility fields, and the authoritative metric parser before comparison with the recorded baseline.

