from __future__ import annotations

import csv
from pathlib import Path

import pytest
import yaml

from conftest import commit_config, git
from research_loop.candidates import add_candidate, rank_candidates, scoped_evidence
from research_loop.errors import ResearchLoopError
from research_loop.executor import execute_experiment
from research_loop.experiments import prepare_experiment
from research_loop.ledger import campaign_status, record_experiment
from research_loop.metrics import evaluate_experiment
from research_loop.planning import approve_plan, save_plan
from research_loop.state import (
    V1_EXPERIMENT_COLUMNS,
    activate_campaign,
    campaign_dir,
    list_campaigns,
    new_campaign,
    setup_project,
    upgrade_control_plane,
)


ROOT = Path(__file__).resolve().parents[1]


def write_candidate(
    tmp_path: Path,
    *,
    candidate_id: str,
    parent_id: str,
    operator: str = "improve",
    trace: str = "exploit",
    family: str = "mock-boost",
    score: float = 0.8,
) -> Path:
    spec = {
        "candidate_id": candidate_id,
        "hypothesis_id": "h-mock-boost",
        "statement": f"Candidate {candidate_id} improves the mock score.",
        "family": family,
        "operator": operator,
        "trace": trace,
        "primary_parent_id": parent_id,
        "source_parent_ids": [parent_id],
        "evidence": [{"experiment_id": parent_id, "reason": "authoritative score"}],
        "scores": {
            field: {"value": score, "reason": f"mock {field}"}
            for field in ("alignment", "impact", "feasibility", "information_gain", "novelty")
        },
        "estimated_cost": 1,
    }
    path = tmp_path / f"{candidate_id}.yaml"
    path.write_text(yaml.safe_dump(spec, sort_keys=False), encoding="utf-8")
    return path


def approve_v1(repo: Path) -> None:
    new_campaign(repo, profile_path=ROOT / "examples" / "mock-profile-v1.yaml", base="HEAD")
    plan = save_plan(repo)
    approve_plan(repo, plan["plan_hash"])


def record_baseline(repo: Path) -> None:
    prepare_experiment(
        repo,
        experiment_id="baseline",
        hypothesis="Record the v1 mock baseline.",
        baseline=True,
    )
    execute_experiment(repo, experiment_id="baseline", mode="full")
    assert evaluate_experiment(repo, experiment_id="baseline")["status"] == "keep"
    record_experiment(repo, experiment_id="baseline")


def test_v1_dag_improvement_confirmation_and_stop(mock_repo: Path, tmp_path: Path) -> None:
    approve_v1(mock_repo)
    record_baseline(mock_repo)

    add_candidate(mock_repo, spec_path=write_candidate(tmp_path, candidate_id="boost", parent_id="baseline"))
    assert rank_candidates(mock_repo)["recommended_candidate_id"] == "boost"
    metadata = prepare_experiment(
        mock_repo,
        experiment_id="boost",
        hypothesis=None,
        candidate_id="boost",
    )
    commit_config(Path(metadata["worktree"]), boost=0.1)
    execute_experiment(mock_repo, experiment_id="boost", mode="full")
    evaluation = evaluate_experiment(mock_repo, experiment_id="boost")
    assert evaluation["status"] == "promising"
    assert evaluation["delta_vs_parent"] == pytest.approx(0.1)
    assert evaluation["new_champion"] is True
    assert evaluation["target_reached"] is True
    assert evaluation["confirmed"] is False
    first = record_experiment(mock_repo, experiment_id="boost")
    assert first["tree_hash"]

    confirmation = write_candidate(
        tmp_path,
        candidate_id="confirm-boost",
        parent_id="boost",
        operator="confirm",
        trace="confirm",
        family="mock-boost-confirm",
        score=0.5,
    )
    add_candidate(mock_repo, spec_path=confirmation)
    ranking = rank_candidates(mock_repo)
    assert ranking["rule"] == "confirmation-priority"
    metadata = prepare_experiment(
        mock_repo,
        experiment_id="confirm-boost",
        hypothesis=None,
        candidate_id="confirm-boost",
    )
    assert git(Path(metadata["worktree"]), "diff", "--name-only", f"{metadata['parent_commit']}..HEAD") == ""
    execute_experiment(mock_repo, experiment_id="confirm-boost", mode="full")
    evaluation = evaluate_experiment(mock_repo, experiment_id="confirm-boost")
    assert evaluation["status"] == "keep"
    assert evaluation["confirmed"] is True
    assert evaluation["tree_hash"] == first["tree_hash"]
    record_experiment(mock_repo, experiment_id="confirm-boost")

    status = campaign_status(mock_repo)
    assert status["stop_condition_met"] is True
    assert status["termination_reason"] == "target-confirmed"
    assert status["champion"]["experiment_id"] in {"boost", "confirm-boost"}
    evidence = scoped_evidence(mock_repo, operator="improve", parent_id="boost")
    assert evidence["evidence"][0]["experiment_id"] == "boost"


