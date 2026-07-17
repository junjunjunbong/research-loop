from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from conftest import commit_config, git
from research_loop.candidates import add_candidate, rank_candidates
from research_loop.errors import ResearchLoopError
from research_loop.executor import execute_experiment
from research_loop.experiments import prepare_experiment
from research_loop.hypotheses import (
    add_hypothesis,
    add_hypothesis_evidence,
    list_hypotheses,
)
from research_loop.ledger import campaign_status, record_experiment
from research_loop.metrics import evaluate_experiment
from research_loop.planning import approve_plan, ensure_approved, save_plan
from research_loop.schema import normalize_profile, validate_profile
from research_loop.state import campaign_dir, new_campaign
from research_loop.strategy import strategy_status


ROOT = Path(__file__).resolve().parents[1]


def write_profile(tmp_path: Path, *, selector: str = "diagnostic", transitions=None) -> Path:
    profile = yaml.safe_load((ROOT / "examples" / "mock-profile-v2.yaml").read_text(encoding="utf-8"))
    profile["strategy"]["initial_selector"] = selector
    if transitions is not None:
        profile["strategy"]["transitions"] = transitions
    path = tmp_path / "profile-v2.yaml"
    path.write_text(yaml.safe_dump(profile, sort_keys=False), encoding="utf-8")
    return path


def approve_v2(repo: Path, profile: Path) -> None:
    new_campaign(repo, profile_path=profile, base="HEAD")
    plan = save_plan(repo)
    assert plan["contract"]["strategy"]["initial_selector"]
    approve_plan(repo, plan["plan_hash"])


def record_baseline(repo: Path) -> None:
    prepare_experiment(repo, experiment_id="baseline", hypothesis="Record the v2 baseline.", baseline=True)
    execute_experiment(repo, experiment_id="baseline", mode="full")
    assert evaluate_experiment(repo, experiment_id="baseline")["status"] == "keep"
    record_experiment(repo, experiment_id="baseline")


def write_hypothesis(tmp_path: Path, *, hypothesis_id: str = "h-bottleneck") -> Path:
    spec = {
        "hypothesis_id": hypothesis_id,
        "statement": "The candidate pool is the primary score bottleneck.",
        "prediction": "Instrumenting the pool will expose missed candidates.",
        "falsification_criteria": "No candidates are missed before ranking.",
        "family": "candidate-pool",
        "origin_evidence": [{"experiment_id": "baseline", "reason": "Authoritative baseline result."}],
    }
    path = tmp_path / f"{hypothesis_id}.yaml"
    path.write_text(yaml.safe_dump(spec, sort_keys=False), encoding="utf-8")
    return path


def write_candidate(
    tmp_path: Path,
    *,
    candidate_id: str,
    parent_id: str,
    operator: str,
    trace: str,
    scores: dict,
    family: str,
) -> Path:
    spec = {
        "candidate_id": candidate_id,
        "hypothesis_id": "h-bottleneck",
        "statement": f"Run {candidate_id} as one atomic experiment.",
        "family": family,
        "operator": operator,
        "trace": trace,
        "primary_parent_id": parent_id,
        "source_parent_ids": [parent_id],
        "evidence": [{"experiment_id": parent_id, "reason": "Recorded parent evidence."}],
        "scores": {
            field: {"value": value, "reason": f"evidence-backed {field}"}
            for field, value in scores.items()
        },
        "estimated_cost": 1,
    }
    path = tmp_path / f"{candidate_id}.yaml"
    path.write_text(yaml.safe_dump(spec, sort_keys=False), encoding="utf-8")
    return path


def standard_scores(value: float) -> dict:
    return {
        "alignment": value,
        "impact": value,
        "feasibility": value,
        "information_gain": value,
        "novelty": value,
    }


