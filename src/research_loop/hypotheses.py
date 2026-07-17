from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from .errors import ResearchLoopError
from .git import validate_slug
from .state import campaign_dir, load_profile, read_ledger
from .util import (
    append_jsonl,
    confined_path,
    now_iso,
    read_json,
    read_jsonl,
    read_yaml,
    write_json,
)


RELATIONS = {"supports", "weakens", "falsifies", "inconclusive"}
ASSESSMENTS = {"open", "supported", "contested", "falsified"}
SOURCE_TYPES = {"primary_metric", "run_log", "artifact"}
IDEA_SOURCE_TYPES = {"paper", "pull_request", "issue", "user_note", "repository_artifact"}


def normalize_idea_source(value: Any, field: str) -> Dict[str, Any]:
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
        "locator": _nonempty(value.get("locator"), f"{field}.locator"),
        "revision": revision,
        "content_sha256": content_sha256,
        "claim": _nonempty(value.get("claim"), f"{field}.claim"),
        "applicability": _nonempty(value.get("applicability"), f"{field}.applicability"),
        "usage": {"mode": "idea_only", "code_reuse_allowed": False},
        "license": license_value.strip(),
    }


def _store_path(repo: Path, campaign: Optional[str]) -> Path:
    return campaign_dir(repo, campaign) / "hypotheses.json"


def _events_path(repo: Path, campaign: Optional[str]) -> Path:
    return campaign_dir(repo, campaign) / "hypothesis-events.jsonl"


def _require_v2(repo: Path, campaign: Optional[str]) -> None:
    if load_profile(repo, campaign)["schema_version"] != 2:
        raise ResearchLoopError("hypothesis evidence features require a schema_version 2 campaign")


def _load_store(repo: Path, campaign: Optional[str]) -> Dict[str, Any]:
    _require_v2(repo, campaign)
    path = _store_path(repo, campaign)
    store = read_json(path)
    if store.get("schema_version") != 2 or not isinstance(store.get("hypotheses"), list):
        raise ResearchLoopError(f"invalid hypothesis store: {path}")
    return store


def get_hypothesis(repo: Path, hypothesis_id: str, campaign: Optional[str] = None) -> Dict[str, Any]:
    for hypothesis in _load_store(repo, campaign)["hypotheses"]:
        if hypothesis.get("hypothesis_id") == hypothesis_id:
            return hypothesis
    raise ResearchLoopError(f"unknown hypothesis: {hypothesis_id}")


def list_hypotheses(repo: Path, campaign: Optional[str] = None) -> Dict[str, Any]:
    store = _load_store(repo, campaign)
    events = read_jsonl(_events_path(repo, campaign))
    hypotheses = []
    for stored in store["hypotheses"]:
        hypothesis = dict(stored)
        hypothesis_events = [
            event for event in events if event.get("hypothesis_id") == hypothesis["hypothesis_id"]
        ]
        relations = {
            relation: sum(event.get("relation") == relation for event in hypothesis_events)
            for relation in sorted(RELATIONS)
        }
        latest = hypothesis_events[-1] if hypothesis_events else None
        hypothesis["evidence_summary"] = {
            "total": len(hypothesis_events),
            "relations": relations,
            "latest_event_id": latest.get("event_id") if latest else None,
            "latest_experiment_id": latest.get("experiment_id") if latest else None,
        }
        hypotheses.append(hypothesis)
    return {
        "schema_version": 2,
        "hypotheses": hypotheses,
        "assessment_counts": {
            assessment: sum(item.get("assessment") == assessment for item in hypotheses)
            for assessment in sorted(ASSESSMENTS)
        },
    }


