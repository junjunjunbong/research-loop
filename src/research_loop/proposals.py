from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .errors import ResearchLoopError
from .git import validate_slug
from .state import load_profile, read_ledger
from .util import canonical_hash, read_yaml

from .candidates import _normalize_candidate, champion_row, list_candidates
from .hypotheses import list_hypotheses
from .strategy import read_strategy_state, selector_definition


SLOTS = {"diagnose", "exploit", "explore", "recombine", "constraint"}
SLOT_TRACES = {"diagnose": "diagnose", "exploit": "exploit", "explore": "explore"}
IDEA_SOURCE_TYPES = {"paper", "pull_request", "issue", "user_note", "repository_artifact"}


def _require_v2(repo: Path, campaign: Optional[str]) -> Dict[str, Any]:
    profile = load_profile(repo, campaign)
    if profile["schema_version"] != 2:
        raise ResearchLoopError("proposal features require a schema_version 2 campaign")
    return profile


def _require_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ResearchLoopError(f"{field} must be a non-empty string")
    return value.strip()


def _normalize_idea_source(value: Any, field: str) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise ResearchLoopError(f"{field} must be a mapping")
    source_type = value.get("source_type")
    if source_type not in IDEA_SOURCE_TYPES:
        raise ResearchLoopError(f"{field}.source_type must be one of {sorted(IDEA_SOURCE_TYPES)}")
    revision = str(value.get("revision", "") or "").strip()
    content_sha256 = str(value.get("content_sha256", "") or "").strip()
    if not revision and not content_sha256:
        raise ResearchLoopError(f"{field} requires an immutable revision or content_sha256")
    usage = value.get("usage", {})
    if not isinstance(usage, dict):
        raise ResearchLoopError(f"{field}.usage must be a mapping")
    if usage.get("mode", "idea_only") != "idea_only":
        raise ResearchLoopError(f"{field}.usage.mode supports only idea_only")
    if bool(usage.get("code_reuse_allowed", False)):
        raise ResearchLoopError(f"{field}.usage.code_reuse_allowed must remain false")
    license_value = value.get("license", "unknown")
    if not isinstance(license_value, str) or not license_value.strip():
        raise ResearchLoopError(f"{field}.license must be a non-empty string")
    return {
        "source_type": source_type,
        "locator": _require_text(value.get("locator"), f"{field}.locator"),
        "revision": revision,
        "content_sha256": content_sha256,
        "claim": _require_text(value.get("claim"), f"{field}.claim"),
        "applicability": _require_text(value.get("applicability"), f"{field}.applicability"),
        "usage": {"mode": "idea_only", "code_reuse_allowed": False},
        "license": license_value.strip(),
    }


def _normalize_intervention(value: Any, field: str) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise ResearchLoopError(f"{field} must be a mapping")
    held_constant = value.get("held_constant", [])
    if not isinstance(held_constant, list) or not all(
        isinstance(item, str) and item.strip() for item in held_constant
    ):
        raise ResearchLoopError(f"{field}.held_constant must be a list of non-empty strings")
    return {
        "changed_factor": _require_text(value.get("changed_factor"), f"{field}.changed_factor"),
        "held_constant": [item.strip() for item in held_constant],
        "expected_mechanism": _require_text(value.get("expected_mechanism"), f"{field}.expected_mechanism"),
        "observable_signature": _require_text(
            value.get("observable_signature"), f"{field}.observable_signature"
        ),
    }


def _normalize_proposed_hypothesis(
    value: Any,
    recorded: set,
    known_ids: set,
    field: str,
) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise ResearchLoopError(f"{field} must be a mapping")
    hypothesis_id = validate_slug(str(value.get("hypothesis_id", "")), f"{field}.hypothesis_id")
    if hypothesis_id in known_ids:
        raise ResearchLoopError(f"hypothesis already exists: {hypothesis_id}")
    origin = value.get("origin_evidence")
    if not isinstance(origin, list) or not origin or not all(isinstance(item, dict) for item in origin):
        raise ResearchLoopError(f"{field}.origin_evidence must be a non-empty list of mappings")
    normalized_origin: List[Dict[str, str]] = []
    for index, item in enumerate(origin):
        experiment_id = _require_text(
            item.get("experiment_id"), f"{field}.origin_evidence[{index}].experiment_id"
        )
        if experiment_id not in recorded:
            raise ResearchLoopError(f"origin evidence is not a recorded experiment: {experiment_id}")
        normalized_origin.append(
            {
                "experiment_id": experiment_id,
                "reason": _require_text(item.get("reason"), f"{field}.origin_evidence[{index}].reason"),
            }
        )
    return {
        "hypothesis_id": hypothesis_id,
        "statement": _require_text(value.get("statement"), f"{field}.statement"),
        "prediction": _require_text(value.get("prediction"), f"{field}.prediction"),
        "falsification_criteria": _require_text(
            value.get("falsification_criteria"), f"{field}.falsification_criteria"
        ),
        "family": validate_slug(str(value.get("family", "")), f"{field}.family"),
        "origin_evidence": normalized_origin,
    }


