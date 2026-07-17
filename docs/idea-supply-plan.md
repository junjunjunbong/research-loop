# Idea Supply development plan

Status: PR0 done (commit `8fb4184`); PR1 done (proposals module, CLI, tests, version 0.4.0). Next: PR2.
Baseline: commit `0d557f8`, package version 0.3.0, schema v2 campaigns. Test suite verified green at this commit (39 passed, 2026-07-17).
Origin: three-way design review (2026-07-17) of AIDE ML / Aiden techniques against this codebase. This plan supersedes the PR numbering used in that discussion; the mapping is listed at the end.

Goal: add an idea-supply front-end — slot-diverse proposal generation, external idea provenance, and local Knowledge Packs — without weakening the deterministic control plane (approval hash, Selectors, eligibility, authoritative metric parsing, append-only evidence).

## Verified code anchors

Future sessions should not re-derive these; they were verified against `0d557f8`.

| Fact | Anchor |
| --- | --- |
| `origin_evidence` must reference recorded experiments; no slot for external sources | `src/research_loop/hypotheses.py:100-105` |
| Hypothesis assessments: open / supported / contested / falsified | `src/research_loop/hypotheses.py:21` |
| Plan hash covers context, environment, evaluation, policy (+ strategy in v2) | `src/research_loop/planning.py:27-39` |
| Dry-run summary shows only argv, metric, scope, paths, base commit, strategy | `src/research_loop/planning.py:49-61` |
| Stale approval rejected when profile/command/policy/base commit change | `src/research_loop/planning.py:112-113` |
| Eligibility checks candidate's own hypothesis for `falsified`, not the source parents' hypotheses | `src/research_loop/candidates.py:228` |
| Recombine sources checked only for invalid/crash experiment status | `src/research_loop/candidates.py:238-241` |
| Same family+parent dedup only blocks while a sibling is `prepared` (serialization, not diversity) | `src/research_loop/candidates.py:242-250` |
| Explore quota applies only under `balanced` and only when an explore candidate exists | `src/research_loop/candidates.py:310-314` |
| Champion = max/min primary metric over valid rows (selection-bias surface) | `src/research_loop/candidates.py:201-210` |
| Runner contains no LLM or network calls (pure file/git/subprocess) | `src/research_loop/` (grep verified) |
| Recombine hard rules (two distinct sources, registered hypothesis, non-empty prediction/falsification, valid sources) already implemented | `src/research_loop/candidates.py:115-116,159-162`, `hypotheses.py:116-117` |
| External material vendored with content hashes already a house practice | `vendor/nvidia/SHA256SUMS` |
| Roadmap already names "research knowledge packs as hypothesis-generation inputs" | `docs/roadmap.md:40` |

## Design principles (converged)

1. **Boundary.** The runner performs only deterministic validation: schema checks, hashes, ledger joins, computable lint. Generation and interpretation are agent-side (skill). Execution authority stays with `candidate-rank` + the approval contract. A critic pass filters; it never authorizes.
2. **Approval boundary.** *How* knowledge may be accessed (`policy.knowledge_access`, `context.research_surface`, invariants) lives inside the plan hash and appears in the dry-run display. *Individual* sources are hash-pinned, append-only evidence: no re-approval per source, immutable after registration.
3. **Untrusted input.** External papers/PRs/issues are data, never instructions. They are normalized to claim records before any proposer sees them. External content can never modify commands, the primary metric, evaluator, allowed/protected paths, resource policy, the Strategy Contract, or approval state. External code is `idea_only`; no code reuse in the initial versions.
4. **Local grounding.** `origin_evidence` (a recorded local experiment) stays mandatory for every hypothesis. `idea_sources` explains where an idea came from; local evidence explains why it is worth testing here.
5. **Computable lint only.** Portfolio warnings are limited to proxies decidable from the stores (family/trace counts, assessment joins). No semantic judgments in the runner.
6. **No schema v3.** All persisted additions are optional fields tolerated by schema v2 readers (`add_hypothesis` constructs records field-by-field, so old stores simply lack new fields).

