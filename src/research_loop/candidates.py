from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .errors import ResearchLoopError
from .git import validate_slug
from .state import campaign_dir, load_profile, read_ledger
from .util import now_iso, read_json, read_yaml, write_json


OPERATORS = {"draft", "improve", "debug", "confirm", "recombine"}
V2_OPERATORS = OPERATORS | {"diagnose"}
TRACES = {"exploit", "explore", "confirm"}
V2_TRACES = TRACES | {"diagnose"}
SCORE_FIELDS = ("alignment", "impact", "feasibility", "information_gain", "novelty")
SCORE_WEIGHTS = {
    "alignment": 0.30,
    "impact": 0.25,
    "feasibility": 0.20,
    "information_gain": 0.15,
    "novelty": 0.10,
}


def _store_path(repo: Path, campaign: Optional[str]) -> Path:
    return campaign_dir(repo, campaign) / "candidates.json"


def _load_store(repo: Path, campaign: Optional[str]) -> Dict[str, Any]:
    profile = load_profile(repo, campaign)
    if profile["schema_version"] not in {1, 2}:
        raise ResearchLoopError("candidate DAG features require a schema_version 1 or 2 campaign")
    path = _store_path(repo, campaign)
    if not path.exists():
        raise ResearchLoopError(f"missing candidate store: {path}")
    store = read_json(path)
    if store.get("schema_version") != profile["schema_version"] or not isinstance(store.get("candidates"), list):
        raise ResearchLoopError(f"invalid candidate store: {path}")
    return store


def list_candidates(repo: Path, campaign: Optional[str] = None) -> List[Dict[str, Any]]:
    return list(_load_store(repo, campaign)["candidates"])


def get_candidate(repo: Path, candidate_id: str, campaign: Optional[str] = None) -> Dict[str, Any]:
    for candidate in list_candidates(repo, campaign):
        if candidate.get("candidate_id") == candidate_id:
            return candidate
    raise ResearchLoopError(f"unknown candidate: {candidate_id}")


def _normalize_score(value: Any, field: str) -> Dict[str, Any]:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        numeric = float(value)
        reason = ""
    elif isinstance(value, dict):
        numeric = value.get("value")
        reason = value.get("reason", "")
        if not isinstance(numeric, (int, float)) or isinstance(numeric, bool):
            raise ResearchLoopError(f"scores.{field}.value must be numeric")
        numeric = float(numeric)
        if not isinstance(reason, str):
            raise ResearchLoopError(f"scores.{field}.reason must be a string")
    else:
        raise ResearchLoopError(f"scores.{field} must be numeric or a value/reason mapping")
    if not 0 <= numeric <= 1:
        raise ResearchLoopError(f"scores.{field} must be between 0 and 1")
    return {"value": numeric, "reason": reason}


def _parent_rows(rows: List[Dict[str, str]]) -> Dict[str, Dict[str, str]]:
    return {row["experiment_id"]: row for row in rows}


