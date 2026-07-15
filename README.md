# Research Loop

Research Loop is a portable Agent Skill for Codex and Claude Code plus a deterministic runner that turns an existing Git research project and a user's goal into a bounded, auditable local experiment campaign.

The user supplies the scientific intent. The plugin inspects the repository, compiles project-specific execution and evaluation contracts, renders an exact dry-run plan, obtains one campaign approval, establishes a baseline, and then iterates through minimal hypotheses in isolated Git worktrees.

> This project contains modified, unofficial derivatives of NVIDIA agent skills. It is not affiliated with, endorsed by, or verified by NVIDIA.

## Why this shape

Research Loop does not require users to build domain modules, evaluator modules, or environment adapters. Those concepts are replaced by generated project contracts:

```text
User Research Goal + repository evidence
                    |
                    v
        generated Research Profile
          /                  \
Execution Contract      Evaluation Contract
          \                  /
           approved Campaign
                    |
                    v
 baseline -> hypothesis -> worktree -> run -> evaluate -> ledger
```

Retrieval/RAG is a future application case, not a dependency of the architecture. Optional research knowledge packs are intentionally absent from v0.

## v0 capabilities

- Codex and Claude Code plugin manifests with one portable Agent Skill
- read-only repository inspection
- generated `.research/` state and schema validation
- plan-hash approval bound to goal, commands, policy, resource class, and base commit
- external Git worktree and branch per baseline/experiment
- local argv execution with `shell=False`, process-group timeout, and exact logs
- JSON, JSONL, and regex metric extraction
- compatibility checks and six research result states
- append-only TSV Research Ledger and durable state/handoff
- mock end-to-end campaign tests without GPU work

## Install for development

Requirements: Git, `uv`, and Python 3.9 or newer.

```bash
git clone https://github.com/junjunjunbong/research-loop.git
cd research-loop
uv sync --extra dev
uv run research-loop --help
```

The Codex manifest is `.codex-plugin/plugin.json`; the Claude Code manifest and self-hosted marketplace are under `.claude-plugin/`. Both clients use the same skill entrypoint at `skills/research-loop/SKILL.md` and the same Python runner.

### Claude Code

For local plugin development from this checkout:

```bash
claude plugin marketplace add ./ --scope project
claude plugin install research-loop@research-loop --scope project
```

After the Claude Code manifests are available on GitHub, install from the repository-hosted marketplace:

```bash
claude plugin marketplace add junjunjunbong/research-loop
claude plugin install research-loop@research-loop --scope project
```

The Claude Code skill is exposed as:

```text
/research-loop:research-loop
```

## Project setup

Run the plugin from an existing Git project and provide a Research Goal in conversation. The Skill runs `inspect`, verifies commands and metrics from repository evidence, and compiles a temporary profile following `skills/research-loop/references/profile-schema.md`.

The deterministic sequence is:

```bash
uv run --project /path/to/research-loop research-loop inspect --repo /path/to/project
uv run --project /path/to/research-loop research-loop setup --repo /path/to/project --profile /tmp/profile.yaml
uv run --project /path/to/research-loop research-loop validate --repo /path/to/project
uv run --project /path/to/research-loop research-loop plan --repo /path/to/project
```

The plan output includes a hash. After the user explicitly approves the displayed plan:

```bash
uv run --project /path/to/research-loop research-loop approve --repo /path/to/project --plan-hash <hash>
```

Approval becomes stale if the profile, command, policy, resource class, or base commit changes.

## Dry-run example

`examples/mock-project/` is copied into a temporary Git repository by the integration tests. It writes a deterministic JSON metric and demonstrates:

```text
setup -> plan -> approval -> baseline -> improved hypothesis
      -> metric parsing -> promising -> Research Ledger -> handoff
```

Run the full verification with:

```bash
uv run --extra dev pytest
```

No real training, GPU, remote, or paid workload is launched.

## Safety policy

- Planning and execution require a clean existing Git commit.
- `.research/` is local and excluded through `.git/info/exclude` by default.
- The base checkout is never edited by a campaign.
- Experiments use external worktrees and preserved branches.
- No automatic merge, stash, reset, clean, force-push, or branch deletion occurs.
- v0 accepts only local `light` or `local_cpu` execution.
- Commands are argv arrays; shell execution is forbidden.
- Secret values are forbidden in profiles.
- Smoke runs cannot become performance results.
- Metrics come only from the approved authoritative parser.

## Upstream and licensing

The five requested NVIDIA source files are preserved verbatim under `vendor/nvidia/` at commit `1700ebd31ba862df5b6992403764c989f2bda66b`. See `UPSTREAM.md`, `NOTICE.md`, and `vendor/nvidia/SHA256SUMS` for exact provenance and integrity data. NVIDIA signature files are intentionally excluded and this derived skill must not be represented as NVIDIA-verified.

The upstream repository's dual-license text is preserved in `LICENSE`. Consult `NOTICE.md` for the upstream distinction between source code and documentation/skills.

## Not implemented in v0

- GPU, Slurm, SSH, Kubernetes, remote, or paid execution
- automatic project Git initialization or dirty-worktree capture
- automatic winning-branch merge or cleanup
- research/domain packs
- arbitrary shell pipelines
- graphical UI, hosted service, or multi-user coordination