def _normalize_item(
    item: Any,
    *,
    recorded: set,
    parent_ids: set,
    existing_hypothesis_ids: set,
    proposed_hypothesis_ids: set,
    existing_candidate_ids: set,
    proposed_candidate_ids: set,
    field: str,
) -> Dict[str, Any]:
    if not isinstance(item, dict):
        raise ResearchLoopError(f"{field} must be a mapping")
    slot = item.get("slot")
    if slot not in SLOTS:
        raise ResearchLoopError(f"{field}.slot must be one of {sorted(SLOTS)}")
    normalized: Dict[str, Any] = {"slot": slot}
    if "hypothesis" in item:
        normalized["hypothesis"] = _normalize_proposed_hypothesis(
            item["hypothesis"],
            recorded,
            existing_hypothesis_ids | proposed_hypothesis_ids,
            f"{field}.hypothesis",
        )
    candidate_spec = item.get("candidate")
    if not isinstance(candidate_spec, dict):
        raise ResearchLoopError(f"{field}.candidate must be a mapping")
    candidate = _normalize_candidate(candidate_spec, 2)
    candidate.pop("status", None)
    candidate.pop("created_at", None)
    if candidate["candidate_id"] in existing_candidate_ids | proposed_candidate_ids:
        raise ResearchLoopError(f"candidate already exists: {candidate['candidate_id']}")
    missing = [parent for parent in candidate["source_parent_ids"] if parent not in parent_ids]
    if missing:
        raise ResearchLoopError(
            f"candidate source parents are not recorded experiments: {', '.join(missing)}"
        )
    hypothesis_pool = existing_hypothesis_ids | proposed_hypothesis_ids
    if "hypothesis" in normalized:
        hypothesis_pool = hypothesis_pool | {normalized["hypothesis"]["hypothesis_id"]}
    if candidate["hypothesis_id"] not in hypothesis_pool:
        raise ResearchLoopError(f"unknown candidate hypothesis: {candidate['hypothesis_id']}")
    expected_trace = SLOT_TRACES.get(slot)
    if expected_trace and candidate["trace"] != expected_trace:
        raise ResearchLoopError(f"slot {slot} requires trace {expected_trace}")
    if slot == "recombine" and candidate["operator"] != "recombine":
        raise ResearchLoopError("slot recombine requires the recombine operator")
    if "interaction_rationale" in candidate_spec:
        candidate["interaction_rationale"] = _require_text(
            candidate_spec.get("interaction_rationale"), f"{field}.candidate.interaction_rationale"
        )
    normalized["candidate"] = candidate
    if "intervention" in item:
        normalized["intervention"] = _normalize_intervention(item["intervention"], f"{field}.intervention")
    sources = item.get("idea_sources", [])
    if not isinstance(sources, list):
        raise ResearchLoopError(f"{field}.idea_sources must be a list")
    normalized["idea_sources"] = [
        _normalize_idea_source(source, f"{field}.idea_sources[{index}]")
        for index, source in enumerate(sources)
    ]
    return normalized