def test_v2_schema_validates_strategy_contract(mock_repo: Path) -> None:
    profile = normalize_profile(
        yaml.safe_load((ROOT / "examples" / "mock-profile-v2.yaml").read_text(encoding="utf-8")),
        mock_repo,
    )
    validate_profile(profile, mock_repo)
    profile["strategy"]["initial_selector"] = "unknown"
    with pytest.raises(ResearchLoopError, match="initial_selector"):
        validate_profile(profile, mock_repo)

    profile = normalize_profile(
        yaml.safe_load((ROOT / "examples" / "mock-profile-v2.yaml").read_text(encoding="utf-8")),
        mock_repo,
    )
    profile["strategy"]["transitions"].append(
        {
            "id": "duplicate-priority",
            "priority": 10,
            "from": "balanced",
            "to": "optimization",
            "trigger": {"type": "target_reached"},
        }
    )
    with pytest.raises(ResearchLoopError, match="duplicate strategy transition priority"):
        validate_profile(profile, mock_repo)

    invalid_cases = (
        (lambda item: item.pop("schema_version"), "schema_version"),
        (lambda item: item["strategy"]["problem_shape"].update(objective="guess"), "problem_shape.objective"),
        (lambda item: item["strategy"]["transitions"][0]["trigger"].update(type="agent_decides"), "trigger.type"),
        (lambda item: item["environment"].update(api_token="forbidden"), "secret-like field"),
        (lambda item: item["context"].update(allowed_paths=["../outside"]), "must stay inside"),
    )
    for mutate, message in invalid_cases:
        invalid = normalize_profile(
            yaml.safe_load((ROOT / "examples" / "mock-profile-v2.yaml").read_text(encoding="utf-8")),
            mock_repo,
        )
        mutate(invalid)
        with pytest.raises(ResearchLoopError, match=message):
            validate_profile(invalid, mock_repo)


@pytest.mark.parametrize(
    ("selector", "expected"),
    (("diagnostic", "diagnose"), ("balanced", "balanced"), ("optimization", "optimize")),
)
def test_v2_selectors_choose_different_candidates(
    mock_repo: Path,
    tmp_path: Path,
    selector: str,
    expected: str,
) -> None:
    approve_v2(mock_repo, write_profile(tmp_path, selector=selector, transitions=[]))
    record_baseline(mock_repo)
    add_hypothesis(mock_repo, spec_path=write_hypothesis(tmp_path))
    specs = (
        ("diagnose", "diagnose", "diagnose", standard_scores(0.2)),
        (
            "balanced",
            "improve",
            "explore",
            {"alignment": 1.0, "impact": 0.5, "feasibility": 1.0, "information_gain": 0.8, "novelty": 1.0},
        ),
        (
            "optimize",
            "improve",
            "exploit",
            {"alignment": 0.9, "impact": 1.0, "feasibility": 0.8, "information_gain": 0.1, "novelty": 0.1},
        ),
    )
    for candidate_id, operator, trace, scores in specs:
        add_candidate(
            mock_repo,
            spec_path=write_candidate(
                tmp_path,
                candidate_id=candidate_id,
                parent_id="baseline",
                operator=operator,
                trace=trace,
                scores=scores,
                family=f"family-{candidate_id}",
            ),
        )
    ranking = rank_candidates(mock_repo)
    assert ranking["selector"] == selector
    assert ranking["recommended_candidate_id"] == expected
    assert all("priority_breakdown" in item for item in ranking["ranked"])


def test_v2_strategy_is_immutable_after_first_ledger_row(mock_repo: Path, tmp_path: Path) -> None:
    approve_v2(mock_repo, write_profile(tmp_path, transitions=[]))
    record_baseline(mock_repo)
    path = campaign_dir(mock_repo) / "research-strategy.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document["strategy"]["initial_selector"] = "optimization"
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    plan = save_plan(mock_repo)
    with pytest.raises(ResearchLoopError, match="create a new campaign"):
        approve_plan(mock_repo, plan["plan_hash"])


