# Separate experiment provenance, selection strategy, and hypothesis evidence

Research Loop keeps the Experiment DAG as immutable provenance, moves next-experiment choice into an approved Strategy Contract with deterministic Selectors, and records hypothesis interpretation as separate agent-authored evidence events. This separation preserves auditability without pretending that Git ancestry, metric optimization, and scientific belief updates are the same problem; schema v1 campaigns remain unchanged, while schema v2 makes the new boundary explicit.
