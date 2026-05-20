from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable

from .agent import build_default_agent
from .config import IntegrationSettings
from .integrations import IntegrationError
from .models import TravelContext, TravelRequest
from .state import TravelState


@dataclass(frozen=True)
class EvalAssertion:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class EvalScenarioResult:
    scenario_id: str
    title: str
    status: str
    state: str
    assertions: list[EvalAssertion]
    summary: str
    source: str = "mock"


@dataclass(frozen=True)
class EvalScenario:
    scenario_id: str
    title: str
    runner: Callable[[], EvalScenarioResult]


@dataclass(frozen=True)
class EvalReport:
    scenarios: list[EvalScenarioResult]

    @property
    def passed(self) -> int:
        return sum(1 for result in self.scenarios if result.status == "PASS")

    @property
    def failed(self) -> int:
        return sum(1 for result in self.scenarios if result.status != "PASS")


def build_default_evaluation_scenarios() -> list[EvalScenario]:
    return [
        EvalScenario("happy_path", "完整下单闭环", _run_happy_path),
        EvalScenario("policy_over_cap", "政策超标", _run_policy_over_cap),
        EvalScenario("approval_rejected", "审批驳回", _run_approval_rejected),
        EvalScenario("price_changed", "价格变化二次确认", _run_price_changed),
        EvalScenario("inventory_expired", "库存失效", _run_inventory_expired),
        EvalScenario("order_failed", "订单失败恢复", _run_order_failed),
        EvalScenario("change_failure", "改签失败补偿", _run_change_failure),
        EvalScenario("calendar_dead_letter", "日历死信", _run_calendar_dead_letter),
    ]


def run_evaluation_suite() -> EvalReport:
    results = [_run_safely(scenario) for scenario in build_default_evaluation_scenarios()]
    return EvalReport(results)


def render_evaluation_report(report: EvalReport) -> str:
    lines = [
        "Evaluation report:",
        f"- passed: {report.passed}",
        f"- failed: {report.failed}",
    ]
    for result in report.scenarios:
        lines.append(
            f"- {result.scenario_id} | {result.title} | {result.status} | {result.state} | {result.summary}"
        )
        for assertion in result.assertions:
            mark = "PASS" if assertion.passed else "FAIL"
            lines.append(f"  - {mark} {assertion.name}: {assertion.detail}")
    return "\n".join(lines)


def _request() -> TravelRequest:
    return TravelRequest(
        user_id="u-demo",
        origin_city="北京",
        destination_city="上海",
        start_date=date(2026, 6, 3),
        end_date=date(2026, 6, 5),
        purpose="客户会议",
        venue="上海张江人工智能岛",
        budget_per_night=650,
        preferences=["可取消"],
    )


def _run_happy_path() -> EvalScenarioResult:
    context = build_default_agent().run_to_order(_request())
    assertions = _assertions(
        [
            ("state_completed", context.state == TravelState.COMPLETED.value, f"state={context.state}"),
            ("has_order", context.order is not None, _presence(context.order)),
            ("has_transport_order", context.transport_order is not None, _presence(context.transport_order)),
            ("approval_approved", context.approval is not None and context.approval.status == "APPROVED", _approval_detail(context)),
        ]
    )
    return _result("happy_path", "完整下单闭环", context, assertions, "mock run completed")


def _run_policy_over_cap() -> EvalScenarioResult:
    request = TravelRequest(
        user_id="u-demo",
        origin_city="北京",
        destination_city="上海",
        start_date=date(2026, 6, 3),
        end_date=date(2026, 6, 5),
        purpose="客户会议",
        venue="上海张江人工智能岛",
        budget_per_night=9999,
        preferences=["可取消"],
    )
    context = build_default_agent().plan(request)
    assertions = _assertions(
        [
            ("policy_not_compliant", context.policy_result is not None and not context.policy_result.compliant, _policy_detail(context)),
            ("hotel_budget_capped", context.policy_result is not None and context.policy_result.approved_budget <= 650, _policy_detail(context)),
        ]
    )
    return _result("policy_over_cap", "政策超标", context, assertions, "policy cap enforced")


