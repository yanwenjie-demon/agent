from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from .models import (
    ApprovalRecord,
    CompensationResult,
    HotelOption,
    InventoryLock,
    ItineraryPlan,
    NotificationRecord,
    PolicyResult,
    PriceCheckResult,
    TravelOrder,
    TransportOption,
    TransportOrder,
    TransportPolicyResult,
)


CITY_POLICY_CAPS = {
    "北京": 650,
    "上海": 650,
    "广州": 550,
    "深圳": 600,
    "杭州": 550,
}


TRANSPORT_POLICY_CAPS = {
    ("北京", "上海"): 1600,
    ("上海", "北京"): 1600,
    ("北京", "深圳"): 2400,
    ("深圳", "北京"): 2400,
}


HOTEL_INVENTORY = {
    "上海": [
        HotelOption("SHA-001", "张江商务精选酒店", "上海", "祖冲之路 88 号", 620, 0.8, 4.7, True, True),
        HotelOption("SHA-002", "浦东会议中心酒店", "上海", "科苑路 186 号", 650, 1.4, 4.6, True, True),
        HotelOption("SHA-003", "陆家嘴行政公寓", "上海", "银城中路 66 号", 780, 11.2, 4.8, False, False),
        HotelOption("SHA-004", "世纪公园轻居酒店", "上海", "锦绣路 300 号", 520, 5.5, 4.3, True, True),
    ],
    "北京": [
        HotelOption("BJS-001", "望京商务酒店", "北京", "广顺北大街 12 号", 610, 1.0, 4.5, True, True),
        HotelOption("BJS-002", "中关村会议酒店", "北京", "科学院南路 8 号", 650, 2.2, 4.6, True, True),
        HotelOption("BJS-003", "国贸行政酒店", "北京", "建国门外大街 1 号", 820, 9.8, 4.8, False, False),
    ],
}


TRANSPORT_INVENTORY = {
    ("北京", "上海"): [
        TransportOption("TRN-BJS-SHA-001", "train", "高铁", "北京", "上海", "2026-06-03T08:00:00+08:00", "2026-06-03T12:40:00+08:00", "二等座", 553, True, True),
        TransportOption("FLT-BJS-SHA-002", "flight", "国航", "北京", "上海", "2026-06-03T09:30:00+08:00", "2026-06-03T11:45:00+08:00", "经济舱", 980, True, True),
        TransportOption("FLT-BJS-SHA-003", "flight", "东航", "北京", "上海", "2026-06-03T12:20:00+08:00", "2026-06-03T14:35:00+08:00", "商务舱", 2800, False, False),
    ],
    ("上海", "北京"): [
        TransportOption("TRN-SHA-BJS-001", "train", "高铁", "上海", "北京", "2026-06-05T16:00:00+08:00", "2026-06-05T20:40:00+08:00", "二等座", 553, True, True),
        TransportOption("FLT-SHA-BJS-002", "flight", "东航", "上海", "北京", "2026-06-05T18:20:00+08:00", "2026-06-05T20:35:00+08:00", "经济舱", 1050, True, True),
    ],
}


def check_policy(
    user_id: str,
    destination_city: str,
    budget_per_night: int | None = None,
) -> PolicyResult:
    cap = CITY_POLICY_CAPS.get(destination_city, 500)
    requested = budget_per_night if budget_per_night is not None else cap
    compliant = requested <= cap
    reasons = []
    if compliant:
        reasons.append(f"Requested hotel budget {requested} is within policy cap {cap}.")
    else:
        reasons.append(f"Requested hotel budget {requested} exceeds policy cap {cap}; capped to {cap}.")
    return PolicyResult(
        policy_id=f"POLICY-{destination_city}-{user_id}",
        max_hotel_price=cap,
        approved_budget=min(requested, cap),
        compliant=compliant,
        reasons=reasons,
    )


def check_transport_policy(
    user_id: str,
    origin_city: str,
    destination_city: str,
    travel_date: date,
) -> TransportPolicyResult:
    del travel_date
    cap = TRANSPORT_POLICY_CAPS.get((origin_city, destination_city), 1800)
    return TransportPolicyResult(
        policy_id=f"TRANSPORT-POLICY-{origin_city}-{destination_city}-{user_id}",
        allowed_seat_classes=["二等座", "经济舱"],
        max_transport_price=cap,
        compliant=True,
        reasons=[f"Transport cap for {origin_city} to {destination_city} is {cap}."],
    )


