from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Dict, Optional

from .errors import ResearchLoopError
from .experiments import experiment_dir
from .git import repo_root
from .planning import ensure_approved
from .schema import VALID_STATUSES
from .state import (
    campaign_dir,
    ensure_campaign_writable,
    ledger_columns,
    load_profile,
    read_ledger,
    resolve_campaign_id,
)
from .util import now_iso, read_json


def checkpoint(
    repo: Path,
    *,
    current: str,
    next_action: str,
    campaign: Optional[str] = None,
) -> Dict[str, Any]:
    root = repo_root(repo)
    ensure_campaign_writable(root, campaign)
    target = campaign_dir(root, campaign)
    profile = load_profile(root, campaign)
    rows = read_ledger(root, campaign)
    latest = rows[-1] if rows else None
    timestamp = now_iso()
    approval = "approved" if (target / "approval.json").exists() else "pending"
    (target / "state.md").write_text(
        "# Research State\n\n"
        f"- Updated: {timestamp}\n"
        f"- Phase: {current}\n"
        f"- Campaign: {profile['policy']['campaign_id']}\n"
        f"- Approval: {approval}\n"
        f"- Attempted rows: {len(rows)}\n"
        f"- Latest result: {latest['experiment_id'] + ' / ' + latest['status'] if latest else 'none'}\n",
        encoding="utf-8",
    )
    (target / "handoff.md").write_text(
        "# Handoff\n\n"
        "## Resume From Here\n"
        f"Campaign `{profile['policy']['campaign_id']}` is in phase `{current}` with {len(rows)} recorded rows.\n\n"
        "## Next Actions\n"
        f"- {next_action}\n\n"
        "## Watch Outs\n"
        "- Re-run `research-loop status` and verify Git state before continuing.\n"
        "- Approval becomes stale if the profile, approved command, policy, or base commit changes.\n",
        encoding="utf-8",
    )
    return {"updated_at": timestamp, "current": current, "next": next_action, "rows": len(rows)}


def record_experiment(
    repo: Path,
    *,
    experiment_id: str,
    description: Optional[str] = None,
    campaign: Optional[str] = None,
) -> Dict[str, str]:
    root = repo_root(repo)
    ensure_campaign_writable(root, campaign)
    ensure_approved(root, campaign)
    profile = load_profile(root, campaign)
    exp_dir = experiment_dir(root, experiment_id, campaign)
    metadata = read_json(exp_dir / "experiment.json")
    manifest = read_json(exp_dir / "full" / "manifest.json")
    evaluation = read_json(exp_dir / "full" / "evaluation.json")
    rows = read_ledger(root, campaign)
    if any(row.get("experiment_id") == experiment_id for row in rows):
        raise ResearchLoopError(f"experiment is already recorded: {experiment_id}")
    status = evaluation.get("status")
    if status not in VALID_STATUSES:
        raise ResearchLoopError(f"cannot record unsupported status: {status}")
    row = {
        "index": str(len(rows) + 1),
        "experiment_id": experiment_id,
        "hypothesis_id": metadata["hypothesis_id"],
        "kind": metadata["kind"],
        "branch": metadata["branch"],
        "parent_commit": metadata["parent_commit"],
        "commit": manifest["commit"],
        "metric_name": evaluation["metric_name"],
        "metric_value": "" if evaluation.get("metric_value") is None else str(evaluation["metric_value"]),
        "baseline_value": "" if evaluation.get("baseline_value") is None else str(evaluation["baseline_value"]),
        "delta": "" if evaluation.get("delta") is None else str(evaluation["delta"]),
        "elapsed_seconds": str(manifest["elapsed_seconds"]),
        "command": json.dumps(manifest["command"], ensure_ascii=False, separators=(",", ":")),
        "log_path": manifest["log_path"],
        "status": status,
        "description": description or "; ".join(evaluation.get("reasons", [])),
        "compatibility_hash": evaluation["compatibility_hash"],
        "created_at": now_iso(),
    }
    if profile["schema_version"] in {1, 2}:
        row.update(
            {
                "primary_parent_id": metadata.get("primary_parent_id", ""),
                "source_parent_ids": json.dumps(metadata.get("source_parent_ids", []), separators=(",", ":")),
                "operator": metadata.get("operator", ""),
                "trace": metadata.get("trace", ""),
                "family": metadata.get("family", ""),
                "tree_hash": manifest.get("tree_hash", ""),
                "parent_value": "" if evaluation.get("parent_value") is None else str(evaluation["parent_value"]),
                "champion_before_value": ""
                if evaluation.get("champion_before_value") is None
                else str(evaluation["champion_before_value"]),
                "delta_vs_baseline": ""
                if evaluation.get("delta_vs_baseline") is None
                else str(evaluation["delta_vs_baseline"]),
                "delta_vs_parent": ""
                if evaluation.get("delta_vs_parent") is None
                else str(evaluation["delta_vs_parent"]),
                "delta_vs_champion": ""
                if evaluation.get("delta_vs_champion") is None
                else str(evaluation["delta_vs_champion"]),
                "local_improvement": str(bool(evaluation.get("local_improvement", False))).lower(),
                "new_champion": str(bool(evaluation.get("new_champion", False))).lower(),
                "target_reached": str(bool(evaluation.get("target_reached", False))).lower(),
                "confirmed": str(bool(evaluation.get("confirmed", False))).lower(),
            }
        )
    if profile["schema_version"] == 2:
        row["selector"] = metadata.get("selector", "baseline" if metadata["kind"] == "baseline" else "balanced")
    ledger_path = campaign_dir(root, campaign) / "experiments.tsv"
    with ledger_path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=ledger_columns(root, campaign), delimiter="\t", extrasaction="raise")
        writer.writerow(row)
    if profile["schema_version"] == 2:
        from .strategy import apply_strategy_transition

        apply_strategy_transition(root, campaign)
    checkpoint(
        root,
        current="experiment-recorded",
        next_action="Check stop rules and select the next hypothesis.",
        campaign=campaign,
    )
    return row


