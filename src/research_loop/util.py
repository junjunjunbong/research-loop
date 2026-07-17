from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import yaml

from .errors import ResearchLoopError


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def canonical_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def read_yaml(path: Path) -> Dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ResearchLoopError(f"cannot read YAML {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ResearchLoopError(f"YAML root must be a mapping: {path}")
    return value


def write_yaml(path: Path, value: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(value, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def read_json(path: Path) -> Dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ResearchLoopError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ResearchLoopError(f"JSON root must be an object: {path}")
    return value


def write_json(path: Path, value: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    result: List[Dict[str, Any]] = []
    try:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ResearchLoopError(f"JSONL line must be an object: {path}:{number}")
            result.append(value)
    except (OSError, json.JSONDecodeError) as exc:
        raise ResearchLoopError(f"cannot read JSONL {path}: {exc}") from exc
    return result


def append_jsonl(path: Path, value: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")


def run(
    argv: Iterable[str],
    *,
    cwd: Path,
    check: bool = True,
    text: bool = True,
) -> subprocess.CompletedProcess:
    command = [str(part) for part in argv]
    try:
        result = subprocess.run(
            command,
            cwd=str(cwd),
            check=False,
            capture_output=True,
            text=text,
        )
    except OSError as exc:
        raise ResearchLoopError(f"failed to run {command[0]}: {exc}") from exc
    if check and result.returncode != 0:
        stderr = (result.stderr or "").strip()
        raise ResearchLoopError(
            f"command failed ({result.returncode}): {' '.join(command)}"
            + (f"\n{stderr}" if stderr else "")
        )
    return result


def require_relative_path(value: str, field: str) -> Path:
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ResearchLoopError(f"{field} must stay inside the project: {value}")
    return path


def confined_path(root: Path, value: str, field: str) -> Path:
    relative = require_relative_path(value, field)
    root_resolved = root.resolve()
    result = (root_resolved / relative).resolve()
    if result != root_resolved and root_resolved not in result.parents:
        raise ResearchLoopError(f"{field} escapes the project: {value}")
    return result


def dotted_get(value: Any, dotted_key: str) -> Any:
    current = value
    for part in dotted_key.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            raise ResearchLoopError(f"key not found: {dotted_key}")
    return current


def list_files(root: Path, *, excluded: Optional[List[str]] = None) -> List[Path]:
    excluded = excluded or [".git", ".research", ".venv", "node_modules"]
    result: List[Path] = []
    for path in root.rglob("*"):
        try:
            relative = path.relative_to(root)
        except ValueError:
            continue
        if any(part in excluded for part in relative.parts):
            continue
        if path.is_file():
            result.append(path)
    return result