def _nonempty(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ResearchLoopError(f"{field} must be a non-empty string")
    return value.strip()


def add_hypothesis(repo: Path, *, spec_path: Path, campaign: Optional[str] = None) -> Dict[str, Any]:
    store = _load_store(repo, campaign)
    spec = read_yaml(spec_path.resolve())
    hypothesis_id = validate_slug(str(spec.get("hypothesis_id", "")), "hypothesis_id")
    if any(item.get("hypothesis_id") == hypothesis_id for item in store["hypotheses"]):
        raise ResearchLoopError(f"hypothesis already exists: {hypothesis_id}")
    origin = spec.get("origin_evidence")
    if not isinstance(origin, list) or not origin or not all(isinstance(item, dict) for item in origin):
        raise ResearchLoopError("origin_evidence must be a non-empty list of mappings")
    recorded = {row["experiment_id"] for row in read_ledger(repo, campaign)}
    normalized_origin: List[Dict[str, str]] = []
    for index, item in enumerate(origin):
        experiment_id = _nonempty(item.get("experiment_id"), f"origin_evidence[{index}].experiment_id")
        if experiment_id not in recorded:
            raise ResearchLoopError(f"origin evidence is not a recorded experiment: {experiment_id}")
        normalized_origin.append(
            {
                "experiment_id": experiment_id,
                "reason": _nonempty(item.get("reason"), f"origin_evidence[{index}].reason"),
            }
        )
    sources = spec.get("idea_sources", [])
    if not isinstance(sources, list):
        raise ResearchLoopError("idea_sources must be a list")
    normalized_sources = [
        normalize_idea_source(item, f"idea_sources[{index}]") for index, item in enumerate(sources)
    ]
    timestamp = now_iso()
    hypothesis = {
        "hypothesis_id": hypothesis_id,
        "statement": _nonempty(spec.get("statement"), "statement"),
        "prediction": _nonempty(spec.get("prediction"), "prediction"),
        "falsification_criteria": _nonempty(spec.get("falsification_criteria"), "falsification_criteria"),
        "family": validate_slug(str(spec.get("family", "")), "family"),
        "origin_evidence": normalized_origin,
        "idea_sources": normalized_sources,
        "assessment": "open",
        "evidence_count": 0,
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    store["hypotheses"].append(hypothesis)
    write_json(_store_path(repo, campaign), store)
    return hypothesis


def _recorded_row(repo: Path, experiment_id: str, campaign: Optional[str]) -> Dict[str, str]:
    for row in read_ledger(repo, campaign):
        if row.get("experiment_id") == experiment_id:
            return row
    raise ResearchLoopError(f"evidence experiment is not recorded: {experiment_id}")


def _verify_source(
    repo: Path,
    experiment_id: str,
    source: Any,
    campaign: Optional[str],
) -> Dict[str, str]:
    if not isinstance(source, dict):
        raise ResearchLoopError("source must be a mapping")
    kind = source.get("type")
    if kind not in SOURCE_TYPES:
        raise ResearchLoopError(f"source.type must be one of {sorted(SOURCE_TYPES)}")
    from .experiments import experiment_dir

    exp_dir = experiment_dir(repo, experiment_id, campaign)
    if kind == "primary_metric":
        path = exp_dir / "full" / "evaluation.json"
        if not path.is_file():
            raise ResearchLoopError(f"primary metric evidence is missing: {path}")
        return {"type": kind, "path": str(path.resolve())}
    if kind == "run_log":
        manifest = read_json(exp_dir / "full" / "manifest.json")
        path = Path(manifest["log_path"]).resolve()
        if not path.is_file():
            raise ResearchLoopError(f"run log evidence is missing: {path}")
        return {"type": kind, "path": str(path)}
    relative = _nonempty(source.get("path"), "source.path")
    metadata = read_json(exp_dir / "experiment.json")
    path = confined_path(Path(metadata["worktree"]), relative, "source.path")
    if not path.is_file():
        raise ResearchLoopError(f"artifact evidence is missing: {path}")
    return {"type": kind, "path": relative, "resolved_path": str(path)}


def add_hypothesis_evidence(
    repo: Path,
    *,
    spec_path: Path,
    campaign: Optional[str] = None,
) -> Dict[str, Any]:
    store = _load_store(repo, campaign)
    spec = read_yaml(spec_path.resolve())
    event_id = validate_slug(str(spec.get("event_id", "")), "event_id")
    if any(item.get("event_id") == event_id for item in read_jsonl(_events_path(repo, campaign))):
        raise ResearchLoopError(f"hypothesis evidence event already exists: {event_id}")
    hypothesis_id = validate_slug(str(spec.get("hypothesis_id", "")), "hypothesis_id")
    hypothesis = next(
        (item for item in store["hypotheses"] if item.get("hypothesis_id") == hypothesis_id),
        None,
    )
    if hypothesis is None:
        raise ResearchLoopError(f"unknown hypothesis: {hypothesis_id}")
    experiment_id = _nonempty(spec.get("experiment_id"), "experiment_id")
    _recorded_row(repo, experiment_id, campaign)
    relation = spec.get("relation")
    assessment = spec.get("assessment")
    if relation not in RELATIONS:
        raise ResearchLoopError(f"relation must be one of {sorted(RELATIONS)}")
    if assessment not in ASSESSMENTS:
        raise ResearchLoopError(f"assessment must be one of {sorted(ASSESSMENTS)}")
    verified_source = _verify_source(repo, experiment_id, spec.get("source"), campaign)
    event = {
        "schema_version": 2,
        "event_id": event_id,
        "hypothesis_id": hypothesis_id,
        "experiment_id": experiment_id,
        "relation": relation,
        "observation": _nonempty(spec.get("observation"), "observation"),
        "source": verified_source,
        "rationale": _nonempty(spec.get("rationale"), "rationale"),
        "previous_assessment": hypothesis["assessment"],
        "assessment": assessment,
        "created_at": now_iso(),
    }
    append_jsonl(_events_path(repo, campaign), event)
    hypothesis["assessment"] = assessment
    hypothesis["evidence_count"] = int(hypothesis.get("evidence_count", 0)) + 1
    hypothesis["updated_at"] = event["created_at"]
    write_json(_store_path(repo, campaign), store)
    return event
