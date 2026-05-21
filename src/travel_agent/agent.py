from __future__ import annotations

from dataclasses import asdict, replace
from datetime import date, datetime, timezone
from typing import TYPE_CHECKING, Any, Optional
from uuid import NAMESPACE_URL, uuid4, uuid5

from .config import IntegrationSettings
from .data_governance import AuditSink, build_audit_sink
from .domain_agents import AgentTeam, build_agent_team
from .integrations import HttpJsonClient, TravelSystemIntegrations
from .mock_tools import plan_itinerary
from .models import (
    AgentExecutionRecord,
    CalendarSyncRecord,
    ChangeRecord,
    HotelOption,
    NotificationRecord,
    RecoveryRecord,
    RefundEstimate,
    Task,
    TaskPlan,
    TravelContext,
    TravelRequest,
    TransportOption,
)
from .permissions import PermissionPolicy, ensure_permission, evaluate_permission
from .state import TravelState, WorkflowStateMachine
from .storage import HttpSessionStore, InMemorySessionStore, SQLiteSessionStore, SessionStore, StoreHttpClient
from .tools import ToolGateway

if TYPE_CHECKING:
    from .operations import (
        OperationsActionSlaNotificationReport,
        OperationsActionSlaReport,
        OperationsKnowledgeSearchReport,
    )


class SimpleTaskPlanner:
    """Deterministic planner for the policy, hotel, and OA approval workflow."""

    def build_plan(
        self,
        request: TravelRequest,
        knowledge_refs: list[str] | None = None,
        guidance: list[str] | None = None,
    ) -> TaskPlan:
        knowledge_refs = knowledge_refs or []
        guidance = guidance or []
        tasks = [
            Task(
                task_id="check_policy",
                task_type="tool",
                description=f"Check enterprise travel policy for {request.destination_city}.",
            ),
        ]
        if guidance:
            tasks.append(
                Task(
                    task_id="apply_operations_knowledge",
                    task_type="agent",
                    description="Apply historical operations knowledge to planning risk checks and fallback hints.",
                    depends_on=["check_policy"],
                )
            )
            planning_dependencies = ["apply_operations_knowledge"]
        else:
            planning_dependencies = ["check_policy"]
        tasks.extend(
            [
                Task(
                    task_id="plan_itinerary",
                    task_type="tool",
                    description="Create a basic business trip itinerary.",
                    depends_on=planning_dependencies,
                ),
                Task(
                    task_id="check_transport_policy",
                    task_type="tool",
                    description="Check enterprise transport policy for the trip route.",
                    depends_on=["check_policy"],
                ),
                Task(
                    task_id="search_hotels",
                    task_type="tool",
                    description="Search live hotel inventory or mock fallback near the venue.",
                    depends_on=["check_policy", "plan_itinerary"],
                ),
                Task(
                    task_id="search_transport",
                    task_type="tool",
                    description="Search flight or train inventory for the outbound trip.",
                    depends_on=["check_transport_policy", "plan_itinerary"],
                ),
                Task(
                    task_id="create_approval",
                    task_type="tool",
                    description="Create an OA approval record after user confirmation.",
                    depends_on=["search_hotels", "search_transport", "user_confirmation"],
                ),
                Task(
                    task_id="get_approval_status",
                    task_type="tool",
                    description="Track OA approval status before booking.",
                    depends_on=["create_approval"],
                ),
                Task(
                    task_id="lock_hotel_inventory",
                    task_type="tool",
                    description="Lock selected hotel inventory after approval.",
                    depends_on=["get_approval_status"],
                ),
                Task(
                    task_id="create_transport_order",
                    task_type="tool",
                    description="Create a transport order after approval.",
                    depends_on=["get_approval_status"],
                ),
                Task(
                    task_id="verify_hotel_price",
                    task_type="tool",
                    description="Verify current hotel price before order creation.",
                    depends_on=["lock_hotel_inventory"],
                ),
                Task(
                    task_id="create_order",
                    task_type="tool",
                    description="Create a hotel order with the approval and inventory lock.",
                    depends_on=["verify_hotel_price"],
                ),
                Task(
                    task_id="get_order_status",
                    task_type="tool",
                    description="Refresh order status after order creation.",
                    depends_on=["create_order"],
                ),
            ]
        )
        return TaskPlan(
            goal="Create a compliant travel plan, OA approval, transport order, and hotel order.",
            tasks=tasks,
            knowledge_refs=knowledge_refs,
            guidance=guidance,
        )


