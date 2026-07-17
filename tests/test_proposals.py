from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from conftest import commit_config
from research_loop.candidates import add_candidate, get_candidate, list_candidates
from research_loop.errors import ResearchLoopError
from research_loop.executor import execute_experiment
from research_loop.experiments import prepare_experiment
from research_loop.hypotheses import add_hypothesis, add_hypothesis_evidence, list_hypotheses
from research_loop.ledger import record_experiment
from research_loop.metrics import evaluate_experiment
from research_loop.proposals import portfolio_lint, proposal_context, validate_proposal
from test_v2_strategy import (
    approve_v2,
    record_baseline,
    standard_scores,
    write_candidate,
    write_hypothesis,
    write_profile,
)


def write_yaml_spec(tmp_path: Path, name: str, spec: dict) -> Path:
    path = tmp_path / name
    path.write_text(yaml.safe_dump(spec, sort_keys=False), encoding="utf-8")
    return path


def candidate_spec(candidate_id: str, *, hypothesis_id: str, trace: str, operator: str, family: str) -> dict:
    return {
        "candidate_id": candidate_id,
        "hypothesis_id": hypothesis_id,
        "statement": f"Run {candidate_id} as one atomic experiment.",
        "family": family,
        "operator": operator,
        "trace": trace,
        "primary_parent_id": "baseline",
        "source_parent_ids": ["baseline"],
        "evidence": [{"experiment_id": "baseline", "reason": "Recorded parent evidence."}],
        "scores": {
            field: {"value": value, "reason": f"evidence-backed {field}"}
            for field, value in standard_scores(0.7).items()
        },
        "estimated_cost": 1,
    }


def paper_source() -> dict:
    return {
        "source_type": "paper",
        "locator": "example-archive:2401.00001v2",
        "content_sha256": "a" * 64,
        "claim": "A lightweight gate stabilizes the scored output.",
        "applicability": "The mock project exposes a comparable scoring path.",
        "license": "unknown",
    }


