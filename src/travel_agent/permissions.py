from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any


KNOWN_ACTIONS = {
    "plan_trip",
    "create_approval",
    "book_order",
    "change_trip",
    "cancel_trip",
    "sync_calendar",
    "replay_dead_letter",
    "run_worker",
    "view_operations_console",
    "create_replay_job",
    "execute_replay_job",
    "run_operations_schedule",
    "publish_closed_loop_schema",
    "update_governance_policy",
    "retry_audit_sink_delivery",
    "manage_compensation_task",
}


@dataclass(frozen=True)
class PermissionPolicy:
    enabled: bool = False
    allowed_actions: set[str] = field(default_factory=lambda: set(KNOWN_ACTIONS))
    blocked_actions: set[str] = field(default_factory=set)
    required_roles: set[str] = field(default_factory=set)
    allowed_users: set[str] = field(default_factory=set)
    blocked_users: set[str] = field(default_factory=set)
    allowed_departments: set[str] = field(default_factory=set)
    blocked_departments: set[str] = field(default_factory=set)
    api_url: str | None = None
    api_token: str | None = None

    @classmethod
    def from_env(cls) -> "PermissionPolicy":
        allowed_actions = _csv_env("TRAVEL_PERMISSION_ALLOWED_ACTIONS")
        return cls(
            enabled=_bool_env("TRAVEL_PERMISSION_ENABLED", False),
            allowed_actions=allowed_actions or set(KNOWN_ACTIONS),
            blocked_actions=_csv_env("TRAVEL_PERMISSION_BLOCKED_ACTIONS"),
            required_roles=_csv_env("TRAVEL_PERMISSION_REQUIRED_ROLES"),
            allowed_users=_csv_env("TRAVEL_PERMISSION_ALLOWED_USERS"),
            blocked_users=_csv_env("TRAVEL_PERMISSION_BLOCKED_USERS"),
            allowed_departments=_csv_env("TRAVEL_PERMISSION_ALLOWED_DEPARTMENTS"),
            blocked_departments=_csv_env("TRAVEL_PERMISSION_BLOCKED_DEPARTMENTS"),
            api_url=_optional_env("TRAVEL_PERMISSION_API_URL"),
            api_token=_optional_env("TRAVEL_PERMISSION_API_TOKEN"),
        )


@dataclass(frozen=True)
class PermissionDecision:
    allowed: bool
    enforced: bool
    status: str
    action: str
    user_id: str
    department: str | None
    roles: list[str]
    reasons: list[str]
    source: str = "local"
    payload: dict[str, Any] = field(default_factory=dict)


class PermissionDeniedError(PermissionError):
    pass


def evaluate_permission(
    policy: PermissionPolicy,
    user_id: str,
    action: str,
    department: str | None = None,
    roles: set[str] | list[str] | tuple[str, ...] | None = None,
    http_client: Any | None = None,
) -> PermissionDecision:
    if policy.enabled and policy.api_url:
        remote = _evaluate_permission_remote(policy, user_id, action, department, roles, http_client)
        if remote is not None:
            return remote

    normalized_department = (department or "").strip() or None
    normalized_roles = {role.strip() for role in roles or [] if role.strip()}

    if not policy.enabled:
        return PermissionDecision(
            allowed=True,
            enforced=False,
            status="NOT_ENFORCED",
            action=action,
            user_id=user_id,
            department=normalized_department,
            roles=sorted(normalized_roles),
            reasons=["permission enforcement is disabled"],
            payload={},
        )

    if action in policy.blocked_actions:
        return _deny(action, user_id, normalized_department, normalized_roles, f"action {action} is blocked")
    if policy.allowed_actions and action not in policy.allowed_actions:
        return _deny(action, user_id, normalized_department, normalized_roles, f"action {action} is not allowed")
    if user_id in policy.blocked_users:
        return _deny(action, user_id, normalized_department, normalized_roles, f"user {user_id} is blocked")
    if normalized_department and normalized_department in policy.blocked_departments:
        return _deny(
            action,
            user_id,
            normalized_department,
            normalized_roles,
            f"department {normalized_department} is blocked",
        )

    reasons: list[str] = []
    if user_id in policy.allowed_users:
        reasons.append(f"user {user_id} is explicitly allowed")
    elif normalized_department and normalized_department in policy.allowed_departments:
        reasons.append(f"department {normalized_department} is explicitly allowed")
    elif policy.allowed_users or policy.allowed_departments:
        return _deny(
            action,
            user_id,
            normalized_department,
            normalized_roles,
            "user or department is outside the allowed audience",
        )

    if policy.required_roles and not normalized_roles.intersection(policy.required_roles):
        return _deny(
            action,
            user_id,
            normalized_department,
            normalized_roles,
            "missing required role: " + ",".join(sorted(policy.required_roles)),
        )

    if not reasons:
        reasons.append("permission policy matched")
    return PermissionDecision(
        allowed=True,
        enforced=True,
        status="ALLOW",
        action=action,
        user_id=user_id,
        department=normalized_department,
        roles=sorted(normalized_roles),
        reasons=reasons,
        payload={
            "user_id": user_id,
            "action": action,
            "department": normalized_department or "",
            "roles": ",".join(sorted(normalized_roles)),
        },
    )


def ensure_permission(decision: PermissionDecision) -> None:
    if decision.allowed:
        return
    raise PermissionDeniedError("; ".join(decision.reasons))


def render_permission_decision(decision: PermissionDecision) -> str:
    lines = [
        "Permission decision:",
        f"- status: {decision.status}",
        f"- allowed: {decision.allowed}",
        f"- enforced: {decision.enforced}",
        f"- action: {decision.action}",
        f"- user: {decision.user_id}",
        f"- department: {decision.department or '-'}",
        f"- roles: {', '.join(decision.roles) if decision.roles else '-'}",
        f"- source: {decision.source}",
    ]
    for reason in decision.reasons:
        lines.append(f"- reason: {reason}")
    return "\n".join(lines)


def _deny(
    action: str,
    user_id: str,
    department: str | None,
    roles: set[str],
    reason: str,
) -> PermissionDecision:
    return PermissionDecision(
        allowed=False,
        enforced=True,
        status="DENY",
        action=action,
        user_id=user_id,
        department=department,
        roles=sorted(roles),
        reasons=[reason],
        payload={
            "user_id": user_id,
            "action": action,
            "department": department or "",
            "roles": ",".join(sorted(roles)),
        },
    )


def _evaluate_permission_remote(
    policy: PermissionPolicy,
    user_id: str,
    action: str,
    department: str | None,
    roles: set[str] | list[str] | tuple[str, ...] | None,
    http_client: Any | None,
) -> PermissionDecision | None:
    from .integrations import JsonHttpClient

    payload = {
        "user_id": user_id,
        "action": action,
        "department": department,
        "roles": sorted({role.strip() for role in roles or [] if role.strip()}),
    }
    try:
        client = http_client or JsonHttpClient()
        response = client.post_json(policy.api_url or "", payload, policy.api_token)
    except Exception:
        return None
    data = response.get("decision") or response.get("data") or response
    allowed = bool(data.get("allowed", True))
    reasons = list(data.get("reasons") or ([] if allowed else ["remote permission denied"]))
    return PermissionDecision(
        allowed=allowed,
        enforced=True,
        status=str(data.get("status") or ("ALLOW" if allowed else "DENY")),
        action=action,
        user_id=user_id,
        department=(department or "").strip() or None,
        roles=sorted({role.strip() for role in roles or [] if role.strip()}),
        reasons=reasons,
        source=str(data.get("source") or "remote"),
        payload=payload,
    )


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
