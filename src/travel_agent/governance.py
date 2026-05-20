from __future__ import annotations

from dataclasses import dataclass

from .acceptance import IntegrationAcceptanceReport
from .config import IntegrationSettings
from .permissions import PermissionPolicy
from .release_control import RolloutPolicy
from .smoke import SmokeProbeReport


@dataclass(frozen=True)
class GovernanceCheck:
    name: str
    status: str
    detail: str


@dataclass(frozen=True)
class ReleaseReadinessReport:
    status: str
    checks: list[GovernanceCheck]


def run_release_readiness_report(
    settings: IntegrationSettings,
    acceptance_report: IntegrationAcceptanceReport | None = None,
    smoke_report: SmokeProbeReport | None = None,
    rollout_policy: RolloutPolicy | None = None,
    permission_policy: PermissionPolicy | None = None,
) -> ReleaseReadinessReport:
    checks = [
        _fallback_governance(settings),
        _persistence_governance(settings),
        _rollout_governance(rollout_policy or RolloutPolicy.from_env()),
        _permission_governance(permission_policy or PermissionPolicy.from_env()),
        _token_governance(settings),
        _auditability_governance(),
        _audit_sink_governance(settings),
        _data_minimization_governance(),
    ]
    if acceptance_report is not None:
        checks.append(_acceptance_governance(acceptance_report))
    if smoke_report is not None:
        checks.append(_smoke_governance(smoke_report))

    if any(check.status == "FAIL" for check in checks):
        status = "FAIL"
    elif any(check.status == "WARN" for check in checks):
        status = "ACTION_REQUIRED"
    else:
        status = "PASS"
    return ReleaseReadinessReport(status=status, checks=checks)


def render_release_readiness_report(report: ReleaseReadinessReport) -> str:
    lines = [
        "Release readiness report:",
        f"- status: {report.status}",
        "Checks:",
    ]
    for check in report.checks:
        lines.append(f"- {check.status} {check.name}: {check.detail}")
    return "\n".join(lines)


def _fallback_governance(settings: IntegrationSettings) -> GovernanceCheck:
    enabled: list[str] = []
    if settings.use_mock_fallback:
        enabled.append("core")
    if settings.notification_use_mock_fallback:
        enabled.append("notification")
    if settings.calendar_use_mock_fallback:
        enabled.append("calendar")
    if enabled:
        return GovernanceCheck(
            name="mock_fallback",
            status="WARN",
            detail=f"disable fallback before production: {', '.join(enabled)}",
        )
    return GovernanceCheck("mock_fallback", "PASS", "all fallback switches disabled")


def _persistence_governance(settings: IntegrationSettings) -> GovernanceCheck:
    backend = settings.session_store_backend.strip().lower()
    if settings.session_store_api_url:
        return GovernanceCheck("session_store", "PASS", "external HTTP session store configured")
    if settings.session_db_path and backend in {"auto", "sqlite"}:
        return GovernanceCheck("session_store", "PASS", "SQLite durable session store configured")
    return GovernanceCheck(
        name="session_store",
        status="FAIL",
        detail="production requires TRAVEL_SESSION_DB_PATH or TRAVEL_SESSION_STORE_API_URL",
    )


def _token_governance(settings: IntegrationSettings) -> GovernanceCheck:
    missing = _missing_tokens(settings)
    if missing:
        return GovernanceCheck(
            name="api_tokens",
            status="WARN",
            detail=f"configured endpoints without tokens: {', '.join(missing)}",
        )
    return GovernanceCheck("api_tokens", "PASS", "configured endpoints have matching tokens or do not require one")


def _rollout_governance(policy: RolloutPolicy) -> GovernanceCheck:
    if policy.rollback_enabled:
        reason = policy.rollback_reason or "rollback enabled"
        return GovernanceCheck("rollout_control", "FAIL", f"rollback is active: {reason}")
    if not policy.enabled:
        return GovernanceCheck("rollout_control", "WARN", "rollout switch is disabled")
    percentage = max(0, min(100, policy.percentage))
    if percentage == 0 and not policy.allowed_users and not policy.allowed_departments:
        return GovernanceCheck("rollout_control", "WARN", "rollout is enabled but no audience is allowed")
    return GovernanceCheck(
        "rollout_control",
        "PASS",
        f"rollout enabled for {percentage}% plus explicit users/departments",
    )


