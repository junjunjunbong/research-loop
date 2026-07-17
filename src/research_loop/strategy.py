from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from .errors import ResearchLoopError
from .state import campaign_dir, load_profile, read_ledger
from .util import append_jsonl, canonical_hash, now_iso, read_json, read_jsonl, write_json


SELECTOR_REGISTRY: Dict[str, Dict[str, Any]] = {
    "diagnostic": {
        "weights": {
            "alignment": 0.25,
            "impact": 0.05,
            "feasibility": 0.20,
            "information_gain": 0.40,
            "novelty": 0.10,
        },
        "preferred_operator": "diagnose",
        "explore_quota": None,
    },
    "balanced": {
        "weights": {
            "alignment": 0.30,
            "impact": 0.25,
            "feasibility": 0.20,
            "information_gain": 0.15,
            "novelty": 0.10,
        },
        "preferred_operator": None,
        "explore_quota": 3,
    },
    "optimization": {
        "weights": {
            "alignment": 0.30,
            "impact": 0.40,
            "feasibility": 0.20,
            "information_gain": 0.05,
            "novelty": 0.05,
        },
        "preferred_operator": None,
        "explore_quota": None,
    },
}


def selector_definition(selector: str) -> Dict[str, Any]:
    definition = SELECTOR_REGISTRY.get(selector)
    if definition is None:
        raise ResearchLoopError(f"unknown selector: {selector}")
    return {
        "weights": dict(definition["weights"]),
        "preferred_operator": definition["preferred_operator"],
        "explore_quota": definition["explore_quota"],
    }


def _state_path(repo: Path, campaign: Optional[str]) -> Path:
    return campaign_dir(repo, campaign) / "strategy-state.json"


def _events_path(repo: Path, campaign: Optional[str]) -> Path:
    return campaign_dir(repo, campaign) / "strategy-events.jsonl"


def _new_state(strategy: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "schema_version": 2,
        "contract_hash": canonical_hash(strategy),
        "active_selector": strategy["initial_selector"],
        "applied_transition_ids": [],
        "updated_at": now_iso(),
    }


def initialize_strategy_state(repo: Path, campaign: Optional[str] = None) -> Dict[str, Any]:
    profile = load_profile(repo, campaign)
    if profile["schema_version"] != 2:
        return {"schema_version": profile["schema_version"], "active_selector": "balanced"}
    expected_hash = canonical_hash(profile["strategy"])
    path = _state_path(repo, campaign)
    current = read_json(path) if path.exists() else None
    if current and current.get("contract_hash") == expected_hash:
        state = current
    else:
        rows = read_ledger(repo, campaign)
        if rows:
            raise ResearchLoopError(
                "Strategy Contract cannot change after the first ledger row; create a new campaign"
            )
        state = _new_state(profile["strategy"])
        write_json(path, state)
        if current is not None:
            append_jsonl(
                _events_path(repo, campaign),
                {
                    "event": "reset-before-first-run",
                    "selector": state["active_selector"],
                    "contract_hash": state["contract_hash"],
                    "created_at": state["updated_at"],
                },
            )
    events = read_jsonl(_events_path(repo, campaign))
    if not any(
        event.get("event") == "approved" and event.get("contract_hash") == expected_hash
        for event in events
    ):
        approved_at = now_iso()
        state["approved_at"] = approved_at
        state["updated_at"] = approved_at
        write_json(path, state)
        append_jsonl(
            _events_path(repo, campaign),
            {
                "event": "approved",
                "selector": state["active_selector"],
                "contract_hash": state["contract_hash"],
                "created_at": approved_at,
            },
        )
    return state


def read_strategy_state(repo: Path, campaign: Optional[str] = None) -> Dict[str, Any]:
    profile = load_profile(repo, campaign)
    if profile["schema_version"] != 2:
        return {
            "schema_version": profile["schema_version"],
            "active_selector": "balanced",
            "applied_transition_ids": [],
        }
    path = _state_path(repo, campaign)
    if not path.exists():
        raise ResearchLoopError("strategy state is missing; approve the schema v2 campaign")
    state = read_json(path)
    if state.get("schema_version") != 2:
        raise ResearchLoopError(f"invalid strategy state: {path}")
    if state.get("contract_hash") != canonical_hash(profile["strategy"]):
        raise ResearchLoopError(
            "Strategy Contract differs from runtime state; re-approve before any run or create a new campaign"
        )
    if state.get("active_selector") not in SELECTOR_REGISTRY:
        raise ResearchLoopError(f"invalid active selector: {state.get('active_selector')!r}")
    return state


