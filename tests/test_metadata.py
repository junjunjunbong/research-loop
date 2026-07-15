from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_plugin_manifest_and_skill_frontmatter() -> None:
    manifest = json.loads((ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert manifest["name"] == "research-loop"
    assert manifest["skills"] == "./skills/"

    skill_files = list(ROOT.glob("skills/**/SKILL.md")) + list(ROOT.glob("vendor/**/SKILL.md"))
    assert skill_files
    for path in skill_files:
        text = path.read_text(encoding="utf-8")
        assert text.startswith("---\n"), path
        _, frontmatter, _ = text.split("---", 2)
        metadata = yaml.safe_load(frontmatter)
        assert isinstance(metadata.get("name"), str)
        assert isinstance(metadata.get("description"), str)


def test_skill_relative_references_exist() -> None:
    skill = ROOT / "skills" / "research-loop" / "SKILL.md"
    text = skill.read_text(encoding="utf-8")
    references = set(re.findall(r"`(references/[^`]+\.md)`", text))
    assert references
    for relative in references:
        assert (skill.parent / relative).is_file(), relative


def test_vendor_checksums_and_no_signatures() -> None:
    vendor = ROOT / "vendor" / "nvidia"
    entries = {}
    for line in (vendor / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        digest, relative = line.split(maxsplit=1)
        entries[relative] = digest
    assert len(entries) == 5
    for relative, expected in entries.items():
        actual = hashlib.sha256((vendor / relative).read_bytes()).hexdigest()
        assert actual == expected
    assert not list(vendor.rglob("skill.oms.sig"))

