from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from research_loop.errors import ResearchLoopError
from research_loop.hypotheses import add_hypothesis
from research_loop.knowledge import add_pack_record, verify_pack
from research_loop.planning import save_plan
from research_loop.proposals import validate_proposal
from research_loop.schema import normalize_profile, validate_profile
from research_loop.state import campaign_dir
from test_proposals import candidate_spec, paper_source, write_yaml_spec
from test_v2_strategy import approve_v2, record_baseline, write_profile


ROOT = Path(__file__).resolve().parents[1]


def write_pack_profile(tmp_path: Path, knowledge_access: dict) -> Path:
    path = write_profile(tmp_path, selector="diagnostic", transitions=[])
    profile = yaml.safe_load(path.read_text(encoding="utf-8"))
    profile["policy"]["knowledge_access"] = knowledge_access
    path.write_text(yaml.safe_dump(profile, sort_keys=False), encoding="utf-8")
    return path


def record_spec(source_id: str = "gate-paper", **overrides: object) -> dict:
    spec = {
        "source_id": source_id,
        **paper_source(),
        "prohibited_interpretations": ["do not modify the evaluator"],
    }
    spec.update(overrides)
    return spec


def test_knowledge_access_schema_validation(mock_repo: Path) -> None:
    def fresh() -> dict:
        return normalize_profile(
            yaml.safe_load((ROOT / "examples" / "mock-profile-v2.yaml").read_text(encoding="utf-8")),
            mock_repo,
        )

    profile = fresh()
    assert "knowledge_access" not in profile["policy"]
    validate_profile(profile, mock_repo)

    profile["policy"]["knowledge_access"] = {"mode": "local_pack"}
    validate_profile(profile, mock_repo)

    invalid_cases = (
        ({"mode": "web"}, "knowledge_access.mode"),
        ({"mode": "agent_retrieval"}, "must be true for agent_retrieval"),
        ({"mode": "local_pack", "allow_network": True}, "only allowed for agent_retrieval"),
        ({"mode": "local_pack", "allowed_source_types": ["blog"]}, "allowed_source_types"),
        ({"mode": "local_pack", "max_sources_per_round": 0}, "max_sources_per_round"),
    )
    for access, message in invalid_cases:
        invalid = fresh()
        invalid["policy"]["knowledge_access"] = access
        with pytest.raises(ResearchLoopError, match=message):
            validate_profile(invalid, mock_repo)


def test_pack_add_verify_and_dry_run(mock_repo: Path, tmp_path: Path) -> None:
    approve_v2(
        mock_repo,
        write_pack_profile(
            tmp_path, {"mode": "local_pack", "allowed_source_types": ["paper", "user_note"]}
        ),
    )
    plan = save_plan(mock_repo)
    assert plan["dry_run"]["knowledge_access"]["mode"] == "local_pack"
    assert plan["dry_run"]["knowledge_access"]["allow_network"] is False

    added = add_pack_record(
        mock_repo, spec_path=write_yaml_spec(tmp_path, "source.yaml", record_spec())
    )
    assert added["record"]["usage"] == {"mode": "idea_only", "code_reuse_allowed": False}
    report = verify_pack(mock_repo)
    assert report["records"] == 1
    assert report["source_ids"] == ["gate-paper"]

    with pytest.raises(ResearchLoopError, match="already exists"):
        add_pack_record(mock_repo, spec_path=write_yaml_spec(tmp_path, "dup.yaml", record_spec()))
    with pytest.raises(ResearchLoopError, match="not allowed by knowledge_access"):
        add_pack_record(
            mock_repo,
            spec_path=write_yaml_spec(
                tmp_path, "pr.yaml", record_spec("other-pr", source_type="pull_request")
            ),
        )
    with pytest.raises(ResearchLoopError, match="secret-like"):
        add_pack_record(
            mock_repo,
            spec_path=write_yaml_spec(
                tmp_path, "secret.yaml", record_spec("leaky", api_key="ENV_NAME")
            ),
        )

    pack = campaign_dir(mock_repo) / "knowledge"
    rogue = pack / "records" / "rogue.json"
    rogue.write_text("{}", encoding="utf-8")
    with pytest.raises(ResearchLoopError, match="not listed"):
        verify_pack(mock_repo)
    rogue.unlink()

    target = pack / "records" / "gate-paper.json"
    target.write_text(target.read_text(encoding="utf-8").replace("stabilizes", "improves"), encoding="utf-8")
    with pytest.raises(ResearchLoopError, match="hash mismatch"):
        verify_pack(mock_repo)