def _run_approval_rejected() -> EvalScenarioResult:
    agent = build_default_agent(
        settings=_scenario_settings(
            oa_approval_api_url="https://oa.example/create",
            oa_approval_status_api_url="https://oa.example/status",
        ),
        http_client=_approval_rejected_http(),
    )
    context = agent.run_to_approval(_request())
    context = agent.refresh_approval_status(context)
    assertions = _assertions(
        [
            ("state_rejected", context.state == TravelState.APPROVAL_REJECTED.value, f"state={context.state}"),
            ("approval_rejected", context.approval is not None and context.approval.status == "REJECTED", _approval_detail(context)),
        ]
    )
    return _result("approval_rejected", "审批驳回", context, assertions, "mock approval rejected")


def _run_price_changed() -> EvalScenarioResult:
    agent = build_default_agent(
        settings=_scenario_settings(hotel_price_check_api_url="https://hotel.example/price"),
        http_client=_price_changed_http(),
    )
    context = agent.run_to_order(_request())
    assertions = _assertions(
        [
            ("state_price_changed", context.state == TravelState.PRICE_CHANGED.value, f"state={context.state}"),
            ("price_requires_confirmation", context.price_check is not None and context.price_check.requires_confirmation, _price_detail(context)),
        ]
    )
    return _result("price_changed", "价格变化二次确认", context, assertions, "price confirmation required")


def _run_inventory_expired() -> EvalScenarioResult:
    agent = build_default_agent(
        settings=_scenario_settings(hotel_price_check_api_url="https://hotel.example/price"),
        http_client=_inventory_expired_http(),
    )
    context = agent.run_to_order(_request())
    assertions = _assertions(
        [
            ("state_inventory_expired", context.state == TravelState.INVENTORY_EXPIRED.value, f"state={context.state}"),
            ("inventory_lock_exists", context.inventory_lock is not None, _inventory_detail(context)),
        ]
    )
    return _result("inventory_expired", "库存失效", context, assertions, "inventory expired before order")


def _run_order_failed() -> EvalScenarioResult:
    agent = build_default_agent(
        settings=_scenario_settings(
            order_api_url="https://order.example/create",
            order_cancel_api_url="https://order.example/cancel",
            hotel_inventory_release_api_url="https://hotel.example/release",
            oa_approval_cancel_api_url="https://oa.example/cancel",
        ),
        http_client=_order_failed_http(),
    )
    context = agent.run_to_order(_request())
    context = agent.replan_after_exception(context, reason="order_failed_replan")
    assertions = _assertions(
        [
            ("state_plan_generated", context.state == TravelState.PLAN_GENERATED.value, f"state={context.state}"),
            ("has_recovery_record", bool(context.recovery_records), f"recovery_records={len(context.recovery_records)}"),
        ]
    )
    return _result("order_failed", "订单失败恢复", context, assertions, "recovery replanned")


def _run_change_failure() -> EvalScenarioResult:
    agent = build_default_agent(
        settings=_scenario_settings(
            refund_estimate_api_url="https://refund.example/estimate",
            refund_confirm_api_url="https://refund.example/confirm",
            change_approval_api_url="https://oa.example/change",
            transport_change_api_url="https://transport.example/change",
            hotel_change_api_url="https://hotel.example/change",
            change_failure_compensation_api_url="https://change.example/compensate",
        ),
        http_client=_change_failure_http(),
    )
    context = agent.change_trip(
        agent.run_to_order(_request()),
        new_depart_at="2026-06-03T13:00:00+08:00",
        new_check_in=date(2026, 6, 4),
        new_check_out=date(2026, 6, 6),
        reason="meeting_rescheduled",
    )
    assertions = _assertions(
        [
            ("change_failed", context.change_records and context.change_records[0].status == "FAILED", _change_detail(context)),
            ("failure_compensation_recorded", bool(context.change_failure_compensations), f"compensations={len(context.change_failure_compensations)}"),
        ]
    )
    return _result("change_failure", "改签失败补偿", context, assertions, "supplier change failed and was compensated")


