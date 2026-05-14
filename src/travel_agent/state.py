from __future__ import annotations

from enum import Enum

from .models import TravelContext


class TravelState(str, Enum):
    DRAFT = "DRAFT"
    POLICY_CHECKED = "POLICY_CHECKED"
    PLAN_GENERATED = "PLAN_GENERATED"
    USER_CONFIRMED = "USER_CONFIRMED"
    APPROVAL_CREATED = "APPROVAL_CREATED"
    APPROVAL_APPROVED = "APPROVAL_APPROVED"
    INVENTORY_LOCKED = "INVENTORY_LOCKED"
    ORDER_CREATED = "ORDER_CREATED"
    COMPLETED = "COMPLETED"
    APPROVAL_REJECTED = "APPROVAL_REJECTED"
    PRICE_CHANGED = "PRICE_CHANGED"
    INVENTORY_EXPIRED = "INVENTORY_EXPIRED"
    ORDER_FAILED = "ORDER_FAILED"
    USER_CANCELLED = "USER_CANCELLED"


ALLOWED_TRANSITIONS = {
    TravelState.DRAFT: {TravelState.POLICY_CHECKED, TravelState.USER_CANCELLED},
    TravelState.POLICY_CHECKED: {TravelState.PLAN_GENERATED, TravelState.USER_CANCELLED},
    TravelState.PLAN_GENERATED: {TravelState.USER_CONFIRMED, TravelState.USER_CANCELLED},
    TravelState.USER_CONFIRMED: {TravelState.APPROVAL_CREATED, TravelState.USER_CANCELLED},
    TravelState.APPROVAL_CREATED: {
        TravelState.APPROVAL_APPROVED,
        TravelState.APPROVAL_REJECTED,
        TravelState.USER_CANCELLED,
    },
    TravelState.APPROVAL_REJECTED: {TravelState.USER_CANCELLED},
    TravelState.APPROVAL_APPROVED: {TravelState.INVENTORY_LOCKED, TravelState.USER_CANCELLED},
    TravelState.INVENTORY_LOCKED: {
        TravelState.ORDER_CREATED,
        TravelState.PRICE_CHANGED,
        TravelState.INVENTORY_EXPIRED,
        TravelState.ORDER_FAILED,
        TravelState.USER_CANCELLED,
    },
    TravelState.ORDER_CREATED: {
        TravelState.COMPLETED,
        TravelState.PRICE_CHANGED,
        TravelState.INVENTORY_EXPIRED,
        TravelState.ORDER_FAILED,
        TravelState.USER_CANCELLED,
    },
    TravelState.COMPLETED: {TravelState.ORDER_FAILED, TravelState.USER_CANCELLED},
    TravelState.PRICE_CHANGED: {TravelState.INVENTORY_LOCKED, TravelState.PLAN_GENERATED, TravelState.USER_CANCELLED},
    TravelState.INVENTORY_EXPIRED: {TravelState.PLAN_GENERATED, TravelState.USER_CANCELLED},
    TravelState.ORDER_FAILED: {TravelState.PLAN_GENERATED, TravelState.USER_CANCELLED},
}


class StateTransitionError(ValueError):
    pass


class WorkflowStateMachine:
    def transition(self, context: TravelContext, next_state: TravelState) -> None:
        current_state = TravelState(context.state)
        allowed = ALLOWED_TRANSITIONS.get(current_state, set())
        if next_state not in allowed:
            raise StateTransitionError(f"Cannot transition from {current_state.value} to {next_state.value}.")
        context.state = next_state.value
        context.append_event(f"State changed: {current_state.value} -> {next_state.value}.")