class TravelAgent:
    def __init__(
        self,
        gateway: ToolGateway,
        planner: Optional[SimpleTaskPlanner] = None,
        state_machine: Optional[WorkflowStateMachine] = None,
        session_store: Optional[SessionStore] = None,
        agent_team: Optional[AgentTeam] = None,
        permission_policy: PermissionPolicy | None = None,
        permission_http_client: Any | None = None,
        audit_sink: AuditSink | None = None,
    ) -> None:
        self.gateway = gateway
        self.planner = planner or SimpleTaskPlanner()
        self.state_machine = state_machine or WorkflowStateMachine()
        self.session_store = session_store or InMemorySessionStore()
        self.agent_team = agent_team or build_agent_team(gateway)
        self.permission_policy = permission_policy or PermissionPolicy.from_env()
        self.permission_http_client = permission_http_client
        self.audit_sink = audit_sink
        if audit_sink is not None:
            self.gateway.audit_sink = audit_sink

    def plan(self, request: TravelRequest) -> TravelContext:
        self._require_permission_for_request(request, "plan_trip")
        context = TravelContext(
            session_id=str(uuid4()),
            request=request,
            state=TravelState.DRAFT.value,
            task_plan=self.planner.build_plan(request),
        )
        context.append_event("Created travel planning session.")
        self._attach_planning_knowledge(context)

        context = self.agent_team.policy.check(context)
        policy = context.policy_result
        if policy is None:
            raise ValueError("PolicyAgent did not return hotel policy.")
        self.state_machine.transition(context, TravelState.POLICY_CHECKED)
        context = self.agent_team.itinerary.plan(context)

        max_price = self._effective_hotel_budget(request, policy.approved_budget)
        context = self.agent_team.hotel.search(context, max_price)
        context = self.agent_team.transport.search(context)
        self.state_machine.transition(context, TravelState.PLAN_GENERATED)
        self.session_store.save(context)
        return context

    def notify_current_state(self, context: TravelContext) -> TravelContext:
        notification = self._build_notification_payload(context)
        if notification is None:
            return context

        event_type, title, message = notification
        dedupe_key = self._notification_dedupe_key(context, event_type)
        existing = self._find_notification(context, event_type, context.workflow_generation)
        if existing and self._notification_terminal(existing):
            context.append_event(f"Notification skipped: {event_type} already terminal.")
            self.session_store.save(context)
            return context

        if dedupe_key in context.notification_keys and existing is None:
            context.notification_keys.remove(dedupe_key)

        record = self._send_or_record_notification(
            context=context,
            event_type=event_type,
            title=title,
            message=message,
            channel="im",
            existing=existing,
        )
        self._upsert_notification(context, record)
        if record.status in {"SENT", "DELIVERED", "DONE"} and dedupe_key not in context.notification_keys:
            context.notification_keys.append(dedupe_key)
        context.append_event(f"Notification {event_type} -> {record.status}.")
        self.session_store.save(context)
        return context

    def notify_operations_action_sla(
        self,
        report: OperationsActionSlaReport,
        channel: str = "im",
    ) -> OperationsActionSlaNotificationReport:
        from .operations import OperationsActionSlaNotificationReport

        notifications: list[NotificationRecord] = []
        for finding in report.findings:
            event_type = f"OPERATIONS_ACTION_SLA_{finding.action_id}"
            title = f"Operations action SLA {finding.severity}: {finding.action_id}"
            message = f"{finding.escalation}. {finding.reason}"
            payload = {
                "action_id": finding.action_id,
                "severity": finding.severity,
                "owner": finding.owner,
                "route": finding.route,
                "age_hours": finding.age_hours,
                "overdue_hours": finding.overdue_hours,
                "reason": finding.reason,
                "reminder": finding.reminder,
                "sla_now": report.now,
            }
            try:
                record = self.gateway.call(
                    "send_notification",
                    session_id="operations-action-sla",
                    user_id=finding.owner,
                    event_type=event_type,
                    title=title,
                    message=message,
                    channel=channel,
                    payload=payload,
                    workflow_generation=1,
                )
            except Exception as exc:
                notification_id = "NTF-" + uuid5(
                    NAMESPACE_URL,
                    f"operations-action-sla:{finding.action_id}:{finding.owner}",
                ).hex[:10].upper()
                record = NotificationRecord(
                    notification_id=notification_id,
                    event_type=event_type,
                    channel=channel,
                    recipient_id=finding.owner,
                    title=title,
                    message=message,
                    status="FAILED",
                    payload=payload,
                    source="local",
                    retry_count=1,
                    max_retries=1,
                    last_error=str(exc),
                )
            notifications.append(record)
        failed_count = sum(
            1
            for notification in notifications
            if notification.status.upper() in {"FAILED", "DEAD_LETTER", "ERROR"}
        )
        return OperationsActionSlaNotificationReport(
            notification_count=len(notifications),
            failed_count=failed_count,
            notifications=notifications,
        )

    def confirm_and_create_approval(
        self,
        context: TravelContext,
        selected_hotel_id: Optional[str] = None,
        selected_transport_id: Optional[str] = None,
    ) -> TravelContext:
        self._require_permission(context, "create_approval")
        selected_hotel = self._select_hotel(context.hotel_options, selected_hotel_id)
        selected_transport = self._select_transport(context.transport_options, selected_transport_id)
        context.selected_hotel = selected_hotel
        context.selected_transport = selected_transport
        self.state_machine.transition(context, TravelState.USER_CONFIRMED)

        context = self.agent_team.approval.create(context)
        self.state_machine.transition(context, TravelState.APPROVAL_CREATED)
        self.session_store.save(context)
        return context

    def run_to_approval(
        self,
        request: TravelRequest,
        selected_hotel_id: Optional[str] = None,
        selected_transport_id: Optional[str] = None,
    ) -> TravelContext:
        context = self.plan(request)
        return self.confirm_and_create_approval(context, selected_hotel_id, selected_transport_id)

    def refresh_approval_status(self, context: TravelContext) -> TravelContext:
        if context.approval is None:
            raise ValueError("Approval must be created before status refresh.")

        context = self.agent_team.approval.refresh(context)
        approval = context.approval
        status = self._normalize_status(approval.status)

        if status in {"APPROVED", "PASS", "PASSED"}:
            if context.state == TravelState.APPROVAL_CREATED.value:
                self.state_machine.transition(context, TravelState.APPROVAL_APPROVED)
            else:
                context.append_event(f"Approval is approved while state is {context.state}.")
        elif status in {"REJECTED", "DENIED", "REFUSED"}:
            if context.state == TravelState.APPROVAL_CREATED.value:
                self.state_machine.transition(context, TravelState.APPROVAL_REJECTED)
            else:
                context.append_event(f"Approval is rejected while state is {context.state}.")
        else:
            context.append_event(f"Approval is still pending: {approval.status}.")

        self.session_store.save(context)
        return context

    def book_after_approval(self, context: TravelContext) -> TravelContext:
        self._require_permission(context, "book_order")
        if context.state != TravelState.APPROVAL_APPROVED.value:
            raise ValueError("Booking requires APPROVAL_APPROVED state.")
        if context.selected_hotel is None:
            raise ValueError("Selected hotel is required before booking.")
        if context.itinerary is None:
            raise ValueError("Itinerary is required before booking.")
        if context.approval is None:
            raise ValueError("Approval is required before booking.")

        context = self.create_transport_order_after_approval(context)
        if context.state != TravelState.APPROVAL_APPROVED.value:
            self.session_store.save(context)
            return context

        context = self.agent_team.hotel.lock_inventory(context)
        inventory_lock = context.inventory_lock
        if self._normalize_status(inventory_lock.status) not in {"LOCKED", "HELD"}:
            raise ValueError(f"Hotel inventory was not locked: {inventory_lock.status}")
        self.state_machine.transition(context, TravelState.INVENTORY_LOCKED)

        context = self.verify_price_before_order(context)
        if context.state != TravelState.INVENTORY_LOCKED.value:
            self.session_store.save(context)
            return context

        return self.create_order_after_lock(context)

    def verify_price_before_order(self, context: TravelContext) -> TravelContext:
        if context.state != TravelState.INVENTORY_LOCKED.value:
            raise ValueError("Price verification requires INVENTORY_LOCKED state.")
        if context.selected_hotel is None:
            raise ValueError("Selected hotel is required before price verification.")
        if context.itinerary is None:
            raise ValueError("Itinerary is required before price verification.")
        if context.policy_result is None:
            raise ValueError("Policy result is required before price verification.")

        context = self.agent_team.hotel.verify_price(context)
        price_check = context.price_check
        price_status = self._normalize_status(price_check.status)
        if price_status in {"SOLD_OUT", "UNAVAILABLE", "INVENTORY_EXPIRED", "NO_INVENTORY"}:
            self.state_machine.transition(context, TravelState.INVENTORY_EXPIRED)
            self.session_store.save(context)
            return context
        if self._price_requires_confirmation(price_check):
            self.state_machine.transition(context, TravelState.PRICE_CHANGED)
            self.session_store.save(context)
            return context

        self.session_store.save(context)
        return context

    def confirm_price_change(self, context: TravelContext, accept: bool) -> TravelContext:
        if context.state != TravelState.PRICE_CHANGED.value:
            raise ValueError("Price change confirmation requires PRICE_CHANGED state.")
        if context.price_check is None:
            raise ValueError("Price check result is required.")
        if not accept:
            if context.transport_order is not None and not self._compensation_done(context.transport_order_cancellation):
                transport_cancellation = self.agent_team.transport.cancel_order(context, "price_change_rejected")
                if transport_cancellation is not None:
                    context.append_event(
                        "Compensation completed: "
                        f"cancel_transport_order {transport_cancellation.target_id} -> {transport_cancellation.status}."
                    )
            if context.inventory_lock is not None and not self._compensation_done(context.inventory_release):
                release = self.agent_team.hotel.release_inventory(context, "price_change_rejected")
                if release is not None:
                    context.append_event(
                        f"Compensation completed: release_hotel_inventory {release.target_id} -> {release.status}."
                    )
            self.state_machine.transition(context, TravelState.USER_CANCELLED)
            self.session_store.save(context)
            return context

        if not context.price_check.policy_compliant:
            raise ValueError("Cannot accept a price change that violates policy.")
        if context.selected_hotel is not None and context.price_check.current_price is not None:
            context.selected_hotel = self._replace_hotel_price(context.selected_hotel, context.price_check.current_price)
            context.append_event(
                f"User accepted hotel price change: {context.price_check.original_price} -> {context.price_check.current_price}."
            )
        self.state_machine.transition(context, TravelState.INVENTORY_LOCKED)
        context = self.create_order_after_lock(context)
        self.session_store.save(context)
        return context

    def create_transport_order_after_approval(self, context: TravelContext) -> TravelContext:
        if context.state != TravelState.APPROVAL_APPROVED.value:
            raise ValueError("Transport booking requires APPROVAL_APPROVED state.")
        if context.approval is None:
            raise ValueError("Approval is required before transport booking.")
        if context.selected_transport is None:
            context.append_event("Transport booking skipped: no selected transport.")
            return context

        context = self.agent_team.transport.create_order(context)
        transport_order = context.transport_order
        if transport_order is None:
            return context
        transport_status = self._normalize_status(transport_order.status)
        if transport_status not in {"CREATED", "CONFIRMED", "SUCCESS", "PAID"}:
            self.state_machine.transition(context, TravelState.ORDER_FAILED)
        self.session_store.save(context)
        return context

    def create_order_after_lock(self, context: TravelContext) -> TravelContext:
        if context.state != TravelState.INVENTORY_LOCKED.value:
            raise ValueError("Order creation requires INVENTORY_LOCKED state.")
        if context.selected_hotel is None:
            raise ValueError("Selected hotel is required before order creation.")
        if context.itinerary is None:
            raise ValueError("Itinerary is required before order creation.")
        if context.approval is None:
            raise ValueError("Approval is required before order creation.")
        if context.inventory_lock is None:
            raise ValueError("Inventory lock is required before order creation.")

        context = self.agent_team.booking.create_hotel_order(context)
        order = context.order
        order_status = self._normalize_status(order.status)
        if order_status in {"CREATED", "CONFIRMED", "SUCCESS", "PAID"}:
            self.state_machine.transition(context, TravelState.ORDER_CREATED)
            self.state_machine.transition(context, TravelState.COMPLETED)
        else:
            self.state_machine.transition(context, TravelState.ORDER_FAILED)

        self.session_store.save(context)
        return context

    def refresh_order_status(self, context: TravelContext) -> TravelContext:
        if context.order is None:
            raise ValueError("Order must be created before status refresh.")
        if context.transport_order is not None:
            context = self.agent_team.transport.refresh_order(context)
            refreshed_transport = context.transport_order
            transport_status = self._normalize_status(refreshed_transport.status)
            if transport_status in {"CANCELLED", "CANCELED"}:
                self.state_machine.transition(context, TravelState.USER_CANCELLED)
                self.session_store.save(context)
                return context
            if transport_status in {"FAILED", "FAILURE"} and context.state != TravelState.ORDER_FAILED.value:
                self.state_machine.transition(context, TravelState.ORDER_FAILED)
                self.session_store.save(context)
                return context

        context = self.agent_team.booking.refresh_hotel_order(context)
        refreshed = context.order
        order_status = self._normalize_status(refreshed.status)
        if order_status in {"CANCELLED", "CANCELED"}:
            self.state_machine.transition(context, TravelState.USER_CANCELLED)
        elif order_status in {"FAILED", "FAILURE"} and context.state != TravelState.ORDER_FAILED.value:
            self.state_machine.transition(context, TravelState.ORDER_FAILED)
        else:
            context.append_event(f"Order status refreshed: {refreshed.status}.")
        self.session_store.save(context)
        return context

    def run_to_order(
        self,
        request: TravelRequest,
        selected_hotel_id: Optional[str] = None,
        selected_transport_id: Optional[str] = None,
    ) -> TravelContext:
        context = self.run_to_approval(request, selected_hotel_id, selected_transport_id)
        context = self.refresh_approval_status(context)
        if context.state == TravelState.APPROVAL_APPROVED.value:
            context = self.book_after_approval(context)
        return context

    def get_session(self, session_id: str) -> TravelContext:
        return self.session_store.get(session_id)

    def replan_after_exception(
        self,
        context: TravelContext,
        reason: str = "exception_replan",
        release_inventory: bool = True,
        cancel_order: bool = True,
        cancel_approval: bool = True,
    ) -> TravelContext:
        if context.state not in {
            TravelState.APPROVAL_CREATED.value,
            TravelState.APPROVAL_APPROVED.value,
            TravelState.APPROVAL_REJECTED.value,
            TravelState.PRICE_CHANGED.value,
            TravelState.INVENTORY_EXPIRED.value,
            TravelState.ORDER_FAILED.value,
        }:
            raise ValueError(f"Cannot replan from state: {context.state}")

        from_state = context.state
        compensation_payload: dict[str, object] = {}
        if (
            cancel_order
            and context.transport_order is not None
            and not self._compensation_done(context.transport_order_cancellation)
        ):
            transport_cancellation = self.agent_team.transport.cancel_order(context, reason)
            if transport_cancellation is not None:
                compensation_payload["transport_order_cancellation"] = asdict(transport_cancellation)
                context.append_event(
                    "Recovery compensation completed: "
                    f"cancel_transport_order {transport_cancellation.target_id} -> {transport_cancellation.status}."
                )

        if cancel_order and context.order is not None and not self._compensation_done(context.order_cancellation):
            cancellation = self.agent_team.booking.cancel_hotel_order(context, reason)
            if cancellation is not None:
                compensation_payload["order_cancellation"] = asdict(cancellation)
                context.append_event(
                    f"Recovery compensation completed: cancel_order {cancellation.target_id} -> {cancellation.status}."
                )

        if release_inventory and context.inventory_lock is not None and not self._compensation_done(context.inventory_release):
            release = self.agent_team.hotel.release_inventory(context, reason)
            if release is not None:
                compensation_payload["inventory_release"] = asdict(release)
                context.append_event(
                    f"Recovery compensation completed: release_hotel_inventory {release.target_id} -> {release.status}."
                )

        if cancel_approval and context.approval is not None and not self._compensation_done(context.approval_cancellation):
            approval_status = self._normalize_status(context.approval.status)
            if approval_status not in {"REJECTED", "DENIED", "REFUSED", "CANCELLED", "CANCELED"}:
                approval_cancellation = self.agent_team.approval.cancel(context, reason)
                if approval_cancellation is not None:
                    compensation_payload["approval_cancellation"] = asdict(approval_cancellation)
                    context.append_event(
                        "Recovery compensation completed: "
                        f"cancel_approval {approval_cancellation.target_id} -> {approval_cancellation.status}."
                    )

        context.workflow_generation += 1
        context.selected_hotel = None
        context.selected_transport = None
        context.approval = None
        context.price_check = None
        context.inventory_lock = None
        context.order = None
        context.transport_order = None
        context.approval_cancellation = None
        context.order_cancellation = None
        context.transport_order_cancellation = None
        context.inventory_release = None

        if context.policy_result is None or context.transport_policy_result is None:
            context = self.agent_team.policy.check(context)
        if context.itinerary is None:
            context = self.agent_team.itinerary.plan(context)

        max_price = self._effective_hotel_budget(context.request, context.policy_result.approved_budget)
        context = self.agent_team.hotel.search(context, max_price)
        context = self.agent_team.transport.search(context)
        self.state_machine.transition(context, TravelState.PLAN_GENERATED)
        context.recovery_records.append(
            RecoveryRecord(
                recovery_id="RCV-" + uuid4().hex[:10].upper(),
                action="replan",
                reason=reason,
                from_state=from_state,
                to_state=context.state,
                payload={
                    "workflow_generation": context.workflow_generation,
                    "compensations": compensation_payload,
                    "hotel_count": len(context.hotel_options),
                    "transport_count": len(context.transport_options),
                },
                created_at=datetime.now(timezone.utc).isoformat(),
            )
        )
        context.append_event(
            f"Recovery replan completed from {from_state}; generation {context.workflow_generation} is ready."
        )
        self.session_store.save(context)
        return context

    def reselect_hotel_and_create_approval(
        self,
        context: TravelContext,
        selected_hotel_id: Optional[str] = None,
        selected_transport_id: Optional[str] = None,
    ) -> TravelContext:
        if context.state != TravelState.PLAN_GENERATED.value:
            raise ValueError("Hotel reselection requires PLAN_GENERATED state.")
        return self.confirm_and_create_approval(context, selected_hotel_id, selected_transport_id)

    def replay_dead_letter_notification(self, context: TravelContext, event_type: str) -> TravelContext:
        self._require_permission(context, "replay_dead_letter")
        existing = self._find_notification(context, event_type, context.workflow_generation)
        if existing is None:
            raise ValueError(f"No notification found for event type: {event_type}")
        if existing.status != "DEAD_LETTER":
            raise ValueError(f"Notification {event_type} is not DEAD_LETTER: {existing.status}")

        reset = replace(existing, status="FAILED", retry_count=0, last_error=None)
        record = self._send_or_record_notification(
            context=context,
            event_type=event_type,
            title=existing.title,
            message=existing.message,
            channel=existing.channel,
            existing=reset,
        )
        self._upsert_notification(context, record)

        dedupe_key = self._notification_dedupe_key(context, event_type)
        if record.status in {"SENT", "DELIVERED", "DONE"} and dedupe_key not in context.notification_keys:
            context.notification_keys.append(dedupe_key)
        elif record.status not in {"SENT", "DELIVERED", "DONE"} and dedupe_key in context.notification_keys:
            context.notification_keys.remove(dedupe_key)

        context.append_event(f"Dead-letter replay {event_type} -> {record.status}.")
        self.session_store.save(context)
        return context

    def estimate_cancellation_refund(
        self,
        context: TravelContext,
        reason: str = "user_cancelled",
    ) -> TravelContext:
        self._require_permission(context, "cancel_trip")
        if context.order is None and context.transport_order is None:
            raise ValueError("Refund estimate requires at least one created order.")

        self.agent_team.transport.estimate_refund(context, reason)
        self.agent_team.booking.estimate_refund(context, reason)
        self.session_store.save(context)
        return context

    def change_trip(
        self,
        context: TravelContext,
        new_depart_at: str | None = None,
        new_check_in: date | None = None,
        new_check_out: date | None = None,
        reason: str = "user_change_requested",
    ) -> TravelContext:
        self._require_permission(context, "change_trip")
        if context.state not in {TravelState.ORDER_CREATED.value, TravelState.COMPLETED.value}:
            raise ValueError("Trip change requires ORDER_CREATED or COMPLETED state.")
        if new_depart_at is None and (new_check_in is None or new_check_out is None):
            raise ValueError("Trip change requires transport or hotel change details.")

        change_request = self._build_change_request(new_depart_at, new_check_in, new_check_out, reason)
        estimates: list[RefundEstimate] = []
        changes: list[ChangeRecord] = []

        if new_depart_at is not None:
            estimate = self.agent_team.transport.estimate_refund(context, reason)
            if estimate is not None:
                estimates.append(estimate)
        if new_check_in is not None or new_check_out is not None:
            if new_check_in is None or new_check_out is None:
                raise ValueError("Hotel change requires both new_check_in and new_check_out.")
            if new_check_out <= new_check_in:
                raise ValueError("new_check_out must be later than new_check_in.")
            estimate = self.agent_team.booking.estimate_refund(context, reason)
            if estimate is not None:
                estimates.append(estimate)

        change_approval = self.agent_team.approval.create_change_approval(context, estimates, change_request)
        if self._normalize_status(change_approval.status) not in {"APPROVED", "AUTO_APPROVED"}:
            context.append_event(f"Change approval pending or rejected: {change_approval.status}.")
            self.session_store.save(context)
            return context

        for estimate in estimates:
            confirmation = self.agent_team.approval.confirm_refund(context, estimate, reason)
            if not self._refund_confirmation_succeeded(confirmation.status):
                context.append_event(f"Refund confirmation blocked trip change: {confirmation.status}.")
                self.session_store.save(context)
                return context

        if new_depart_at is not None:
            changes.append(self.agent_team.transport.change_order(context, new_depart_at, reason))
            self._compensate_if_change_failed(context, changes[-1], changes[:-1], reason)
        if new_check_in is not None and new_check_out is not None:
            changes.append(self.agent_team.booking.change_hotel_order(context, new_check_in, new_check_out, reason))
            self._compensate_if_change_failed(context, changes[-1], changes[:-1], reason)

        if changes and all(self._change_succeeded(change) for change in changes):
            self.sync_calendar(context, event_type="TRIP_CHANGED")
        else:
            self.session_store.save(context)

        return context

    def sync_calendar(
        self,
        context: TravelContext,
        event_type: str | None = None,
        attendees: list[str] | None = None,
        existing: CalendarSyncRecord | None = None,
    ) -> TravelContext:
        self._require_permission(context, "sync_calendar")
        resolved_event_type = event_type or self._calendar_event_type(context)
        if resolved_event_type is None:
            raise ValueError(f"Calendar sync is not supported for state: {context.state}")

        title, start_at, end_at, payload = self._calendar_payload(context, resolved_event_type)
        record = self._sync_or_record_calendar(
            context=context,
            event_type=resolved_event_type,
            title=title,
            start_at=start_at,
            end_at=end_at,
            payload=payload,
            attendees=attendees,
            existing=existing,
        )
        self._upsert_calendar_sync(context, record)
        context.append_event(f"Calendar sync {resolved_event_type} -> {record.status}.")
        self.session_store.save(context)
        return context

    def replay_dead_letter_calendar_sync(self, context: TravelContext, event_type: str) -> TravelContext:
        self._require_permission(context, "replay_dead_letter")
        existing = self._find_calendar_sync(context, event_type, context.workflow_generation)
        if existing is None:
            raise ValueError(f"No calendar sync found for event type: {event_type}")
        if existing.status != "DEAD_LETTER":
            raise ValueError(f"Calendar sync {event_type} is not DEAD_LETTER: {existing.status}")

        reset = replace(existing, status="FAILED", retry_count=0, last_error=None)
        context = self.sync_calendar(
            context,
            event_type=event_type,
            attendees=reset.attendees,
            existing=reset,
        )
        context.append_event(f"Calendar dead-letter replay requested for {event_type}.")
        self.session_store.save(context)
        return context

    def cancel_trip(self, context: TravelContext, reason: str = "user_cancelled") -> TravelContext:
        self._require_permission(context, "cancel_trip")
        if context.transport_order is not None and not self._compensation_done(context.transport_order_cancellation):
            transport_cancellation = self.agent_team.transport.cancel_order(context, reason)
            if transport_cancellation is not None:
                context.append_event(
                    "Compensation completed: "
                    f"cancel_transport_order {transport_cancellation.target_id} -> {transport_cancellation.status}."
                )

        if context.order is not None and not self._compensation_done(context.order_cancellation):
            cancellation = self.agent_team.booking.cancel_hotel_order(context, reason)
            if cancellation is not None:
                context.append_event(
                    f"Compensation completed: cancel_order {cancellation.target_id} -> {cancellation.status}."
                )

        if context.inventory_lock is not None and not self._compensation_done(context.inventory_release):
            release = self.agent_team.hotel.release_inventory(context, reason)
            if release is not None:
                context.append_event(
                    f"Compensation completed: release_hotel_inventory {release.target_id} -> {release.status}."
                )

        if context.state != TravelState.USER_CANCELLED.value:
            self.state_machine.transition(context, TravelState.USER_CANCELLED)
        self.session_store.save(context)
        return context

    def _attach_planning_knowledge(self, context: TravelContext) -> None:
        try:
            report = self._search_planning_knowledge(context.request)
        except Exception as exc:
            context.append_event(f"Operations knowledge planning search skipped: {exc}")
            return
        if report is None or not report.hits:
            return

        knowledge_refs = [hit.entry.entry_id for hit in report.hits]
        guidance = report.suggested_actions
        context.task_plan = self.planner.build_plan(
            context.request,
            knowledge_refs=knowledge_refs,
            guidance=guidance,
        )
        context.append_event(
            f"Operations knowledge applied to planning: {len(knowledge_refs)} hits, {len(guidance)} suggested actions."
        )
        context.agent_executions.append(
            AgentExecutionRecord(
                agent_name="PlanningKnowledgeAgent",
                action="search_operations_knowledge",
                status="SUCCESS",
                input_refs={
                    "session_id": context.session_id,
                    "workflow_generation": context.workflow_generation,
                    "query": report.query,
                },
                output_refs={
                    "knowledge_refs": knowledge_refs,
                    "suggested_actions": guidance,
                },
                message="Historical operations knowledge attached to task plan.",
                created_at=datetime.now(timezone.utc).isoformat(),
            )
        )

    def _search_planning_knowledge(self, request: TravelRequest) -> OperationsKnowledgeSearchReport | None:
        from .operations import operations_knowledge_entry_from_dict, search_operations_knowledge

        entries = [
            operations_knowledge_entry_from_dict(item)
            for item in self.session_store.list_operations_knowledge_entries(limit=20)
        ]
        if not entries:
            return None
        return search_operations_knowledge(entries, self._planning_knowledge_query(request), limit=5)

    @staticmethod
    def _planning_knowledge_query(request: TravelRequest) -> str:
        tokens = [
            request.origin_city,
            request.destination_city,
            request.purpose,
            request.venue,
            request.department or "",
            *request.preferences,
            "policy",
            "hotel",
            "transport",
            "approval",
            "inventory",
            "order",
            "notification",
            "calendar",
        ]
        return " ".join(token for token in tokens if token)

    @staticmethod
    def _effective_hotel_budget(request: TravelRequest, approved_budget: int) -> int:
        if request.budget_per_night is None:
            return approved_budget
        return min(request.budget_per_night, approved_budget)

    def _require_permission(self, context: TravelContext, action: str) -> None:
        self._require_permission_for_request(context.request, action)

    def _require_permission_for_request(self, request: TravelRequest, action: str) -> None:
        decision = evaluate_permission(
            self.permission_policy,
            user_id=request.user_id,
            action=action,
            department=request.department,
            roles=request.roles,
            http_client=self.permission_http_client,
        )
        ensure_permission(decision)

    @staticmethod
    def _select_hotel(
        hotel_options: list[HotelOption],
        selected_hotel_id: Optional[str],
    ) -> HotelOption:
        if not hotel_options:
            raise ValueError("No hotel options are available for confirmation.")

        if selected_hotel_id is None:
            return hotel_options[0]

        for hotel in hotel_options:
            if hotel.hotel_id == selected_hotel_id:
                return hotel
        raise ValueError(f"Unknown hotel id: {selected_hotel_id}")

    @staticmethod
    def _select_transport(
        transport_options: list[TransportOption],
        selected_transport_id: Optional[str],
    ) -> TransportOption:
        if not transport_options:
            raise ValueError("No transport options are available for confirmation.")

        if selected_transport_id is None:
            return transport_options[0]

        for option in transport_options:
            if option.transport_id == selected_transport_id:
                return option
        raise ValueError(f"Unknown transport id: {selected_transport_id}")

    @staticmethod
    def _normalize_status(status: str) -> str:
        return status.strip().upper()

    @staticmethod
    def _price_requires_confirmation(price_check: object) -> bool:
        status = str(getattr(price_check, "status", "")).strip().upper()
        return bool(getattr(price_check, "requires_confirmation", False)) or status == "PRICE_CHANGED" or not bool(
            getattr(price_check, "policy_compliant", True)
        )

    @staticmethod
    def _replace_hotel_price(hotel: HotelOption, nightly_price: int) -> HotelOption:
        return HotelOption(
            hotel_id=hotel.hotel_id,
            name=hotel.name,
            city=hotel.city,
            address=hotel.address,
            nightly_price=nightly_price,
            distance_km=hotel.distance_km,
            rating=hotel.rating,
            refundable=hotel.refundable,
            policy_compliant=hotel.policy_compliant,
            source=hotel.source,
        )

    @staticmethod
    def _merge_order_status(original: object, refreshed: object) -> object:
        from .models import TravelOrder

        return TravelOrder(
            order_id=getattr(refreshed, "order_id"),
            status=getattr(refreshed, "status"),
            total_amount=getattr(original, "total_amount"),
            currency=getattr(original, "currency"),
            payload=getattr(refreshed, "payload"),
            source=getattr(refreshed, "source"),
        )

    @staticmethod
    def _merge_transport_order_status(original: object, refreshed: object) -> object:
        from .models import TransportOrder

        return TransportOrder(
            order_id=getattr(refreshed, "order_id"),
            status=getattr(refreshed, "status"),
            total_amount=getattr(original, "total_amount"),
            currency=getattr(original, "currency"),
            payload=getattr(refreshed, "payload"),
            source=getattr(refreshed, "source"),
        )

    @classmethod
    def _compensation_done(cls, result: object | None) -> bool:
        if result is None:
            return False
        status = getattr(result, "status", "")
        return cls._normalize_status(status) in {"DONE", "CANCELLED", "RELEASED", "SUCCESS", "SUCCEEDED"}

    @staticmethod
    def _build_change_request(
        new_depart_at: str | None,
        new_check_in: date | None,
        new_check_out: date | None,
        reason: str,
    ) -> dict[str, object]:
        return {
            "new_depart_at": new_depart_at,
            "new_check_in": new_check_in.isoformat() if new_check_in else None,
            "new_check_out": new_check_out.isoformat() if new_check_out else None,
            "reason": reason,
        }

    @classmethod
    def _change_succeeded(cls, change: ChangeRecord) -> bool:
        return cls._normalize_status(change.status) in {"CHANGED", "SUCCESS", "SUCCEEDED", "DONE", "CONFIRMED"}

    @classmethod
    def _refund_confirmation_succeeded(cls, status: str) -> bool:
        return cls._normalize_status(status) in {"CONFIRMED", "SUCCESS", "SUCCEEDED", "DONE", "APPROVED"}

    def _compensate_if_change_failed(
        self,
        context: TravelContext,
        change: ChangeRecord,
        completed_changes: list[ChangeRecord],
        reason: str,
    ) -> None:
        if self._change_succeeded(change):
            return
        self.agent_team.approval.compensate_change_failure(
            context,
            failed_change=change,
            reason=reason,
            completed_changes=completed_changes,
        )

    @staticmethod
    def _build_notification_payload(context: TravelContext) -> tuple[str, str, str] | None:
        if context.state == TravelState.PRICE_CHANGED.value and context.price_check is not None:
            return (
                "PRICE_CHANGE_CONFIRMATION_REQUIRED",
                "差旅酒店价格变化待确认",
                f"酒店 {context.price_check.hotel_id} 价格从 {context.price_check.original_price} 变为 {context.price_check.current_price}，请确认是否继续。",
            )
        if context.state == TravelState.APPROVAL_REJECTED.value:
            return (
                "APPROVAL_REJECTED",
                "差旅审批已驳回",
                f"{context.request.destination_city} 差旅审批被驳回，请调整方案后重新提交。",
            )
        if context.state == TravelState.INVENTORY_EXPIRED.value:
            return (
                "INVENTORY_EXPIRED",
                "酒店库存已失效",
                f"{context.request.destination_city} 酒店库存或价格已失效，需要重新查询。",
            )
        if context.state == TravelState.ORDER_FAILED.value:
            return (
                "ORDER_FAILED",
                "差旅订单创建失败",
                "订单创建失败，需要重新查询或人工处理。",
            )
        if context.state == TravelState.USER_CANCELLED.value:
            return (
                "TRIP_CANCELLED",
                "差旅流程已取消",
                "差旅流程已取消，相关订单和库存补偿已尽量执行。",
            )
        if context.state == TravelState.COMPLETED.value and context.order is not None:
            transport_text = (
                f"，交通订单 {context.transport_order.order_id}"
                if context.transport_order is not None
                else ""
            )
            return (
                "ORDER_COMPLETED",
                "差旅订单已创建",
                f"酒店订单 {context.order.order_id}{transport_text} 已创建，金额 {context.order.total_amount} {context.order.currency}。",
            )
        return None

    @staticmethod
    def _notification_context_payload(context: TravelContext) -> dict[str, object]:
        return {
            "session_id": context.session_id,
            "workflow_generation": context.workflow_generation,
            "state": context.state,
            "destination_city": context.request.destination_city,
            "start_date": context.request.start_date.isoformat(),
            "end_date": context.request.end_date.isoformat(),
            "approval_id": context.approval.approval_id if context.approval else None,
            "order_id": context.order.order_id if context.order else None,
            "transport_order_id": context.transport_order.order_id if context.transport_order else None,
            "hotel_id": context.selected_hotel.hotel_id if context.selected_hotel else None,
            "transport_id": context.selected_transport.transport_id if context.selected_transport else None,
        }

    @staticmethod
    def _calendar_event_type(context: TravelContext) -> str | None:
        if context.state == TravelState.USER_CANCELLED.value:
            return "TRIP_CANCELLED"
        if context.change_records:
            return "TRIP_CHANGED"
        if context.state == TravelState.COMPLETED.value:
            return "TRIP_BOOKED"
        return None

    @staticmethod
    def _calendar_payload(context: TravelContext, event_type: str) -> tuple[str, str, str, dict[str, object]]:
        start_at = context.request.start_date.isoformat()
        end_at = context.request.end_date.isoformat()
        if context.itinerary is not None:
            start_at = context.itinerary.check_in.isoformat()
            end_at = context.itinerary.check_out.isoformat()
        if context.change_records:
            latest_hotel_change = next(
                (record for record in reversed(context.change_records) if record.target_type == "hotel"),
                None,
            )
            if latest_hotel_change is not None:
                start_at = str(latest_hotel_change.payload.get("new_check_in") or start_at)
                end_at = str(latest_hotel_change.payload.get("new_check_out") or end_at)

        title = f"{context.request.destination_city}差旅"
        if event_type == "TRIP_CHANGED":
            title = f"{title}已改签"
        elif event_type == "TRIP_CANCELLED":
            title = f"{title}已取消"
        else:
            title = f"{title}已预订"

        payload = {
            **TravelAgent._notification_context_payload(context),
            "event_type": event_type,
            "change_ids": [record.change_id for record in context.change_records],
            "calendar_source_state": context.state,
        }
        return title, start_at, end_at, payload

    def _sync_or_record_calendar(
        self,
        context: TravelContext,
        event_type: str,
        title: str,
        start_at: str,
        end_at: str,
        payload: dict[str, object],
        attendees: list[str] | None,
        existing: CalendarSyncRecord | None,
    ) -> CalendarSyncRecord:
        retry_count = existing.retry_count if existing else 0
        max_retries = existing.max_retries if existing else 3
        if retry_count >= max_retries:
            return replace(existing, status="DEAD_LETTER") if existing else self._failed_calendar_sync_record(
                context,
                event_type,
                title,
                start_at,
                end_at,
                payload,
                attendees,
                retry_count=max_retries,
                max_retries=max_retries,
                error="Calendar max retries reached before sync.",
                status="DEAD_LETTER",
            )

        try:
            return self.gateway.call(
                "sync_calendar_event",
                session_id=context.session_id,
                user_id=context.request.user_id,
                event_type=event_type,
                title=title,
                start_at=start_at,
                end_at=end_at,
                payload=payload,
                attendees=attendees or [context.request.user_id],
                workflow_generation=context.workflow_generation,
            )
        except Exception as exc:
            retry_count += 1
            status = "DEAD_LETTER" if retry_count >= max_retries else "FAILED"
            return self._failed_calendar_sync_record(
                context,
                event_type,
                title,
                start_at,
                end_at,
                payload,
                attendees,
                retry_count=retry_count,
                max_retries=max_retries,
                error=str(exc),
                status=status,
            )

    @staticmethod
    def _failed_calendar_sync_record(
        context: TravelContext,
        event_type: str,
        title: str,
        start_at: str,
        end_at: str,
        payload: dict[str, object],
        attendees: list[str] | None,
        retry_count: int,
        max_retries: int,
        error: str,
        status: str = "FAILED",
    ) -> CalendarSyncRecord:
        calendar_event_id = "CAL-" + uuid5(
            NAMESPACE_URL,
            f"{context.session_id}:{context.workflow_generation}:{event_type}",
        ).hex[:10].upper()
        return CalendarSyncRecord(
            calendar_event_id=calendar_event_id,
            event_type=event_type,
            status=status,
            user_id=context.request.user_id,
            title=title,
            start_at=start_at,
            end_at=end_at,
            payload=payload,
            source="local",
            attendees=attendees or [context.request.user_id],
            retry_count=retry_count,
            max_retries=max_retries,
            last_error=error,
        )

    @staticmethod
    def _find_calendar_sync(
        context: TravelContext,
        event_type: str,
        workflow_generation: int | None = None,
    ) -> CalendarSyncRecord | None:
        for record in reversed(context.calendar_syncs):
            if record.event_type != event_type:
                continue
            if workflow_generation is not None and TravelAgent._calendar_generation(record) != workflow_generation:
                continue
            return record
        return None

    @staticmethod
    def _upsert_calendar_sync(context: TravelContext, record: CalendarSyncRecord) -> None:
        for index, existing in enumerate(context.calendar_syncs):
            if existing.event_type == record.event_type and TravelAgent._calendar_generation(
                existing
            ) == TravelAgent._calendar_generation(record):
                context.calendar_syncs[index] = record
                return
        context.calendar_syncs.append(record)

    @staticmethod
    def _calendar_generation(record: CalendarSyncRecord) -> int:
        payload = record.payload
        generation = payload.get("workflow_generation")
        if generation is None and isinstance(payload.get("payload"), dict):
            generation = payload["payload"].get("workflow_generation")
        try:
            return int(generation)
        except (TypeError, ValueError):
            return 1

    def _send_or_record_notification(
        self,
        context: TravelContext,
        event_type: str,
        title: str,
        message: str,
        channel: str,
        existing: NotificationRecord | None,
    ) -> NotificationRecord:
        retry_count = existing.retry_count if existing else 0
        max_retries = existing.max_retries if existing else 3
        if retry_count >= max_retries:
            return replace(existing, status="DEAD_LETTER") if existing else self._failed_notification_record(
                context,
                event_type,
                title,
                message,
                channel,
                retry_count=max_retries,
                max_retries=max_retries,
                error="Notification max retries reached before send.",
            )

        try:
            return self.gateway.call(
                "send_notification",
                session_id=context.session_id,
                user_id=context.request.user_id,
                event_type=event_type,
                title=title,
                message=message,
                channel=channel,
                workflow_generation=context.workflow_generation,
                payload=self._notification_context_payload(context),
            )
        except Exception as exc:
            retry_count += 1
            status = "DEAD_LETTER" if retry_count >= max_retries else "FAILED"
            return self._failed_notification_record(
                context,
                event_type,
                title,
                message,
                channel,
                retry_count=retry_count,
                max_retries=max_retries,
                error=str(exc),
                status=status,
            )

    @staticmethod
    def _failed_notification_record(
        context: TravelContext,
        event_type: str,
        title: str,
        message: str,
        channel: str,
        retry_count: int,
        max_retries: int,
        error: str,
        status: str = "FAILED",
    ) -> NotificationRecord:
        notification_id = "NTF-" + uuid5(
            NAMESPACE_URL,
            f"{context.session_id}:{context.workflow_generation}:{event_type}",
        ).hex[:10].upper()
        return NotificationRecord(
            notification_id=notification_id,
            event_type=event_type,
            channel=channel,
            recipient_id=context.request.user_id,
            title=title,
            message=message,
            status=status,
            payload=TravelAgent._notification_context_payload(context),
            source="local",
            retry_count=retry_count,
            max_retries=max_retries,
            last_error=error,
        )

    @staticmethod
    def _find_notification(
        context: TravelContext,
        event_type: str,
        workflow_generation: int | None = None,
    ) -> NotificationRecord | None:
        for notification in reversed(context.notifications):
            if notification.event_type != event_type:
                continue
            if workflow_generation is not None and TravelAgent._notification_generation(notification) != workflow_generation:
                continue
            return notification
        return None

    @staticmethod
    def _upsert_notification(context: TravelContext, record: NotificationRecord) -> None:
        for index, notification in enumerate(context.notifications):
            if notification.event_type == record.event_type and TravelAgent._notification_generation(
                notification
            ) == TravelAgent._notification_generation(record):
                context.notifications[index] = record
                return
        context.notifications.append(record)

    @staticmethod
    def _notification_terminal(notification: NotificationRecord) -> bool:
        return notification.status in {"SENT", "DELIVERED", "DONE", "DEAD_LETTER"}

    @staticmethod
    def _notification_dedupe_key(context: TravelContext, event_type: str) -> str:
        return f"{context.session_id}:{context.workflow_generation}:{event_type}"

    @staticmethod
    def _notification_generation(notification: NotificationRecord) -> int:
        payload = notification.payload
        generation = payload.get("workflow_generation")
        if generation is None and isinstance(payload.get("payload"), dict):
            generation = payload["payload"].get("workflow_generation")
        try:
            return int(generation)
        except (TypeError, ValueError):
            return 1