def campaign_status(repo: Path, campaign: Optional[str] = None) -> Dict[str, Any]:
    root = repo_root(repo)
    profile = load_profile(root, campaign)
    rows = read_ledger(root, campaign)
    baseline = next((row for row in rows if row.get("kind") == "baseline"), None)
    experiments = [row for row in rows if row.get("kind") != "baseline"]
    latest = rows[-1] if rows else None
    result: Dict[str, Any] = {
        "repo": str(root),
        "campaign_id": resolve_campaign_id(root, campaign),
        "approved": (campaign_dir(root, campaign) / "approval.json").exists(),
        "baseline": baseline,
        "attempted_experiments": len(experiments),
        "remaining_experiments": max(0, profile["policy"]["max_experiments"] - len(experiments)),
        "latest": latest,
        "stop_condition_met": len(experiments) >= profile["policy"]["max_experiments"],
    }
    if profile["schema_version"] == 0:
        return result

    from .candidates import champion_row, rank_candidates

    direction = profile["evaluation"]["primary_metric"]["direction"]
    champion = champion_row(rows, direction)
    target_confirmed = bool(
        champion
        and champion.get("target_reached", "").lower() == "true"
        and champion.get("confirmed", "").lower() == "true"
    )
    budget_exhausted = len(experiments) >= profile["policy"]["max_experiments"]
    elapsed_seconds = 0.0
    for manifest_path in (campaign_dir(root, campaign) / "runs").rglob("manifest.json"):
        try:
            elapsed_seconds += float(read_json(manifest_path).get("elapsed_seconds", 0))
        except (ResearchLoopError, TypeError, ValueError):
            continue
    timeout_exhausted = elapsed_seconds >= float(profile["policy"]["campaign_timeout_seconds"])
    if target_confirmed:
        termination_reason = "target-confirmed"
    elif budget_exhausted:
        termination_reason = "experiment-budget-exhausted"
    elif timeout_exhausted:
        termination_reason = "campaign-timeout-exhausted"
    else:
        termination_reason = None
    ranking = rank_candidates(root, campaign) if not (target_confirmed or budget_exhausted or timeout_exhausted) else None
    target = profile["evaluation"]["target"]
    baseline_value = float(baseline["metric_value"]) if baseline and baseline.get("metric_value") else None
    champion_value = float(champion["metric_value"]) if champion and champion.get("metric_value") else None
    if baseline_value is None or champion_value is None:
        achieved = None
    elif target["type"] == "metric_value":
        achieved = champion_value
    else:
        raw_improvement = (
            champion_value - baseline_value if direction == "maximize" else baseline_value - champion_value
        )
        achieved = (
            raw_improvement / abs(baseline_value)
            if target["type"] == "relative_improvement" and baseline_value != 0
            else raw_improvement
        )
    result.update(
        {
            "schema_version": profile["schema_version"],
            "champion": champion,
            "trace_counts": {
                trace: sum(1 for row in experiments if row.get("trace") == trace)
                for trace in (("exploit", "explore", "confirm", "diagnose") if profile["schema_version"] == 2 else ("exploit", "explore", "confirm"))
            },
            "target_reached": bool(champion and champion.get("target_reached", "").lower() == "true"),
            "target_progress": {"type": target["type"], "achieved": achieved, "required": target["value"]},
            "confirmed": bool(champion and champion.get("confirmed", "").lower() == "true"),
            "recommended_candidate_id": ranking["recommended_candidate_id"] if ranking else None,
            "recommendation_rule": ranking["rule"] if ranking else None,
            "campaign_elapsed_seconds": round(elapsed_seconds, 6),
            "stop_condition_met": target_confirmed or budget_exhausted or timeout_exhausted,
            "termination_reason": termination_reason,
        }
    )
    if profile["schema_version"] == 2:
        from .hypotheses import list_hypotheses
        from .strategy import strategy_status

        result["strategy"] = strategy_status(root, campaign)
        result["hypotheses"] = list_hypotheses(root, campaign)["assessment_counts"]
    return result
