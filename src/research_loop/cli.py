from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

from .errors import ResearchLoopError
from .executor import execute_experiment
from .experiments import prepare_experiment
from .inspector import inspect_project
from .ledger import campaign_status, checkpoint, record_experiment
from .metrics import evaluate_experiment
from .planning import approve_plan, save_plan
from .state import profile_validation, setup_project


def _repo_parser(subparsers: argparse._SubParsersAction, name: str, help_text: str) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(name, help=help_text)
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="Target Git project")
    return parser


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="research-loop")
    parser.add_argument("--version", action="version", version="research-loop 0.1.0")
    subparsers = parser.add_subparsers(dest="command", required=True)

    _repo_parser(subparsers, "inspect", "Inspect project evidence without changing it")
    setup = _repo_parser(subparsers, "setup", "Materialize a compiled Research Profile")
    setup.add_argument("--profile", type=Path, required=True, help="Compiled profile YAML")
    _repo_parser(subparsers, "validate", "Validate the generated Research Profile")
    _repo_parser(subparsers, "plan", "Render and save a dry-run campaign plan")
    approve = _repo_parser(subparsers, "approve", "Record user approval for an exact plan hash")
    approve.add_argument("--plan-hash", required=True)

    prepare = _repo_parser(subparsers, "prepare", "Create an isolated experiment worktree")
    prepare.add_argument("--id", required=True, dest="experiment_id")
    prepare.add_argument("--hypothesis", required=True)
    prepare.add_argument("--hypothesis-id")
    prepare.add_argument("--parent")
    prepare.add_argument("--baseline", action="store_true")

    execute = _repo_parser(subparsers, "execute", "Execute an approved smoke or full command")
    execute.add_argument("--id", required=True, dest="experiment_id")
    execute.add_argument("--mode", choices=("smoke", "full"), required=True)

    evaluate = _repo_parser(subparsers, "evaluate", "Extract authoritative metrics and decide status")
    evaluate.add_argument("--id", required=True, dest="experiment_id")
    evaluate.add_argument("--mode", choices=("smoke", "full"), default="full")

    record = _repo_parser(subparsers, "record", "Append an evaluated full run to the ledger")
    record.add_argument("--id", required=True, dest="experiment_id")
    record.add_argument("--description")

    checkpoint_parser = _repo_parser(subparsers, "checkpoint", "Refresh durable state and handoff")
    checkpoint_parser.add_argument("--current", required=True)
    checkpoint_parser.add_argument("--next", required=True, dest="next_action")
    _repo_parser(subparsers, "status", "Summarize campaign progress")
    return parser


def dispatch(args: argparse.Namespace) -> Dict[str, Any]:
    repo = args.repo.resolve()
    if args.command == "inspect":
        return inspect_project(repo)
    if args.command == "setup":
        return setup_project(repo, args.profile)
    if args.command == "validate":
        return profile_validation(repo)
    if args.command == "plan":
        return save_plan(repo)
    if args.command == "approve":
        return approve_plan(repo, args.plan_hash)
    if args.command == "prepare":
        return prepare_experiment(
            repo,
            experiment_id=args.experiment_id,
            hypothesis=args.hypothesis,
            hypothesis_id=args.hypothesis_id,
            parent=args.parent,
            baseline=args.baseline,
        )
    if args.command == "execute":
        return execute_experiment(repo, experiment_id=args.experiment_id, mode=args.mode)
    if args.command == "evaluate":
        return evaluate_experiment(repo, experiment_id=args.experiment_id, mode=args.mode)
    if args.command == "record":
        return record_experiment(repo, experiment_id=args.experiment_id, description=args.description)
    if args.command == "checkpoint":
        return checkpoint(repo, current=args.current, next_action=args.next_action)
    if args.command == "status":
        return campaign_status(repo)
    raise ResearchLoopError(f"unsupported command: {args.command}")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = dispatch(args)
    except ResearchLoopError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps({"ok": True, "result": result}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
