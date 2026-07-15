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
from .state import EXPERIMENT_COLUMNS, load_profile, read_ledger, research_dir
from .util import now_iso, read_json


def checkpoint(repo: Path, *, current: str, next_action: str) -> Dict[str, Any]:
    root = repo_root(repo)
    target = research_dir(root)
    profile = load_profile(root)
    rows = read_ledger(root)
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


def record_experiment(repo: Path, *, experiment_id: str, description: Optional[str] = None) -> Dict[str, str]:
    root = repo_root(repo)
    ensure_approved(root)
    exp_dir = experiment_dir(root, experiment_id)
    metadata = read_json(exp_dir / "experiment.json")
    manifest = read_json(exp_dir / "full" / "manifest.json")
    evaluation = read_json(exp_dir / "full" / "evaluation.json")
    rows = read_ledger(root)
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
    with (research_dir(root) / "experiments.tsv").open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=EXPERIMENT_COLUMNS, delimiter="\t", extrasaction="raise")
        writer.writerow(row)
    checkpoint(root, current="experiment-recorded", next_action="Check stop rules and select the next hypothesis.")
    return row


def campaign_status(repo: Path) -> Dict[str, Any]:
    root = repo_root(repo)
    profile = load_profile(root)
    rows = read_ledger(root)
    baseline = next((row for row in rows if row.get("kind") == "baseline"), None)
    experiments = [row for row in rows if row.get("kind") != "baseline"]
    latest = rows[-1] if rows else None
    return {
        "repo": str(root),
        "campaign_id": profile["policy"]["campaign_id"],
        "approved": (research_dir(root) / "approval.json").exists(),
        "baseline": baseline,
        "attempted_experiments": len(experiments),
        "remaining_experiments": max(0, profile["policy"]["max_experiments"] - len(experiments)),
        "latest": latest,
        "stop_condition_met": len(experiments) >= profile["policy"]["max_experiments"],
    }
