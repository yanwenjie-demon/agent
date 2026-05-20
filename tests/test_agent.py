from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from typing import Any
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from travel_agent.agent import build_default_agent, build_session_store
from travel_agent.acceptance import render_integration_acceptance_report, run_integration_acceptance_report
from travel_agent.cli import (
    create_metrics_server,
    render_calendar_dead_letters,
    render_context,
    render_dead_letters,
    render_metrics,
    render_otlp_export_result,
    render_prometheus_metrics,
    render_storage_health,
    render_worker_runs,
    run_metrics_server_in_thread,
)
from travel_agent.config import IntegrationSettings
from travel_agent.evaluation import render_evaluation_report, run_evaluation_suite
from travel_agent.domain_agents import ApprovalAgent, BookingAgent, HotelAgent, PolicyAgent, TransportAgent
from travel_agent.governance import render_release_readiness_report, run_release_readiness_report
from travel_agent.integrations import IntegrationError
from travel_agent.data_governance import HttpAuditSink, build_audit_event, redact_payload
from travel_agent.permissions import PermissionDeniedError, PermissionPolicy, evaluate_permission, render_permission_decision
from travel_agent.models import (
    CalendarSyncRecord,
    DeadLetterCalendarSync,
    DeadLetterNotification,
    NotificationRecord,
    TravelRequest,
    WorkerRunRecord,
)
from travel_agent.observability import build_otlp_payloads, build_sla_alerts, export_otlp_http
from travel_agent.operations import (
    build_alert_route_rules,
    build_operations_alerts,
    build_operations_dashboard,
    build_operations_dashboard_snapshot,
    build_operations_action_sla_policy,
    build_operations_closed_loop_report,
    build_operations_dashboard_trend_report,
    build_operations_knowledge_entries,
    build_operations_drill_report,
    build_operations_multidimensional_view,
    build_operations_postmortem_report,
    build_operations_trend_alert_rules,
    build_postmortem_action_items,
    build_trend_alert_action_items,
    close_operations_action_item,
    evaluate_operations_action_sla,
    build_operations_runbook,
    evaluate_operations_drill_gate,
    evaluate_operations_trend_alerts,
    export_operations_alerts_http,
    fetch_oncall_ticket_status_http,
    open_oncall_ticket_http,
    oncall_ticket_status_from_dict,
    oncall_ticket_status_to_dict,
    operations_action_item_from_dict,
    operations_action_item_to_dict,
    operations_dashboard_snapshot_from_dict,
    operations_dashboard_snapshot_to_dict,
    operations_knowledge_entry_from_dict,
    operations_knowledge_entry_to_dict,
    operations_trend_alert_from_dict,
    operations_trend_alert_to_dict,
    render_alert_route_rules,
    render_alert_route_rules_json,
    render_operations_action_items,
    render_operations_action_sla_report,
    render_operations_closed_loop_report,
    render_oncall_ticket_status,
    render_oncall_ticket_result,
    render_operations_alert_export_result,
    render_operations_alerts,
    render_operations_alerts_json,
    render_operations_alerts_prometheus,
    render_operations_dashboard,
    render_operations_dashboard_snapshots,
    render_operations_dashboard_trend_report,
    render_operations_knowledge_entries,
    render_operations_knowledge_search_report,
    render_operations_drill_gate_result,
    render_operations_drill_report,
    render_operations_multidimensional_view,
    render_operations_postmortem_report,
    render_operations_trend_alerts,
    render_operations_trend_alerts_json,
    render_operations_runbook,
    search_operations_knowledge,
)
from travel_agent.release_gate import evaluate_release_gate, render_release_gate_result
from travel_agent.release_control import RolloutPolicy, evaluate_rollout
from travel_agent.smoke import render_smoke_probe_report, run_smoke_probes
from travel_agent.state import TravelState
from travel_agent.storage import (
    HttpSessionStore,
    InMemorySessionStore,
    SQLiteSessionStore,
    StoreConcurrencyError,
    StorageHealth,
)
from travel_agent.tools import ToolGateway, ToolValidationError
from travel_agent.worker import WorkflowWorker


class TravelAgentFlowTest(unittest.TestCase):
    def test_plan_stops_before_confirmation(self) -> None:
        agent = build_default_agent()
        context = agent.plan(_request())

        self.assertEqual(context.state, TravelState.PLAN_GENERATED.value)
        self.assertIsNotNone(context.policy_result)
        self.assertIsNotNone(context.transport_policy_result)
        self.assertIsNotNone(context.itinerary)
        self.assertGreater(len(context.hotel_options), 0)
        self.assertGreater(len(context.transport_options), 0)
        self.assertIsNone(context.approval)

    def test_run_to_approval_creates_draft(self) -> None:
        agent = build_default_agent()
        context = agent.run_to_approval(_request())

        self.assertEqual(context.state, TravelState.APPROVAL_CREATED.value)
        self.assertIsNotNone(context.selected_hotel)
        self.assertIsNotNone(context.selected_transport)
        self.assertIsNotNone(context.approval)
        self.assertEqual(context.approval.status, "PENDING_APPROVAL")
        self.assertTrue(context.approval.approval_id.startswith("APP-"))
        self.assertEqual(context.approval.payload["selected_transport"]["transport_id"], context.selected_transport.transport_id)

    def test_run_to_order_completes_mock_flow(self) -> None:
        agent = build_default_agent()
        context = agent.run_to_order(_request())

        self.assertEqual(context.state, TravelState.COMPLETED.value)
        self.assertEqual(context.approval.status, "APPROVED")
        self.assertIsNotNone(context.inventory_lock)
        self.assertIsNotNone(context.transport_order)
        self.assertIsNotNone(context.order)
        self.assertEqual(context.inventory_lock.status, "LOCKED")
        self.assertEqual(context.transport_order.status, "CREATED")
        self.assertEqual(context.order.status, "CREATED")
        self.assertEqual(context.transport_order.total_amount, context.selected_transport.price)
        self.assertEqual(context.order.total_amount, 1240)

    def test_refresh_order_status_updates_order(self) -> None:
        agent = build_default_agent()
        context = agent.run_to_order(_request())
        context = agent.refresh_order_status(context)

        self.assertEqual(context.order.status, "CONFIRMED")
        self.assertEqual(context.transport_order.status, "CONFIRMED")
        self.assertEqual(context.order.total_amount, 1240)

    def test_cancel_trip_compensates_order_and_inventory(self) -> None:
        agent = build_default_agent()
        context = agent.run_to_order(_request())
        context = agent.cancel_trip(context, "meeting_cancelled")

        self.assertEqual(context.state, TravelState.USER_CANCELLED.value)
        self.assertIsNotNone(context.order_cancellation)
        self.assertIsNotNone(context.transport_order_cancellation)
        self.assertIsNotNone(context.inventory_release)
        self.assertEqual(context.order_cancellation.status, "CANCELLED")
        self.assertEqual(context.transport_order_cancellation.status, "CANCELLED")
        self.assertEqual(context.inventory_release.status, "RELEASED")

    def test_estimates_refund_before_cancellation(self) -> None:
        agent = build_default_agent()
        context = agent.estimate_cancellation_refund(agent.run_to_order(_request()), "meeting_cancelled")

        self.assertEqual(len(context.refund_estimates), 2)
        self.assertEqual({estimate.target_type for estimate in context.refund_estimates}, {"hotel", "transport"})
        self.assertTrue(all(estimate.refundable_amount > 0 for estimate in context.refund_estimates))

    def test_change_trip_records_transport_and_hotel_changes(self) -> None:
        agent = build_default_agent()
        context = agent.change_trip(
            agent.run_to_order(_request()),
            new_depart_at="2026-06-03T13:00:00+08:00",
            new_check_in=date(2026, 6, 4),
            new_check_out=date(2026, 6, 6),
            reason="meeting_rescheduled",
        )

        self.assertEqual(len(context.change_records), 2)
        self.assertEqual({record.target_type for record in context.change_records}, {"hotel", "transport"})
        self.assertEqual({record.status for record in context.change_records}, {"CHANGED"})
        self.assertEqual(len(context.change_approvals), 1)
        self.assertEqual(context.change_approvals[0].status, "APPROVED")
        self.assertEqual(len(context.refund_confirmations), 2)
        self.assertEqual(context.calendar_syncs[-1].event_type, "TRIP_CHANGED")
        actions = {(record.agent_name, record.action) for record in context.agent_executions}
        self.assertIn(("TransportAgent", "change_transport_order"), actions)
        self.assertIn(("BookingAgent", "change_hotel_order"), actions)
        self.assertIn(("ApprovalAgent", "create_change_approval"), actions)
        self.assertIn(("ApprovalAgent", "confirm_refund"), actions)

    def test_syncs_calendar_for_completed_changed_and_cancelled_trip(self) -> None:
        agent = build_default_agent()
        completed = agent.sync_calendar(agent.run_to_order(_request()))

        self.assertEqual(completed.calendar_syncs[-1].event_type, "TRIP_BOOKED")
        self.assertEqual(completed.calendar_syncs[-1].status, "SYNCED")

        changed = agent.change_trip(
            completed,
            new_depart_at="2026-06-03T13:00:00+08:00",
            new_check_in=date(2026, 6, 4),
            new_check_out=date(2026, 6, 6),
            reason="meeting_rescheduled",
        )

        self.assertEqual(changed.calendar_syncs[-1].event_type, "TRIP_CHANGED")
        self.assertEqual(changed.calendar_syncs[-1].start_at, "2026-06-04")
        self.assertEqual(changed.calendar_syncs[-1].end_at, "2026-06-06")

        cancelled = agent.cancel_trip(changed, "meeting_cancelled")
        cancelled = agent.sync_calendar(cancelled)

        self.assertEqual(cancelled.calendar_syncs[-1].event_type, "TRIP_CANCELLED")

    def test_syncs_calendar_with_attendees(self) -> None:
        agent = build_default_agent()
        context = agent.sync_calendar(
            agent.run_to_order(_request()),
            attendees=["u-demo", "manager@example.com"],
        )

        self.assertEqual(context.calendar_syncs[-1].attendees, ["u-demo", "manager@example.com"])

    def test_notify_current_state_is_idempotent(self) -> None:
        agent = build_default_agent()
        context = agent.run_to_order(_request())

        context = agent.notify_current_state(context)
        context = agent.notify_current_state(context)

        self.assertEqual(len(context.notifications), 1)
        self.assertEqual(context.notifications[0].event_type, "ORDER_COMPLETED")

    def test_policy_caps_hotel_budget(self) -> None:
        agent = build_default_agent()
        request = _request(budget_per_night=900)
        context = agent.plan(request)

        self.assertFalse(context.policy_result.compliant)
        self.assertEqual(context.policy_result.approved_budget, 650)
        self.assertTrue(all(hotel.nightly_price <= 650 for hotel in context.hotel_options if hotel.policy_compliant))


class MultiAgentStructureTest(unittest.TestCase):
    def test_default_agent_uses_domain_agent_team(self) -> None:
        agent = build_default_agent()

        self.assertIsInstance(agent.agent_team.policy, PolicyAgent)
        self.assertIsInstance(agent.agent_team.hotel, HotelAgent)
        self.assertIsInstance(agent.agent_team.transport, TransportAgent)
        self.assertIsInstance(agent.agent_team.approval, ApprovalAgent)
        self.assertIsInstance(agent.agent_team.booking, BookingAgent)

    def test_domain_agents_append_auditable_events(self) -> None:
        agent = build_default_agent()
        context = agent.run_to_order(_request())

        self.assertTrue(any("PolicyAgent completed" in event for event in context.events))
        self.assertTrue(any("HotelAgent searched" in event for event in context.events))
        self.assertTrue(any("TransportAgent created transport order" in event for event in context.events))
        self.assertTrue(any("ApprovalAgent created approval" in event for event in context.events))
        self.assertTrue(any("BookingAgent created hotel order" in event for event in context.events))

    def test_domain_agents_record_execution_summaries(self) -> None:
        agent = build_default_agent()
        context = agent.run_to_order(_request())

        actions = {(record.agent_name, record.action) for record in context.agent_executions}

        self.assertIn(("PolicyAgent", "check_policies"), actions)
        self.assertIn(("ItineraryAgent", "plan_itinerary"), actions)
        self.assertIn(("HotelAgent", "search_hotels"), actions)
        self.assertIn(("TransportAgent", "create_transport_order"), actions)
        self.assertIn(("ApprovalAgent", "create_approval"), actions)
        self.assertIn(("BookingAgent", "create_order"), actions)
        self.assertTrue(all(record.input_refs["workflow_generation"] == 1 for record in context.agent_executions))

    def test_cancel_trip_records_compensation_execution_summaries(self) -> None:
        agent = build_default_agent()
        context = agent.cancel_trip(agent.run_to_order(_request()), "meeting_cancelled")

        actions = {(record.agent_name, record.action) for record in context.agent_executions}

        self.assertIn(("TransportAgent", "cancel_transport_order"), actions)
        self.assertIn(("BookingAgent", "cancel_order"), actions)
        self.assertIn(("HotelAgent", "release_hotel_inventory"), actions)
        self.assertEqual(context.order_cancellation.status, "CANCELLED")
        self.assertEqual(context.transport_order_cancellation.status, "CANCELLED")
        self.assertEqual(context.inventory_release.status, "RELEASED")