## Non-goals (deliberately not imported from AIDE)

Probabilistic debugging (`debug_prob`), pure greedy best-node search, LLM-parsed metrics from logs, plan+code generation in one call, LLM calls inside the runner, network retrieval before a threat model and approval policy exist.

## PR sequence

### PR0 — ADR + threat model (docs only) — DONE (`8fb4184`)
Deliverables: this plan, `docs/adr/0004-agent-side-idea-supply.md`, `docs/threat-model-external-knowledge.md`.
Acceptance: no behavior change; consistent with `CONTEXT.md` language.

### PR1 — Stateless proposal contract (runner) — DONE
New module `src/research_loop/proposals.py` + CLI wiring. Version bump to 0.4.0 (update README install pin per house practice).

- `proposal-validate --spec <file>`: validates a proposal file (shape below), cross-checks parents/hypotheses against the ledger and stores, stamps `context_hash` and `source_set_hash` via `canonical_hash`, returns normalized items plus per-item rejection reasons. **Writes nothing.**
- `portfolio-lint`: selector-aware, computable warnings over pending candidates and/or a proposal file:
  - L1: all eligible pending candidates share one family (warn under every selector; strongest under `balanced`).
  - L2: `balanced` selector at/near explore quota with no pending explore candidate.
  - L3: `diagnostic` selector while a hypothesis with assessment `open`/`contested` has no pending `diagnose` candidate in its family.
  - L4: recombine candidate whose source experiment's hypothesis is `falsified` and no `interaction_rationale` present.
  - L5: exact duplicate family+parent+operator among pending candidates.
- `proposal-context`: deterministic generation-context renderer (champion, per-family assessment summary from hypothesis events, families never touched, remaining budget, constraints). Reuses `scoped_evidence` internals; read-only.

Proposal shape (validated, not persisted):

```yaml
schema_version: 2
proposal_id: round-3
generated_by: {agent: "...", template_version: v1}   # optional; hashes stamped by runner
items:
  - slot: explore            # diagnose | exploit | explore | recombine | constraint
    hypothesis: {...}        # same fields hypothesis-add accepts
    candidate: {...}         # same fields candidate-add accepts
    intervention:
      changed_factor: "one string"
      held_constant: [...]
      expected_mechanism: "..."
      observable_signature: "..."
    idea_sources: [...]      # shape validated here; persisted only in PR4
```

Acceptance: pure functions, zero writes under `.research/`, deterministic output, tests for schema rejection + each lint rule (`tests/test_proposals.py`).

### PR2 — Skill-side portfolio generation + critic (docs/skill only)
- `SKILL.md` + `references/workflow.md`: generate per-slot (1 diagnose, 2 exploit, 1 explore, 1 recombine when eligible, 1 constraint-aware), run the critic checklist, then `proposal-validate` + `portfolio-lint`, show the dry run to the user, and only then `hypothesis-add`/`candidate-add`.
- New `references/proposal-guide.md`: slot definitions, critic checklist (falsifiable? duplicate? scope-valid? reward-hacking risk? one causal factor?), and the rule that `constraint` maps onto existing operators/traces (`debug` for invalid parents, `improve`/`exploit` or `explore` otherwise) — no new trace.
- No runner changes.

### PR3 — Recombine refinement (small runner change)
- Optional `interaction_rationale` field on recombine candidate specs, stored and surfaced.
- No new hard eligibility blocks (consensus: falsified-alone sources may ground a *new* interaction hypothesis). L4 in `portfolio-lint` is the enforcement surface.

### PR4 — Persisted external provenance (`idea_sources`)
- Optional `idea_sources` on hypothesis specs, validated in `hypotheses.py`: `source_type` ∈ {paper, pull_request, issue, user_note, repository_artifact}; non-empty `locator`; immutable `revision` and/or `content_sha256`; non-empty `claim` and `applicability`; `usage.mode` defaulting to `idea_only` with `code_reuse_allowed: false`; `license` field (may be `unknown`).
- `origin_evidence` remains mandatory (principle 4). `hypothesis-list` and checkpoint/handoff rendering show source summaries.
- Backward compatible with existing v2 stores.