def proposal_context(repo: Path, campaign: Optional[str] = None) -> Dict[str, Any]:
    profile = _require_v2(repo, campaign)
    rows = read_ledger(repo, campaign)
    direction = profile["evaluation"]["primary_metric"]["direction"]
    experiments = [row for row in rows if row.get("kind") != "baseline"]
    champion = champion_row(rows, direction)
    listed = list_hypotheses(repo, campaign)
    pending = [item for item in list_candidates(repo, campaign) if item.get("status") == "pending"]
    hypotheses_by_assessment: Dict[str, List[Dict[str, str]]] = {}
    for hypothesis in listed["hypotheses"]:
        hypotheses_by_assessment.setdefault(hypothesis["assessment"], []).append(
            {
                "hypothesis_id": hypothesis["hypothesis_id"],
                "family": hypothesis["family"],
                "statement": hypothesis["statement"],
            }
        )
    families: Dict[str, Dict[str, Any]] = {}
    for hypothesis in listed["hypotheses"]:
        entry = families.setdefault(hypothesis["family"], {"hypotheses": [], "recorded_experiments": 0})
        entry["hypotheses"].append(hypothesis["hypothesis_id"])
    for row in rows:
        family = row.get("family", "")
        if not family:
            continue
        entry = families.setdefault(family, {"hypotheses": [], "recorded_experiments": 0})
        entry["recorded_experiments"] += 1
    diagnose_covered = {
        item["hypothesis_id"] for item in pending if item.get("trace") == "diagnose"
    }
    uncovered = [
        hypothesis["hypothesis_id"]
        for hypothesis in listed["hypotheses"]
        if hypothesis["assessment"] in {"open", "contested"}
        and hypothesis["hypothesis_id"] not in diagnose_covered
    ]
    recent_fields = ("experiment_id", "hypothesis_id", "family", "trace", "status", "metric_value", "delta_vs_parent")
    return {
        "schema_version": 2,
        "primary_metric": profile["evaluation"]["primary_metric"]["name"],
        "direction": direction,
        "remaining_experiments": max(0, profile["policy"]["max_experiments"] - len(experiments)),
        "champion": (
            {
                "experiment_id": champion["experiment_id"],
                "hypothesis_id": champion.get("hypothesis_id", ""),
                "family": champion.get("family", ""),
                "metric_value": champion.get("metric_value", ""),
                "confirmed": champion.get("confirmed", ""),
            }
            if champion
            else None
        ),
        "assessment_counts": listed["assessment_counts"],
        "hypotheses_by_assessment": hypotheses_by_assessment,
        "families": families,
        "coverage": {
            "families_without_recorded_experiments": sorted(
                family for family, entry in families.items() if entry["recorded_experiments"] == 0
            ),
            "open_or_contested_without_pending_diagnose": sorted(uncovered),
        },
        "recent_experiments": [
            {key: row.get(key, "") for key in recent_fields} for row in experiments[-5:]
        ],
        "constraints": {
            "allowed_paths": profile["context"].get("allowed_paths", []),
            "protected_paths": profile["context"].get("protected_paths", []),
            "resource_class": profile["environment"]["resource_class"],
            "timeout_seconds": profile["environment"]["timeout_seconds"],
            "confirmation_runs": profile["evaluation"]["confirmation_runs"],
            "acceptance": profile["evaluation"]["acceptance"],
            "target": profile["evaluation"]["target"],
        },
    }


def validate_proposal(repo: Path, *, spec_path: Path, campaign: Optional[str] = None) -> Dict[str, Any]:
    _require_v2(repo, campaign)
    spec = read_yaml(spec_path.resolve())
    if spec.get("schema_version") != 2:
        raise ResearchLoopError("proposal schema_version must be 2")
    proposal_id = validate_slug(str(spec.get("proposal_id", "")), "proposal_id")
    generated_by = spec.get("generated_by")
    if generated_by is not None and (
        not isinstance(generated_by, dict)
        or not all(isinstance(key, str) and isinstance(value, str) for key, value in generated_by.items())
    ):
        raise ResearchLoopError("generated_by must be a mapping of strings")
    items = spec.get("items")
    if not isinstance(items, list) or not items:
        raise ResearchLoopError("items must be a non-empty list")
    rows = read_ledger(repo, campaign)
    recorded = {row["experiment_id"] for row in rows}
    existing_hypothesis_ids = {
        item["hypothesis_id"] for item in list_hypotheses(repo, campaign)["hypotheses"]
    }
    existing_candidate_ids = {item["candidate_id"] for item in list_candidates(repo, campaign)}
    proposed_hypothesis_ids: set = set()
    proposed_candidate_ids: set = set()
    accepted: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    for index, item in enumerate(items):
        field = f"items[{index}]"
        try:
            normalized = _normalize_item(
                item,
                recorded=recorded,
                parent_ids=recorded,
                existing_hypothesis_ids=existing_hypothesis_ids,
                proposed_hypothesis_ids=proposed_hypothesis_ids,
                existing_candidate_ids=existing_candidate_ids,
                proposed_candidate_ids=proposed_candidate_ids,
                field=field,
            )
        except ResearchLoopError as exc:
            slot = item.get("slot") if isinstance(item, dict) else None
            candidate_id = (
                item.get("candidate", {}).get("candidate_id")
                if isinstance(item, dict) and isinstance(item.get("candidate"), dict)
                else None
            )
            rejected.append(
                {"index": index, "slot": slot, "candidate_id": candidate_id, "reasons": [str(exc)]}
            )
            continue
        if "hypothesis" in normalized:
            proposed_hypothesis_ids.add(normalized["hypothesis"]["hypothesis_id"])
        proposed_candidate_ids.add(normalized["candidate"]["candidate_id"])
        accepted.append(normalized)
    source_identities = sorted(
        (
            {
                "source_type": source["source_type"],
                "locator": source["locator"],
                "revision": source["revision"],
                "content_sha256": source["content_sha256"],
            }
            for item in accepted
            for source in item["idea_sources"]
        ),
        key=lambda entry: canonical_hash(entry),
    )
    return {
        "schema_version": 2,
        "proposal_id": proposal_id,
        "generated_by": generated_by,
        "context_hash": canonical_hash(proposal_context(repo, campaign)),
        "source_set_hash": canonical_hash(source_identities),
        "items": accepted,
        "rejected": rejected,
        "counts": {
            "items": len(items),
            "accepted": len(accepted),
            "rejected": len(rejected),
            "new_hypotheses": len(proposed_hypothesis_ids),
            "idea_sources": len(source_identities),
        },
    }


