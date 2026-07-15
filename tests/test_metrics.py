from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_loop.errors import ResearchLoopError
from research_loop.metrics import parse_value


def test_json_parser(tmp_path: Path) -> None:
    (tmp_path / "metrics.json").write_text('{"metrics":{"score":0.75}}\n', encoding="utf-8")
    value = parse_value(
        {"type": "json", "path": "metrics.json", "key": "metrics.score"},
        worktree=tmp_path,
        run_log=tmp_path / "run.log",
    )
    assert value == 0.75


def test_jsonl_parser_uses_last_matching_value(tmp_path: Path) -> None:
    (tmp_path / "metrics.jsonl").write_text(
        '{"score":0.5}\nnot-json\n{"score":0.7}\n',
        encoding="utf-8",
    )
    value = parse_value(
        {"type": "jsonl", "path": "metrics.jsonl", "key": "score"},
        worktree=tmp_path,
        run_log=tmp_path / "run.log",
    )
    assert value == 0.7


def test_regex_parser_uses_run_log(tmp_path: Path) -> None:
    log = tmp_path / "run.log"
    log.write_text("validation score=0.8125\n", encoding="utf-8")
    value = parse_value(
        {"type": "regex", "source": "run_log", "pattern": r"score=([0-9.]+)", "group": 1},
        worktree=tmp_path,
        run_log=log,
    )
    assert value == "0.8125"


def test_parser_failure_is_explicit(tmp_path: Path) -> None:
    with pytest.raises(ResearchLoopError, match="metric source is missing"):
        parse_value(
            {"type": "json", "path": "missing.json", "key": "score"},
            worktree=tmp_path,
            run_log=tmp_path / "run.log",
        )

