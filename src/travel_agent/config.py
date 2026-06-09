from __future__ import annotations

import os
from dataclasses import dataclass


TRUE_VALUES = {"1", "true", "yes", "y", "on"}
FALSE_VALUES = {"0", "false", "no", "n", "off"}


@dataclass(frozen=True)
class IntegrationSettings:
    policy_api_url: str | None = None
    transport_policy_api_url: str | None = None
    hotel_inventory_api_url: str | None = None
    hotel_price_check_api_url: str | None = None
    hotel_inventory_lock_api_url: str | None = None
    hotel_inventory_release_api_url: str | None = None
    oa_approval_api_url: str | None = None
    oa_approval_status_api_url: str | None = None
    oa_approval_cancel_api_url: str | None = None
    order_api_url: str | None = None
    order_status_api_url: str | None = None
    order_cancel_api_url: str | None = None
    refund_estimate_api_url: str | None = None
    refund_confirm_api_url: str | None = None
    change_approval_api_url: str | None = None
    change_failure_compensation_api_url: str | None = None
    hotel_change_api_url: str | None = None
    transport_inventory_api_url: str | None = None
    transport_order_api_url: str | None = None
    transport_order_status_api_url: str | None = None
    transport_order_cancel_api_url: str | None = None
    transport_change_api_url: str | None = None
    notification_api_url: str | None = None
    calendar_api_url: str | None = None
    permission_api_url: str | None = None
    audit_log_api_url: str | None = None
    alert_api_url: str | None = None
    oncall_api_url: str | None = None
    oncall_status_api_url: str | None = None
    oncall_webhook_secret: str | None = None
    closed_loop_api_url: str | None = None
    closed_loop_schema_registry_url: str | None = None
    recovery_approval_api_url: str | None = None
    recovery_governance_policy_json: str | None = None
    recovery_governance_policy_api_url: str | None = None
    compensation_execution_policy_json: str | None = None
    compensation_slo_policy_json: str | None = None
    compensation_remediation_policy_json: str | None = None
    operations_dashboard_token: str | None = None
    alert_rules_json: str | None = None
    trend_alert_rules_json: str | None = None
    action_sla_policy_json: str | None = None
    otlp_http_endpoint: str | None = None
    policy_api_token: str | None = None
    transport_api_token: str | None = None
    hotel_inventory_api_token: str | None = None
    oa_approval_api_token: str | None = None
    order_api_token: str | None = None
    notification_api_token: str | None = None
    calendar_api_token: str | None = None
    permission_api_token: str | None = None
    audit_log_api_token: str | None = None
    alert_api_token: str | None = None
    oncall_api_token: str | None = None
    closed_loop_api_token: str | None = None
    closed_loop_schema_registry_api_token: str | None = None
    recovery_approval_api_token: str | None = None
    recovery_governance_policy_api_token: str | None = None
    otlp_api_token: str | None = None
    use_mock_fallback: bool = True
    notification_use_mock_fallback: bool = True
    calendar_use_mock_fallback: bool = True
    timeout_seconds: float = 5.0
    session_db_path: str | None = None
    session_store_backend: str = "auto"
    session_store_api_url: str | None = None
    session_store_api_token: str | None = None

    @classmethod
    def from_env(cls) -> "IntegrationSettings":
        return cls(
            policy_api_url=_optional_env("TRAVEL_POLICY_API_URL"),
            transport_policy_api_url=_optional_env("TRAVEL_TRANSPORT_POLICY_API_URL"),
            hotel_inventory_api_url=_optional_env("TRAVEL_HOTEL_INVENTORY_API_URL"),
            hotel_price_check_api_url=_optional_env("TRAVEL_HOTEL_PRICE_CHECK_API_URL"),
            hotel_inventory_lock_api_url=_optional_env("TRAVEL_HOTEL_INVENTORY_LOCK_API_URL"),
            hotel_inventory_release_api_url=_optional_env("TRAVEL_HOTEL_INVENTORY_RELEASE_API_URL"),
            oa_approval_api_url=_optional_env("TRAVEL_OA_APPROVAL_API_URL"),
            oa_approval_status_api_url=_optional_env("TRAVEL_OA_APPROVAL_STATUS_API_URL"),
            oa_approval_cancel_api_url=_optional_env("TRAVEL_OA_APPROVAL_CANCEL_API_URL"),
            order_api_url=_optional_env("TRAVEL_ORDER_API_URL"),
            order_status_api_url=_optional_env("TRAVEL_ORDER_STATUS_API_URL"),
            order_cancel_api_url=_optional_env("TRAVEL_ORDER_CANCEL_API_URL"),
            refund_estimate_api_url=_optional_env("TRAVEL_REFUND_ESTIMATE_API_URL"),
            refund_confirm_api_url=_optional_env("TRAVEL_REFUND_CONFIRM_API_URL"),
            change_approval_api_url=_optional_env("TRAVEL_CHANGE_APPROVAL_API_URL"),
            change_failure_compensation_api_url=_optional_env("TRAVEL_CHANGE_FAILURE_COMPENSATION_API_URL"),
            hotel_change_api_url=_optional_env("TRAVEL_HOTEL_CHANGE_API_URL"),
            transport_inventory_api_url=_optional_env("TRAVEL_TRANSPORT_INVENTORY_API_URL"),
            transport_order_api_url=_optional_env("TRAVEL_TRANSPORT_ORDER_API_URL"),
            transport_order_status_api_url=_optional_env("TRAVEL_TRANSPORT_ORDER_STATUS_API_URL"),
            transport_order_cancel_api_url=_optional_env("TRAVEL_TRANSPORT_ORDER_CANCEL_API_URL"),
            transport_change_api_url=_optional_env("TRAVEL_TRANSPORT_CHANGE_API_URL"),
            notification_api_url=_optional_env("TRAVEL_NOTIFICATION_API_URL"),
            calendar_api_url=_optional_env("TRAVEL_CALENDAR_API_URL"),
            permission_api_url=_optional_env("TRAVEL_PERMISSION_API_URL"),
            audit_log_api_url=_optional_env("TRAVEL_AUDIT_LOG_API_URL"),
            alert_api_url=_optional_env("TRAVEL_ALERT_API_URL"),
            oncall_api_url=_optional_env("TRAVEL_ONCALL_API_URL"),
            oncall_status_api_url=_optional_env("TRAVEL_ONCALL_STATUS_API_URL"),
            oncall_webhook_secret=_optional_env("TRAVEL_ONCALL_WEBHOOK_SECRET"),
            closed_loop_api_url=_optional_env("TRAVEL_CLOSED_LOOP_API_URL"),
            closed_loop_schema_registry_url=_optional_env("TRAVEL_CLOSED_LOOP_SCHEMA_REGISTRY_URL"),
            recovery_approval_api_url=_optional_env("TRAVEL_RECOVERY_APPROVAL_API_URL"),
            recovery_governance_policy_json=_optional_env("TRAVEL_RECOVERY_GOVERNANCE_POLICY_JSON"),
            recovery_governance_policy_api_url=_optional_env("TRAVEL_RECOVERY_GOVERNANCE_POLICY_API_URL"),
            compensation_execution_policy_json=_optional_env("TRAVEL_COMPENSATION_EXECUTION_POLICY_JSON"),
            compensation_slo_policy_json=_optional_env("TRAVEL_COMPENSATION_SLO_POLICY_JSON"),
            compensation_remediation_policy_json=_optional_env("TRAVEL_COMPENSATION_REMEDIATION_POLICY_JSON"),
            operations_dashboard_token=_optional_env("TRAVEL_OPERATIONS_DASHBOARD_TOKEN"),
            alert_rules_json=_optional_env("TRAVEL_ALERT_RULES_JSON"),
            trend_alert_rules_json=_optional_env("TRAVEL_TREND_ALERT_RULES_JSON"),
            action_sla_policy_json=_optional_env("TRAVEL_ACTION_SLA_POLICY_JSON"),
            otlp_http_endpoint=_optional_env("TRAVEL_OTLP_HTTP_ENDPOINT"),
            policy_api_token=_optional_env("TRAVEL_POLICY_API_TOKEN"),
            transport_api_token=_optional_env("TRAVEL_TRANSPORT_API_TOKEN"),
            hotel_inventory_api_token=_optional_env("TRAVEL_HOTEL_INVENTORY_API_TOKEN"),
            oa_approval_api_token=_optional_env("TRAVEL_OA_APPROVAL_API_TOKEN"),
            order_api_token=_optional_env("TRAVEL_ORDER_API_TOKEN"),
            notification_api_token=_optional_env("TRAVEL_NOTIFICATION_API_TOKEN"),
            calendar_api_token=_optional_env("TRAVEL_CALENDAR_API_TOKEN"),
            permission_api_token=_optional_env("TRAVEL_PERMISSION_API_TOKEN"),
            audit_log_api_token=_optional_env("TRAVEL_AUDIT_LOG_API_TOKEN"),
            alert_api_token=_optional_env("TRAVEL_ALERT_API_TOKEN"),
            oncall_api_token=_optional_env("TRAVEL_ONCALL_API_TOKEN"),
            closed_loop_api_token=_optional_env("TRAVEL_CLOSED_LOOP_API_TOKEN"),
            closed_loop_schema_registry_api_token=_optional_env("TRAVEL_CLOSED_LOOP_SCHEMA_REGISTRY_API_TOKEN"),
            recovery_approval_api_token=_optional_env("TRAVEL_RECOVERY_APPROVAL_API_TOKEN"),
            recovery_governance_policy_api_token=_optional_env("TRAVEL_RECOVERY_GOVERNANCE_POLICY_API_TOKEN"),
            otlp_api_token=_optional_env("TRAVEL_OTLP_API_TOKEN"),
            use_mock_fallback=_bool_env("TRAVEL_USE_MOCK_FALLBACK", True),
            notification_use_mock_fallback=_bool_env("TRAVEL_NOTIFICATION_USE_MOCK_FALLBACK", True),
            calendar_use_mock_fallback=_bool_env("TRAVEL_CALENDAR_USE_MOCK_FALLBACK", True),
            timeout_seconds=_float_env("TRAVEL_API_TIMEOUT_SECONDS", 5.0),
            session_db_path=_optional_env("TRAVEL_SESSION_DB_PATH"),
            session_store_backend=_optional_env("TRAVEL_SESSION_STORE_BACKEND") or "auto",
            session_store_api_url=_optional_env("TRAVEL_SESSION_STORE_API_URL"),
            session_store_api_token=_optional_env("TRAVEL_SESSION_STORE_API_TOKEN"),
        )

    @classmethod
    def mock_only(cls) -> "IntegrationSettings":
        return cls()


def _optional_env(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def _bool_env(name: str, default: bool) -> bool:
    value = _optional_env(name)
    if value is None:
        return default
    normalized = value.lower()
    if normalized in TRUE_VALUES:
        return True
    if normalized in FALSE_VALUES:
        return False
    return default


def _float_env(name: str, default: float) -> float:
    value = _optional_env(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default