def _run_calendar_dead_letter() -> EvalScenarioResult:
    agent = build_default_agent(
        settings=_scenario_settings(calendar_api_url="https://calendar.example/sync", calendar_use_mock_fallback=False),
        http_client=_calendar_dead_letter_http(),
    )
    context = agent.sync_calendar(agent.run_to_order(_request()))
    assertions = _assertions(
        [
            ("calendar_dead_letter", context.calendar_syncs[-1].status == "DEAD_LETTER", _calendar_detail(context)),
            ("retry_count_positive", context.calendar_syncs[-1].retry_count >= 1, _calendar_detail(context)),
        ]
    )
    return _result("calendar_dead_letter", "日历死信", context, assertions, "calendar sync dead letter captured")


def _run_safely(scenario: EvalScenario) -> EvalScenarioResult:
    try:
        return scenario.runner()
    except Exception as exc:
        return EvalScenarioResult(
            scenario_id=scenario.scenario_id,
            title=scenario.title,
            status="FAIL",
            state="ERROR",
            assertions=[EvalAssertion(name="exception", passed=False, detail=str(exc))],
            summary="scenario raised exception",
            source="mock",
        )


def _result(
    scenario_id: str,
    title: str,
    context: TravelContext,
    assertions: list[EvalAssertion],
    summary: str,
) -> EvalScenarioResult:
    status = "PASS" if all(item.passed for item in assertions) else "FAIL"
    return EvalScenarioResult(
        scenario_id=scenario_id,
        title=title,
        status=status,
        state=context.state,
        assertions=assertions,
        summary=summary,
    )


def _assertions(items: list[tuple[str, bool, str]]) -> list[EvalAssertion]:
    return [EvalAssertion(name=name, passed=passed, detail=detail) for name, passed, detail in items]


def _presence(value: object) -> str:
    return "present" if value is not None else "missing"


def _approval_detail(context: TravelContext) -> str:
    return f"approval={context.approval.approval_id if context.approval else '-'} status={context.approval.status if context.approval else '-'}"


def _policy_detail(context: TravelContext) -> str:
    policy = context.policy_result
    return f"budget={policy.approved_budget if policy else '-'} compliant={policy.compliant if policy else '-'}"


def _price_detail(context: TravelContext) -> str:
    price_check = context.price_check
    return f"status={price_check.status if price_check else '-'} current={price_check.current_price if price_check else '-'} requires_confirmation={price_check.requires_confirmation if price_check else '-'}"


def _inventory_detail(context: TravelContext) -> str:
    lock = context.inventory_lock
    return f"lock={lock.lock_id if lock else '-'} status={lock.status if lock else '-'}"


def _change_detail(context: TravelContext) -> str:
    if not context.change_records:
        return "no change records"
    record = context.change_records[0]
    return f"change={record.change_id} status={record.status} target={record.target_type}"


def _calendar_detail(context: TravelContext) -> str:
    record = context.calendar_syncs[-1]
    return f"event={record.event_type} status={record.status} retry={record.retry_count}/{record.max_retries}"


def _scenario_settings(**overrides: Any) -> IntegrationSettings:
    values: dict[str, Any] = {
        "use_mock_fallback": True,
        "notification_use_mock_fallback": True,
        "calendar_use_mock_fallback": True,
    }
    values.update(overrides)
    return IntegrationSettings(**values)


def _approval_rejected_http() -> _StubHttpClient:
    return _StubHttpClient(
        {
            "https://oa.example/create": {
                "approval": {
                    "approval_id": "APP-1",
                    "status": "PENDING_APPROVAL",
                }
            },
            "https://oa.example/status": {
                "approval": {
                    "approval_id": "APP-1",
                    "status": "REJECTED",
                }
            },
        }
    )


def _price_changed_http() -> _StubHttpClient:
    responses = _base_responses()
    responses["https://hotel.example/price"] = {
        "price_check": {
            "hotel_id": "REMOTE-HOTEL-1",
            "status": "PRICE_CHANGED",
            "original_price": 660,
            "current_price": 700,
            "policy_compliant": True,
            "requires_confirmation": True,
        }
    }
    return _StubHttpClient(responses)


