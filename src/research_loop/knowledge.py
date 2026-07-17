from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from .errors import ResearchLoopError
from .git import validate_slug
from .hypotheses import normalize_idea_source
from .schema import IDEA_SOURCE_TYPES, _reject_secrets
from .state import campaign_dir, load_profile
from .util import canonical_hash, now_iso, read_json, read_yaml, write_json


PACK_DIRNAME = "knowledge"
RECORDS_DIRNAME = "records"
SUMS_FILENAME = "SHA256SUMS"
DEFAULT_MAX_SOURCES_PER_ROUND = 20
DEFAULT_MAX_RECORD_BYTES = 16384


def resolve_knowledge_access(policy: Dict[str, Any]) -> Dict[str, Any]:
    access = policy.get("knowledge_access")
    if access is None:
        return {"mode": "none"}
    resolved = dict(access)
    resolved.setdefault("mode", "none")
    resolved.setdefault("allow_network", False)
    resolved.setdefault("allowed_source_types", sorted(IDEA_SOURCE_TYPES))
    resolved.setdefault("max_sources_per_round", DEFAULT_MAX_SOURCES_PER_ROUND)
    resolved.setdefault("max_record_bytes", DEFAULT_MAX_RECORD_BYTES)
    resolved.setdefault("retrieval_cutoff", "")
    return resolved


def source_identity(source: Dict[str, Any]) -> Dict[str, str]:
    return {
        "source_type": source["source_type"],
        "locator": source["locator"],
        "revision": source["revision"],
        "content_sha256": source["content_sha256"],
    }


def _pack_dir(repo: Path, campaign: Optional[str]) -> Path:
    return campaign_dir(repo, campaign) / PACK_DIRNAME


def _require_enabled(repo: Path, campaign: Optional[str]) -> Dict[str, Any]:
    profile = load_profile(repo, campaign)
    if profile["schema_version"] != 2:
        raise ResearchLoopError("knowledge pack features require a schema_version 2 campaign")
    access = resolve_knowledge_access(profile["policy"])
    if access["mode"] == "none":
        raise ResearchLoopError("knowledge access is not enabled for this campaign")
    return access


def _read_sums(path: Path) -> Dict[str, str]:
    if not path.exists():
        return {}
    entries: Dict[str, str] = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        parts = line.split(maxsplit=1)
        if len(parts) != 2:
            raise ResearchLoopError(f"invalid checksum line: {path}:{number}")
        digest, relative = parts
        entries[relative.strip()] = digest
    return entries


def _write_sums(path: Path, entries: Dict[str, str]) -> None:
    lines = [f"{entries[relative]}  {relative}" for relative in sorted(entries)]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def _validate_record(
    record: Dict[str, Any],
    access: Dict[str, Any],
    field: str,
) -> Dict[str, Any]:
    source_id = validate_slug(str(record.get("source_id", "")), f"{field}.source_id")
    core = normalize_idea_source(record, field)
    if core["source_type"] not in access["allowed_source_types"]:
        raise ResearchLoopError(
            f"{field}.source_type {core['source_type']} is not allowed by knowledge_access"
        )
    prohibited = record.get("prohibited_interpretations", [])
    if not isinstance(prohibited, list) or not all(
        isinstance(item, str) and item.strip() for item in prohibited
    ):
        raise ResearchLoopError(f"{field}.prohibited_interpretations must be a list of non-empty strings")
    retrieved_at = record.get("retrieved_at", "")
    if not isinstance(retrieved_at, str):
        raise ResearchLoopError(f"{field}.retrieved_at must be a string")
    return {
        "schema_version": 2,
        "source_id": source_id,
        **core,
        "prohibited_interpretations": [item.strip() for item in prohibited],
        "retrieved_at": retrieved_at.strip(),
    }


def add_pack_record(repo: Path, *, spec_path: Path, campaign: Optional[str] = None) -> Dict[str, Any]:
    access = _require_enabled(repo, campaign)
    spec = read_yaml(spec_path.resolve())
    _reject_secrets(spec, "record")
    record = _validate_record(spec, access, "record")
    record["registered_at"] = now_iso()
    payload = json.dumps(record, ensure_ascii=False)
    if len(payload.encode("utf-8")) > access["max_record_bytes"]:
        raise ResearchLoopError(
            f"record exceeds knowledge_access.max_record_bytes ({access['max_record_bytes']})"
        )
    pack = _pack_dir(repo, campaign)
    relative = f"{RECORDS_DIRNAME}/{record['source_id']}.json"
    target = pack / RECORDS_DIRNAME / f"{record['source_id']}.json"
    if target.exists():
        raise ResearchLoopError(f"knowledge pack record already exists: {record['source_id']}")
    write_json(target, record)
    sums_path = pack / SUMS_FILENAME
    entries = _read_sums(sums_path)
    entries[relative] = hashlib.sha256(target.read_bytes()).hexdigest()
    _write_sums(sums_path, entries)
    return {"record": record, "pack": {"path": str(pack), "records": len(entries)}}


def verify_pack(repo: Path, campaign: Optional[str] = None) -> Dict[str, Any]:
    access = _require_enabled(repo, campaign)
    pack = _pack_dir(repo, campaign)
    records_dir = pack / RECORDS_DIRNAME
    sums_path = pack / SUMS_FILENAME
    entries = _read_sums(sums_path)
    on_disk = sorted(
        f"{RECORDS_DIRNAME}/{path.name}" for path in records_dir.glob("*.json")
    ) if records_dir.is_dir() else []
    unlisted = [relative for relative in on_disk if relative not in entries]
    if unlisted:
        raise ResearchLoopError(f"knowledge pack files are not listed in {SUMS_FILENAME}: {', '.join(unlisted)}")
    records: List[Dict[str, Any]] = []
    for relative in sorted(entries):
        target = pack / relative
        if not target.is_file():
            raise ResearchLoopError(f"knowledge pack record is missing: {relative}")
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        if digest != entries[relative]:
            raise ResearchLoopError(f"knowledge pack hash mismatch: {relative}")
        record = _validate_record(read_json(target), access, relative)
        expected_name = f"{RECORDS_DIRNAME}/{record['source_id']}.json"
        if relative != expected_name:
            raise ResearchLoopError(f"knowledge pack record name mismatch: {relative}")
        records.append(record)
    return {
        "mode": access["mode"],
        "allow_network": access["allow_network"],
        "records": len(records),
        "source_ids": [record["source_id"] for record in records],
        "verified": True,
    }


def verified_identity_hashes(repo: Path, campaign: Optional[str] = None) -> Dict[str, str]:
    access = _require_enabled(repo, campaign)
    pack = _pack_dir(repo, campaign)
    entries = _read_sums(pack / SUMS_FILENAME)
    verify_pack(repo, campaign)
    hashes: Dict[str, str] = {}
    for relative in entries:
        record = read_json(pack / relative)
        normalized = _validate_record(record, access, relative)
        hashes[canonical_hash(source_identity(normalized))] = normalized["source_id"]
    return hashes
