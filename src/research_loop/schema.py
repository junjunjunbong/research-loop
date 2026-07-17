from __future__ import annotations

import re
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List

from .errors import ResearchLoopError
from .git import validate_slug
from .util import require_relative_path


VALID_STATUSES = {
    "promising",
    "keep",
    "discard",
    "inconclusive",
    "crash",
    "invalid",
}
SCHEMA_VERSIONS = {0, 1, 2}
TARGET_TYPES = {"relative_improvement", "absolute_improvement", "metric_value"}
PARSER_TYPES = {"json", "jsonl", "regex"}
SELECTOR_TYPES = {"diagnostic", "balanced", "optimization"}
OBJECTIVE_TYPES = {"diagnose", "optimize", "mixed"}
SEARCH_SPACE_TYPES = {"structured_parameters", "unstructured_code", "mixed"}
FIDELITY_TYPES = {"single", "multi"}
NOISE_TYPES = {"low", "high", "unknown"}
TRANSITION_TRIGGERS = {
    "baseline_recorded",
    "experiments_recorded_gte",
    "promising_results_gte",
    "consecutive_inconclusive_gte",
    "target_reached",
    "remaining_experiments_lte",
}
VALUE_TRANSITION_TRIGGERS = {
    "experiments_recorded_gte",
    "promising_results_gte",
    "consecutive_inconclusive_gte",
    "remaining_experiments_lte",
}
SECRET_KEY_RE = re.compile(r"(?:password|secret|credential|api[_-]?key|token)", re.I)
IDEA_SOURCE_TYPES = {"paper", "pull_request", "issue", "user_note", "repository_artifact"}
KNOWLEDGE_MODES = {"none", "local_pack", "agent_retrieval"}


def _mapping(value: Any, field: str) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise ResearchLoopError(f"{field} must be a mapping")
    return value


def _string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ResearchLoopError(f"{field} must be a non-empty string")
    return value


def _positive_number(value: Any, field: str, *, allow_zero: bool = False) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ResearchLoopError(f"{field} must be numeric")
    if value < 0 or (value == 0 and not allow_zero):
        qualifier = "non-negative" if allow_zero else "positive"
        raise ResearchLoopError(f"{field} must be {qualifier}")
    return float(value)