def _inventory_expired_http() -> _StubHttpClient:
    responses = _base_responses()
    responses["https://hotel.example/price"] = {
        "price_check": {
            "hotel_id": "REMOTE-HOTEL-1",
            "status": "SOLD_OUT",
            "original_price": 660,
            "current_price": None,
            "policy_compliant": False,
            "requires_confirmation": False,
        }
    }
    return _StubHttpClient(responses)


def _order_failed_http() -> _StubHttpClient:
    responses = _base_responses()
    responses["https://order.example/create"] = {
        "order": {
            "order_id": "REMOTE-ORDER-1",
            "status": "FAILED",
            "total_amount": 1320,
            "currency": "CNY",
        }
    }
    responses["https://order.example/cancel"] = {
        "compensation": {
            "action": "cancel_order",
            "target_id": "REMOTE-ORDER-1",
            "status": "CANCELLED",
        }
    }
    responses["https://hotel.example/release"] = {
        "compensation": {
            "action": "release_hotel_inventory",
            "target_id": "REMOTE-LOCK-1",
            "status": "RELEASED",
        }
    }
    responses["https://oa.example/cancel"] = {
        "compensation": {
            "action": "cancel_approval",
            "target_id": "REMOTE-APPROVAL-1",
            "status": "CANCELLED",
        }
    }
    return _StubHttpClient(responses)


def _change_failure_http() -> _StubHttpClient:
    responses = _base_responses()
    responses["https://transport.example/change"] = {
        "change": {
            "change_id": "REMOTE-TCHG-FAILED",
            "target_type": "transport",
            "target_id": "REMOTE-TRANSPORT-ORDER-1",
            "status": "FAILED",
            "penalty_amount": 0,
            "currency": "CNY",
        }
    }
    responses["https://change.example/compensate"] = {
        "compensation": {
            "action": "compensate_change_failure",
            "target_id": "transport:REMOTE-TRANSPORT-ORDER-1",
            "status": "DONE",
        }
    }
    return _StubHttpClient(responses)


def _calendar_dead_letter_http() -> _StubHttpClient:
    return _StubHttpClient(_base_responses())


