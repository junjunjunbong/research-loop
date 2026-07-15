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
from .state import load_profile, read_ledger
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


def evaluate_experiment(repo: Path, *, experiment_id: str, mode: str = "full") -> Dict[str, Any]:
    root = repo_root(repo)
    ensure_approved(root)
    profile = load_profile(root)
    exp_dir = experiment_dir(root, experiment_id)
    metadata = read_json(exp_dir / "experiment.json")
    manifest = read_json(exp_dir / mode / "manifest.json")
    worktree = Path(manifest["worktree"]).resolve()
    run_log = Path(manifest["log_path"]).resolve()
    evaluation = profile["evaluation"]
    primary = evaluation["primary_metric"]
    result: Dict[str, Any] = {
        "schema_version": 0,
        "experiment_id": experiment_id,
        "hypothesis_id": metadata["hypothesis_id"],
        "kind": metadata["kind"],
        "mode": mode,
        "metric_name": primary["name"],
        "metric_value": None,
        "baseline_value": None,
        "delta": None,
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
            rows = read_ledger(root)
            if metadata["kind"] == "baseline":
                result["status"] = "keep"
                result["reasons"].append("valid baseline anchor")
            else:
                baseline = _baseline_value(rows)
                if baseline is None:
                    result["reasons"].append("no valid baseline is recorded")
                else:
                    value = float(result["metric_value"])
                    delta = value - baseline
                    improvement = delta if primary["direction"] == "maximize" else -delta
                    result["baseline_value"] = baseline
                    result["delta"] = delta
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

    if result["status"] not in VALID_STATUSES:
        raise ResearchLoopError(f"internal invalid status: {result['status']}")
    output = exp_dir / mode / "evaluation.json"
    write_json(output, result)
    return result