def test_v2_strategy_change_invalidates_approval_before_first_run(mock_repo: Path, tmp_path: Path) -> None:
    approve_v2(mock_repo, write_profile(tmp_path, transitions=[]))
    path = campaign_dir(mock_repo) / "research-strategy.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document["strategy"]["initial_selector"] = "optimization"
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    with pytest.raises(ResearchLoopError, match="approval is stale"):
        ensure_approved(mock_repo)
    replacement = save_plan(mock_repo)
    approve_plan(mock_repo, replacement["plan_hash"])
    assert strategy_status(mock_repo)["active_selector"] == "optimization"


def test_v2_transition_applies_only_highest_priority_rule(mock_repo: Path, tmp_path: Path) -> None:
    transitions = [
        {
            "id": "lower-priority-balanced",
            "priority": 20,
            "from": "diagnostic",
            "to": "balanced",
            "trigger": {"type": "baseline_recorded"},
        },
        {
            "id": "higher-priority-optimization",
            "priority": 10,
            "from": "diagnostic",
            "to": "optimization",
            "trigger": {"type": "baseline_recorded"},
        },
    ]
    approve_v2(mock_repo, write_profile(tmp_path, transitions=transitions))
    record_baseline(mock_repo)
    status = strategy_status(mock_repo)
    assert status["active_selector"] == "optimization"
    assert status["applied_transition_ids"] == ["higher-priority-optimization"]
    assert status["applied_transitions"][0]["transition_id"] == "higher-priority-optimization"
    assert status["next_transition"] is None
    assert set(status["selector_score_criteria"]) == {"balanced", "diagnostic", "optimization"}


def test_v2_hypothesis_evidence_and_falsified_candidate(
    mock_repo: Path,
    tmp_path: Path,
) -> None:
    approve_v2(mock_repo, write_profile(tmp_path, transitions=[]))
    record_baseline(mock_repo)
    add_hypothesis(mock_repo, spec_path=write_hypothesis(tmp_path))
    evidence = {
        "event_id": "baseline-falsifies",
        "hypothesis_id": "h-bottleneck",
        "experiment_id": "baseline",
        "relation": "falsifies",
        "observation": "The authoritative artifact shows no missed candidates.",
        "source": {"type": "artifact", "path": "results/metrics.json"},
        "rationale": "The declared falsification criterion is met.",
        "assessment": "falsified",
    }
    path = tmp_path / "evidence.yaml"
    path.write_text(yaml.safe_dump(evidence, sort_keys=False), encoding="utf-8")
    add_hypothesis_evidence(mock_repo, spec_path=path)
    listed = list_hypotheses(mock_repo)
    assert listed["assessment_counts"]["falsified"] == 1
    assert listed["hypotheses"][0]["evidence_summary"] == {
        "total": 1,
        "relations": {"falsifies": 1, "inconclusive": 0, "supports": 0, "weakens": 0},
        "latest_event_id": "baseline-falsifies",
        "latest_experiment_id": "baseline",
    }
    with pytest.raises(ResearchLoopError, match="already exists"):
        add_hypothesis_evidence(mock_repo, spec_path=path)

    invalid = dict(evidence)
    invalid["event_id"] = "missing-artifact"
    invalid["source"] = {"type": "artifact", "path": "results/missing.json"}
    invalid_path = tmp_path / "invalid-evidence.yaml"
    invalid_path.write_text(yaml.safe_dump(invalid, sort_keys=False), encoding="utf-8")
    with pytest.raises(ResearchLoopError, match="artifact evidence is missing"):
        add_hypothesis_evidence(mock_repo, spec_path=invalid_path)

    add_candidate(
        mock_repo,
        spec_path=write_candidate(
            tmp_path,
            candidate_id="blocked",
            parent_id="baseline",
            operator="improve",
            trace="exploit",
            scores=standard_scores(0.9),
            family="blocked-family",
        ),
    )
    ranking = rank_candidates(mock_repo)
    assert ranking["recommended_candidate_id"] is None
    assert ranking["ineligible"][0]["eligibility_reasons"] == ["candidate hypothesis is falsified"]