class IntegrationAdapterTest(unittest.TestCase):
    def test_uses_real_http_integrations_when_urls_are_configured(self) -> None:
        http = StubHttpClient(
            {
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
            }
        )
        settings = IntegrationSettings(
            policy_api_url="https://policy.example/check",
            transport_policy_api_url="https://transport.example/policy",
            hotel_inventory_api_url="https://hotel.example/search",
            transport_inventory_api_url="https://transport.example/search",
            oa_approval_api_url="https://oa.example/create",
        )

        context = build_default_agent(settings=settings, http_client=http).run_to_approval(_request())

        self.assertEqual(context.policy_result.source, "real")
        self.assertEqual(context.transport_policy_result.source, "real")
        self.assertEqual(context.hotel_options[0].source, "real")
        self.assertEqual(context.transport_options[0].source, "real")
        self.assertEqual(context.approval.source, "real")
        self.assertEqual(context.approval.approval_id, "REMOTE-APPROVAL-1")

    def test_uses_real_http_integrations_for_order_creation(self) -> None:
        http = StubHttpClient(
            {
                "https://policy.example/check": {
                    "policy": {
                        "policy_id": "REMOTE-POLICY-1",
                        "max_hotel_price": 700,
                        "approved_budget": 680,
                        "compliant": True,
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
            }
        )
        settings = IntegrationSettings(
            policy_api_url="https://policy.example/check",
            transport_policy_api_url="https://transport.example/policy",
            hotel_inventory_api_url="https://hotel.example/search",
            transport_inventory_api_url="https://transport.example/search",
            oa_approval_api_url="https://oa.example/create",
            oa_approval_status_api_url="https://oa.example/status",
            hotel_inventory_lock_api_url="https://hotel.example/lock",
            transport_order_api_url="https://transport.example/order",
            order_api_url="https://order.example/create",
        )

        context = build_default_agent(settings=settings, http_client=http).run_to_order(_request())

        self.assertEqual(context.state, TravelState.COMPLETED.value)
        self.assertEqual(context.approval.source, "real")
        self.assertEqual(context.transport_order.source, "real")
        self.assertEqual(context.inventory_lock.source, "real")
        self.assertEqual(context.order.source, "real")
        self.assertEqual(context.transport_order.order_id, "REMOTE-TRANSPORT-ORDER-1")
        self.assertEqual(context.order.order_id, "REMOTE-ORDER-1")

    def test_price_change_pauses_until_user_confirmation(self) -> None:
        http = StubHttpClient(
            _remote_order_responses(
                price_check={
                    "price_check": {
                        "hotel_id": "REMOTE-HOTEL-1",
                        "status": "PRICE_CHANGED",
                        "original_price": 660,
                        "current_price": 680,
                        "policy_compliant": True,
                        "requires_confirmation": True,
                    }
                }
            )
        )
        settings = _remote_order_settings()

        agent = build_default_agent(settings=settings, http_client=http)
        context = agent.run_to_order(_request())

        self.assertEqual(context.state, TravelState.PRICE_CHANGED.value)
        self.assertIsNotNone(context.price_check)
        self.assertIsNone(context.order)

        context = agent.confirm_price_change(context, accept=True)

        self.assertEqual(context.state, TravelState.COMPLETED.value)
        self.assertEqual(context.selected_hotel.nightly_price, 680)
        self.assertEqual(context.order.payload["selected_hotel"]["nightly_price"], 680)

    def test_reject_price_change_releases_inventory(self) -> None:
        http = StubHttpClient(
            _remote_order_responses(
                price_check={
                    "price_check": {
                        "hotel_id": "REMOTE-HOTEL-1",
                        "status": "PRICE_CHANGED",
                        "original_price": 660,
                        "current_price": 680,
                        "policy_compliant": True,
                        "requires_confirmation": True,
                    }
                }
            )
            | {
                "https://hotel.example/release": {
                    "compensation": {
                        "action": "release_hotel_inventory",
                        "target_id": "REMOTE-LOCK-1",
                        "status": "RELEASED",
                    }
                }
            }
        )
        settings = _remote_order_settings(hotel_inventory_release_api_url="https://hotel.example/release")

        agent = build_default_agent(settings=settings, http_client=http)
        context = agent.run_to_order(_request())
        context = agent.confirm_price_change(context, accept=False)

        self.assertEqual(context.state, TravelState.USER_CANCELLED.value)
        self.assertIsNone(context.order)
        self.assertEqual(context.inventory_release.status, "RELEASED")

    def test_inventory_expired_stops_before_order_creation(self) -> None:
        http = StubHttpClient(
            _remote_order_responses(
                price_check={
                    "price_check": {
                        "hotel_id": "REMOTE-HOTEL-1",
                        "status": "SOLD_OUT",
                        "original_price": 660,
                        "current_price": None,
                        "policy_compliant": False,
                        "requires_confirmation": False,
                    }
                }
            )
        )
        settings = _remote_order_settings()

        context = build_default_agent(settings=settings, http_client=http).run_to_order(_request())

        self.assertEqual(context.state, TravelState.INVENTORY_EXPIRED.value)
        self.assertIsNotNone(context.inventory_lock)
        self.assertIsNone(context.order)

    def test_refreshes_real_order_status(self) -> None:
        http = StubHttpClient(
            _remote_order_responses()
            | {
                "https://order.example/status": {
                    "order": {
                        "order_id": "REMOTE-ORDER-1",
                        "status": "CONFIRMED",
                        "total_amount": 1320,
                        "currency": "CNY",
                    }
                },
                "https://transport.example/status": {
                    "transport_order": {
                        "order_id": "REMOTE-TRANSPORT-ORDER-1",
                        "status": "CONFIRMED",
                        "total_amount": 980,
                        "currency": "CNY",
                    }
                }
            }
        )
        settings = _remote_order_settings(
            order_status_api_url="https://order.example/status",
            transport_order_status_api_url="https://transport.example/status",
        )

        agent = build_default_agent(settings=settings, http_client=http)
        context = agent.run_to_order(_request())
        context = agent.refresh_order_status(context)

        self.assertEqual(context.order.status, "CONFIRMED")
        self.assertEqual(context.transport_order.status, "CONFIRMED")
        self.assertEqual(context.order.source, "real")
        self.assertEqual(context.transport_order.source, "real")

    def test_uses_real_http_integrations_for_refund_and_change(self) -> None:
        http = StubHttpClient(
            _remote_order_responses()
            | {
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
                "https://oa.example/change": {
                    "approval": {
                        "approval_id": "REMOTE-CHANGE-APPROVAL-1",
                        "status": "APPROVED",
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
            }
        )
        settings = _remote_order_settings(
            refund_estimate_api_url="https://refund.example/estimate",
            refund_confirm_api_url="https://refund.example/confirm",
            change_approval_api_url="https://oa.example/change",
            transport_change_api_url="https://transport.example/change",
            hotel_change_api_url="https://hotel.example/change",
        )

        agent = build_default_agent(settings=settings, http_client=http)
        context = agent.change_trip(
            agent.run_to_order(_request()),
            new_depart_at="2026-06-03T13:00:00+08:00",
            new_check_in=date(2026, 6, 4),
            new_check_out=date(2026, 6, 6),
            reason="meeting_rescheduled",
        )

        self.assertEqual(context.refund_estimates[0].source, "real")
        self.assertEqual(context.change_approvals[0].source, "real")
        self.assertEqual(context.change_approvals[0].approval_id, "REMOTE-CHANGE-APPROVAL-1")
        self.assertEqual(context.refund_confirmations[0].source, "real")
        self.assertEqual(context.refund_confirmations[0].confirmation_id, "REMOTE-RFC-1")
        self.assertEqual(context.change_records[0].source, "real")
        self.assertEqual(context.change_records[1].source, "real")
        self.assertEqual(context.change_records[0].change_id, "REMOTE-TCHG-1")
        self.assertEqual(context.change_records[1].change_id, "REMOTE-HCHG-1")

    def test_change_trip_records_supplier_failure_compensation(self) -> None:
        http = StubHttpClient(
            _remote_order_responses()
            | {
                "https://transport.example/change": {
                    "change": {
                        "change_id": "REMOTE-TCHG-FAILED",
                        "target_type": "transport",
                        "target_id": "REMOTE-TRANSPORT-ORDER-1",
                        "status": "FAILED",
                        "penalty_amount": 0,
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
            }
        )
        settings = _remote_order_settings(
            transport_change_api_url="https://transport.example/change",
            hotel_change_api_url="https://hotel.example/change",
            change_failure_compensation_api_url="https://change.example/compensate",
        )

        agent = build_default_agent(settings=settings, http_client=http)
        context = agent.change_trip(
            agent.run_to_order(_request()),
            new_depart_at="2026-06-03T13:00:00+08:00",
            new_check_in=date(2026, 6, 4),
            new_check_out=date(2026, 6, 6),
            reason="meeting_rescheduled",
        )

        self.assertEqual(context.change_records[0].status, "FAILED")
        self.assertEqual(len(context.change_failure_compensations), 1)
        self.assertEqual(context.change_failure_compensations[0].source, "real")
        self.assertFalse(context.calendar_syncs)

    def test_uses_real_http_integration_for_calendar_sync(self) -> None:
        http = StubHttpClient(
            _remote_order_responses()
            | {
                "https://calendar.example/sync": {
                    "calendar": {
                        "calendar_event_id": "REMOTE-CAL-1",
                        "event_type": "TRIP_BOOKED",
                        "status": "SYNCED",
                        "user_id": "u-demo",
                        "title": "remote calendar",
                        "start_at": "2026-06-03",
                        "end_at": "2026-06-05",
                    }
                }
            }
        )
        settings = _remote_order_settings(calendar_api_url="https://calendar.example/sync")

        agent = build_default_agent(settings=settings, http_client=http)
        context = agent.sync_calendar(agent.run_to_order(_request()))

        self.assertEqual(context.calendar_syncs[-1].source, "real")
        self.assertEqual(context.calendar_syncs[-1].calendar_event_id, "REMOTE-CAL-1")

    def test_uses_real_http_integration_for_notifications(self) -> None:
        http = StubHttpClient(
            _remote_order_responses()
            | {
                "https://notify.example/send": {
                    "notification": {
                        "notification_id": "REMOTE-NOTIFY-1",
                        "event_type": "ORDER_COMPLETED",
                        "channel": "im",
                        "recipient_id": "u-demo",
                        "title": "remote title",
                        "message": "remote message",
                        "status": "SENT",
                    }
                }
            }
        )
        settings = _remote_order_settings(notification_api_url="https://notify.example/send")
        agent = build_default_agent(settings=settings, http_client=http)

        context = agent.notify_current_state(agent.run_to_order(_request()))

        self.assertEqual(context.notifications[0].source, "real")
        self.assertEqual(context.notifications[0].notification_id, "REMOTE-NOTIFY-1")

    def test_uses_real_http_integrations_for_compensation(self) -> None:
        http = StubHttpClient(
            {
                "https://policy.example/check": {
                    "policy": {
                        "policy_id": "REMOTE-POLICY-1",
                        "max_hotel_price": 700,
                        "approved_budget": 680,
                        "compliant": True,
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
                "https://order.example/create": {
                    "order": {
                        "order_id": "REMOTE-ORDER-1",
                        "status": "CREATED",
                        "total_amount": 1320,
                        "currency": "CNY",
                    }
                },
                "https://order.example/cancel": {
                    "compensation": {
                        "action": "cancel_order",
                        "target_id": "REMOTE-ORDER-1",
                        "status": "CANCELLED",
                    }
                },
                "https://transport.example/cancel": {
                    "compensation": {
                        "action": "cancel_transport_order",
                        "target_id": "REMOTE-TRANSPORT-ORDER-1",
                        "status": "CANCELLED",
                    }
                },
                "https://hotel.example/release": {
                    "compensation": {
                        "action": "release_hotel_inventory",
                        "target_id": "REMOTE-LOCK-1",
                        "status": "RELEASED",
                    }
                },
            }
        )
        settings = IntegrationSettings(
            policy_api_url="https://policy.example/check",
            hotel_inventory_api_url="https://hotel.example/search",
            oa_approval_api_url="https://oa.example/create",
            oa_approval_status_api_url="https://oa.example/status",
            hotel_inventory_lock_api_url="https://hotel.example/lock",
            hotel_inventory_release_api_url="https://hotel.example/release",
            order_api_url="https://order.example/create",
            order_cancel_api_url="https://order.example/cancel",
            transport_order_cancel_api_url="https://transport.example/cancel",
        )

        agent = build_default_agent(settings=settings, http_client=http)
        context = agent.cancel_trip(agent.run_to_order(_request()), "meeting_cancelled")

        self.assertEqual(context.state, TravelState.USER_CANCELLED.value)
        self.assertEqual(context.order_cancellation.source, "real")
        self.assertEqual(context.transport_order_cancellation.source, "real")
        self.assertEqual(context.inventory_release.source, "real")

    def test_rejected_approval_stops_before_booking(self) -> None:
        http = StubHttpClient(
            {
                "https://policy.example/check": {
                    "policy": {
                        "policy_id": "REMOTE-POLICY-1",
                        "max_hotel_price": 700,
                        "approved_budget": 680,
                        "compliant": True,
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
                "https://oa.example/create": {
                    "approval": {
                        "approval_id": "REMOTE-APPROVAL-1",
                        "status": "PENDING_APPROVAL",
                    }
                },
                "https://oa.example/status": {
                    "approval": {
                        "approval_id": "REMOTE-APPROVAL-1",
                        "status": "REJECTED",
                    }
                },
            }
        )
        settings = IntegrationSettings(
            policy_api_url="https://policy.example/check",
            hotel_inventory_api_url="https://hotel.example/search",
            oa_approval_api_url="https://oa.example/create",
            oa_approval_status_api_url="https://oa.example/status",
        )

        context = build_default_agent(settings=settings, http_client=http).run_to_order(_request())

        self.assertEqual(context.state, TravelState.APPROVAL_REJECTED.value)
        self.assertIsNone(context.inventory_lock)
        self.assertIsNone(context.order)

    def test_replans_after_rejected_approval_and_creates_new_approval(self) -> None:
        http = StubHttpClient(
            {
                "https://policy.example/check": {
                    "policy": {
                        "policy_id": "REMOTE-POLICY-1",
                        "max_hotel_price": 700,
                        "approved_budget": 680,
                        "compliant": True,
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
                        },
                        {
                            "hotel_id": "REMOTE-HOTEL-2",
                            "name": "Remote Hotel 2",
                            "city": "上海",
                            "address": "Remote Road 2",
                            "nightly_price": 620,
                            "distance_km": 1.0,
                            "rating": 4.7,
                            "refundable": True,
                        },
                    ]
                },
                "https://oa.example/create": {
                    "approval": {
                        "approval_id": "REMOTE-APPROVAL-NEW",
                        "status": "PENDING_APPROVAL",
                    }
                },
                "https://oa.example/status": {
                    "approval": {
                        "approval_id": "REMOTE-APPROVAL-OLD",
                        "status": "REJECTED",
                    }
                },
            }
        )
        settings = IntegrationSettings(
            policy_api_url="https://policy.example/check",
            hotel_inventory_api_url="https://hotel.example/search",
            oa_approval_api_url="https://oa.example/create",
            oa_approval_status_api_url="https://oa.example/status",
        )
        agent = build_default_agent(settings=settings, http_client=http)
        context = agent.run_to_order(_request())

        replanned = agent.replan_after_exception(context, reason="approval_rejected_replan")
        new_approval = agent.reselect_hotel_and_create_approval(replanned, "REMOTE-HOTEL-2")

        self.assertEqual(replanned.workflow_generation, 2)
        self.assertEqual(replanned.state, TravelState.APPROVAL_CREATED.value)
        self.assertEqual(new_approval.approval.approval_id, "REMOTE-APPROVAL-NEW")
        self.assertEqual(new_approval.approval.payload["workflow_generation"], 2)
        self.assertEqual(new_approval.recovery_records[0].from_state, TravelState.APPROVAL_REJECTED.value)

    def test_replans_after_price_change_releases_inventory(self) -> None:
        http = StubHttpClient(
            _remote_order_responses(
                price_check={
                    "price_check": {
                        "hotel_id": "REMOTE-HOTEL-1",
                        "status": "PRICE_CHANGED",
                        "original_price": 660,
                        "current_price": 680,
                        "policy_compliant": True,
                        "requires_confirmation": True,
                    }
                }
            )
            | {
                "https://hotel.example/release": {
                    "compensation": {
                        "action": "release_hotel_inventory",
                        "target_id": "REMOTE-LOCK-1",
                        "status": "RELEASED",
                    }
                },
                "https://oa.example/cancel": {
                    "compensation": {
                        "action": "cancel_approval",
                        "target_id": "REMOTE-APPROVAL-1",
                        "status": "CANCELLED",
                    }
                },
            }
        )
        settings = _remote_order_settings(
            hotel_inventory_release_api_url="https://hotel.example/release",
            oa_approval_cancel_api_url="https://oa.example/cancel",
        )
        agent = build_default_agent(settings=settings, http_client=http)
        context = agent.run_to_order(_request())

        replanned = agent.replan_after_exception(context, reason="price_change_replan")

        self.assertEqual(replanned.state, TravelState.PLAN_GENERATED.value)
        self.assertEqual(replanned.workflow_generation, 2)
        self.assertIsNone(replanned.inventory_lock)
        self.assertIsNone(replanned.approval)
        self.assertIn("inventory_release", replanned.recovery_records[0].payload["compensations"])
        self.assertIn("approval_cancellation", replanned.recovery_records[0].payload["compensations"])
        actions = {(record.agent_name, record.action) for record in replanned.agent_executions}
        self.assertIn(("HotelAgent", "release_hotel_inventory"), actions)
        self.assertIn(("ApprovalAgent", "cancel_approval"), actions)
        self.assertIn(("HotelAgent", "search_hotels"), actions)

    def test_replans_after_order_failed_cancels_order_and_uses_new_idempotency_key(self) -> None:
        http = CapturingHttpClient(
            _remote_order_responses(
                order={
                    "order": {
                        "order_id": "REMOTE-ORDER-1",
                        "status": "FAILED",
                        "total_amount": 1320,
                        "currency": "CNY",
                    }
                }
            )
            | {
                "https://order.example/cancel": {
                    "compensation": {
                        "action": "cancel_order",
                        "target_id": "REMOTE-ORDER-1",
                        "status": "CANCELLED",
                    }
                },
                "https://hotel.example/release": {
                    "compensation": {
                        "action": "release_hotel_inventory",
                        "target_id": "REMOTE-LOCK-1",
                        "status": "RELEASED",
                    }
                },
                "https://oa.example/cancel": {
                    "compensation": {
                        "action": "cancel_approval",
                        "target_id": "REMOTE-APPROVAL-1",
                        "status": "CANCELLED",
                    }
                },
            }
        )
        settings = _remote_order_settings(
            order_cancel_api_url="https://order.example/cancel",
            hotel_inventory_release_api_url="https://hotel.example/release",
            oa_approval_cancel_api_url="https://oa.example/cancel",
        )
        agent = build_default_agent(settings=settings, http_client=http)
        context = agent.run_to_order(_request())

        replanned = agent.replan_after_exception(context, reason="order_failed_replan")
        new_approval = agent.reselect_hotel_and_create_approval(replanned)

        self.assertEqual(context.state, TravelState.APPROVAL_CREATED.value)
        self.assertIn("order_cancellation", replanned.recovery_records[0].payload["compensations"])
        self.assertIsNone(new_approval.order)
        self.assertEqual(http.payloads["https://oa.example/create"][-1]["idempotency_key"], f"travel-approval:{context.session_id}:2:u-demo")

    def test_falls_back_to_mock_when_real_system_fails(self) -> None:
        settings = IntegrationSettings(
            policy_api_url="https://policy.example/check",
            hotel_inventory_api_url="https://hotel.example/search",
            oa_approval_api_url="https://oa.example/create",
            use_mock_fallback=True,
        )

        context = build_default_agent(settings=settings, http_client=FailingHttpClient()).run_to_approval(_request())

        self.assertEqual(context.policy_result.source, "mock_fallback")
        self.assertEqual(context.hotel_options[0].source, "mock_fallback")
        self.assertEqual(context.approval.source, "mock_fallback")

    def test_raises_when_real_system_missing_and_fallback_disabled(self) -> None:
        settings = IntegrationSettings(use_mock_fallback=False)

        with self.assertRaises(IntegrationError):
            build_default_agent(settings=settings).plan(_request())


class ToolGatewayTest(unittest.TestCase):
    def test_validates_required_parameters(self) -> None:
        gateway = ToolGateway()
        gateway.register("echo", "Echo one value.", ("value",), lambda value: value)

        with self.assertRaises(ToolValidationError):
            gateway.call("echo")
        self.assertEqual(len(gateway.call_logs), 1)
        self.assertFalse(gateway.call_logs[0].ok)

    def test_records_redacted_audit_event_for_tool_calls(self) -> None:
        gateway = ToolGateway()
        gateway.register("echo", "Echo one value.", ("phone",), lambda phone: phone)

        gateway.call("echo", phone="13800000000")

        self.assertEqual(len(gateway.audit_events), 1)
        self.assertEqual(gateway.audit_events[0].redacted_payload["phone"], "***")
        self.assertIn("phone", gateway.audit_events[0].redacted_keys)

    def test_writes_redacted_audit_event_to_http_sink(self) -> None:
        http = CapturingAnyHttpClient({"https://audit.example/events": {"ok": True, "accepted": 1}})
        gateway = ToolGateway(audit_sink=HttpAuditSink("https://audit.example/events", "audit-token", http_client=http))
        gateway.register("echo", "Echo one value.", ("phone",), lambda phone: phone)

        gateway.call("echo", phone="13800000000")

        self.assertEqual(gateway.audit_sink_results[0].delivered, 1)
        self.assertEqual(http.calls[0][2], "audit-token")
        self.assertEqual(http.calls[0][1]["events"][0]["payload"]["phone"], "***")


class SessionStoreTest(unittest.TestCase):
    def test_http_session_store_round_trips_context_and_worker_runs(self) -> None:
        http = FakeSessionStoreHttpClient()
        store = HttpSessionStore("https://store.example/api", token="store-token", http_client=http)
        agent = build_default_agent(session_store=store)
        context = agent.run_to_order(_request())

        reloaded = store.get(context.session_id)
        recent = store.list_recent(limit=1)
        by_state = store.list_by_states({TravelState.COMPLETED.value})
        worker_run = WorkerRunRecord(
            run_id="WRK-HTTP-1",
            started_at="2026-05-14T00:00:00+00:00",
            finished_at="2026-05-14T00:00:01+00:00",
            scanned=1,
            advanced=1,
            skipped=0,
            errors={},
            session_ids=[context.session_id],
        )
        store.record_worker_run(worker_run)
        health = store.health_check()

        self.assertEqual(reloaded.session_id, context.session_id)
        self.assertEqual(reloaded.state, TravelState.COMPLETED.value)
        self.assertEqual(recent[0].session_id, context.session_id)
        self.assertEqual(by_state[0].session_id, context.session_id)
        self.assertEqual(store.list_worker_runs()[0].run_id, "WRK-HTTP-1")
        self.assertTrue(health.ok)
        self.assertEqual(health.backend, "http-json")
        self.assertEqual(health.session_count, 1)
        self.assertTrue(all(token == "store-token" for _, _, token in http.calls))

    def test_http_session_store_uses_optimistic_concurrency(self) -> None:
        http = FakeSessionStoreHttpClient()
        store = HttpSessionStore("https://store.example/api", http_client=http)
        context = build_default_agent(session_store=store).run_to_order(_request())

        stored = store.get_with_metadata(context.session_id)
        context.events.append("manual http metadata test event")
        next_version = store.save_if_version(context, expected_version=stored.version)
        reloaded = store.get_with_metadata(context.session_id)

        self.assertEqual(next_version, stored.version + 1)
        self.assertEqual(reloaded.version, next_version)
        self.assertTrue(reloaded.created_at)
        self.assertTrue(reloaded.updated_at)
        with self.assertRaises(StoreConcurrencyError):
            store.save_if_version(context, expected_version=stored.version)

    def test_build_default_agent_can_use_http_session_store_from_settings(self) -> None:
        http = FakeSessionStoreHttpClient()
        settings = IntegrationSettings(
            session_store_backend="http",
            session_store_api_url="https://store.example/api",
            session_store_api_token="store-token",
        )

        agent = build_default_agent(settings=settings, store_http_client=http)
        context = agent.run_to_order(_request())

        self.assertIsInstance(agent.session_store, HttpSessionStore)
        self.assertEqual(agent.get_session(context.session_id).state, TravelState.COMPLETED.value)

    def test_http_session_store_records_operations_records(self) -> None:
        http = FakeSessionStoreHttpClient()
        store = HttpSessionStore("https://store.example/api", http_client=http)
        dashboard = build_operations_dashboard()
        snapshot = build_operations_dashboard_snapshot(
            dashboard,
            snapshot_id="DASH-HTTP",
            created_at="2026-05-19T10:00:00+00:00",
        )
        status = oncall_ticket_status_to_dict(
            fetch_oncall_ticket_status_http(
                "INC-HTTP",
                endpoint="https://oncall.example/status",
                http_client=CapturingAnyHttpClient(
                    {
                        "https://oncall.example/status": {
                            "ticket": {
                                "ticket_id": "INC-HTTP",
                                "status": "ACKED",
                                "updated_at": "2026-05-19T10:05:00+00:00",
                            }
                        }
                    }
                ),
            )
        )

        store.record_operations_dashboard_snapshot(operations_dashboard_snapshot_to_dict(snapshot))
        store.record_oncall_ticket_status(status)
        store.record_operations_trend_alert(
            {
                "alert_id": "TREND-HTTP",
                "metric": "critical_alerts",
                "severity": "critical",
                "route": "ops",
                "escalation": "page",
                "owner": "ops",
                "current": 2,
                "previous": 1,
                "delta": 1,
                "delta_percent": 100.0,
                "reason": "delta 1 >= threshold 1",
                "action_item": "Handle critical alerts",
            }
        )
        store.record_operations_action_item(
            {
                "action_id": "ACT-HTTP",
                "source_type": "trend_alert",
                "source_id": "TREND-HTTP",
                "title": "Handle critical alerts",
                "owner": "ops",
                "status": "OPEN",
                "eta": None,
                "created_at": "2026-05-19T10:00:00+00:00",
                "updated_at": "2026-05-19T10:00:00+00:00",
                "evidence": ["metric=critical_alerts"],
                "closure_note": None,
            }
        )
        store.record_operations_knowledge_entry(
            {
                "entry_id": "KB-HTTP",
                "topic": "critical_alerts",
                "title": "Critical alert response",
                "summary": "Handle critical alert growth",
                "signals": ["critical_alerts"],
                "recommended_actions": ["Handle critical alerts"],
                "source_refs": ["TREND-HTTP"],
                "created_at": "2026-05-19T10:00:00+00:00",
                "updated_at": "2026-05-19T10:00:00+00:00",
            }
        )

        self.assertEqual(store.list_operations_dashboard_snapshots()[0]["snapshot_id"], "DASH-HTTP")
        self.assertEqual(store.list_oncall_ticket_statuses()[0]["status"], "ACKED")
        self.assertEqual(store.list_operations_trend_alerts()[0]["alert_id"], "TREND-HTTP")
        self.assertEqual(store.list_operations_action_items()[0]["action_id"], "ACT-HTTP")
        self.assertEqual(store.list_operations_knowledge_entries()[0]["entry_id"], "KB-HTTP")
        self.assertTrue(any(call[0].endswith("/operations/dashboard-snapshots/record") for call in http.calls))
        self.assertTrue(any(call[0].endswith("/operations/oncall-statuses/record") for call in http.calls))
        self.assertTrue(any(call[0].endswith("/operations/trend-alerts/record") for call in http.calls))
        self.assertTrue(any(call[0].endswith("/operations/action-items/record") for call in http.calls))
        self.assertTrue(any(call[0].endswith("/operations/knowledge/record") for call in http.calls))

    def test_build_session_store_selects_configured_backends(self) -> None:
        http = FakeSessionStoreHttpClient()
        http_store = build_session_store(
            IntegrationSettings(session_store_backend="http", session_store_api_url="https://store.example/api"),
            store_http_client=http,
        )
        memory_store = build_session_store(IntegrationSettings(session_store_backend="memory"))
        auto_store = build_session_store(
            IntegrationSettings(session_store_api_url="https://store.example/api"),
            store_http_client=http,
        )

        self.assertIsInstance(http_store, HttpSessionStore)
        self.assertIsInstance(memory_store, InMemorySessionStore)
        self.assertIsInstance(auto_store, HttpSessionStore)

    def test_sqlite_session_store_round_trips_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "sessions.sqlite3"
            store = SQLiteSessionStore(db_path)
            agent = build_default_agent(session_store=store)
            context = agent.run_to_order(_request())

            reloaded = SQLiteSessionStore(db_path).get(context.session_id)

            self.assertEqual(reloaded.session_id, context.session_id)
            self.assertEqual(reloaded.state, TravelState.COMPLETED.value)
            self.assertEqual(reloaded.request.start_date, date(2026, 6, 3))
            self.assertEqual(reloaded.selected_hotel.hotel_id, context.selected_hotel.hotel_id)
            self.assertEqual(reloaded.selected_transport.transport_id, context.selected_transport.transport_id)
            self.assertEqual(reloaded.order.order_id, context.order.order_id)
            self.assertEqual(reloaded.transport_order.order_id, context.transport_order.order_id)
            self.assertEqual(len(reloaded.agent_executions), len(context.agent_executions))
            self.assertEqual(reloaded.agent_executions[-1].agent_name, "BookingAgent")
            self.assertEqual(reloaded.agent_executions[-1].action, "create_order")

            changed = agent.change_trip(
                context,
                new_depart_at="2026-06-03T13:00:00+08:00",
                new_check_in=date(2026, 6, 4),
                new_check_out=date(2026, 6, 6),
                reason="meeting_rescheduled",
            )
            changed_reloaded = SQLiteSessionStore(db_path).get(changed.session_id)
            self.assertEqual(len(changed_reloaded.refund_estimates), 2)
            self.assertEqual(len(changed_reloaded.refund_confirmations), 2)
            self.assertEqual(len(changed_reloaded.change_approvals), 1)
            self.assertEqual(len(changed_reloaded.change_records), 2)
            self.assertEqual(len(changed_reloaded.calendar_syncs), 1)
            self.assertEqual(changed_reloaded.calendar_syncs[0].event_type, "TRIP_CHANGED")

    def test_sqlite_store_records_operations_dashboard_and_oncall_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "sessions.sqlite3"
            store = SQLiteSessionStore(db_path)
            dashboard = build_operations_dashboard(
                alerts=[{"alert_type": "audit_sink_failed", "severity": "critical", "message": "audit down", "value": 1}]
            )
            snapshot = build_operations_dashboard_snapshot(
                dashboard,
                alerts=[{"alert_type": "audit_sink_failed", "severity": "critical", "message": "audit down", "value": 1}],
                snapshot_id="DASH-SQL",
                created_at="2026-05-19T10:00:00+00:00",
            )
            status = fetch_oncall_ticket_status_http(
                "INC-SQL",
                endpoint="https://oncall.example/status",
                http_client=CapturingAnyHttpClient(
                    {
                        "https://oncall.example/status": {
                            "ticket": {
                                "ticket_id": "INC-SQL",
                                "status": "RESOLVED",
                                "assignee": "ops",
                                "updated_at": "2026-05-19T10:05:00+00:00",
                            }
                        }
                    }
                ),
            )

            store.record_operations_dashboard_snapshot(operations_dashboard_snapshot_to_dict(snapshot))
            store.record_oncall_ticket_status(oncall_ticket_status_to_dict(status))
            trend = build_operations_dashboard_trend_report([snapshot], window=1)
            trend_alerts = evaluate_operations_trend_alerts(trend)
            action_items = build_trend_alert_action_items(trend_alerts, eta="2026-05-20T12:00:00+00:00")
            entries = build_operations_knowledge_entries(trend_alerts=trend_alerts, action_items=action_items)
            for alert in trend_alerts:
                store.record_operations_trend_alert(operations_trend_alert_to_dict(alert))
            for item in action_items:
                store.record_operations_action_item(operations_action_item_to_dict(item))
            for entry in entries:
                store.record_operations_knowledge_entry(operations_knowledge_entry_to_dict(entry))

            reloaded_snapshot = operations_dashboard_snapshot_from_dict(store.list_operations_dashboard_snapshots()[0])
            reloaded_status = oncall_ticket_status_from_dict(store.list_oncall_ticket_statuses()[0])
            reloaded_alert = operations_trend_alert_from_dict(store.list_operations_trend_alerts()[0])
            reloaded_action = operations_action_item_from_dict(store.list_operations_action_items()[0])
            reloaded_entry = operations_knowledge_entry_from_dict(store.list_operations_knowledge_entries()[0])
            health = store.health_check()

            self.assertEqual(reloaded_snapshot.snapshot_id, "DASH-SQL")
            self.assertEqual(reloaded_status.status, "RESOLVED")
            self.assertEqual(reloaded_alert.metric, "critical_alerts")
            self.assertEqual(reloaded_action.status, "OPEN")
            self.assertEqual(reloaded_entry.topic, "critical_alerts")
            self.assertGreaterEqual(health.schema_version, 4)
            self.assertEqual(health.details["dashboard_snapshots"], "1")
            self.assertEqual(health.details["oncall_ticket_statuses"], "1")
            self.assertEqual(health.details["operations_trend_alerts"], "1")
            self.assertEqual(health.details["operations_action_items"], "1")
            self.assertEqual(health.details["operations_knowledge_entries"], "1")

    def test_sqlite_session_store_tracks_metadata_and_versions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "sessions.sqlite3"
            store = SQLiteSessionStore(db_path)
            agent = build_default_agent(session_store=store)
            context = agent.run_to_order(_request())

            stored = SQLiteSessionStore(db_path).get_with_metadata(context.session_id)
            original_version = stored.version
            context.events.append("manual metadata test event")
            next_version = store.save_if_version(context, expected_version=original_version)

            reloaded = store.get_with_metadata(context.session_id)

            self.assertEqual(next_version, original_version + 1)
            self.assertEqual(reloaded.version, next_version)
            self.assertTrue(reloaded.created_at)
            self.assertTrue(reloaded.updated_at)

            with self.assertRaises(StoreConcurrencyError):
                store.save_if_version(context, expected_version=original_version)

    def test_sqlite_session_store_health_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "sessions.sqlite3"
            store = SQLiteSessionStore(db_path)
            agent = build_default_agent(session_store=store)
            agent.run_to_order(_request())
            WorkflowWorker(agent).run_once()

            health = SQLiteSessionStore(db_path).health_check()

            self.assertTrue(health.ok)
            self.assertGreaterEqual(health.schema_version, 2)
            self.assertEqual(health.session_count, 1)
            self.assertEqual(health.worker_run_count, 1)
            self.assertEqual(health.details["integrity_check"], "ok")

    def test_sqlite_session_store_lists_by_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "sessions.sqlite3"
            store = SQLiteSessionStore(db_path)
            agent = build_default_agent(session_store=store)
            approval_context = agent.run_to_approval(_request())
            completed_context = agent.run_to_order(_request())

            approval_sessions = store.list_by_states({TravelState.APPROVAL_CREATED.value})

            self.assertEqual([context.session_id for context in approval_sessions], [approval_context.session_id])
            self.assertNotEqual(approval_sessions[0].session_id, completed_context.session_id)

    def test_sqlite_session_store_lists_recent_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "sessions.sqlite3"
            store = SQLiteSessionStore(db_path)
            agent = build_default_agent(session_store=store)
            first = agent.run_to_approval(_request())
            second = agent.run_to_order(_request())

            sessions = SQLiteSessionStore(db_path).list_recent(limit=2)

            self.assertEqual(len(sessions), 2)
            self.assertEqual(sessions[0].session_id, second.session_id)
            self.assertEqual(sessions[1].session_id, first.session_id)

    def test_sqlite_session_store_records_worker_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "sessions.sqlite3"
            store = SQLiteSessionStore(db_path)
            agent = build_default_agent(session_store=store)
            context = agent.run_to_order(_request())

            result = WorkflowWorker(agent).run_once()
            runs = SQLiteSessionStore(db_path).list_worker_runs()

            self.assertEqual(len(runs), 1)
            self.assertEqual(runs[0].run_id, result.run_id)
            self.assertEqual(runs[0].scanned, 1)
            self.assertIn(context.session_id, runs[0].session_ids)

    def test_sqlite_session_store_lists_dead_letter_notifications(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "sessions.sqlite3"
            store = SQLiteSessionStore(db_path)
            settings = IntegrationSettings(
                notification_api_url="https://notify.example/send",
                notification_use_mock_fallback=False,
            )
            agent = build_default_agent(
                settings=settings,
                http_client=NotificationFailingHttpClient(),
                session_store=store,
            )
            context = agent.run_to_order(_request())

            worker = WorkflowWorker(agent)
            worker.run_once()
            worker.run_once()
            worker.run_once()
            dead_letters = SQLiteSessionStore(db_path).list_dead_letter_notifications()

            self.assertEqual(len(dead_letters), 1)
            self.assertEqual(dead_letters[0].session_id, context.session_id)
            self.assertEqual(dead_letters[0].notification.event_type, "ORDER_COMPLETED")
            self.assertEqual(dead_letters[0].notification.status, "DEAD_LETTER")

    def test_sqlite_session_store_lists_calendar_dead_letters(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "sessions.sqlite3"
            store = SQLiteSessionStore(db_path)
            settings = IntegrationSettings(
                calendar_api_url="https://calendar.example/sync",
                calendar_use_mock_fallback=False,
            )
            agent = build_default_agent(
                settings=settings,
                http_client=CalendarFailingHttpClient(),
                session_store=store,
            )
            context = agent.sync_calendar(agent.run_to_order(_request()))

            worker = WorkflowWorker(agent)
            worker.run_once()
            worker.run_once()
            dead_letters = SQLiteSessionStore(db_path).list_dead_letter_calendar_syncs()

            self.assertEqual(len(dead_letters), 1)
            self.assertEqual(dead_letters[0].session_id, context.session_id)
            self.assertEqual(dead_letters[0].calendar_sync.event_type, "TRIP_BOOKED")
            self.assertEqual(dead_letters[0].calendar_sync.status, "DEAD_LETTER")


class WorkflowWorkerTest(unittest.TestCase):
    def test_worker_advances_pending_approval_to_completed_order(self) -> None:
        store = InMemorySessionStore()
        agent = build_default_agent(session_store=store)
        context = agent.run_to_approval(_request())

        result = WorkflowWorker(agent).run_once()
        updated = store.get(context.session_id)

        self.assertEqual(result.scanned, 1)
        self.assertEqual(result.advanced, 1)
        self.assertEqual(updated.state, TravelState.COMPLETED.value)
        self.assertIsNotNone(updated.order)

    def test_worker_records_run_summary_in_memory_store(self) -> None:
        store = InMemorySessionStore()
        agent = build_default_agent(session_store=store)
        agent.run_to_order(_request())

        result = WorkflowWorker(agent).run_once()
        runs = store.list_worker_runs()

        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0].run_id, result.run_id)
        self.assertEqual(runs[0].scanned, result.scanned)
        self.assertEqual(runs[0].advanced, result.advanced)

    def test_worker_refreshes_completed_order_status(self) -> None:
        store = InMemorySessionStore()
        agent = build_default_agent(session_store=store)
        context = agent.run_to_order(_request())

        result = WorkflowWorker(agent).run_once()
        updated = store.get(context.session_id)

        self.assertEqual(result.scanned, 1)
        self.assertEqual(updated.order.status, "CONFIRMED")

    def test_worker_stops_on_price_change(self) -> None:
        store = InMemorySessionStore()
        http = StubHttpClient(
            _remote_order_responses(
                price_check={
                    "price_check": {
                        "hotel_id": "REMOTE-HOTEL-1",
                        "status": "PRICE_CHANGED",
                        "original_price": 660,
                        "current_price": 680,
                        "policy_compliant": True,
                        "requires_confirmation": True,
                    }
                }
            )
        )
        agent = build_default_agent(settings=_remote_order_settings(), http_client=http, session_store=store)
        context = agent.run_to_approval(_request())

        result = WorkflowWorker(agent).run_once()
        updated = store.get(context.session_id)

        self.assertEqual(result.scanned, 1)
        self.assertEqual(updated.state, TravelState.PRICE_CHANGED.value)
        self.assertIsNone(updated.order)
        self.assertEqual(updated.notifications[0].event_type, "PRICE_CHANGE_CONFIRMATION_REQUIRED")

    def test_worker_sends_notification_once_for_completed_order(self) -> None:
        store = InMemorySessionStore()
        agent = build_default_agent(session_store=store)
        context = agent.run_to_order(_request())

        WorkflowWorker(agent).run_once()
        WorkflowWorker(agent).run_once()
        updated = store.get(context.session_id)

        completed_notifications = [
            notification
            for notification in updated.notifications
            if notification.event_type == "ORDER_COMPLETED"
        ]
        self.assertEqual(len(completed_notifications), 1)

    def test_worker_records_failed_notification_without_blocking_flow(self) -> None:
        store = InMemorySessionStore()
        settings = IntegrationSettings(
            notification_api_url="https://notify.example/send",
            notification_use_mock_fallback=False,
        )
        agent = build_default_agent(settings=settings, http_client=NotificationFailingHttpClient(), session_store=store)
        context = agent.run_to_order(_request())

        result = WorkflowWorker(agent).run_once()
        updated = store.get(context.session_id)

        self.assertEqual(result.errors, {})
        self.assertEqual(updated.notifications[0].status, "FAILED")
        self.assertEqual(updated.notifications[0].retry_count, 1)

    def test_worker_retries_failed_notification_and_marks_dead_letter(self) -> None:
        store = InMemorySessionStore()
        settings = IntegrationSettings(
            notification_api_url="https://notify.example/send",
            notification_use_mock_fallback=False,
        )
        agent = build_default_agent(settings=settings, http_client=NotificationFailingHttpClient(), session_store=store)
        context = agent.run_to_order(_request())

        worker = WorkflowWorker(agent)
        worker.run_once()
        worker.run_once()
        worker.run_once()
        updated = store.get(context.session_id)

        self.assertEqual(updated.notifications[0].status, "DEAD_LETTER")
        self.assertEqual(updated.notifications[0].retry_count, 3)

    def test_worker_retries_failed_calendar_sync_and_marks_dead_letter(self) -> None:
        store = InMemorySessionStore()
        settings = IntegrationSettings(
            calendar_api_url="https://calendar.example/sync",
            calendar_use_mock_fallback=False,
        )
        agent = build_default_agent(settings=settings, http_client=CalendarFailingHttpClient(), session_store=store)
        context = agent.sync_calendar(agent.run_to_order(_request()))

        worker = WorkflowWorker(agent)
        worker.run_once()
        worker.run_once()
        updated = store.get(context.session_id)

        self.assertEqual(updated.calendar_syncs[0].status, "DEAD_LETTER")
        self.assertEqual(updated.calendar_syncs[0].retry_count, 3)

    def test_replay_calendar_dead_letter_syncs_again(self) -> None:
        store = InMemorySessionStore()
        settings = IntegrationSettings(
            calendar_api_url="https://calendar.example/sync",
            calendar_use_mock_fallback=False,
        )
        agent = build_default_agent(
            settings=settings,
            http_client=FlakyCalendarHttpClient(failures=3),
            session_store=store,
        )
        context = agent.sync_calendar(agent.run_to_order(_request()))

        worker = WorkflowWorker(agent)
        worker.run_once()
        worker.run_once()
        dead_letter_context = store.get(context.session_id)
        replayed = agent.replay_dead_letter_calendar_sync(dead_letter_context, "TRIP_BOOKED")

        self.assertEqual(replayed.calendar_syncs[0].status, "SYNCED")
        self.assertEqual(replayed.calendar_syncs[0].retry_count, 0)
        self.assertEqual(replayed.calendar_syncs[0].calendar_event_id, "REMOTE-CALENDAR-REPLAY")

    def test_replay_dead_letter_notification_sends_again(self) -> None:
        store = InMemorySessionStore()
        settings = IntegrationSettings(
            notification_api_url="https://notify.example/send",
            notification_use_mock_fallback=False,
        )
        agent = build_default_agent(
            settings=settings,
            http_client=FlakyNotificationHttpClient(failures=3),
            session_store=store,
        )
        context = agent.run_to_order(_request())

        worker = WorkflowWorker(agent)
        worker.run_once()
        worker.run_once()
        worker.run_once()
        dead_letter_context = store.get(context.session_id)
        replayed = agent.replay_dead_letter_notification(dead_letter_context, "ORDER_COMPLETED")

        self.assertEqual(replayed.notifications[0].status, "SENT")
        self.assertEqual(replayed.notifications[0].retry_count, 0)
        self.assertIn(f"{context.session_id}:1:ORDER_COMPLETED", replayed.notification_keys)

    def test_worker_loop_aggregates_iterations(self) -> None:
        store = InMemorySessionStore()
        agent = build_default_agent(session_store=store)
        agent.run_to_approval(_request())

        result = WorkflowWorker(agent).run_loop(iterations=2, interval_seconds=0, limit=10)

        self.assertEqual(result.iterations, 2)
        self.assertGreaterEqual(result.scanned, 1)
        self.assertGreaterEqual(result.advanced, 1)


class CliRenderTest(unittest.TestCase):
    def test_renders_agent_execution_summaries(self) -> None:
        context = build_default_agent().run_to_order(_request())

        rendered = render_context(context)

        self.assertIn("Agent 执行摘要:", rendered)
        self.assertIn("PolicyAgent.check_policies", rendered)
        self.assertIn("BookingAgent.create_order", rendered)

    def test_renders_refund_estimates_and_change_records(self) -> None:
        agent = build_default_agent()
        context = agent.change_trip(
            agent.run_to_order(_request()),
            new_depart_at="2026-06-03T13:00:00+08:00",
            new_check_in=date(2026, 6, 4),
            new_check_out=date(2026, 6, 6),
        )
        context = agent.sync_calendar(context)

        rendered = render_context(context)

        self.assertIn("退款预估:", rendered)
        self.assertIn("改签记录:", rendered)
        self.assertIn("日历同步:", rendered)

    def test_renders_worker_runs_dead_letters_and_metrics(self) -> None:
        worker_run = WorkerRunRecord(
            run_id="WRK-1",
            started_at="2026-05-14T00:00:00+00:00",
            finished_at="2026-05-14T00:00:01+00:00",
            scanned=2,
            advanced=1,
            skipped=1,
            errors={},
            session_ids=["S-1"],
        )
        dead_letter = DeadLetterNotification(
            session_id="S-1",
            state=TravelState.COMPLETED.value,
            notification=NotificationRecord(
                notification_id="NTF-1",
                event_type="ORDER_COMPLETED",
                channel="im",
                recipient_id="u-demo",
                title="title",
                message="message",
                status="DEAD_LETTER",
                payload={},
                retry_count=3,
                max_retries=3,
                last_error="unavailable",
            ),
        )

        self.assertIn("WRK-1", render_worker_runs([worker_run]))
        self.assertIn("ORDER_COMPLETED", render_dead_letters([dead_letter]))
        self.assertIn("- dead_letters: 1", render_metrics([worker_run], [dead_letter]))
        calendar_dead_letter = CalendarSyncRecord(
            calendar_event_id="CAL-1",
            event_type="TRIP_BOOKED",
            status="DEAD_LETTER",
            user_id="u-demo",
            title="title",
            start_at="2026-06-03",
            end_at="2026-06-05",
            payload={},
            retry_count=3,
            last_error="calendar unavailable",
        )
        self.assertIn(
            "TRIP_BOOKED",
            render_calendar_dead_letters(
                [
                    DeadLetterCalendarSync(
                        session_id="S-1",
                        state=TravelState.COMPLETED.value,
                        calendar_sync=calendar_dead_letter,
                    )
                ]
            ),
        )

    def test_renders_prometheus_metrics_for_agent_and_calendar_records(self) -> None:
        agent = build_default_agent()
        context = agent.sync_calendar(agent.run_to_order(_request()))
        worker_run = WorkerRunRecord(
            run_id="WRK-1",
            started_at="2026-05-14T00:00:00+00:00",
            finished_at="2026-05-14T00:00:01+00:00",
            scanned=1,
            advanced=1,
            skipped=0,
            errors={},
            session_ids=[context.session_id],
        )

        rendered = render_prometheus_metrics([worker_run], [], [context])

        self.assertIn("travel_worker_runs_total 1", rendered)
        self.assertIn('travel_session_states_total{state="COMPLETED"} 1', rendered)
        self.assertIn('travel_agent_executions_total{agent="PolicyAgent",action="check_policies",status="SUCCESS"} 1', rendered)
        self.assertIn('travel_calendar_syncs_total{event_type="TRIP_BOOKED",status="SYNCED",source="mock"} 1', rendered)

    def test_serves_prometheus_metrics_over_http(self) -> None:
        store = InMemorySessionStore()
        agent = build_default_agent(session_store=store)
        agent.sync_calendar(agent.run_to_order(_request()))
        WorkflowWorker(agent).run_once()
        server = create_metrics_server(store, port=0)
        thread = run_metrics_server_in_thread(server)
        host, port = server.server_address
        try:
            with urlopen(f"http://{host}:{port}/health", timeout=5) as response:
                health = response.read().decode("utf-8")
            with urlopen(f"http://{host}:{port}/metrics", timeout=5) as response:
                metrics = response.read().decode("utf-8")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        self.assertEqual(health, "ok\n")
        self.assertIn("travel_worker_runs_total 1", metrics)
        self.assertIn("travel_calendar_syncs_total", metrics)

    def test_builds_otlp_payloads_and_sla_alerts(self) -> None:
        agent = build_default_agent()
        context = agent.sync_calendar(agent.run_to_order(_request()))
        worker_run = WorkerRunRecord(
            run_id="WRK-1",
            started_at="2026-05-14T00:00:00+00:00",
            finished_at="2026-05-14T00:00:01+00:00",
            scanned=1,
            advanced=1,
            skipped=0,
            errors={"S-ERR": "boom"},
            session_ids=[context.session_id],
        )
        dead_letter = DeadLetterNotification(
            session_id=context.session_id,
            state=TravelState.COMPLETED.value,
            notification=NotificationRecord(
                notification_id="NTF-1",
                event_type="ORDER_COMPLETED",
                channel="im",
                recipient_id="u-demo",
                title="title",
                message="message",
                status="DEAD_LETTER",
                payload={},
                retry_count=3,
                max_retries=3,
                last_error="unavailable",
            ),
        )

        traces_payload, metrics_payload, alerts = build_otlp_payloads(
            [worker_run],
            [dead_letter],
            [context],
            service_name="travel-agent-test",
        )

        spans = traces_payload["resourceSpans"][0]["scopeSpans"][0]["spans"]
        metrics = metrics_payload["resourceMetrics"][0]["scopeMetrics"][0]["metrics"]
        alert_types = {alert["alert_type"] for alert in alerts}

        self.assertGreaterEqual(len(spans), len(context.agent_executions) + 1)
        self.assertTrue(any(metric["name"] == "travel.agent.executions" for metric in metrics))
        self.assertTrue(any(metric["name"] == "travel.sla.alerts" for metric in metrics))
        self.assertIn("worker_errors", alert_types)
        self.assertIn("notification_dead_letters", alert_types)

    def test_exports_otlp_http_payloads(self) -> None:
        calls: list[tuple[str, dict[str, Any], str | None]] = []

        def post_json(url: str, payload: dict[str, Any], token: str | None) -> int:
            calls.append((url, payload, token))
            return 200

        traces_payload = {"resourceSpans": [{"scopeSpans": [{"spans": [{"spanId": "1"}]}]}]}
        metrics_payload = {
            "resourceMetrics": [
                {
                    "scopeMetrics": [
                        {
                            "metrics": [
                                {"name": "travel.worker.runs", "sum": {"dataPoints": [{"asInt": "1"}]}},
                                {"name": "travel.sla.alerts", "gauge": {"dataPoints": [{"asInt": "0"}]}},
                            ]
                        }
                    ]
                }
            ]
        }

        result = export_otlp_http(
            "http://collector:4318",
            traces_payload,
            metrics_payload,
            token="otel-token",
            post_json=post_json,
        )

        self.assertEqual([call[0] for call in calls], ["http://collector:4318/v1/traces", "http://collector:4318/v1/metrics"])
        self.assertTrue(all(call[2] == "otel-token" for call in calls))
        self.assertEqual(result.traces_status, 200)
        self.assertEqual(result.metrics_status, 200)
        self.assertEqual(result.span_count, 1)
        self.assertEqual(result.metric_count, 2)
        self.assertIn("OTLP export result:", render_otlp_export_result(result))

    def test_sla_alerts_include_order_failed_and_calendar_failure(self) -> None:
        context = build_default_agent().run_to_order(_request())
        context.state = TravelState.ORDER_FAILED.value
        context.calendar_syncs.append(
            CalendarSyncRecord(
                calendar_event_id="CAL-FAILED",
                event_type="TRIP_BOOKED",
                status="FAILED",
                user_id=context.request.user_id,
                title="calendar failed",
                start_at=context.request.start_date.isoformat(),
                end_at=context.request.end_date.isoformat(),
                payload={},
                source="mock",
            )
        )

        alerts = build_sla_alerts([], [], [context])
        alert_types = {alert["alert_type"] for alert in alerts}

        self.assertIn("order_failed", alert_types)
        self.assertIn("calendar_sync_failed", alert_types)

    def test_renders_storage_health(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "sessions.sqlite3"
            store = SQLiteSessionStore(db_path)
            build_default_agent(session_store=store).run_to_order(_request())

            rendered = render_storage_health(store.health_check())

            self.assertIn("Storage health:", rendered)
            self.assertIn("- ok: True", rendered)
            self.assertIn("- sessions: 1", rendered)


class EvaluationSuiteTest(unittest.TestCase):
    def test_builtin_evaluation_suite_passes_expected_scenarios(self) -> None:
        report = run_evaluation_suite()

        scenario_ids = {result.scenario_id for result in report.scenarios}
        statuses = {result.scenario_id: result.status for result in report.scenarios}

        self.assertEqual(report.failed, 0)
        self.assertIn("happy_path", scenario_ids)
        self.assertIn("policy_over_cap", scenario_ids)
        self.assertIn("approval_rejected", scenario_ids)
        self.assertIn("price_changed", scenario_ids)
        self.assertIn("inventory_expired", scenario_ids)
        self.assertIn("order_failed", scenario_ids)
        self.assertIn("change_failure", scenario_ids)
        self.assertIn("calendar_dead_letter", scenario_ids)
        self.assertTrue(all(status == "PASS" for status in statuses.values()))

    def test_renders_evaluation_report(self) -> None:
        rendered = render_evaluation_report(run_evaluation_suite())

        self.assertIn("Evaluation report:", rendered)
        self.assertIn("happy_path", rendered)
        self.assertIn("- failed: 0", rendered)


class IntegrationAcceptanceTest(unittest.TestCase):
    def test_acceptance_report_marks_mock_only_configuration_action_required(self) -> None:
        report = run_integration_acceptance_report(IntegrationSettings(), include_evaluation=False)
        rendered = render_integration_acceptance_report(report)

        self.assertEqual(report.status, "ACTION_REQUIRED")
        self.assertGreater(len(report.missing_required_endpoints), 0)
        self.assertIn("WARN required_endpoints", rendered)
        self.assertIn("WARN mock_fallback", rendered)
        self.assertIn("WARN session_store", rendered)

    def test_acceptance_report_passes_for_full_real_configuration(self) -> None:
        health = StorageHealth(
            backend="sqlite",
            ok=True,
            schema_version=2,
            session_count=1,
            worker_run_count=1,
            details={"integrity_check": "ok"},
        )

        report = run_integration_acceptance_report(
            _full_acceptance_settings(),
            storage_health=health,
            include_evaluation=False,
        )
        rendered = render_integration_acceptance_report(report)

        self.assertEqual(report.status, "PASS")
        self.assertEqual(report.configured_required_endpoints, report.required_endpoints)
        self.assertIn("- status: PASS", rendered)
        self.assertIn("PASS session_store", rendered)


class SmokeProbeTest(unittest.TestCase):
    def test_smoke_probes_skip_unconfigured_endpoints(self) -> None:
        report = run_smoke_probes(IntegrationSettings(), SmokeProbeHttpClient({}))

        self.assertEqual(report.status, "SKIP")
        self.assertEqual(report.failed, 0)
        self.assertGreater(report.skipped, 0)

    def test_smoke_probes_call_configured_endpoints_with_dry_run_payloads(self) -> None:
        settings = _full_acceptance_settings()
        http = SmokeProbeHttpClient(
            {
                "https://policy.example/check": {"policy": {}},
                "https://policy.example/transport": {"transport_policy": {}},
                "https://hotel.example/search": {"hotels": []},
                "https://transport.example/search": {"transports": []},
                "https://hotel.example/price": {"price_check": {}},
                "https://hotel.example/lock": {"inventory_lock": {}},
                "https://hotel.example/release": {"compensation": {}},
                "https://oa.example/create": {"approval": {}},
                "https://oa.example/status": {"approval": {}},
                "https://oa.example/cancel": {"compensation": {}},
                "https://order.example/create": {"order": {}},
                "https://order.example/status": {"order": {}},
                "https://order.example/cancel": {"compensation": {}},
                "https://transport.example/order": {"transport_order": {}},
                "https://transport.example/status": {"transport_order": {}},
                "https://transport.example/cancel": {"compensation": {}},
                "https://refund.example/estimate": {"refund_estimate": {}},
                "https://refund.example/confirm": {"refund_confirmation": {}},
                "https://oa.example/change": {"approval": {}},
                "https://hotel.example/change": {"change": {}},
                "https://transport.example/change": {"change": {}},
                "https://change.example/compensate": {"compensation": {}},
                "https://notify.example/send": {"notification": {}},
                "https://calendar.example/sync": {"calendar": {}},
            }
        )

        report = run_smoke_probes(settings, http, include_optional=False)
        rendered = render_smoke_probe_report(report)

        self.assertEqual(report.status, "PASS")
        self.assertEqual(report.passed, 24)
        self.assertTrue(all(call[1]["dry_run"] is True for call in http.calls))
        self.assertTrue(all(call[1]["smoke_test"] is True for call in http.calls))
        self.assertIn("- status: PASS", rendered)


class ReleaseControlTest(unittest.TestCase):
    def test_rollout_decision_allows_explicit_user(self) -> None:
        policy = RolloutPolicy(enabled=False, allowed_users={"u-demo"})

        decision = evaluate_rollout(policy, user_id="u-demo")

        self.assertTrue(decision.enabled)
        self.assertEqual(decision.status, "ENABLED")

    def test_rollout_decision_honors_rollback(self) -> None:
        policy = RolloutPolicy(enabled=True, rollback_enabled=True, rollback_reason="incident")

        decision = evaluate_rollout(policy, user_id="u-demo")

        self.assertFalse(decision.enabled)
        self.assertEqual(decision.status, "ROLLED_BACK")


class OperationsReadinessTest(unittest.TestCase):
    def test_renders_operations_runbook(self) -> None:
        rendered = render_operations_runbook(build_operations_runbook())

        self.assertIn("Operations runbook:", rendered)
        self.assertIn("上线准备", rendered)
        self.assertIn("权限中心不可用演练", rendered)

    def test_operations_alerts_include_permission_and_audit_failures(self) -> None:
        denied = evaluate_permission(
            PermissionPolicy(enabled=True, blocked_actions={"book_order"}),
            user_id="u-demo",
            action="book_order",
            roles={"traveler"},
        )

        alerts = build_operations_alerts(
            permission_decisions=[denied],
            audit_sink_results=[HttpAuditSink("https://audit.example/events", http_client=FailingHttpClient()).write([])],
        )
        alert_types = {alert["alert_type"] for alert in alerts}

        self.assertIn("permission_denied", alert_types)
        self.assertIn("audit_sink_failed", alert_types)

    def test_operations_drill_report_covers_expected_scenarios(self) -> None:
        report = build_operations_drill_report(IntegrationSettings())
        rendered = render_operations_drill_report(report)
        statuses = {drill.scenario: drill.status for drill in report.drills}
        alert_types = {alert["alert_type"] for alert in report.alerts}

        self.assertEqual(statuses["permission_unavailable"], "PASS")
        self.assertEqual(statuses["audit_sink_unavailable"], "PASS")
        self.assertEqual(statuses["supplier_order_failure"], "PASS")
        self.assertEqual(statuses["rollback_trigger"], "PASS")
        self.assertIn("permission_center_fallback", alert_types)
        self.assertIn("permission_denied", alert_types)
        self.assertIn("audit_sink_failed", alert_types)
        self.assertIn("order_failed", alert_types)
        self.assertIn("Operations drill report:", rendered)

    def test_renders_operations_alert_formats(self) -> None:
        alerts = [{"alert_type": "audit_sink_failed", "severity": "critical", "message": "audit down", "value": 2}]

        self.assertIn("critical audit_sink_failed", render_operations_alerts(alerts))
        self.assertIn('"alert_type": "audit_sink_failed"', render_operations_alerts_json(alerts))
        self.assertIn('travel_operations_alerts{alert_type="audit_sink_failed"', render_operations_alerts_prometheus(alerts))

    def test_exports_operations_alerts_to_http_sink(self) -> None:
        http = CapturingAnyHttpClient({"https://alerts.example/events": {"ok": True, "accepted": 1}})

        result = export_operations_alerts_http(
            [{"alert_type": "order_failed", "severity": "critical", "message": "order failed", "value": 1}],
            endpoint="https://alerts.example/events",
            token="alert-token",
            http_client=http,
        )
        rendered = render_operations_alert_export_result(result)

        self.assertTrue(result.ok)
        self.assertEqual(result.delivered, 1)
        self.assertEqual(http.calls[0][2], "alert-token")
        self.assertEqual(http.calls[0][1]["source"], "travel-agent")
        self.assertIn("Operations alert export:", rendered)

    def test_operations_alert_export_reports_failures(self) -> None:
        result = export_operations_alerts_http(
            [{"alert_type": "audit_sink_failed", "severity": "critical", "message": "audit down", "value": 1}],
            endpoint="https://alerts.example/events",
            http_client=FailingHttpClient(),
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.failed, 1)

    def test_operations_drill_gate_exit_codes(self) -> None:
        report = build_operations_drill_report(IntegrationSettings())

        gate = evaluate_operations_drill_gate(report)
        rendered = render_operations_drill_gate_result(gate)

        self.assertTrue(gate.passed)
        self.assertEqual(gate.exit_code, 0)
        self.assertIn("Operations drill gate:", rendered)

    def test_builds_operations_dashboard(self) -> None:
        context = build_default_agent().run_to_order(_request())
        context.state = TravelState.ORDER_FAILED.value
        worker_run = WorkerRunRecord(
            run_id="WRK-OPS",
            started_at="2026-05-14T00:00:00+00:00",
            finished_at="2026-05-14T00:00:01+00:00",
            scanned=1,
            advanced=0,
            skipped=0,
            errors={context.session_id: "boom"},
            session_ids=[context.session_id],
        )

        dashboard = build_operations_dashboard(
            worker_runs=[worker_run],
            sessions=[context],
            alerts=[{"alert_type": "order_failed", "severity": "critical", "message": "failed", "value": 1}],
        )
        rendered = render_operations_dashboard(dashboard)

        self.assertEqual(dashboard.worker_errors, 1)
        self.assertEqual(dashboard.critical_alerts, 1)
        self.assertEqual(dashboard.state_counts[TravelState.ORDER_FAILED.value], 1)
        self.assertIn("Operations dashboard:", rendered)
        self.assertIn("ORDER_FAILED", rendered)

    def test_renders_alert_route_rules(self) -> None:
        rules = build_alert_route_rules()
        rendered = render_alert_route_rules(rules)
        rendered_json = render_alert_route_rules_json(rules)

        self.assertTrue(any(rule.alert_type == "order_failed" for rule in rules))
        self.assertIn("Alert route rules:", rendered)
        self.assertIn('"alert_type": "order_failed"', rendered_json)

    def test_builds_alert_route_rules_from_config(self) -> None:
        rules = build_alert_route_rules(
            '{"rules":[{"alert_type":"custom_alert","severity":"critical","route":"custom-oncall","escalation":"page","silence_hint":"owner approval"}]}'
        )

        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0].alert_type, "custom_alert")
        self.assertEqual(rules[0].route, "custom-oncall")

    def test_opens_oncall_ticket(self) -> None:
        report = build_operations_drill_report(IntegrationSettings())
        http = CapturingAnyHttpClient({"https://oncall.example/tickets": {"ok": True, "ticket_id": "INC-1"}})

        result = open_oncall_ticket_http(
            report,
            endpoint="https://oncall.example/tickets",
            token="oncall-token",
            http_client=http,
        )
        rendered = render_oncall_ticket_result(result)

        self.assertTrue(result.ok)
        self.assertEqual(result.ticket_id, "INC-1")
        self.assertEqual(http.calls[0][2], "oncall-token")
        self.assertEqual(http.calls[0][1]["source"], "travel-agent")
        self.assertIn("OnCall ticket:", rendered)

    def test_oncall_ticket_reports_failures(self) -> None:
        result = open_oncall_ticket_http(
            build_operations_drill_report(IntegrationSettings()),
            endpoint="https://oncall.example/tickets",
            http_client=FailingHttpClient(),
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.failed, 1)

    def test_fetches_oncall_ticket_status(self) -> None:
        http = CapturingAnyHttpClient(
            {
                "https://oncall.example/status": {
                    "ticket": {
                        "ticket_id": "INC-1",
                        "status": "ACKED",
                        "assignee": "ops-user",
                        "updated_at": "2026-05-19T10:00:00+00:00",
                        "detail": "accepted",
                    }
                }
            }
        )

        status = fetch_oncall_ticket_status_http(
            "INC-1",
            endpoint="https://oncall.example/status",
            token="oncall-token",
            http_client=http,
        )
        rendered = render_oncall_ticket_status(status)

        self.assertEqual(status.status, "ACKED")
        self.assertEqual(status.assignee, "ops-user")
        self.assertEqual(http.calls[0][1]["ticket_id"], "INC-1")
        self.assertIn("OnCall ticket status:", rendered)

    def test_dashboard_snapshot_round_trips_as_dict(self) -> None:
        dashboard = build_operations_dashboard(
            alerts=[{"alert_type": "order_failed", "severity": "critical", "message": "failed", "value": 1}]
        )
        snapshot = build_operations_dashboard_snapshot(
            dashboard,
            alerts=[{"alert_type": "order_failed", "severity": "critical", "message": "failed", "value": 1}],
            snapshot_id="DASH-1",
            created_at="2026-05-19T10:00:00+00:00",
        )

        reloaded = operations_dashboard_snapshot_from_dict(operations_dashboard_snapshot_to_dict(snapshot))
        rendered = render_operations_dashboard_snapshots([reloaded])

        self.assertEqual(reloaded.snapshot_id, "DASH-1")
        self.assertEqual(reloaded.dashboard.critical_alerts, 1)
        self.assertIn("DASH-1", rendered)

    def test_dashboard_trend_report_detects_alert_growth(self) -> None:
        first = build_operations_dashboard_snapshot(
            build_operations_dashboard(
                alerts=[{"alert_type": "order_failed", "severity": "critical", "message": "failed", "value": 1}]
            ),
            alerts=[{"alert_type": "order_failed", "severity": "critical", "message": "failed", "value": 1}],
            snapshot_id="DASH-A",
            created_at="2026-05-19T10:00:00+00:00",
        )
        second = build_operations_dashboard_snapshot(
            build_operations_dashboard(
                alerts=[
                    {"alert_type": "order_failed", "severity": "critical", "message": "failed", "value": 1},
                    {"alert_type": "audit_sink_failed", "severity": "critical", "message": "audit down", "value": 1},
                ]
            ),
            alerts=[
                {"alert_type": "order_failed", "severity": "critical", "message": "failed", "value": 1},
                {"alert_type": "audit_sink_failed", "severity": "critical", "message": "audit down", "value": 1},
            ],
            snapshot_id="DASH-B",
            created_at="2026-05-19T10:05:00+00:00",
        )

        report = build_operations_dashboard_trend_report([second, first], window=2)
        rendered = render_operations_dashboard_trend_report(report)

        self.assertEqual(report.latest_snapshot.snapshot_id, "DASH-B")
        self.assertTrue(any(metric.name == "critical_alerts" and metric.delta == 1 for metric in report.metrics))
        self.assertTrue(any("critical_alerts" in anomaly for anomaly in report.anomalies))
        self.assertIn("Operations dashboard trends:", rendered)

    def test_trend_alerts_create_action_items_and_knowledge(self) -> None:
        first = build_operations_dashboard_snapshot(
            build_operations_dashboard(),
            snapshot_id="DASH-T1",
            created_at="2026-05-19T10:00:00+00:00",
        )
        second = build_operations_dashboard_snapshot(
            build_operations_dashboard(
                alerts=[{"alert_type": "order_failed", "severity": "critical", "message": "failed", "value": 1}]
            ),
            alerts=[{"alert_type": "order_failed", "severity": "critical", "message": "failed", "value": 1}],
            snapshot_id="DASH-T2",
            created_at="2026-05-19T10:05:00+00:00",
        )
        trend = build_operations_dashboard_trend_report([first, second], window=2)
        rules = build_operations_trend_alert_rules(
            '{"rules":[{"metric":"critical_alerts","severity":"critical","route":"ops","owner":"ops","delta_threshold":1,"action_template":"Handle {metric} now"}]}'
        )

        alerts = evaluate_operations_trend_alerts(trend, rules)
        action_items = build_trend_alert_action_items(alerts, eta="2026-05-20T12:00:00+00:00")
        closed = close_operations_action_item(action_items[0], "verified fixed", "2026-05-20T13:00:00+00:00")
        entries = build_operations_knowledge_entries(trend_alerts=alerts, action_items=[closed])

        reloaded_alert = operations_trend_alert_from_dict(operations_trend_alert_to_dict(alerts[0]))
        reloaded_action = operations_action_item_from_dict(operations_action_item_to_dict(closed))
        reloaded_entry = operations_knowledge_entry_from_dict(operations_knowledge_entry_to_dict(entries[0]))

        self.assertEqual(alerts[0].metric, "critical_alerts")
        self.assertEqual(reloaded_alert.severity, "critical")
        self.assertEqual(reloaded_action.status, "CLOSED")
        self.assertTrue(reloaded_entry.recommended_actions)
        self.assertIn("Operations trend alerts:", render_operations_trend_alerts(alerts))
        self.assertIn('"metric": "critical_alerts"', render_operations_trend_alerts_json(alerts))
        self.assertIn("Operations action items:", render_operations_action_items([closed]))
        self.assertIn("Operations knowledge entries:", render_operations_knowledge_entries(entries))

    def test_builds_operations_multidimensional_view(self) -> None:
        request = TravelRequest(
            user_id="u-demo",
            origin_city="北京",
            destination_city="上海",
            start_date=date(2026, 6, 3),
            end_date=date(2026, 6, 5),
            purpose="客户会议",
            venue="上海张江人工智能岛",
            budget_per_night=650,
            preferences=["可取消"],
            department="sales",
        )
        context = build_default_agent().run_to_order(request)
        context.state = TravelState.ORDER_FAILED.value
        context.order_cancellation = context.order_cancellation or None
        worker_run = WorkerRunRecord(
            run_id="WRK-MD",
            started_at="2026-05-14T00:00:00+00:00",
            finished_at="2026-05-14T00:00:01+00:00",
            scanned=1,
            advanced=0,
            skipped=0,
            errors={context.session_id: "boom"},
            session_ids=[context.session_id],
        )

        view = build_operations_multidimensional_view(
            sessions=[context],
            alerts=[{"alert_type": "order_failed", "severity": "critical", "message": "failed", "value": 1}],
            worker_runs=[worker_run],
            limit=3,
        )
        rendered = render_operations_multidimensional_view(view)

        self.assertEqual(view.total_sessions, 1)
        self.assertEqual(view.worker_errors, 1)
        self.assertEqual(view.alert_counts["order_failed"], 1)
        self.assertTrue(any(group.name == "departments" for group in view.groups))
        self.assertIn("Operations multi-dimensional view:", rendered)
        self.assertIn("sales", rendered)

    def test_builds_operations_postmortem_report(self) -> None:
        context = build_default_agent().run_to_order(_request())
        context.state = TravelState.ORDER_FAILED.value
        dashboard = build_operations_dashboard(
            sessions=[context],
            alerts=[{"alert_type": "order_failed", "severity": "critical", "message": "failed", "value": 1}],
        )
        snapshot = build_operations_dashboard_snapshot(
            dashboard,
            alerts=[{"alert_type": "order_failed", "severity": "critical", "message": "failed", "value": 1}],
            snapshot_id="DASH-PM",
            created_at="2026-05-19T10:00:00+00:00",
        )
        ticket = fetch_oncall_ticket_status_http(
            "INC-PM",
            endpoint="https://oncall.example/status",
            http_client=CapturingAnyHttpClient(
                {
                    "https://oncall.example/status": {
                        "ticket": {
                            "ticket_id": "INC-PM",
                            "status": "ACKED",
                            "assignee": "ops",
                            "updated_at": "2026-05-19T10:05:00+00:00",
                        }
                    }
                }
            ),
        )
        worker_run = WorkerRunRecord(
            run_id="WRK-PM",
            started_at="2026-05-19T10:00:00+00:00",
            finished_at="2026-05-19T10:00:01+00:00",
            scanned=1,
            advanced=0,
            skipped=0,
            errors={context.session_id: "boom"},
            session_ids=[context.session_id],
        )

        report = build_operations_postmortem_report(
            sessions=[context],
            snapshots=[snapshot],
            oncall_statuses=[ticket],
            alerts=[{"alert_type": "order_failed", "severity": "critical", "message": "failed", "value": 1}],
            worker_runs=[worker_run],
            drill_report=build_operations_drill_report(IntegrationSettings(), sessions=[context]),
        )
        rendered = render_operations_postmortem_report(report)

        self.assertEqual(report.incident_id, "INC-PM")
        self.assertEqual(report.severity, "critical")
        self.assertIn(context.session_id, report.related_sessions)
        self.assertTrue(any("Supplier order" in cause for cause in report.root_causes))
        self.assertIn("Operations incident postmortem:", rendered)

    def test_postmortem_creates_action_items_and_knowledge(self) -> None:
        context = build_default_agent().run_to_order(_request())
        context.state = TravelState.ORDER_FAILED.value
        report = build_operations_postmortem_report(
            sessions=[context],
            alerts=[{"alert_type": "order_failed", "severity": "critical", "message": "failed", "value": 1}],
            drill_report=build_operations_drill_report(IntegrationSettings(), sessions=[context]),
            incident_id="INC-ACTION",
            generated_at="2026-05-19T10:00:00+00:00",
        )

        items = build_postmortem_action_items(report, owner="ops", eta="2026-05-20T12:00:00+00:00")
        entries = build_operations_knowledge_entries(postmortem=report, action_items=items)

        self.assertTrue(items)
        self.assertEqual(items[0].source_type, "postmortem")
        self.assertEqual(items[0].source_id, "INC-ACTION")
        self.assertTrue(any(entry.topic == report.primary_signal for entry in entries))
        self.assertIn("Operations action items:", render_operations_action_items(items))

    def test_searches_operations_knowledge_and_summarizes_closed_loop(self) -> None:
        trend_alert = operations_trend_alert_from_dict(
            {
                "alert_id": "TREND-SEARCH",
                "metric": "critical_alerts",
                "severity": "critical",
                "route": "incident-oncall",
                "escalation": "page",
                "owner": "platform-oncall",
                "current": 2,
                "previous": 1,
                "delta": 1,
                "delta_percent": 100.0,
                "reason": "critical alert grew",
                "action_item": "Review critical alerts",
            }
        )
        action = operations_action_item_from_dict(
            {
                "action_id": "ACT-SEARCH",
                "source_type": "trend_alert",
                "source_id": trend_alert.alert_id,
                "title": "Review critical alerts",
                "owner": "platform-oncall",
                "status": "CLOSED",
                "eta": None,
                "created_at": "2026-05-19T00:00:00+00:00",
                "updated_at": "2026-05-19T02:00:00+00:00",
                "evidence": ["metric=critical_alerts"],
                "closure_note": "alert owner confirmed",
            }
        )
        entries = build_operations_knowledge_entries(trend_alerts=[trend_alert], action_items=[action])

        search = search_operations_knowledge(entries, "critical alerts", limit=3)
        closed_loop = build_operations_closed_loop_report(
            trend_alerts=[trend_alert],
            action_items=[action],
            knowledge_entries=entries,
            generated_at="2026-05-20T00:00:00+00:00",
        )

        self.assertTrue(search.hits)
        self.assertEqual(closed_loop.closure_rate, 100.0)
        self.assertEqual(closed_loop.action_items_closed, 1)
        self.assertIn("Operations knowledge search:", render_operations_knowledge_search_report(search))
        self.assertIn("Operations closed-loop report:", render_operations_closed_loop_report(closed_loop))

    def test_action_sla_escalates_overdue_open_items(self) -> None:
        item = operations_action_item_from_dict(
            {
                "action_id": "ACT-SLA",
                "source_type": "postmortem",
                "source_id": "INC-SLA",
                "title": "Recover audit sink",
                "owner": "compliance-platform-oncall",
                "status": "OPEN",
                "eta": None,
                "created_at": "2026-05-18T00:00:00+00:00",
                "updated_at": "2026-05-18T00:00:00+00:00",
                "evidence": ["audit_sink_failed"],
                "closure_note": None,
            }
        )
        policy = build_operations_action_sla_policy(
            '{"warning_after_hours":12,"critical_after_hours":24,"owner_routes":{"compliance-platform-oncall":"compliance-route"}}'
        )

        report = evaluate_operations_action_sla(
            [item],
            policy=policy,
            now="2026-05-20T00:00:00+00:00",
        )
        rendered = render_operations_action_sla_report(report)

        self.assertEqual(len(report.findings), 1)
        self.assertEqual(report.findings[0].severity, "critical")
        self.assertEqual(report.findings[0].route, "compliance-route")
        self.assertIn("Operations action SLA:", rendered)


class PermissionPolicyTest(unittest.TestCase):
    def test_permission_policy_allows_matching_role(self) -> None:
        policy = PermissionPolicy(enabled=True, required_roles={"traveler"})

        decision = evaluate_permission(policy, user_id="u-demo", action="plan_trip", roles={"traveler"})

        self.assertTrue(decision.allowed)
        self.assertEqual(decision.status, "ALLOW")
        self.assertIn("ALLOW", render_permission_decision(decision))

    def test_permission_policy_denies_missing_role_in_agent_flow(self) -> None:
        policy = PermissionPolicy(enabled=True, required_roles={"travel_admin"})
        agent = build_default_agent(permission_policy=policy)

        with self.assertRaises(PermissionDeniedError):
            agent.plan(_request())

    def test_permission_policy_can_block_specific_action(self) -> None:
        policy = PermissionPolicy(enabled=True, blocked_actions={"book_order"}, required_roles={"traveler"})
        agent = build_default_agent(permission_policy=policy)
        context = agent.run_to_approval(_request_with_roles(["traveler"]))
        context = agent.refresh_approval_status(context)

        with self.assertRaises(PermissionDeniedError):
            agent.book_after_approval(context)

    def test_permission_policy_uses_remote_permission_center(self) -> None:
        http = CapturingAnyHttpClient(
            {
                "https://iam.example/check": {
                    "decision": {
                        "allowed": False,
                        "status": "DENY",
                        "reasons": ["remote denied"],
                        "source": "iam",
                    }
                }
            }
        )
        policy = PermissionPolicy(enabled=True, api_url="https://iam.example/check", api_token="iam-token")

        decision = evaluate_permission(
            policy,
            user_id="u-demo",
            action="plan_trip",
            roles={"traveler"},
            http_client=http,
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.source, "iam")
        self.assertEqual(http.calls[0][2], "iam-token")

    def test_permission_policy_falls_back_to_local_policy_when_remote_unavailable(self) -> None:
        policy = PermissionPolicy(
            enabled=True,
            api_url="https://iam.example/check",
            required_roles={"traveler"},
        )

        decision = evaluate_permission(
            policy,
            user_id="u-demo",
            action="plan_trip",
            roles={"traveler"},
            http_client=FailingHttpClient(),
        )

        self.assertTrue(decision.allowed)
        self.assertEqual(decision.source, "local")


class DataGovernanceTest(unittest.TestCase):
    def test_redacts_sensitive_payload_fields(self) -> None:
        result = redact_payload(
            {
                "user_id": "u-demo",
                "phone": "13800000000",
                "traveler": {"id_card_no": "110101199001010011"},
                "items": [{"email": "user@example.com"}, {"hotel_id": "H-1"}],
            }
        )

        self.assertEqual(result.redacted["phone"], "***")
        self.assertEqual(result.redacted["traveler"]["id_card_no"], "***")
        self.assertEqual(result.redacted["items"][0]["email"], "***")
        self.assertIn("phone", result.redacted_keys)
        self.assertIn("traveler.id_card_no", result.redacted_keys)

    def test_builds_audit_event_from_redacted_payload(self) -> None:
        event = build_audit_event("submit_approval", {"phone": "13800000000", "session_id": "S-1"})

        self.assertEqual(event.event_type, "submit_approval")
        self.assertEqual(event.detail, "payload redacted")
        self.assertIn("phone", event.redacted_keys)
        self.assertEqual(event.redacted_payload["phone"], "***")


class ReleaseReadinessTest(unittest.TestCase):
    def test_release_readiness_blocks_mock_only_configuration(self) -> None:
        report = run_release_readiness_report(IntegrationSettings())
        rendered = render_release_readiness_report(report)

        self.assertEqual(report.status, "FAIL")
        self.assertIn("WARN mock_fallback", rendered)
        self.assertIn("FAIL session_store", rendered)

    def test_release_readiness_passes_for_full_configuration_with_tokens(self) -> None:
        report = run_release_readiness_report(
            _full_acceptance_settings_with_tokens(),
            rollout_policy=RolloutPolicy(enabled=True, percentage=10, rollback_runbook_url="https://runbook.example"),
            permission_policy=PermissionPolicy(
                enabled=True,
                required_roles={"traveler"},
                api_url="https://iam.example/check",
                api_token="iam-token",
            ),
        )
        rendered = render_release_readiness_report(report)

        self.assertEqual(report.status, "PASS")
        self.assertIn("PASS api_tokens", rendered)
        self.assertIn("PASS rollout_control", rendered)
        self.assertIn("PASS permission_policy", rendered)
        self.assertIn("PASS audit_log_sink", rendered)
        self.assertIn("PASS auditability", rendered)

    def test_release_gate_fails_on_readiness_fail(self) -> None:
        report = run_release_readiness_report(IntegrationSettings())

        gate = evaluate_release_gate(report)
        rendered = render_release_gate_result(gate)

        self.assertFalse(gate.passed)
        self.assertEqual(gate.exit_code, 1)
        self.assertIn("Release gate:", rendered)

    def test_release_readiness_warns_for_external_permission_and_audit_tokens(self) -> None:
        report = run_release_readiness_report(
            IntegrationSettings(
                permission_api_url="https://iam.example/check",
                audit_log_api_url="https://audit.example/events",
            )
        )
        rendered = render_release_readiness_report(report)

        self.assertIn("permission", rendered)
        self.assertIn("audit_log", rendered)


def _request(budget_per_night: int = 650) -> TravelRequest:
    return TravelRequest(
        user_id="u-demo",
        origin_city="北京",
        destination_city="上海",
        start_date=date(2026, 6, 3),
        end_date=date(2026, 6, 5),
        purpose="客户会议",
        venue="上海张江人工智能岛",
        budget_per_night=budget_per_night,
        preferences=["可取消"],
    )


def _request_with_roles(roles: list[str]) -> TravelRequest:
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
        roles=roles,
    )


def _full_acceptance_settings() -> IntegrationSettings:
    return IntegrationSettings(
        policy_api_url="https://policy.example/check",
        transport_policy_api_url="https://policy.example/transport",
        hotel_inventory_api_url="https://hotel.example/search",
        hotel_price_check_api_url="https://hotel.example/price",
        hotel_inventory_lock_api_url="https://hotel.example/lock",
        hotel_inventory_release_api_url="https://hotel.example/release",
        oa_approval_api_url="https://oa.example/create",
        oa_approval_status_api_url="https://oa.example/status",
        oa_approval_cancel_api_url="https://oa.example/cancel",
        order_api_url="https://order.example/create",
        order_status_api_url="https://order.example/status",
        order_cancel_api_url="https://order.example/cancel",
        refund_estimate_api_url="https://refund.example/estimate",
        refund_confirm_api_url="https://refund.example/confirm",
        change_approval_api_url="https://oa.example/change",
        change_failure_compensation_api_url="https://change.example/compensate",
        hotel_change_api_url="https://hotel.example/change",
        transport_inventory_api_url="https://transport.example/search",
        transport_order_api_url="https://transport.example/order",
        transport_order_status_api_url="https://transport.example/status",
        transport_order_cancel_api_url="https://transport.example/cancel",
        transport_change_api_url="https://transport.example/change",
        notification_api_url="https://notify.example/send",
        calendar_api_url="https://calendar.example/sync",
        use_mock_fallback=False,
        notification_use_mock_fallback=False,
        calendar_use_mock_fallback=False,
        session_store_backend="sqlite",
        session_db_path="travel-agent-acceptance.sqlite3",
    )


def _full_acceptance_settings_with_tokens() -> IntegrationSettings:
    settings = _full_acceptance_settings()
    return IntegrationSettings(
        policy_api_url=settings.policy_api_url,
        transport_policy_api_url=settings.transport_policy_api_url,
        hotel_inventory_api_url=settings.hotel_inventory_api_url,
        hotel_price_check_api_url=settings.hotel_price_check_api_url,
        hotel_inventory_lock_api_url=settings.hotel_inventory_lock_api_url,
        hotel_inventory_release_api_url=settings.hotel_inventory_release_api_url,
        oa_approval_api_url=settings.oa_approval_api_url,
        oa_approval_status_api_url=settings.oa_approval_status_api_url,
        oa_approval_cancel_api_url=settings.oa_approval_cancel_api_url,
        order_api_url=settings.order_api_url,
        order_status_api_url=settings.order_status_api_url,
        order_cancel_api_url=settings.order_cancel_api_url,
        refund_estimate_api_url=settings.refund_estimate_api_url,
        refund_confirm_api_url=settings.refund_confirm_api_url,
        change_approval_api_url=settings.change_approval_api_url,
        change_failure_compensation_api_url=settings.change_failure_compensation_api_url,
        hotel_change_api_url=settings.hotel_change_api_url,
        transport_inventory_api_url=settings.transport_inventory_api_url,
        transport_order_api_url=settings.transport_order_api_url,
        transport_order_status_api_url=settings.transport_order_status_api_url,
        transport_order_cancel_api_url=settings.transport_order_cancel_api_url,
        transport_change_api_url=settings.transport_change_api_url,
        notification_api_url=settings.notification_api_url,
        calendar_api_url=settings.calendar_api_url,
        permission_api_url="https://iam.example/check",
        audit_log_api_url="https://audit.example/events",
        alert_api_url="https://alerts.example/events",
        oncall_api_url="https://oncall.example/tickets",
        policy_api_token="policy-token",
        transport_api_token="transport-token",
        hotel_inventory_api_token="hotel-token",
        oa_approval_api_token="oa-token",
        order_api_token="order-token",
        notification_api_token="notification-token",
        calendar_api_token="calendar-token",
        permission_api_token="iam-token",
        audit_log_api_token="audit-token",
        alert_api_token="alert-token",
        oncall_api_token="oncall-token",
        use_mock_fallback=False,
        notification_use_mock_fallback=False,
        calendar_use_mock_fallback=False,
        session_store_backend="sqlite",
        session_db_path=settings.session_db_path,
    )


class StubHttpClient:
    def __init__(self, responses: dict[str, dict[str, Any]]) -> None:
        self.responses = responses

    def post_json(self, url: str, payload: dict[str, Any], token: str | None = None) -> dict[str, Any]:
        del payload, token
        return self.responses[url]


class CapturingHttpClient(StubHttpClient):
    def __init__(self, responses: dict[str, dict[str, Any]]) -> None:
        super().__init__(responses)
        self.payloads: dict[str, list[dict[str, Any]]] = {}

    def post_json(self, url: str, payload: dict[str, Any], token: str | None = None) -> dict[str, Any]:
        del token
        self.payloads.setdefault(url, []).append(payload)
        return self.responses[url]


class CapturingAnyHttpClient:
    def __init__(self, responses: dict[str, dict[str, Any]]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, dict[str, Any], str | None]] = []

    def post_json(self, url: str, payload: dict[str, Any], token: str | None = None) -> dict[str, Any]:
        self.calls.append((url, payload, token))
        return self.responses[url]


class FakeSessionStoreHttpClient:
    def __init__(self) -> None:
        self.sessions: dict[str, dict[str, Any]] = {}
        self.worker_runs: list[dict[str, Any]] = []
        self.dashboard_snapshots: list[dict[str, Any]] = []
        self.oncall_statuses: list[dict[str, Any]] = []
        self.trend_alerts: list[dict[str, Any]] = []
        self.action_items: list[dict[str, Any]] = []
        self.knowledge_entries: list[dict[str, Any]] = []
        self.calls: list[tuple[str, dict[str, Any], str | None]] = []

    def post_json(self, url: str, payload: dict[str, Any], token: str | None = None) -> dict[str, Any]:
        self.calls.append((url, payload, token))
        path = "/" + url.split("/", 3)[3].split("/", 1)[1]
        if path == "/sessions/save":
            session_id = str(payload["session_id"])
            existing = self.sessions.get(session_id)
            version = int(existing["version"]) + 1 if existing else 1
            self.sessions[session_id] = self._session_record(payload, version, existing)
            return {"ok": True, "version": version}
        if path == "/sessions/save-if-version":
            session_id = str(payload["session_id"])
            existing = self.sessions.get(session_id)
            expected_version = int(payload["expected_version"])
            if existing is None:
                if expected_version != 0:
                    return {"ok": False, "error": "version mismatch"}
                version = 1
            elif int(existing["version"]) != expected_version:
                return {"ok": False, "error": "version mismatch"}
            else:
                version = expected_version + 1
            self.sessions[session_id] = self._session_record(payload, version, existing)
            return {"ok": True, "version": version}
        if path == "/sessions/get":
            return {"session": self.sessions[str(payload["session_id"])]}
        if path == "/sessions/list-by-states":
            states = set(payload["states"])
            sessions = [session for session in self.sessions.values() if session["state"] in states]
            return {"sessions": sessions[: int(payload["limit"])]}
        if path == "/sessions/list-recent":
            return {"sessions": list(reversed(list(self.sessions.values())))[0 : int(payload["limit"])]}
        if path == "/worker-runs/record":
            self.worker_runs.append(dict(payload["worker_run"]))
            return {"ok": True}
        if path == "/worker-runs/list":
            return {"worker_runs": list(reversed(self.worker_runs))[0 : int(payload["limit"])]}
        if path == "/operations/dashboard-snapshots/record":
            self.dashboard_snapshots.append(dict(payload["snapshot"]))
            return {"ok": True}
        if path == "/operations/dashboard-snapshots/list":
            return {"snapshots": list(reversed(self.dashboard_snapshots))[0 : int(payload["limit"])]}
        if path == "/operations/oncall-statuses/record":
            self.oncall_statuses.append(dict(payload["status"]))
            return {"ok": True}
        if path == "/operations/oncall-statuses/list":
            return {"statuses": list(reversed(self.oncall_statuses))[0 : int(payload["limit"])]}
        if path == "/operations/trend-alerts/record":
            self.trend_alerts.append(dict(payload["alert"]))
            return {"ok": True}
        if path == "/operations/trend-alerts/list":
            return {"alerts": list(reversed(self.trend_alerts))[0 : int(payload["limit"])]}
        if path == "/operations/action-items/record":
            self.action_items = [
                item for item in self.action_items if item.get("action_id") != payload["item"].get("action_id")
            ]
            self.action_items.append(dict(payload["item"]))
            return {"ok": True}
        if path == "/operations/action-items/list":
            return {"items": list(reversed(self.action_items))[0 : int(payload["limit"])]}
        if path == "/operations/knowledge/record":
            self.knowledge_entries.append(dict(payload["entry"]))
            return {"ok": True}
        if path == "/operations/knowledge/list":
            return {"entries": list(reversed(self.knowledge_entries))[0 : int(payload["limit"])]}
        if path == "/health":
            return {
                "backend": "http-json",
                "ok": True,
                "schema_version": 4,
                "session_count": len(self.sessions),
                "worker_run_count": len(self.worker_runs),
                "details": {
                    "contract": "session-store-v1",
                    "dashboard_snapshots": str(len(self.dashboard_snapshots)),
                    "oncall_ticket_statuses": str(len(self.oncall_statuses)),
                    "operations_trend_alerts": str(len(self.trend_alerts)),
                    "operations_action_items": str(len(self.action_items)),
                    "operations_knowledge_entries": str(len(self.knowledge_entries)),
                },
            }
        raise AssertionError(f"Unexpected HTTP store URL: {url}")

    @staticmethod
    def _session_record(
        payload: dict[str, Any],
        version: int,
        existing: dict[str, Any] | None,
    ) -> dict[str, Any]:
        created_at = existing["created_at"] if existing else "2026-05-14T00:00:00+00:00"
        return {
            "session_id": payload["session_id"],
            "state": payload["state"],
            "payload": payload["payload"],
            "version": version,
            "created_at": created_at,
            "updated_at": f"2026-05-14T00:00:0{version}+00:00",
        }


class SmokeProbeHttpClient:
    def __init__(self, responses: dict[str, dict[str, Any]]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, dict[str, Any], str | None]] = []

    def post_json(self, url: str, payload: dict[str, Any], token: str | None = None) -> dict[str, Any]:
        self.calls.append((url, payload, token))
        return self.responses[url]


class FailingHttpClient:
    def post_json(self, url: str, payload: dict[str, Any], token: str | None = None) -> dict[str, Any]:
        del payload, token
        raise IntegrationError(f"{url} is unavailable")


class NotificationFailingHttpClient:
    def post_json(self, url: str, payload: dict[str, Any], token: str | None = None) -> dict[str, Any]:
        del payload, token
        if url == "https://notify.example/send":
            raise IntegrationError(f"{url} is unavailable")
        return {}


class CalendarFailingHttpClient:
    def post_json(self, url: str, payload: dict[str, Any], token: str | None = None) -> dict[str, Any]:
        del payload, token
        if url == "https://calendar.example/sync":
            raise IntegrationError(f"{url} is unavailable")
        return {}


class FlakyNotificationHttpClient:
    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.calls = 0

    def post_json(self, url: str, payload: dict[str, Any], token: str | None = None) -> dict[str, Any]:
        del token
        if url == "https://notify.example/send":
            self.calls += 1
            if self.calls <= self.failures:
                raise IntegrationError(f"{url} is unavailable")
            return {
                "notification": {
                    "notification_id": "REMOTE-NOTIFY-REPLAY",
                    "event_type": payload["event_type"],
                    "channel": payload["channel"],
                    "recipient_id": payload["user_id"],
                    "title": payload["title"],
                    "message": payload["message"],
                    "status": "SENT",
                }
            }
        return {}


class FlakyCalendarHttpClient:
    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.calls = 0

    def post_json(self, url: str, payload: dict[str, Any], token: str | None = None) -> dict[str, Any]:
        del token
        if url == "https://calendar.example/sync":
            self.calls += 1
            if self.calls <= self.failures:
                raise IntegrationError(f"{url} is unavailable")
            return {
                "calendar": {
                    "calendar_event_id": "REMOTE-CALENDAR-REPLAY",
                    "event_type": payload["event_type"],
                    "status": "SYNCED",
                    "user_id": payload["user_id"],
                    "title": payload["title"],
                    "start_at": payload["start_at"],
                    "end_at": payload["end_at"],
                    "attendees": payload["attendees"],
                }
            }
        return {}


def _remote_order_responses(
    price_check: dict[str, Any] | None = None,
    order: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    responses = {
        "https://policy.example/check": {
            "policy": {
                "policy_id": "REMOTE-POLICY-1",
                "max_hotel_price": 700,
                "approved_budget": 680,
                "compliant": True,
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
        "https://hotel.example/price": price_check
        or {
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
        "https://order.example/create": order
        or {
            "order": {
                "order_id": "REMOTE-ORDER-1",
                "status": "CREATED",
                "total_amount": 1320,
                "currency": "CNY",
            }
        },
    }
    return responses


def _remote_order_settings(**overrides: Any) -> IntegrationSettings:
    values = {
        "policy_api_url": "https://policy.example/check",
        "transport_policy_api_url": "https://transport.example/policy",
        "hotel_inventory_api_url": "https://hotel.example/search",
        "transport_inventory_api_url": "https://transport.example/search",
        "oa_approval_api_url": "https://oa.example/create",
        "oa_approval_status_api_url": "https://oa.example/status",
        "hotel_inventory_lock_api_url": "https://hotel.example/lock",
        "hotel_price_check_api_url": "https://hotel.example/price",
        "transport_order_api_url": "https://transport.example/order",
        "order_api_url": "https://order.example/create",
    }
    values.update(overrides)
    return IntegrationSettings(**values)


if __name__ == "__main__":
    unittest.main()
