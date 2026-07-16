from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Dict, Optional

from .errors import ResearchLoopError
from .util import run


SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


def repo_root(path: Path) -> Path:
    path = path.resolve()
    result = run(["git", "rev-parse", "--show-toplevel"], cwd=path, check=False)
    if result.returncode != 0:
        raise ResearchLoopError(f"target is not a Git repository: {path}")
    return Path(result.stdout.strip()).resolve()


def git_info(path: Path) -> Dict[str, Any]:
    path = path.resolve()
    top = run(["git", "rev-parse", "--show-toplevel"], cwd=path, check=False)
    if top.returncode != 0:
        return {"is_repo": False, "root": str(path), "clean": False, "status": []}
    root = Path(top.stdout.strip()).resolve()
    branch = run(["git", "branch", "--show-current"], cwd=root).stdout.strip()
    commit = run(["git", "rev-parse", "HEAD"], cwd=root, check=False)
    status = run(["git", "status", "--short"], cwd=root).stdout.splitlines()
    return {
        "is_repo": True,
        "root": str(root),
        "branch": branch,
        "commit": commit.stdout.strip() if commit.returncode == 0 else None,
        "clean": not status,
        "status": status,
    }


def ensure_clean(path: Path) -> None:
    info = git_info(path)
    if not info["is_repo"]:
        raise ResearchLoopError("campaigns require an existing Git repository")
    if not info["commit"]:
        raise ResearchLoopError("campaigns require at least one Git commit")
    if not info["clean"]:
        preview = ", ".join(info["status"][:5])
        raise ResearchLoopError(f"campaign requires a clean base worktree: {preview}")


def add_local_exclude(path: Path, pattern: str = "/.research/") -> None:
    root = repo_root(path)
    result = run(["git", "rev-parse", "--git-path", "info/exclude"], cwd=root)
    exclude = Path(result.stdout.strip())
    if not exclude.is_absolute():
        exclude = root / exclude
    exclude.parent.mkdir(parents=True, exist_ok=True)
    existing = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
    lines = existing.splitlines()
    if pattern not in lines:
        with exclude.open("a", encoding="utf-8") as handle:
            if existing and not existing.endswith("\n"):
                handle.write("\n")
            handle.write(pattern + "\n")


def validate_slug(value: str, field: str) -> str:
    if not SLUG_RE.fullmatch(value):
        raise ResearchLoopError(f"{field} must match {SLUG_RE.pattern}: {value}")
    return value


def cache_worktree_root(path: Path, campaign_id: str) -> Path:
    root = repo_root(path)
    digest = hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:12]
    return Path.home() / ".cache" / "research-loop" / "worktrees" / digest / campaign_id


def branch_exists(path: Path, branch: str) -> bool:
    result = run(["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"], cwd=repo_root(path), check=False)
    return result.returncode == 0


def create_worktree(path: Path, *, branch: str, destination: Path, parent: str) -> None:
    root = repo_root(path)
    if branch_exists(root, branch):
        raise ResearchLoopError(f"experiment branch already exists: {branch}")
    if destination.exists():
        raise ResearchLoopError(f"worktree destination already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    run(["git", "worktree", "add", "-b", branch, str(destination), parent], cwd=root)


def worktree_head(path: Path) -> str:
    return run(["git", "rev-parse", "HEAD"], cwd=path).stdout.strip()


def worktree_tree(path: Path) -> str:
    return run(["git", "rev-parse", "HEAD^{tree}"], cwd=path).stdout.strip()


def resolve_commit(path: Path, value: str) -> str:
    result = run(["git", "rev-parse", "--verify", f"{value}^{{commit}}"], cwd=repo_root(path), check=False)
    if result.returncode != 0:
        raise ResearchLoopError(f"unknown parent commit or branch: {value}")
    return result.stdout.strip()