def _pool_candidates(
    repo: Path,
    spec_path: Optional[Path],
    campaign: Optional[str],
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    pending = [
        dict(item, origin="pending")
        for item in list_candidates(repo, campaign)
        if item.get("status") == "pending"
    ]
    proposed: List[Dict[str, Any]] = []
    if spec_path is not None:
        validated = validate_proposal(repo, spec_path=spec_path, campaign=campaign)
        proposed = [dict(item["candidate"], origin="proposed") for item in validated["items"]]
    return pending + proposed, {"pending": len(pending), "proposed": len(proposed)}


def _since_explore(rows: List[Dict[str, str]]) -> int:
    count = 0
    for row in reversed([row for row in rows if row.get("kind") != "baseline"]):
        if row.get("trace") == "explore":
            break
        if row.get("trace") != "confirm":
            count += 1
    return count


def portfolio_lint(
    repo: Path,
    *,
    spec_path: Optional[Path] = None,
    campaign: Optional[str] = None,
) -> Dict[str, Any]:
    _require_v2(repo, campaign)
    selector = read_strategy_state(repo, campaign)["active_selector"]
    rows = read_ledger(repo, campaign)
    pool, pool_counts = _pool_candidates(repo, spec_path, campaign)
    assessments = {
        item["hypothesis_id"]: item["assessment"]
        for item in list_hypotheses(repo, campaign)["hypotheses"]
    }
    families = sorted({item["family"] for item in pool})
    traces = sorted({item["trace"] for item in pool})
    warnings: List[Dict[str, Any]] = []

    if len(pool) >= 2 and len(families) == 1:
        warnings.append(
            {
                "rule": "L1-single-family",
                "message": f"all {len(pool)} pool candidates belong to one family: {families[0]}",
                "refs": sorted(item["candidate_id"] for item in pool),
            }
        )

    quota = selector_definition(selector)["explore_quota"]
    if quota is not None:
        since_explore = _since_explore(rows)
        has_explore = any(item["trace"] == "explore" for item in pool)
        if since_explore >= quota - 1 and not has_explore:
            warnings.append(
                {
                    "rule": "L2-explore-missing",
                    "message": (
                        f"selector {selector} reaches its explore quota after {quota} exploit steps "
                        f"({since_explore} recorded since the last explore) but the pool has no explore candidate"
                    ),
                    "refs": [],
                }
            )

    if selector == "diagnostic":
        diagnose_covered = {item["hypothesis_id"] for item in pool if item["trace"] == "diagnose"}
        uncovered = sorted(
            hypothesis_id
            for hypothesis_id, assessment in assessments.items()
            if assessment in {"open", "contested"} and hypothesis_id not in diagnose_covered
        )
        if uncovered:
            warnings.append(
                {
                    "rule": "L3-diagnose-missing",
                    "message": "open or contested hypotheses have no pool diagnose candidate",
                    "refs": uncovered,
                }
            )

    row_by_id = {row["experiment_id"]: row for row in rows}
    for item in pool:
        if item["operator"] != "recombine":
            continue
        if str(item.get("interaction_rationale", "")).strip():
            continue
        falsified_sources = sorted(
            source_id
            for source_id in item["source_parent_ids"]
            if assessments.get(row_by_id.get(source_id, {}).get("hypothesis_id", "")) == "falsified"
        )
        if falsified_sources:
            warnings.append(
                {
                    "rule": "L4-falsified-source-recombine",
                    "message": (
                        f"recombine candidate {item['candidate_id']} builds on falsified-hypothesis "
                        "sources without an interaction_rationale"
                    ),
                    "refs": falsified_sources,
                }
            )

    duplicates = Counter((item["family"], item["primary_parent_id"], item["operator"]) for item in pool)
    for (family, parent, operator), count in sorted(duplicates.items()):
        if count > 1:
            warnings.append(
                {
                    "rule": "L5-duplicate-shape",
                    "message": (
                        f"{count} pool candidates share family {family}, parent {parent}, operator {operator}"
                    ),
                    "refs": sorted(
                        item["candidate_id"]
                        for item in pool
                        if (item["family"], item["primary_parent_id"], item["operator"])
                        == (family, parent, operator)
                    ),
                }
            )

    return {
        "schema_version": 2,
        "selector": selector,
        "pool": pool_counts,
        "portfolio_health": {
            "family_count": len(families),
            "trace_count": len(traces),
            "families": families,
            "traces": traces,
            "warnings": warnings,
        },
    }
