from __future__ import annotations

from dataclasses import dataclass

from .config import IntegrationSettings
from .evaluation import EvalReport, run_evaluation_suite
from .storage import StorageHealth


@dataclass(frozen=True)
class AcceptanceCheck:
    name: str
    status: str
    detail: str


@dataclass(frozen=True)
class IntegrationEndpointStatus:
    system: str
    endpoint: str
    configured: bool
    required_for_production: bool
    fallback_allowed: bool

    @property
    def status(self) -> str:
        if self.configured:
            return "CONFIGURED"
        if self.required_for_production:
            return "MISSING"
        return "OPTIONAL_MISSING"


@dataclass(frozen=True)
class IntegrationAcceptanceReport:
    status: str
    checks: list[AcceptanceCheck]
    endpoints: list[IntegrationEndpointStatus]
    evaluation: EvalReport | None = None
    storage_health: StorageHealth | None = None

    @property
    def configured_required_endpoints(self) -> int:
        return sum(1 for item in self.endpoints if item.required_for_production and item.configured)

    @property
    def required_endpoints(self) -> int:
        return sum(1 for item in self.endpoints if item.required_for_production)

    @property
    def missing_required_endpoints(self) -> list[IntegrationEndpointStatus]:
        return [
            item
            for item in self.endpoints
            if item.required_for_production and not item.configured
        ]


def run_integration_acceptance_report(
    settings: IntegrationSettings,
    evaluation: EvalReport | None = None,
    storage_health: StorageHealth | None = None,
    include_evaluation: bool = True,
) -> IntegrationAcceptanceReport:
    resolved_evaluation = evaluation
    if include_evaluation and resolved_evaluation is None:
        resolved_evaluation = run_evaluation_suite()

    endpoints = build_endpoint_statuses(settings)
    checks = [
        _endpoint_readiness_check(endpoints),
        _fallback_check(settings),
        _storage_check(settings, storage_health),
    ]
    if resolved_evaluation is not None:
        checks.append(_evaluation_check(resolved_evaluation))

    if any(check.status == "FAIL" for check in checks):
        status = "FAIL"
    elif any(check.status == "WARN" for check in checks):
        status = "ACTION_REQUIRED"
    else:
        status = "PASS"
    return IntegrationAcceptanceReport(
        status=status,
        checks=checks,
        endpoints=endpoints,
        evaluation=resolved_evaluation,
        storage_health=storage_health,
    )


