# Use one public Skill with an isolated deterministic runner

The plugin exposes one Agent Skill for setup, execution, and recovery while a Python runner owns inspection, validation, approval hashing, execution limits, metric parsing, and ledger updates. This keeps the user experience singular and conversational without making safety-critical state transitions depend on free-form agent behavior.