def _relative_list(value: Any, field: str) -> List[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ResearchLoopError(f"{field} must be a list of paths")
    for item in value:
        require_relative_path(item, field)
    return value


def _validate_parser(parser: Any, field: str) -> None:
    parser = _mapping(parser, field)
    kind = parser.get("type")
    if kind not in PARSER_TYPES:
        raise ResearchLoopError(f"{field}.type must be one of {sorted(PARSER_TYPES)}")
    if kind in {"json", "jsonl"}:
        require_relative_path(_string(parser.get("path"), f"{field}.path"), f"{field}.path")
        _string(parser.get("key"), f"{field}.key")
    if kind == "regex":
        if parser.get("source") != "run_log":
            require_relative_path(_string(parser.get("path"), f"{field}.path"), f"{field}.path")
        _string(parser.get("pattern"), f"{field}.pattern")
        group = parser.get("group", 1)
        if not isinstance(group, int) or group < 0:
            raise ResearchLoopError(f"{field}.group must be a non-negative integer")


def _reject_secrets(value: Any, prefix: str = "profile") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            field = f"{prefix}.{key}"
            if SECRET_KEY_RE.search(str(key)):
                raise ResearchLoopError(
                    f"secret-like field is forbidden in Research Profile: {field}; store only its environment variable name"
                )
            _reject_secrets(child, field)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_secrets(child, f"{prefix}[{index}]")


def normalize_profile(profile: Dict[str, Any], repo: Path) -> Dict[str, Any]:
    result = deepcopy(profile)
    version = result.get("schema_version")
    policy = result.setdefault("policy", {})
    if isinstance(policy, dict):
        policy.setdefault("campaign_id", f"{datetime.now().astimezone():%Y-%m-%d}-{repo.name.lower().replace('_', '-')}")
        policy.setdefault("branch_prefix", "autoresearch")
        policy.setdefault("max_experiments", 3)
        policy.setdefault("experiment_timeout_seconds", 1800)
        policy.setdefault("campaign_timeout_seconds", 7200)
        policy.setdefault("allow_gpu", False)
        policy.setdefault("allow_remote", False)
        policy.setdefault("allow_paid", False)
        policy.setdefault("allow_shell", False)
        policy.setdefault("auto_commit", True)
    environment = result.setdefault("environment", {})
    if isinstance(environment, dict):
        environment.setdefault("resource_class", "light")
        environment.setdefault("cwd", ".")
        environment.setdefault("timeout_seconds", 1800)
        environment.setdefault("required_env", [])
    evaluation = result.setdefault("evaluation", {})
    if isinstance(evaluation, dict):
        evaluation.setdefault("required_artifacts", [])
        evaluation.setdefault("compatibility", [])
        evaluation.setdefault("min_duration_seconds", 0)
        evaluation.setdefault("confirmation_runs", 2)
        evaluation.setdefault("min_delta", 0.0)
        evaluation.setdefault("noise_tolerance", 0.0)
        if version in {1, 2}:
            evaluation.setdefault(
                "acceptance",
                {
                    "min_parent_delta": evaluation.get("min_delta", 0.0),
                    "noise_tolerance": evaluation.get("noise_tolerance", 0.0),
                },
            )
            evaluation.setdefault(
                "target",
                {
                    "type": "absolute_improvement",
                    "value": evaluation.get("min_delta", 0.0),
                },
            )
    return result


def _validate_strategy(strategy: Any) -> None:
    strategy = _mapping(strategy, "strategy")
    problem = _mapping(strategy.get("problem_shape"), "strategy.problem_shape")
    enums = (
        ("objective", OBJECTIVE_TYPES),
        ("search_space", SEARCH_SPACE_TYPES),
        ("fidelity", FIDELITY_TYPES),
        ("noise", NOISE_TYPES),
    )
    for field, allowed in enums:
        if problem.get(field) not in allowed:
            raise ResearchLoopError(f"strategy.problem_shape.{field} must be one of {sorted(allowed)}")

    rationale = strategy.get("rationale")
    if not isinstance(rationale, list) or not rationale or not all(
        isinstance(item, str) and item.strip() for item in rationale
    ):
        raise ResearchLoopError("strategy.rationale must be a non-empty list of strings")
    if strategy.get("initial_selector") not in SELECTOR_TYPES:
        raise ResearchLoopError(f"strategy.initial_selector must be one of {sorted(SELECTOR_TYPES)}")

    transitions = strategy.get("transitions", [])
    if not isinstance(transitions, list):
        raise ResearchLoopError("strategy.transitions must be a list")
    seen_ids = set()
    seen_priorities = set()
    for index, item in enumerate(transitions):
        field = f"strategy.transitions[{index}]"
        transition = _mapping(item, field)
        transition_id = validate_slug(_string(transition.get("id"), f"{field}.id"), f"{field}.id")
        if transition_id in seen_ids:
            raise ResearchLoopError(f"duplicate strategy transition id: {transition_id}")
        seen_ids.add(transition_id)
        priority = transition.get("priority")
        if not isinstance(priority, int) or isinstance(priority, bool) or priority < 0:
            raise ResearchLoopError(f"{field}.priority must be a non-negative integer")
        if priority in seen_priorities:
            raise ResearchLoopError(f"duplicate strategy transition priority: {priority}")
        seen_priorities.add(priority)
        source = transition.get("from")
        target = transition.get("to")
        if source not in SELECTOR_TYPES or target not in SELECTOR_TYPES:
            raise ResearchLoopError(f"{field}.from and .to must be supported selectors")
        if source == target:
            raise ResearchLoopError(f"{field}.from and .to must differ")
        trigger = _mapping(transition.get("trigger"), f"{field}.trigger")
        trigger_type = trigger.get("type")
        if trigger_type not in TRANSITION_TRIGGERS:
            raise ResearchLoopError(f"{field}.trigger.type must be one of {sorted(TRANSITION_TRIGGERS)}")
        if trigger_type in VALUE_TRANSITION_TRIGGERS:
            value = trigger.get("value")
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ResearchLoopError(f"{field}.trigger.value must be a non-negative integer")
        elif "value" in trigger:
            raise ResearchLoopError(f"{field}.trigger.value is not allowed for {trigger_type}")


def validate_profile(profile: Dict[str, Any], repo: Path) -> None:
    version = profile.get("schema_version")
    if version not in SCHEMA_VERSIONS:
        raise ResearchLoopError(f"schema_version must be one of {sorted(SCHEMA_VERSIONS)}")
    _reject_secrets(profile)

    context = _mapping(profile.get("context"), "context")
    _string(context.get("goal"), "context.goal")
    _relative_list(context.get("allowed_paths", []), "context.allowed_paths")
    _relative_list(context.get("protected_paths", []), "context.protected_paths")
    criteria = context.get("success_criteria", [])
    if not isinstance(criteria, list) or not all(isinstance(item, str) for item in criteria):
        raise ResearchLoopError("context.success_criteria must be a list of strings")

    environment = _mapping(profile.get("environment"), "environment")
    _string(environment.get("package_manager"), "environment.package_manager")
    if environment.get("resource_class") not in {"light", "local_cpu"}:
        raise ResearchLoopError("the runner supports only light or local_cpu resource_class")
    require_relative_path(_string(environment.get("cwd"), "environment.cwd"), "environment.cwd")
    _positive_number(environment.get("timeout_seconds"), "environment.timeout_seconds")
    commands = _mapping(environment.get("commands"), "environment.commands")
    for command_name in ("smoke", "full"):
        argv = commands.get(command_name)
        if not isinstance(argv, list) or not argv or not all(isinstance(part, str) and part for part in argv):
            raise ResearchLoopError(f"environment.commands.{command_name} must be a non-empty argv list")
    required_env = environment.get("required_env", [])
    if not isinstance(required_env, list) or not all(isinstance(item, str) and item for item in required_env):
        raise ResearchLoopError("environment.required_env must be a list of environment variable names")

    evaluation = _mapping(profile.get("evaluation"), "evaluation")
    primary = _mapping(evaluation.get("primary_metric"), "evaluation.primary_metric")
    _string(primary.get("name"), "evaluation.primary_metric.name")
    if primary.get("direction") not in {"maximize", "minimize"}:
        raise ResearchLoopError("evaluation.primary_metric.direction must be maximize or minimize")
    _validate_parser(primary.get("parser"), "evaluation.primary_metric.parser")
    _relative_list(evaluation.get("required_artifacts", []), "evaluation.required_artifacts")
    _positive_number(evaluation.get("min_duration_seconds", 0), "evaluation.min_duration_seconds", allow_zero=True)
    confirmation_runs = evaluation.get("confirmation_runs")
    if not isinstance(confirmation_runs, int) or confirmation_runs < 2:
        raise ResearchLoopError("evaluation.confirmation_runs must be an integer >= 2")
    _positive_number(evaluation.get("min_delta", 0), "evaluation.min_delta", allow_zero=True)
    _positive_number(evaluation.get("noise_tolerance", 0), "evaluation.noise_tolerance", allow_zero=True)
    if version in {1, 2}:
        acceptance = _mapping(evaluation.get("acceptance"), "evaluation.acceptance")
        _positive_number(
            acceptance.get("min_parent_delta", 0),
            "evaluation.acceptance.min_parent_delta",
            allow_zero=True,
        )
        _positive_number(
            acceptance.get("noise_tolerance", 0),
            "evaluation.acceptance.noise_tolerance",
            allow_zero=True,
        )
        target = _mapping(evaluation.get("target"), "evaluation.target")
        if target.get("type") not in TARGET_TYPES:
            raise ResearchLoopError(f"evaluation.target.type must be one of {sorted(TARGET_TYPES)}")
        _positive_number(target.get("value"), "evaluation.target.value", allow_zero=True)
    compatibility = evaluation.get("compatibility", [])
    if not isinstance(compatibility, list):
        raise ResearchLoopError("evaluation.compatibility must be a list")
    for index, check in enumerate(compatibility):
        check = _mapping(check, f"evaluation.compatibility[{index}]")
        _string(check.get("name"), f"evaluation.compatibility[{index}].name")
        if "expected" not in check:
            raise ResearchLoopError(f"evaluation.compatibility[{index}].expected is required")
        _validate_parser(check.get("parser"), f"evaluation.compatibility[{index}].parser")

    policy = _mapping(profile.get("policy"), "policy")
    validate_slug(_string(policy.get("campaign_id"), "policy.campaign_id"), "policy.campaign_id")
    branch_prefix = _string(policy.get("branch_prefix"), "policy.branch_prefix")
    if branch_prefix.startswith("/") or ".." in branch_prefix.split("/"):
        raise ResearchLoopError("policy.branch_prefix is unsafe")
    max_experiments = policy.get("max_experiments")
    if not isinstance(max_experiments, int) or not 1 <= max_experiments <= 100:
        raise ResearchLoopError("policy.max_experiments must be between 1 and 100")
    experiment_timeout = _positive_number(policy.get("experiment_timeout_seconds"), "policy.experiment_timeout_seconds")
    campaign_timeout = _positive_number(policy.get("campaign_timeout_seconds"), "policy.campaign_timeout_seconds")
    if campaign_timeout < experiment_timeout:
        raise ResearchLoopError("campaign timeout cannot be shorter than experiment timeout")
    for key in ("allow_gpu", "allow_remote", "allow_paid", "allow_shell"):
        if policy.get(key) is not False:
            raise ResearchLoopError(f"the runner requires policy.{key}: false")
    if policy.get("auto_commit") is not True:
        raise ResearchLoopError("the runner requires policy.auto_commit: true for isolated experiment worktrees")
    access = policy.get("knowledge_access")
    if access is not None:
        access = _mapping(access, "policy.knowledge_access")
        mode = access.get("mode")
        if mode not in KNOWLEDGE_MODES:
            raise ResearchLoopError(
                f"policy.knowledge_access.mode must be one of {sorted(KNOWLEDGE_MODES)}"
            )
        allow_network = access.get("allow_network", False)
        if not isinstance(allow_network, bool):
            raise ResearchLoopError("policy.knowledge_access.allow_network must be a boolean")
        if mode == "agent_retrieval" and allow_network is not True:
            raise ResearchLoopError(
                "policy.knowledge_access.allow_network must be true for agent_retrieval"
            )
        if mode != "agent_retrieval" and allow_network:
            raise ResearchLoopError(
                "policy.knowledge_access.allow_network is only allowed for agent_retrieval"
            )
        types = access.get("allowed_source_types", sorted(IDEA_SOURCE_TYPES))
        if (
            not isinstance(types, list)
            or not types
            or not set(types) <= IDEA_SOURCE_TYPES
            or len(set(types)) != len(types)
        ):
            raise ResearchLoopError(
                "policy.knowledge_access.allowed_source_types must be a non-empty subset of "
                f"{sorted(IDEA_SOURCE_TYPES)}"
            )
        for key in ("max_sources_per_round", "max_record_bytes"):
            value = access.get(key, 1)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ResearchLoopError(f"policy.knowledge_access.{key} must be a positive integer")
        if not isinstance(access.get("retrieval_cutoff", ""), str):
            raise ResearchLoopError("policy.knowledge_access.retrieval_cutoff must be a string")

    if version == 2:
        _validate_strategy(profile.get("strategy"))


def split_profile(profile: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    version = profile["schema_version"]
    documents = {
        "research-context.yaml": {"schema_version": version, "context": profile["context"]},
        "environment.yaml": {"schema_version": version, "environment": profile["environment"]},
        "evaluation.yaml": {"schema_version": version, "evaluation": profile["evaluation"]},
        "loop-policy.yaml": {"schema_version": version, "policy": profile["policy"]},
    }
    if version == 2:
        documents["research-strategy.yaml"] = {"schema_version": version, "strategy": profile["strategy"]}
    return documents