def test_proposal_validate_accepts_rejects_and_writes_nothing(mock_repo: Path, tmp_path: Path) -> None:
    approve_v2(mock_repo, write_profile(tmp_path, selector="diagnostic", transitions=[]))
    record_baseline(mock_repo)
    add_hypothesis(mock_repo, spec_path=write_hypothesis(tmp_path))

    good_hypothesis = {
        "hypothesis_id": "h-gate",
        "statement": "Gating the score reduces noise.",
        "prediction": "The primary metric improves beyond noise tolerance.",
        "falsification_criteria": "The metric does not improve beyond noise tolerance.",
        "family": "gating",
        "origin_evidence": [{"experiment_id": "baseline", "reason": "Baseline shows unstable scores."}],
    }
    proposal = {
        "schema_version": 2,
        "proposal_id": "round-1",
        "generated_by": {"agent": "test", "template_version": "v1"},
        "items": [
            {
                "slot": "explore",
                "hypothesis": good_hypothesis,
                "candidate": candidate_spec(
                    "explore-gate", hypothesis_id="h-gate", trace="explore", operator="draft", family="gating"
                ),
                "intervention": {
                    "changed_factor": "score gating",
                    "held_constant": ["dataset", "evaluator"],
                    "expected_mechanism": "suppresses unstable contributions",
                    "observable_signature": "lower score variance",
                },
                "idea_sources": [paper_source()],
            },
            {
                "slot": "diagnose",
                "candidate": candidate_spec(
                    "bad-slot", hypothesis_id="h-bottleneck", trace="exploit", operator="improve", family="candidate-pool"
                ),
            },
            {
                "slot": "exploit",
                "candidate": candidate_spec(
                    "bad-hypothesis", hypothesis_id="h-missing", trace="exploit", operator="improve", family="candidate-pool"
                ),
            },
            {
                "slot": "exploit",
                "candidate": candidate_spec(
                    "bad-source", hypothesis_id="h-bottleneck", trace="exploit", operator="improve", family="candidate-pool"
                ),
                "idea_sources": [{k: v for k, v in paper_source().items() if k != "content_sha256"}],
            },
        ],
    }
    spec_path = write_yaml_spec(tmp_path, "proposal.yaml", proposal)
    result = validate_proposal(mock_repo, spec_path=spec_path)

    assert result["counts"] == {
        "items": 4,
        "accepted": 1,
        "rejected": 3,
        "new_hypotheses": 1,
        "idea_sources": 1,
    }
    assert result["items"][0]["slot"] == "explore"
    assert result["items"][0]["candidate"]["candidate_id"] == "explore-gate"
    assert "status" not in result["items"][0]["candidate"]
    reasons = {entry["candidate_id"]: entry["reasons"][0] for entry in result["rejected"]}
    assert "requires trace diagnose" in reasons["bad-slot"]
    assert "unknown candidate hypothesis" in reasons["bad-hypothesis"]
    assert "revision or content_sha256" in reasons["bad-source"]
    assert len(result["context_hash"]) == 64
    assert len(result["source_set_hash"]) == 64

    repeat = validate_proposal(mock_repo, spec_path=spec_path)
    assert repeat["context_hash"] == result["context_hash"]
    assert repeat["source_set_hash"] == result["source_set_hash"]

    assert list_candidates(mock_repo) == []
    assert [item["hypothesis_id"] for item in list_hypotheses(mock_repo)["hypotheses"]] == ["h-bottleneck"]

    duplicate = dict(proposal)
    duplicate["items"] = [
        {
            "slot": "explore",
            "hypothesis": dict(good_hypothesis, hypothesis_id="h-bottleneck"),
            "candidate": candidate_spec(
                "dup", hypothesis_id="h-bottleneck", trace="explore", operator="draft", family="gating"
            ),
        }
    ]
    duplicate_path = write_yaml_spec(tmp_path, "duplicate.yaml", duplicate)
    rejected = validate_proposal(mock_repo, spec_path=duplicate_path)["rejected"]
    assert "hypothesis already exists" in rejected[0]["reasons"][0]

    with pytest.raises(ResearchLoopError, match="schema_version must be 2"):
        validate_proposal(
            mock_repo,
            spec_path=write_yaml_spec(tmp_path, "bad-version.yaml", dict(proposal, schema_version=1)),
        )

    context = proposal_context(mock_repo)
    assert context["champion"]["experiment_id"] == "baseline"
    assert context["remaining_experiments"] == 5
    assert context["coverage"]["open_or_contested_without_pending_diagnose"] == ["h-bottleneck"]
    assert "gating" not in context["families"]
    assert context["constraints"]["allowed_paths"]


