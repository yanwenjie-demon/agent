from __future__ import annotations

import hashlib
import hmac
import json
import sys
import tempfile
import unittest
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from travel_agent.agent import build_default_agent, build_session_store
from travel_agent.acceptance import render_integration_acceptance_report, run_integration_acceptance_report
from travel_agent.cli import (
    build_operations_closed_loop_dashboard_json,
    build_operations_console_overview_json,
    build_operations_console_view_html,
    build_operations_console_view_json,
    build_oncall_webhook_ops_console_json,
    build_oncall_webhook_replay_jobs_json,
    create_operations_dashboard_server,
    create_metrics_server,
    render_calendar_dead_letters,
    render_context,
    render_dead_letters,
    render_metrics,
    render_otlp_export_result,
    render_prometheus_metrics,
    render_storage_health,
    render_worker_runs,
    run_operations_console_action,
    run_metrics_server_in_thread,
)
from travel_agent.config import IntegrationSettings
from travel_agent.evaluation import render_evaluation_report, run_evaluation_suite
from travel_agent.domain_agents import ApprovalAgent, BookingAgent, HotelAgent, PolicyAgent, TransportAgent
from travel_agent.governance import render_release_readiness_report, run_release_readiness_report
from travel_agent.integrations import IntegrationError
from travel_agent.data_governance import HttpAuditSink, InMemoryAuditSink, build_audit_event, redact_payload
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
    advance_operations_scheduled_task,
    authorize_operations_action,
    build_operations_closed_loop_acceptance_report,
    build_operations_closed_loop_checkpoint_plan,
    build_alert_route_rules,
    build_operations_alerts,
    build_operations_dashboard,
    build_operations_dashboard_snapshot,
    build_operations_action_sla_policy,
    build_operations_closed_loop_report,
    build_operations_closed_loop_snapshot,
    build_operations_console_overview,
    build_operations_console_view,
    build_operations_audit_timeline,
    build_operations_closed_loop_dashboard,
    build_operations_dashboard_trend_report,
    build_operations_knowledge_entries,
    build_operations_drill_report,
    build_operations_multidimensional_view,
    build_operations_postmortem_report,
    build_operations_trend_alert_rules,
    build_oncall_webhook_event,
    build_oncall_webhook_ops_console,
    build_operations_closed_loop_json_schema,
    build_operations_closed_loop_openapi_spec,
    build_operations_scheduled_tasks,
    build_operations_scheduler_health_report,
    build_operations_governance_policy_change,
    build_operations_console_action_audit,
    build_recovery_strategy_metrics,
    build_oncall_webhook_replay_job,
    build_recovery_approval_sla_policy,
    build_recovery_governance_policy_audit,
    collect_recovery_approval_receipts,
    build_postmortem_action_items,
    build_trend_alert_action_items,
    close_operations_action_item,
    evaluate_operations_action_sla,
    evaluate_operations_closed_loop_quality,
    execute_oncall_webhook_replay_job,
    build_operations_runbook,
    evaluate_operations_drill_gate,
    evaluate_operations_trend_alerts,
    evaluate_recovery_strategy_gate,
    evaluate_recovery_approval_sla,
    export_recovery_approval_receipt_http,
    export_operations_closed_loop_report_http,
    export_operations_alerts_http,
    fetch_recovery_governance_policy_http,
    fetch_oncall_ticket_status_http,
    open_oncall_ticket_http,
    oncall_ticket_status_from_dict,
    oncall_ticket_status_from_webhook,
    oncall_ticket_status_to_dict,
    open_recovery_failure_ticket_http,
    oncall_webhook_replay_job_from_dict,
    oncall_webhook_replay_job_to_dict,
    oncall_webhook_event_from_dict,
    oncall_webhook_event_to_dict,
    list_dead_letter_oncall_webhook_events,
    patch_oncall_webhook_event_payload,
    replay_dead_letter_oncall_webhook_events,
    oncall_webhook_replay_batch_result_from_dict,
    oncall_webhook_replay_batch_result_to_dict,
    oncall_webhook_replay_result_from_dict,
    oncall_webhook_replay_result_to_dict,
    operations_action_item_from_dict,
    operations_action_item_to_dict,
    operations_closed_loop_snapshot_from_dict,
    operations_closed_loop_snapshot_to_dict,
    operations_closed_loop_report_to_dict,
    operations_closed_loop_dashboard_to_dict,
    operations_dashboard_snapshot_from_dict,
    operations_dashboard_snapshot_to_dict,
    operations_knowledge_entry_from_dict,
    operations_knowledge_entry_to_dict,
    operations_scheduled_task_from_dict,
    operations_scheduled_task_to_dict,
    operations_scheduler_run_report_from_dict,
    operations_scheduler_run_report_to_dict,
    operations_governance_policy_change_from_dict,
    operations_governance_policy_change_to_dict,
    operations_console_action_audit_from_dict,
    operations_console_action_audit_to_dict,
    operations_trend_alert_from_dict,
    operations_trend_alert_to_dict,
    render_alert_route_rules,
    render_alert_route_rules_json,
    render_operations_action_items,
    render_operations_action_sla_notifications,
    render_operations_action_sla_report,
    render_operations_action_status_sync_report,
    render_operations_closed_loop_export_result,
    render_operations_closed_loop_report,
    render_operations_closed_loop_dashboard_json,
    render_operations_closed_loop_report_json,
    render_operations_closed_loop_report_prometheus,
    render_operations_closed_loop_snapshots,
    render_operations_closed_loop_json_schema,
    render_operations_closed_loop_openapi_spec,
    render_operations_closed_loop_contract_validation,
    publish_operations_closed_loop_schema_http,
    render_oncall_ticket_status,
    render_oncall_webhook_event,
    render_oncall_webhook_ops_console,
    render_oncall_webhook_ops_console_json,
    render_oncall_webhook_replay_audit_json,
    render_oncall_webhook_replay_batch_result,
    render_oncall_webhook_replay_result,
    render_oncall_webhook_replay_jobs,
    render_oncall_webhook_replay_jobs_json,
    render_oncall_ticket_result,
    render_operations_alert_export_result,
    render_operations_alerts,
    render_operations_alerts_json,
    render_operations_alerts_prometheus,
    render_operations_action_authorization,
    render_operations_dashboard,
    render_operations_dashboard_snapshots,
    render_operations_dashboard_trend_report,
    render_operations_console_overview_json,
    render_operations_console_view_html,
    render_operations_console_view_json,
    render_operations_knowledge_entries,
    render_operations_knowledge_search_report,
    render_operations_drill_gate_result,
    render_operations_drill_report,
    render_operations_multidimensional_view,
    render_operations_postmortem_report,
    render_operations_trend_alerts,
    render_operations_trend_alerts_json,
    render_operations_runbook,
    render_recovery_strategy_decision,
    render_recovery_strategy_execution_result,
    render_recovery_governance_decision,
    render_recovery_approval_sla_report,
    render_recovery_governance_policy_audit,
    render_recovery_governance_policy_fetch_result,
    render_operations_closed_loop_acceptance_report,
    render_operations_closed_loop_checkpoint_plan,
    render_operations_closed_loop_quality_report,
    render_operations_closed_loop_schema_publish_result,
    render_operations_scheduled_tasks,
    render_operations_scheduler_health_report,
    render_operations_scheduler_run_report,
    render_operations_governance_policy_changes,
    render_operations_console_action_audits,
    render_operations_audit_timeline,
    render_operations_audit_timeline_json,
    render_recovery_approval_export_result,
    render_recovery_strategy_metrics_prometheus,
    render_recovery_strategy_gate_result,
    render_oncall_webhook_replay_job_execution,
    recovery_strategy_decision_from_dict,
    recovery_governance_policy_from_dict,
    recovery_governance_policy_from_json,
    recovery_governance_policy_to_dict,
    recovery_governance_decision_from_dict,
    approve_operations_governance_policy_change,
    apply_operations_governance_policy_change,
    rollback_operations_governance_policy_change,
    recovery_strategy_execution_result_from_dict,
    recovery_strategy_execution_result_to_dict,
    recovery_strategy_gate_result_from_dict,
    replay_dead_letter_oncall_webhook_event,
    validate_operations_closed_loop_dashboard_contract,
    search_operations_knowledge,
    sync_operations_action_items_from_oncall,
    run_operations_scheduled_tasks,
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

    def test_plan_uses_persisted_operations_knowledge(self) -> None:
        store = InMemorySessionStore()
        store.record_operations_knowledge_entry(
            {
                "entry_id": "KB-PLAN",
                "topic": "hotel_inventory",
                "title": "Hotel inventory fallback",
                "summary": "Use fallback checks when Shanghai hotel inventory is unstable.",
                "signals": ["hotel", "inventory", "Shanghai"],
                "recommended_actions": ["Check hotel inventory fallback before approval."],
                "source_refs": ["INC-PLAN"],
                "created_at": "2026-05-20T00:00:00+00:00",
                "updated_at": "2026-05-20T00:00:00+00:00",
            }
        )
        agent = build_default_agent(session_store=store)

        context = agent.plan(_request())
        task_ids = [task.task_id for task in context.task_plan.tasks]

        self.assertIn("KB-PLAN", context.task_plan.knowledge_refs)
        self.assertIn("Check hotel inventory fallback before approval.", context.task_plan.guidance)
        self.assertIn("apply_operations_knowledge", task_ids)
        self.assertTrue(any(record.agent_name == "PlanningKnowledgeAgent" for record in context.agent_executions))
        self.assertIn("规划知识", render_context(context))

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
        store = InMemorySessionStore()
        store.record_operations_knowledge_entry(
            {
                "entry_id": "KB-RECOVERY",
                "topic": "APPROVAL_REJECTED",
                "title": "Approval rejected recovery",
                "summary": "When approval is rejected, replan with a lower hotel price and resubmit.",
                "signals": ["APPROVAL_REJECTED", "approval", "recovery"],
                "recommended_actions": ["Select a lower-price compliant hotel before resubmitting approval."],
                "source_refs": ["INC-APPROVAL"],
                "created_at": "2026-05-20T00:00:00+00:00",
                "updated_at": "2026-05-20T00:00:00+00:00",
            }
        )
        agent = build_default_agent(settings=settings, http_client=http, session_store=store)
        context = agent.run_to_order(_request())

        replanned = agent.replan_after_exception(context, reason="approval_rejected_replan")
        new_approval = agent.reselect_hotel_and_create_approval(replanned, "REMOTE-HOTEL-2")

        self.assertEqual(replanned.workflow_generation, 2)
        self.assertEqual(replanned.state, TravelState.APPROVAL_CREATED.value)
        self.assertEqual(new_approval.approval.approval_id, "REMOTE-APPROVAL-NEW")
        self.assertEqual(new_approval.approval.payload["workflow_generation"], 2)
        self.assertEqual(new_approval.recovery_records[0].from_state, TravelState.APPROVAL_REJECTED.value)
        self.assertIn("KB-RECOVERY", new_approval.recovery_records[0].payload["knowledge_refs"])
        decision = recovery_strategy_decision_from_dict(
            new_approval.recovery_records[0].payload["strategy_decision"]
        )
        gate = recovery_strategy_gate_result_from_dict(new_approval.recovery_records[0].payload["strategy_gate"])
        self.assertEqual(decision.action, "knowledge_guided_replan")
        self.assertEqual(decision.severity, "warning")
        self.assertTrue(gate.allow_automation)
        self.assertIn("KB-RECOVERY", decision.knowledge_refs)
        self.assertIn("Recovery strategy decision:", render_recovery_strategy_decision(decision))
        self.assertIn("Recovery strategy gate:", render_recovery_strategy_gate_result(gate))
        self.assertIn("Select a lower-price compliant hotel before resubmitting approval.", new_approval.task_plan.guidance)
        self.assertTrue(any(record.agent_name == "RecoveryStrategyAgent" for record in new_approval.agent_executions))
        self.assertTrue(any(record.agent_name == "RecoveryKnowledgeAgent" for record in new_approval.agent_executions))

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

    def test_executes_recovery_strategy_with_gate_override(self) -> None:
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
            transport_order_cancel_api_url="https://transport.example/cancel",
            hotel_inventory_release_api_url="https://hotel.example/release",
            oa_approval_cancel_api_url="https://oa.example/cancel",
        )
        agent = build_default_agent(settings=settings, http_client=http)
        context = agent.run_to_order(_request())

        blocked = agent.execute_recovery_strategy(context, reason="order_failed_strategy", enforce_strategy_gate=True)
        blocked_execution = recovery_strategy_execution_result_from_dict(
            blocked.recovery_records[-1].payload["strategy_execution"]
        )
        duplicate_blocked = agent.execute_recovery_strategy(
            blocked,
            reason="order_failed_strategy",
            enforce_strategy_gate=True,
        )
        duplicate_blocked_payload = duplicate_blocked.recovery_records[-1].payload["strategy_execution"]
        duplicate_blocked_execution = recovery_strategy_execution_result_from_dict(
            duplicate_blocked_payload
        )
        blocked_state = blocked.state
        recovered = agent.execute_recovery_strategy(
            blocked,
            reason="order_failed_strategy",
            enforce_strategy_gate=True,
            approval_override=True,
            approved_by="ops-lead",
            approval_reason="incident approved",
        )
        execution = recovery_strategy_execution_result_from_dict(
            recovered.recovery_records[-1].payload["strategy_execution"]
        )
        serialized = recovery_strategy_execution_result_to_dict(execution)
        metrics = build_recovery_strategy_metrics([recovered])
        prometheus = render_recovery_strategy_metrics_prometheus([recovered])

        self.assertEqual(blocked_state, TravelState.ORDER_FAILED.value)
        self.assertEqual(blocked_execution.status, "BLOCKED")
        self.assertEqual(duplicate_blocked_execution.status, "SKIPPED")
        self.assertTrue(duplicate_blocked_payload["idempotent"])
        self.assertEqual(recovered.state, TravelState.PLAN_GENERATED.value)
        self.assertEqual(recovered.workflow_generation, 2)
        self.assertEqual(execution.action, "compensate_then_replan")
        self.assertEqual(execution.status, "EXECUTED")
        self.assertTrue(execution.approval_override)
        self.assertIsNotNone(execution.approval_receipt)
        self.assertEqual(execution.approval_receipt["approved_by"], "ops-lead")
        self.assertTrue(execution.idempotency_key.startswith(f"recovery-execution:{context.session_id}:"))
        self.assertIn("strategy_execution", recovered.recovery_records[-1].payload)
        self.assertIn("Recovery strategy execution:", render_recovery_strategy_execution_result(execution))
        self.assertEqual(serialized["status"], "EXECUTED")
        self.assertEqual(serialized["approval_receipt"]["reason"], "incident approved")
        self.assertGreaterEqual(metrics["status:EXECUTED"], 1)
        self.assertGreaterEqual(metrics["approval_receipt"], 1)
        self.assertIn("travel_recovery_strategy_executions_total", prometheus)
        self.assertTrue(any(record.agent_name == "RecoveryStrategyExecutor" for record in recovered.agent_executions))

    def test_recovery_governance_blocks_exports_receipts_and_opens_failure_ticket(self) -> None:
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
            transport_order_cancel_api_url="https://transport.example/cancel",
            hotel_inventory_release_api_url="https://hotel.example/release",
            oa_approval_cancel_api_url="https://oa.example/cancel",
        )
        agent = build_default_agent(settings=settings, http_client=http)
        context = agent.run_to_order(_request())
        blocked_policy = recovery_governance_policy_from_dict({"blocked_actions": ["compensate_then_replan"]})

        blocked = agent.execute_recovery_strategy(
            context,
            reason="governance_block",
            enforce_strategy_gate=True,
            approval_override=True,
            approved_by="ops-lead",
            approval_reason="approved but blocked by policy",
            governance_policy=blocked_policy,
        )
        blocked_execution_payload = blocked.recovery_records[-1].payload["strategy_execution"]
        blocked_execution = recovery_strategy_execution_result_from_dict(blocked_execution_payload)
        governance = recovery_governance_decision_from_dict(blocked.recovery_records[-1].payload["strategy_governance"])
        audit_http = CapturingAnyHttpClient({"https://audit.example/recovery": {"ok": True, "accepted": 1}})
        ticket_http = CapturingAnyHttpClient({"https://oncall.example/tickets": {"ok": True, "ticket_id": "INC-RECOVERY"}})
        receipts = collect_recovery_approval_receipts([blocked])
        export_result = export_recovery_approval_receipt_http(
            receipts[0],
            "https://audit.example/recovery",
            token="audit-token",
            http_client=audit_http,
        )
        ticket_result = open_recovery_failure_ticket_http(
            blocked,
            blocked_execution,
            "https://oncall.example/tickets",
            token="oncall-token",
            http_client=ticket_http,
        )

        self.assertEqual(blocked.state, TravelState.ORDER_FAILED.value)
        self.assertEqual(blocked_execution.status, "BLOCKED")
        self.assertEqual(blocked_execution.gate_status, "GOVERNANCE_BLOCKED")
        self.assertFalse(governance.allow_automation)
        self.assertIn("Recovery governance decision:", render_recovery_governance_decision(governance))
        self.assertEqual(receipts[0].approved_by, "ops-lead")
        self.assertTrue(export_result.ok)
        self.assertIn("Recovery approval export:", render_recovery_approval_export_result(export_result))
        self.assertEqual(audit_http.calls[0][2], "audit-token")
        self.assertEqual(ticket_result.ticket_id, "INC-RECOVERY")
        self.assertEqual(ticket_http.calls[0][1]["recovery_execution"]["status"], "BLOCKED")
        self.assertEqual(recovery_governance_policy_from_json('{"max_executions_per_session":1}').max_executions_per_session, 1)
        config_http = CapturingAnyHttpClient(
            {
                "https://config.example/recovery-governance": {
                    "source": "config-center",
                    "policy": {
                        "allowed_actions": ["compensate_then_replan"],
                        "max_executions_per_session": 3,
                    },
                }
            }
        )
        fetched = fetch_recovery_governance_policy_http(
            "https://config.example/recovery-governance",
            token="config-token",
            http_client=config_http,
            fallback_policy=blocked_policy,
        )
        fallback = fetch_recovery_governance_policy_http(
            "https://config.example/recovery-governance",
            http_client=FailingHttpClient(),
            fallback_policy=blocked_policy,
        )
        policy_audit = build_recovery_governance_policy_audit(
            blocked_policy,
            fetched.policy,
            changed_by="platform",
            changed_at="2026-05-20T01:00:00+00:00",
        )
        sla_report = evaluate_recovery_approval_sla(
            [blocked],
            policy=build_recovery_approval_sla_policy('{"allowed_approvers":["security-lead"]}'),
            now=receipts[0].approved_at,
        )

        self.assertTrue(fetched.ok)
        self.assertEqual(fetched.policy.allowed_actions, ["compensate_then_replan"])
        self.assertEqual(config_http.calls[0][2], "config-token")
        self.assertFalse(fallback.ok)
        self.assertEqual(fallback.policy.blocked_actions, ["compensate_then_replan"])
        self.assertTrue(policy_audit.changes)
        self.assertIn("Recovery governance policy fetch:", render_recovery_governance_policy_fetch_result(fetched))
        self.assertIn("Recovery governance policy audit:", render_recovery_governance_policy_audit(policy_audit))
        self.assertEqual(sla_report.findings[0].severity, "critical")
        self.assertIn("Recovery approval SLA:", render_recovery_approval_sla_report(sla_report))

    def test_builds_approves_and_rolls_back_governance_policy_change(self) -> None:
        previous = recovery_governance_policy_from_dict({"allowed_actions": ["replan"]})
        current = recovery_governance_policy_from_dict(
            {"allowed_actions": ["replan", "retry_status_refresh"], "max_executions_per_session": 2}
        )

        change = build_operations_governance_policy_change(
            previous,
            current,
            requested_by="ops-a",
            requested_at="2026-05-20T03:00:00+00:00",
            reason="allow safe retry",
        )
        approved = approve_operations_governance_policy_change(change, "ops-b")
        applied = apply_operations_governance_policy_change(approved, "2026-05-20T03:05:00+00:00")
        rollback = rollback_operations_governance_policy_change(
            applied,
            requested_by="ops-c",
            requested_at="2026-05-20T03:10:00+00:00",
        )
        reloaded = operations_governance_policy_change_from_dict(
            operations_governance_policy_change_to_dict(applied)
        )

        self.assertEqual(change.status, "PENDING_APPROVAL")
        self.assertTrue(any("max_executions_per_session" in item for item in change.changes))
        self.assertEqual(approved.status, "APPROVED")
        self.assertEqual(applied.status, "APPLIED")
        self.assertEqual(reloaded.change_id, applied.change_id)
        self.assertEqual(rollback.status, "ROLLED_BACK")
        self.assertEqual(rollback.after, change.before)
        self.assertIn("Operations governance policy changes:", render_operations_governance_policy_changes([applied]))

    def test_builds_console_action_audit_summary(self) -> None:
        authorization = {
            "allowed": True,
            "action": "update_governance_policy",
            "decision": {"status": "NOT_ENFORCED"},
        }
        audit = build_operations_console_action_audit(
            action="propose_governance_policy_change",
            actor="ops-a",
            roles=["ops"],
            department="platform",
            authorization=authorization,
            request_payload={
                "action": "propose_governance_policy_change",
                "before": {"allowed_actions": ["replan"]},
                "after": {"allowed_actions": ["replan", "retry_status_refresh"]},
                "token": "secret-token",
            },
            result_body={
                "ok": True,
                "action": "propose_governance_policy_change",
                "change": {"change_id": "OGP-1", "status": "PENDING_APPROVAL"},
            },
            requested_at="2026-05-20T03:00:00+00:00",
            completed_at="2026-05-20T03:01:00+00:00",
        )
        reloaded = operations_console_action_audit_from_dict(operations_console_action_audit_to_dict(audit))

        self.assertEqual(audit.status, "SUCCESS")
        self.assertEqual(audit.request_summary["token"]["present"], True)
        self.assertNotIn("secret-token", str(audit.request_summary))
        self.assertEqual(audit.result_summary["change_id"], "OGP-1")
        self.assertEqual(reloaded.audit_id, audit.audit_id)
        self.assertIn("Operations console action audits:", render_operations_console_action_audits([audit]))

    def test_builds_operations_audit_timeline_with_filters(self) -> None:
        audit = build_operations_console_action_audit(
            action="propose_governance_policy_change",
            actor="ops-a",
            roles=["ops"],
            department="platform",
            authorization={"allowed": True, "action": "update_governance_policy"},
            request_payload={"action": "propose_governance_policy_change"},
            result_body={
                "ok": True,
                "change": {"change_id": "OGP-TL", "status": "PENDING_APPROVAL"},
            },
            requested_at="2026-05-20T03:00:00+00:00",
            completed_at="2026-05-20T03:01:00+00:00",
        )
        change = operations_governance_policy_change_from_dict(
            {
                "change_id": "OGP-TL",
                "status": "APPLIED",
                "policy_type": "recovery_governance",
                "requested_by": "ops-a",
                "requested_at": "2026-05-20T03:02:00+00:00",
                "before": {"allowed_actions": ["replan"]},
                "after": {"allowed_actions": ["replan", "retry_status_refresh"]},
                "changes": ["allowed_actions: ['replan'] -> ['replan', 'retry_status_refresh']"],
                "approvals": ["ops-b"],
                "applied_at": "2026-05-20T03:03:00+00:00",
            }
        )
        replay_job = build_oncall_webhook_replay_job(
            ["WHK-TL"],
            requested_by="ops-c",
            patch_template_id="missing_ticket_status",
            created_at="2026-05-20T03:04:00+00:00",
        )
        scheduler_run = operations_scheduler_run_report_from_dict(
            {
                "run_id": "OSR-TL",
                "started_at": "2026-05-20T03:05:00+00:00",
                "finished_at": "2026-05-20T03:06:00+00:00",
                "due_count": 1,
                "executed_count": 1,
                "failed_count": 0,
                "results": [],
                "summary": "executed=1 failed=0",
            }
        )

        timeline = build_operations_audit_timeline(
            [audit],
            [change],
            [replay_job],
            [scheduler_run],
            generated_at="2026-05-20T03:07:00+00:00",
        )
        action_filtered = build_operations_audit_timeline([audit], [change], [replay_job], [scheduler_run], action="run_operations_schedule")
        actor_filtered = build_operations_audit_timeline([audit], [change], [replay_job], [scheduler_run], actor="ops-c")
        status_filtered = build_operations_audit_timeline([audit], [change], [replay_job], [scheduler_run], status="APPLIED")
        type_filtered = build_operations_audit_timeline(
            [audit],
            [change],
            [replay_job],
            [scheduler_run],
            event_type="console_action",
        )

        self.assertEqual([event.event_type for event in timeline.events], ["scheduler_run", "replay_job", "governance_policy_change", "console_action"])
        self.assertEqual(action_filtered.events[0].event_id, "OSR-TL")
        self.assertEqual(actor_filtered.events[0].event_id, replay_job.job_id)
        self.assertEqual(status_filtered.events[0].event_id, "OGP-TL")
        self.assertEqual(type_filtered.events[0].event_id, audit.audit_id)
        self.assertIn("operations_audit_timeline", render_operations_audit_timeline_json(timeline))
        self.assertIn("Operations audit timeline:", render_operations_audit_timeline(timeline))

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
        closed_loop_report = build_operations_closed_loop_report(generated_at="2026-05-19T10:10:00+00:00")
        closed_loop_snapshot = build_operations_closed_loop_snapshot(
            closed_loop_report,
            snapshot_id="CLP-HTTP",
            created_at="2026-05-19T10:10:00+00:00",
        )
        store.record_operations_closed_loop_snapshot(operations_closed_loop_snapshot_to_dict(closed_loop_snapshot))
        store.record_oncall_ticket_status(status)
        webhook_event = build_oncall_webhook_event(
            {
                "event_id": "WHK-HTTP",
                "data": {
                    "ticket_id": "INC-HTTP",
                    "status": "RESOLVED",
                    "updated_at": "2026-05-19T10:06:00+00:00",
                },
            },
            now="2026-05-19T10:07:00+00:00",
        )
        store.record_oncall_webhook_event(oncall_webhook_event_to_dict(webhook_event))
        replay_job = build_oncall_webhook_replay_job(
            [webhook_event.event_id],
            requested_by="ops",
            patch_template_id="missing_ticket_status",
            created_at="2026-05-19T10:08:00+00:00",
        )
        store.record_oncall_webhook_replay_job(oncall_webhook_replay_job_to_dict(replay_job))
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
        schedule_task = build_operations_scheduled_tasks(now="2026-05-19T10:00:00+00:00")[0]
        store.record_operations_scheduled_task(operations_scheduled_task_to_dict(schedule_task))
        claimed_tasks = store.claim_due_operations_scheduled_tasks(
            owner="worker-a",
            now="2026-05-19T10:01:00+00:00",
            lease_seconds=120,
            limit=1,
        )
        store.complete_operations_scheduled_task(
            {
                **claimed_tasks[0],
                "next_run_at": "2026-05-19T11:01:00+00:00",
                "lease_owner": None,
                "lease_expires_at": None,
            }
        )
        scheduler_report = run_operations_scheduled_tasks(
            [operations_scheduled_task_from_dict(claimed_tasks[0])],
            {"closed_loop_snapshot": lambda task: {"ok": True}},
            now="2026-05-19T10:02:00+00:00",
        )
        store.record_operations_scheduler_run(operations_scheduler_run_report_to_dict(scheduler_report))
        governance_change = build_operations_governance_policy_change(
            recovery_governance_policy_from_dict({"allowed_actions": ["replan"]}),
            recovery_governance_policy_from_dict({"allowed_actions": ["replan", "retry_status_refresh"]}),
            requested_by="ops",
            requested_at="2026-05-19T10:09:00+00:00",
        )
        store.record_operations_governance_policy_change(
            operations_governance_policy_change_to_dict(governance_change)
        )
        console_audit = build_operations_console_action_audit(
            action="propose_governance_policy_change",
            actor="ops",
            roles=["ops"],
            department="platform",
            authorization={"allowed": True, "action": "update_governance_policy"},
            request_payload={"action": "propose_governance_policy_change", "after": {"allowed_actions": ["replan"]}},
            result_body={"ok": True, "action": "propose_governance_policy_change"},
            requested_at="2026-05-19T10:10:00+00:00",
            completed_at="2026-05-19T10:11:00+00:00",
        )
        store.record_operations_console_action_audit(operations_console_action_audit_to_dict(console_audit))

        self.assertEqual(store.list_operations_dashboard_snapshots()[0]["snapshot_id"], "DASH-HTTP")
        self.assertEqual(store.list_operations_closed_loop_snapshots()[0]["snapshot_id"], "CLP-HTTP")
        self.assertEqual(store.list_oncall_ticket_statuses()[0]["status"], "ACKED")
        self.assertEqual(store.list_oncall_webhook_events()[0]["event_id"], "WHK-HTTP")
        self.assertEqual(store.list_oncall_webhook_replay_jobs()[0]["job_id"], replay_job.job_id)
        self.assertEqual(store.list_operations_trend_alerts()[0]["alert_id"], "TREND-HTTP")
        self.assertEqual(store.list_operations_action_items()[0]["action_id"], "ACT-HTTP")
        self.assertEqual(store.list_operations_knowledge_entries()[0]["entry_id"], "KB-HTTP")
        self.assertEqual(claimed_tasks[0]["lease_owner"], "worker-a")
        self.assertEqual(store.list_operations_scheduled_tasks()[0]["next_run_at"], "2026-05-19T11:01:00+00:00")
        self.assertEqual(store.list_operations_scheduler_runs()[0]["run_id"], scheduler_report.run_id)
        self.assertEqual(
            store.list_operations_governance_policy_changes()[0]["change_id"],
            governance_change.change_id,
        )
        self.assertEqual(store.list_operations_console_action_audits()[0]["audit_id"], console_audit.audit_id)
        self.assertTrue(any(call[0].endswith("/operations/dashboard-snapshots/record") for call in http.calls))
        self.assertTrue(any(call[0].endswith("/operations/closed-loop-snapshots/record") for call in http.calls))
        self.assertTrue(any(call[0].endswith("/operations/oncall-statuses/record") for call in http.calls))
        self.assertTrue(any(call[0].endswith("/operations/oncall-webhooks/record") for call in http.calls))
        self.assertTrue(any(call[0].endswith("/operations/oncall-webhook-replay-jobs/record") for call in http.calls))
        self.assertTrue(any(call[0].endswith("/operations/trend-alerts/record") for call in http.calls))
        self.assertTrue(any(call[0].endswith("/operations/action-items/record") for call in http.calls))
        self.assertTrue(any(call[0].endswith("/operations/knowledge/record") for call in http.calls))
        self.assertTrue(any(call[0].endswith("/operations/scheduled-tasks/claim-due") for call in http.calls))
        self.assertTrue(any(call[0].endswith("/operations/scheduler-runs/record") for call in http.calls))
        self.assertTrue(any(call[0].endswith("/operations/governance-policy-changes/record") for call in http.calls))
        self.assertTrue(any(call[0].endswith("/operations/console-action-audits/record") for call in http.calls))

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
            webhook_event = build_oncall_webhook_event(
                {
                    "event_id": "WHK-SQL",
                    "data": {
                        "ticket_id": "INC-SQL",
                        "status": "RESOLVED",
                        "updated_at": "2026-05-19T10:06:00+00:00",
                    },
                },
                now="2026-05-19T10:07:00+00:00",
            )
            store.record_oncall_webhook_event(oncall_webhook_event_to_dict(webhook_event))
            replay_job = build_oncall_webhook_replay_job(
                [webhook_event.event_id],
                requested_by="ops",
                patch_template_id="missing_ticket_status",
                created_at="2026-05-19T10:08:00+00:00",
            )
            store.record_oncall_webhook_replay_job(oncall_webhook_replay_job_to_dict(replay_job))
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
            schedule_task = build_operations_scheduled_tasks(now="2026-05-19T10:00:00+00:00")[0]
            store.record_operations_scheduled_task(operations_scheduled_task_to_dict(schedule_task))
            claimed = store.claim_due_operations_scheduled_tasks(
                owner="worker-a",
                now="2026-05-19T10:01:00+00:00",
                lease_seconds=120,
                limit=1,
            )
            still_locked = store.claim_due_operations_scheduled_tasks(
                owner="worker-b",
                now="2026-05-19T10:02:00+00:00",
                lease_seconds=120,
                limit=1,
            )
            expired_claim = store.claim_due_operations_scheduled_tasks(
                owner="worker-b",
                now="2026-05-19T10:04:00+00:00",
                lease_seconds=120,
                limit=1,
            )
            advanced_task = advance_operations_scheduled_task(
                operations_scheduled_task_from_dict(expired_claim[0]),
                run_operations_scheduled_tasks(
                    [operations_scheduled_task_from_dict(expired_claim[0])],
                    {"closed_loop_snapshot": lambda task: {"ok": True}},
                    now="2026-05-19T10:04:00+00:00",
                ).results[0],
            )
            store.complete_operations_scheduled_task(operations_scheduled_task_to_dict(advanced_task))
            scheduler_report = run_operations_scheduled_tasks(
                [operations_scheduled_task_from_dict(expired_claim[0])],
                {"closed_loop_snapshot": lambda task: {"ok": True}},
                now="2026-05-19T10:04:00+00:00",
            )
            store.record_operations_scheduler_run(operations_scheduler_run_report_to_dict(scheduler_report))
            governance_change = build_operations_governance_policy_change(
                recovery_governance_policy_from_dict({"allowed_actions": ["replan"]}),
                recovery_governance_policy_from_dict({"allowed_actions": ["replan", "retry_status_refresh"]}),
                requested_by="ops",
                requested_at="2026-05-19T10:09:00+00:00",
            )
            store.record_operations_governance_policy_change(
                operations_governance_policy_change_to_dict(governance_change)
            )
            console_audit = build_operations_console_action_audit(
                action="propose_governance_policy_change",
                actor="ops",
                roles=["ops"],
                department="platform",
                authorization={"allowed": True, "action": "update_governance_policy"},
                request_payload={"action": "propose_governance_policy_change"},
                result_body={"ok": True, "action": "propose_governance_policy_change"},
                requested_at="2026-05-19T10:10:00+00:00",
                completed_at="2026-05-19T10:11:00+00:00",
            )
            store.record_operations_console_action_audit(operations_console_action_audit_to_dict(console_audit))
            closed_loop = build_operations_closed_loop_report(
                trend_alerts=trend_alerts,
                action_items=action_items,
                knowledge_entries=entries,
                generated_at="2026-05-19T10:15:00+00:00",
            )
            closed_loop_snapshot = build_operations_closed_loop_snapshot(
                closed_loop,
                snapshot_id="CLP-SQL",
                created_at="2026-05-19T10:15:00+00:00",
            )
            store.record_operations_closed_loop_snapshot(operations_closed_loop_snapshot_to_dict(closed_loop_snapshot))

            reloaded_snapshot = operations_dashboard_snapshot_from_dict(store.list_operations_dashboard_snapshots()[0])
            reloaded_closed_loop_snapshot = operations_closed_loop_snapshot_from_dict(
                store.list_operations_closed_loop_snapshots()[0]
            )
            reloaded_status = oncall_ticket_status_from_dict(store.list_oncall_ticket_statuses()[0])
            reloaded_webhook_event = oncall_webhook_event_from_dict(store.list_oncall_webhook_events()[0])
            reloaded_replay_job = oncall_webhook_replay_job_from_dict(store.list_oncall_webhook_replay_jobs()[0])
            reloaded_alert = operations_trend_alert_from_dict(store.list_operations_trend_alerts()[0])
            reloaded_action = operations_action_item_from_dict(store.list_operations_action_items()[0])
            reloaded_entry = operations_knowledge_entry_from_dict(store.list_operations_knowledge_entries()[0])
            reloaded_task = operations_scheduled_task_from_dict(store.list_operations_scheduled_tasks()[0])
            reloaded_run = operations_scheduler_run_report_from_dict(store.list_operations_scheduler_runs()[0])
            reloaded_governance_change = operations_governance_policy_change_from_dict(
                store.list_operations_governance_policy_changes()[0]
            )
            reloaded_console_audit = operations_console_action_audit_from_dict(
                store.list_operations_console_action_audits()[0]
            )
            health = store.health_check()

            self.assertEqual(reloaded_snapshot.snapshot_id, "DASH-SQL")
            self.assertEqual(reloaded_closed_loop_snapshot.snapshot_id, "CLP-SQL")
            self.assertEqual(reloaded_status.status, "RESOLVED")
            self.assertEqual(reloaded_webhook_event.event_id, "WHK-SQL")
            self.assertEqual(reloaded_replay_job.job_id, replay_job.job_id)
            self.assertEqual(reloaded_alert.metric, "critical_alerts")
            self.assertEqual(reloaded_action.status, "OPEN")
            self.assertEqual(reloaded_entry.topic, "critical_alerts")
            self.assertEqual(claimed[0]["lease_owner"], "worker-a")
            self.assertEqual(still_locked, [])
            self.assertEqual(expired_claim[0]["lease_owner"], "worker-b")
            self.assertEqual(reloaded_task.run_count, 1)
            self.assertIsNone(reloaded_task.lease_owner)
            self.assertGreater(reloaded_task.next_run_at, "2026-05-19T10:04:00+00:00")
            self.assertEqual(reloaded_run.run_id, scheduler_report.run_id)
            self.assertEqual(reloaded_governance_change.change_id, governance_change.change_id)
            self.assertEqual(reloaded_console_audit.audit_id, console_audit.audit_id)
            self.assertGreaterEqual(health.schema_version, 11)
            self.assertEqual(health.details["dashboard_snapshots"], "1")
            self.assertEqual(health.details["closed_loop_snapshots"], "1")
            self.assertEqual(health.details["oncall_ticket_statuses"], "1")
            self.assertEqual(health.details["oncall_webhook_events"], "1")
            self.assertEqual(health.details["oncall_webhook_replay_jobs"], "1")
            self.assertEqual(health.details["operations_trend_alerts"], "1")
            self.assertEqual(health.details["operations_action_items"], "1")
            self.assertEqual(health.details["operations_knowledge_entries"], "1")
            self.assertEqual(health.details["operations_scheduled_tasks"], "1")
            self.assertEqual(health.details["operations_scheduler_runs"], "1")
            self.assertEqual(health.details["operations_governance_policy_changes"], "1")
            self.assertEqual(health.details["operations_console_action_audits"], "1")

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

    def test_worker_auto_recovers_rejected_approval_when_enabled(self) -> None:
        store = InMemorySessionStore()
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
        agent = build_default_agent(settings=settings, http_client=http, session_store=store)
        context = agent.run_to_order(_request())

        result = WorkflowWorker(agent, auto_recover=True).run_once()
        updated = store.get(context.session_id)
        execution = recovery_strategy_execution_result_from_dict(
            updated.recovery_records[-1].payload["strategy_execution"]
        )

        self.assertEqual(result.scanned, 1)
        self.assertEqual(result.advanced, 1)
        self.assertEqual(updated.state, TravelState.PLAN_GENERATED.value)
        self.assertEqual(updated.workflow_generation, 2)
        self.assertEqual(execution.action, "replan")
        self.assertEqual(execution.status, "EXECUTED")
        self.assertTrue(any(record.agent_name == "RecoveryStrategyExecutor" for record in updated.agent_executions))

    def test_worker_auto_recovery_honors_rollout_policy(self) -> None:
        store = InMemorySessionStore()
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
        agent = build_default_agent(settings=settings, http_client=http, session_store=store)
        context = agent.run_to_order(_request())

        WorkflowWorker(
            agent,
            auto_recover=True,
            recovery_rollout_policy=RolloutPolicy(enabled=True, percentage=0, salt="test"),
        ).run_once()
        updated = store.get(context.session_id)

        self.assertEqual(updated.state, TravelState.APPROVAL_REJECTED.value)
        self.assertEqual(updated.recovery_records, [])
        self.assertTrue(any("Worker recovery rollout skipped" in event for event in updated.events))

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
        snapshot = build_operations_closed_loop_snapshot(
            closed_loop,
            snapshot_id="CLP-SEARCH",
            created_at="2026-05-20T00:05:00+00:00",
        )
        reloaded_snapshot = operations_closed_loop_snapshot_from_dict(
            operations_closed_loop_snapshot_to_dict(snapshot)
        )

        self.assertTrue(search.hits)
        self.assertEqual(closed_loop.closure_rate, 100.0)
        self.assertEqual(closed_loop.action_items_closed, 1)
        self.assertEqual(operations_closed_loop_report_to_dict(closed_loop)["closure_rate"], 100.0)
        self.assertEqual(reloaded_snapshot.snapshot_id, "CLP-SEARCH")
        self.assertIn("Operations knowledge search:", render_operations_knowledge_search_report(search))
        self.assertIn("Operations closed-loop report:", render_operations_closed_loop_report(closed_loop))
        self.assertIn("Operations closed-loop snapshots:", render_operations_closed_loop_snapshots([snapshot]))
        self.assertIn('"closure_rate": 100.0', render_operations_closed_loop_report_json(closed_loop))
        self.assertIn(
            "travel_operations_closed_loop_action_items",
            render_operations_closed_loop_report_prometheus(closed_loop),
        )
        http = CapturingAnyHttpClient({"https://closed-loop.example/sink": {"ok": True, "accepted": 1}})
        export = export_operations_closed_loop_report_http(
            closed_loop,
            "https://closed-loop.example/sink",
            token="closed-loop-token",
            http_client=http,
        )

        self.assertTrue(export.ok)
        self.assertEqual(http.calls[0][2], "closed-loop-token")
        self.assertIn("Operations closed-loop export:", render_operations_closed_loop_export_result(export))

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
        notification_report = build_default_agent().notify_operations_action_sla(report)

        self.assertEqual(len(report.findings), 1)
        self.assertEqual(report.findings[0].severity, "critical")
        self.assertEqual(report.findings[0].route, "compliance-route")
        self.assertEqual(notification_report.notification_count, 1)
        self.assertEqual(notification_report.notifications[0].recipient_id, "compliance-platform-oncall")
        self.assertIn("Operations action SLA:", rendered)
        self.assertIn("Operations action SLA notifications:", render_operations_action_sla_notifications(notification_report))

    def test_syncs_action_items_from_oncall_ticket_status(self) -> None:
        item = operations_action_item_from_dict(
            {
                "action_id": "ACT-TICKET",
                "source_type": "trend_alert",
                "source_id": "TREND-TICKET",
                "title": "Recover order workflow",
                "owner": "booking-oncall",
                "status": "OPEN",
                "eta": None,
                "created_at": "2026-05-20T00:00:00+00:00",
                "updated_at": "2026-05-20T00:00:00+00:00",
                "evidence": ["ticket=INC-TICKET", "metric=state:ORDER_FAILED"],
                "closure_note": None,
            }
        )
        status = oncall_ticket_status_from_dict(
            {
                "ticket_id": "INC-TICKET",
                "status": "RESOLVED",
                "assignee": "booking-oncall",
                "updated_at": "2026-05-20T02:00:00+00:00",
                "detail": "supplier reconciliation completed",
            }
        )

        report = sync_operations_action_items_from_oncall(
            [item],
            [status],
            updated_at="2026-05-20T02:05:00+00:00",
        )
        rendered = render_operations_action_status_sync_report(report)

        self.assertEqual(report.matched_items, 1)
        self.assertEqual(report.closed_items[0].status, "CLOSED")
        self.assertIn("INC-TICKET", report.closed_items[0].closure_note)
        self.assertIn("Operations action status sync:", rendered)

    def test_recovery_strategy_gate_requires_approval_for_critical_paths(self) -> None:
        decision = recovery_strategy_decision_from_dict(
            {
                "decision_id": "RSD-GATE",
                "action": "compensate_then_replan",
                "severity": "critical",
                "reason": "state=ORDER_FAILED",
                "from_state": "ORDER_FAILED",
                "compensation_required": True,
                "manual_escalation_required": False,
                "knowledge_refs": [],
                "guidance": [],
                "recommended_next_steps": ["Complete compensation before resubmitting."],
            }
        )

        blocked = evaluate_recovery_strategy_gate(decision)
        approved = evaluate_recovery_strategy_gate(decision, approved=True)

        self.assertEqual(blocked.status, "APPROVAL_REQUIRED")
        self.assertFalse(blocked.allow_automation)
        self.assertIn("critical_recovery_approval", blocked.required_approvals)
        self.assertTrue(approved.allow_automation)
        self.assertIn("Recovery strategy gate:", render_recovery_strategy_gate_result(blocked))

    def test_parses_oncall_webhook_payloads_and_closes_action_items(self) -> None:
        item = operations_action_item_from_dict(
            {
                "action_id": "ACT-WEBHOOK",
                "source_type": "postmortem",
                "source_id": "INC-WEBHOOK",
                "title": "Close webhook related item",
                "owner": "workflow-oncall",
                "status": "OPEN",
                "eta": None,
                "created_at": "2026-05-20T00:00:00+00:00",
                "updated_at": "2026-05-20T00:00:00+00:00",
                "evidence": ["ticket=INC-WEBHOOK"],
                "closure_note": None,
            }
        )
        webhook_payload = {
            "event_type": "ticket.updated",
            "data": {
                "ticket_id": "INC-WEBHOOK",
                "status": "CLOSED",
                "assignee": {"name": "workflow-oncall"},
                "updated_at": "2026-05-20T03:00:00+00:00",
                "detail": "resolved by webhook",
            },
        }

        status = oncall_ticket_status_from_webhook(webhook_payload)
        report = sync_operations_action_items_from_oncall([item], [status], updated_at="2026-05-20T03:05:00+00:00")
        rendered = render_oncall_ticket_status(status)

        self.assertEqual(status.ticket_id, "INC-WEBHOOK")
        self.assertEqual(status.assignee, "workflow-oncall")
        self.assertEqual(report.matched_items, 1)
        self.assertIn("OnCall ticket status:", rendered)

    def test_oncall_webhook_event_validates_signature_dedupe_and_replay(self) -> None:
        payload = {
            "event_id": "WHK-SECURE",
            "data": {
                "ticket_id": "INC-SECURE",
                "status": "CLOSED",
                "assignee": "ops",
                "updated_at": "2026-05-20T03:00:00+00:00",
                "detail": "resolved by signed webhook",
            },
        }
        raw_body = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        secret = "webhook-secret"
        signature = "sha256=" + hmac.new(secret.encode("utf-8"), raw_body.encode("utf-8"), hashlib.sha256).hexdigest()

        accepted = build_oncall_webhook_event(
            payload,
            raw_body=raw_body,
            secret=secret,
            signature=signature,
            now="2026-05-20T03:05:00+00:00",
            replay_window_minutes=30,
        )
        duplicate = build_oncall_webhook_event(
            payload,
            raw_body=raw_body,
            secret=secret,
            signature=signature,
            seen_event_ids={"WHK-SECURE"},
            now="2026-05-20T03:05:00+00:00",
            replay_window_minutes=30,
        )
        invalid_signature = build_oncall_webhook_event(
            payload,
            raw_body=raw_body,
            secret=secret,
            signature="sha256=bad",
            now="2026-05-20T03:05:00+00:00",
        )
        replay = build_oncall_webhook_event(
            payload,
            raw_body=raw_body,
            secret=secret,
            signature=signature,
            now="2026-05-21T03:05:00+00:00",
            replay_window_minutes=30,
        )
        reloaded = oncall_webhook_event_from_dict(oncall_webhook_event_to_dict(accepted))

        self.assertTrue(accepted.accepted)
        self.assertTrue(accepted.signature_valid)
        self.assertEqual(reloaded.event_id, "WHK-SECURE")
        self.assertTrue(duplicate.duplicate)
        self.assertFalse(duplicate.accepted)
        self.assertFalse(invalid_signature.signature_valid)
        self.assertTrue(invalid_signature.dead_letter)
        self.assertTrue(replay.replay)
        self.assertTrue(replay.dead_letter)
        self.assertIn("OnCall webhook event:", render_oncall_webhook_event(accepted))

    def test_replays_oncall_webhook_dead_letter(self) -> None:
        payload = {
            "event_id": "WHK-DEAD",
            "data": {
                "ticket_id": "INC-DEAD",
                "status": "CLOSED",
                "assignee": "ops",
                "updated_at": "2026-05-20T03:00:00+00:00",
                "detail": "resolved after webhook replay",
            },
        }
        raw_body = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        event = build_oncall_webhook_event(
            payload,
            raw_body=raw_body,
            secret="webhook-secret",
            signature="sha256=bad",
            now="2026-05-20T03:05:00+00:00",
        )

        replayed_event, status, replay_result = replay_dead_letter_oncall_webhook_event(
            event,
            replayed_at="2026-05-20T03:10:00+00:00",
        )
        reloaded = oncall_webhook_replay_result_from_dict(oncall_webhook_replay_result_to_dict(replay_result))

        self.assertEqual([item.event_id for item in list_dead_letter_oncall_webhook_events([event])], ["WHK-DEAD"])
        self.assertEqual(replayed_event.status, "REPLAYED")
        self.assertFalse(replayed_event.dead_letter)
        self.assertTrue(replay_result.accepted)
        self.assertEqual(status.ticket_id, "INC-DEAD")
        self.assertEqual(reloaded.source_event_id, "WHK-DEAD")
        self.assertIn("OnCall webhook replay:", render_oncall_webhook_replay_result(replay_result))

    def test_batches_and_patches_oncall_webhook_dead_letter_replay(self) -> None:
        invalid_payload = {
            "event_id": "WHK-PATCH",
            "data": {
                "status": "CLOSED",
                "assignee": "ops",
                "updated_at": "2026-05-20T03:00:00+00:00",
                "detail": "resolved after batch replay",
            },
        }
        event = build_oncall_webhook_event(
            invalid_payload,
            raw_body=json.dumps(invalid_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            now="2026-05-20T03:05:00+00:00",
        )
        patched = patch_oncall_webhook_event_payload(
            event,
            {"ticket_status": {"ticket_id": "INC-PATCH", "status": "CLOSED", "updated_at": "2026-05-20T03:00:00+00:00"}},
            patched_at="2026-05-20T03:09:00+00:00",
        )

        replayed_events, statuses, batch = replay_dead_letter_oncall_webhook_events(
            [patched],
            replayed_at="2026-05-20T03:10:00+00:00",
        )
        serialized = oncall_webhook_replay_batch_result_to_dict(batch)
        reloaded = oncall_webhook_replay_batch_result_from_dict(serialized)
        job = build_oncall_webhook_replay_job(
            [result.source_event_id for result in batch.results],
            requested_by="ops",
            patch_template_id="missing_ticket_status",
            batch_result=batch,
            created_at="2026-05-20T03:11:00+00:00",
        )
        reloaded_job = oncall_webhook_replay_job_from_dict(oncall_webhook_replay_job_to_dict(job))

        self.assertTrue(event.dead_letter)
        self.assertEqual(replayed_events[0].status, "REPLAYED")
        self.assertEqual(statuses[0].ticket_id, "INC-PATCH")
        self.assertEqual(batch.accepted, 1)
        self.assertEqual(reloaded.batch_id, batch.batch_id)
        self.assertEqual(reloaded_job.status, "COMPLETED")
        self.assertEqual(reloaded_job.batch_result.batch_id, batch.batch_id)
        self.assertIn("OnCall webhook replay batch:", render_oncall_webhook_replay_batch_result(batch))
        self.assertIn("oncall_webhook_replay_audit", render_oncall_webhook_replay_audit_json(batch))
        self.assertIn("OnCall webhook replay jobs:", render_oncall_webhook_replay_jobs([job]))
        self.assertIn("oncall_webhook_replay_jobs", render_oncall_webhook_replay_jobs_json([job]))

    def test_builds_oncall_webhook_ops_console_with_templates(self) -> None:
        payload = {
            "event_id": "WHK-CONSOLE",
            "data": {
                "status": "CLOSED",
                "assignee": "ops",
                "updated_at": "2026-05-20T03:00:00+00:00",
                "detail": "missing ticket id",
            },
        }
        event = build_oncall_webhook_event(
            payload,
            raw_body=json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            now="2026-05-20T03:05:00+00:00",
        )

        console = build_oncall_webhook_ops_console([event], generated_at="2026-05-20T03:10:00+00:00")
        rendered = render_oncall_webhook_ops_console(console)
        json_payload = json.loads(render_oncall_webhook_ops_console_json(console))

        self.assertEqual(console.dead_letters, 1)
        self.assertEqual(console.retryable_event_ids, [event.event_id])
        self.assertEqual(console.failure_reasons["missing_ticket_id"], 1)
        self.assertEqual(console.patch_templates[0].template_id, "missing_ticket_status")
        self.assertIn("OnCall webhook operations console:", rendered)
        self.assertEqual(json_payload["oncall_webhook_ops_console"]["dead_letters"], 1)

    def test_authorizes_operations_action_and_writes_audit_event(self) -> None:
        sink = InMemoryAuditSink()
        policy = PermissionPolicy(enabled=True, required_roles={"ops"})

        allowed = authorize_operations_action(
            "execute_replay_job",
            user_id="ops-user",
            permission_policy=policy,
            department="platform",
            roles=["ops"],
            audit_sink=sink,
            payload={"ticket_id": "INC-1", "phone": "13800000000"},
        )
        denied = authorize_operations_action(
            "execute_replay_job",
            user_id="viewer",
            permission_policy=policy,
            roles=["viewer"],
            audit_sink=sink,
            payload={"ticket_id": "INC-2"},
        )

        self.assertTrue(allowed.allowed)
        self.assertEqual(allowed.audit_result.delivered, 1)
        self.assertFalse(denied.allowed)
        self.assertEqual(len(sink.events), 2)
        self.assertEqual(sink.events[0].event_type, "operations.execute_replay_job")
        self.assertEqual(sink.events[0].redacted_payload["payload"]["phone"], "***")
        self.assertIn("Operations action authorization:", render_operations_action_authorization(allowed))
        self.assertIn("missing required role", denied.decision.reasons[0])

    def test_runs_operations_console_action_for_replay_job_creation(self) -> None:
        payload = {
            "event_id": "WHK-ACTION",
            "data": {
                "status": "CLOSED",
                "updated_at": "2026-05-20T03:00:00+00:00",
                "detail": "missing ticket id",
            },
        }
        event = build_oncall_webhook_event(
            payload,
            raw_body=json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            now="2026-05-20T03:05:00+00:00",
        )
        store = InMemorySessionStore()
        store.record_oncall_webhook_event(oncall_webhook_event_to_dict(event))

        result = json.loads(
            run_operations_console_action(
                store,
                "create_replay_job",
                actor="ops-user",
                roles=["ops"],
                payload={"limit": 1, "requested_by": "ops-ui"},
            )
        )

        action = result["operations_console_action"]
        self.assertTrue(action["ok"])
        self.assertEqual(action["authorization"]["action"], "create_replay_job")
        self.assertEqual(action["job"]["requested_by"], "ops-ui")
        self.assertEqual(store.list_oncall_webhook_replay_jobs(1)[0]["job_id"], action["job"]["job_id"])

    def test_runs_operations_console_scheduler_action(self) -> None:
        store = InMemorySessionStore()

        result = json.loads(
            run_operations_console_action(
                store,
                "run_operations_schedule",
                actor="ops-user",
                roles=["ops"],
                payload={"limit": 10, "now": "2026-05-20T03:05:00+00:00"},
            )
        )

        action = result["operations_console_action"]
        self.assertTrue(action["ok"])
        self.assertEqual(action["authorization"]["action"], "run_operations_schedule")
        self.assertEqual(action["scheduler_run"]["due_count"], 5)
        self.assertEqual(store.list_operations_scheduler_runs(1)[0]["run_id"], action["scheduler_run"]["run_id"])

    def test_executes_pending_oncall_webhook_replay_job(self) -> None:
        payload = {
            "event_id": "WHK-JOB",
            "data": {
                "status": "CLOSED",
                "updated_at": "2026-05-20T03:00:00+00:00",
                "detail": "missing ticket id",
            },
        }
        event = build_oncall_webhook_event(
            payload,
            raw_body=json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            now="2026-05-20T03:05:00+00:00",
        )
        job = build_oncall_webhook_replay_job(
            [event.event_id],
            requested_by="ops",
            patch_template_id="missing_ticket_status",
            created_at="2026-05-20T03:06:00+00:00",
        )

        execution = execute_oncall_webhook_replay_job(
            job,
            [event],
            patches={
                event.event_id: {
                    "ticket_status": {
                        "ticket_id": "INC-JOB",
                        "status": "CLOSED",
                        "updated_at": "2026-05-20T03:00:00+00:00",
                    }
                }
            },
            executed_at="2026-05-20T03:10:00+00:00",
        )

        self.assertEqual(execution.job.status, "COMPLETED")
        self.assertEqual(execution.result.accepted, 1)
        self.assertEqual(execution.statuses[0].ticket_id, "INC-JOB")
        self.assertEqual(execution.replayed_events[0].status, "REPLAYED")
        self.assertEqual(execution.job.audit["source"], "scheduler")
        self.assertIn("OnCall webhook replay job execution:", render_oncall_webhook_replay_job_execution(execution))

    def test_runs_operations_scheduled_tasks_with_registered_handlers(self) -> None:
        tasks = build_operations_scheduled_tasks(now="2026-05-20T03:00:00+00:00")
        calls: list[str] = []

        def _handler(task: Any) -> dict[str, Any]:
            calls.append(task.task_type)
            return {"task_id": task.task_id}

        report = run_operations_scheduled_tasks(
            tasks,
            {
                "closed_loop_quality": _handler,
                "webhook_replay_jobs": _handler,
            },
            now="2026-05-20T03:05:00+00:00",
        )

        self.assertEqual(report.due_count, 5)
        self.assertEqual(report.executed_count, 2)
        self.assertEqual(report.failed_count, 0)
        self.assertEqual(calls, ["closed_loop_quality", "webhook_replay_jobs"])
        self.assertIn("Operations scheduled tasks:", render_operations_scheduled_tasks(tasks))
        self.assertIn("Operations scheduler run:", render_operations_scheduler_run_report(report))

    def test_advances_operations_scheduled_task_after_success_and_failure(self) -> None:
        task = build_operations_scheduled_tasks(now="2026-05-20T03:00:00+00:00")[0]
        success = run_operations_scheduled_tasks(
            [task],
            {"closed_loop_snapshot": lambda item: {"ok": True}},
            now="2026-05-20T03:05:00+00:00",
        ).results[0]
        failed = run_operations_scheduled_tasks(
            [task],
            {"closed_loop_snapshot": lambda item: (_ for _ in ()).throw(RuntimeError("boom"))},
            now="2026-05-20T03:05:00+00:00",
        ).results[0]

        advanced_success = advance_operations_scheduled_task(task, success)
        advanced_failure = advance_operations_scheduled_task(task, failed)

        self.assertEqual(advanced_success.last_status, "SUCCESS")
        self.assertEqual(advanced_success.run_count, 1)
        self.assertEqual(advanced_success.failure_count, 0)
        self.assertGreater(advanced_success.next_run_at, success.finished_at)
        self.assertEqual(advanced_failure.last_status, "FAILED")
        self.assertEqual(advanced_failure.failure_count, 1)
        self.assertGreater(advanced_failure.next_run_at, failed.finished_at)

    def test_builds_operations_scheduler_health_alerts(self) -> None:
        task = build_operations_scheduled_tasks(now="2026-05-20T03:00:00+00:00")[0]
        failed_run = run_operations_scheduled_tasks(
            [task],
            {"closed_loop_snapshot": lambda item: (_ for _ in ()).throw(RuntimeError("boom"))},
            now="2026-05-20T03:05:00+00:00",
        )
        stale_task = operations_scheduled_task_from_dict(
            {
                **operations_scheduled_task_to_dict(task),
                "failure_count": 3,
                "lease_owner": "worker-a",
                "lease_expires_at": "2026-05-20T03:00:00+00:00",
                "last_run_at": "2026-05-19T03:00:00+00:00",
            }
        )

        health = build_operations_scheduler_health_report(
            [failed_run],
            [stale_task],
            now="2026-05-20T04:00:00+00:00",
            stale_lease_seconds=300,
            stale_task_seconds=3600,
        )
        rendered = render_operations_scheduler_health_report(health)

        self.assertEqual(health.failed_runs, 1)
        self.assertEqual(health.stale_leases, 1)
        self.assertTrue(any(alert["alert_type"] == "operations_scheduler_run_failed" for alert in health.alerts))
        self.assertTrue(any(alert["alert_type"] == "operations_scheduler_stale_lease" for alert in health.alerts))
        self.assertTrue(any(alert["alert_type"] == "operations_scheduler_task_repeated_failures" for alert in health.alerts))
        self.assertIn("Operations scheduler health:", rendered)

    def test_builds_operations_console_overview_payload(self) -> None:
        closed_loop = build_operations_closed_loop_report(generated_at="2026-05-20T03:00:00+00:00")
        snapshot = build_operations_closed_loop_snapshot(
            closed_loop,
            snapshot_id="CLP-OVERVIEW",
            created_at="2026-05-20T03:05:00+00:00",
            metadata={"department": "finance", "tenant": "corp-a"},
        )
        dashboard = build_operations_closed_loop_dashboard([snapshot], generated_at="2026-05-20T03:10:00+00:00")
        payload = {
            "event_id": "WHK-OVERVIEW",
            "data": {
                "status": "CLOSED",
                "updated_at": "2026-05-20T03:00:00+00:00",
            },
        }
        event = build_oncall_webhook_event(
            payload,
            raw_body=json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            now="2026-05-20T03:05:00+00:00",
        )
        job = build_oncall_webhook_replay_job(
            [event.event_id],
            requested_by="ops",
            patch_template_id="missing_ticket_status",
            created_at="2026-05-20T03:06:00+00:00",
        )

        overview = build_operations_console_overview(
            dashboard,
            build_oncall_webhook_ops_console([event], generated_at="2026-05-20T03:10:00+00:00"),
            [job],
            generated_at="2026-05-20T03:11:00+00:00",
        )
        json_payload = json.loads(render_operations_console_overview_json(overview))

        self.assertIn("closed_loop_snapshots=1", overview.summary)
        self.assertEqual(json_payload["operations_console_overview"]["webhook_ops"]["dead_letters"], 1)
        self.assertEqual(json_payload["operations_console_overview"]["replay_jobs"][0]["status"], "PENDING")

    def test_builds_operations_console_view_with_rbac_actions(self) -> None:
        dashboard = build_operations_closed_loop_dashboard([], generated_at="2026-05-20T03:10:00+00:00")
        overview = build_operations_console_overview(
            dashboard,
            build_oncall_webhook_ops_console([], generated_at="2026-05-20T03:10:00+00:00"),
            [],
            generated_at="2026-05-20T03:11:00+00:00",
        )
        policy = PermissionPolicy(enabled=True, required_roles={"ops"})

        ops_view = build_operations_console_view(
            overview,
            actor="ops-user",
            roles=["ops"],
            department="platform",
            permission_policy=policy,
            generated_at="2026-05-20T03:12:00+00:00",
        )
        viewer_view = build_operations_console_view(
            overview,
            actor="viewer",
            roles=["viewer"],
            permission_policy=policy,
            generated_at="2026-05-20T03:12:00+00:00",
        )
        ops_json = json.loads(render_operations_console_view_json(ops_view))
        ops_html = render_operations_console_view_html(ops_view)
        viewer_html = render_operations_console_view_html(viewer_view)

        self.assertFalse(ops_view.read_only)
        self.assertIn("replay_jobs", ops_view.visible_sections)
        self.assertTrue(all(item["allowed"] for item in ops_view.actions))
        self.assertTrue(viewer_view.read_only)
        self.assertEqual(viewer_view.visible_sections, [])
        self.assertEqual(ops_json["operations_console_view"]["actor"], "ops-user")
        self.assertIn("Operations Console", ops_html)
        self.assertIn("Access denied", viewer_html)

    def test_builds_closed_loop_dashboard_payload_and_serves_it_over_http(self) -> None:
        closed_loop = build_operations_closed_loop_report(
            trend_alerts=[
                operations_trend_alert_from_dict(
                    {
                        "alert_id": "TREND-DASH",
                        "metric": "critical_alerts",
                        "severity": "critical",
                        "route": "ops",
                        "escalation": "page",
                        "owner": "ops",
                        "current": 2,
                        "previous": 1,
                        "delta": 1,
                        "delta_percent": 100.0,
                        "reason": "growth",
                        "action_item": "Handle critical alerts",
                    }
                )
            ],
            action_items=[
                operations_action_item_from_dict(
                    {
                        "action_id": "ACT-DASH",
                        "source_type": "trend_alert",
                        "source_id": "TREND-DASH",
                        "title": "Handle critical alerts",
                        "owner": "ops",
                        "status": "OPEN",
                        "eta": None,
                        "created_at": "2026-05-20T00:00:00+00:00",
                        "updated_at": "2026-05-20T00:00:00+00:00",
                        "evidence": ["metric=critical_alerts"],
                        "closure_note": None,
                    }
                )
            ],
            knowledge_entries=[],
            generated_at="2026-05-20T03:00:00+00:00",
        )
        snapshot = build_operations_closed_loop_snapshot(
            closed_loop,
            snapshot_id="CLP-DASH",
            created_at="2026-05-20T03:05:00+00:00",
            metadata={"department": "finance", "tenant": "corp-a"},
        )
        dashboard = build_operations_closed_loop_dashboard([snapshot], generated_at="2026-05-20T03:10:00+00:00")
        filtered_dashboard = build_operations_closed_loop_dashboard(
            [snapshot],
            generated_at="2026-05-20T03:11:00+00:00",
            owner="ops",
            department="finance",
            tenant="corp-a",
        )
        empty_dashboard = build_operations_closed_loop_dashboard(
            [snapshot],
            generated_at="2026-05-20T03:12:00+00:00",
            department="sales",
        )
        dashboard_json = render_operations_closed_loop_dashboard_json(dashboard)
        serialized = operations_closed_loop_dashboard_to_dict(dashboard)

        store = InMemorySessionStore()
        store.record_operations_closed_loop_snapshot(operations_closed_loop_snapshot_to_dict(snapshot))
        dead_letter_payload = {
            "event_id": "WHK-HTTP-CONSOLE",
            "data": {
                "status": "CLOSED",
                "updated_at": "2026-05-20T03:00:00+00:00",
            },
        }
        dead_letter_event = build_oncall_webhook_event(
            dead_letter_payload,
            raw_body=json.dumps(dead_letter_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            now="2026-05-20T03:05:00+00:00",
        )
        store.record_oncall_webhook_event(oncall_webhook_event_to_dict(dead_letter_event))
        replay_job = build_oncall_webhook_replay_job(
            [dead_letter_event.event_id],
            requested_by="ops",
            patch_template_id="missing_ticket_status",
            created_at="2026-05-20T03:06:00+00:00",
        )
        store.record_oncall_webhook_replay_job(oncall_webhook_replay_job_to_dict(replay_job))
        schedule_task = build_operations_scheduled_tasks(now="2026-05-20T03:00:00+00:00")[2]
        store.record_operations_scheduled_task(operations_scheduled_task_to_dict(schedule_task))
        registry_server = create_schema_registry_server(token="schema-token")
        registry_thread = run_metrics_server_in_thread(registry_server)
        registry_host, registry_port = registry_server.server_address
        server = create_operations_dashboard_server(store, port=0, limit=10, token="dash-token")
        thread = run_metrics_server_in_thread(server)
        host, port = server.server_address
        try:
            with self.assertRaises(HTTPError) as raised:
                urlopen(f"http://{host}:{port}/operations/closed-loop", timeout=5)
            self.assertEqual(raised.exception.code, 401)
            request = Request(
                f"http://{host}:{port}/operations/closed-loop?owner=ops&department=finance&tenant=corp-a",
                headers={"Authorization": "Bearer dash-token"},
            )
            with urlopen(request, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
            snapshots_request = Request(
                f"http://{host}:{port}/operations/closed-loop/snapshots?owner=ops",
                headers={"Authorization": "Bearer dash-token"},
            )
            with urlopen(snapshots_request, timeout=5) as response:
                snapshots_payload = json.loads(response.read().decode("utf-8"))
            webhook_ops_request = Request(
                f"http://{host}:{port}/operations/oncall-webhook-ops",
                headers={"X-Operations-Dashboard-Token": "dash-token"},
            )
            with urlopen(webhook_ops_request, timeout=5) as response:
                webhook_ops_payload = json.loads(response.read().decode("utf-8"))
            replay_jobs_request = Request(
                f"http://{host}:{port}/operations/oncall-webhook-replay-jobs",
                headers={"X-Operations-Dashboard-Token": "dash-token"},
            )
            with urlopen(replay_jobs_request, timeout=5) as response:
                replay_jobs_payload = json.loads(response.read().decode("utf-8"))
            console_request = Request(
                f"http://{host}:{port}/operations/console?limit=10",
                headers={"Authorization": "Bearer dash-token"},
            )
            with urlopen(console_request, timeout=5) as response:
                console_payload = json.loads(response.read().decode("utf-8"))
            console_view_request = Request(
                f"http://{host}:{port}/operations/console/view?limit=10",
                headers={
                    "Authorization": "Bearer dash-token",
                    "X-Operations-Actor": "ops-user",
                    "X-Operations-Roles": "ops",
                    "X-Operations-Department": "platform",
                },
            )
            with urlopen(console_view_request, timeout=5) as response:
                console_view_payload = json.loads(response.read().decode("utf-8"))
            console_ui_request = Request(
                f"http://{host}:{port}/operations/console/ui?limit=10",
                headers={
                    "Authorization": "Bearer dash-token",
                    "X-Operations-Actor": "ops-user",
                    "X-Operations-Roles": "ops",
                },
            )
            with urlopen(console_ui_request, timeout=5) as response:
                console_ui = response.read().decode("utf-8")
            create_action_request = Request(
                f"http://{host}:{port}/operations/console/actions",
                data=json.dumps(
                    {
                        "action": "create_replay_job",
                        "limit": 1,
                        "requested_by": "ops-ui",
                        "patch_template_id": "missing_ticket_status",
                    },
                    ensure_ascii=False,
                ).encode("utf-8"),
                headers={
                    "Authorization": "Bearer dash-token",
                    "Content-Type": "application/json",
                    "X-Operations-Actor": "ops-user",
                    "X-Operations-Roles": "ops",
                },
                method="POST",
            )
            with urlopen(create_action_request, timeout=5) as response:
                create_action_payload = json.loads(response.read().decode("utf-8"))
            execute_action_request = Request(
                f"http://{host}:{port}/operations/console/actions",
                data=json.dumps(
                    {
                        "action": "execute_replay_jobs",
                        "limit": 10,
                        "patches": {
                            dead_letter_event.event_id: {
                                "ticket_status": {
                                    "ticket_id": "INC-HTTP-CONSOLE",
                                    "status": "CLOSED",
                                    "updated_at": "2026-05-20T03:00:00+00:00",
                                }
                            }
                        },
                    },
                    ensure_ascii=False,
                ).encode("utf-8"),
                headers={
                    "Authorization": "Bearer dash-token",
                    "Content-Type": "application/json",
                    "X-Operations-Actor": "ops-user",
                    "X-Operations-Roles": "ops",
                },
                method="POST",
            )
            with urlopen(execute_action_request, timeout=5) as response:
                execute_action_payload = json.loads(response.read().decode("utf-8"))
            scheduler_action_request = Request(
                f"http://{host}:{port}/operations/console/actions",
                data=json.dumps(
                    {
                        "action": "run_operations_schedule",
                        "limit": 10,
                        "persisted": True,
                        "owner": "ops-ui",
                        "now": "2026-05-20T03:05:00+00:00",
                    },
                    ensure_ascii=False,
                ).encode("utf-8"),
                headers={
                    "Authorization": "Bearer dash-token",
                    "Content-Type": "application/json",
                    "X-Operations-Actor": "ops-user",
                    "X-Operations-Roles": "ops",
                },
                method="POST",
            )
            with urlopen(scheduler_action_request, timeout=5) as response:
                scheduler_action_payload = json.loads(response.read().decode("utf-8"))
            publish_action_request = Request(
                f"http://{host}:{port}/operations/console/actions",
                data=json.dumps(
                    {
                        "action": "publish_closed_loop_schema",
                        "endpoint": f"http://{registry_host}:{registry_port}/schema-registry",
                        "token": "schema-token",
                        "server_url": f"http://{host}:{port}",
                    },
                    ensure_ascii=False,
                ).encode("utf-8"),
                headers={
                    "Authorization": "Bearer dash-token",
                    "Content-Type": "application/json",
                    "X-Operations-Actor": "ops-user",
                    "X-Operations-Roles": "ops",
                },
                method="POST",
            )
            with urlopen(publish_action_request, timeout=5) as response:
                publish_action_payload = json.loads(response.read().decode("utf-8"))
            propose_governance_request = Request(
                f"http://{host}:{port}/operations/console/actions",
                data=json.dumps(
                    {
                        "action": "propose_governance_policy_change",
                        "before": {"allowed_actions": ["replan"]},
                        "after": {
                            "allowed_actions": ["replan", "retry_status_refresh"],
                            "max_executions_per_session": 2,
                        },
                        "reason": "allow safe retry",
                    },
                    ensure_ascii=False,
                ).encode("utf-8"),
                headers={
                    "Authorization": "Bearer dash-token",
                    "Content-Type": "application/json",
                    "X-Operations-Actor": "ops-a",
                    "X-Operations-Roles": "ops",
                },
                method="POST",
            )
            with urlopen(propose_governance_request, timeout=5) as response:
                propose_governance_payload = json.loads(response.read().decode("utf-8"))
            proposed_change_id = propose_governance_payload["operations_console_action"]["change"]["change_id"]
            approve_governance_request = Request(
                f"http://{host}:{port}/operations/console/actions",
                data=json.dumps(
                    {
                        "action": "approve_governance_policy_change",
                        "change_id": proposed_change_id,
                        "approved_by": "ops-b",
                        "applied_at": "2026-05-20T03:20:00+00:00",
                    },
                    ensure_ascii=False,
                ).encode("utf-8"),
                headers={
                    "Authorization": "Bearer dash-token",
                    "Content-Type": "application/json",
                    "X-Operations-Actor": "ops-b",
                    "X-Operations-Roles": "ops",
                },
                method="POST",
            )
            with urlopen(approve_governance_request, timeout=5) as response:
                approve_governance_payload = json.loads(response.read().decode("utf-8"))
            rollback_governance_request = Request(
                f"http://{host}:{port}/operations/console/actions",
                data=json.dumps(
                    {
                        "action": "rollback_governance_policy_change",
                        "change_id": proposed_change_id,
                        "requested_by": "ops-c",
                        "requested_at": "2026-05-20T03:25:00+00:00",
                    },
                    ensure_ascii=False,
                ).encode("utf-8"),
                headers={
                    "Authorization": "Bearer dash-token",
                    "Content-Type": "application/json",
                    "X-Operations-Actor": "ops-c",
                    "X-Operations-Roles": "ops",
                },
                method="POST",
            )
            with urlopen(rollback_governance_request, timeout=5) as response:
                rollback_governance_payload = json.loads(response.read().decode("utf-8"))
            audit_timeline_request = Request(
                f"http://{host}:{port}/operations/console/audit-timeline?limit=20",
                headers={"Authorization": "Bearer dash-token"},
            )
            with urlopen(audit_timeline_request, timeout=5) as response:
                audit_timeline_payload = json.loads(response.read().decode("utf-8"))
            governance_timeline_request = Request(
                f"http://{host}:{port}/operations/console/audit-timeline?event_type=governance_policy_change&status=ROLLED_BACK",
                headers={"Authorization": "Bearer dash-token"},
            )
            with urlopen(governance_timeline_request, timeout=5) as response:
                governance_timeline_payload = json.loads(response.read().decode("utf-8"))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
            registry_server.shutdown()
            registry_server.server_close()
            registry_thread.join(timeout=5)

        self.assertEqual(serialized["schema_version"], "travel.operations.closed_loop.v1")
        self.assertEqual(dashboard.snapshot_count, 1)
        self.assertEqual(filtered_dashboard.filters["owner"], "ops")
        self.assertEqual(filtered_dashboard.filters["department"], "finance")
        self.assertEqual(filtered_dashboard.filters["tenant"], "corp-a")
        self.assertEqual(empty_dashboard.snapshot_count, 0)
        self.assertEqual(serialized["latest_snapshot"]["metadata"]["tenant"], "corp-a")
        self.assertEqual(serialized["checkpoint"], "2026-05-20T03:05:00+00:00")
        self.assertIn("closed_loop_dashboard", dashboard_json)
        self.assertEqual(payload["closed_loop_dashboard"]["snapshot_count"], 1)
        self.assertEqual(payload["closed_loop_dashboard"]["filters"]["owner"], "ops")
        self.assertEqual(payload["closed_loop_dashboard"]["filters"]["department"], "finance")
        self.assertEqual(payload["closed_loop_dashboard"]["filters"]["tenant"], "corp-a")
        self.assertEqual(snapshots_payload["closed_loop_dashboard"]["latest_snapshot"]["snapshot_id"], "CLP-DASH")
        self.assertEqual(webhook_ops_payload["oncall_webhook_ops_console"]["dead_letters"], 1)
        self.assertEqual(replay_jobs_payload["oncall_webhook_replay_jobs"][0]["job_id"], replay_job.job_id)
        self.assertEqual(console_payload["operations_console_overview"]["webhook_ops"]["dead_letters"], 1)
        self.assertEqual(console_payload["operations_console_overview"]["replay_jobs"][0]["job_id"], replay_job.job_id)
        self.assertIn("closed_loop_snapshots=1", console_payload["operations_console_overview"]["summary"])
        self.assertEqual(console_view_payload["operations_console_view"]["actor"], "ops-user")
        self.assertIn("replay_jobs", console_view_payload["operations_console_view"]["visible_sections"])
        self.assertIn("Operations Console", console_ui)
        self.assertIn("Replay Jobs", console_ui)
        create_action = create_action_payload["operations_console_action"]
        self.assertTrue(create_action["ok"])
        self.assertEqual(create_action["authorization"]["action"], "create_replay_job")
        self.assertEqual(create_action["job"]["requested_by"], "ops-ui")
        self.assertEqual(create_action["job"]["status"], "PENDING")
        self.assertEqual(create_action["job"]["patch_template_id"], "missing_ticket_status")
        self.assertTrue(create_action["action_audit"]["recorded"])
        execute_action = execute_action_payload["operations_console_action"]
        self.assertTrue(execute_action["ok"])
        self.assertEqual(execute_action["authorization"]["action"], "execute_replay_job")
        self.assertGreaterEqual(len(execute_action["executions"]), 1)
        self.assertEqual(execute_action["executions"][0]["job"]["status"], "COMPLETED")
        self.assertEqual(store.list_oncall_ticket_statuses(1)[0]["ticket_id"], "INC-HTTP-CONSOLE")
        self.assertEqual(store.list_oncall_webhook_events(1)[0]["status"], "REPLAYED")
        scheduler_action = scheduler_action_payload["operations_console_action"]
        self.assertTrue(scheduler_action["ok"])
        self.assertEqual(scheduler_action["authorization"]["action"], "run_operations_schedule")
        self.assertEqual(scheduler_action["scheduler_run"]["due_count"], 1)
        self.assertEqual(store.list_operations_scheduler_runs(1)[0]["run_id"], scheduler_action["scheduler_run"]["run_id"])
        publish_action = publish_action_payload["operations_console_action"]
        self.assertTrue(publish_action["ok"])
        self.assertEqual(publish_action["authorization"]["action"], "publish_closed_loop_schema")
        self.assertEqual(publish_action["publish_result"]["schema_version"], "travel.operations.closed_loop.v1")
        self.assertEqual(registry_server.captured_payload["schema_version"], "travel.operations.closed_loop.v1")
        self.assertEqual(registry_server.captured_token, "Bearer schema-token")
        propose_governance = propose_governance_payload["operations_console_action"]
        self.assertTrue(propose_governance["ok"])
        self.assertEqual(propose_governance["authorization"]["action"], "update_governance_policy")
        self.assertEqual(propose_governance["change"]["status"], "PENDING_APPROVAL")
        approve_governance = approve_governance_payload["operations_console_action"]
        self.assertTrue(approve_governance["ok"])
        self.assertEqual(approve_governance["change"]["status"], "APPLIED")
        self.assertIn("ops-b", approve_governance["change"]["approvals"])
        rollback_governance = rollback_governance_payload["operations_console_action"]
        self.assertTrue(rollback_governance["ok"])
        self.assertEqual(rollback_governance["change"]["status"], "ROLLED_BACK")
        self.assertEqual(store.list_operations_governance_policy_changes(1)[0]["status"], "ROLLED_BACK")
        self.assertTrue(rollback_governance["action_audit"]["recorded"])
        action_audits = store.list_operations_console_action_audits(10)
        self.assertGreaterEqual(len(action_audits), 7)
        self.assertEqual(action_audits[0]["action"], "rollback_governance_policy_change")
        self.assertEqual(action_audits[0]["status"], "SUCCESS")
        self.assertEqual(action_audits[0]["result_summary"]["change_status"], "ROLLED_BACK")
        timeline_events = audit_timeline_payload["operations_audit_timeline"]["events"]
        self.assertGreaterEqual(len(timeline_events), 4)
        self.assertIn("console_action", {item["event_type"] for item in timeline_events})
        self.assertIn("replay_job", {item["event_type"] for item in timeline_events})
        self.assertIn("scheduler_run", {item["event_type"] for item in timeline_events})
        self.assertEqual(
            governance_timeline_payload["operations_audit_timeline"]["events"][0]["event_type"],
            "governance_policy_change",
        )
        self.assertEqual(
            governance_timeline_payload["operations_audit_timeline"]["events"][0]["status"],
            "ROLLED_BACK",
        )
        self.assertIn("oncall_webhook_ops_console", build_oncall_webhook_ops_console_json(store))
        self.assertIn("oncall_webhook_replay_jobs", build_oncall_webhook_replay_jobs_json(store))
        self.assertIn("operations_console_overview", build_operations_console_overview_json(store))
        self.assertIn("operations_console_view", build_operations_console_view_json(store, actor="ops-user", roles=["ops"]))
        self.assertIn("Operations Console", build_operations_console_view_html(store, actor="ops-user", roles=["ops"]))

    def test_closed_loop_dashboard_supports_cursor_pagination(self) -> None:
        report = build_operations_closed_loop_report(generated_at="2026-05-20T03:00:00+00:00")
        newest = build_operations_closed_loop_snapshot(
            report,
            snapshot_id="CLP-NEW",
            created_at="2026-05-20T03:10:00+00:00",
        )
        older = build_operations_closed_loop_snapshot(
            report,
            snapshot_id="CLP-OLD",
            created_at="2026-05-20T03:00:00+00:00",
        )

        first_page = build_operations_closed_loop_dashboard(
            [older, newest],
            generated_at="2026-05-20T03:11:00+00:00",
            limit=1,
        )
        second_page = build_operations_closed_loop_dashboard(
            [older, newest],
            generated_at="2026-05-20T03:12:00+00:00",
            limit=1,
            cursor=first_page.next_cursor,
        )
        serialized = operations_closed_loop_dashboard_to_dict(first_page)
        checkpoint_page = build_operations_closed_loop_dashboard(
            [older, newest],
            generated_at="2026-05-20T03:13:00+00:00",
            limit=1,
            checkpoint=first_page.checkpoint,
        )
        store = InMemorySessionStore()
        store.record_operations_closed_loop_snapshot(operations_closed_loop_snapshot_to_dict(older))
        store.record_operations_closed_loop_snapshot(operations_closed_loop_snapshot_to_dict(newest))
        helper_payload = json.loads(build_operations_closed_loop_dashboard_json(store, limit=1))
        helper_next_payload = json.loads(
            build_operations_closed_loop_dashboard_json(
                store,
                limit=1,
                cursor=helper_payload["closed_loop_dashboard"]["next_cursor"],
            )
        )

        self.assertEqual(first_page.snapshot_count, 1)
        self.assertTrue(first_page.has_more)
        self.assertEqual(first_page.next_cursor, "2026-05-20T03:10:00+00:00")
        self.assertEqual(second_page.snapshots[0].snapshot_id, "CLP-OLD")
        self.assertEqual(first_page.checkpoint, "2026-05-20T03:10:00+00:00")
        self.assertEqual(checkpoint_page.snapshots[0].snapshot_id, "CLP-OLD")
        self.assertEqual(serialized["limit"], 1)
        self.assertTrue(serialized["has_more"])
        self.assertEqual(serialized["next_cursor"], "2026-05-20T03:10:00+00:00")
        self.assertEqual(serialized["checkpoint"], "2026-05-20T03:10:00+00:00")
        self.assertEqual(helper_payload["closed_loop_dashboard"]["limit"], 1)
        self.assertEqual(
            helper_next_payload["closed_loop_dashboard"]["latest_snapshot"]["snapshot_id"],
            "CLP-OLD",
        )

    def test_closed_loop_contract_schema_openapi_and_validation(self) -> None:
        report = build_operations_closed_loop_report(generated_at="2026-05-20T03:00:00+00:00")
        snapshot = build_operations_closed_loop_snapshot(
            report,
            snapshot_id="CLP-CONTRACT",
            created_at="2026-05-20T03:10:00+00:00",
            metadata={"department": "finance", "tenant": "corp-a"},
        )
        dashboard = build_operations_closed_loop_dashboard(
            [snapshot],
            generated_at="2026-05-20T03:11:00+00:00",
            department="finance",
            tenant="corp-a",
        )

        schema = build_operations_closed_loop_json_schema()
        openapi = build_operations_closed_loop_openapi_spec("https://ops.example")
        validation = validate_operations_closed_loop_dashboard_contract(dashboard)
        schema_http = CapturingAnyHttpClient({"https://schema.example/registry": {"ok": True, "accepted": 1}})
        publish = publish_operations_closed_loop_schema_http(
            "https://schema.example/registry",
            token="schema-token",
            http_client=schema_http,
            server_url="https://ops.example",
        )
        quality = evaluate_operations_closed_loop_quality(dashboard, generated_at="2026-05-20T03:12:00+00:00")
        checkpoint = build_operations_closed_loop_checkpoint_plan(
            dashboard,
            generated_at="2026-05-20T03:13:00+00:00",
        )
        acceptance = build_operations_closed_loop_acceptance_report(
            dashboard,
            generated_at="2026-05-20T03:14:00+00:00",
        )

        self.assertEqual(schema["properties"]["closed_loop_dashboard"]["properties"]["schema_version"]["const"], "travel.operations.closed_loop.v1")
        self.assertEqual(openapi["servers"][0]["url"], "https://ops.example")
        self.assertTrue(validation["ok"])
        self.assertTrue(publish.ok)
        self.assertEqual(schema_http.calls[0][2], "schema-token")
        self.assertEqual(schema_http.calls[0][1]["schema_version"], "travel.operations.closed_loop.v1")
        self.assertTrue(quality.ok)
        self.assertTrue(checkpoint.ready)
        self.assertEqual(checkpoint.next_checkpoint, "2026-05-20T03:10:00+00:00")
        self.assertTrue(acceptance.ok)
        self.assertIn("travel.operations.closed_loop.v1", render_operations_closed_loop_json_schema())
        self.assertIn("/operations/closed-loop", render_operations_closed_loop_openapi_spec("https://ops.example"))
        self.assertIn("Operations closed-loop contract validation:", render_operations_closed_loop_contract_validation(validation))
        self.assertIn("Operations closed-loop schema publish:", render_operations_closed_loop_schema_publish_result(publish))
        self.assertIn("Operations closed-loop quality:", render_operations_closed_loop_quality_report(quality))
        self.assertIn("Operations closed-loop checkpoint plan:", render_operations_closed_loop_checkpoint_plan(checkpoint))
        self.assertIn("Operations closed-loop acceptance:", render_operations_closed_loop_acceptance_report(acceptance))


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


def create_schema_registry_server(token: str | None = None) -> ThreadingHTTPServer:
    class SchemaRegistryHandler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length).decode("utf-8") if length else "{}"
            self.server.captured_payload = json.loads(raw)
            self.server.captured_token = self.headers.get("Authorization")
            expected = f"Bearer {token}" if token else None
            if expected and self.server.captured_token != expected:
                self.send_response(401)
                self.end_headers()
                return
            body = json.dumps(
                {
                    "ok": True,
                    "accepted": 1,
                    "schema_version": self.server.captured_payload.get("schema_version"),
                    "detail": "accepted by test registry",
                },
                ensure_ascii=False,
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            del format, args

    server = ThreadingHTTPServer(("127.0.0.1", 0), SchemaRegistryHandler)
    server.captured_payload = {}
    server.captured_token = None
    return server


class FailingHttpClient:
    def post_json(self, url: str, payload: dict[str, Any], token: str | None = None) -> dict[str, Any]:
        del url, payload, token
        raise RuntimeError("remote config unavailable")


def _test_add_seconds(value: str, seconds: int) -> str:
    from datetime import datetime, timezone

    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return datetime.fromtimestamp(parsed.timestamp() + seconds, timezone.utc).isoformat()


class FakeSessionStoreHttpClient:
    def __init__(self) -> None:
        self.sessions: dict[str, dict[str, Any]] = {}
        self.worker_runs: list[dict[str, Any]] = []
        self.dashboard_snapshots: list[dict[str, Any]] = []
        self.closed_loop_snapshots: list[dict[str, Any]] = []
        self.oncall_statuses: list[dict[str, Any]] = []
        self.oncall_webhook_events: list[dict[str, Any]] = []
        self.oncall_webhook_replay_jobs: list[dict[str, Any]] = []
        self.trend_alerts: list[dict[str, Any]] = []
        self.action_items: list[dict[str, Any]] = []
        self.knowledge_entries: list[dict[str, Any]] = []
        self.scheduled_tasks: list[dict[str, Any]] = []
        self.scheduler_runs: list[dict[str, Any]] = []
        self.governance_policy_changes: list[dict[str, Any]] = []
        self.console_action_audits: list[dict[str, Any]] = []
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
        if path == "/operations/closed-loop-snapshots/record":
            self.closed_loop_snapshots = [
                snapshot
                for snapshot in self.closed_loop_snapshots
                if snapshot.get("snapshot_id") != payload["snapshot"].get("snapshot_id")
            ]
            self.closed_loop_snapshots.append(dict(payload["snapshot"]))
            return {"ok": True}
        if path == "/operations/closed-loop-snapshots/list":
            return {"snapshots": list(reversed(self.closed_loop_snapshots))[0 : int(payload["limit"])]}
        if path == "/operations/oncall-statuses/record":
            self.oncall_statuses.append(dict(payload["status"]))
            return {"ok": True}
        if path == "/operations/oncall-statuses/list":
            return {"statuses": list(reversed(self.oncall_statuses))[0 : int(payload["limit"])]}
        if path == "/operations/oncall-webhooks/record":
            self.oncall_webhook_events = [
                event
                for event in self.oncall_webhook_events
                if event.get("event_id") != payload["event"].get("event_id")
            ]
            self.oncall_webhook_events.append(dict(payload["event"]))
            return {"ok": True}
        if path == "/operations/oncall-webhooks/list":
            return {"events": list(reversed(self.oncall_webhook_events))[0 : int(payload["limit"])]}
        if path == "/operations/oncall-webhook-replay-jobs/record":
            self.oncall_webhook_replay_jobs = [
                job
                for job in self.oncall_webhook_replay_jobs
                if job.get("job_id") != payload["job"].get("job_id")
            ]
            self.oncall_webhook_replay_jobs.append(dict(payload["job"]))
            return {"ok": True}
        if path == "/operations/oncall-webhook-replay-jobs/list":
            return {"jobs": list(reversed(self.oncall_webhook_replay_jobs))[0 : int(payload["limit"])]}
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
        if path == "/operations/scheduled-tasks/record":
            self.scheduled_tasks = [
                task for task in self.scheduled_tasks if task.get("task_id") != payload["task"].get("task_id")
            ]
            self.scheduled_tasks.append(dict(payload["task"]))
            return {"ok": True}
        if path == "/operations/scheduled-tasks/list":
            return {"tasks": sorted(self.scheduled_tasks, key=lambda task: task.get("next_run_at", ""))[0 : int(payload["limit"])]}
        if path == "/operations/scheduled-tasks/claim-due":
            owner = str(payload["owner"])
            now = str(payload["now"])
            lease_seconds = int(payload["lease_seconds"])
            lease_expires_at = _test_add_seconds(now, lease_seconds)
            claimed = []
            for task in sorted(self.scheduled_tasks, key=lambda item: item.get("next_run_at", "")):
                if len(claimed) >= int(payload["limit"]):
                    break
                if not task.get("enabled", True) or str(task.get("next_run_at") or "") > now:
                    continue
                lease_owner = str(task.get("lease_owner") or "")
                lease_expires = str(task.get("lease_expires_at") or "")
                if lease_owner and lease_expires > now:
                    continue
                task.update({"lease_owner": owner, "lease_expires_at": lease_expires_at})
                claimed.append(dict(task))
            return {"tasks": claimed}
        if path == "/operations/scheduled-tasks/complete":
            self.scheduled_tasks = [
                task for task in self.scheduled_tasks if task.get("task_id") != payload["task"].get("task_id")
            ]
            self.scheduled_tasks.append(dict(payload["task"]))
            return {"ok": True}
        if path == "/operations/scheduler-runs/record":
            self.scheduler_runs = [
                run for run in self.scheduler_runs if run.get("run_id") != payload["run"].get("run_id")
            ]
            self.scheduler_runs.append(dict(payload["run"]))
            return {"ok": True}
        if path == "/operations/scheduler-runs/list":
            return {"runs": list(reversed(self.scheduler_runs))[0 : int(payload["limit"])]}
        if path == "/operations/governance-policy-changes/record":
            self.governance_policy_changes = [
                change
                for change in self.governance_policy_changes
                if change.get("change_id") != payload["change"].get("change_id")
            ]
            self.governance_policy_changes.append(dict(payload["change"]))
            return {"ok": True}
        if path == "/operations/governance-policy-changes/list":
            return {"changes": list(reversed(self.governance_policy_changes))[0 : int(payload["limit"])]}
        if path == "/operations/console-action-audits/record":
            self.console_action_audits = [
                audit for audit in self.console_action_audits if audit.get("audit_id") != payload["audit"].get("audit_id")
            ]
            self.console_action_audits.append(dict(payload["audit"]))
            return {"ok": True}
        if path == "/operations/console-action-audits/list":
            return {"audits": list(reversed(self.console_action_audits))[0 : int(payload["limit"])]}
        if path == "/health":
            return {
                "backend": "http-json",
                "ok": True,
                "schema_version": 8,
                "session_count": len(self.sessions),
                "worker_run_count": len(self.worker_runs),
                "details": {
                    "contract": "session-store-v1",
                    "dashboard_snapshots": str(len(self.dashboard_snapshots)),
                    "closed_loop_snapshots": str(len(self.closed_loop_snapshots)),
                    "oncall_ticket_statuses": str(len(self.oncall_statuses)),
                    "oncall_webhook_events": str(len(self.oncall_webhook_events)),
                    "oncall_webhook_replay_jobs": str(len(self.oncall_webhook_replay_jobs)),
                    "operations_trend_alerts": str(len(self.trend_alerts)),
                    "operations_action_items": str(len(self.action_items)),
                    "operations_knowledge_entries": str(len(self.knowledge_entries)),
                    "operations_scheduled_tasks": str(len(self.scheduled_tasks)),
                    "operations_scheduler_runs": str(len(self.scheduler_runs)),
                    "operations_governance_policy_changes": str(len(self.governance_policy_changes)),
                    "operations_console_action_audits": str(len(self.console_action_audits)),
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
