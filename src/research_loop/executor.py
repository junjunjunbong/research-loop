from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from pathlib import Path
from typing import Any, Dict

from .errors import ResearchLoopError
from .experiments import experiment_dir
from .git import git_info, repo_root, worktree_head
from .planning import ensure_approved
from .state import load_profile, research_dir
from .util import confined_path, now_iso, read_json, run, write_json


def _campaign_elapsed(repo: Path) -> float:
    total = 0.0
    runs = research_dir(repo) / "runs"
    for path in runs.glob("*/*/*/manifest.json"):
        try:
            total += float(json.loads(path.read_text(encoding="utf-8")).get("elapsed_seconds", 0))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            continue
    return total


def _path_is_within(path: str, scopes: list[str]) -> bool:
    candidate = Path(path)
    return any(candidate == Path(scope) or Path(scope) in candidate.parents for scope in scopes)


def _validate_change_scope(worktree: Path, parent_commit: str, allowed: list[str], protected: list[str], kind: str) -> list[str]:
    result = run(["git", "diff", "--name-only", f"{parent_commit}..HEAD"], cwd=worktree)
    changed = [line for line in result.stdout.splitlines() if line.strip()]
    if kind != "baseline" and not changed:
        raise ResearchLoopError("experiment commit does not change any files")
    blocked = [path for path in changed if _path_is_within(path, protected)]
    if blocked:
        raise ResearchLoopError(f"experiment changes protected paths: {', '.join(blocked)}")
    outside = [path for path in changed if not _path_is_within(path, allowed)]
    if outside:
        raise ResearchLoopError(f"experiment changes paths outside the approved scope: {', '.join(outside)}")
    return changed


def execute_experiment(repo: Path, *, experiment_id: str, mode: str) -> Dict[str, Any]:
    if mode not in {"smoke", "full"}:
        raise ResearchLoopError("mode must be smoke or full")
    root = repo_root(repo)
    approval = ensure_approved(root)
    profile = load_profile(root)
    exp_dir = experiment_dir(root, experiment_id)
    metadata_path = exp_dir / "experiment.json"
    if not metadata_path.exists():
        raise ResearchLoopError(f"experiment is not prepared: {experiment_id}")
    metadata = read_json(metadata_path)
    worktree = Path(metadata["worktree"]).resolve()
    if not worktree.exists():
        raise ResearchLoopError(f"experiment worktree is missing: {worktree}")
    info = git_info(worktree)
    if not info["clean"]:
        raise ResearchLoopError("experiment worktree must be committed and clean before execution")
    commit = worktree_head(worktree)
    if commit == metadata["parent_commit"]:
        raise ResearchLoopError("experiment branch has no hypothesis commit")
    changed_paths = _validate_change_scope(
        worktree,
        metadata["parent_commit"],
        profile["context"].get("allowed_paths", []),
        profile["context"].get("protected_paths", []),
        metadata["kind"],
    )

    run_dir = exp_dir / mode
    manifest_path = run_dir / "manifest.json"
    if manifest_path.exists():
        raise ResearchLoopError(f"{mode} run already exists for {experiment_id}")
    run_dir.mkdir(parents=True, exist_ok=True)
    log_path = run_dir / "run.log"

    environment = profile["environment"]
    policy = profile["policy"]
    missing_env = [name for name in environment.get("required_env", []) if name not in os.environ]
    if missing_env:
        raise ResearchLoopError(f"missing required environment variables: {', '.join(missing_env)}")
    argv = environment["commands"][mode]
    cwd = confined_path(worktree, environment["cwd"], "environment.cwd")
    if not cwd.is_dir():
        raise ResearchLoopError(f"execution cwd does not exist: {cwd}")
    configured_timeout = min(
        float(environment["timeout_seconds"]),
        float(policy["experiment_timeout_seconds"]),
    )
    remaining = float(policy["campaign_timeout_seconds"]) - _campaign_elapsed(root)
    if remaining <= 0:
        raise ResearchLoopError("campaign wall-clock budget is exhausted")
    if mode == "full" and remaining < configured_timeout:
        raise ResearchLoopError("not enough campaign time remains to start a full experiment")
    timeout = min(configured_timeout, remaining)

    started_at = now_iso()
    started = time.monotonic()
    timed_out = False
    exit_code = 1
    with log_path.open("wb") as log_handle:
        try:
            process = subprocess.Popen(
                argv,
                cwd=str(cwd),
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                shell=False,
                start_new_session=True,
                env=os.environ.copy(),
            )
        except OSError as exc:
            raise ResearchLoopError(f"failed to start approved command {argv[0]}: {exc}") from exc
        try:
            exit_code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=5)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
            exit_code = 124
    elapsed = time.monotonic() - started
    manifest = {
        "schema_version": 0,
        "experiment_id": experiment_id,
        "mode": mode,
        "command": argv,
        "cwd": str(cwd),
        "worktree": str(worktree),
        "branch": metadata["branch"],
        "commit": commit,
        "parent_commit": metadata["parent_commit"],
        "started_at": started_at,
        "finished_at": now_iso(),
        "elapsed_seconds": round(elapsed, 6),
        "timeout_seconds": timeout,
        "timed_out": timed_out,
        "exit_code": exit_code,
        "log_path": str(log_path),
        "plan_hash": approval["plan_hash"],
        "resource_class": environment["resource_class"],
        "required_env_names": environment.get("required_env", []),
        "changed_paths": changed_paths,
    }
    write_json(manifest_path, manifest)
    return manifest
