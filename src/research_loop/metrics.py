from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from .errors import ResearchLoopError
from .experiments import experiment_dir
from .git import repo_root
from .planning import ensure_approved
from .schema import VALID_STATUSES
from .state import ensure_campaign_writable, load_profile, read_ledger
from .util import canonical_hash, confined_path, dotted_get, now_iso, read_json, write_json


def parse_value(parser: Dict[str, Any], *, worktree: Path, run_log: Path) -> Any:
    kind = parser["type"]
    if kind == "regex":
        source = run_log if parser.get("source") == "run_log" else confined_path(worktree, parser["path"], "parser.path")
        if not source.exists():
            raise ResearchLoopError(f"metric source is missing: {source}")
        match = re.search(parser["pattern"], source.read_text(encoding="utf-8", errors="replace"), re.MULTILINE)
        if not match:
            raise ResearchLoopError("metric regex did not match")
        return match.group(parser.get("group", 1))

    source = confined_path(worktree, parser["path"], "parser.path")
    if not source.exists():
        raise ResearchLoopError(f"metric source is missing: {source}")
    if kind == "json":
        try:
            payload = json.loads(source.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ResearchLoopError(f"invalid metric JSON: {source}") from exc
        return dotted_get(payload, parser["key"])
    if kind == "jsonl":
        last_value: Any = None
        found = False
        for line in source.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
                last_value = dotted_get(payload, parser["key"])
                found = True
            except (json.JSONDecodeError, ResearchLoopError):
                continue
        if not found:
            raise ResearchLoopError("metric key was not found in JSONL")
        return last_value
    raise ResearchLoopError(f"unsupported parser type: {kind}")


def _as_float(value: Any, field: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ResearchLoopError(f"{field} is not numeric: {value!r}") from exc


def _baseline_value(rows: List[Dict[str, str]]) -> Optional[float]:
    for row in rows:
        if row.get("kind") == "baseline" and row.get("status") == "keep" and row.get("metric_value"):
            return float(row["metric_value"])
    return None


def _improvement(value: float, reference: float, direction: str) -> float:
    delta = value - reference
    return delta if direction == "maximize" else -delta


def _champion_row(rows: List[Dict[str, str]], direction: str) -> Optional[Dict[str, str]]:
    valid = [row for row in rows if row.get("metric_value") and row.get("status") not in {"invalid", "crash"}]
    if not valid:
        return None
    best_value = (max if direction == "maximize" else min)(float(row["metric_value"]) for row in valid)
    tied = [row for row in valid if float(row["metric_value"]) == best_value]
    return max(
        tied,
        key=lambda row: (row.get("confirmed", "").lower() == "true", int(row.get("index", "0") or 0)),
    )


def _target_reached(value: float, baseline: float, direction: str, target: Dict[str, Any]) -> bool:
    kind = target["type"]
    threshold = float(target["value"])
    improvement = _improvement(value, baseline, direction)
    if kind == "absolute_improvement":
        return improvement >= threshold
    if kind == "relative_improvement":
        return abs(baseline) > 0 and improvement / abs(baseline) >= threshold
    return value >= threshold if direction == "maximize" else value <= threshold


def evaluate_experiment(
    repo: Path,
    *,
    experiment_id: str,
    mode: str = "full",
    campaign: Optional[str] = None,
) -> Dict[str, Any]:
    root = repo_root(repo)
    ensure_campaign_writable(root, campaign)
    ensure_approved(root, campaign)
    profile = load_profile(root, campaign)
    exp_dir = experiment_dir(root, experiment_id, campaign)
    metadata = read_json(exp_dir / "experiment.json")
    manifest = read_json(exp_dir / mode / "manifest.json")
    worktree = Path(manifest["worktree"]).resolve()
    run_log = Path(manifest["log_path"]).resolve()
    evaluation = profile["evaluation"]
    primary = evaluation["primary_metric"]
    result: Dict[str, Any] = {
        "schema_version": profile["schema_version"],
        "experiment_id": experiment_id,
        "hypothesis_id": metadata["hypothesis_id"],
        "kind": metadata["kind"],
        "mode": mode,
        "metric_name": primary["name"],
        "metric_value": None,
        "baseline_value": None,
        "delta": None,
        "tree_hash": manifest.get("tree_hash"),
        "status": "invalid",
        "reasons": [],
        "compatibility": [],
        "compatibility_hash": canonical_hash(evaluation.get("compatibility", [])),
        "evaluated_at": now_iso(),
    }

    if mode != "full":
        result["reasons"].append("smoke runs are plumbing checks and cannot be performance results")
    elif manifest.get("timed_out") or manifest.get("exit_code") != 0:
        result["status"] = "crash"
        result["reasons"].append("approved command timed out or exited unsuccessfully")
    else:
        missing = [
            path
            for path in evaluation.get("required_artifacts", [])
            if not confined_path(worktree, path, "evaluation.required_artifacts").exists()
        ]
        if missing:
            result["reasons"].append(f"required artifacts are missing: {', '.join(missing)}")
        if float(manifest.get("elapsed_seconds", 0)) < float(evaluation.get("min_duration_seconds", 0)):
            result["reasons"].append("run was shorter than the authoritative minimum duration")
        try:
            result["metric_value"] = _as_float(
                parse_value(primary["parser"], worktree=worktree, run_log=run_log),
                "primary metric",
            )
        except ResearchLoopError as exc:
            result["reasons"].append(f"metric parser failed: {exc}")
        for check in evaluation.get("compatibility", []):
            entry = {"name": check["name"], "expected": check["expected"], "actual": None, "valid": False}
            try:
                actual = parse_value(check["parser"], worktree=worktree, run_log=run_log)
                entry["actual"] = actual
                entry["valid"] = actual == check["expected"]
                if not entry["valid"]:
                    result["reasons"].append(
                        f"compatibility mismatch for {check['name']}: expected {check['expected']!r}, got {actual!r}"
                    )
            except ResearchLoopError as exc:
                result["reasons"].append(f"compatibility parser failed for {check['name']}: {exc}")
            result["compatibility"].append(entry)

        if not result["reasons"]:
            rows = read_ledger(root, campaign)
            if metadata["kind"] == "baseline":
                result["status"] = "keep"
                result["reasons"].append("valid baseline anchor")
                if profile["schema_version"] == 1:
                    result.update(
                        {
                            "parent_value": None,
                            "champion_before_value": None,
                            "delta_vs_baseline": 0.0,
                            "delta_vs_parent": None,
                            "delta_vs_champion": None,
                            "local_improvement": False,
                            "new_champion": True,
                            "target_reached": False,
                            "confirmed": True,
                        }
                    )
            else:
                baseline = _baseline_value(rows)
                if baseline is None:
                    result["reasons"].append("no valid baseline is recorded")
                else:
                    value = float(result["metric_value"])
                    delta = value - baseline
                    improvement = _improvement(value, baseline, primary["direction"])
                    result["baseline_value"] = baseline
                    result["delta"] = delta
                    if profile["schema_version"] == 0:
                        noise = float(evaluation.get("noise_tolerance", 0))
                        threshold = max(noise, float(evaluation.get("min_delta", 0)))
                        if improvement > threshold:
                            prior_confirmations = sum(
                                1
                                for row in rows
                                if row.get("hypothesis_id") == metadata["hypothesis_id"]
                                and row.get("status") in {"promising", "keep"}
                            )
                            confirmed = prior_confirmations + 1
                            if confirmed >= int(evaluation["confirmation_runs"]):
                                result["status"] = "keep"
                                result["reasons"].append(f"improvement confirmed in {confirmed} valid runs")
                            else:
                                result["status"] = "promising"
                                result["reasons"].append("single valid improvement requires confirmation")
                        elif improvement < -noise:
                            result["status"] = "discard"
                            result["reasons"].append("primary metric regressed beyond noise tolerance")
                        else:
                            result["status"] = "inconclusive"
                            result["reasons"].append("metric change is within the inconclusive range")
                    else:
                        direction = primary["direction"]
                        parent = next(
                            (row for row in rows if row.get("experiment_id") == metadata.get("primary_parent_id")),
                            None,
                        )
                        parent_value = float(parent["metric_value"]) if parent and parent.get("metric_value") else None
                        champion = _champion_row(rows, direction)
                        champion_value = float(champion["metric_value"]) if champion else None
                        acceptance = evaluation["acceptance"]
                        noise = float(acceptance["noise_tolerance"])
                        parent_threshold = max(noise, float(acceptance["min_parent_delta"]))
                        parent_improvement = (
                            _improvement(value, parent_value, direction) if parent_value is not None else None
                        )
                        champion_improvement = (
                            _improvement(value, champion_value, direction) if champion_value is not None else None
                        )
                        local_improvement = parent_improvement is not None and parent_improvement > parent_threshold
                        new_champion = champion_improvement is None or champion_improvement > noise
                        target_reached = _target_reached(value, baseline, direction, evaluation["target"])
                        compatibility_hash = result["compatibility_hash"]
                        tree_hash = manifest.get("tree_hash")
                        qualifying_run = target_reached or improvement > parent_threshold
                        prior_same_tree = sum(
                            1
                            for row in rows
                            if row.get("kind") != "baseline"
                            and row.get("tree_hash") == tree_hash
                            and row.get("compatibility_hash") == compatibility_hash
                            and row.get("status") not in {"invalid", "crash"}
                            and row.get("metric_value")
                            and (
                                row.get("target_reached", "").lower() == "true"
                                or _improvement(float(row["metric_value"]), baseline, direction) > parent_threshold
                            )
                        )
                        confirmation_count = prior_same_tree + 1
                        confirmed = qualifying_run and confirmation_count >= int(evaluation["confirmation_runs"])
                        result.update(
                            {
                                "parent_value": parent_value,
                                "champion_before_value": champion_value,
                                "delta_vs_baseline": value - baseline,
                                "delta_vs_parent": None if parent_value is None else value - parent_value,
                                "delta_vs_champion": None if champion_value is None else value - champion_value,
                                "local_improvement": local_improvement,
                                "new_champion": new_champion,
                                "target_reached": target_reached,
                                "confirmed": confirmed,
                                "confirmation_count": confirmation_count,
                            }
                        )
                        if confirmed:
                            result["status"] = "keep"
                            result["reasons"].append(
                                f"identical code tree confirmed in {confirmation_count} compatible full runs"
                            )
                        elif parent_improvement is not None and parent_improvement < -noise:
                            result["status"] = "discard"
                            result["reasons"].append("primary metric regressed from parent beyond noise tolerance")
                        elif local_improvement or new_champion or target_reached:
                            result["status"] = "promising"
                            result["reasons"].append("valid improvement requires identical-tree confirmation")
                        else:
                            result["status"] = "inconclusive"
                            result["reasons"].append("valid result is within the parent improvement threshold")

    if result["status"] not in VALID_STATUSES:
        raise ResearchLoopError(f"internal invalid status: {result['status']}")
    output = exp_dir / mode / "evaluation.json"
    write_json(output, result)
    return result
