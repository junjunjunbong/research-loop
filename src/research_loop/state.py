from __future__ import annotations

import csv
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from .errors import ResearchLoopError
from .git import add_local_exclude, git_info, repo_root, resolve_commit
from .schema import normalize_profile, split_profile, validate_profile
from .util import append_jsonl, canonical_hash, now_iso, read_json, read_yaml, write_json, write_yaml


V0_EXPERIMENT_COLUMNS = [
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

V1_EXTRA_EXPERIMENT_COLUMNS = [
    "primary_parent_id",
    "source_parent_ids",
    "operator",
    "trace",
    "family",
    "tree_hash",
    "parent_value",
    "champion_before_value",
    "delta_vs_baseline",
    "delta_vs_parent",
    "delta_vs_champion",
    "local_improvement",
    "new_champion",
    "target_reached",
    "confirmed",
]

EXPERIMENT_COLUMNS = V0_EXPERIMENT_COLUMNS
V1_EXPERIMENT_COLUMNS = V0_EXPERIMENT_COLUMNS + V1_EXTRA_EXPERIMENT_COLUMNS
V2_EXPERIMENT_COLUMNS = V1_EXPERIMENT_COLUMNS + ["selector"]

PROFILE_FILES = {
    "context": "research-context.yaml",
    "environment": "environment.yaml",
    "evaluation": "evaluation.yaml",
    "policy": "loop-policy.yaml",
}
STRATEGY_PROFILE_FILE = "research-strategy.yaml"


def research_dir(repo: Path) -> Path:
    return repo_root(repo) / ".research"


def _index_path(repo: Path) -> Path:
    return research_dir(repo) / "index.json"


def is_v1_control_plane(repo: Path) -> bool:
    return _index_path(repo).is_file()


def _read_index(repo: Path) -> Dict[str, Any]:
    path = _index_path(repo)
    if not path.exists():
        raise ResearchLoopError("v1 campaign index is missing")
    index = read_json(path)
    if index.get("schema_version") != 1 or not isinstance(index.get("campaigns"), dict):
        raise ResearchLoopError(f"invalid v1 campaign index: {path}")
    return index


def list_campaigns(repo: Path) -> Dict[str, Any]:
    if not is_v1_control_plane(repo):
        campaign_id = resolve_campaign_id(repo)
        return {
            "schema_version": 0,
            "active_campaign": campaign_id,
            "campaigns": {campaign_id: campaign_metadata(repo)},
        }
    return _read_index(repo)


def activate_campaign(repo: Path, campaign: str) -> Dict[str, Any]:
    index = _read_index(repo)
    if campaign not in index["campaigns"]:
        raise ResearchLoopError(f"unknown campaign: {campaign}")
    index["active_campaign"] = campaign
    write_json(_index_path(repo), index)
    return {"active_campaign": campaign, "campaign": index["campaigns"][campaign]}


def resolve_campaign_id(repo: Path, campaign: Optional[str] = None) -> str:
    root = research_dir(repo)
    if is_v1_control_plane(repo):
        index = _read_index(repo)
        selected = campaign or index.get("active_campaign")
        if not isinstance(selected, str) or selected not in index["campaigns"]:
            raise ResearchLoopError(f"unknown or inactive campaign: {selected!r}")
        return selected

    policy_path = root / "loop-policy.yaml"
    if not policy_path.exists():
        raise ResearchLoopError(f"Research Profile does not exist: {root}")
    document = read_yaml(policy_path)
    selected = document.get("policy", {}).get("campaign_id")
    if not isinstance(selected, str):
        raise ResearchLoopError(f"invalid v0 campaign policy: {policy_path}")
    if campaign is not None and campaign != selected:
        raise ResearchLoopError(f"v0 control plane contains only campaign {selected!r}")
    return selected


def campaign_dir(repo: Path, campaign: Optional[str] = None) -> Path:
    root = research_dir(repo)
    if is_v1_control_plane(repo):
        return root / "campaigns" / resolve_campaign_id(repo, campaign)
    resolve_campaign_id(repo, campaign)
    return root


def campaign_metadata(repo: Path, campaign: Optional[str] = None) -> Dict[str, Any]:
    campaign_id = resolve_campaign_id(repo, campaign)
    if is_v1_control_plane(repo):
        return dict(_read_index(repo)["campaigns"][campaign_id])
    plan_path = research_dir(repo) / "plan.json"
    if plan_path.exists():
        plan = read_json(plan_path)
        base_commit = plan.get("contract", {}).get("base_commit")
    else:
        base_commit = git_info(repo_root(repo)).get("commit")
    return {"campaign_id": campaign_id, "base_commit": base_commit, "profile_schema": 0}


def ensure_campaign_writable(repo: Path, campaign: Optional[str] = None) -> None:
    if is_v1_control_plane(repo):
        metadata = campaign_metadata(repo, campaign)
        if metadata.get("migrated_from") == 0:
            raise ResearchLoopError("migrated schema v0 campaigns are read-only; create a new versioned campaign")


def load_profile(repo: Path, campaign: Optional[str] = None) -> Dict[str, Any]:
    root = campaign_dir(repo, campaign)
    merged: Dict[str, Any] = {}
    version: Optional[int] = None
    for key, filename in PROFILE_FILES.items():
        path = root / filename
        if not path.exists():
            raise ResearchLoopError(f"missing Research Profile file: {path}")
        document = read_yaml(path)
        document_version = document.get("schema_version")
        if document_version not in {0, 1, 2} or key not in document:
            raise ResearchLoopError(f"invalid Research Profile document: {path}")
        if version is None:
            version = document_version
        elif version != document_version:
            raise ResearchLoopError("Research Profile documents use mixed schema versions")
        merged[key] = document[key]
    if version == 2:
        path = root / STRATEGY_PROFILE_FILE
        if not path.exists():
            raise ResearchLoopError(f"missing Research Profile file: {path}")
        document = read_yaml(path)
        if document.get("schema_version") != 2 or "strategy" not in document:
            raise ResearchLoopError(f"invalid Research Profile document: {path}")
        merged["strategy"] = document["strategy"]
    merged["schema_version"] = version
    validate_profile(merged, repo_root(repo))
    return merged


def _initialize_campaign(target: Path, profile: Dict[str, Any]) -> None:
    target.mkdir(parents=True)
    for filename, document in split_profile(profile).items():
        write_yaml(target / filename, document)
    (target / "runs").mkdir()
    if profile["schema_version"] == 2:
        columns = V2_EXPERIMENT_COLUMNS
    elif profile["schema_version"] == 1:
        columns = V1_EXPERIMENT_COLUMNS
    else:
        columns = V0_EXPERIMENT_COLUMNS
    with (target / "experiments.tsv").open("w", encoding="utf-8", newline="") as handle:
        csv.writer(handle, delimiter="\t").writerow(columns)
    (target / "hypotheses.md").write_text("# Hypotheses\n\nNo hypotheses have been prepared.\n", encoding="utf-8")
    if profile["schema_version"] in {1, 2}:
        (target / "candidates").mkdir()
        write_json(target / "candidates.json", {"schema_version": profile["schema_version"], "candidates": []})
    if profile["schema_version"] == 2:
        timestamp = now_iso()
        write_json(target / "hypotheses.json", {"schema_version": 2, "hypotheses": []})
        (target / "hypothesis-events.jsonl").write_text("", encoding="utf-8")
        strategy_state = {
            "schema_version": 2,
            "contract_hash": canonical_hash(profile["strategy"]),
            "active_selector": profile["strategy"]["initial_selector"],
            "applied_transition_ids": [],
            "updated_at": timestamp,
        }
        write_json(target / "strategy-state.json", strategy_state)
        (target / "strategy-events.jsonl").write_text("", encoding="utf-8")
        append_jsonl(
            target / "strategy-events.jsonl",
            {
                "event": "initialized",
                "selector": strategy_state["active_selector"],
                "contract_hash": strategy_state["contract_hash"],
                "created_at": timestamp,
            },
        )


def _write_initial_state(target: Path, profile: Dict[str, Any], base_commit: str, base_branch: str) -> None:
    timestamp = now_iso()
    (target / "state.md").write_text(
        "# Research State\n\n"
        f"- Updated: {timestamp}\n"
        "- Phase: setup\n"
        f"- Base branch: {base_branch}\n"
        f"- Base commit: {base_commit}\n"
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


def setup_project(repo: Path, profile_path: Path) -> Dict[str, Any]:
    root = repo_root(repo)
    profile = normalize_profile(read_yaml(profile_path.resolve()), root)
    validate_profile(profile, root)
    if profile["schema_version"] in {1, 2}:
        return new_campaign(root, profile_path=profile_path, base="HEAD")

    target = root / ".research"
    if target.exists():
        raise ResearchLoopError(f"Research Profile already exists: {target}")
    _initialize_campaign(target, profile)
    info = git_info(root)
    _write_initial_state(target, profile, info.get("commit") or "unborn", info.get("branch") or "unknown")
    add_local_exclude(root)
    return {
        "repo": str(root),
        "research_dir": str(target),
        "campaign_id": profile["policy"]["campaign_id"],
        "schema_version": 0,
        "next": "validate and render plan",
    }


def new_campaign(repo: Path, *, profile_path: Path, base: str = "HEAD") -> Dict[str, Any]:
    root = repo_root(repo)
    profile = normalize_profile(read_yaml(profile_path.resolve()), root)
    if profile.get("schema_version") not in {1, 2}:
        raise ResearchLoopError("new-campaign requires an explicit schema_version of 1 or 2")
    validate_profile(profile, root)
    campaign_id = profile["policy"]["campaign_id"]
    control = root / ".research"
    if control.exists() and not (control / "index.json").exists():
        raise ResearchLoopError("v0 control plane must be upgraded before adding a versioned campaign")
    control.mkdir(parents=True, exist_ok=True)
    target = control / "campaigns" / campaign_id
    if target.exists():
        raise ResearchLoopError(f"campaign already exists: {campaign_id}")
    base_commit = resolve_commit(root, base)
    _initialize_campaign(target, profile)
    info = git_info(root)
    _write_initial_state(target, profile, base_commit, base)

    if (control / "index.json").exists():
        index = _read_index(root)
    else:
        index = {"schema_version": 1, "active_campaign": campaign_id, "campaigns": {}}
    index["active_campaign"] = campaign_id
    index["campaigns"][campaign_id] = {
        "campaign_id": campaign_id,
        "base_commit": base_commit,
        "base_ref": base,
        "profile_schema": profile["schema_version"],
        "created_at": now_iso(),
    }
    write_json(control / "index.json", index)
    add_local_exclude(root)
    return {
        "repo": str(root),
        "research_dir": str(target),
        "campaign_id": campaign_id,
        "schema_version": profile["schema_version"],
        "base_commit": base_commit,
        "next": "validate and render plan",
    }


def read_ledger(repo: Path, campaign: Optional[str] = None) -> List[Dict[str, str]]:
    path = campaign_dir(repo, campaign) / "experiments.tsv"
    if not path.exists():
        raise ResearchLoopError(f"missing Research Ledger: {path}")
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def ledger_columns(repo: Path, campaign: Optional[str] = None) -> List[str]:
    path = campaign_dir(repo, campaign) / "experiments.tsv"
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle, delimiter="\t")
        return next(reader)


def profile_validation(repo: Path, campaign: Optional[str] = None) -> Dict[str, Any]:
    root = repo_root(repo)
    profile = load_profile(root, campaign)
    info = git_info(root)
    metadata = campaign_metadata(root, campaign)
    return {
        "valid": True,
        "schema_version": profile["schema_version"],
        "campaign_id": resolve_campaign_id(root, campaign),
        "campaign_ready": bool(info["clean"] and metadata.get("base_commit")),
        "base_commit": metadata.get("base_commit"),
        "git": info,
        "warnings": [] if info["clean"] else ["base worktree is dirty; setup is valid but campaign execution is blocked"],
    }


def upgrade_status(repo: Path) -> Dict[str, Any]:
    root = repo_root(repo)
    control = root / ".research"
    if (control / "index.json").exists():
        return {"upgrade_required": False, "schema_version": 1, "blockers": []}
    if not control.exists():
        raise ResearchLoopError("no Research Profile exists to upgrade")
    campaign_id = resolve_campaign_id(root)
    expected = set(PROFILE_FILES.values()) | {
        "runs",
        "experiments.tsv",
        "hypotheses.md",
        "state.md",
        "handoff.md",
        "plan.json",
        "approval.json",
    }
    unknown = sorted(path.name for path in control.iterdir() if path.name not in expected)
    run_campaigns = sorted(path.name for path in (control / "runs").iterdir()) if (control / "runs").exists() else []
    blockers = []
    if unknown:
        blockers.append(f"unknown top-level entries: {', '.join(unknown)}")
    extra_runs = [name for name in run_campaigns if name != campaign_id]
    if extra_runs:
        blockers.append(f"run directories do not match active v0 campaign: {', '.join(extra_runs)}")
    return {
        "upgrade_required": True,
        "schema_version": 0,
        "campaign_id": campaign_id,
        "blockers": blockers,
        "ready": not blockers,
    }


def _rewrite_migrated_paths(target: Path, old_runs: Path, new_runs: Path) -> None:
    old = str(old_runs)
    new = str(new_runs)
    for path in target.rglob("*"):
        if not path.is_file() or path.suffix not in {".json", ".tsv", ".md"}:
            continue
        text = path.read_text(encoding="utf-8")
        if old in text:
            path.write_text(text.replace(old, new), encoding="utf-8")


def upgrade_control_plane(repo: Path, *, apply: bool = False) -> Dict[str, Any]:
    root = repo_root(repo)
    status = upgrade_status(root)
    if not status.get("upgrade_required") or not apply:
        return status
    if status["blockers"]:
        raise ResearchLoopError("v0 upgrade is blocked: " + "; ".join(status["blockers"]))

    control = root / ".research"
    campaign_id = status["campaign_id"]
    profile = load_profile(root)
    metadata = campaign_metadata(root)
    staged = Path(tempfile.mkdtemp(prefix=".research-upgrade-", dir=str(root)))
    backup = root / f".research-v0-backup-{os.getpid()}"
    campaign_target = staged / "campaigns" / campaign_id
    campaign_target.mkdir(parents=True)
    try:
        for filename in PROFILE_FILES.values():
            shutil.copy2(control / filename, campaign_target / filename)
        for filename in ("experiments.tsv", "hypotheses.md", "state.md", "handoff.md", "plan.json", "approval.json"):
            source = control / filename
            if source.exists():
                shutil.copy2(source, campaign_target / filename)
        source_runs = control / "runs" / campaign_id
        if source_runs.exists():
            shutil.copytree(source_runs, campaign_target / "runs")
        else:
            (campaign_target / "runs").mkdir()
        (campaign_target / "candidates").mkdir()
        write_json(campaign_target / "candidates.json", {"schema_version": 1, "candidates": []})
        write_json(
            staged / "index.json",
            {
                "schema_version": 1,
                "active_campaign": campaign_id,
                "campaigns": {
                    campaign_id: {
                        "campaign_id": campaign_id,
                        "base_commit": metadata.get("base_commit"),
                        "base_ref": metadata.get("base_commit"),
                        "profile_schema": profile["schema_version"],
                        "migrated_from": 0,
                        "created_at": now_iso(),
                    }
                },
            },
        )
        _rewrite_migrated_paths(
            campaign_target,
            control / "runs" / campaign_id,
            control / "campaigns" / campaign_id / "runs",
        )
        os.replace(control, backup)
        try:
            os.replace(staged, control)
        except Exception:
            os.replace(backup, control)
            raise
        shutil.rmtree(backup, ignore_errors=True)
    except Exception:
        shutil.rmtree(staged, ignore_errors=True)
        if backup.exists() and not control.exists():
            os.replace(backup, control)
        raise
    return {
        "upgrade_required": False,
        "schema_version": 1,
        "campaign_id": campaign_id,
        "migrated": True,
        "research_dir": str(control / "campaigns" / campaign_id),
    }