def test_v1_prepare_enforces_recommendation(mock_repo: Path, tmp_path: Path) -> None:
    approve_v1(mock_repo)
    record_baseline(mock_repo)
    add_candidate(
        mock_repo,
        spec_path=write_candidate(tmp_path, candidate_id="lower", parent_id="baseline", score=0.4),
    )
    add_candidate(
        mock_repo,
        spec_path=write_candidate(
            tmp_path,
            candidate_id="higher",
            parent_id="baseline",
            family="other-family",
            score=0.9,
        ),
    )
    assert rank_candidates(mock_repo)["recommended_candidate_id"] == "higher"
    with pytest.raises(ResearchLoopError, match="deterministic recommendation"):
        prepare_experiment(
            mock_repo,
            experiment_id="lower",
            hypothesis=None,
            candidate_id="lower",
        )


def test_explore_quota_and_recombine_evidence(mock_repo: Path, tmp_path: Path) -> None:
    approve_v1(mock_repo)
    record_baseline(mock_repo)
    ledger = campaign_dir(mock_repo) / "experiments.tsv"
    with ledger.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=V1_EXPERIMENT_COLUMNS, delimiter="\t")
        for index in range(1, 4):
            row = {field: "" for field in V1_EXPERIMENT_COLUMNS}
            row.update(
                {
                    "index": str(index + 1),
                    "experiment_id": f"prior-{index}",
                    "hypothesis_id": f"h-prior-{index}",
                    "kind": "experiment",
                    "parent_commit": git(mock_repo, "rev-parse", "HEAD"),
                    "commit": git(mock_repo, "rev-parse", "HEAD"),
                    "metric_name": "score",
                    "metric_value": str(0.5 + index / 1000),
                    "baseline_value": "0.5",
                    "status": "inconclusive",
                    "compatibility_hash": "mock-compatible",
                    "primary_parent_id": "baseline",
                    "operator": "improve",
                    "trace": "exploit",
                    "family": f"prior-family-{index}",
                    "confirmed": "false",
                    "target_reached": "false",
                }
            )
            writer.writerow(row)

    add_candidate(
        mock_repo,
        spec_path=write_candidate(
            tmp_path,
            candidate_id="exploit-next",
            parent_id="baseline",
            family="exploit-next",
            score=0.95,
        ),
    )
    recombine = yaml.safe_load(
        write_candidate(
            tmp_path,
            candidate_id="recombine-explore",
            parent_id="baseline",
            operator="recombine",
            trace="explore",
            family="recombine-family",
            score=0.2,
        ).read_text(encoding="utf-8")
    )
    recombine["source_parent_ids"] = ["baseline", "prior-1"]
    path = tmp_path / "recombine-explore.yaml"
    path.write_text(yaml.safe_dump(recombine, sort_keys=False), encoding="utf-8")
    add_candidate(mock_repo, spec_path=path)

    ranking = rank_candidates(mock_repo)
    assert ranking["rule"] == "explore-quota"
    assert ranking["recommended_candidate_id"] == "recombine-explore"
    evidence = scoped_evidence(mock_repo, candidate_id="recombine-explore")
    assert {item["experiment_id"] for item in evidence["evidence"]} == {"baseline", "prior-1"}


