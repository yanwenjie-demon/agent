from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from .config import IntegrationSettings
from .integrations import HttpJsonClient


@dataclass(frozen=True)
class SmokeProbeResult:
    system: str
    url: str
    status: str
    detail: str


@dataclass(frozen=True)
class SmokeProbeReport:
    results: list[SmokeProbeResult]

    @property
    def passed(self) -> int:
        return sum(1 for result in self.results if result.status == "PASS")

    @property
    def failed(self) -> int:
        return sum(1 for result in self.results if result.status == "FAIL")

    @property
    def skipped(self) -> int:
        return sum(1 for result in self.results if result.status == "SKIP")

    @property
    def status(self) -> str:
        if self.failed:
            return "FAIL"
        if self.skipped:
            return "SKIP" if self.passed == 0 else "ACTION_REQUIRED"
        if self.passed:
            return "PASS"
        return "SKIP"


@dataclass(frozen=True)
class SmokeProbe:
    system: str
    url: str | None
    token: str | None
    expected_keys: tuple[str, ...]
    payload: dict[str, Any]


def run_smoke_probes(
    settings: IntegrationSettings,
    http_client: HttpJsonClient,
    include_optional: bool = True,
) -> SmokeProbeReport:
    results = [_run_probe(probe, http_client) for probe in build_smoke_probes(settings, include_optional)]
    return SmokeProbeReport(results)