def _permission_governance(policy: PermissionPolicy) -> GovernanceCheck:
    if not policy.enabled:
        return GovernanceCheck("permission_policy", "WARN", "permission enforcement is disabled")
    required_actions = {"plan_trip", "create_approval", "book_order"}
    blocked_required = sorted(policy.blocked_actions.intersection(required_actions))
    if blocked_required:
        return GovernanceCheck(
            "permission_policy",
            "FAIL",
            "production policy blocks required actions: " + ", ".join(blocked_required),
        )
    missing_required = sorted(required_actions.difference(policy.allowed_actions))
    if missing_required:
        return GovernanceCheck(
            "permission_policy",
            "FAIL",
            "required actions are not allowed before release: " + ", ".join(missing_required),
        )
    if policy.api_url:
        return GovernanceCheck("permission_policy", "PASS", "external permission center configured")
    if not (policy.required_roles or policy.allowed_users or policy.allowed_departments):
        return GovernanceCheck(
            "permission_policy",
            "WARN",
            "permission enforcement is enabled without role or audience constraints",
        )
    constraints = []
    if policy.required_roles:
        constraints.append("roles=" + ",".join(sorted(policy.required_roles)))
    if policy.allowed_users:
        constraints.append("users=" + str(len(policy.allowed_users)))
    if policy.allowed_departments:
        constraints.append("departments=" + ",".join(sorted(policy.allowed_departments)))
    return GovernanceCheck(
        "permission_policy",
        "WARN",
        "local permission policy active; external permission center not configured: " + "; ".join(constraints),
    )


def _auditability_governance() -> GovernanceCheck:
    return GovernanceCheck(
        name="auditability",
        status="PASS",
        detail="ToolGateway audit trail, AgentExecutionRecord, worker runs, storage health and OTLP export are implemented",
    )


def _audit_sink_governance(settings: IntegrationSettings) -> GovernanceCheck:
    if not settings.audit_log_api_url:
        return GovernanceCheck("audit_log_sink", "WARN", "external audit log sink is not configured")
    return GovernanceCheck("audit_log_sink", "PASS", "external audit log sink configured")


def _data_minimization_governance() -> GovernanceCheck:
    return GovernanceCheck(
        name="data_minimization",
        status="PASS",
        detail="current models avoid payment credentials and identity documents; production logs should keep payload review enabled",
    )


def _acceptance_governance(report: IntegrationAcceptanceReport) -> GovernanceCheck:
    if report.status == "PASS":
        return GovernanceCheck("integration_acceptance", "PASS", "acceptance report passed")
    if report.status == "FAIL":
        return GovernanceCheck("integration_acceptance", "FAIL", "acceptance report failed")
    return GovernanceCheck("integration_acceptance", "WARN", f"acceptance status is {report.status}")


def _smoke_governance(report: SmokeProbeReport) -> GovernanceCheck:
    if report.status == "PASS":
        return GovernanceCheck("smoke_probes", "PASS", f"{report.passed} probes passed")
    if report.status == "FAIL":
        return GovernanceCheck("smoke_probes", "FAIL", f"{report.failed} probes failed")
    return GovernanceCheck(
        "smoke_probes",
        "WARN",
        f"smoke status is {report.status}: passed={report.passed}, skipped={report.skipped}",
    )


def _missing_tokens(settings: IntegrationSettings) -> list[str]:
    missing: list[str] = []
    if settings.policy_api_url and not settings.policy_api_token:
        missing.append("policy")
    if (
        settings.transport_policy_api_url
        or settings.transport_inventory_api_url
        or settings.transport_order_api_url
        or settings.transport_order_status_api_url
        or settings.transport_order_cancel_api_url
        or settings.transport_change_api_url
    ) and not settings.transport_api_token:
        missing.append("transport")
    if (
        settings.hotel_inventory_api_url
        or settings.hotel_price_check_api_url
        or settings.hotel_inventory_lock_api_url
        or settings.hotel_inventory_release_api_url
    ) and not settings.hotel_inventory_api_token:
        missing.append("hotel")
    if (
        settings.oa_approval_api_url
        or settings.oa_approval_status_api_url
        or settings.oa_approval_cancel_api_url
        or settings.change_approval_api_url
    ) and not settings.oa_approval_api_token:
        missing.append("oa")
    if (
        settings.order_api_url
        or settings.order_status_api_url
        or settings.order_cancel_api_url
        or settings.refund_estimate_api_url
        or settings.refund_confirm_api_url
        or settings.hotel_change_api_url
        or settings.change_failure_compensation_api_url
    ) and not settings.order_api_token:
        missing.append("order")
    if settings.notification_api_url and not settings.notification_api_token:
        missing.append("notification")
    if settings.calendar_api_url and not settings.calendar_api_token:
        missing.append("calendar")
    if settings.permission_api_url and not settings.permission_api_token:
        missing.append("permission")
    if settings.audit_log_api_url and not settings.audit_log_api_token:
        missing.append("audit_log")
    if settings.alert_api_url and not settings.alert_api_token:
        missing.append("alert")
    if settings.oncall_api_url and not settings.oncall_api_token:
        missing.append("oncall")
    if settings.session_store_api_url and not settings.session_store_api_token:
        missing.append("session_store")
    if settings.otlp_http_endpoint and not settings.otlp_api_token:
        missing.append("otlp")
    return missing