def test_v0_upgrade_check_apply_and_idempotence(mock_repo: Path) -> None:
    setup_project(mock_repo, ROOT / "examples" / "mock-profile.yaml")
    plan = save_plan(mock_repo)
    approve_plan(mock_repo, plan["plan_hash"])
    record_baseline(mock_repo)
    before = list(csv.DictReader((mock_repo / ".research" / "experiments.tsv").open(), delimiter="\t"))

    check = upgrade_control_plane(mock_repo, apply=False)
    assert check["ready"] is True
    applied = upgrade_control_plane(mock_repo, apply=True)
    assert applied["migrated"] is True
    migrated = campaign_dir(mock_repo, "mock-campaign")
    after = list(csv.DictReader((migrated / "experiments.tsv").open(), delimiter="\t"))
    assert before[0]["metric_value"] == after[0]["metric_value"]
    assert (migrated / "runs" / "baseline" / "full" / "evaluation.json").is_file()
    assert upgrade_control_plane(mock_repo, apply=True)["upgrade_required"] is False
    with pytest.raises(ResearchLoopError, match="read-only"):
        save_plan(mock_repo, "mock-campaign")


def test_multiple_campaigns_and_explicit_activation(mock_repo: Path, tmp_path: Path) -> None:
    first = new_campaign(mock_repo, profile_path=ROOT / "examples" / "mock-profile-v1.yaml", base="HEAD")
    profile = yaml.safe_load((ROOT / "examples" / "mock-profile-v1.yaml").read_text(encoding="utf-8"))
    profile["policy"]["campaign_id"] = "mock-dag-v1-second"
    second_profile = tmp_path / "second-profile.yaml"
    second_profile.write_text(yaml.safe_dump(profile, sort_keys=False), encoding="utf-8")
    second = new_campaign(mock_repo, profile_path=second_profile, base="HEAD")

    listed = list_campaigns(mock_repo)
    assert listed["active_campaign"] == second["campaign_id"]
    assert set(listed["campaigns"]) == {first["campaign_id"], second["campaign_id"]}
    activated = activate_campaign(mock_repo, first["campaign_id"])
    assert activated["active_campaign"] == first["campaign_id"]
    assert campaign_dir(mock_repo) == mock_repo / ".research" / "campaigns" / first["campaign_id"]


def test_v1_minimize_direction_uses_parent_and_champion_correctly(mock_repo: Path, tmp_path: Path) -> None:
    profile = yaml.safe_load((ROOT / "examples" / "mock-profile-v1.yaml").read_text(encoding="utf-8"))
    profile["policy"]["campaign_id"] = "mock-minimize-v1"
    profile["evaluation"]["primary_metric"]["direction"] = "minimize"
    path = tmp_path / "minimize-profile.yaml"
    path.write_text(yaml.safe_dump(profile, sort_keys=False), encoding="utf-8")
    new_campaign(mock_repo, profile_path=path, base="HEAD")
    plan = save_plan(mock_repo)
    approve_plan(mock_repo, plan["plan_hash"])
    record_baseline(mock_repo)
    add_candidate(
        mock_repo,
        spec_path=write_candidate(tmp_path, candidate_id="lower-score", parent_id="baseline"),
    )
    metadata = prepare_experiment(
        mock_repo,
        experiment_id="lower-score",
        hypothesis=None,
        candidate_id="lower-score",
    )
    commit_config(Path(metadata["worktree"]), boost=-0.1)
    execute_experiment(mock_repo, experiment_id="lower-score", mode="full")
    evaluation = evaluate_experiment(mock_repo, experiment_id="lower-score")
    assert evaluation["metric_value"] == pytest.approx(0.4)
    assert evaluation["delta_vs_parent"] == pytest.approx(-0.1)
    assert evaluation["local_improvement"] is True
    assert evaluation["new_champion"] is True
    assert evaluation["target_reached"] is True