### PR5 — Local Knowledge Pack
- Content-addressed pack (records + `SHA256SUMS`, mirroring `vendor/` practice) holding normalized claim records: `source_id`, `source_type`, `revision`, `content_sha256`, `claim`, `applicability_conditions`, `prohibited_interpretations`, `usage`, `license`.
- `policy.knowledge_access` in the profile (`mode: none | local_pack`, `allow_network: false`, `allowed_source_types`, `max_sources_per_round`, size caps). Approval-bound automatically via the policy section; extend the dry-run display (`planning.py`) to show it. `allow_network` is distinct from the existing `allow_remote` (execution); both default false.
- Runner `pack-verify`: existence, hashes, schema, allowed types, size limits, secret-like field scan. `proposal-validate` cross-checks `idea_sources` against a verified pack when one is configured.
- Skill: normalizer instructions (strip instructions from raw sources, extract claims, mark code blocks non-executable).

### PR6 — Research surface (independent track; any time after PR0)
- `context.research_surface` (editable_components, invariants, forbidden_data_flows) as *descriptive* data — automatically approval-bound via `context`; shown in the dry run.
- No executable commands here: verification runs only through existing `environment.commands` and evaluation compatibility parsers (trust-boundary rule from the review).

### Later (explicitly deferred)
- **Network retrieval** behind a new approval policy: allowed domains/source types, request budget, temporal cutoff / benchmark-contamination policy, content snapshotting, injection isolation.
- **Adaptive-overfitting guards**: optional `evaluation.confirmation_metric` (separate parser/path) used only by confirm-trace evaluation; secondary guardrail metrics. Low urgency at ≤6 experiments per campaign; first priority once idea supply raises throughput. Selection-bias surface is `champion_row`.
- **Score calibration** from historical outcomes: requires a cross-campaign store and metric comparability — a separate design, far later.

## Ubiquitous language (add to CONTEXT.md as each lands)

- **Proposal** (PR1): an agent-authored, runner-validated portfolio of hypothesis/candidate items that changes no state.
- **Portfolio Lint** (PR1): deterministic, selector-aware coverage warnings over pending candidates; advisory, never authorizing.
- **Idea Source** (PR4): a hash-pinned reference to external material that explains an idea's origin; never a substitute for local origin evidence.
- **Knowledge Pack** (PR5): a content-addressed, locally verified set of normalized claim records offered as optional hypothesis-generation input.
- **Research Surface** (PR6): the approved description of which components may change, the invariants that must hold, and forbidden data flows.

## Numbering map to the 2026-07-17 discussion

Discussion PR0 → PR0 here. Discussion PR1 (proposal schema + validator) → PR1. Discussion PR2 (skill generation) → PR2. Discussion PR3 (persisted provenance) → PR4. Discussion PR4 (knowledge pack) → PR5. Recombine refinement and research surface were folded out into PR3 and PR6.

## How to resume (handoff)

1. Read this file, then `git log --oneline -5` and `git status`.
2. Run `uv run pytest -q` and confirm the baseline is green before starting a PR. The suite exercises real git worktrees and subprocesses and takes several minutes; do not kill it at the first two-minute mark.
3. Pick the first unchecked PR above, implement within its stated boundary (runner vs skill), add tests, update this file's status line and check the box.
4. Runner-changing PRs bump the minor version and rebuild `dist/` per house practice; check the README install pin.
5. Do not fold multiple PRs into one commit; the sequence is the audit trail.

- [x] PR0 — ADR + threat model (commit `8fb4184`)
- [x] PR1 — stateless proposal contract (`proposals.py`, `proposal-validate` / `portfolio-lint` / `proposal-context`, `tests/test_proposals.py`, version 0.4.0 + dist; README install pin stays at `v0.3.0` until a `v0.4.0` release tag exists)
- [ ] PR2 — skill-side generation + critic
- [ ] PR3 — recombine refinement
- [ ] PR4 — persisted `idea_sources`
- [ ] PR5 — local Knowledge Pack
- [ ] PR6 — research surface