def test_hypothesis_add_persists_idea_sources(mock_repo: Path, tmp_path: Path) -> None:
    approve_v2(mock_repo, write_profile(tmp_path, selector="diagnostic", transitions=[]))
    record_baseline(mock_repo)
    spec = {
        "hypothesis_id": "h-gate",
        "statement": "Gating the score reduces noise.",
        "prediction": "The primary metric improves beyond noise tolerance.",
        "falsification_criteria": "The metric does not improve beyond noise tolerance.",
        "family": "gating",
        "origin_evidence": [{"experiment_id": "baseline", "reason": "Baseline shows unstable scores."}],
        "idea_sources": [paper_source()],
    }
    created = add_hypothesis(mock_repo, spec_path=write_yaml_spec(tmp_path, "h-gate.yaml", spec))
    assert created["idea_sources"][0]["usage"] == {"mode": "idea_only", "code_reuse_allowed": False}
    assert created["idea_sources"][0]["license"] == "unknown"
    listed = list_hypotheses(mock_repo)["hypotheses"][0]["idea_sources"]
    assert listed[0]["locator"] == "example-archive:2401.00001v2"

    missing_hash = dict(spec, hypothesis_id="h-bad")
    missing_hash["idea_sources"] = [{k: v for k, v in paper_source().items() if k != "content_sha256"}]
    with pytest.raises(ResearchLoopError, match="revision or content_sha256"):
        add_hypothesis(mock_repo, spec_path=write_yaml_spec(tmp_path, "h-bad.yaml", missing_hash))

    code_reuse = dict(spec, hypothesis_id="h-bad2")
    code_reuse["idea_sources"] = [
        dict(paper_source(), usage={"mode": "idea_only", "code_reuse_allowed": True})
    ]
    with pytest.raises(ResearchLoopError, match="must remain false"):
        add_hypothesis(mock_repo, spec_path=write_yaml_spec(tmp_path, "h-bad2.yaml", code_reuse))

    proposal = {
        "schema_version": 2,
        "proposal_id": "round-sources",
        "items": [
            {
                "slot": "explore",
                "hypothesis": {
                    "hypothesis_id": "h-pack",
                    "statement": "Sequence packing raises throughput without hurting the metric.",
                    "prediction": "The metric holds while runtime drops.",
                    "falsification_criteria": "The metric regresses beyond noise tolerance.",
                    "family": "packing",
                    "origin_evidence": [
                        {"experiment_id": "baseline", "reason": "Baseline runtime dominates."}
                    ],
                    "idea_sources": [paper_source()],
                },
                "candidate": candidate_spec(
                    "explore-pack", hypothesis_id="h-pack", trace="explore", operator="draft", family="packing"
                ),
                "idea_sources": [paper_source()],
            }
        ],
    }
    result = validate_proposal(
        mock_repo, spec_path=write_yaml_spec(tmp_path, "round-sources.yaml", proposal)
    )
    assert result["counts"]["accepted"] == 1
    assert result["counts"]["idea_sources"] == 1


def test_portfolio_lint_flags_and_clears_coverage_gaps(mock_repo: Path, tmp_path: Path) -> None:
    approve_v2(mock_repo, write_profile(tmp_path, selector="diagnostic", transitions=[]))
    record_baseline(mock_repo)
    add_hypothesis(mock_repo, spec_path=write_hypothesis(tmp_path))
    for candidate_id in ("first", "second"):
        add_candidate(
            mock_repo,
            spec_path=write_candidate(
                tmp_path,
                candidate_id=candidate_id,
                parent_id="baseline",
                operator="improve",
                trace="exploit",
                scores=standard_scores(0.7),
                family="candidate-pool",
            ),
        )

    report = portfolio_lint(mock_repo)
    rules = [warning["rule"] for warning in report["portfolio_health"]["warnings"]]
    assert report["selector"] == "diagnostic"
    assert report["pool"] == {"pending": 2, "proposed": 0}
    assert rules == ["L1-single-family", "L3-diagnose-missing", "L5-duplicate-shape"]

    proposal = {
        "schema_version": 2,
        "proposal_id": "round-2",
        "items": [
            {
                "slot": "diagnose",
                "candidate": candidate_spec(
                    "diagnose-pool",
                    hypothesis_id="h-bottleneck",
                    trace="diagnose",
                    operator="diagnose",
                    family="diagnosis",
                ),
            }
        ],
    }
    spec_path = write_yaml_spec(tmp_path, "round-2.yaml", proposal)
    cleared = portfolio_lint(mock_repo, spec_path=spec_path)
    cleared_rules = [warning["rule"] for warning in cleared["portfolio_health"]["warnings"]]
    assert cleared["pool"] == {"pending": 2, "proposed": 1}
    assert "L1-single-family" not in cleared_rules
    assert "L3-diagnose-missing" not in cleared_rules
    assert "L5-duplicate-shape" in cleared_rules