def build_endpoint_statuses(settings: IntegrationSettings) -> list[IntegrationEndpointStatus]:
    fallback_allowed = settings.use_mock_fallback
    return [
        _endpoint("policy", "TRAVEL_POLICY_API_URL", settings.policy_api_url, True, fallback_allowed),
        _endpoint(
            "transport_policy",
            "TRAVEL_TRANSPORT_POLICY_API_URL",
            settings.transport_policy_api_url,
            True,
            fallback_allowed,
        ),
        _endpoint(
            "hotel_inventory",
            "TRAVEL_HOTEL_INVENTORY_API_URL",
            settings.hotel_inventory_api_url,
            True,
            fallback_allowed,
        ),
        _endpoint(
            "transport_inventory",
            "TRAVEL_TRANSPORT_INVENTORY_API_URL",
            settings.transport_inventory_api_url,
            True,
            fallback_allowed,
        ),
        _endpoint(
            "hotel_price_check",
            "TRAVEL_HOTEL_PRICE_CHECK_API_URL",
            settings.hotel_price_check_api_url,
            True,
            fallback_allowed,
        ),
        _endpoint(
            "hotel_inventory_lock",
            "TRAVEL_HOTEL_INVENTORY_LOCK_API_URL",
            settings.hotel_inventory_lock_api_url,
            True,
            fallback_allowed,
        ),
        _endpoint(
            "hotel_inventory_release",
            "TRAVEL_HOTEL_INVENTORY_RELEASE_API_URL",
            settings.hotel_inventory_release_api_url,
            True,
            fallback_allowed,
        ),
        _endpoint("oa_approval", "TRAVEL_OA_APPROVAL_API_URL", settings.oa_approval_api_url, True, fallback_allowed),
        _endpoint(
            "oa_approval_status",
            "TRAVEL_OA_APPROVAL_STATUS_API_URL",
            settings.oa_approval_status_api_url,
            True,
            fallback_allowed,
        ),
        _endpoint(
            "oa_approval_cancel",
            "TRAVEL_OA_APPROVAL_CANCEL_API_URL",
            settings.oa_approval_cancel_api_url,
            True,
            fallback_allowed,
        ),
        _endpoint("order", "TRAVEL_ORDER_API_URL", settings.order_api_url, True, fallback_allowed),
        _endpoint("order_status", "TRAVEL_ORDER_STATUS_API_URL", settings.order_status_api_url, True, fallback_allowed),
        _endpoint("order_cancel", "TRAVEL_ORDER_CANCEL_API_URL", settings.order_cancel_api_url, True, fallback_allowed),
        _endpoint("transport_order", "TRAVEL_TRANSPORT_ORDER_API_URL", settings.transport_order_api_url, True, fallback_allowed),
        _endpoint(
            "transport_order_status",
            "TRAVEL_TRANSPORT_ORDER_STATUS_API_URL",
            settings.transport_order_status_api_url,
            True,
            fallback_allowed,
        ),
        _endpoint(
            "transport_order_cancel",
            "TRAVEL_TRANSPORT_ORDER_CANCEL_API_URL",
            settings.transport_order_cancel_api_url,
            True,
            fallback_allowed,
        ),
        _endpoint("refund_estimate", "TRAVEL_REFUND_ESTIMATE_API_URL", settings.refund_estimate_api_url, True, fallback_allowed),
        _endpoint("refund_confirm", "TRAVEL_REFUND_CONFIRM_API_URL", settings.refund_confirm_api_url, True, fallback_allowed),
        _endpoint("change_approval", "TRAVEL_CHANGE_APPROVAL_API_URL", settings.change_approval_api_url, True, fallback_allowed),
        _endpoint("hotel_change", "TRAVEL_HOTEL_CHANGE_API_URL", settings.hotel_change_api_url, True, fallback_allowed),
        _endpoint("transport_change", "TRAVEL_TRANSPORT_CHANGE_API_URL", settings.transport_change_api_url, True, fallback_allowed),
        _endpoint(
            "change_failure_compensation",
            "TRAVEL_CHANGE_FAILURE_COMPENSATION_API_URL",
            settings.change_failure_compensation_api_url,
            True,
            fallback_allowed,
        ),
        _endpoint(
            "notification",
            "TRAVEL_NOTIFICATION_API_URL",
            settings.notification_api_url,
            True,
            settings.notification_use_mock_fallback and fallback_allowed,
        ),
        _endpoint(
            "calendar",
            "TRAVEL_CALENDAR_API_URL",
            settings.calendar_api_url,
            True,
            settings.calendar_use_mock_fallback and fallback_allowed,
        ),
        _endpoint("alert_sink", "TRAVEL_ALERT_API_URL", settings.alert_api_url, False, True),
        _endpoint("oncall", "TRAVEL_ONCALL_API_URL", settings.oncall_api_url, False, True),
        _endpoint("otlp", "TRAVEL_OTLP_HTTP_ENDPOINT", settings.otlp_http_endpoint, False, True),
        _endpoint(
            "session_store_http",
            "TRAVEL_SESSION_STORE_API_URL",
            settings.session_store_api_url,
            False,
            True,
        ),
    ]


