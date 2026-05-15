from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime, timezone
from typing import Any

from .models import (
    AgentExecutionRecord,
    ChangeRecord,
    CompensationResult,
    RefundEstimate,
    TravelContext,
    TravelOrder,
    TransportOrder,
)
from .tools import ToolGateway


def _record_execution(
    context: TravelContext,
    agent_name: str,
    action: str,
    status: str,
    input_refs: dict[str, Any] | None = None,
    output_refs: dict[str, Any] | None = None,
    message: str = "",
) -> None:
    refs = {
        "session_id": context.session_id,
        "workflow_generation": context.workflow_generation,
    }
    if input_refs:
        refs.update(input_refs)
    context.agent_executions.append(
        AgentExecutionRecord(
            agent_name=agent_name,
            action=action,
            status=status,
            input_refs=refs,
            output_refs=output_refs or {},
            message=message,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
    )


def _merge_order_status(original: TravelOrder, refreshed: TravelOrder) -> TravelOrder:
    if refreshed.total_amount != 0:
        return refreshed
    return TravelOrder(
        order_id=refreshed.order_id,
        status=refreshed.status,
        total_amount=original.total_amount,
        currency=original.currency,
        payload=refreshed.payload,
        source=refreshed.source,
    )


def _merge_transport_order_status(original: TransportOrder, refreshed: TransportOrder) -> TransportOrder:
    if refreshed.total_amount != 0:
        return refreshed
    return TransportOrder(
        order_id=refreshed.order_id,
        status=refreshed.status,
        total_amount=original.total_amount,
        currency=original.currency,
        payload=refreshed.payload,
        source=refreshed.source,
    )


class PolicyAgent:
    def __init__(self, gateway: ToolGateway) -> None:
        self.gateway = gateway

    def check(self, context: TravelContext) -> TravelContext:
        request = context.request
        context.policy_result = self.gateway.call(
            "check_policy",
            user_id=request.user_id,
            destination_city=request.destination_city,
            budget_per_night=request.budget_per_night,
        )
        context.transport_policy_result = self.gateway.call(
            "check_transport_policy",
            user_id=request.user_id,
            origin_city=request.origin_city,
            destination_city=request.destination_city,
            travel_date=request.start_date,
        )
        context.append_event("PolicyAgent completed hotel and transport policy checks.")
        _record_execution(
            context,
            "PolicyAgent",
            "check_policies",
            "SUCCESS",
            input_refs={
                "user_id": request.user_id,
                "destination_city": request.destination_city,
            },
            output_refs={
                "policy_id": context.policy_result.policy_id,
                "transport_policy_id": context.transport_policy_result.policy_id,
                "hotel_compliant": context.policy_result.compliant,
                "transport_compliant": context.transport_policy_result.compliant,
            },
            message="Hotel and transport policies checked.",
        )
        return context


class ItineraryAgent:
    def __init__(self, gateway: ToolGateway) -> None:
        self.gateway = gateway

    def plan(self, context: TravelContext) -> TravelContext:
        request = context.request
        context.itinerary = self.gateway.call(
            "plan_itinerary",
            origin_city=request.origin_city,
            destination_city=request.destination_city,
            start_date=request.start_date,
            end_date=request.end_date,
            purpose=request.purpose,
            venue=request.venue,
        )
        context.append_event("ItineraryAgent created itinerary draft.")
        _record_execution(
            context,
            "ItineraryAgent",
            "plan_itinerary",
            "SUCCESS",
            input_refs={
                "origin_city": request.origin_city,
                "destination_city": request.destination_city,
            },
            output_refs={
                "check_in": context.itinerary.check_in.isoformat(),
                "check_out": context.itinerary.check_out.isoformat(),
                "agenda_count": len(context.itinerary.agenda),
            },
            message="Itinerary draft created.",
        )
        return context


class HotelAgent:
    def __init__(self, gateway: ToolGateway) -> None:
        self.gateway = gateway

    def search(self, context: TravelContext, max_price: int) -> TravelContext:
        if context.itinerary is None:
            raise ValueError("Itinerary is required before hotel search.")
        request = context.request
        context.hotel_options = self.gateway.call(
            "search_hotels",
            city=request.destination_city,
            check_in=context.itinerary.check_in,
            check_out=context.itinerary.check_out,
            venue=request.venue,
            max_price=max_price,
            preferences=request.preferences,
        )
        context.append_event("HotelAgent searched hotel inventory.")
        _record_execution(
            context,
            "HotelAgent",
            "search_hotels",
            "SUCCESS",
            input_refs={
                "city": request.destination_city,
                "max_price": max_price,
            },
            output_refs={
                "hotel_count": len(context.hotel_options),
                "hotel_ids": [hotel.hotel_id for hotel in context.hotel_options],
            },
            message="Hotel inventory searched.",
        )
        return context

    def lock_inventory(self, context: TravelContext) -> TravelContext:
        if context.selected_hotel is None:
            raise ValueError("Selected hotel is required before inventory lock.")
        if context.itinerary is None:
            raise ValueError("Itinerary is required before inventory lock.")

        context.inventory_lock = self.gateway.call(
            "lock_hotel_inventory",
            session_id=context.session_id,
            user_id=context.request.user_id,
            selected_hotel=asdict(context.selected_hotel),
            check_in=context.itinerary.check_in,
            check_out=context.itinerary.check_out,
            workflow_generation=context.workflow_generation,
        )
        context.append_event("HotelAgent locked hotel inventory.")
        _record_execution(
            context,
            "HotelAgent",
            "lock_hotel_inventory",
            "SUCCESS",
            input_refs={"hotel_id": context.selected_hotel.hotel_id},
            output_refs={
                "lock_id": context.inventory_lock.lock_id,
                "hotel_id": context.inventory_lock.hotel_id,
                "status": context.inventory_lock.status,
            },
            message="Hotel inventory locked.",
        )
        return context

    def verify_price(self, context: TravelContext) -> TravelContext:
        if context.selected_hotel is None:
            raise ValueError("Selected hotel is required before price verification.")
        if context.itinerary is None:
            raise ValueError("Itinerary is required before price verification.")
        if context.policy_result is None:
            raise ValueError("Policy result is required before price verification.")

        context.price_check = self.gateway.call(
            "verify_hotel_price",
            selected_hotel=asdict(context.selected_hotel),
            max_price=context.policy_result.approved_budget,
            check_in=context.itinerary.check_in,
            check_out=context.itinerary.check_out,
        )
        context.append_event("HotelAgent verified hotel price.")
        _record_execution(
            context,
            "HotelAgent",
            "verify_hotel_price",
            "SUCCESS",
            input_refs={"hotel_id": context.selected_hotel.hotel_id},
            output_refs={
                "hotel_id": context.price_check.hotel_id,
                "status": context.price_check.status,
                "current_price": context.price_check.current_price,
                "requires_confirmation": context.price_check.requires_confirmation,
            },
            message="Hotel price verified.",
        )
        return context

    def release_inventory(self, context: TravelContext, reason: str) -> CompensationResult | None:
        if context.inventory_lock is None:
            _record_execution(
                context,
                "HotelAgent",
                "release_hotel_inventory",
                "SKIPPED",
                input_refs={"reason": reason},
                message="Inventory release skipped because no lock exists.",
            )
            return None

        context.inventory_release = self.gateway.call(
            "release_hotel_inventory",
            lock_id=context.inventory_lock.lock_id,
            user_id=context.request.user_id,
            reason=reason,
        )
        context.append_event(
            "HotelAgent released hotel inventory: "
            f"{context.inventory_release.target_id} -> {context.inventory_release.status}."
        )
        _record_execution(
            context,
            "HotelAgent",
            "release_hotel_inventory",
            "SUCCESS",
            input_refs={
                "lock_id": context.inventory_lock.lock_id,
                "reason": reason,
            },
            output_refs={
                "target_id": context.inventory_release.target_id,
                "status": context.inventory_release.status,
            },
            message="Hotel inventory release compensation completed.",
        )
        return context.inventory_release


class TransportAgent:
    def __init__(self, gateway: ToolGateway) -> None:
        self.gateway = gateway

    def search(self, context: TravelContext) -> TravelContext:
        if context.transport_policy_result is None:
            raise ValueError("Transport policy is required before transport search.")
        request = context.request
        context.transport_options = self.gateway.call(
            "search_transport",
            origin_city=request.origin_city,
            destination_city=request.destination_city,
            travel_date=request.start_date,
            max_price=context.transport_policy_result.max_transport_price,
            preferences=request.preferences,
        )
        context.append_event("TransportAgent searched transport inventory.")
        _record_execution(
            context,
            "TransportAgent",
            "search_transport",
            "SUCCESS",
            input_refs={
                "origin_city": request.origin_city,
                "destination_city": request.destination_city,
            },
            output_refs={
                "transport_count": len(context.transport_options),
                "transport_ids": [option.transport_id for option in context.transport_options],
            },
            message="Transport inventory searched.",
        )
        return context

    def create_order(self, context: TravelContext) -> TravelContext:
        if context.approval is None:
            raise ValueError("Approval is required before transport booking.")
        if context.selected_transport is None:
            context.append_event("TransportAgent skipped booking: no selected transport.")
            _record_execution(
                context,
                "TransportAgent",
                "create_transport_order",
                "SKIPPED",
                message="Transport booking skipped because no transport was selected.",
            )
            return context

        context.transport_order = self.gateway.call(
            "create_transport_order",
            session_id=context.session_id,
            user_id=context.request.user_id,
            request=asdict(context.request),
            selected_transport=asdict(context.selected_transport),
            approval=asdict(context.approval),
            workflow_generation=context.workflow_generation,
        )
        context.append_event("TransportAgent created transport order.")
        _record_execution(
            context,
            "TransportAgent",
            "create_transport_order",
            "SUCCESS",
            input_refs={"transport_id": context.selected_transport.transport_id},
            output_refs={
                "order_id": context.transport_order.order_id,
                "status": context.transport_order.status,
                "total_amount": context.transport_order.total_amount,
            },
            message="Transport order created.",
        )
        return context

    def refresh_order(self, context: TravelContext) -> TravelContext:
        if context.transport_order is None:
            _record_execution(
                context,
                "TransportAgent",
                "get_transport_order_status",
                "SKIPPED",
                message="Transport order status refresh skipped because no order exists.",
            )
            return context

        original = context.transport_order
        refreshed = self.gateway.call(
            "get_transport_order_status",
            order_id=original.order_id,
            user_id=context.request.user_id,
        )
        context.transport_order = _merge_transport_order_status(original, refreshed)
        context.append_event("TransportAgent refreshed transport order status.")
        _record_execution(
            context,
            "TransportAgent",
            "get_transport_order_status",
            "SUCCESS",
            input_refs={"order_id": original.order_id},
            output_refs={
                "order_id": context.transport_order.order_id,
                "status": context.transport_order.status,
                "total_amount": context.transport_order.total_amount,
            },
            message="Transport order status refreshed.",
        )
        return context

    def cancel_order(self, context: TravelContext, reason: str) -> CompensationResult | None:
        if context.transport_order is None:
            _record_execution(
                context,
                "TransportAgent",
                "cancel_transport_order",
                "SKIPPED",
                input_refs={"reason": reason},
                message="Transport order cancellation skipped because no order exists.",
            )
            return None

        context.transport_order_cancellation = self.gateway.call(
            "cancel_transport_order",
            order_id=context.transport_order.order_id,
            user_id=context.request.user_id,
            reason=reason,
        )
        context.append_event(
            "TransportAgent cancelled transport order: "
            f"{context.transport_order_cancellation.target_id} -> {context.transport_order_cancellation.status}."
        )
        _record_execution(
            context,
            "TransportAgent",
            "cancel_transport_order",
            "SUCCESS",
            input_refs={
                "order_id": context.transport_order.order_id,
                "reason": reason,
            },
            output_refs={
                "target_id": context.transport_order_cancellation.target_id,
                "status": context.transport_order_cancellation.status,
            },
            message="Transport order cancellation compensation completed.",
        )
        return context.transport_order_cancellation

    def estimate_refund(self, context: TravelContext, reason: str) -> RefundEstimate | None:
        if context.transport_order is None:
            _record_execution(
                context,
                "TransportAgent",
                "estimate_refund",
                "SKIPPED",
                input_refs={"target_type": "transport", "reason": reason},
                message="Transport refund estimate skipped because no order exists.",
            )
            return None

        estimate = self.gateway.call(
            "estimate_refund",
            target_type="transport",
            target_id=context.transport_order.order_id,
            user_id=context.request.user_id,
            total_amount=context.transport_order.total_amount,
            reason=reason,
        )
        context.refund_estimates.append(estimate)
        context.append_event(
            "TransportAgent estimated transport refund: "
            f"{estimate.target_id} refundable {estimate.refundable_amount} {estimate.currency}."
        )
        _record_execution(
            context,
            "TransportAgent",
            "estimate_refund",
            "SUCCESS",
            input_refs={
                "target_type": "transport",
                "target_id": context.transport_order.order_id,
                "reason": reason,
            },
            output_refs={
                "estimate_id": estimate.estimate_id,
                "refundable_amount": estimate.refundable_amount,
                "penalty_amount": estimate.penalty_amount,
            },
            message="Transport refund estimated.",
        )
        return estimate

    def change_order(self, context: TravelContext, new_depart_at: str, reason: str) -> ChangeRecord:
        if context.transport_order is None:
            raise ValueError("Transport order is required before transport change.")

        change = self.gateway.call(
            "change_transport_order",
            order_id=context.transport_order.order_id,
            user_id=context.request.user_id,
            new_depart_at=new_depart_at,
            reason=reason,
        )
        context.change_records.append(change)
        context.append_event(
            f"TransportAgent changed transport order: {change.target_id} -> {change.status}."
        )
        _record_execution(
            context,
            "TransportAgent",
            "change_transport_order",
            "SUCCESS",
            input_refs={
                "order_id": context.transport_order.order_id,
                "new_depart_at": new_depart_at,
                "reason": reason,
            },
            output_refs={
                "change_id": change.change_id,
                "status": change.status,
                "penalty_amount": change.penalty_amount,
            },
            message="Transport order changed.",
        )
        return change


class ApprovalAgent:
    def __init__(self, gateway: ToolGateway) -> None:
        self.gateway = gateway

    def create(self, context: TravelContext) -> TravelContext:
        if context.selected_hotel is None:
            raise ValueError("Selected hotel is required before approval creation.")
        if context.selected_transport is None:
            raise ValueError("Selected transport is required before approval creation.")

        context.approval = self.gateway.call(
            "create_approval",
            session_id=context.session_id,
            user_id=context.request.user_id,
            request=asdict(context.request),
            policy=asdict(context.policy_result) if context.policy_result else {},
            transport_policy=asdict(context.transport_policy_result) if context.transport_policy_result else {},
            itinerary=asdict(context.itinerary) if context.itinerary else {},
            selected_hotel=asdict(context.selected_hotel),
            selected_transport=asdict(context.selected_transport),
            workflow_generation=context.workflow_generation,
        )
        context.append_event("ApprovalAgent created approval record.")
        _record_execution(
            context,
            "ApprovalAgent",
            "create_approval",
            "SUCCESS",
            input_refs={
                "hotel_id": context.selected_hotel.hotel_id,
                "transport_id": context.selected_transport.transport_id,
            },
            output_refs={
                "approval_id": context.approval.approval_id,
                "status": context.approval.status,
            },
            message="OA approval record created.",
        )
        return context

    def refresh(self, context: TravelContext) -> TravelContext:
        if context.approval is None:
            raise ValueError("Approval must be created before status refresh.")

        original_id = context.approval.approval_id
        context.approval = self.gateway.call(
            "get_approval_status",
            approval_id=original_id,
            user_id=context.request.user_id,
        )
        context.append_event("ApprovalAgent refreshed approval status.")
        _record_execution(
            context,
            "ApprovalAgent",
            "get_approval_status",
            "SUCCESS",
            input_refs={"approval_id": original_id},
            output_refs={
                "approval_id": context.approval.approval_id,
                "status": context.approval.status,
            },
            message="OA approval status refreshed.",
        )
        return context

    def cancel(self, context: TravelContext, reason: str) -> CompensationResult | None:
        if context.approval is None:
            _record_execution(
                context,
                "ApprovalAgent",
                "cancel_approval",
                "SKIPPED",
                input_refs={"reason": reason},
                message="Approval cancellation skipped because no approval exists.",
            )
            return None

        context.approval_cancellation = self.gateway.call(
            "cancel_approval",
            approval_id=context.approval.approval_id,
            user_id=context.request.user_id,
            reason=reason,
        )
        context.append_event(
            "ApprovalAgent cancelled approval: "
            f"{context.approval_cancellation.target_id} -> {context.approval_cancellation.status}."
        )
        _record_execution(
            context,
            "ApprovalAgent",
            "cancel_approval",
            "SUCCESS",
            input_refs={
                "approval_id": context.approval.approval_id,
                "reason": reason,
            },
            output_refs={
                "target_id": context.approval_cancellation.target_id,
                "status": context.approval_cancellation.status,
            },
            message="OA approval cancellation compensation completed.",
        )
        return context.approval_cancellation


class BookingAgent:
    def __init__(self, gateway: ToolGateway) -> None:
        self.gateway = gateway

    def create_hotel_order(self, context: TravelContext) -> TravelContext:
        if context.selected_hotel is None:
            raise ValueError("Selected hotel is required before order creation.")
        if context.itinerary is None:
            raise ValueError("Itinerary is required before order creation.")
        if context.approval is None:
            raise ValueError("Approval is required before order creation.")
        if context.inventory_lock is None:
            raise ValueError("Inventory lock is required before order creation.")

        context.order = self.gateway.call(
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
        context.append_event("BookingAgent created hotel order.")
        _record_execution(
            context,
            "BookingAgent",
            "create_order",
            "SUCCESS",
            input_refs={
                "hotel_id": context.selected_hotel.hotel_id,
                "lock_id": context.inventory_lock.lock_id,
            },
            output_refs={
                "order_id": context.order.order_id,
                "status": context.order.status,
                "total_amount": context.order.total_amount,
            },
            message="Hotel order created.",
        )
        return context

    def refresh_hotel_order(self, context: TravelContext) -> TravelContext:
        if context.order is None:
            raise ValueError("Order must be created before status refresh.")

        original = context.order
        refreshed = self.gateway.call(
            "get_order_status",
            order_id=original.order_id,
            user_id=context.request.user_id,
        )
        context.order = _merge_order_status(original, refreshed)
        context.append_event("BookingAgent refreshed hotel order status.")
        _record_execution(
            context,
            "BookingAgent",
            "get_order_status",
            "SUCCESS",
            input_refs={"order_id": original.order_id},
            output_refs={
                "order_id": context.order.order_id,
                "status": context.order.status,
                "total_amount": context.order.total_amount,
            },
            message="Hotel order status refreshed.",
        )
        return context

    def cancel_hotel_order(self, context: TravelContext, reason: str) -> CompensationResult | None:
        if context.order is None:
            _record_execution(
                context,
                "BookingAgent",
                "cancel_order",
                "SKIPPED",
                input_refs={"reason": reason},
                message="Hotel order cancellation skipped because no order exists.",
            )
            return None

        context.order_cancellation = self.gateway.call(
            "cancel_order",
            order_id=context.order.order_id,
            user_id=context.request.user_id,
            reason=reason,
        )
        context.append_event(
            "BookingAgent cancelled hotel order: "
            f"{context.order_cancellation.target_id} -> {context.order_cancellation.status}."
        )
        _record_execution(
            context,
            "BookingAgent",
            "cancel_order",
            "SUCCESS",
            input_refs={
                "order_id": context.order.order_id,
                "reason": reason,
            },
            output_refs={
                "target_id": context.order_cancellation.target_id,
                "status": context.order_cancellation.status,
            },
            message="Hotel order cancellation compensation completed.",
        )
        return context.order_cancellation

    def estimate_refund(self, context: TravelContext, reason: str) -> RefundEstimate | None:
        if context.order is None:
            _record_execution(
                context,
                "BookingAgent",
                "estimate_refund",
                "SKIPPED",
                input_refs={"target_type": "hotel", "reason": reason},
                message="Hotel refund estimate skipped because no order exists.",
            )
            return None

        estimate = self.gateway.call(
            "estimate_refund",
            target_type="hotel",
            target_id=context.order.order_id,
            user_id=context.request.user_id,
            total_amount=context.order.total_amount,
            reason=reason,
        )
        context.refund_estimates.append(estimate)
        context.append_event(
            "BookingAgent estimated hotel refund: "
            f"{estimate.target_id} refundable {estimate.refundable_amount} {estimate.currency}."
        )
        _record_execution(
            context,
            "BookingAgent",
            "estimate_refund",
            "SUCCESS",
            input_refs={
                "target_type": "hotel",
                "target_id": context.order.order_id,
                "reason": reason,
            },
            output_refs={
                "estimate_id": estimate.estimate_id,
                "refundable_amount": estimate.refundable_amount,
                "penalty_amount": estimate.penalty_amount,
            },
            message="Hotel refund estimated.",
        )
        return estimate

    def change_hotel_order(
        self,
        context: TravelContext,
        new_check_in: date,
        new_check_out: date,
        reason: str,
    ) -> ChangeRecord:
        if context.order is None:
            raise ValueError("Hotel order is required before hotel change.")

        change = self.gateway.call(
            "change_hotel_order",
            order_id=context.order.order_id,
            user_id=context.request.user_id,
            new_check_in=new_check_in,
            new_check_out=new_check_out,
            reason=reason,
        )
        context.change_records.append(change)
        context.append_event(f"BookingAgent changed hotel order: {change.target_id} -> {change.status}.")
        _record_execution(
            context,
            "BookingAgent",
            "change_hotel_order",
            "SUCCESS",
            input_refs={
                "order_id": context.order.order_id,
                "new_check_in": new_check_in.isoformat(),
                "new_check_out": new_check_out.isoformat(),
                "reason": reason,
            },
            output_refs={
                "change_id": change.change_id,
                "status": change.status,
                "penalty_amount": change.penalty_amount,
            },
            message="Hotel order changed.",
        )
        return change


class AgentTeam:
    def __init__(self, gateway: ToolGateway) -> None:
        self.policy = PolicyAgent(gateway)
        self.itinerary = ItineraryAgent(gateway)
        self.hotel = HotelAgent(gateway)
        self.transport = TransportAgent(gateway)
        self.approval = ApprovalAgent(gateway)
        self.booking = BookingAgent(gateway)


def build_agent_team(gateway: ToolGateway) -> AgentTeam:
    return AgentTeam(gateway)