def plan_itinerary(
    origin_city: str,
    destination_city: str,
    start_date: date,
    end_date: date,
    purpose: str,
    venue: str,
) -> ItineraryPlan:
    agenda = [
        f"{start_date.isoformat()} arrive in {destination_city} from {origin_city}.",
        f"{start_date.isoformat()} attend {purpose} near {venue}.",
        f"{end_date.isoformat()} return to {origin_city}.",
    ]
    return ItineraryPlan(
        summary=f"{origin_city} to {destination_city} business trip for {purpose}.",
        check_in=start_date,
        check_out=end_date,
        agenda=agenda,
    )


def search_hotels(
    city: str,
    check_in: date,
    check_out: date,
    venue: str,
    max_price: int,
    preferences: list[str] | None = None,
) -> list[HotelOption]:
    del check_in, check_out, venue, preferences
    inventory = HOTEL_INVENTORY.get(city) or _default_city_inventory(city)
    normalized = [
        HotelOption(
            hotel.hotel_id,
            hotel.name,
            hotel.city,
            hotel.address,
            hotel.nightly_price,
            hotel.distance_km,
            hotel.rating,
            hotel.refundable,
            hotel.nightly_price <= max_price,
        )
        for hotel in inventory
    ]
    return sorted(
        normalized,
        key=lambda hotel: (
            not hotel.policy_compliant,
            hotel.distance_km,
            -hotel.rating,
            hotel.nightly_price,
        ),
    )[:3]


def search_transport(
    origin_city: str,
    destination_city: str,
    travel_date: date,
    max_price: int,
    preferences: list[str] | None = None,
) -> list[TransportOption]:
    del preferences
    inventory = TRANSPORT_INVENTORY.get((origin_city, destination_city)) or _default_transport_inventory(
        origin_city,
        destination_city,
        travel_date,
    )
    normalized = [
        TransportOption(
            option.transport_id,
            option.mode,
            option.provider,
            option.origin_city,
            option.destination_city,
            _with_date(option.depart_at, travel_date),
            _with_date(option.arrive_at, travel_date),
            option.seat_class,
            option.price,
            option.refundable,
            option.price <= max_price and option.seat_class in {"二等座", "经济舱"},
        )
        for option in inventory
    ]
    return sorted(
        normalized,
        key=lambda option: (
            not option.policy_compliant,
            option.price,
            option.depart_at,
        ),
    )[:3]


def create_approval(
    session_id: str,
    user_id: str,
    request: dict[str, Any],
    policy: dict[str, Any],
    itinerary: dict[str, Any],
    selected_hotel: dict[str, Any],
    transport_policy: dict[str, Any] | None = None,
    selected_transport: dict[str, Any] | None = None,
    workflow_generation: int = 1,
) -> ApprovalRecord:
    approval_id = "APP-" + uuid5(NAMESPACE_URL, f"{session_id}:{workflow_generation}:{user_id}").hex[:10].upper()
    return ApprovalRecord(
        approval_id=approval_id,
        status="PENDING_APPROVAL",
        payload={
            "session_id": session_id,
            "user_id": user_id,
            "request": request,
            "policy": policy,
            "transport_policy": transport_policy or {},
            "itinerary": itinerary,
            "selected_hotel": selected_hotel,
            "selected_transport": selected_transport or {},
            "workflow_generation": workflow_generation,
        },
    )


def create_approval_draft(
    session_id: str,
    user_id: str,
    request: dict[str, Any],
    policy: dict[str, Any],
    itinerary: dict[str, Any],
    selected_hotel: dict[str, Any],
    transport_policy: dict[str, Any] | None = None,
    selected_transport: dict[str, Any] | None = None,
    workflow_generation: int = 1,
) -> ApprovalRecord:
    return create_approval(
        session_id,
        user_id,
        request,
        policy,
        itinerary,
        selected_hotel,
        transport_policy,
        selected_transport,
        workflow_generation,
    )