def render_integration_acceptance_report(report: IntegrationAcceptanceReport) -> str:
    lines = [
        "Integration acceptance report:",
        f"- status: {report.status}",
        (
            "- required_endpoints: "
            f"{report.configured_required_endpoints}/{report.required_endpoints} configured"
        ),
    ]
    if report.evaluation is not None:
        lines.append(f"- evaluation: {report.evaluation.passed} passed / {report.evaluation.failed} failed")
    if report.storage_health is not None:
        lines.append(
            "- storage_health: "
            f"{report.storage_health.backend} ok={report.storage_health.ok} "
            f"sessions={report.storage_health.session_count}"
        )
    lines.append("Checks:")
    for check in report.checks:
        lines.append(f"- {check.status} {check.name}: {check.detail}")
    lines.append("Required endpoints:")
    for endpoint in [item for item in report.endpoints if item.required_for_production]:
        fallback = "fallback=true" if endpoint.fallback_allowed else "fallback=false"
        lines.append(
            f"- {endpoint.status} {endpoint.system}: {endpoint.endpoint} ({fallback})"
        )
    optional = [item for item in report.endpoints if not item.required_for_production]
    if optional:
        lines.append("Optional endpoints:")
        for endpoint in optional:
            lines.append(f"- {endpoint.status} {endpoint.system}: {endpoint.endpoint}")
    return "\n".join(lines)


def _endpoint(
    system: str,
    endpoint: str,
    value: str | None,
    required_for_production: bool,
    fallback_allowed: bool,
) -> IntegrationEndpointStatus:
    return IntegrationEndpointStatus(
        system=system,
        endpoint=endpoint,
        configured=bool(value),
        required_for_production=required_for_production,
        fallback_allowed=fallback_allowed,
    )


def _endpoint_readiness_check(endpoints: list[IntegrationEndpointStatus]) -> AcceptanceCheck:
    required = [item for item in endpoints if item.required_for_production]
    missing = [item for item in required if not item.configured]
    if not missing:
        return AcceptanceCheck(
            name="required_endpoints",
            status="PASS",
            detail=f"{len(required)}/{len(required)} production endpoints configured",
        )
    return AcceptanceCheck(
        name="required_endpoints",
        status="WARN",
        detail=f"{len(required) - len(missing)}/{len(required)} configured; missing: {_names(missing)}",
    )


def _fallback_check(settings: IntegrationSettings) -> AcceptanceCheck:
    if (
        not settings.use_mock_fallback
        and not settings.notification_use_mock_fallback
        and not settings.calendar_use_mock_fallback
    ):
        return AcceptanceCheck(
            name="mock_fallback",
            status="PASS",
            detail="all mock fallback switches are disabled",
        )
    enabled: list[str] = []
    if settings.use_mock_fallback:
        enabled.append("core")
    if settings.notification_use_mock_fallback:
        enabled.append("notification")
    if settings.calendar_use_mock_fallback:
        enabled.append("calendar")
    return AcceptanceCheck(
        name="mock_fallback",
        status="WARN",
        detail=f"fallback still enabled: {', '.join(enabled)}",
    )


def _storage_check(
    settings: IntegrationSettings,
    storage_health: StorageHealth | None,
) -> AcceptanceCheck:
    backend = settings.session_store_backend.strip().lower()
    if settings.session_store_api_url:
        configured = "http"
    elif settings.session_db_path:
        configured = "sqlite"
    elif backend == "memory":
        configured = "memory"
    else:
        configured = "memory"

    if configured == "memory":
        return AcceptanceCheck(
            name="session_store",
            status="WARN",
            detail="memory store is not durable; configure SQLite or HTTP store for integration acceptance",
        )
    if storage_health is None:
        return AcceptanceCheck(
            name="session_store",
            status="PASS",
            detail=f"{configured} store configured; health check not executed",
        )
    if storage_health.ok:
        return AcceptanceCheck(
            name="session_store",
            status="PASS",
            detail=f"{storage_health.backend} health ok",
        )
    return AcceptanceCheck(
        name="session_store",
        status="FAIL",
        detail=f"{storage_health.backend} health failed: {storage_health.details}",
    )


def _evaluation_check(report: EvalReport) -> AcceptanceCheck:
    if report.failed == 0:
        return AcceptanceCheck(
            name="evaluation_suite",
            status="PASS",
            detail=f"{report.passed} scenarios passed",
        )
    return AcceptanceCheck(
        name="evaluation_suite",
        status="FAIL",
        detail=f"{report.failed} scenarios failed",
    )


def _names(endpoints: list[IntegrationEndpointStatus]) -> str:
    return ", ".join(item.system for item in endpoints)