def _base_responses() -> dict[str, dict[str, Any]]:
    return {
        "https://policy.example/check": {
            "policy": {
                "policy_id": "REMOTE-POLICY-1",
                "max_hotel_price": 700,
                "approved_budget": 680,
                "compliant": True,
                "reasons": ["remote policy ok"],
            }
        },
        "https://hotel.example/search": {
            "hotels": [
                {
                    "hotel_id": "REMOTE-HOTEL-1",
                    "name": "Remote Hotel",
                    "city": "上海",
                    "address": "Remote Road",
                    "nightly_price": 660,
                    "distance_km": 0.6,
                    "rating": 4.9,
                    "refundable": True,
                }
            ]
        },
        "https://transport.example/policy": {
            "transport_policy": {
                "policy_id": "REMOTE-TRANSPORT-POLICY-1",
                "allowed_seat_classes": ["经济舱", "二等座"],
                "max_transport_price": 1600,
                "compliant": True,
            }
        },
        "https://transport.example/search": {
            "transports": [
                {
                    "transport_id": "REMOTE-TRANSPORT-1",
                    "mode": "flight",
                    "provider": "Remote Air",
                    "origin_city": "北京",
                    "destination_city": "上海",
                    "depart_at": "2026-06-03T09:00:00+08:00",
                    "arrive_at": "2026-06-03T11:20:00+08:00",
                    "seat_class": "经济舱",
                    "price": 980,
                    "refundable": True,
                }
            ]
        },
        "https://oa.example/create": {
            "approval": {
                "approval_id": "REMOTE-APPROVAL-1",
                "status": "PENDING_APPROVAL",
            }
        },
        "https://oa.example/status": {
            "approval": {
                "approval_id": "REMOTE-APPROVAL-1",
                "status": "APPROVED",
            }
        },
        "https://hotel.example/lock": {
            "inventory_lock": {
                "lock_id": "REMOTE-LOCK-1",
                "status": "LOCKED",
                "hotel_id": "REMOTE-HOTEL-1",
                "expires_at": "2026-06-03T10:00:00Z",
            }
        },
        "https://hotel.example/price": {
            "price_check": {
                "hotel_id": "REMOTE-HOTEL-1",
                "status": "UNCHANGED",
                "original_price": 660,
                "current_price": 660,
                "policy_compliant": True,
                "requires_confirmation": False,
            }
        },
        "https://transport.example/order": {
            "transport_order": {
                "order_id": "REMOTE-TRANSPORT-ORDER-1",
                "status": "CREATED",
                "total_amount": 980,
                "currency": "CNY",
            }
        },
        "https://order.example/create": {
            "order": {
                "order_id": "REMOTE-ORDER-1",
                "status": "CREATED",
                "total_amount": 1320,
                "currency": "CNY",
            }
        },
        "https://refund.example/estimate": {
            "refund_estimate": {
                "estimate_id": "REMOTE-RFD-1",
                "target_type": "hotel",
                "target_id": "REMOTE-ORDER-1",
                "refundable_amount": 1000,
                "penalty_amount": 320,
                "currency": "CNY",
                "rules": ["remote refund rule"],
            }
        },
        "https://refund.example/confirm": {
            "refund_confirmation": {
                "confirmation_id": "REMOTE-RFC-1",
                "estimate_id": "REMOTE-RFD-1",
                "target_type": "hotel",
                "target_id": "REMOTE-ORDER-1",
                "status": "CONFIRMED",
                "confirmed_amount": 1000,
                "currency": "CNY",
            }
        },
        "https://oa.example/change": {
            "approval": {
                "approval_id": "REMOTE-CHANGE-APPROVAL-1",
                "status": "APPROVED",
            }
        },
        "https://transport.example/change": {
            "change": {
                "change_id": "REMOTE-TCHG-1",
                "target_type": "transport",
                "target_id": "REMOTE-TRANSPORT-ORDER-1",
                "status": "CHANGED",
                "penalty_amount": 120,
                "currency": "CNY",
            }
        },
        "https://hotel.example/change": {
            "change": {
                "change_id": "REMOTE-HCHG-1",
                "target_type": "hotel",
                "target_id": "REMOTE-ORDER-1",
                "status": "CHANGED",
                "penalty_amount": 80,
                "currency": "CNY",
            }
        },
        "https://change.example/compensate": {
            "compensation": {
                "action": "compensate_change_failure",
                "target_id": "transport:REMOTE-TRANSPORT-ORDER-1",
                "status": "DONE",
            }
        },
        "https://calendar.example/sync": {
            "calendar": {
                "calendar_event_id": "REMOTE-CALENDAR-1",
                "event_type": "TRIP_BOOKED",
                "status": "SYNCED",
                "user_id": "u-demo",
                "title": "remote calendar",
                "start_at": "2026-06-03",
                "end_at": "2026-06-05",
                "attendees": ["u-demo"],
            }
        },
    }


class _StubHttpClient:
    def __init__(self, responses: dict[str, dict[str, Any]]) -> None:
        self.responses = responses

    def post_json(self, url: str, payload: dict[str, Any], token: str | None = None) -> dict[str, Any]:
        del payload, token
        if url == "https://calendar.example/sync":
            return {
                "calendar": {
                    "calendar_event_id": "REMOTE-CALENDAR-FAILED",
                    "event_type": "TRIP_BOOKED",
                    "status": "DEAD_LETTER",
                    "user_id": "u-demo",
                    "title": "calendar failed",
                    "start_at": "2026-06-03",
                    "end_at": "2026-06-05",
                    "attendees": ["u-demo"],
                    "retry_count": 3,
                    "max_retries": 3,
                    "last_error": "calendar unavailable",
                }
            }
        return self.responses[url]
