from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Dict, List

from .errors import ResearchLoopError
from .git import add_local_exclude, git_info, repo_root
from .schema import normalize_profile, split_profile, validate_profile
from .util import now_iso, read_yaml, write_yaml


EXPERIMENT_COLUMNS = [
    "index",
    "experiment_id",
    "hypothesis_id",
    "kind",
    "branch",
    "parent_commit",
    "commit",
    "metric_name",
    "metric_value",
    "baseline_value",
    "delta",
    "elapsed_seconds",
    "command",
    "log_path",
    "status",
    "description",
    "compatibility_hash",
    "created_at",
]


def research_dir(repo: Path) -> Path:
    return repo_root(repo) / ".research"


def load_profile(repo: Path) -> Dict[str, Any]:
    root = research_dir(repo)
    filenames = {
        "context": "research-context.yaml",
        "environment": "environment.yaml",
        "evaluation": "evaluation.yaml",
        "policy": "loop-policy.yaml",
    }
    merged: Dict[str, Any] = {"schema_version": 0}
    for key, filename in filenames.items():
        path = root / filename
        if not path.exists():
            raise ResearchLoopError(f"missing Research Profile file: {path}")
        document = read_yaml(path)
        if document.get("schema_version") != 0 or key not in document:
            raise ResearchLoopError(f"invalid Research Profile document: {path}")
        merged[key] = document[key]
    validate_profile(merged, repo_root(repo))
    return merged


def setup_project(repo: Path, profile_path: Path) -> Dict[str, Any]:
    root = repo_root(repo)
    target = root / ".research"
    if target.exists():
        raise ResearchLoopError(f"Research Profile already exists: {target}")
    profile = normalize_profile(read_yaml(profile_path.resolve()), root)
    validate_profile(profile, root)
    target.mkdir(parents=True)
    for filename, document in split_profile(profile).items():
        write_yaml(target / filename, document)
    (target / "runs").mkdir()
    with (target / "experiments.tsv").open("w", encoding="utf-8", newline="") as handle:
        csv.writer(handle, delimiter="\t").writerow(EXPERIMENT_COLUMNS)
    (target / "hypotheses.md").write_text(
        "# Hypotheses\n\nNo hypotheses have been prepared.\n",
        encoding="utf-8",
    )
    info = git_info(root)
    timestamp = now_iso()
    (target / "state.md").write_text(
        "# Research State\n\n"
        f"- Updated: {timestamp}\n"
        "- Phase: setup\n"
        f"- Base branch: {info.get('branch') or 'unknown'}\n"
        f"- Base commit: {info.get('commit') or 'unborn'}\n"
        "- Approval: pending\n"
        "- Latest result: none\n",
        encoding="utf-8",
    )
    (target / "handoff.md").write_text(
        "# Handoff\n\n"
        "## Resume From Here\n"
        "Validate the generated Research Profile, render the dry-run plan, and obtain campaign approval.\n\n"
        "## Next Actions\n"
        "- Run `research-loop validate`.\n"
        "- Run `research-loop plan` and present the exact plan to the user.\n\n"
        "## Watch Outs\n"
        "- Do not execute experiments before the plan hash is approved.\n",
        encoding="utf-8",
    )
    add_local_exclude(root)
    return {
        "repo": str(root),
        "research_dir": str(target),
        "campaign_id": profile["policy"]["campaign_id"],
        "next": "validate and render plan",
    }


def read_ledger(repo: Path) -> List[Dict[str, str]]:
    path = research_dir(repo) / "experiments.tsv"
    if not path.exists():
        raise ResearchLoopError(f"missing Research Ledger: {path}")
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    return rows


def profile_validation(repo: Path) -> Dict[str, Any]:
    root = repo_root(repo)
    profile = load_profile(root)
    info = git_info(root)
    return {
        "valid": True,
        "schema_version": profile["schema_version"],
        "campaign_ready": bool(info["clean"] and info["commit"]),
        "git": info,
        "warnings": [] if info["clean"] else ["base worktree is dirty; setup is valid but campaign execution is blocked"],
    }