def test_portfolio_lint_flags_falsified_recombine_source(mock_repo: Path, tmp_path: Path) -> None:
    approve_v2(mock_repo, write_profile(tmp_path, selector="diagnostic", transitions=[]))
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
    metadata = prepare_experiment(
        mock_repo, experiment_id="diagnose-pool", hypothesis=None, candidate_id="diagnose-pool"
    )
    commit_config(Path(metadata["worktree"]), diagnostic=True)
    execute_experiment(mock_repo, experiment_id="diagnose-pool", mode="full")
    assert evaluate_experiment(mock_repo, experiment_id="diagnose-pool")["status"] == "inconclusive"
    record_experiment(mock_repo, experiment_id="diagnose-pool")
    add_hypothesis_evidence(
        mock_repo,
        spec_path=write_yaml_spec(
            tmp_path,
            "falsifies.yaml",
            {
                "event_id": "diagnose-falsifies",
                "hypothesis_id": "h-bottleneck",
                "experiment_id": "diagnose-pool",
                "relation": "falsifies",
                "observation": "The diagnostic artifact contradicts the prediction.",
                "source": {"type": "artifact", "path": "results/metrics.json"},
                "rationale": "The declared falsification criterion is met.",
                "assessment": "falsified",
            },
        ),
    )

    recombine_item = {
        "slot": "recombine",
        "hypothesis": {
            "hypothesis_id": "h-combo",
            "statement": "The pool change helps only under the diagnostic condition.",
            "prediction": "The combination improves the metric although one part alone did not.",
            "falsification_criteria": "The combination performs no better than its parts.",
            "family": "interaction",
            "origin_evidence": [
                {"experiment_id": "diagnose-pool", "reason": "Recorded interaction signal."}
            ],
        },
        "candidate": {
            "candidate_id": "combo",
            "hypothesis_id": "h-combo",
            "statement": "Combine the diagnostic condition with the pool change.",
            "family": "interaction",
            "operator": "recombine",
            "trace": "exploit",
            "primary_parent_id": "diagnose-pool",
            "source_parent_ids": ["diagnose-pool", "baseline"],
            "evidence": [{"experiment_id": "diagnose-pool", "reason": "Recorded parent evidence."}],
            "scores": {
                field: {"value": value, "reason": f"evidence-backed {field}"}
                for field, value in standard_scores(0.5).items()
            },
            "estimated_cost": 1,
        },
    }
    proposal = {"schema_version": 2, "proposal_id": "round-3", "items": [recombine_item]}
    flagged = portfolio_lint(
        mock_repo, spec_path=write_yaml_spec(tmp_path, "round-3.yaml", proposal)
    )
    flagged_rules = {
        warning["rule"]: warning for warning in flagged["portfolio_health"]["warnings"]
    }
    assert flagged_rules["L4-falsified-source-recombine"]["refs"] == ["diagnose-pool"]

    recombine_item["candidate"]["interaction_rationale"] = (
        "The pool change was ineffective alone but its mechanism requires the diagnostic condition."
    )
    cleared = portfolio_lint(
        mock_repo, spec_path=write_yaml_spec(tmp_path, "round-4.yaml", proposal)
    )
    assert all(
        warning["rule"] != "L4-falsified-source-recombine"
        for warning in cleared["portfolio_health"]["warnings"]
    )

    add_hypothesis(
        mock_repo, spec_path=write_yaml_spec(tmp_path, "h-combo.yaml", recombine_item["hypothesis"])
    )
    add_candidate(
        mock_repo, spec_path=write_yaml_spec(tmp_path, "combo.yaml", recombine_item["candidate"])
    )
    assert get_candidate(mock_repo, "combo")["interaction_rationale"].startswith("The pool change")
    stored = portfolio_lint(mock_repo)
    assert stored["pool"] == {"pending": 1, "proposed": 0}
    assert all(
        warning["rule"] != "L4-falsified-source-recombine"
        for warning in stored["portfolio_health"]["warnings"]
    )

    bad = candidate_spec(
        "bad-rationale", hypothesis_id="h-combo", trace="exploit", operator="improve", family="interaction"
    )
    bad["interaction_rationale"] = "not a recombine candidate"
    with pytest.raises(ResearchLoopError, match="applies only to recombine"):
        add_candidate(mock_repo, spec_path=write_yaml_spec(tmp_path, "bad-rationale.yaml", bad))
