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
)


CITY_POLICY_CAPS = {
    "北京": 650,
    "上海": 650,
    "广州": 550,
    "深圳": 600,
    "杭州": 550,
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


def create_approval(
    session_id: str,
    user_id: str,
    request: dict[str, Any],
    policy: dict[str, Any],
    itinerary: dict[str, Any],
    selected_hotel: dict[str, Any],
) -> ApprovalRecord:
    approval_id = "APP-" + uuid5(NAMESPACE_URL, f"{session_id}:{user_id}").hex[:10].upper()
    return ApprovalRecord(
        approval_id=approval_id,
        status="PENDING_APPROVAL",
        payload={
            "session_id": session_id,
            "user_id": user_id,
            "request": request,
            "policy": policy,
            "itinerary": itinerary,
            "selected_hotel": selected_hotel,
        },
    )


def create_approval_draft(
    session_id: str,
    user_id: str,
    request: dict[str, Any],
    policy: dict[str, Any],
    itinerary: dict[str, Any],
    selected_hotel: dict[str, Any],
) -> ApprovalRecord:
    return create_approval(session_id, user_id, request, policy, itinerary, selected_hotel)


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


def lock_hotel_inventory(
    session_id: str,
    user_id: str,
    selected_hotel: dict[str, Any],
    check_in: date,
    check_out: date,
) -> InventoryLock:
    hotel_id = str(selected_hotel["hotel_id"])
    lock_id = "LOCK-" + uuid5(NAMESPACE_URL, f"{session_id}:{user_id}:{hotel_id}").hex[:10].upper()
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
) -> TravelOrder:
    order_id = "ORD-" + uuid5(NAMESPACE_URL, f"{session_id}:{user_id}:{inventory_lock['lock_id']}").hex[:10].upper()
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
) -> NotificationRecord:
    notification_id = "NTF-" + uuid5(NAMESPACE_URL, f"{session_id}:{user_id}:{event_type}").hex[:10].upper()
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
            "payload": payload,
        },
    )


def _default_city_inventory(city: str) -> list[HotelOption]:
    return [
        HotelOption(f"{city}-001", f"{city}商务酒店", city, "会场周边 1 号", 480, 1.2, 4.4, True, True),
        HotelOption(f"{city}-002", f"{city}会议中心酒店", city, "会场周边 2 号", 520, 2.0, 4.5, True, True),
        HotelOption(f"{city}-003", f"{city}行政酒店", city, "市中心 3 号", 680, 6.5, 4.7, False, False),
    ]


def _nights(check_in: date | str, check_out: date | str) -> int:
    start = check_in if isinstance(check_in, date) else date.fromisoformat(check_in)
    end = check_out if isinstance(check_out, date) else date.fromisoformat(check_out)
    return max(1, (end - start).days)
