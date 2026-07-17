from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

from .errors import ResearchLoopError
from .candidates import add_candidate, rank_candidates, scoped_evidence
from .executor import execute_experiment
from .experiments import prepare_experiment
from .hypotheses import add_hypothesis, add_hypothesis_evidence, list_hypotheses
from .inspector import inspect_project
from .ledger import campaign_status, checkpoint, record_experiment
from .metrics import evaluate_experiment
from .planning import approve_plan, save_plan
from .proposals import portfolio_lint, proposal_context, validate_proposal
from .state import (
    activate_campaign,
    list_campaigns,
    new_campaign,
    profile_validation,
    setup_project,
    upgrade_control_plane,
)


def _repo_parser(subparsers: argparse._SubParsersAction, name: str, help_text: str) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(name, help=help_text)
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="Target Git project")
    parser.add_argument("--campaign", help="Campaign id; defaults to the active versioned campaign")
    return parser


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="research-loop")
    parser.add_argument("--version", action="version", version="research-loop 0.4.0")
    subparsers = parser.add_subparsers(dest="command", required=True)

    _repo_parser(subparsers, "inspect", "Inspect project evidence without changing it")
    setup = _repo_parser(subparsers, "setup", "Materialize a compiled Research Profile")
    setup.add_argument("--profile", type=Path, required=True, help="Compiled profile YAML")
    new = _repo_parser(subparsers, "new-campaign", "Create a schema v1 or v2 campaign from an explicit Git base")
    new.add_argument("--profile", type=Path, required=True, help="Compiled schema v1 or v2 profile YAML")
    new.add_argument("--base", default="HEAD", help="Git revision to freeze as the campaign base")
    upgrade = _repo_parser(subparsers, "upgrade", "Check or apply a v0 to v1 control-plane migration")
    upgrade_mode = upgrade.add_mutually_exclusive_group(required=True)
    upgrade_mode.add_argument("--check", action="store_true")
    upgrade_mode.add_argument("--apply", action="store_true")
    _repo_parser(subparsers, "campaign-list", "List local research campaigns")
    activate = _repo_parser(subparsers, "campaign-activate", "Set the active versioned campaign")
    activate.add_argument("--id", required=True, dest="campaign_id")
    _repo_parser(subparsers, "validate", "Validate the generated Research Profile")
    _repo_parser(subparsers, "plan", "Render and save a dry-run campaign plan")
    approve = _repo_parser(subparsers, "approve", "Record user approval for an exact plan hash")
    approve.add_argument("--plan-hash", required=True)

    prepare = _repo_parser(subparsers, "prepare", "Create an isolated experiment worktree")
    prepare.add_argument("--id", required=True, dest="experiment_id")
    prepare.add_argument("--hypothesis")
    prepare.add_argument("--hypothesis-id")
    prepare.add_argument("--parent")
    prepare.add_argument("--baseline", action="store_true")
    prepare.add_argument("--candidate-id")

    candidate_add = _repo_parser(subparsers, "candidate-add", "Register a scored DAG hypothesis candidate")
    candidate_add.add_argument("--spec", type=Path, required=True)
    _repo_parser(subparsers, "candidate-rank", "Rank eligible candidates with the deterministic policy")
    hypothesis_add = _repo_parser(subparsers, "hypothesis-add", "Register a schema v2 research hypothesis")
    hypothesis_add.add_argument("--spec", type=Path, required=True)
    _repo_parser(subparsers, "hypothesis-list", "List schema v2 hypotheses and assessments")
    hypothesis_evidence = _repo_parser(
        subparsers,
        "hypothesis-evidence-add",
        "Append evidence and an assessment to a schema v2 hypothesis",
    )
    hypothesis_evidence.add_argument("--spec", type=Path, required=True)
    evidence = _repo_parser(subparsers, "evidence", "Render operator-scoped experiment evidence")
    evidence.add_argument("--candidate-id")
    evidence.add_argument("--operator")
    evidence.add_argument("--parent-id")
    evidence.add_argument("--source-parent-id", action="append", dest="source_parent_ids")

    proposal_validate = _repo_parser(
        subparsers, "proposal-validate", "Validate a stateless hypothesis/candidate proposal file"
    )
    proposal_validate.add_argument("--spec", type=Path, required=True)
    lint = _repo_parser(
        subparsers, "portfolio-lint", "Report computable coverage warnings for the candidate pool"
    )
    lint.add_argument("--spec", type=Path, help="Optional proposal file to lint together with pending candidates")
    _repo_parser(subparsers, "proposal-context", "Render the deterministic hypothesis-generation context")

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
    if args.command == "new-campaign":
        return new_campaign(repo, profile_path=args.profile, base=args.base)
    if args.command == "upgrade":
        return upgrade_control_plane(repo, apply=args.apply)
    if args.command == "campaign-list":
        return list_campaigns(repo)
    if args.command == "campaign-activate":
        return activate_campaign(repo, args.campaign_id)
    if args.command == "validate":
        return profile_validation(repo, args.campaign)
    if args.command == "plan":
        return save_plan(repo, args.campaign)
    if args.command == "approve":
        return approve_plan(repo, args.plan_hash, args.campaign)
    if args.command == "candidate-add":
        return add_candidate(repo, spec_path=args.spec, campaign=args.campaign)
    if args.command == "candidate-rank":
        return rank_candidates(repo, args.campaign)
    if args.command == "hypothesis-add":
        return add_hypothesis(repo, spec_path=args.spec, campaign=args.campaign)
    if args.command == "hypothesis-list":
        return list_hypotheses(repo, args.campaign)
    if args.command == "hypothesis-evidence-add":
        return add_hypothesis_evidence(repo, spec_path=args.spec, campaign=args.campaign)
    if args.command == "proposal-validate":
        return validate_proposal(repo, spec_path=args.spec, campaign=args.campaign)
    if args.command == "portfolio-lint":
        return portfolio_lint(repo, spec_path=args.spec, campaign=args.campaign)
    if args.command == "proposal-context":
        return proposal_context(repo, args.campaign)
    if args.command == "evidence":
        return scoped_evidence(
            repo,
            candidate_id=args.candidate_id,
            operator=args.operator,
            parent_id=args.parent_id,
            source_parent_ids=args.source_parent_ids,
            campaign=args.campaign,
        )
    if args.command == "prepare":
        return prepare_experiment(
            repo,
            experiment_id=args.experiment_id,
            hypothesis=args.hypothesis,
            hypothesis_id=args.hypothesis_id,
            parent=args.parent,
            baseline=args.baseline,
            candidate_id=args.candidate_id,
            campaign=args.campaign,
        )
    if args.command == "execute":
        return execute_experiment(repo, experiment_id=args.experiment_id, mode=args.mode, campaign=args.campaign)
    if args.command == "evaluate":
        return evaluate_experiment(repo, experiment_id=args.experiment_id, mode=args.mode, campaign=args.campaign)
    if args.command == "record":
        return record_experiment(repo, experiment_id=args.experiment_id, description=args.description, campaign=args.campaign)
    if args.command == "checkpoint":
        return checkpoint(repo, current=args.current, next_action=args.next_action, campaign=args.campaign)
    if args.command == "status":
        return campaign_status(repo, args.campaign)
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
