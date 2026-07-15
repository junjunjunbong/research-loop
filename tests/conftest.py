from __future__ import annotations

import shutil
import subprocess
import hashlib
from pathlib import Path
from typing import Dict

import pytest
from research_loop.planning import approve_plan, save_plan
from research_loop.state import setup_project


ROOT = Path(__file__).resolve().parents[1]


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


@pytest.fixture
def mock_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "mock-project"
    shutil.copytree(ROOT / "examples" / "mock-project", repo)
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.name", "Research Loop Test")
    git(repo, "config", "user.email", "research-loop@example.test")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "fixture: initial project")
    yield repo
    digest = hashlib.sha256(str(repo.resolve()).encode("utf-8")).hexdigest()[:12]
    candidate = Path.home() / ".cache" / "research-loop" / "worktrees" / digest
    shutil.rmtree(candidate, ignore_errors=True)


@pytest.fixture
def approved_repo(mock_repo: Path) -> Path:
    setup_project(mock_repo, ROOT / "examples" / "mock-profile.yaml")
    plan = save_plan(mock_repo)
    approve_plan(mock_repo, plan["plan_hash"])
    return mock_repo


def commit_config(worktree: Path, **updates: object) -> None:
    path = worktree / "config.json"
    import json

    config: Dict[str, object] = json.loads(path.read_text(encoding="utf-8"))
    config.update(updates)
    path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    git(worktree, "add", "config.json")
    git(worktree, "commit", "-m", "experiment: update mock configuration")