def _normalize_candidate(spec: Dict[str, Any], version: int) -> Dict[str, Any]:
    candidate_id = validate_slug(str(spec.get("candidate_id", "")), "candidate_id")
    hypothesis_id = validate_slug(str(spec.get("hypothesis_id", "")), "hypothesis_id")
    statement = spec.get("statement")
    family = spec.get("family")
    operator = spec.get("operator")
    trace = spec.get("trace")
    primary_parent_id = spec.get("primary_parent_id")
    source_parent_ids = spec.get("source_parent_ids", [primary_parent_id])
    evidence = spec.get("evidence", [])
    estimated_cost = spec.get("estimated_cost", 1)
    if not isinstance(statement, str) or not statement.strip():
        raise ResearchLoopError("candidate statement must be non-empty")
    if not isinstance(family, str) or not family.strip():
        raise ResearchLoopError("candidate family must be non-empty")
    validate_slug(family, "family")
    operators = V2_OPERATORS if version == 2 else OPERATORS
    traces = V2_TRACES if version == 2 else TRACES
    if operator not in operators:
        raise ResearchLoopError(f"operator must be one of {sorted(operators)}")
    if trace not in traces:
        raise ResearchLoopError(f"trace must be one of {sorted(traces)}")
    if trace == "confirm" and operator != "confirm":
        raise ResearchLoopError("confirm trace requires the confirm operator")
    if operator == "confirm" and trace != "confirm":
        raise ResearchLoopError("confirm operator requires the confirm trace")
    if operator == "diagnose" and trace != "diagnose":
        raise ResearchLoopError("diagnose operator requires the diagnose trace")
    if trace == "diagnose" and operator != "diagnose":
        raise ResearchLoopError("diagnose trace requires the diagnose operator")
    if not isinstance(primary_parent_id, str) or not primary_parent_id:
        raise ResearchLoopError("primary_parent_id must be non-empty")
    if not isinstance(source_parent_ids, list) or not source_parent_ids or not all(
        isinstance(item, str) and item for item in source_parent_ids
    ):
        raise ResearchLoopError("source_parent_ids must be a non-empty list")
    if primary_parent_id not in source_parent_ids:
        raise ResearchLoopError("primary_parent_id must be included in source_parent_ids")
    if operator == "recombine" and len(set(source_parent_ids)) != 2:
        raise ResearchLoopError("recombine requires exactly two distinct source_parent_ids")
    if operator != "recombine" and len(set(source_parent_ids)) != 1:
        raise ResearchLoopError("only recombine may declare multiple source parents")
    if not isinstance(evidence, list) or not evidence or not all(isinstance(item, dict) for item in evidence):
        raise ResearchLoopError("evidence must be a non-empty list of mappings")
    if not isinstance(estimated_cost, int) or not 1 <= estimated_cost <= 3:
        raise ResearchLoopError("estimated_cost must be an integer from 1 to 3")
    scores = spec.get("scores")
    if not isinstance(scores, dict):
        raise ResearchLoopError("scores must be a mapping")
    normalized_scores = {field: _normalize_score(scores.get(field), field) for field in SCORE_FIELDS}
    priority = sum(SCORE_WEIGHTS[field] * normalized_scores[field]["value"] for field in SCORE_FIELDS)
    candidate = {
        "candidate_id": candidate_id,
        "hypothesis_id": hypothesis_id,
        "statement": statement.strip(),
        "family": family,
        "operator": operator,
        "trace": trace,
        "primary_parent_id": primary_parent_id,
        "source_parent_ids": list(dict.fromkeys(source_parent_ids)),
        "evidence": evidence,
        "scores": normalized_scores,
        "estimated_cost": estimated_cost,
        "status": "pending",
        "created_at": now_iso(),
    }
    if version == 1:
        candidate["priority"] = round(priority, 12)
    return candidate


def add_candidate(repo: Path, *, spec_path: Path, campaign: Optional[str] = None) -> Dict[str, Any]:
    profile = load_profile(repo, campaign)
    store = _load_store(repo, campaign)
    candidate = _normalize_candidate(read_yaml(spec_path.resolve()), profile["schema_version"])
    if any(item.get("candidate_id") == candidate["candidate_id"] for item in store["candidates"]):
        raise ResearchLoopError(f"candidate already exists: {candidate['candidate_id']}")
    rows = read_ledger(repo, campaign)
    parents = _parent_rows(rows)
    missing = [item for item in candidate["source_parent_ids"] if item not in parents]
    if missing:
        raise ResearchLoopError(f"candidate source parents are not recorded experiments: {', '.join(missing)}")
    if profile["schema_version"] == 2:
        from .hypotheses import get_hypothesis

        get_hypothesis(repo, candidate["hypothesis_id"], campaign)
    store["candidates"].append(candidate)
    write_json(_store_path(repo, campaign), store)
    write_json(campaign_dir(repo, campaign) / "candidates" / f"{candidate['candidate_id']}.json", candidate)
    return candidate


def mark_candidate_prepared(
    repo: Path,
    candidate_id: str,
    experiment_id: str,
    campaign: Optional[str] = None,
) -> Dict[str, Any]:
    store = _load_store(repo, campaign)
    selected: Optional[Dict[str, Any]] = None
    for candidate in store["candidates"]:
        if candidate.get("candidate_id") == candidate_id:
            if candidate.get("status") != "pending":
                raise ResearchLoopError(f"candidate is not pending: {candidate_id}")
            candidate["status"] = "prepared"
            candidate["experiment_id"] = experiment_id
            candidate["prepared_at"] = now_iso()
            selected = candidate
            break
    if selected is None:
        raise ResearchLoopError(f"unknown candidate: {candidate_id}")
    write_json(_store_path(repo, campaign), store)
    write_json(campaign_dir(repo, campaign) / "candidates" / f"{candidate_id}.json", selected)
    return selected


