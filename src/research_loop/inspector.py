from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Dict, List

from .git import git_info
from .util import list_files


LANGUAGE_BY_SUFFIX = {
    ".py": "python",
    ".ipynb": "jupyter",
    ".js": "javascript",
    ".ts": "typescript",
    ".rs": "rust",
    ".go": "go",
    ".java": "java",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".c": "c",
    ".sh": "shell",
}


def _candidate(path: Path, root: Path, reason: str) -> Dict[str, str]:
    return {"path": str(path.relative_to(root)), "reason": reason}


def inspect_project(repo: Path) -> Dict[str, Any]:
    repo = repo.resolve()
    files = list_files(repo)
    language_counts = Counter(
        LANGUAGE_BY_SUFFIX[path.suffix.lower()]
        for path in files
        if path.suffix.lower() in LANGUAGE_BY_SUFFIX
    )

    package_managers: List[Dict[str, str]] = []
    package_evidence = {
        "uv.lock": "uv lockfile",
        "pyproject.toml": "Python project metadata",
        "requirements.txt": "pip requirements",
        "environment.yml": "conda environment",
        "package.json": "Node project metadata",
        "Cargo.toml": "Rust project metadata",
        "go.mod": "Go module metadata",
    }
    for filename, reason in package_evidence.items():
        path = repo / filename
        if path.exists():
            package_managers.append(_candidate(path, repo, reason))

    entrypoints: List[Dict[str, str]] = []
    evaluators: List[Dict[str, str]] = []
    configs: List[Dict[str, str]] = []
    datasets: List[Dict[str, str]] = []
    for path in files:
        name = path.name.lower()
        if path.suffix.lower() in {".py", ".sh", ".js", ".ts"} and any(
            token in path.stem.lower() for token in ("run", "main", "train", "experiment")
        ):
            entrypoints.append(_candidate(path, repo, "entrypoint-like filename"))
        if any(token in path.stem.lower() for token in ("eval", "metric", "score")):
            evaluators.append(_candidate(path, repo, "evaluation-like filename"))
        if path.suffix.lower() in {".yaml", ".yml", ".toml", ".json"} and any(
            token in name for token in ("config", "setting", "recipe")
        ):
            configs.append(_candidate(path, repo, "configuration-like filename"))
    for dirname in ("data", "dataset", "datasets"):
        path = repo / dirname
        if path.is_dir():
            datasets.append(_candidate(path, repo, "conventional dataset directory"))

    for special in ("Makefile", "README.md"):
        path = repo / special
        if path.exists():
            entrypoints.append(_candidate(path, repo, "may document runnable commands"))

    return {
        "repo": str(repo),
        "git": git_info(repo),
        "languages": dict(language_counts.most_common()),
        "package_manager_evidence": package_managers,
        "candidates": {
            "entrypoints": entrypoints[:30],
            "evaluators": evaluators[:30],
            "configs": configs[:30],
            "datasets": datasets[:30],
        },
        "notes": [
            "Candidates are evidence, not approved commands.",
            "No file contents, credentials, or secret values are included in this report.",
        ],
    }
