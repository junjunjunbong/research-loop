from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from research_loop.errors import ResearchLoopError
from research_loop.inspector import inspect_project
from research_loop.planning import ensure_approved, save_plan
from research_loop.schema import VALID_STATUSES, normalize_profile, validate_profile
from research_loop.state import load_profile, setup_project


ROOT = Path(__file__).resolve().parents[1]


def load_example() -> dict:
    return yaml.safe_load((ROOT / "examples" / "mock-profile.yaml").read_text(encoding="utf-8"))


def test_inspect_is_read_only_and_finds_evidence(mock_repo: Path) -> None:
    before = sorted(path.relative_to(mock_repo) for path in mock_repo.rglob("*") if ".git" not in path.parts)
    report = inspect_project(mock_repo)
    after = sorted(path.relative_to(mock_repo) for path in mock_repo.rglob("*") if ".git" not in path.parts)
    assert report["git"]["is_repo"] is True
    assert report["languages"]["python"] == 1
    assert any(item["path"] == "experiment.py" for item in report["candidates"]["entrypoints"])
    assert before == after


def test_setup_splits_profile_and_excludes_state(mock_repo: Path) -> None:
    result = setup_project(mock_repo, ROOT / "examples" / "mock-profile.yaml")
    profile = load_profile(mock_repo)
    assert result["campaign_id"] == "mock-campaign"
    assert profile["context"]["goal"].startswith("Improve")
    assert (mock_repo / ".research" / "experiments.tsv").is_file()
    assert "/.research/" in (mock_repo / ".git" / "info" / "exclude").read_text(encoding="utf-8")
    assert not __import__("subprocess").run(
        ["git", "status", "--short"], cwd=mock_repo, capture_output=True, text=True, check=True
    ).stdout


def test_non_git_setup_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ResearchLoopError, match="not a Git repository"):
        setup_project(tmp_path, ROOT / "examples" / "mock-profile.yaml")


def test_dirty_repo_blocks_plan(mock_repo: Path) -> None:
    setup_project(mock_repo, ROOT / "examples" / "mock-profile.yaml")
    (mock_repo / "config.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(ResearchLoopError, match="clean base worktree"):
        save_plan(mock_repo)


def test_profile_rejects_secret_values_as_fields(mock_repo: Path) -> None:
    profile = normalize_profile(load_example(), mock_repo)
    profile["environment"]["api_token"] = "forbidden"
    with pytest.raises(ResearchLoopError, match="secret-like field"):
        validate_profile(profile, mock_repo)


def test_profile_rejects_path_escape(mock_repo: Path) -> None:
    profile = normalize_profile(load_example(), mock_repo)
    profile["context"]["allowed_paths"] = ["../outside"]
    with pytest.raises(ResearchLoopError, match="must stay inside"):
        validate_profile(profile, mock_repo)


def test_profile_rejects_ambiguous_evaluator(mock_repo: Path) -> None:
    profile = normalize_profile(load_example(), mock_repo)
    del profile["evaluation"]["primary_metric"]["parser"]
    with pytest.raises(ResearchLoopError, match="must be a mapping"):
        validate_profile(profile, mock_repo)


def test_status_enum_is_exact() -> None:
    assert VALID_STATUSES == {"promising", "keep", "discard", "inconclusive", "crash", "invalid"}


def test_profile_change_invalidates_approval(approved_repo: Path) -> None:
    environment_path = approved_repo / ".research" / "environment.yaml"
    document = yaml.safe_load(environment_path.read_text(encoding="utf-8"))
    document["environment"]["timeout_seconds"] = 29
    environment_path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    with pytest.raises(ResearchLoopError, match="approval is stale"):
        ensure_approved(approved_repo)