def _as_bool(value: str) -> bool:
    return value.lower() == "true"


def _valid_rows(rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    return [row for row in rows if row.get("metric_value") and row.get("status") not in {"invalid", "crash"}]


def champion_row(rows: List[Dict[str, str]], direction: str) -> Optional[Dict[str, str]]:
    valid = _valid_rows(rows)
    if not valid:
        return None
    best_value = (max if direction == "maximize" else min)(float(row["metric_value"]) for row in valid)
    tied = [row for row in valid if float(row["metric_value"]) == best_value]
    return max(
        tied,
        key=lambda row: (row.get("confirmed", "").lower() == "true", int(row.get("index", "0") or 0)),
    )


def _eligibility(
    candidate: Dict[str, Any],
    rows: List[Dict[str, str]],
    candidates: List[Dict[str, Any]],
    direction: str,
    assessments: Optional[Dict[str, str]] = None,
) -> Tuple[bool, List[str]]:
    reasons: List[str] = []
    parents = _parent_rows(rows)
    parent = parents.get(candidate["primary_parent_id"])
    if parent is None:
        reasons.append("primary parent is not recorded")
        return False, reasons
    if candidate.get("status") != "pending":
        reasons.append(f"candidate status is {candidate.get('status')}")
    if assessments and assessments.get(candidate["hypothesis_id"]) == "falsified":
        reasons.append("candidate hypothesis is falsified")
    operator = candidate["operator"]
    if operator == "debug" and parent.get("status") not in {"invalid", "crash"}:
        reasons.append("debug requires an invalid or crashed parent")
    if operator != "debug" and parent.get("status") in {"invalid", "crash"}:
        reasons.append("non-debug operator requires a valid parent")
    champion = champion_row(rows, direction)
    if operator == "confirm" and (champion is None or parent["experiment_id"] != champion["experiment_id"]):
        reasons.append("confirm requires the current champion as parent")
    if operator == "recombine":
        for source_id in candidate["source_parent_ids"]:
            if parents[source_id].get("status") in {"invalid", "crash"}:
                reasons.append(f"recombine source is not valid: {source_id}")
    duplicate_prepared = any(
        other.get("candidate_id") != candidate["candidate_id"]
        and other.get("status") == "prepared"
        and other.get("family") == candidate["family"]
        and other.get("primary_parent_id") == candidate["primary_parent_id"]
        for other in candidates
    )
    if duplicate_prepared:
        reasons.append("same family already has a prepared sibling for this parent")
    return not reasons, reasons


def rank_candidates(repo: Path, campaign: Optional[str] = None) -> Dict[str, Any]:
    profile = load_profile(repo, campaign)
    candidates = list_candidates(repo, campaign)
    rows = read_ledger(repo, campaign)
    direction = profile["evaluation"]["primary_metric"]["direction"]
    assessments: Dict[str, str] = {}
    selector = "balanced"
    if profile["schema_version"] == 2:
        from .hypotheses import list_hypotheses
        from .strategy import read_strategy_state, score_candidate, selector_definition

        assessments = {
            item["hypothesis_id"]: item["assessment"]
            for item in list_hypotheses(repo, campaign)["hypotheses"]
        }
        selector = read_strategy_state(repo, campaign)["active_selector"]
        selector_policy = selector_definition(selector)
    else:
        selector_policy = {"preferred_operator": None, "explore_quota": 3}
    experiments = [row for row in rows if row.get("kind") != "baseline"]
    remaining = max(0, profile["policy"]["max_experiments"] - len(experiments))
    ranked: List[Dict[str, Any]] = []
    for candidate in candidates:
        eligible, reasons = _eligibility(candidate, rows, candidates, direction, assessments)
        scored = dict(candidate)
        if profile["schema_version"] == 2:
            scored.update(score_candidate(candidate, selector))
        ranked.append({**scored, "eligible": eligible, "eligibility_reasons": reasons})
    eligible = [item for item in ranked if item["eligible"]]
    eligible.sort(key=lambda item: (-item["priority"], item["estimated_cost"], item["created_at"], item["candidate_id"]))

    recommendation: Optional[Dict[str, Any]] = None
    rule = "highest-priority"
    champion = champion_row(rows, direction)
    confirm_candidates = [item for item in eligible if item["trace"] == "confirm"]
    champion_needs_confirmation = bool(
        champion and (_as_bool(champion.get("target_reached", "false")) or remaining <= 1) and not _as_bool(champion.get("confirmed", "false"))
    )
    if remaining <= 0:
        rule = "experiment-budget-exhausted"
    elif champion_needs_confirmation and confirm_candidates:
        recommendation = confirm_candidates[0]
        rule = "confirmation-priority"
    elif selector_policy["preferred_operator"]:
        preferred = [
            item for item in eligible if item["operator"] == selector_policy["preferred_operator"]
        ]
        recommendation = (preferred or eligible or [None])[0]
        rule = f"{selector}-priority" if preferred else f"{selector}-fallback"
    else:
        since_explore = 0
        for row in reversed(experiments):
            if row.get("trace") == "explore":
                break
            if row.get("trace") != "confirm":
                since_explore += 1
        explore = [item for item in eligible if item["trace"] == "explore"]
        quota = selector_policy["explore_quota"]
        if quota is not None and since_explore >= quota and explore:
            recommendation = explore[0]
            rule = "explore-quota"
        elif eligible:
            recommendation = eligible[0]
    return {
        "schema_version": profile["schema_version"],
        "selector": selector,
        "remaining_experiments": remaining,
        "rule": rule,
        "recommended_candidate_id": recommendation["candidate_id"] if recommendation else None,
        "ranked": eligible,
        "ineligible": [item for item in ranked if not item["eligible"]],
    }


def scoped_evidence(
    repo: Path,
    *,
    candidate_id: Optional[str] = None,
    operator: Optional[str] = None,
    parent_id: Optional[str] = None,
    source_parent_ids: Optional[List[str]] = None,
    campaign: Optional[str] = None,
) -> Dict[str, Any]:
    profile = load_profile(repo, campaign)
    rows = read_ledger(repo, campaign)
    parents = _parent_rows(rows)
    if candidate_id:
        candidate = get_candidate(repo, candidate_id, campaign)
        operator = candidate["operator"]
        parent_id = candidate["primary_parent_id"]
        source_parent_ids = candidate["source_parent_ids"]
    elif operator not in (V2_OPERATORS if profile["schema_version"] == 2 else OPERATORS) or not parent_id:
        raise ResearchLoopError("evidence requires --candidate-id or a valid --operator and --parent-id")
    source_parent_ids = source_parent_ids or [parent_id]
    if parent_id not in parents:
        raise ResearchLoopError(f"unknown evidence parent: {parent_id}")
    direction = profile["evaluation"]["primary_metric"]["direction"]
    champion = champion_row(rows, direction)

    selected: List[Dict[str, str]] = []
    if operator == "debug":
        current = parents[parent_id]
        seen = set()
        while current and current["experiment_id"] not in seen:
            selected.append(current)
            seen.add(current["experiment_id"])
            current = parents.get(current.get("primary_parent_id", ""))
    elif operator == "recombine":
        selected = [parents[item] for item in source_parent_ids if item in parents]
    else:
        selected.append(parents[parent_id])
        if champion and champion["experiment_id"] != parent_id:
            selected.append(champion)
        selected.extend(
            row
            for row in rows
            if row.get("primary_parent_id") == parent_id and row["experiment_id"] not in {item["experiment_id"] for item in selected}
        )
    fields = (
        "experiment_id",
        "hypothesis_id",
        "primary_parent_id",
        "operator",
        "trace",
        "family",
        "commit",
        "tree_hash",
        "metric_name",
        "metric_value",
        "delta_vs_parent",
        "delta_vs_champion",
        "status",
        "description",
        "log_path",
    )
    compact = [{field: row.get(field, "") for field in fields} for row in selected]
    return {
        "operator": operator,
        "parent_id": parent_id,
        "source_parent_ids": source_parent_ids,
        "remaining_experiments": max(0, profile["policy"]["max_experiments"] - len([r for r in rows if r.get("kind") != "baseline"])),
        "evidence": compact,
    }
