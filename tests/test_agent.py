from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from travel_agent.agent import build_default_agent
from travel_agent.cli import render_context, render_dead_letters, render_metrics, render_worker_runs
from travel_agent.config import IntegrationSettings
from travel_agent.domain_agents import ApprovalAgent, BookingAgent, HotelAgent, PolicyAgent, TransportAgent
from travel_agent.integrations import IntegrationError
from travel_agent.models import DeadLetterNotification, NotificationRecord, TravelRequest, WorkerRunRecord
from travel_agent.state import TravelState
from travel_agent.storage import InMemorySessionStore, SQLiteSessionStore
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
        actions = {(record.agent_name, record.action) for record in context.agent_executions}
        self.assertIn(("TransportAgent", "change_transport_order"), actions)
        self.assertIn(("BookingAgent", "change_hotel_order"), actions)

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
        changed = agent.sync_calendar(changed)

        self.assertEqual(changed.calendar_syncs[-1].event_type, "TRIP_CHANGED")
        self.assertEqual(changed.calendar_syncs[-1].start_at, "2026-06-04")
        self.assertEqual(changed.calendar_syncs[-1].end_at, "2026-06-06")

        cancelled = agent.cancel_trip(changed, "meeting_cancelled")
        cancelled = agent.sync_calendar(cancelled)

        self.assertEqual(cancelled.calendar_syncs[-1].event_type, "TRIP_CANCELLED")

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
        self.assertEqual(context.change_records[0].source, "real")
        self.assertEqual(context.change_records[1].source, "real")
        self.assertEqual(context.change_records[0].change_id, "REMOTE-TCHG-1")
        self.assertEqual(context.change_records[1].change_id, "REMOTE-HCHG-1")

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


class SessionStoreTest(unittest.TestCase):
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
            self.assertEqual(len(changed_reloaded.change_records), 2)

            synced = agent.sync_calendar(changed)
            synced_reloaded = SQLiteSessionStore(db_path).get(synced.session_id)
            self.assertEqual(len(synced_reloaded.calendar_syncs), 1)
            self.assertEqual(synced_reloaded.calendar_syncs[0].event_type, "TRIP_CHANGED")

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