def selector_weights(repo: Path, campaign: Optional[str] = None) -> Dict[str, float]:
    selector = read_strategy_state(repo, campaign)["active_selector"]
    return selector_definition(selector)["weights"]


def score_candidate(candidate: Dict[str, Any], selector: str) -> Dict[str, Any]:
    weights = selector_definition(selector)["weights"]
    breakdown = {
        field: round(weights[field] * float(candidate["scores"][field]["value"]), 12)
        for field in weights
    }
    return {
        "selector": selector,
        "selector_weights": dict(weights),
        "priority_breakdown": breakdown,
        "priority": round(sum(breakdown.values()), 12),
    }


def _consecutive_status(rows: List[Dict[str, str]], status: str) -> int:
    count = 0
    for row in reversed([item for item in rows if item.get("kind") != "baseline"]):
        if row.get("status") != status:
            break
        count += 1
    return count


def _trigger_matches(
    trigger: Dict[str, Any], rows: List[Dict[str, str]], max_experiments: int
) -> bool:
    kind = trigger["type"]
    experiments = [row for row in rows if row.get("kind") != "baseline"]
    value = int(trigger.get("value", 0))
    if kind == "baseline_recorded":
        return any(row.get("kind") == "baseline" for row in rows)
    if kind == "experiments_recorded_gte":
        return len(experiments) >= value
    if kind == "promising_results_gte":
        return sum(row.get("status") == "promising" for row in experiments) >= value
    if kind == "consecutive_inconclusive_gte":
        return _consecutive_status(rows, "inconclusive") >= value
    if kind == "target_reached":
        return any(row.get("target_reached", "").lower() == "true" for row in experiments)
    if kind == "remaining_experiments_lte":
        return max(0, max_experiments - len(experiments)) <= value
    return False


def apply_strategy_transition(repo: Path, campaign: Optional[str] = None) -> Optional[Dict[str, Any]]:
    profile = load_profile(repo, campaign)
    if profile["schema_version"] != 2:
        return None
    state = read_strategy_state(repo, campaign)
    rows = read_ledger(repo, campaign)
    applied = set(state.get("applied_transition_ids", []))
    eligible = sorted(
        (
            transition
            for transition in profile["strategy"].get("transitions", [])
            if transition["id"] not in applied
            and transition["from"] == state["active_selector"]
            and _trigger_matches(transition["trigger"], rows, profile["policy"]["max_experiments"])
        ),
        key=lambda item: (item["priority"], item["id"]),
    )
    if not eligible:
        return None
    transition = eligible[0]
    event = {
        "event": "transition",
        "transition_id": transition["id"],
        "from": state["active_selector"],
        "to": transition["to"],
        "trigger": transition["trigger"],
        "ledger_rows": len(rows),
        "created_at": now_iso(),
    }
    state["active_selector"] = transition["to"]
    state.setdefault("applied_transition_ids", []).append(transition["id"])
    state["updated_at"] = event["created_at"]
    write_json(_state_path(repo, campaign), state)
    append_jsonl(_events_path(repo, campaign), event)
    return event


def strategy_status(repo: Path, campaign: Optional[str] = None) -> Dict[str, Any]:
    profile = load_profile(repo, campaign)
    state = read_strategy_state(repo, campaign)
    if profile["schema_version"] != 2:
        return {
            "active_selector": "balanced",
            "selector_weights": selector_definition("balanced")["weights"],
            "selector_score_criteria": {
                name: selector_definition(name) for name in sorted(SELECTOR_REGISTRY)
            },
            "applied_transition_ids": [],
            "applied_transitions": [],
            "pending_transitions": [],
            "next_transition": None,
        }
    applied = set(state.get("applied_transition_ids", []))
    pending = sorted(
        (
            item
            for item in profile["strategy"].get("transitions", [])
            if item["id"] not in applied and item["from"] == state["active_selector"]
        ),
        key=lambda item: (item["priority"], item["id"]),
    )
    applied_events = [
        event for event in read_jsonl(_events_path(repo, campaign)) if event.get("event") == "transition"
    ]
    return {
        "active_selector": state["active_selector"],
        "selector_weights": selector_definition(state["active_selector"])["weights"],
        "selector_score_criteria": {
            name: selector_definition(name) for name in sorted(SELECTOR_REGISTRY)
        },
        "applied_transition_ids": list(state.get("applied_transition_ids", [])),
        "applied_transitions": applied_events,
        "pending_transitions": pending,
        "next_transition": pending[0] if pending else None,
    }
