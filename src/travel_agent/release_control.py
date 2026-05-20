from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class RolloutPolicy:
    enabled: bool = False
    percentage: int = 0
    salt: str = "travel-agent"
    allowed_users: set[str] = field(default_factory=set)
    blocked_users: set[str] = field(default_factory=set)
    allowed_departments: set[str] = field(default_factory=set)
    blocked_departments: set[str] = field(default_factory=set)
    rollback_enabled: bool = False
    rollback_reason: str | None = None
    rollback_runbook_url: str | None = None

    @classmethod
    def from_env(cls) -> "RolloutPolicy":
        return cls(
            enabled=_bool_env("TRAVEL_ROLLOUT_ENABLED", False),
            percentage=_int_env("TRAVEL_ROLLOUT_PERCENTAGE", 0),
            salt=os.getenv("TRAVEL_ROLLOUT_SALT", "travel-agent"),
            allowed_users=_csv_env("TRAVEL_ROLLOUT_ALLOWED_USERS"),
            blocked_users=_csv_env("TRAVEL_ROLLOUT_BLOCKED_USERS"),
            allowed_departments=_csv_env("TRAVEL_ROLLOUT_ALLOWED_DEPARTMENTS"),
            blocked_departments=_csv_env("TRAVEL_ROLLOUT_BLOCKED_DEPARTMENTS"),
            rollback_enabled=_bool_env("TRAVEL_ROLLBACK_ENABLED", False),
            rollback_reason=_optional_env("TRAVEL_ROLLBACK_REASON"),
            rollback_runbook_url=_optional_env("TRAVEL_ROLLBACK_RUNBOOK_URL"),
        )


@dataclass(frozen=True)
class RolloutDecision:
    enabled: bool
    status: str
    bucket: int
    reasons: list[str]


def evaluate_rollout(
    policy: RolloutPolicy,
    user_id: str,
    department: str | None = None,
    scenario: str = "default",
) -> RolloutDecision:
    normalized_department = department or ""
    bucket = _bucket(policy.salt, user_id, normalized_department, scenario)
    if policy.rollback_enabled:
        reason = policy.rollback_reason or "rollback enabled"
        return RolloutDecision(False, "ROLLED_BACK", bucket, [reason])
    if user_id in policy.blocked_users:
        return RolloutDecision(False, "DISABLED", bucket, [f"user {user_id} is blocked"])
    if normalized_department and normalized_department in policy.blocked_departments:
        return RolloutDecision(False, "DISABLED", bucket, [f"department {normalized_department} is blocked"])
    if user_id in policy.allowed_users:
        return RolloutDecision(True, "ENABLED", bucket, [f"user {user_id} is explicitly allowed"])
    if normalized_department and normalized_department in policy.allowed_departments:
        return RolloutDecision(True, "ENABLED", bucket, [f"department {normalized_department} is explicitly allowed"])
    if not policy.enabled:
        return RolloutDecision(False, "DISABLED", bucket, ["rollout is disabled"])
    percentage = max(0, min(100, policy.percentage))
    if bucket < percentage:
        return RolloutDecision(True, "ENABLED", bucket, [f"bucket {bucket} is within {percentage}% rollout"])
    return RolloutDecision(False, "DISABLED", bucket, [f"bucket {bucket} is outside {percentage}% rollout"])


def render_rollout_decision(decision: RolloutDecision) -> str:
    lines = [
        "Rollout decision:",
        f"- status: {decision.status}",
        f"- enabled: {decision.enabled}",
        f"- bucket: {decision.bucket}",
    ]
    for reason in decision.reasons:
        lines.append(f"- reason: {reason}")
    return "\n".join(lines)


def _bucket(salt: str, user_id: str, department: str, scenario: str) -> int:
    digest = hashlib.sha256(f"{salt}:{user_id}:{department}:{scenario}".encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % 100


def _optional_env(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def _csv_env(name: str) -> set[str]:
    value = _optional_env(name)
    if value is None:
        return set()
    return {item.strip() for item in value.split(",") if item.strip()}


def _bool_env(name: str, default: bool) -> bool:
    value = _optional_env(name)
    if value is None:
        return default
    normalized = value.lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _int_env(name: str, default: int) -> int:
    value = _optional_env(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default
