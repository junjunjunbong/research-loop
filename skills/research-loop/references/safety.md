# Safety policy

- Require a clean, committed Git base before planning or execution.
- Keep the user's base checkout untouched; all hypothesis edits occur in external worktrees.
- Never run `git stash`, `git reset`, `git clean`, force-push, or an overwriting checkout.
- Never merge, delete, or rewrite experiment branches automatically.
- Execute only the exact approved argv with `shell=False` and a timeout.
- Treat approval as bound to the profile, commands, policy, resource class, and base commit hash.
- Permit only `light` or `local_cpu` resource classes in v1.
- Do not launch GPU, remote, paid, Slurm, SSH, or Kubernetes work in v1.
- Store environment variable names only. Never write credentials, tokens, or secret values to `.research/`.
- Confine configured paths to the target project and edits to approved paths.
- Do not mutate datasets unless an allowed path and the approved hypothesis explicitly require it.
- Treat smoke runs as plumbing checks only.
- Use the Evaluation Contract's authoritative metric source; never select a convenient number from logs.
- Treat DAG source parents as provenance only. Create a worktree from one approved primary parent and never merge, cherry-pick, or rewrite branches automatically.
- Do not execute a schema v1 candidate unless deterministic ranking selects it.
