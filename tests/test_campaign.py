from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
import yaml

from conftest import commit_config, git
from research_loop.errors import ResearchLoopError
from research_loop.executor import execute_experiment
from research_loop.experiments import prepare_experiment
from research_loop.ledger import campaign_status, record_experiment
from research_loop.metrics import evaluate_experiment
from research_loop.planning import approve_plan, save_plan
from research_loop.state import setup_project


ROOT = Path(__file__).resolve().parents[1]


def approve_variant(repo: Path, tmp_path: Path, mutate) -> None:
    profile = yaml.safe_load((ROOT / "examples" / "mock-profile.yaml").read_text(encoding="utf-8"))
    mutate(profile)
    profile_path = tmp_path / "variant-profile.yaml"
    profile_path.write_text(yaml.safe_dump(profile, sort_keys=False), encoding="utf-8")
    setup_project(repo, profile_path)
    plan = save_plan(repo)
    approve_plan(repo, plan["plan_hash"])


def run_baseline(repo: Path) -> None:
    metadata = prepare_experiment(
        repo,
        experiment_id="baseline",
        hypothesis="Record the unmodified authoritative baseline.",
        baseline=True,
    )
    smoke = execute_experiment(repo, experiment_id="baseline", mode="smoke")
    assert smoke["exit_code"] == 0
    smoke_evaluation = evaluate_experiment(repo, experiment_id="baseline", mode="smoke")
    assert smoke_evaluation["status"] == "invalid"
    execute_experiment(repo, experiment_id="baseline", mode="full")
    evaluation = evaluate_experiment(repo, experiment_id="baseline")
    assert evaluation["status"] == "keep"
    assert evaluation["metric_value"] == 0.5
    row = record_experiment(repo, experiment_id="baseline")
    assert row["kind"] == "baseline"


def test_end_to_end_promising_and_base_untouched(approved_repo: Path) -> None:
    original_config = (approved_repo / "config.json").read_text(encoding="utf-8")
    run_baseline(approved_repo)
    metadata = prepare_experiment(
        approved_repo,
        experiment_id="boost-score",
        hypothesis_id="boost-score",
        hypothesis="Increasing the mock boost improves the authoritative score.",
    )
    worktree = Path(metadata["worktree"])
    commit_config(worktree, boost=0.1)
    execute_experiment(approved_repo, experiment_id="boost-score", mode="smoke")
    execute_experiment(approved_repo, experiment_id="boost-score", mode="full")
    evaluation = evaluate_experiment(approved_repo, experiment_id="boost-score")
    assert evaluation["status"] == "promising"
    assert evaluation["metric_value"] == pytest.approx(0.6)
    row = record_experiment(approved_repo, experiment_id="boost-score")
    assert row["status"] == "promising"
    status = campaign_status(approved_repo)
    assert status["attempted_experiments"] == 1
    assert status["remaining_experiments"] == 2
    assert (approved_repo / "config.json").read_text(encoding="utf-8") == original_config
    assert git(approved_repo, "status", "--short") == ""
    assert (approved_repo / ".research" / "handoff.md").is_file()


def test_compatibility_mismatch_is_invalid(approved_repo: Path) -> None:
    run_baseline(approved_repo)
    metadata = prepare_experiment(
        approved_repo,
        experiment_id="changed-dataset",
        hypothesis="Changing evaluation conditions must never look like an improvement.",
    )
    worktree = Path(metadata["worktree"])
    commit_config(worktree, boost=0.2, dataset_version="mock-v2")
    execute_experiment(approved_repo, experiment_id="changed-dataset", mode="full")
    evaluation = evaluate_experiment(approved_repo, experiment_id="changed-dataset")
    assert evaluation["status"] == "invalid"
    assert any("dataset_version" in reason for reason in evaluation["reasons"])


def test_protected_or_unapproved_path_is_blocked(approved_repo: Path) -> None:
    metadata = prepare_experiment(
        approved_repo,
        experiment_id="touch-evaluator",
        hypothesis="This intentionally violates the approved path scope.",
    )
    worktree = Path(metadata["worktree"])
    path = worktree / "experiment.py"
    path.write_text(path.read_text(encoding="utf-8") + "\n# forbidden\n", encoding="utf-8")
    git(worktree, "add", "experiment.py")
    git(worktree, "commit", "-m", "experiment: touch protected evaluator")
    with pytest.raises(ResearchLoopError, match="protected paths"):
        execute_experiment(approved_repo, experiment_id="touch-evaluator", mode="smoke")


def test_timeout_becomes_crash(mock_repo: Path, tmp_path: Path) -> None:
    def mutate(profile: dict) -> None:
        profile["environment"]["commands"]["full"] = ["python3", "-c", "import time; time.sleep(1)"]
        profile["environment"]["timeout_seconds"] = 0.1
        profile["policy"]["experiment_timeout_seconds"] = 0.1
        profile["policy"]["campaign_timeout_seconds"] = 0.2

    approve_variant(mock_repo, tmp_path, mutate)
    prepare_experiment(
        mock_repo,
        experiment_id="baseline",
        hypothesis="Record timeout behavior.",
        baseline=True,
    )
    manifest = execute_experiment(mock_repo, experiment_id="baseline", mode="full")
    assert manifest["timed_out"] is True
    assert evaluate_experiment(mock_repo, experiment_id="baseline")["status"] == "crash"


def test_missing_artifact_and_short_run_are_invalid(mock_repo: Path, tmp_path: Path) -> None:
    def mutate(profile: dict) -> None:
        profile["environment"]["commands"]["full"] = ["python3", "-c", "print('completed without metrics')"]
        profile["evaluation"]["min_duration_seconds"] = 10

    approve_variant(mock_repo, tmp_path, mutate)
    prepare_experiment(
        mock_repo,
        experiment_id="baseline",
        hypothesis="Record invalid artifact behavior.",
        baseline=True,
    )
    execute_experiment(mock_repo, experiment_id="baseline", mode="full")
    evaluation = evaluate_experiment(mock_repo, experiment_id="baseline")
    assert evaluation["status"] == "invalid"
    assert any("required artifacts" in reason for reason in evaluation["reasons"])
    assert any("minimum duration" in reason for reason in evaluation["reasons"])
