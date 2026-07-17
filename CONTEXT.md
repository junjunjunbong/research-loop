# Research Loop

Research Loop turns an existing research project and a researcher's intent into a bounded, auditable experiment campaign.

## Language

**Research Goal**:
The researcher's desired outcome, success criteria, preferences, and constraints expressed for one project.
_Avoid_: Domain module, research recipe

**Research Profile**:
The project-specific, generated representation of a Research Goal plus verified project facts.
_Avoid_: User-authored configuration, domain module

**Execution Contract**:
The approved description of how this project can be run, including commands, working directory, resource class, and limits.
_Avoid_: Environment adapter

**Evaluation Contract**:
The approved description of the authoritative metric source, comparison direction, compatibility checks, and confirmation policy.
_Avoid_: Evaluator module

**Research Strategy**:
The approved approach for choosing among eligible hypothesis-driven Experiments for one Campaign.
_Avoid_: Search algorithm, DAG policy

**Strategy Contract**:
The approved representation of the project shape, initial Selector, rationale, and deterministic Selector transitions.
_Avoid_: Loop Policy, agent preference

**Selector**:
The deterministic policy that scores and recommends the next eligible Experiment candidate under a Strategy Contract.
_Avoid_: Strategy, LLM judgment

**Hypothesis Evidence**:
An auditable observation from a recorded Experiment together with the agent's explicit assessment of how it bears on a Hypothesis.
_Avoid_: Performance result, metric status

**Campaign**:
One approved sequence consisting of a baseline and a bounded number of related Experiments.
_Avoid_: Session, run

**Experiment**:
One minimal, hypothesis-driven project change evaluated against a deliberate parent result.
_Avoid_: Trial, arbitrary code change

**Research Ledger**:
The append-only record that connects every attempted Experiment to its branch, command, artifacts, metric, and decision.
_Avoid_: Log file, notes

**Proposal**:
An agent-authored, runner-validated portfolio of hypothesis and candidate items that changes no state until its accepted items are registered.
_Avoid_: Plan, batch of guesses

**Portfolio Lint**:
Deterministic, Selector-aware coverage warnings over pending and proposed candidates; advisory, never authorizing.
_Avoid_: Critic, gate

**Idea Source**:
A hash-pinned reference to external material that explains where an idea came from; never a substitute for recorded local origin evidence.
_Avoid_: Citation, imported solution

**Knowledge Pack**:
The content-addressed, locally verified set of normalized claim records offered as optional hypothesis-generation input, filled by the user or by approved Agent Retrieval.
_Avoid_: Cache, scraped corpus

**Agent Retrieval**:
The approved, agent-side search-and-normalize workflow that fills a Knowledge Pack from external papers, pull requests, and issues; the runner never fetches.
_Avoid_: Runner network access, web crawling

**Research Surface**:
The approved description of which components may change, the invariants that must hold, and the data flows that are forbidden.
_Avoid_: Allowed paths, executable checks
