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
    hotel_change_api_url: str | None = None
    transport_inventory_api_url: str | None = None
    transport_order_api_url: str | None = None
    transport_order_status_api_url: str | None = None
    transport_order_cancel_api_url: str | None = None
    transport_change_api_url: str | None = None
    notification_api_url: str | None = None
    calendar_api_url: str | None = None
    policy_api_token: str | None = None
    transport_api_token: str | None = None
    hotel_inventory_api_token: str | None = None
    oa_approval_api_token: str | None = None
    order_api_token: str | None = None
    notification_api_token: str | None = None
    calendar_api_token: str | None = None
    use_mock_fallback: bool = True
    notification_use_mock_fallback: bool = True
    timeout_seconds: float = 5.0
    session_db_path: str | None = None

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
            hotel_change_api_url=_optional_env("TRAVEL_HOTEL_CHANGE_API_URL"),
            transport_inventory_api_url=_optional_env("TRAVEL_TRANSPORT_INVENTORY_API_URL"),
            transport_order_api_url=_optional_env("TRAVEL_TRANSPORT_ORDER_API_URL"),
            transport_order_status_api_url=_optional_env("TRAVEL_TRANSPORT_ORDER_STATUS_API_URL"),
            transport_order_cancel_api_url=_optional_env("TRAVEL_TRANSPORT_ORDER_CANCEL_API_URL"),
            transport_change_api_url=_optional_env("TRAVEL_TRANSPORT_CHANGE_API_URL"),
            notification_api_url=_optional_env("TRAVEL_NOTIFICATION_API_URL"),
            calendar_api_url=_optional_env("TRAVEL_CALENDAR_API_URL"),
            policy_api_token=_optional_env("TRAVEL_POLICY_API_TOKEN"),
            transport_api_token=_optional_env("TRAVEL_TRANSPORT_API_TOKEN"),
            hotel_inventory_api_token=_optional_env("TRAVEL_HOTEL_INVENTORY_API_TOKEN"),
            oa_approval_api_token=_optional_env("TRAVEL_OA_APPROVAL_API_TOKEN"),
            order_api_token=_optional_env("TRAVEL_ORDER_API_TOKEN"),
            notification_api_token=_optional_env("TRAVEL_NOTIFICATION_API_TOKEN"),
            calendar_api_token=_optional_env("TRAVEL_CALENDAR_API_TOKEN"),
            use_mock_fallback=_bool_env("TRAVEL_USE_MOCK_FALLBACK", True),
            notification_use_mock_fallback=_bool_env("TRAVEL_NOTIFICATION_USE_MOCK_FALLBACK", True),
            timeout_seconds=_float_env("TRAVEL_API_TIMEOUT_SECONDS", 5.0),
            session_db_path=_optional_env("TRAVEL_SESSION_DB_PATH"),
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
