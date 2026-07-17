from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from .errors import ResearchLoopError
from .git import ensure_clean, git_info, repo_root
from .state import (
    campaign_dir,
    campaign_metadata,
    ensure_campaign_writable,
    load_profile,
    read_ledger,
    resolve_campaign_id,
)
from .util import canonical_hash, now_iso, read_json, write_json


def build_contract(repo: Path, campaign: Optional[str] = None) -> Dict[str, Any]:
    root = repo_root(repo)
    profile = load_profile(root, campaign)
    info = git_info(root)
    metadata = campaign_metadata(root, campaign)
    base_commit = metadata.get("base_commit") if profile["schema_version"] in {1, 2} else info.get("commit")
    if not base_commit:
        raise ResearchLoopError("a committed base revision is required before planning")
    contract = {
        "schema_version": profile["schema_version"],
        "repo": str(root),
        "campaign_id": resolve_campaign_id(root, campaign),
        "base_commit": base_commit,
        "context": profile["context"],
        "environment": profile["environment"],
        "evaluation": profile["evaluation"],
        "policy": profile["policy"],
    }
    if profile["schema_version"] == 2:
        contract["strategy"] = profile["strategy"]
    return contract


def build_plan(repo: Path, campaign: Optional[str] = None) -> Dict[str, Any]:
    root = repo_root(repo)
    ensure_clean(root)
    contract = build_contract(root, campaign)
    rows = read_ledger(root, campaign)
    baseline_required = not any(row.get("kind") == "baseline" for row in rows)
    plan_hash = canonical_hash(contract)
    dry_run = {
        "baseline_required": baseline_required,
        "max_experiments": contract["policy"]["max_experiments"],
        "smoke_argv": contract["environment"]["commands"]["smoke"],
        "full_argv": contract["environment"]["commands"]["full"],
        "primary_metric": contract["evaluation"]["primary_metric"],
        "resource_class": contract["environment"]["resource_class"],
        "modification_scope": contract["context"].get("allowed_paths", []),
        "protected_paths": contract["context"].get("protected_paths", []),
        "base_commit": contract["base_commit"],
    }
    if contract["schema_version"] == 2:
        dry_run["strategy"] = contract["strategy"]
    return {
        "schema_version": contract["schema_version"],
        "generated_at": now_iso(),
        "plan_hash": plan_hash,
        "contract": contract,
        "dry_run": dry_run,
    }


def save_plan(repo: Path, campaign: Optional[str] = None) -> Dict[str, Any]:
    ensure_campaign_writable(repo, campaign)
    plan = build_plan(repo, campaign)
    write_json(campaign_dir(repo, campaign) / "plan.json", plan)
    return plan


def approve_plan(repo: Path, plan_hash: str, campaign: Optional[str] = None) -> Dict[str, Any]:
    root = repo_root(repo)
    ensure_campaign_writable(root, campaign)
    plan_path = campaign_dir(root, campaign) / "plan.json"
    if not plan_path.exists():
        raise ResearchLoopError("no dry-run plan exists; run plan first")
    stored = read_json(plan_path)
    current = build_plan(root, campaign)
    if stored.get("plan_hash") != plan_hash:
        raise ResearchLoopError("provided plan hash does not match the rendered dry-run plan")
    if current["plan_hash"] != plan_hash:
        raise ResearchLoopError("Research Profile or base commit changed after planning; render a new plan")
    if current["schema_version"] == 2:
        from .strategy import initialize_strategy_state

        initialize_strategy_state(root, campaign)
    approval = {
        "schema_version": current["schema_version"],
        "plan_hash": plan_hash,
        "approved_at": now_iso(),
        "scope": f"one local schema v{current['schema_version']} campaign",
    }
    write_json(campaign_dir(root, campaign) / "approval.json", approval)
    return approval


def ensure_approved(repo: Path, campaign: Optional[str] = None) -> Dict[str, Any]:
    root = repo_root(repo)
    ensure_clean(root)
    approval_path = campaign_dir(root, campaign) / "approval.json"
    if not approval_path.exists():
        raise ResearchLoopError("campaign is not approved")
    approval = read_json(approval_path)
    current = build_plan(root, campaign)
    if approval.get("plan_hash") != current["plan_hash"]:
        raise ResearchLoopError("approval is stale because the profile, command, policy, or base commit changed")
    return approval
