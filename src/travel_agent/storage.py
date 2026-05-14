from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any, Protocol

from .models import (
    ApprovalRecord,
    CompensationResult,
    HotelOption,
    InventoryLock,
    ItineraryPlan,
    NotificationRecord,
    PolicyResult,
    PriceCheckResult,
    Task,
    TaskPlan,
    TravelContext,
    TravelOrder,
    TravelRequest,
)


class SessionStore(Protocol):
    def save(self, context: TravelContext) -> None:
        ...

    def get(self, session_id: str) -> TravelContext:
        ...

    def list_by_states(self, states: set[str], limit: int = 50) -> list[TravelContext]:
        ...


class InMemorySessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, TravelContext] = {}

    def save(self, context: TravelContext) -> None:
        self._sessions[context.session_id] = context

    def get(self, session_id: str) -> TravelContext:
        return self._sessions[session_id]

    def list_by_states(self, states: set[str], limit: int = 50) -> list[TravelContext]:
        matches = [context for context in self._sessions.values() if context.state in states]
        return matches[:limit]


class SQLiteSessionStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def save(self, context: TravelContext) -> None:
        payload = json.dumps(context_to_dict(context), ensure_ascii=False, default=_json_default)
        with closing(sqlite3.connect(self.db_path)) as connection:
            connection.execute(
                """
                INSERT INTO travel_sessions(session_id, state, payload, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(session_id) DO UPDATE SET
                    state = excluded.state,
                    payload = excluded.payload,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (context.session_id, context.state, payload),
            )
            connection.commit()

    def get(self, session_id: str) -> TravelContext:
        with closing(sqlite3.connect(self.db_path)) as connection:
            row = connection.execute(
                "SELECT payload FROM travel_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if row is None:
            raise KeyError(session_id)
        return context_from_dict(json.loads(row[0]))

    def list_by_states(self, states: set[str], limit: int = 50) -> list[TravelContext]:
        if not states:
            return []
        placeholders = ", ".join("?" for _ in states)
        query = (
            "SELECT payload FROM travel_sessions "
            f"WHERE state IN ({placeholders}) "
            "ORDER BY updated_at ASC "
            "LIMIT ?"
        )
        with closing(sqlite3.connect(self.db_path)) as connection:
            rows = connection.execute(query, (*sorted(states), limit)).fetchall()
        return [context_from_dict(json.loads(row[0])) for row in rows]

    def _init_schema(self) -> None:
        with closing(sqlite3.connect(self.db_path)) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS travel_sessions (
                    session_id TEXT PRIMARY KEY,
                    state TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.commit()


def context_to_dict(context: TravelContext) -> dict[str, Any]:
    return asdict(context)


def context_from_dict(payload: dict[str, Any]) -> TravelContext:
    request = TravelRequest(
        user_id=payload["request"]["user_id"],
        origin_city=payload["request"]["origin_city"],
        destination_city=payload["request"]["destination_city"],
        start_date=_date(payload["request"]["start_date"]),
        end_date=_date(payload["request"]["end_date"]),
        purpose=payload["request"]["purpose"],
        venue=payload["request"]["venue"],
        budget_per_night=payload["request"].get("budget_per_night"),
        require_approval=payload["request"].get("require_approval", True),
        preferences=list(payload["request"].get("preferences", [])),
    )
    return TravelContext(
        session_id=payload["session_id"],
        request=request,
        state=payload["state"],
        task_plan=_task_plan(payload.get("task_plan")),
        policy_result=_optional(PolicyResult, payload.get("policy_result")),
        itinerary=_itinerary(payload.get("itinerary")),
        hotel_options=[HotelOption(**item) for item in payload.get("hotel_options", [])],
        selected_hotel=_optional(HotelOption, payload.get("selected_hotel")),
        approval=_optional(ApprovalRecord, payload.get("approval")),
        price_check=_optional(PriceCheckResult, payload.get("price_check")),
        inventory_lock=_optional(InventoryLock, payload.get("inventory_lock")),
        order=_optional(TravelOrder, payload.get("order")),
        order_cancellation=_optional(CompensationResult, payload.get("order_cancellation")),
        inventory_release=_optional(CompensationResult, payload.get("inventory_release")),
        notifications=[NotificationRecord(**item) for item in payload.get("notifications", [])],
        notification_keys=list(payload.get("notification_keys", [])),
        events=list(payload.get("events", [])),
    )


def _task_plan(payload: dict[str, Any] | None) -> TaskPlan | None:
    if payload is None:
        return None
    return TaskPlan(
        goal=payload["goal"],
        tasks=[Task(**task) for task in payload.get("tasks", [])],
    )


def _itinerary(payload: dict[str, Any] | None) -> ItineraryPlan | None:
    if payload is None:
        return None
    return ItineraryPlan(
        summary=payload["summary"],
        check_in=_date(payload["check_in"]),
        check_out=_date(payload["check_out"]),
        agenda=list(payload.get("agenda", [])),
    )


def _optional(model: type[Any], payload: dict[str, Any] | None) -> Any:
    if payload is None:
        return None
    return model(**payload)


def _date(value: date | str) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(value)


def _json_default(value: Any) -> str:
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable.")
