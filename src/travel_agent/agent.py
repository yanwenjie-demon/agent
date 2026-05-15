from __future__ import annotations

from dataclasses import asdict, replace
from datetime import datetime, timezone
from typing import Optional
from uuid import NAMESPACE_URL, uuid4, uuid5

from .config import IntegrationSettings
from .integrations import HttpJsonClient, TravelSystemIntegrations
from .mock_tools import plan_itinerary
from .models import HotelOption, NotificationRecord, RecoveryRecord, Task, TaskPlan, TravelContext, TravelRequest, TransportOption
from .state import TravelState, WorkflowStateMachine
from .storage import InMemorySessionStore, SQLiteSessionStore, SessionStore
from .tools import ToolGateway


class SimpleTaskPlanner:
    """Deterministic planner for the policy, hotel, and OA approval workflow."""

    def build_plan(self, request: TravelRequest) -> TaskPlan:
        tasks = [
            Task(
                task_id="check_policy",
                task_type="tool",
                description=f"Check enterprise travel policy for {request.destination_city}.",
            ),
            Task(
                task_id="plan_itinerary",
                task_type="tool",
                description="Create a basic business trip itinerary.",
                depends_on=["check_policy"],
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
        return TaskPlan(goal="Create a compliant travel plan, OA approval, transport order, and hotel order.", tasks=tasks)


class TravelAgent:
    def __init__(
        self,
        gateway: ToolGateway,
        planner: Optional[SimpleTaskPlanner] = None,
        state_machine: Optional[WorkflowStateMachine] = None,
        session_store: Optional[SessionStore] = None,
    ) -> None:
        self.gateway = gateway
        self.planner = planner or SimpleTaskPlanner()
        self.state_machine = state_machine or WorkflowStateMachine()
        self.session_store = session_store or InMemorySessionStore()

    def plan(self, request: TravelRequest) -> TravelContext:
        context = TravelContext(
            session_id=str(uuid4()),
            request=request,
            state=TravelState.DRAFT.value,
            task_plan=self.planner.build_plan(request),
        )
        context.append_event("Created travel planning session.")

        policy = self.gateway.call(
            "check_policy",
            user_id=request.user_id,
            destination_city=request.destination_city,
            budget_per_night=request.budget_per_night,
        )
        context.policy_result = policy
        self.state_machine.transition(context, TravelState.POLICY_CHECKED)

        transport_policy = self.gateway.call(
            "check_transport_policy",
            user_id=request.user_id,
            origin_city=request.origin_city,
            destination_city=request.destination_city,
            travel_date=request.start_date,
        )
        context.transport_policy_result = transport_policy

        itinerary = self.gateway.call(
            "plan_itinerary",
            origin_city=request.origin_city,
            destination_city=request.destination_city,
            start_date=request.start_date,
            end_date=request.end_date,
            purpose=request.purpose,
            venue=request.venue,
        )
        context.itinerary = itinerary

        max_price = self._effective_hotel_budget(request, policy.approved_budget)
        hotels = self.gateway.call(
            "search_hotels",
            city=request.destination_city,
            check_in=itinerary.check_in,
            check_out=itinerary.check_out,
            venue=request.venue,
            max_price=max_price,
            preferences=request.preferences,
        )
        context.hotel_options = hotels
        transport_options = self.gateway.call(
            "search_transport",
            origin_city=request.origin_city,
            destination_city=request.destination_city,
            travel_date=request.start_date,
            max_price=transport_policy.max_transport_price,
            preferences=request.preferences,
        )
        context.transport_options = transport_options
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

    def confirm_and_create_approval(
        self,
        context: TravelContext,
        selected_hotel_id: Optional[str] = None,
        selected_transport_id: Optional[str] = None,
    ) -> TravelContext:
        selected_hotel = self._select_hotel(context.hotel_options, selected_hotel_id)
        selected_transport = self._select_transport(context.transport_options, selected_transport_id)
        context.selected_hotel = selected_hotel
        context.selected_transport = selected_transport
        self.state_machine.transition(context, TravelState.USER_CONFIRMED)

        approval = self.gateway.call(
            "create_approval",
            session_id=context.session_id,
            user_id=context.request.user_id,
            request=asdict(context.request),
            policy=asdict(context.policy_result) if context.policy_result else {},
            transport_policy=asdict(context.transport_policy_result) if context.transport_policy_result else {},
            itinerary=asdict(context.itinerary) if context.itinerary else {},
            selected_hotel=asdict(selected_hotel),
            selected_transport=asdict(selected_transport),
            workflow_generation=context.workflow_generation,
        )
        context.approval = approval
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

        approval = self.gateway.call(
            "get_approval_status",
            approval_id=context.approval.approval_id,
            user_id=context.request.user_id,
        )
        context.approval = approval
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

        inventory_lock = self.gateway.call(
            "lock_hotel_inventory",
            session_id=context.session_id,
            user_id=context.request.user_id,
            selected_hotel=asdict(context.selected_hotel),
            check_in=context.itinerary.check_in,
            check_out=context.itinerary.check_out,
            workflow_generation=context.workflow_generation,
        )
        context.inventory_lock = inventory_lock
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

        price_check = self.gateway.call(
            "verify_hotel_price",
            selected_hotel=asdict(context.selected_hotel),
            max_price=context.policy_result.approved_budget,
            check_in=context.itinerary.check_in,
            check_out=context.itinerary.check_out,
        )
        context.price_check = price_check
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
                transport_cancellation = self.gateway.call(
                    "cancel_transport_order",
                    order_id=context.transport_order.order_id,
                    user_id=context.request.user_id,
                    reason="price_change_rejected",
                )
                context.transport_order_cancellation = transport_cancellation
                context.append_event(
                    "Compensation completed: "
                    f"cancel_transport_order {transport_cancellation.target_id} -> {transport_cancellation.status}."
                )
            if context.inventory_lock is not None and not self._compensation_done(context.inventory_release):
                release = self.gateway.call(
                    "release_hotel_inventory",
                    lock_id=context.inventory_lock.lock_id,
                    user_id=context.request.user_id,
                    reason="price_change_rejected",
                )
                context.inventory_release = release
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

        transport_order = self.gateway.call(
            "create_transport_order",
            session_id=context.session_id,
            user_id=context.request.user_id,
            request=asdict(context.request),
            selected_transport=asdict(context.selected_transport),
            approval=asdict(context.approval),
            workflow_generation=context.workflow_generation,
        )
        context.transport_order = transport_order
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

        order = self.gateway.call(
            "create_order",
            session_id=context.session_id,
            user_id=context.request.user_id,
            request=asdict(context.request),
            itinerary=asdict(context.itinerary),
            selected_hotel=asdict(context.selected_hotel),
            approval=asdict(context.approval),
            inventory_lock=asdict(context.inventory_lock),
            workflow_generation=context.workflow_generation,
        )
        context.order = order
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
            refreshed_transport = self.gateway.call(
                "get_transport_order_status",
                order_id=context.transport_order.order_id,
                user_id=context.request.user_id,
            )
            if refreshed_transport.total_amount == 0:
                refreshed_transport = self._merge_transport_order_status(context.transport_order, refreshed_transport)
            context.transport_order = refreshed_transport
            transport_status = self._normalize_status(refreshed_transport.status)
            if transport_status in {"CANCELLED", "CANCELED"}:
                self.state_machine.transition(context, TravelState.USER_CANCELLED)
                self.session_store.save(context)
                return context
            if transport_status in {"FAILED", "FAILURE"} and context.state != TravelState.ORDER_FAILED.value:
                self.state_machine.transition(context, TravelState.ORDER_FAILED)
                self.session_store.save(context)
                return context

        refreshed = self.gateway.call(
            "get_order_status",
            order_id=context.order.order_id,
            user_id=context.request.user_id,
        )
        if refreshed.total_amount == 0:
            refreshed = self._merge_order_status(context.order, refreshed)
        context.order = refreshed
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
            transport_cancellation = self.gateway.call(
                "cancel_transport_order",
                order_id=context.transport_order.order_id,
                user_id=context.request.user_id,
                reason=reason,
            )
            context.transport_order_cancellation = transport_cancellation
            compensation_payload["transport_order_cancellation"] = asdict(transport_cancellation)
            context.append_event(
                "Recovery compensation completed: "
                f"cancel_transport_order {transport_cancellation.target_id} -> {transport_cancellation.status}."
            )

        if cancel_order and context.order is not None and not self._compensation_done(context.order_cancellation):
            cancellation = self.gateway.call(
                "cancel_order",
                order_id=context.order.order_id,
                user_id=context.request.user_id,
                reason=reason,
            )
            context.order_cancellation = cancellation
            compensation_payload["order_cancellation"] = asdict(cancellation)
            context.append_event(
                f"Recovery compensation completed: cancel_order {cancellation.target_id} -> {cancellation.status}."
            )

        if release_inventory and context.inventory_lock is not None and not self._compensation_done(context.inventory_release):
            release = self.gateway.call(
                "release_hotel_inventory",
                lock_id=context.inventory_lock.lock_id,
                user_id=context.request.user_id,
                reason=reason,
            )
            context.inventory_release = release
            compensation_payload["inventory_release"] = asdict(release)
            context.append_event(
                f"Recovery compensation completed: release_hotel_inventory {release.target_id} -> {release.status}."
            )

        if cancel_approval and context.approval is not None and not self._compensation_done(context.approval_cancellation):
            approval_status = self._normalize_status(context.approval.status)
            if approval_status not in {"REJECTED", "DENIED", "REFUSED", "CANCELLED", "CANCELED"}:
                approval_cancellation = self.gateway.call(
                    "cancel_approval",
                    approval_id=context.approval.approval_id,
                    user_id=context.request.user_id,
                    reason=reason,
                )
                context.approval_cancellation = approval_cancellation
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

        if context.policy_result is None:
            context.policy_result = self.gateway.call(
                "check_policy",
                user_id=context.request.user_id,
                destination_city=context.request.destination_city,
                budget_per_night=context.request.budget_per_night,
            )
        if context.transport_policy_result is None:
            context.transport_policy_result = self.gateway.call(
                "check_transport_policy",
                user_id=context.request.user_id,
                origin_city=context.request.origin_city,
                destination_city=context.request.destination_city,
                travel_date=context.request.start_date,
            )
        if context.itinerary is None:
            context.itinerary = self.gateway.call(
                "plan_itinerary",
                origin_city=context.request.origin_city,
                destination_city=context.request.destination_city,
                start_date=context.request.start_date,
                end_date=context.request.end_date,
                purpose=context.request.purpose,
                venue=context.request.venue,
            )

        max_price = self._effective_hotel_budget(context.request, context.policy_result.approved_budget)
        context.hotel_options = self.gateway.call(
            "search_hotels",
            city=context.request.destination_city,
            check_in=context.itinerary.check_in,
            check_out=context.itinerary.check_out,
            venue=context.request.venue,
            max_price=max_price,
            preferences=context.request.preferences,
        )
        context.transport_options = self.gateway.call(
            "search_transport",
            origin_city=context.request.origin_city,
            destination_city=context.request.destination_city,
            travel_date=context.request.start_date,
            max_price=context.transport_policy_result.max_transport_price,
            preferences=context.request.preferences,
        )
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

    def cancel_trip(self, context: TravelContext, reason: str = "user_cancelled") -> TravelContext:
        if context.transport_order is not None and not self._compensation_done(context.transport_order_cancellation):
            transport_cancellation = self.gateway.call(
                "cancel_transport_order",
                order_id=context.transport_order.order_id,
                user_id=context.request.user_id,
                reason=reason,
            )
            context.transport_order_cancellation = transport_cancellation
            context.append_event(
                "Compensation completed: "
                f"cancel_transport_order {transport_cancellation.target_id} -> {transport_cancellation.status}."
            )

        if context.order is not None and not self._compensation_done(context.order_cancellation):
            cancellation = self.gateway.call(
                "cancel_order",
                order_id=context.order.order_id,
                user_id=context.request.user_id,
                reason=reason,
            )
            context.order_cancellation = cancellation
            context.append_event(
                f"Compensation completed: cancel_order {cancellation.target_id} -> {cancellation.status}."
            )

        if context.inventory_lock is not None and not self._compensation_done(context.inventory_release):
            release = self.gateway.call(
                "release_hotel_inventory",
                lock_id=context.inventory_lock.lock_id,
                user_id=context.request.user_id,
                reason=reason,
            )
            context.inventory_release = release
            context.append_event(
                f"Compensation completed: release_hotel_inventory {release.target_id} -> {release.status}."
            )

        if context.state != TravelState.USER_CANCELLED.value:
            self.state_machine.transition(context, TravelState.USER_CANCELLED)
        self.session_store.save(context)
        return context

    @staticmethod
    def _effective_hotel_budget(request: TravelRequest, approved_budget: int) -> int:
        if request.budget_per_night is None:
            return approved_budget
        return min(request.budget_per_night, approved_budget)

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
    session_store: SessionStore | None = None,
) -> TravelAgent:
    gateway = ToolGateway()
    resolved_settings = settings or IntegrationSettings.from_env()
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
        name="send_notification",
        description="Send IM or task notification for workflow events.",
        required=("session_id", "user_id", "event_type", "title", "message", "channel", "payload"),
        handler=integrations.send_notification,
    )
    if session_store is None and resolved_settings.session_db_path:
        session_store = SQLiteSessionStore(resolved_settings.session_db_path)
    return TravelAgent(gateway=gateway, session_store=session_store)