def build_smoke_probes(settings: IntegrationSettings, include_optional: bool = True) -> list[SmokeProbe]:
    probes = [
        SmokeProbe(
            "policy",
            settings.policy_api_url,
            settings.policy_api_token,
            ("policy", "data"),
            _base_payload("policy") | {
                "user_id": "u-smoke",
                "destination_city": "上海",
                "budget_per_night": 650,
            },
        ),
        SmokeProbe(
            "transport_policy",
            settings.transport_policy_api_url,
            settings.transport_api_token,
            ("transport_policy", "data"),
            _base_payload("transport_policy") | _route_payload(),
        ),
        SmokeProbe(
            "hotel_inventory",
            settings.hotel_inventory_api_url,
            settings.hotel_inventory_api_token,
            ("hotels", "data"),
            _base_payload("hotel_inventory") | {
                "city": "上海",
                "check_in": "2026-06-03",
                "check_out": "2026-06-05",
                "venue": "上海张江人工智能岛",
                "max_price": 650,
                "preferences": ["可取消"],
            },
        ),
        SmokeProbe(
            "transport_inventory",
            settings.transport_inventory_api_url,
            settings.transport_api_token,
            ("transports", "data"),
            _base_payload("transport_inventory") | _route_payload() | {"max_price": 1600},
        ),
        SmokeProbe(
            "hotel_price_check",
            settings.hotel_price_check_api_url,
            settings.hotel_inventory_api_token,
            ("price_check", "data"),
            _base_payload("hotel_price_check") | _hotel_payload(),
        ),
        SmokeProbe(
            "hotel_inventory_lock",
            settings.hotel_inventory_lock_api_url,
            settings.hotel_inventory_api_token,
            ("inventory_lock", "data"),
            _base_payload("hotel_inventory_lock") | _hotel_payload(),
        ),
        SmokeProbe(
            "hotel_inventory_release",
            settings.hotel_inventory_release_api_url,
            settings.hotel_inventory_api_token,
            ("compensation", "data"),
            _base_payload("hotel_inventory_release") | {"lock_id": "SMOKE-LOCK", "reason": "smoke_test"},
        ),
        SmokeProbe(
            "oa_approval",
            settings.oa_approval_api_url,
            settings.oa_approval_api_token,
            ("approval", "data"),
            _base_payload("oa_approval") | _approval_payload(),
        ),
        SmokeProbe(
            "oa_approval_status",
            settings.oa_approval_status_api_url,
            settings.oa_approval_api_token,
            ("approval", "data"),
            _base_payload("oa_approval_status") | {"approval_id": "SMOKE-APPROVAL", "user_id": "u-smoke"},
        ),
        SmokeProbe(
            "oa_approval_cancel",
            settings.oa_approval_cancel_api_url,
            settings.oa_approval_api_token,
            ("compensation", "data"),
            _base_payload("oa_approval_cancel") | {"approval_id": "SMOKE-APPROVAL", "user_id": "u-smoke", "reason": "smoke_test"},
        ),
        SmokeProbe(
            "order",
            settings.order_api_url,
            settings.order_api_token,
            ("order", "data"),
            _base_payload("order") | _order_payload(),
        ),
        SmokeProbe(
            "order_status",
            settings.order_status_api_url,
            settings.order_api_token,
            ("order", "data"),
            _base_payload("order_status") | {"order_id": "SMOKE-ORDER", "user_id": "u-smoke"},
        ),
        SmokeProbe(
            "order_cancel",
            settings.order_cancel_api_url,
            settings.order_api_token,
            ("compensation", "data"),
            _base_payload("order_cancel") | {"order_id": "SMOKE-ORDER", "user_id": "u-smoke", "reason": "smoke_test"},
        ),
        SmokeProbe(
            "transport_order",
            settings.transport_order_api_url,
            settings.transport_api_token,
            ("transport_order", "data"),
            _base_payload("transport_order") | _transport_order_payload(),
        ),
        SmokeProbe(
            "transport_order_status",
            settings.transport_order_status_api_url,
            settings.transport_api_token,
            ("transport_order", "data"),
            _base_payload("transport_order_status") | {"order_id": "SMOKE-TRANSPORT-ORDER", "user_id": "u-smoke"},
        ),
        SmokeProbe(
            "transport_order_cancel",
            settings.transport_order_cancel_api_url,
            settings.transport_api_token,
            ("compensation", "data"),
            _base_payload("transport_order_cancel") | {
                "order_id": "SMOKE-TRANSPORT-ORDER",
                "user_id": "u-smoke",
                "reason": "smoke_test",
            },
        ),
        SmokeProbe(
            "refund_estimate",
            settings.refund_estimate_api_url,
            settings.order_api_token,
            ("refund_estimate", "data"),
            _base_payload("refund_estimate") | _refund_payload(),
        ),
        SmokeProbe(
            "refund_confirm",
            settings.refund_confirm_api_url,
            settings.order_api_token,
            ("refund_confirmation", "data"),
            _base_payload("refund_confirm") | _refund_payload() | {"estimate_id": "SMOKE-REFUND"},
        ),
        SmokeProbe(
            "change_approval",
            settings.change_approval_api_url,
            settings.oa_approval_api_token,
            ("approval", "data"),
            _base_payload("change_approval") | _approval_payload() | {"change_request": {"reason": "smoke_test"}},
        ),
        SmokeProbe(
            "hotel_change",
            settings.hotel_change_api_url,
            settings.order_api_token,
            ("change", "data"),
            _base_payload("hotel_change") | {
                "order_id": "SMOKE-ORDER",
                "user_id": "u-smoke",
                "new_check_in": "2026-06-04",
                "new_check_out": "2026-06-06",
                "reason": "smoke_test",
            },
        ),
        SmokeProbe(
            "transport_change",
            settings.transport_change_api_url,
            settings.transport_api_token,
            ("change", "data"),
            _base_payload("transport_change") | {
                "order_id": "SMOKE-TRANSPORT-ORDER",
                "user_id": "u-smoke",
                "new_depart_at": "2026-06-03T13:00:00+08:00",
                "reason": "smoke_test",
            },
        ),
        SmokeProbe(
            "change_failure_compensation",
            settings.change_failure_compensation_api_url,
            settings.order_api_token,
            ("compensation", "data"),
            _base_payload("change_failure_compensation") | {
                "session_id": "SMOKE-SESSION",
                "user_id": "u-smoke",
                "failed_target_type": "transport",
                "failed_target_id": "SMOKE-TRANSPORT-ORDER",
                "reason": "smoke_test",
                "completed_changes": [],
            },
        ),
        SmokeProbe(
            "notification",
            settings.notification_api_url,
            settings.notification_api_token,
            ("notification", "data"),
            _base_payload("notification") | {
                "session_id": "SMOKE-SESSION",
                "user_id": "u-smoke",
                "event_type": "SMOKE_TEST",
                "title": "smoke test",
                "message": "smoke test",
                "channel": "im",
                "payload": {},
            },
        ),
        SmokeProbe(
            "calendar",
            settings.calendar_api_url,
            settings.calendar_api_token,
            ("calendar", "data"),
            _base_payload("calendar") | {
                "session_id": "SMOKE-SESSION",
                "user_id": "u-smoke",
                "event_type": "SMOKE_TEST",
                "title": "smoke test",
                "start_at": "2026-06-03",
                "end_at": "2026-06-05",
                "attendees": ["u-smoke"],
                "payload": {},
            },
        ),
    ]
    if include_optional:
        probes.append(
            SmokeProbe(
                "session_store_http",
                _join_url(settings.session_store_api_url, "/health"),
                settings.session_store_api_token,
                ("ok", "backend"),
                _base_payload("session_store_http"),
            )
        )
    return probes