def test_sources_must_be_registered_when_pack_enabled(mock_repo: Path, tmp_path: Path) -> None:
    approve_v2(
        mock_repo,
        write_pack_profile(tmp_path, {"mode": "local_pack", "allowed_source_types": ["paper"]}),
    )
    record_baseline(mock_repo)
    hypothesis = {
        "hypothesis_id": "h-gate",
        "statement": "Gating the score reduces noise.",
        "prediction": "The primary metric improves beyond noise tolerance.",
        "falsification_criteria": "The metric does not improve beyond noise tolerance.",
        "family": "gating",
        "origin_evidence": [{"experiment_id": "baseline", "reason": "Baseline shows unstable scores."}],
        "idea_sources": [paper_source()],
    }
    with pytest.raises(ResearchLoopError, match="not registered in the knowledge pack"):
        add_hypothesis(mock_repo, spec_path=write_yaml_spec(tmp_path, "h-gate.yaml", hypothesis))

    add_pack_record(mock_repo, spec_path=write_yaml_spec(tmp_path, "source.yaml", record_spec()))
    created = add_hypothesis(mock_repo, spec_path=write_yaml_spec(tmp_path, "h-gate2.yaml", hypothesis))
    assert created["idea_sources"][0]["locator"] == "example-archive:2401.00001v2"

    unregistered = dict(paper_source(), locator="example-archive:2402.99999v1")
    proposal = {
        "schema_version": 2,
        "proposal_id": "round-pack",
        "items": [
            {
                "slot": "exploit",
                "candidate": candidate_spec(
                    "use-gate", hypothesis_id="h-gate", trace="exploit", operator="improve", family="gating"
                ),
                "idea_sources": [paper_source()],
            },
            {
                "slot": "exploit",
                "candidate": candidate_spec(
                    "unknown-source",
                    hypothesis_id="h-gate",
                    trace="exploit",
                    operator="improve",
                    family="gating-two",
                ),
                "idea_sources": [unregistered],
            },
        ],
    }
    result = validate_proposal(
        mock_repo, spec_path=write_yaml_spec(tmp_path, "round-pack.yaml", proposal)
    )
    assert result["counts"]["accepted"] == 1
    assert result["items"][0]["candidate"]["candidate_id"] == "use-gate"
    assert "not registered in the knowledge pack" in result["rejected"][0]["reasons"][0]


def test_max_sources_per_round(mock_repo: Path, tmp_path: Path) -> None:
    approve_v2(
        mock_repo,
        write_pack_profile(
            tmp_path,
            {"mode": "local_pack", "allowed_source_types": ["paper"], "max_sources_per_round": 1},
        ),
    )
    record_baseline(mock_repo)
    add_pack_record(mock_repo, spec_path=write_yaml_spec(tmp_path, "one.yaml", record_spec("one")))
    second = record_spec("two", locator="example-archive:2402.00002v1")
    add_pack_record(mock_repo, spec_path=write_yaml_spec(tmp_path, "two.yaml", second))
    proposal = {
        "schema_version": 2,
        "proposal_id": "round-over",
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
                "idea_sources": [{k: v for k, v in second.items() if k not in {"source_id", "prohibited_interpretations"}}],
            }
        ],
    }
    with pytest.raises(ResearchLoopError, match="max_sources_per_round"):
        validate_proposal(mock_repo, spec_path=write_yaml_spec(tmp_path, "round-over.yaml", proposal))
