from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
CANONICAL_IDENTITY = "research-loop@research-loop"


def test_plugin_manifests_and_marketplace() -> None:
    codex_manifest = json.loads((ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
    claude_manifest = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    claude_marketplace = json.loads(
        (ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8")
    )
    codex_marketplace = json.loads(
        (ROOT / ".agents" / "plugins" / "marketplace.json").read_text(encoding="utf-8")
    )

    assert codex_manifest["name"] == claude_manifest["name"] == "research-loop"
    assert codex_manifest["version"] == claude_manifest["version"]
    assert codex_manifest["version"] == "0.4.1"
    assert codex_manifest["description"] == claude_manifest["description"]
    assert codex_manifest["skills"] == "./skills/"

    assert codex_marketplace["name"] == claude_marketplace["name"] == "research-loop"
    assert codex_marketplace["interface"]["displayName"] == "Research Loop"
    assert len(codex_marketplace["plugins"]) == len(claude_marketplace["plugins"]) == 1

    codex_plugin = codex_marketplace["plugins"][0]
    claude_plugin = claude_marketplace["plugins"][0]
    assert codex_plugin["name"] == claude_plugin["name"] == claude_manifest["name"]
    assert codex_plugin["source"] == claude_plugin["source"] == "./"
    assert codex_plugin["policy"] == {
        "installation": "AVAILABLE",
        "authentication": "ON_INSTALL",
    }
    assert codex_plugin["category"] == "Education & Research"
    assert claude_plugin["description"] == claude_manifest["description"]
    assert (ROOT / "skills" / "research-loop" / "SKILL.md").is_file()


def test_claude_project_plugin_settings() -> None:
    settings = json.loads((ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))
    source = settings["extraKnownMarketplaces"]["research-loop"]["source"]
    assert source == {"source": "directory", "path": "."}
    assert settings["enabledPlugins"] == {CANONICAL_IDENTITY: True}


def test_repository_packaging_has_no_legacy_marketplace_identity() -> None:
    packaging_files = [
        ROOT / ".agents" / "plugins" / "marketplace.json",
        ROOT / ".codex-plugin" / "plugin.json",
        ROOT / ".claude-plugin" / "marketplace.json",
        ROOT / ".claude-plugin" / "plugin.json",
        ROOT / ".claude" / "settings.json",
    ]
    for path in packaging_files:
        assert "local-research-loop" not in path.read_text(encoding="utf-8"), path


def test_skill_frontmatter() -> None:
    skill_files = list(ROOT.glob("skills/**/SKILL.md")) + list(ROOT.glob("vendor/**/SKILL.md"))
    assert skill_files
    for path in skill_files:
        text = path.read_text(encoding="utf-8")
        assert text.startswith("---\n"), path
        _, frontmatter, _ = text.split("---", 2)
        metadata = yaml.safe_load(frontmatter)
        assert isinstance(metadata.get("name"), str)
        assert isinstance(metadata.get("description"), str)


def test_research_loop_requires_explicit_invocation() -> None:
    skill = ROOT / "skills" / "research-loop" / "SKILL.md"
    _, frontmatter, body = skill.read_text(encoding="utf-8").split("---", 2)
    metadata = yaml.safe_load(frontmatter)

    assert "disable-model-invocation" not in metadata
    assert "only when the user explicitly names" in metadata["description"]
    assert "Do not trigger from a task's similarity" in metadata["description"]
    assert "explicitly names" in body


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
