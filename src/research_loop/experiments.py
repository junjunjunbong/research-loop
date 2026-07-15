from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from .errors import ResearchLoopError
from .git import (
    cache_worktree_root,
    create_worktree,
    repo_root,
    resolve_commit,
    validate_slug,
    worktree_head,
)
from .planning import build_contract, ensure_approved
from .state import load_profile, read_ledger, research_dir
from .util import now_iso, run, write_json


def experiment_dir(repo: Path, experiment_id: str) -> Path:
    profile = load_profile(repo)
    return research_dir(repo) / "runs" / profile["policy"]["campaign_id"] / experiment_id


def prepare_experiment(
    repo: Path,
    *,
    experiment_id: str,
    hypothesis: str,
    hypothesis_id: Optional[str] = None,
    parent: Optional[str] = None,
    baseline: bool = False,
) -> Dict[str, Any]:
    root = repo_root(repo)
    ensure_approved(root)
    profile = load_profile(root)
    experiment_id = validate_slug(experiment_id, "experiment_id")
    hypothesis_id = validate_slug(hypothesis_id or experiment_id, "hypothesis_id")
    if not hypothesis.strip():
        raise ResearchLoopError("hypothesis must be non-empty")

    rows = read_ledger(root)
    if any(row.get("experiment_id") == experiment_id for row in rows):
        raise ResearchLoopError(f"experiment is already recorded: {experiment_id}")
    if baseline and any(row.get("kind") == "baseline" for row in rows):
        raise ResearchLoopError("a baseline is already recorded")
    attempted = sum(1 for row in rows if row.get("kind") != "baseline")
    if not baseline and attempted >= profile["policy"]["max_experiments"]:
        raise ResearchLoopError("campaign experiment budget is exhausted")

    target_dir = experiment_dir(root, experiment_id)
    if target_dir.exists():
        raise ResearchLoopError(f"experiment state already exists: {target_dir}")
    contract = build_contract(root)
    parent_value = parent or contract["base_commit"]
    parent_commit = resolve_commit(root, parent_value)
    campaign_id = profile["policy"]["campaign_id"]
    branch = f"{profile['policy']['branch_prefix']}/{campaign_id}/{experiment_id}"
    worktree = cache_worktree_root(root, campaign_id) / experiment_id
    create_worktree(root, branch=branch, destination=worktree, parent=parent_commit)

    if baseline:
        run(["git", "commit", "--allow-empty", "-m", "baseline: record starting point"], cwd=worktree)

    target_dir.mkdir(parents=True)
    metadata = {
        "schema_version": 0,
        "experiment_id": experiment_id,
        "hypothesis_id": "baseline" if baseline else hypothesis_id,
        "hypothesis": hypothesis,
        "kind": "baseline" if baseline else "experiment",
        "branch": branch,
        "parent_commit": parent_commit,
        "prepared_commit": worktree_head(worktree),
        "worktree": str(worktree),
        "prepared_at": now_iso(),
    }
    write_json(target_dir / "experiment.json", metadata)
    hypotheses = research_dir(root) / "hypotheses.md"
    with hypotheses.open("a", encoding="utf-8") as handle:
        handle.write(
            f"\n## {experiment_id}\n\n"
            f"- Hypothesis ID: `{metadata['hypothesis_id']}`\n"
            f"- Kind: `{metadata['kind']}`\n"
            f"- Branch: `{branch}`\n"
            f"- Parent: `{parent_commit}`\n"
            f"- Statement: {hypothesis.strip()}\n"
        )
    return metadata