def build_default_agent(
    settings: IntegrationSettings | None = None,
    http_client: HttpJsonClient | None = None,
    store_http_client: StoreHttpClient | None = None,
    session_store: SessionStore | None = None,
    permission_policy: PermissionPolicy | None = None,
    permission_http_client: Any | None = None,
    audit_sink: AuditSink | None = None,
) -> TravelAgent:
    gateway = ToolGateway()
    resolved_settings = settings or IntegrationSettings.from_env()
    if audit_sink is None:
        audit_sink = build_audit_sink(resolved_settings, http_client=http_client)
    gateway.audit_sink = audit_sink
    integrations = TravelSystemIntegrations(settings=resolved_settings, http_client=http_client)
    gateway.register(
        name="check_policy",
        description="Check travel policy and hotel budget cap.",
        required=("user_id", "destination_city"),
        handler=integrations.check_policy,
    )
    gateway.register(
        name="check_transport_policy",
        description="Check travel transport policy and fare cap.",
        required=("user_id", "origin_city", "destination_city", "travel_date"),
        handler=integrations.check_transport_policy,
    )
    gateway.register(
        name="plan_itinerary",
        description="Create a basic itinerary draft.",
        required=("origin_city", "destination_city", "start_date", "end_date", "purpose", "venue"),
        handler=plan_itinerary,
    )
    gateway.register(
        name="search_hotels",
        description="Search hotels by city, date, venue, and budget.",
        required=("city", "check_in", "check_out", "venue", "max_price"),
        handler=integrations.search_hotels,
    )
    gateway.register(
        name="search_transport",
        description="Search flight or train inventory by route, date, and budget.",
        required=("origin_city", "destination_city", "travel_date", "max_price"),
        handler=integrations.search_transport,
    )
    gateway.register(
        name="create_approval",
        description="Create a travel approval record in OA.",
        required=("session_id", "user_id", "request", "policy", "itinerary", "selected_hotel", "selected_transport"),
        handler=integrations.create_approval,
    )
    gateway.register(
        name="create_approval_draft",
        description="Backward-compatible alias for create_approval.",
        required=("session_id", "user_id", "request", "policy", "itinerary", "selected_hotel", "selected_transport"),
        handler=integrations.create_approval,
    )
    gateway.register(
        name="get_approval_status",
        description="Fetch OA approval status.",
        required=("approval_id", "user_id"),
        handler=integrations.get_approval_status,
    )
    gateway.register(
        name="cancel_approval",
        description="Cancel or withdraw an OA approval record as recovery compensation.",
        required=("approval_id", "user_id", "reason"),
        handler=integrations.cancel_approval,
    )
    gateway.register(
        name="create_change_approval",
        description="Create an OA approval record for a post-booking trip change.",
        required=("session_id", "user_id", "request", "current_approval", "refund_estimates", "change_request"),
        handler=integrations.create_change_approval,
    )
    gateway.register(
        name="lock_hotel_inventory",
        description="Lock selected hotel inventory before order creation.",
        required=("session_id", "user_id", "selected_hotel", "check_in", "check_out"),
        handler=integrations.lock_hotel_inventory,
    )
    gateway.register(
        name="create_order",
        description="Create a hotel order after approval and inventory lock.",
        required=("session_id", "user_id", "request", "itinerary", "selected_hotel", "approval", "inventory_lock"),
        handler=integrations.create_order,
    )
    gateway.register(
        name="verify_hotel_price",
        description="Verify selected hotel price before order creation.",
        required=("selected_hotel", "max_price", "check_in", "check_out"),
        handler=integrations.verify_hotel_price,
    )
    gateway.register(
        name="get_order_status",
        description="Fetch order status after creation.",
        required=("order_id", "user_id"),
        handler=integrations.get_order_status,
    )
    gateway.register(
        name="create_transport_order",
        description="Create a flight or train order after approval.",
        required=("session_id", "user_id", "request", "selected_transport", "approval"),
        handler=integrations.create_transport_order,
    )
    gateway.register(
        name="get_transport_order_status",
        description="Fetch transport order status after creation.",
        required=("order_id", "user_id"),
        handler=integrations.get_transport_order_status,
    )
    gateway.register(
        name="cancel_transport_order",
        description="Cancel a created transport order as compensation.",
        required=("order_id", "user_id", "reason"),
        handler=integrations.cancel_transport_order,
    )
    gateway.register(
        name="cancel_order",
        description="Cancel a created hotel order as compensation.",
        required=("order_id", "user_id", "reason"),
        handler=integrations.cancel_order,
    )
    gateway.register(
        name="release_hotel_inventory",
        description="Release a hotel inventory lock as compensation.",
        required=("lock_id", "user_id", "reason"),
        handler=integrations.release_hotel_inventory,
    )
    gateway.register(
        name="estimate_refund",
        description="Estimate refund and penalty before cancellation or change.",
        required=("target_type", "target_id", "user_id", "total_amount", "reason"),
        handler=integrations.estimate_refund,
    )
    gateway.register(
        name="confirm_refund",
        description="Confirm refund amount before executing a cancellation or change.",
        required=(
            "estimate_id",
            "target_type",
            "target_id",
            "user_id",
            "refundable_amount",
            "penalty_amount",
            "currency",
            "reason",
        ),
        handler=integrations.confirm_refund,
    )
    gateway.register(
        name="change_transport_order",
        description="Change a created flight or train order.",
        required=("order_id", "user_id", "new_depart_at", "reason"),
        handler=integrations.change_transport_order,
    )
    gateway.register(
        name="change_hotel_order",
        description="Change a created hotel order date range.",
        required=("order_id", "user_id", "new_check_in", "new_check_out", "reason"),
        handler=integrations.change_hotel_order,
    )
    gateway.register(
        name="compensate_change_failure",
        description="Compensate or escalate when one supplier change fails after another succeeded.",
        required=("session_id", "user_id", "failed_target_type", "failed_target_id", "reason"),
        handler=integrations.compensate_change_failure,
    )
    gateway.register(
        name="send_notification",
        description="Send IM or task notification for workflow events.",
        required=("session_id", "user_id", "event_type", "title", "message", "channel", "payload"),
        handler=integrations.send_notification,
    )
    gateway.register(
        name="sync_calendar_event",
        description="Create or update a calendar event for booked, changed, or cancelled travel.",
        required=("session_id", "user_id", "event_type", "title", "start_at", "end_at", "payload"),
        handler=integrations.sync_calendar_event,
    )
    if session_store is None:
        session_store = build_session_store(resolved_settings, store_http_client=store_http_client)
    return TravelAgent(
        gateway=gateway,
        session_store=session_store,
        permission_policy=permission_policy,
        permission_http_client=permission_http_client or http_client,
        audit_sink=audit_sink,
    )


def build_session_store(
    settings: IntegrationSettings,
    store_http_client: StoreHttpClient | None = None,
) -> SessionStore | None:
    backend = settings.session_store_backend.strip().lower()
    if backend == "http":
        if not settings.session_store_api_url:
            raise ValueError("TRAVEL_SESSION_STORE_API_URL is required when session store backend is http.")
        return HttpSessionStore(
            base_url=settings.session_store_api_url,
            token=settings.session_store_api_token,
            http_client=store_http_client,
            timeout_seconds=settings.timeout_seconds,
        )
    if backend == "sqlite":
        if not settings.session_db_path:
            raise ValueError("TRAVEL_SESSION_DB_PATH is required when session store backend is sqlite.")
        return SQLiteSessionStore(settings.session_db_path)
    if backend == "memory":
        return InMemorySessionStore()
    if backend != "auto":
        raise ValueError(f"Unsupported session store backend: {settings.session_store_backend}")
    if settings.session_store_api_url:
        return HttpSessionStore(
            base_url=settings.session_store_api_url,
            token=settings.session_store_api_token,
            http_client=store_http_client,
            timeout_seconds=settings.timeout_seconds,
        )
    if settings.session_db_path:
        return SQLiteSessionStore(settings.session_db_path)
    return None
