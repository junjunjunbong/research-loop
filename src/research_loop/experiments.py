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
from .state import campaign_dir, ensure_campaign_writable, is_v1_control_plane, load_profile, read_ledger
from .util import now_iso, run, write_json


def experiment_dir(repo: Path, experiment_id: str, campaign: Optional[str] = None) -> Path:
    profile = load_profile(repo, campaign)
    root = campaign_dir(repo, campaign) / "runs"
    if profile["schema_version"] == 0 and not is_v1_control_plane(repo):
        root = root / profile["policy"]["campaign_id"]
    return root / experiment_id


def prepare_experiment(
    repo: Path,
    *,
    experiment_id: str,
    hypothesis: Optional[str],
    hypothesis_id: Optional[str] = None,
    parent: Optional[str] = None,
    baseline: bool = False,
    candidate_id: Optional[str] = None,
    campaign: Optional[str] = None,
) -> Dict[str, Any]:
    root = repo_root(repo)
    ensure_campaign_writable(root, campaign)
    ensure_approved(root, campaign)
    profile = load_profile(root, campaign)
    experiment_id = validate_slug(experiment_id, "experiment_id")
    hypothesis_id = validate_slug(hypothesis_id or experiment_id, "hypothesis_id")
    rows = read_ledger(root, campaign)
    if any(row.get("experiment_id") == experiment_id for row in rows):
        raise ResearchLoopError(f"experiment is already recorded: {experiment_id}")
    if baseline and any(row.get("kind") == "baseline" for row in rows):
        raise ResearchLoopError("a baseline is already recorded")
    attempted = sum(1 for row in rows if row.get("kind") != "baseline")
    if not baseline and attempted >= profile["policy"]["max_experiments"]:
        raise ResearchLoopError("campaign experiment budget is exhausted")

    target_dir = experiment_dir(root, experiment_id, campaign)
    if target_dir.exists():
        raise ResearchLoopError(f"experiment state already exists: {target_dir}")
    contract = build_contract(root, campaign)
    candidate: Optional[Dict[str, Any]] = None
    if profile["schema_version"] == 1 and not baseline:
        if not candidate_id:
            raise ResearchLoopError("schema_version 1 experiments require --candidate-id")
        if parent is not None:
            raise ResearchLoopError("--parent cannot be combined with --candidate-id")
        from .candidates import get_candidate, rank_candidates

        candidate = get_candidate(root, candidate_id, campaign)
        ranking = rank_candidates(root, campaign)
        if ranking["recommended_candidate_id"] != candidate_id:
            raise ResearchLoopError(
                f"candidate is not the current deterministic recommendation: {ranking['recommended_candidate_id']!r}"
            )
        parent_row = next(
            (row for row in rows if row.get("experiment_id") == candidate["primary_parent_id"]),
            None,
        )
        if parent_row is None or not parent_row.get("commit"):
            raise ResearchLoopError(f"candidate parent is not a recorded commit: {candidate['primary_parent_id']}")
        parent_value = parent_row["commit"]
        hypothesis_id = candidate["hypothesis_id"]
        hypothesis = candidate["statement"]
    else:
        if not isinstance(hypothesis, str) or not hypothesis.strip():
            raise ResearchLoopError("hypothesis must be non-empty")
        parent_value = parent or contract["base_commit"]
    parent_commit = resolve_commit(root, parent_value)
    campaign_id = profile["policy"]["campaign_id"]
    branch = f"{profile['policy']['branch_prefix']}/{campaign_id}/{experiment_id}"
    worktree = cache_worktree_root(root, campaign_id) / experiment_id
    create_worktree(root, branch=branch, destination=worktree, parent=parent_commit)

    if baseline:
        run(["git", "commit", "--allow-empty", "-m", "baseline: record starting point"], cwd=worktree)
    elif candidate and candidate["operator"] == "confirm":
        run(["git", "commit", "--allow-empty", "-m", f"experiment: confirm {hypothesis_id}"], cwd=worktree)

    target_dir.mkdir(parents=True)
    metadata = {
        "schema_version": profile["schema_version"],
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
    if candidate:
        metadata.update(
            {
                "candidate_id": candidate["candidate_id"],
                "primary_parent_id": candidate["primary_parent_id"],
                "source_parent_ids": candidate["source_parent_ids"],
                "operator": candidate["operator"],
                "trace": candidate["trace"],
                "family": candidate["family"],
                "priority": candidate["priority"],
            }
        )
    else:
        metadata.update(
            {
                "primary_parent_id": "" if baseline else None,
                "source_parent_ids": [],
                "operator": "baseline" if baseline else "improve",
                "trace": "baseline" if baseline else "exploit",
                "family": "baseline" if baseline else hypothesis_id,
            }
        )
    write_json(target_dir / "experiment.json", metadata)
    hypotheses = campaign_dir(root, campaign) / "hypotheses.md"
    with hypotheses.open("a", encoding="utf-8") as handle:
        handle.write(
            f"\n## {experiment_id}\n\n"
            f"- Hypothesis ID: `{metadata['hypothesis_id']}`\n"
            f"- Kind: `{metadata['kind']}`\n"
            f"- Branch: `{branch}`\n"
            f"- Parent: `{parent_commit}`\n"
            f"- Primary parent ID: `{metadata.get('primary_parent_id', '')}`\n"
            f"- Operator / trace / family: `{metadata['operator']}` / `{metadata['trace']}` / `{metadata['family']}`\n"
            f"- Statement: {hypothesis.strip()}\n"
        )
    if candidate:
        from .candidates import mark_candidate_prepared

        mark_candidate_prepared(root, candidate_id, experiment_id, campaign)
    return metadata
