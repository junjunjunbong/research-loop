# Threat model: external knowledge as hypothesis-generation input

Scope: the idea-supply features planned in `docs/idea-supply-plan.md` (ADR 0004). Reading papers, pull requests, issues, or user notes into an autonomous loop that edits code and runs commands introduces a new trust boundary. This document fixes that boundary before any implementation.

## Assets to protect

- The approved contracts: commands (argv), primary metric and parser, evaluator, allowed/protected paths, resource policy, Strategy Contract, base commit, approval state.
- The integrity of the Research Ledger and Hypothesis Evidence (append-only, provenance-verified).
- The target repository outside approved paths, and the user's credentials/secrets.
- Scientific validity: comparisons against the authoritative metric without contamination.

## Trust boundaries

1. **User chat → agent**: trusted instructions.
2. **Repository evidence and ledger → agent**: trusted data (locally produced, hash-anchored).
3. **External content (papers, PRs, issues) → agent**: **untrusted data**. Never instructions, regardless of any text inside it claiming otherwise.
4. **Agent → runner**: proposals and specs; the runner re-validates everything against schemas, the ledger, and the approval hash. The runner never calls an LLM or the network.

## Threats and mitigations

| # | Threat | Mitigation | Where |
| --- | --- | --- | --- |
| T1 | Prompt injection: source text steers the agent to run commands, change contracts, or exfiltrate data | Normalize raw sources into claim records (claim, applicability, provenance) before any proposer reads them; instructions and imperative text are dropped at normalization; contract surfaces are immutable to external content by construction (approval hash) | PR5 normalizer; existing `planning.py` hash gate |
| T2 | Contract steering: a source "recommends" changing the evaluator, metric, paths, or policy | Proposals may only produce hypotheses/candidates; any profile change re-renders the plan and invalidates approval (`approval is stale`) | existing; restated as invariant I1 |
| T3 | Unvetted code execution: copying code from a PR/paper into the worktree | `usage.mode: idea_only`, `code_reuse_allowed: false` by default; code blocks marked non-executable at normalization; execution stays argv-only under `environment.commands` | PR4 field, PR5 normalizer |
| T4 | Benchmark contamination / data leakage: sources reveal test answers or tuned-on-benchmark tricks | `prohibited_interpretations` on claim records; `knowledge_access` temporal cutoff policy (network phase); evaluation compatibility checks remain authoritative | PR5, Later |
| T5 | License violation: reusing incompatible code | `license` field on every source record (may be `unknown`); code reuse disabled initially; idea/mechanism use only | PR4 |
| T6 | Reproducibility loss: source content changes after the fact | Immutable `revision` and/or `content_sha256` required at registration; packs are content-addressed with `SHA256SUMS` (mirrors `vendor/` practice) | PR4, PR5 |
| T7 | Secret exposure via packs | `pack-verify` scans for secret-like fields; packs hold names/claims, never credentials (matches `required_env` names-only rule) | PR5 |
| T8 | Scope creep: retrieval quietly adds network access to a local-only loop | `policy.knowledge_access.allow_network` (distinct from `allow_remote`) defaults false and is approval-bound; v1 supports only `local_pack`; network retrieval is a later, separately approved phase | PR5, Later |
| T9 | Adaptive overfitting: repeated candidate selection against one validation metric | Out of scope for idea supply itself; tracked in the plan as a deferred guard (`confirmation_metric` / holdout for confirm-trace evaluation) — priority rises with throughput | Later |

## Invariants

- I1: External content can never modify commands, metric, evaluator, paths, policy, strategy, or approval state; only the user-approved plan hash can.
- I2: Every hypothesis keeps at least one recorded local `origin_evidence` entry; external sources are additive context, never a substitute.
- I3: The runner performs no LLM and no network calls; all generation is agent-side.
- I4: Individual sources are immutable after registration (revision + content hash); source *policy* is approval-bound, source *instances* are not.
- I5: Runner-side portfolio checks use only computable proxies over the stores; semantic judgments stay with the agent/critic, which filter but never authorize.
