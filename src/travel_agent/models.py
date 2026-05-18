from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any


@dataclass(frozen=True)
class TravelRequest:
    user_id: str
    origin_city: str
    destination_city: str
    start_date: date
    end_date: date
    purpose: str
    venue: str
    budget_per_night: int | None = None
    require_approval: bool = True
    preferences: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.end_date <= self.start_date:
            raise ValueError("end_date must be later than start_date.")


@dataclass(frozen=True)
class Task:
    task_id: str
    task_type: str
    description: str
    depends_on: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class TaskPlan:
    goal: str
    tasks: list[Task]


@dataclass(frozen=True)
class PolicyResult:
    policy_id: str
    max_hotel_price: int
    approved_budget: int
    compliant: bool
    reasons: list[str]
    source: str = "mock"


@dataclass(frozen=True)
class TransportPolicyResult:
    policy_id: str
    allowed_seat_classes: list[str]
    max_transport_price: int
    compliant: bool
    reasons: list[str]
    source: str = "mock"


@dataclass(frozen=True)
class ItineraryPlan:
    summary: str
    check_in: date
    check_out: date
    agenda: list[str]


@dataclass(frozen=True)
class HotelOption:
    hotel_id: str
    name: str
    city: str
    address: str
    nightly_price: int
    distance_km: float
    rating: float
    refundable: bool
    policy_compliant: bool
    source: str = "mock"


@dataclass(frozen=True)
class TransportOption:
    transport_id: str
    mode: str
    provider: str
    origin_city: str
    destination_city: str
    depart_at: str
    arrive_at: str
    seat_class: str
    price: int
    refundable: bool
    policy_compliant: bool
    source: str = "mock"


@dataclass(frozen=True)
class ApprovalRecord:
    approval_id: str
    status: str
    payload: dict[str, Any]
    source: str = "mock"


ApprovalDraft = ApprovalRecord


@dataclass(frozen=True)
class InventoryLock:
    lock_id: str
    status: str
    hotel_id: str
    expires_at: str
    payload: dict[str, Any]
    source: str = "mock"


@dataclass(frozen=True)
class TravelOrder:
    order_id: str
    status: str
    total_amount: int
    currency: str
    payload: dict[str, Any]
    source: str = "mock"


@dataclass(frozen=True)
class TransportOrder:
    order_id: str
    status: str
    total_amount: int
    currency: str
    payload: dict[str, Any]
    source: str = "mock"


@dataclass(frozen=True)
class PriceCheckResult:
    hotel_id: str
    status: str
    original_price: int
    current_price: int | None
    policy_compliant: bool
    requires_confirmation: bool
    payload: dict[str, Any]
    source: str = "mock"


@dataclass(frozen=True)
class CompensationResult:
    action: str
    target_id: str
    status: str
    payload: dict[str, Any]
    source: str = "mock"


@dataclass(frozen=True)
class RefundEstimate:
    estimate_id: str
    target_type: str
    target_id: str
    refundable_amount: int
    penalty_amount: int
    currency: str
    rules: list[str]
    payload: dict[str, Any]
    source: str = "mock"


@dataclass(frozen=True)
class RefundConfirmationRecord:
    confirmation_id: str
    estimate_id: str
    target_type: str
    target_id: str
    status: str
    confirmed_amount: int
    currency: str
    payload: dict[str, Any]
    source: str = "mock"


@dataclass(frozen=True)
class ChangeRecord:
    change_id: str
    target_type: str
    target_id: str
    status: str
    penalty_amount: int
    currency: str
    payload: dict[str, Any]
    source: str = "mock"


@dataclass(frozen=True)
class CalendarSyncRecord:
    calendar_event_id: str
    event_type: str
    status: str
    user_id: str
    title: str
    start_at: str
    end_at: str
    payload: dict[str, Any]
    source: str = "mock"
    attendees: list[str] = field(default_factory=list)
    retry_count: int = 0
    max_retries: int = 3
    last_error: str | None = None


@dataclass(frozen=True)
class NotificationRecord:
    notification_id: str
    event_type: str
    channel: str
    recipient_id: str
    title: str
    message: str
    status: str
    payload: dict[str, Any]
    source: str = "mock"
    retry_count: int = 0
    max_retries: int = 3
    last_error: str | None = None


@dataclass(frozen=True)
class DeadLetterNotification:
    session_id: str
    state: str
    notification: NotificationRecord


@dataclass(frozen=True)
class DeadLetterCalendarSync:
    session_id: str
    state: str
    calendar_sync: CalendarSyncRecord


@dataclass(frozen=True)
class WorkerRunRecord:
    run_id: str
    started_at: str
    finished_at: str
    scanned: int
    advanced: int
    skipped: int
    errors: dict[str, str]
    session_ids: list[str]


@dataclass(frozen=True)
class RecoveryRecord:
    recovery_id: str
    action: str
    reason: str
    from_state: str
    to_state: str
    payload: dict[str, Any]
    created_at: str
    source: str = "local"


@dataclass(frozen=True)
class AgentExecutionRecord:
    agent_name: str
    action: str
    status: str
    input_refs: dict[str, Any]
    output_refs: dict[str, Any]
    message: str
    created_at: str


@dataclass
class TravelContext:
    session_id: str
    request: TravelRequest
    state: str
    workflow_generation: int = 1
    task_plan: TaskPlan | None = None
    policy_result: PolicyResult | None = None
    transport_policy_result: TransportPolicyResult | None = None
    itinerary: ItineraryPlan | None = None
    hotel_options: list[HotelOption] = field(default_factory=list)
    transport_options: list[TransportOption] = field(default_factory=list)
    selected_hotel: HotelOption | None = None
    selected_transport: TransportOption | None = None
    approval: ApprovalRecord | None = None
    price_check: PriceCheckResult | None = None
    inventory_lock: InventoryLock | None = None
    order: TravelOrder | None = None
    transport_order: TransportOrder | None = None
    approval_cancellation: CompensationResult | None = None
    order_cancellation: CompensationResult | None = None
    transport_order_cancellation: CompensationResult | None = None
    inventory_release: CompensationResult | None = None
    refund_estimates: list[RefundEstimate] = field(default_factory=list)
    refund_confirmations: list[RefundConfirmationRecord] = field(default_factory=list)
    change_approvals: list[ApprovalRecord] = field(default_factory=list)
    change_records: list[ChangeRecord] = field(default_factory=list)
    change_failure_compensations: list[CompensationResult] = field(default_factory=list)
    calendar_syncs: list[CalendarSyncRecord] = field(default_factory=list)
    notifications: list[NotificationRecord] = field(default_factory=list)
    notification_keys: list[str] = field(default_factory=list)
    recovery_records: list[RecoveryRecord] = field(default_factory=list)
    agent_executions: list[AgentExecutionRecord] = field(default_factory=list)
    events: list[str] = field(default_factory=list)

    def append_event(self, message: str) -> None:
        self.events.append(message)
