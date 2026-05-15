from __future__ import annotations

import json
from dataclasses import replace
from datetime import date
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from . import mock_tools
from .config import IntegrationSettings
from .models import (
    ApprovalRecord,
    CompensationResult,
    HotelOption,
    InventoryLock,
    NotificationRecord,
    PolicyResult,
    PriceCheckResult,
    TravelOrder,
    TransportOption,
    TransportOrder,
    TransportPolicyResult,
)


class IntegrationError(RuntimeError):
    pass


class HttpJsonClient(Protocol):
    def post_json(self, url: str, payload: dict[str, Any], token: str | None = None) -> dict[str, Any]:
        ...


class JsonHttpClient:
    def __init__(self, timeout_seconds: float = 5.0) -> None:
        self.timeout_seconds = timeout_seconds

    def post_json(self, url: str, payload: dict[str, Any], token: str | None = None) -> dict[str, Any]:
        body = json.dumps(payload, ensure_ascii=False, default=_json_default).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"

        request = Request(url=url, data=body, headers=headers, method="POST")
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise IntegrationError(f"HTTP {exc.code} from {url}: {detail}") from exc
        except URLError as exc:
            raise IntegrationError(f"Cannot reach {url}: {exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise IntegrationError(f"Invalid JSON response from {url}: {exc}") from exc


class TravelSystemIntegrations:
    def __init__(
        self,
        settings: IntegrationSettings | None = None,
        http_client: HttpJsonClient | None = None,
    ) -> None:
        self.settings = settings or IntegrationSettings.from_env()
        self.http_client = http_client or JsonHttpClient(self.settings.timeout_seconds)

    def check_policy(
        self,
        user_id: str,
        destination_city: str,
        budget_per_night: int | None = None,
    ) -> PolicyResult:
        payload = {
            "user_id": user_id,
            "destination_city": destination_city,
            "budget_per_night": budget_per_night,
        }
        if self.settings.policy_api_url:
            try:
                response = self.http_client.post_json(
                    self.settings.policy_api_url,
                    payload,
                    self.settings.policy_api_token,
                )
                return self._parse_policy_response(response, budget_per_night, source="real")
            except Exception as exc:
                return self._fallback_policy(user_id, destination_city, budget_per_night, exc)

        return self._fallback_policy(user_id, destination_city, budget_per_night, None)

    def check_transport_policy(
        self,
        user_id: str,
        origin_city: str,
        destination_city: str,
        travel_date: date,
    ) -> TransportPolicyResult:
        payload = {
            "user_id": user_id,
            "origin_city": origin_city,
            "destination_city": destination_city,
            "travel_date": travel_date,
        }
        if self.settings.transport_policy_api_url:
            try:
                response = self.http_client.post_json(
                    self.settings.transport_policy_api_url,
                    payload,
                    self.settings.transport_api_token,
                )
                return self._parse_transport_policy_response(response, source="real")
            except Exception as exc:
                return self._fallback_transport_policy(user_id, origin_city, destination_city, travel_date, exc)

        return self._fallback_transport_policy(user_id, origin_city, destination_city, travel_date, None)

    def search_hotels(
        self,
        city: str,
        check_in: date,
        check_out: date,
        venue: str,
        max_price: int,
        preferences: list[str] | None = None,
    ) -> list[HotelOption]:
        payload = {
            "city": city,
            "check_in": check_in,
            "check_out": check_out,
            "venue": venue,
            "max_price": max_price,
            "preferences": preferences or [],
        }
        if self.settings.hotel_inventory_api_url:
            try:
                response = self.http_client.post_json(
                    self.settings.hotel_inventory_api_url,
                    payload,
                    self.settings.hotel_inventory_api_token,
                )
                return self._parse_hotel_response(response, max_price, source="real")
            except Exception as exc:
                return self._fallback_hotels(city, check_in, check_out, venue, max_price, preferences, exc)

        return self._fallback_hotels(city, check_in, check_out, venue, max_price, preferences, None)

    def search_transport(
        self,
        origin_city: str,
        destination_city: str,
        travel_date: date,
        max_price: int,
        preferences: list[str] | None = None,
    ) -> list[TransportOption]:
        payload = {
            "origin_city": origin_city,
            "destination_city": destination_city,
            "travel_date": travel_date,
            "max_price": max_price,
            "preferences": preferences or [],
        }
        if self.settings.transport_inventory_api_url:
            try:
                response = self.http_client.post_json(
                    self.settings.transport_inventory_api_url,
                    payload,
                    self.settings.transport_api_token,
                )
                return self._parse_transport_response(response, max_price, source="real")
            except Exception as exc:
                return self._fallback_transport(origin_city, destination_city, travel_date, max_price, preferences, exc)

        return self._fallback_transport(origin_city, destination_city, travel_date, max_price, preferences, None)

    def create_approval(
        self,
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
        payload = {
            "session_id": session_id,
            "user_id": user_id,
            "request": request,
            "policy": policy,
            "transport_policy": transport_policy or {},
            "itinerary": itinerary,
            "selected_hotel": selected_hotel,
            "selected_transport": selected_transport or {},
            "workflow_generation": workflow_generation,
            "idempotency_key": f"travel-approval:{session_id}:{workflow_generation}:{user_id}",
        }
        if self.settings.oa_approval_api_url:
            try:
                response = self.http_client.post_json(
                    self.settings.oa_approval_api_url,
                    payload,
                    self.settings.oa_approval_api_token,
                )
                return self._parse_approval_response(response, payload, source="real")
            except Exception as exc:
                return self._fallback_approval(payload, exc)

        return self._fallback_approval(payload, None)

    def get_approval_status(self, approval_id: str, user_id: str) -> ApprovalRecord:
        payload = {
            "approval_id": approval_id,
            "user_id": user_id,
        }
        if self.settings.oa_approval_status_api_url:
            try:
                response = self.http_client.post_json(
                    self.settings.oa_approval_status_api_url,
                    payload,
                    self.settings.oa_approval_api_token,
                )
                return self._parse_approval_response(response, payload, source="real")
            except Exception as exc:
                return self._fallback_approval_status(approval_id, user_id, exc)

        return self._fallback_approval_status(approval_id, user_id, None)

    def cancel_approval(self, approval_id: str, user_id: str, reason: str) -> CompensationResult:
        payload = {
            "approval_id": approval_id,
            "user_id": user_id,
            "reason": reason,
            "idempotency_key": f"cancel-approval:{approval_id}:{user_id}",
        }
        if self.settings.oa_approval_cancel_api_url:
            try:
                response = self.http_client.post_json(
                    self.settings.oa_approval_cancel_api_url,
                    payload,
                    self.settings.oa_approval_api_token,
                )
                return self._parse_compensation_response(response, payload, "cancel_approval", approval_id, source="real")
            except Exception as exc:
                return self._fallback_cancel_approval(approval_id, user_id, reason, exc)

        return self._fallback_cancel_approval(approval_id, user_id, reason, None)

    def lock_hotel_inventory(
        self,
        session_id: str,
        user_id: str,
        selected_hotel: dict[str, Any],
        check_in: date,
        check_out: date,
        workflow_generation: int = 1,
    ) -> InventoryLock:
        payload = {
            "session_id": session_id,
            "user_id": user_id,
            "selected_hotel": selected_hotel,
            "check_in": check_in,
            "check_out": check_out,
            "workflow_generation": workflow_generation,
            "idempotency_key": f"hotel-lock:{session_id}:{workflow_generation}:{selected_hotel['hotel_id']}",
        }
        if self.settings.hotel_inventory_lock_api_url:
            try:
                response = self.http_client.post_json(
                    self.settings.hotel_inventory_lock_api_url,
                    payload,
                    self.settings.hotel_inventory_api_token,
                )
                return self._parse_inventory_lock_response(response, payload, source="real")
            except Exception as exc:
                return self._fallback_inventory_lock(
                    session_id,
                    user_id,
                    selected_hotel,
                    check_in,
                    check_out,
                    workflow_generation,
                    exc,
                )

        return self._fallback_inventory_lock(
            session_id,
            user_id,
            selected_hotel,
            check_in,
            check_out,
            workflow_generation,
            None,
        )

    def verify_hotel_price(
        self,
        selected_hotel: dict[str, Any],
        max_price: int,
        check_in: date,
        check_out: date,
    ) -> PriceCheckResult:
        payload = {
            "selected_hotel": selected_hotel,
            "max_price": max_price,
            "check_in": check_in,
            "check_out": check_out,
        }
        if self.settings.hotel_price_check_api_url:
            try:
                response = self.http_client.post_json(
                    self.settings.hotel_price_check_api_url,
                    payload,
                    self.settings.hotel_inventory_api_token,
                )
                return self._parse_price_check_response(response, payload, source="real")
            except Exception as exc:
                return self._fallback_price_check(selected_hotel, max_price, check_in, check_out, exc)

        return self._fallback_price_check(selected_hotel, max_price, check_in, check_out, None)

    def create_order(
        self,
        session_id: str,
        user_id: str,
        request: dict[str, Any],
        itinerary: dict[str, Any],
        selected_hotel: dict[str, Any],
        approval: dict[str, Any],
        inventory_lock: dict[str, Any],
        workflow_generation: int = 1,
    ) -> TravelOrder:
        payload = {
            "session_id": session_id,
            "user_id": user_id,
            "request": request,
            "itinerary": itinerary,
            "selected_hotel": selected_hotel,
            "approval": approval,
            "inventory_lock": inventory_lock,
            "workflow_generation": workflow_generation,
            "idempotency_key": f"travel-order:{session_id}:{workflow_generation}:{inventory_lock['lock_id']}",
        }
        if self.settings.order_api_url:
            try:
                response = self.http_client.post_json(
                    self.settings.order_api_url,
                    payload,
                    self.settings.order_api_token,
                )
                return self._parse_order_response(response, payload, source="real")
            except Exception as exc:
                return self._fallback_order(payload, exc)

        return self._fallback_order(payload, None)

    def get_order_status(self, order_id: str, user_id: str) -> TravelOrder:
        payload = {
            "order_id": order_id,
            "user_id": user_id,
        }
        if self.settings.order_status_api_url:
            try:
                response = self.http_client.post_json(
                    self.settings.order_status_api_url,
                    payload,
                    self.settings.order_api_token,
                )
                return self._parse_order_response(response, payload, source="real")
            except Exception as exc:
                return self._fallback_order_status(order_id, user_id, exc)

        return self._fallback_order_status(order_id, user_id, None)

    def create_transport_order(
        self,
        session_id: str,
        user_id: str,
        request: dict[str, Any],
        selected_transport: dict[str, Any],
        approval: dict[str, Any],
        workflow_generation: int = 1,
    ) -> TransportOrder:
        payload = {
            "session_id": session_id,
            "user_id": user_id,
            "request": request,
            "selected_transport": selected_transport,
            "approval": approval,
            "workflow_generation": workflow_generation,
            "idempotency_key": f"transport-order:{session_id}:{workflow_generation}:{selected_transport['transport_id']}",
        }
        if self.settings.transport_order_api_url:
            try:
                response = self.http_client.post_json(
                    self.settings.transport_order_api_url,
                    payload,
                    self.settings.transport_api_token,
                )
                return self._parse_transport_order_response(response, payload, source="real")
            except Exception as exc:
                return self._fallback_transport_order(payload, exc)

        return self._fallback_transport_order(payload, None)

    def get_transport_order_status(self, order_id: str, user_id: str) -> TransportOrder:
        payload = {
            "order_id": order_id,
            "user_id": user_id,
        }
        if self.settings.transport_order_status_api_url:
            try:
                response = self.http_client.post_json(
                    self.settings.transport_order_status_api_url,
                    payload,
                    self.settings.transport_api_token,
                )
                return self._parse_transport_order_response(response, payload, source="real")
            except Exception as exc:
                return self._fallback_transport_order_status(order_id, user_id, exc)

        return self._fallback_transport_order_status(order_id, user_id, None)

    def cancel_transport_order(self, order_id: str, user_id: str, reason: str) -> CompensationResult:
        payload = {
            "order_id": order_id,
            "user_id": user_id,
            "reason": reason,
            "idempotency_key": f"cancel-transport-order:{order_id}:{user_id}",
        }
        if self.settings.transport_order_cancel_api_url:
            try:
                response = self.http_client.post_json(
                    self.settings.transport_order_cancel_api_url,
                    payload,
                    self.settings.transport_api_token,
                )
                return self._parse_compensation_response(
                    response,
                    payload,
                    "cancel_transport_order",
                    order_id,
                    source="real",
                )
            except Exception as exc:
                return self._fallback_cancel_transport_order(order_id, user_id, reason, exc)

        return self._fallback_cancel_transport_order(order_id, user_id, reason, None)

    def cancel_order(self, order_id: str, user_id: str, reason: str) -> CompensationResult:
        payload = {
            "order_id": order_id,
            "user_id": user_id,
            "reason": reason,
            "idempotency_key": f"cancel-order:{order_id}:{user_id}",
        }
        if self.settings.order_cancel_api_url:
            try:
                response = self.http_client.post_json(
                    self.settings.order_cancel_api_url,
                    payload,
                    self.settings.order_api_token,
                )
                return self._parse_compensation_response(response, payload, "cancel_order", order_id, source="real")
            except Exception as exc:
                return self._fallback_cancel_order(order_id, user_id, reason, exc)

        return self._fallback_cancel_order(order_id, user_id, reason, None)

    def release_hotel_inventory(self, lock_id: str, user_id: str, reason: str) -> CompensationResult:
        payload = {
            "lock_id": lock_id,
            "user_id": user_id,
            "reason": reason,
            "idempotency_key": f"release-hotel-lock:{lock_id}:{user_id}",
        }
        if self.settings.hotel_inventory_release_api_url:
            try:
                response = self.http_client.post_json(
                    self.settings.hotel_inventory_release_api_url,
                    payload,
                    self.settings.hotel_inventory_api_token,
                )
                return self._parse_compensation_response(
                    response,
                    payload,
                    "release_hotel_inventory",
                    lock_id,
                    source="real",
                )
            except Exception as exc:
                return self._fallback_release_inventory(lock_id, user_id, reason, exc)

        return self._fallback_release_inventory(lock_id, user_id, reason, None)

    def send_notification(
        self,
        session_id: str,
        user_id: str,
        event_type: str,
        title: str,
        message: str,
        channel: str,
        payload: dict[str, Any],
        workflow_generation: int = 1,
    ) -> NotificationRecord:
        request_payload = {
            "session_id": session_id,
            "user_id": user_id,
            "event_type": event_type,
            "title": title,
            "message": message,
            "channel": channel,
            "workflow_generation": workflow_generation,
            "payload": payload,
            "idempotency_key": f"notification:{session_id}:{workflow_generation}:{event_type}",
        }
        if self.settings.notification_api_url:
            try:
                response = self.http_client.post_json(
                    self.settings.notification_api_url,
                    request_payload,
                    self.settings.notification_api_token,
                )
                return self._parse_notification_response(response, request_payload, source="real")
            except Exception as exc:
                return self._fallback_notification(request_payload, exc)

        return self._fallback_notification(request_payload, None)

    def _fallback_policy(
        self,
        user_id: str,
        destination_city: str,
        budget_per_night: int | None,
        exc: Exception | None,
    ) -> PolicyResult:
        self._ensure_fallback_allowed("policy", exc)
        policy = mock_tools.check_policy(user_id, destination_city, budget_per_night)
        if exc is None:
            return policy
        return replace(
            policy,
            source="mock_fallback",
            reasons=policy.reasons + [f"Policy system unavailable, used mock fallback: {exc}"],
        )

    def _fallback_transport_policy(
        self,
        user_id: str,
        origin_city: str,
        destination_city: str,
        travel_date: date,
        exc: Exception | None,
    ) -> TransportPolicyResult:
        self._ensure_fallback_allowed("transport policy", exc)
        policy = mock_tools.check_transport_policy(user_id, origin_city, destination_city, travel_date)
        if exc is None:
            return policy
        return replace(
            policy,
            source="mock_fallback",
            reasons=policy.reasons + [f"Transport policy system unavailable, used mock fallback: {exc}"],
        )

    def _fallback_hotels(
        self,
        city: str,
        check_in: date,
        check_out: date,
        venue: str,
        max_price: int,
        preferences: list[str] | None,
        exc: Exception | None,
    ) -> list[HotelOption]:
        self._ensure_fallback_allowed("hotel inventory", exc)
        hotels = mock_tools.search_hotels(city, check_in, check_out, venue, max_price, preferences)
        if exc is None:
            return hotels
        return [replace(hotel, source="mock_fallback") for hotel in hotels]

    def _fallback_transport(
        self,
        origin_city: str,
        destination_city: str,
        travel_date: date,
        max_price: int,
        preferences: list[str] | None,
        exc: Exception | None,
    ) -> list[TransportOption]:
        self._ensure_fallback_allowed("transport inventory", exc)
        options = mock_tools.search_transport(origin_city, destination_city, travel_date, max_price, preferences)
        if exc is None:
            return options
        return [replace(option, source="mock_fallback") for option in options]

    def _fallback_approval(self, payload: dict[str, Any], exc: Exception | None) -> ApprovalRecord:
        self._ensure_fallback_allowed("OA approval", exc)
        fallback_payload = dict(payload)
        if exc is not None:
            fallback_payload["fallback_reason"] = f"OA approval system unavailable, used mock fallback: {exc}"
        approval = mock_tools.create_approval(
            session_id=fallback_payload["session_id"],
            user_id=fallback_payload["user_id"],
            request=fallback_payload["request"],
            policy=fallback_payload["policy"],
            itinerary=fallback_payload["itinerary"],
            selected_hotel=fallback_payload["selected_hotel"],
            transport_policy=fallback_payload.get("transport_policy"),
            selected_transport=fallback_payload.get("selected_transport"),
            workflow_generation=int(fallback_payload.get("workflow_generation", 1)),
        )
        if exc is None:
            return approval
        return replace(
            approval,
            source="mock_fallback",
            payload={**approval.payload, "fallback_reason": fallback_payload["fallback_reason"]},
        )

    def _fallback_approval_status(
        self,
        approval_id: str,
        user_id: str,
        exc: Exception | None,
    ) -> ApprovalRecord:
        self._ensure_fallback_allowed("OA approval status", exc)
        approval = mock_tools.get_approval_status(approval_id, user_id)
        if exc is None:
            return approval
        return replace(
            approval,
            source="mock_fallback",
            payload={
                **approval.payload,
                "fallback_reason": f"OA approval status system unavailable, used mock fallback: {exc}",
            },
        )

    def _fallback_cancel_approval(
        self,
        approval_id: str,
        user_id: str,
        reason: str,
        exc: Exception | None,
    ) -> CompensationResult:
        self._ensure_fallback_allowed("OA approval cancellation", exc)
        result = mock_tools.cancel_approval(approval_id, user_id, reason)
        if exc is None:
            return result
        return replace(
            result,
            source="mock_fallback",
            payload={
                **result.payload,
                "fallback_reason": f"OA approval cancellation system unavailable, used mock fallback: {exc}",
            },
        )

    def _fallback_inventory_lock(
        self,
        session_id: str,
        user_id: str,
        selected_hotel: dict[str, Any],
        check_in: date,
        check_out: date,
        workflow_generation: int,
        exc: Exception | None,
    ) -> InventoryLock:
        self._ensure_fallback_allowed("hotel inventory lock", exc)
        lock = mock_tools.lock_hotel_inventory(
            session_id,
            user_id,
            selected_hotel,
            check_in,
            check_out,
            workflow_generation,
        )
        if exc is None:
            return lock
        return replace(
            lock,
            source="mock_fallback",
            payload={
                **lock.payload,
                "fallback_reason": f"Hotel inventory lock system unavailable, used mock fallback: {exc}",
            },
        )

    def _fallback_price_check(
        self,
        selected_hotel: dict[str, Any],
        max_price: int,
        check_in: date,
        check_out: date,
        exc: Exception | None,
    ) -> PriceCheckResult:
        self._ensure_fallback_allowed("hotel price check", exc)
        result = mock_tools.verify_hotel_price(selected_hotel, max_price, check_in, check_out)
        if exc is None:
            return result
        return replace(
            result,
            source="mock_fallback",
            payload={
                **result.payload,
                "fallback_reason": f"Hotel price check system unavailable, used mock fallback: {exc}",
            },
        )

    def _fallback_order(self, payload: dict[str, Any], exc: Exception | None) -> TravelOrder:
        self._ensure_fallback_allowed("order", exc)
        fallback_payload = dict(payload)
        if exc is not None:
            fallback_payload["fallback_reason"] = f"Order system unavailable, used mock fallback: {exc}"
        order = mock_tools.create_order(
            session_id=fallback_payload["session_id"],
            user_id=fallback_payload["user_id"],
            request=fallback_payload["request"],
            itinerary=fallback_payload["itinerary"],
            selected_hotel=fallback_payload["selected_hotel"],
            approval=fallback_payload["approval"],
            inventory_lock=fallback_payload["inventory_lock"],
            workflow_generation=int(fallback_payload.get("workflow_generation", 1)),
        )
        if exc is None:
            return order
        return replace(
            order,
            source="mock_fallback",
            payload={**order.payload, "fallback_reason": fallback_payload["fallback_reason"]},
        )

    def _fallback_order_status(
        self,
        order_id: str,
        user_id: str,
        exc: Exception | None,
    ) -> TravelOrder:
        self._ensure_fallback_allowed("order status", exc)
        result = mock_tools.get_order_status(order_id, user_id)
        if exc is None:
            return result
        return replace(
            result,
            source="mock_fallback",
            payload={
                **result.payload,
                "fallback_reason": f"Order status system unavailable, used mock fallback: {exc}",
            },
        )

    def _fallback_transport_order(self, payload: dict[str, Any], exc: Exception | None) -> TransportOrder:
        self._ensure_fallback_allowed("transport order", exc)
        fallback_payload = dict(payload)
        if exc is not None:
            fallback_payload["fallback_reason"] = f"Transport order system unavailable, used mock fallback: {exc}"
        order = mock_tools.create_transport_order(
            session_id=fallback_payload["session_id"],
            user_id=fallback_payload["user_id"],
            request=fallback_payload["request"],
            selected_transport=fallback_payload["selected_transport"],
            approval=fallback_payload["approval"],
            workflow_generation=int(fallback_payload.get("workflow_generation", 1)),
        )
        if exc is None:
            return order
        return replace(
            order,
            source="mock_fallback",
            payload={**order.payload, "fallback_reason": fallback_payload["fallback_reason"]},
        )

    def _fallback_transport_order_status(
        self,
        order_id: str,
        user_id: str,
        exc: Exception | None,
    ) -> TransportOrder:
        self._ensure_fallback_allowed("transport order status", exc)
        result = mock_tools.get_transport_order_status(order_id, user_id)
        if exc is None:
            return result
        return replace(
            result,
            source="mock_fallback",
            payload={
                **result.payload,
                "fallback_reason": f"Transport order status system unavailable, used mock fallback: {exc}",
            },
        )

    def _fallback_cancel_order(
        self,
        order_id: str,
        user_id: str,
        reason: str,
        exc: Exception | None,
    ) -> CompensationResult:
        self._ensure_fallback_allowed("order cancellation", exc)
        result = mock_tools.cancel_order(order_id, user_id, reason)
        if exc is None:
            return result
        return replace(
            result,
            source="mock_fallback",
            payload={
                **result.payload,
                "fallback_reason": f"Order cancellation system unavailable, used mock fallback: {exc}",
            },
        )

    def _fallback_cancel_transport_order(
        self,
        order_id: str,
        user_id: str,
        reason: str,
        exc: Exception | None,
    ) -> CompensationResult:
        self._ensure_fallback_allowed("transport order cancellation", exc)
        result = mock_tools.cancel_transport_order(order_id, user_id, reason)
        if exc is None:
            return result
        return replace(
            result,
            source="mock_fallback",
            payload={
                **result.payload,
                "fallback_reason": f"Transport order cancellation system unavailable, used mock fallback: {exc}",
            },
        )

    def _fallback_release_inventory(
        self,
        lock_id: str,
        user_id: str,
        reason: str,
        exc: Exception | None,
    ) -> CompensationResult:
        self._ensure_fallback_allowed("hotel inventory release", exc)
        result = mock_tools.release_hotel_inventory(lock_id, user_id, reason)
        if exc is None:
            return result
        return replace(
            result,
            source="mock_fallback",
            payload={
                **result.payload,
                "fallback_reason": f"Hotel inventory release system unavailable, used mock fallback: {exc}",
            },
        )

    def _fallback_notification(
        self,
        payload: dict[str, Any],
        exc: Exception | None,
    ) -> NotificationRecord:
        if not self.settings.notification_use_mock_fallback:
            if exc is None:
                raise IntegrationError("notification API URL is not configured and notification mock fallback is disabled.")
            raise IntegrationError(f"notification integration failed and notification mock fallback is disabled: {exc}") from exc
        self._ensure_fallback_allowed("notification", exc)
        result = mock_tools.send_notification(
            session_id=payload["session_id"],
            user_id=payload["user_id"],
            event_type=payload["event_type"],
            title=payload["title"],
            message=payload["message"],
            channel=payload["channel"],
            payload=payload["payload"],
            workflow_generation=int(payload.get("workflow_generation", 1)),
        )
        if exc is None:
            return result
        return replace(
            result,
            source="mock_fallback",
            payload={
                **result.payload,
                "fallback_reason": f"Notification system unavailable, used mock fallback: {exc}",
            },
        )

    def _ensure_fallback_allowed(self, system_name: str, exc: Exception | None) -> None:
        if self.settings.use_mock_fallback:
            return
        if exc is None:
            raise IntegrationError(f"{system_name} API URL is not configured and mock fallback is disabled.")
        raise IntegrationError(f"{system_name} integration failed and mock fallback is disabled: {exc}") from exc

    @staticmethod
    def _parse_policy_response(
        response: dict[str, Any],
        requested_budget: int | None,
        source: str,
    ) -> PolicyResult:
        body = _unwrap(response, "policy")
        raw_cap = _first_present(body, "max_hotel_price", "hotel_budget_cap", "cap", default=None)
        raw_approved = _first_present(
            body,
            "approved_budget",
            "approved_hotel_budget",
            default=None,
        )
        cap = int(raw_cap if raw_cap is not None else raw_approved)
        approved_budget = int(
            raw_approved if raw_approved is not None else cap if requested_budget is None else min(requested_budget, cap)
        )
        compliant = bool(body.get("compliant", requested_budget is None or requested_budget <= cap))
        reasons = body.get("reasons", [])
        if isinstance(reasons, str):
            reasons = [reasons]
        if not reasons:
            reasons = ["Policy returned by enterprise policy system."]
        return PolicyResult(
            policy_id=str(body.get("policy_id") or body.get("id") or "POLICY-REMOTE"),
            max_hotel_price=cap,
            approved_budget=approved_budget,
            compliant=compliant,
            reasons=list(reasons),
            source=source,
        )

    @staticmethod
    def _parse_transport_policy_response(
        response: dict[str, Any],
        source: str,
    ) -> TransportPolicyResult:
        body = _unwrap(response, "transport_policy")
        allowed = body.get("allowed_seat_classes") or body.get("seat_classes") or ["二等座", "经济舱"]
        if isinstance(allowed, str):
            allowed = [allowed]
        cap = int(_first_present(body, "max_transport_price", "approved_transport_budget", "cap", default=1800))
        reasons = body.get("reasons", [])
        if isinstance(reasons, str):
            reasons = [reasons]
        if not reasons:
            reasons = ["Transport policy returned by enterprise policy system."]
        return TransportPolicyResult(
            policy_id=str(body.get("policy_id") or body.get("id") or "TRANSPORT-POLICY-REMOTE"),
            allowed_seat_classes=list(allowed),
            max_transport_price=cap,
            compliant=bool(body.get("compliant", True)),
            reasons=list(reasons),
            source=source,
        )

    @staticmethod
    def _parse_hotel_response(
        response: dict[str, Any],
        max_price: int,
        source: str,
    ) -> list[HotelOption]:
        records = _unwrap_list(response, "hotels")
        hotels = [
            HotelOption(
                hotel_id=str(_first_present(record, "hotel_id", "id")),
                name=str(_first_present(record, "name", "hotel_name")),
                city=str(record.get("city", "")),
                address=str(record.get("address", "")),
                nightly_price=int(_first_present(record, "nightly_price", "price_per_night", "price")),
                distance_km=float(_first_present(record, "distance_km", "distance", default=999.0)),
                rating=float(record.get("rating", 0.0)),
                refundable=bool(record.get("refundable", True)),
                policy_compliant=bool(
                    record.get(
                        "policy_compliant",
                        int(_first_present(record, "nightly_price", "price_per_night", "price")) <= max_price,
                    )
                ),
                source=source,
            )
            for record in records
        ]
        return sorted(
            hotels,
            key=lambda hotel: (
                not hotel.policy_compliant,
                hotel.distance_km,
                -hotel.rating,
                hotel.nightly_price,
            ),
        )

    @staticmethod
    def _parse_transport_response(
        response: dict[str, Any],
        max_price: int,
        source: str,
    ) -> list[TransportOption]:
        records = _unwrap_list(response, "transports")
        options = [
            TransportOption(
                transport_id=str(_first_present(record, "transport_id", "id", "offer_id")),
                mode=str(record.get("mode") or record.get("type") or "flight"),
                provider=str(record.get("provider") or record.get("carrier") or ""),
                origin_city=str(_first_present(record, "origin_city", "origin")),
                destination_city=str(_first_present(record, "destination_city", "destination")),
                depart_at=str(_first_present(record, "depart_at", "departure_time", "depart_time")),
                arrive_at=str(_first_present(record, "arrive_at", "arrival_time", "arrive_time")),
                seat_class=str(_first_present(record, "seat_class", "cabin", "class", default="经济舱")),
                price=int(_first_present(record, "price", "total_amount", "amount")),
                refundable=bool(record.get("refundable", True)),
                policy_compliant=bool(
                    record.get(
                        "policy_compliant",
                        int(_first_present(record, "price", "total_amount", "amount")) <= max_price,
                    )
                ),
                source=source,
            )
            for record in records
        ]
        return sorted(
            options,
            key=lambda option: (
                not option.policy_compliant,
                option.price,
                option.depart_at,
            ),
        )

    @staticmethod
    def _parse_approval_response(
        response: dict[str, Any],
        request_payload: dict[str, Any],
        source: str,
    ) -> ApprovalRecord:
        body = _unwrap(response, "approval")
        approval_id = body.get("approval_id") or body.get("id") or body.get("process_instance_id")
        if not approval_id:
            raise IntegrationError("OA approval response is missing approval_id.")
        status = str(body.get("status") or body.get("approval_status") or "PENDING_APPROVAL")
        return ApprovalRecord(
            approval_id=str(approval_id),
            status=status,
            payload=body.get("payload") or request_payload,
            source=source,
        )

    @staticmethod
    def _parse_inventory_lock_response(
        response: dict[str, Any],
        request_payload: dict[str, Any],
        source: str,
    ) -> InventoryLock:
        body = _unwrap(response, "inventory_lock")
        lock_id = body.get("lock_id") or body.get("id") or body.get("hold_id")
        if not lock_id:
            raise IntegrationError("Hotel inventory lock response is missing lock_id.")
        status = str(body.get("status") or body.get("lock_status") or "LOCKED")
        hotel_id = str(body.get("hotel_id") or request_payload["selected_hotel"]["hotel_id"])
        expires_at = str(body.get("expires_at") or body.get("expire_time") or "")
        return InventoryLock(
            lock_id=str(lock_id),
            status=status,
            hotel_id=hotel_id,
            expires_at=expires_at,
            payload=body.get("payload") or request_payload,
            source=source,
        )

    @staticmethod
    def _parse_price_check_response(
        response: dict[str, Any],
        request_payload: dict[str, Any],
        source: str,
    ) -> PriceCheckResult:
        body = _unwrap(response, "price_check")
        selected_hotel = request_payload["selected_hotel"]
        original_price = int(body.get("original_price") or selected_hotel["nightly_price"])
        current_price_value = body.get("current_price") or body.get("nightly_price") or body.get("price")
        current_price = int(current_price_value) if current_price_value is not None else original_price
        status = str(body.get("status") or ("PRICE_CHANGED" if current_price != original_price else "UNCHANGED"))
        policy_compliant = bool(body.get("policy_compliant", current_price <= int(request_payload["max_price"])))
        requires_confirmation = bool(
            body.get(
                "requires_confirmation",
                current_price != original_price or not policy_compliant,
            )
        )
        return PriceCheckResult(
            hotel_id=str(body.get("hotel_id") or selected_hotel["hotel_id"]),
            status=status,
            original_price=original_price,
            current_price=current_price,
            policy_compliant=policy_compliant,
            requires_confirmation=requires_confirmation,
            payload=body.get("payload") or request_payload,
            source=source,
        )

    @staticmethod
    def _parse_order_response(
        response: dict[str, Any],
        request_payload: dict[str, Any],
        source: str,
    ) -> TravelOrder:
        body = _unwrap(response, "order")
        order_id = body.get("order_id") or body.get("id") or body.get("order_no")
        if not order_id:
            raise IntegrationError("Order response is missing order_id.")
        status = str(body.get("status") or body.get("order_status") or "CREATED")
        total_amount = int(body.get("total_amount") or _order_total(request_payload))
        currency = str(body.get("currency") or "CNY")
        return TravelOrder(
            order_id=str(order_id),
            status=status,
            total_amount=total_amount,
            currency=currency,
            payload=body.get("payload") or request_payload,
            source=source,
        )

    @staticmethod
    def _parse_transport_order_response(
        response: dict[str, Any],
        request_payload: dict[str, Any],
        source: str,
    ) -> TransportOrder:
        body = _unwrap(response, "transport_order")
        order_id = body.get("order_id") or body.get("id") or body.get("order_no")
        if not order_id:
            raise IntegrationError("Transport order response is missing order_id.")
        selected_transport = request_payload.get("selected_transport", {})
        status = str(body.get("status") or body.get("order_status") or "CREATED")
        total_amount = int(body.get("total_amount") or body.get("amount") or selected_transport.get("price", 0))
        currency = str(body.get("currency") or "CNY")
        return TransportOrder(
            order_id=str(order_id),
            status=status,
            total_amount=total_amount,
            currency=currency,
            payload=body.get("payload") or request_payload,
            source=source,
        )

    @staticmethod
    def _parse_compensation_response(
        response: dict[str, Any],
        request_payload: dict[str, Any],
        action: str,
        target_id: str,
        source: str,
    ) -> CompensationResult:
        body = _unwrap(response, "compensation")
        status = str(body.get("status") or body.get("result_status") or body.get("state") or "DONE")
        parsed_target_id = str(
            body.get("target_id")
            or body.get("order_id")
            or body.get("lock_id")
            or body.get("id")
            or target_id
        )
        return CompensationResult(
            action=str(body.get("action") or action),
            target_id=parsed_target_id,
            status=status,
            payload=body.get("payload") or request_payload,
            source=source,
        )

    @staticmethod
    def _parse_notification_response(
        response: dict[str, Any],
        request_payload: dict[str, Any],
        source: str,
    ) -> NotificationRecord:
        body = _unwrap(response, "notification")
        notification_id = body.get("notification_id") or body.get("id") or body.get("message_id")
        if not notification_id:
            raise IntegrationError("Notification response is missing notification_id.")
        return NotificationRecord(
            notification_id=str(notification_id),
            event_type=str(body.get("event_type") or request_payload["event_type"]),
            channel=str(body.get("channel") or request_payload["channel"]),
            recipient_id=str(body.get("recipient_id") or body.get("user_id") or request_payload["user_id"]),
            title=str(body.get("title") or request_payload["title"]),
            message=str(body.get("message") or request_payload["message"]),
            status=str(body.get("status") or body.get("send_status") or "SENT"),
            payload=body.get("payload") or request_payload,
            source=source,
            retry_count=int(body.get("retry_count") or 0),
            max_retries=int(body.get("max_retries") or 3),
            last_error=body.get("last_error"),
        )


def _json_default(value: Any) -> str:
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable.")


def _order_total(payload: dict[str, Any]) -> int:
    itinerary = payload["itinerary"]
    hotel = payload["selected_hotel"]
    check_in = itinerary["check_in"]
    check_out = itinerary["check_out"]
    start = check_in if isinstance(check_in, date) else date.fromisoformat(check_in)
    end = check_out if isinstance(check_out, date) else date.fromisoformat(check_out)
    nights = max(1, (end - start).days)
    return int(hotel["nightly_price"]) * nights


def _unwrap(response: dict[str, Any], key: str) -> dict[str, Any]:
    if key in response and isinstance(response[key], dict):
        return response[key]
    if "data" in response and isinstance(response["data"], dict):
        data = response["data"]
        if key in data and isinstance(data[key], dict):
            return data[key]
        return data
    return response


def _unwrap_list(response: dict[str, Any], key: str) -> list[dict[str, Any]]:
    candidate: Any = response
    if key in response:
        candidate = response[key]
    elif "data" in response:
        candidate = response["data"]
        if isinstance(candidate, dict):
            candidate = candidate.get(key) or candidate.get("items") or candidate.get("records")
    if not isinstance(candidate, list):
        raise IntegrationError(f"Expected list response for {key}.")
    return candidate


_MISSING = object()


def _first_present(body: dict[str, Any], *keys: str, default: Any = _MISSING) -> Any:
    for key in keys:
        if key in body and body[key] is not None:
            return body[key]
    if default is not _MISSING:
        return default
    raise IntegrationError(f"Missing required response field. Expected one of: {', '.join(keys)}")