def render_smoke_probe_report(report: SmokeProbeReport) -> str:
    lines = [
        "Smoke probe report:",
        f"- status: {report.status}",
        f"- passed: {report.passed}",
        f"- failed: {report.failed}",
        f"- skipped: {report.skipped}",
    ]
    for result in report.results:
        lines.append(f"- {result.status} {result.system}: {result.detail}")
    return "\n".join(lines)


def _run_probe(probe: SmokeProbe, http_client: HttpJsonClient) -> SmokeProbeResult:
    if not probe.url:
        return SmokeProbeResult(probe.system, "", "SKIP", "endpoint not configured")
    try:
        response = http_client.post_json(probe.url, probe.payload, probe.token)
    except Exception as exc:
        return SmokeProbeResult(probe.system, probe.url, "FAIL", str(exc))
    if not any(key in response for key in probe.expected_keys):
        return SmokeProbeResult(
            probe.system,
            probe.url,
            "FAIL",
            f"missing expected response keys: {', '.join(probe.expected_keys)}",
        )
    return SmokeProbeResult(probe.system, probe.url, "PASS", "response contract matched")


def _base_payload(system: str) -> dict[str, Any]:
    return {
        "smoke_test": True,
        "dry_run": True,
        "system": system,
        "idempotency_key": f"travel-agent-smoke:{system}",
    }


def _route_payload() -> dict[str, Any]:
    return {
        "user_id": "u-smoke",
        "origin_city": "北京",
        "destination_city": "上海",
        "travel_date": date(2026, 6, 3).isoformat(),
    }


def _hotel_payload() -> dict[str, Any]:
    return {
        "session_id": "SMOKE-SESSION",
        "user_id": "u-smoke",
        "hotel_id": "SMOKE-HOTEL",
        "selected_hotel": {
            "hotel_id": "SMOKE-HOTEL",
            "name": "Smoke Hotel",
            "city": "上海",
            "nightly_price": 650,
        },
        "check_in": "2026-06-03",
        "check_out": "2026-06-05",
    }


def _approval_payload() -> dict[str, Any]:
    return {
        "session_id": "SMOKE-SESSION",
        "user_id": "u-smoke",
        "request": {"origin_city": "北京", "destination_city": "上海"},
        "policy": {"approved_budget": 650, "compliant": True},
        "transport_policy": {"max_transport_price": 1600, "compliant": True},
        "itinerary": {"summary": "smoke test"},
        "selected_hotel": {"hotel_id": "SMOKE-HOTEL", "nightly_price": 650},
        "selected_transport": {"transport_id": "SMOKE-TRANSPORT", "price": 553},
        "workflow_generation": 1,
    }


def _order_payload() -> dict[str, Any]:
    return _approval_payload() | {
        "approval": {"approval_id": "SMOKE-APPROVAL", "status": "APPROVED"},
        "inventory_lock": {"lock_id": "SMOKE-LOCK", "status": "LOCKED"},
    }


def _transport_order_payload() -> dict[str, Any]:
    return {
        "session_id": "SMOKE-SESSION",
        "user_id": "u-smoke",
        "approval": {"approval_id": "SMOKE-APPROVAL", "status": "APPROVED"},
        "selected_transport": {"transport_id": "SMOKE-TRANSPORT", "price": 553},
    }


def _refund_payload() -> dict[str, Any]:
    return {
        "session_id": "SMOKE-SESSION",
        "user_id": "u-smoke",
        "target_type": "hotel",
        "target_id": "SMOKE-ORDER",
        "reason": "smoke_test",
    }


def _join_url(base_url: str | None, path: str) -> str | None:
    if not base_url:
        return None
    return f"{base_url.rstrip('/')}{path}"
