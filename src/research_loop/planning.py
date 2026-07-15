from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from .errors import ResearchLoopError
from .git import ensure_clean, git_info, repo_root
from .state import load_profile, read_ledger, research_dir
from .util import canonical_hash, now_iso, read_json, write_json


def build_contract(repo: Path) -> Dict[str, Any]:
    root = repo_root(repo)
    profile = load_profile(root)
    info = git_info(root)
    if not info["commit"]:
        raise ResearchLoopError("a committed base revision is required before planning")
    return {
        "schema_version": 0,
        "repo": str(root),
        "base_commit": info["commit"],
        "context": profile["context"],
        "environment": profile["environment"],
        "evaluation": profile["evaluation"],
        "policy": profile["policy"],
    }


def build_plan(repo: Path) -> Dict[str, Any]:
    root = repo_root(repo)
    ensure_clean(root)
    contract = build_contract(root)
    rows = read_ledger(root)
    baseline_required = not any(row.get("kind") == "baseline" for row in rows)
    plan_hash = canonical_hash(contract)
    return {
        "schema_version": 0,
        "generated_at": now_iso(),
        "plan_hash": plan_hash,
        "contract": contract,
        "dry_run": {
            "baseline_required": baseline_required,
            "max_experiments": contract["policy"]["max_experiments"],
            "smoke_argv": contract["environment"]["commands"]["smoke"],
            "full_argv": contract["environment"]["commands"]["full"],
            "primary_metric": contract["evaluation"]["primary_metric"],
            "resource_class": contract["environment"]["resource_class"],
            "modification_scope": contract["context"].get("allowed_paths", []),
            "protected_paths": contract["context"].get("protected_paths", []),
        },
    }


def save_plan(repo: Path) -> Dict[str, Any]:
    plan = build_plan(repo)
    write_json(research_dir(repo) / "plan.json", plan)
    return plan


def approve_plan(repo: Path, plan_hash: str) -> Dict[str, Any]:
    root = repo_root(repo)
    plan_path = research_dir(root) / "plan.json"
    if not plan_path.exists():
        raise ResearchLoopError("no dry-run plan exists; run plan first")
    stored = read_json(plan_path)
    current = build_plan(root)
    if stored.get("plan_hash") != plan_hash:
        raise ResearchLoopError("provided plan hash does not match the rendered dry-run plan")
    if current["plan_hash"] != plan_hash:
        raise ResearchLoopError("Research Profile or base commit changed after planning; render a new plan")
    approval = {
        "schema_version": 0,
        "plan_hash": plan_hash,
        "approved_at": now_iso(),
        "scope": "one local v0 campaign",
    }
    write_json(research_dir(root) / "approval.json", approval)
    return approval


def ensure_approved(repo: Path) -> Dict[str, Any]:
    root = repo_root(repo)
    ensure_clean(root)
    approval_path = research_dir(root) / "approval.json"
    if not approval_path.exists():
        raise ResearchLoopError("campaign is not approved")
    approval = read_json(approval_path)
    current = build_plan(root)
    if approval.get("plan_hash") != current["plan_hash"]:
        raise ResearchLoopError("approval is stale because the profile, command, policy, or base commit changed")
    return approval