def get_approval_status(approval_id: str, user_id: str) -> ApprovalRecord:
    return ApprovalRecord(
        approval_id=approval_id,
        status="APPROVED",
        payload={
            "approval_id": approval_id,
            "user_id": user_id,
            "approver": "mock-manager",
            "comment": "Approved by mock OA workflow.",
        },
    )


def cancel_approval(approval_id: str, user_id: str, reason: str) -> CompensationResult:
    return CompensationResult(
        action="cancel_approval",
        target_id=approval_id,
        status="CANCELLED",
        payload={
            "approval_id": approval_id,
            "user_id": user_id,
            "reason": reason,
        },
    )


def lock_hotel_inventory(
    session_id: str,
    user_id: str,
    selected_hotel: dict[str, Any],
    check_in: date,
    check_out: date,
    workflow_generation: int = 1,
) -> InventoryLock:
    hotel_id = str(selected_hotel["hotel_id"])
    lock_id = "LOCK-" + uuid5(NAMESPACE_URL, f"{session_id}:{workflow_generation}:{user_id}:{hotel_id}").hex[:10].upper()
    expires_at = (
        (datetime.now(timezone.utc) + timedelta(minutes=15))
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
    return InventoryLock(
        lock_id=lock_id,
        status="LOCKED",
        hotel_id=hotel_id,
        expires_at=expires_at,
        payload={
            "session_id": session_id,
            "user_id": user_id,
            "selected_hotel": selected_hotel,
            "check_in": check_in.isoformat(),
            "check_out": check_out.isoformat(),
            "workflow_generation": workflow_generation,
        },
    )


def verify_hotel_price(
    selected_hotel: dict[str, Any],
    max_price: int,
    check_in: date,
    check_out: date,
) -> PriceCheckResult:
    del check_in, check_out
    original_price = int(selected_hotel["nightly_price"])
    return PriceCheckResult(
        hotel_id=str(selected_hotel["hotel_id"]),
        status="UNCHANGED",
        original_price=original_price,
        current_price=original_price,
        policy_compliant=original_price <= max_price,
        requires_confirmation=False,
        payload={
            "selected_hotel": selected_hotel,
            "max_price": max_price,
        },
    )


def create_order(
    session_id: str,
    user_id: str,
    request: dict[str, Any],
    itinerary: dict[str, Any],
    selected_hotel: dict[str, Any],
    approval: dict[str, Any],
    inventory_lock: dict[str, Any],
    workflow_generation: int = 1,
) -> TravelOrder:
    order_id = "ORD-" + uuid5(
        NAMESPACE_URL,
        f"{session_id}:{workflow_generation}:{user_id}:{inventory_lock['lock_id']}",
    ).hex[:10].upper()
    nights = _nights(itinerary["check_in"], itinerary["check_out"])
    total_amount = int(selected_hotel["nightly_price"]) * nights
    return TravelOrder(
        order_id=order_id,
        status="CREATED",
        total_amount=total_amount,
        currency="CNY",
        payload={
            "session_id": session_id,
            "user_id": user_id,
            "request": request,
            "itinerary": itinerary,
            "selected_hotel": selected_hotel,
            "approval": approval,
            "inventory_lock": inventory_lock,
            "workflow_generation": workflow_generation,
        },
    )


def create_transport_order(
    session_id: str,
    user_id: str,
    request: dict[str, Any],
    selected_transport: dict[str, Any],
    approval: dict[str, Any],
    workflow_generation: int = 1,
) -> TransportOrder:
    order_id = "TORD-" + uuid5(
        NAMESPACE_URL,
        f"{session_id}:{workflow_generation}:{user_id}:{selected_transport['transport_id']}",
    ).hex[:10].upper()
    return TransportOrder(
        order_id=order_id,
        status="CREATED",
        total_amount=int(selected_transport["price"]),
        currency="CNY",
        payload={
            "session_id": session_id,
            "user_id": user_id,
            "request": request,
            "selected_transport": selected_transport,
            "approval": approval,
            "workflow_generation": workflow_generation,
        },
    )


def get_order_status(order_id: str, user_id: str) -> TravelOrder:
    return TravelOrder(
        order_id=order_id,
        status="CONFIRMED",
        total_amount=0,
        currency="CNY",
        payload={
            "order_id": order_id,
            "user_id": user_id,
            "status_detail": "Confirmed by mock order workflow.",
        },
    )


def get_transport_order_status(order_id: str, user_id: str) -> TransportOrder:
    return TransportOrder(
        order_id=order_id,
        status="CONFIRMED",
        total_amount=0,
        currency="CNY",
        payload={
            "order_id": order_id,
            "user_id": user_id,
            "status_detail": "Confirmed by mock transport workflow.",
        },
    )


def cancel_order(order_id: str, user_id: str, reason: str) -> CompensationResult:
    return CompensationResult(
        action="cancel_order",
        target_id=order_id,
        status="CANCELLED",
        payload={
            "order_id": order_id,
            "user_id": user_id,
            "reason": reason,
            "refund_status": "PENDING",
        },
    )


def cancel_transport_order(order_id: str, user_id: str, reason: str) -> CompensationResult:
    return CompensationResult(
        action="cancel_transport_order",
        target_id=order_id,
        status="CANCELLED",
        payload={
            "order_id": order_id,
            "user_id": user_id,
            "reason": reason,
            "refund_status": "PENDING",
        },
    )


def release_hotel_inventory(lock_id: str, user_id: str, reason: str) -> CompensationResult:
    return CompensationResult(
        action="release_hotel_inventory",
        target_id=lock_id,
        status="RELEASED",
        payload={
            "lock_id": lock_id,
            "user_id": user_id,
            "reason": reason,
        },
    )


def send_notification(
    session_id: str,
    user_id: str,
    event_type: str,
    title: str,
    message: str,
    channel: str,
    payload: dict[str, Any],
    workflow_generation: int = 1,
) -> NotificationRecord:
    notification_id = "NTF-" + uuid5(
        NAMESPACE_URL,
        f"{session_id}:{workflow_generation}:{user_id}:{event_type}",
    ).hex[:10].upper()
    return NotificationRecord(
        notification_id=notification_id,
        event_type=event_type,
        channel=channel,
        recipient_id=user_id,
        title=title,
        message=message,
        status="SENT",
        payload={
            "session_id": session_id,
            "user_id": user_id,
            "event_type": event_type,
            "title": title,
            "message": message,
            "channel": channel,
            "workflow_generation": workflow_generation,
            "payload": payload,
        },
    )


def _default_city_inventory(city: str) -> list[HotelOption]:
    return [
        HotelOption(f"{city}-001", f"{city}商务酒店", city, "会场周边 1 号", 480, 1.2, 4.4, True, True),
        HotelOption(f"{city}-002", f"{city}会议中心酒店", city, "会场周边 2 号", 520, 2.0, 4.5, True, True),
        HotelOption(f"{city}-003", f"{city}行政酒店", city, "市中心 3 号", 680, 6.5, 4.7, False, False),
    ]


def _default_transport_inventory(origin_city: str, destination_city: str, travel_date: date) -> list[TransportOption]:
    day = travel_date.isoformat()
    return [
        TransportOption(
            f"TRN-{origin_city}-{destination_city}-001",
            "train",
            "高铁",
            origin_city,
            destination_city,
            f"{day}T08:30:00+08:00",
            f"{day}T13:10:00+08:00",
            "二等座",
            520,
            True,
            True,
        ),
        TransportOption(
            f"FLT-{origin_city}-{destination_city}-002",
            "flight",
            "航司",
            origin_city,
            destination_city,
            f"{day}T10:20:00+08:00",
            f"{day}T12:30:00+08:00",
            "经济舱",
            980,
            True,
            True,
        ),
    ]


def _with_date(value: str, travel_date: date) -> str:
    if "T" not in value:
        return f"{travel_date.isoformat()}T{value}"
    return f"{travel_date.isoformat()}T{value.split('T', 1)[1]}"


def _nights(check_in: date | str, check_out: date | str) -> int:
    start = check_in if isinstance(check_in, date) else date.fromisoformat(check_in)
    end = check_out if isinstance(check_out, date) else date.fromisoformat(check_out)
    return max(1, (end - start).days)