def test_v2_end_to_end_strategy_evidence_and_confirmation(mock_repo: Path, tmp_path: Path) -> None:
    approve_v2(mock_repo, write_profile(tmp_path))
    record_baseline(mock_repo)
    add_hypothesis(mock_repo, spec_path=write_hypothesis(tmp_path))

    add_candidate(
        mock_repo,
        spec_path=write_candidate(
            tmp_path,
            candidate_id="diagnose-pool",
            parent_id="baseline",
            operator="diagnose",
            trace="diagnose",
            scores=standard_scores(0.6),
            family="diagnosis",
        ),
    )
    metadata = prepare_experiment(mock_repo, experiment_id="diagnose-pool", hypothesis=None, candidate_id="diagnose-pool")
    commit_config(Path(metadata["worktree"]), diagnostic=True)
    execute_experiment(mock_repo, experiment_id="diagnose-pool", mode="full")
    assert evaluate_experiment(mock_repo, experiment_id="diagnose-pool")["status"] == "inconclusive"
    record_experiment(mock_repo, experiment_id="diagnose-pool")
    assert strategy_status(mock_repo)["active_selector"] == "balanced"

    evidence = {
        "event_id": "diagnosis-supports",
        "hypothesis_id": "h-bottleneck",
        "experiment_id": "diagnose-pool",
        "relation": "supports",
        "observation": "The diagnostic artifact is compatible with the bottleneck hypothesis.",
        "source": {"type": "artifact", "path": "results/metrics.json"},
        "rationale": "The diagnostic observation supports another intervention.",
        "assessment": "supported",
    }
    evidence_path = tmp_path / "diagnosis-evidence.yaml"
    evidence_path.write_text(yaml.safe_dump(evidence, sort_keys=False), encoding="utf-8")
    add_hypothesis_evidence(mock_repo, spec_path=evidence_path)

    add_candidate(
        mock_repo,
        spec_path=write_candidate(
            tmp_path,
            candidate_id="boost",
            parent_id="diagnose-pool",
            operator="improve",
            trace="exploit",
            scores=standard_scores(0.9),
            family="candidate-pool",
        ),
    )
    metadata = prepare_experiment(mock_repo, experiment_id="boost", hypothesis=None, candidate_id="boost")
    commit_config(Path(metadata["worktree"]), boost=0.1)
    execute_experiment(mock_repo, experiment_id="boost", mode="full")
    assert evaluate_experiment(mock_repo, experiment_id="boost")["status"] == "promising"
    first = record_experiment(mock_repo, experiment_id="boost")

    add_candidate(
        mock_repo,
        spec_path=write_candidate(
            tmp_path,
            candidate_id="confirm-boost",
            parent_id="boost",
            operator="confirm",
            trace="confirm",
            scores=standard_scores(0.1),
            family="candidate-pool-confirm",
        ),
    )
    ranking = rank_candidates(mock_repo)
    assert ranking["rule"] == "confirmation-priority"
    metadata = prepare_experiment(mock_repo, experiment_id="confirm-boost", hypothesis=None, candidate_id="confirm-boost")
    assert git(Path(metadata["worktree"]), "diff", "--name-only", f"{metadata['parent_commit']}..HEAD") == ""
    execute_experiment(mock_repo, experiment_id="confirm-boost", mode="full")
    confirmation = evaluate_experiment(mock_repo, experiment_id="confirm-boost")
    assert confirmation["status"] == "keep"
    assert confirmation["tree_hash"] == first["tree_hash"]
    record_experiment(mock_repo, experiment_id="confirm-boost")
    status = campaign_status(mock_repo)
    assert status["termination_reason"] == "target-confirmed"
    assert status["strategy"]["active_selector"] == "balanced"
    assert status["hypotheses"]["supported"] == 1
