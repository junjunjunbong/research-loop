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
