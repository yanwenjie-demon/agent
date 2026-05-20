from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .models import (
    AgentExecutionRecord,
    ApprovalRecord,
    CalendarSyncRecord,
    ChangeRecord,
    CompensationResult,
    DeadLetterCalendarSync,
    DeadLetterNotification,
    HotelOption,
    InventoryLock,
    ItineraryPlan,
    NotificationRecord,
    PolicyResult,
    PriceCheckResult,
    RecoveryRecord,
    RefundConfirmationRecord,
    RefundEstimate,
    Task,
    TaskPlan,
    TravelContext,
    TravelOrder,
    TravelRequest,
    TransportOption,
    TransportOrder,
    TransportPolicyResult,
    WorkerRunRecord,
)


SQLITE_SCHEMA_VERSION = 4


class StoreConcurrencyError(RuntimeError):
    pass


@dataclass(frozen=True)
class StoredSession:
    context: TravelContext
    version: int
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class StorageHealth:
    backend: str
    ok: bool
    schema_version: int
    session_count: int
    worker_run_count: int
    details: dict[str, str]


class SessionStore(Protocol):
    def save(self, context: TravelContext) -> None:
        ...

    def get(self, session_id: str) -> TravelContext:
        ...

    def list_by_states(self, states: set[str], limit: int = 50) -> list[TravelContext]:
        ...

    def list_recent(self, limit: int = 50) -> list[TravelContext]:
        ...

    def record_worker_run(self, record: WorkerRunRecord) -> None:
        ...

    def list_worker_runs(self, limit: int = 20) -> list[WorkerRunRecord]:
        ...

    def list_dead_letter_notifications(self, limit: int = 50) -> list[DeadLetterNotification]:
        ...

    def list_dead_letter_calendar_syncs(self, limit: int = 50) -> list[DeadLetterCalendarSync]:
        ...

    def record_operations_dashboard_snapshot(self, snapshot: dict[str, Any]) -> None:
        ...

    def list_operations_dashboard_snapshots(self, limit: int = 20) -> list[dict[str, Any]]:
        ...

    def record_oncall_ticket_status(self, status: dict[str, Any]) -> None:
        ...

    def list_oncall_ticket_statuses(self, limit: int = 20) -> list[dict[str, Any]]:
        ...

    def record_operations_action_item(self, item: dict[str, Any]) -> None:
        ...

    def list_operations_action_items(self, limit: int = 20) -> list[dict[str, Any]]:
        ...

    def record_operations_knowledge_entry(self, entry: dict[str, Any]) -> None:
        ...

    def list_operations_knowledge_entries(self, limit: int = 20) -> list[dict[str, Any]]:
        ...

    def record_operations_trend_alert(self, alert: dict[str, Any]) -> None:
        ...

    def list_operations_trend_alerts(self, limit: int = 20) -> list[dict[str, Any]]:
        ...


class InMemorySessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, TravelContext] = {}
        self._worker_runs: list[WorkerRunRecord] = []
        self._dashboard_snapshots: list[dict[str, Any]] = []
        self._oncall_statuses: list[dict[str, Any]] = []
        self._operations_trend_alerts: list[dict[str, Any]] = []
        self._operations_action_items: list[dict[str, Any]] = []
        self._operations_knowledge_entries: list[dict[str, Any]] = []

    def save(self, context: TravelContext) -> None:
        self._sessions[context.session_id] = context

    def get(self, session_id: str) -> TravelContext:
        return self._sessions[session_id]

    def list_by_states(self, states: set[str], limit: int = 50) -> list[TravelContext]:
        matches = [context for context in self._sessions.values() if context.state in states]
        return matches[:limit]

    def list_recent(self, limit: int = 50) -> list[TravelContext]:
        return list(reversed(list(self._sessions.values())[-limit:]))

    def record_worker_run(self, record: WorkerRunRecord) -> None:
        self._worker_runs.append(record)

    def list_worker_runs(self, limit: int = 20) -> list[WorkerRunRecord]:
        return list(reversed(self._worker_runs[-limit:]))

    def list_dead_letter_notifications(self, limit: int = 50) -> list[DeadLetterNotification]:
        records: list[DeadLetterNotification] = []
        for context in self._sessions.values():
            records.extend(_dead_letters_from_context(context))
            if len(records) >= limit:
                return records[:limit]
        return records

    def list_dead_letter_calendar_syncs(self, limit: int = 50) -> list[DeadLetterCalendarSync]:
        records: list[DeadLetterCalendarSync] = []
        for context in self._sessions.values():
            records.extend(_calendar_dead_letters_from_context(context))
            if len(records) >= limit:
                return records[:limit]
        return records

    def record_operations_dashboard_snapshot(self, snapshot: dict[str, Any]) -> None:
        self._dashboard_snapshots.append(dict(snapshot))

    def list_operations_dashboard_snapshots(self, limit: int = 20) -> list[dict[str, Any]]:
        return list(reversed(self._dashboard_snapshots[-limit:]))

    def record_oncall_ticket_status(self, status: dict[str, Any]) -> None:
        self._oncall_statuses.append(dict(status))

    def list_oncall_ticket_statuses(self, limit: int = 20) -> list[dict[str, Any]]:
        return list(reversed(self._oncall_statuses[-limit:]))

    def record_operations_trend_alert(self, alert: dict[str, Any]) -> None:
        self._operations_trend_alerts = [
            existing for existing in self._operations_trend_alerts if existing.get("alert_id") != alert.get("alert_id")
        ]
        self._operations_trend_alerts.append(dict(alert))

    def list_operations_trend_alerts(self, limit: int = 20) -> list[dict[str, Any]]:
        return list(reversed(self._operations_trend_alerts[-limit:]))

    def record_operations_action_item(self, item: dict[str, Any]) -> None:
        self._operations_action_items = [
            existing for existing in self._operations_action_items if existing.get("action_id") != item.get("action_id")
        ]
        self._operations_action_items.append(dict(item))

    def list_operations_action_items(self, limit: int = 20) -> list[dict[str, Any]]:
        return list(reversed(self._operations_action_items[-limit:]))

    def record_operations_knowledge_entry(self, entry: dict[str, Any]) -> None:
        self._operations_knowledge_entries = [
            existing
            for existing in self._operations_knowledge_entries
            if existing.get("entry_id") != entry.get("entry_id")
        ]
        self._operations_knowledge_entries.append(dict(entry))

    def list_operations_knowledge_entries(self, limit: int = 20) -> list[dict[str, Any]]:
        return list(reversed(self._operations_knowledge_entries[-limit:]))


class SQLiteSessionStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def save(self, context: TravelContext) -> None:
        payload = json.dumps(context_to_dict(context), ensure_ascii=False, default=_json_default)
        with closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO travel_sessions(session_id, state, payload, version, created_at, updated_at)
                VALUES (?, ?, ?, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ON CONFLICT(session_id) DO UPDATE SET
                    state = excluded.state,
                    payload = excluded.payload,
                    version = travel_sessions.version + 1,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (context.session_id, context.state, payload),
            )
            connection.commit()

    def save_if_version(self, context: TravelContext, expected_version: int) -> int:
        payload = json.dumps(context_to_dict(context), ensure_ascii=False, default=_json_default)
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                UPDATE travel_sessions
                SET state = ?, payload = ?, version = version + 1, updated_at = CURRENT_TIMESTAMP
                WHERE session_id = ? AND version = ?
                RETURNING version
                """,
                (context.state, payload, context.session_id, expected_version),
            ).fetchone()
            if row is None:
                exists = connection.execute(
                    "SELECT 1 FROM travel_sessions WHERE session_id = ?",
                    (context.session_id,),
                ).fetchone()
                if exists is None and expected_version == 0:
                    inserted = connection.execute(
                        """
                        INSERT INTO travel_sessions(session_id, state, payload, version, created_at, updated_at)
                        VALUES (?, ?, ?, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                        RETURNING version
                        """,
                        (context.session_id, context.state, payload),
                    ).fetchone()
                    connection.commit()
                    return int(inserted[0])
                raise StoreConcurrencyError(
                    f"Session {context.session_id} version mismatch; expected {expected_version}."
                )
            connection.commit()
            return int(row[0])

    def get(self, session_id: str) -> TravelContext:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT payload FROM travel_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if row is None:
            raise KeyError(session_id)
        return context_from_dict(json.loads(row[0]))

    def get_with_metadata(self, session_id: str) -> StoredSession:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT payload, version, created_at, updated_at
                FROM travel_sessions
                WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()
        if row is None:
            raise KeyError(session_id)
        return StoredSession(
            context=context_from_dict(json.loads(row[0])),
            version=int(row[1]),
            created_at=str(row[2]),
            updated_at=str(row[3]),
        )

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
        with closing(self._connect()) as connection:
            rows = connection.execute(query, (*sorted(states), limit)).fetchall()
        return [context_from_dict(json.loads(row[0])) for row in rows]

    def list_recent(self, limit: int = 50) -> list[TravelContext]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT payload
                FROM travel_sessions
                ORDER BY updated_at DESC, rowid DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [context_from_dict(json.loads(row[0])) for row in rows]

    def record_worker_run(self, record: WorkerRunRecord) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO worker_runs(
                    run_id,
                    started_at,
                    finished_at,
                    scanned,
                    advanced,
                    skipped,
                    errors,
                    session_ids
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    started_at = excluded.started_at,
                    finished_at = excluded.finished_at,
                    scanned = excluded.scanned,
                    advanced = excluded.advanced,
                    skipped = excluded.skipped,
                    errors = excluded.errors,
                    session_ids = excluded.session_ids
                """,
                (
                    record.run_id,
                    record.started_at,
                    record.finished_at,
                    record.scanned,
                    record.advanced,
                    record.skipped,
                    json.dumps(record.errors, ensure_ascii=False),
                    json.dumps(record.session_ids, ensure_ascii=False),
                ),
            )
            connection.commit()

    def list_worker_runs(self, limit: int = 20) -> list[WorkerRunRecord]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT run_id, started_at, finished_at, scanned, advanced, skipped, errors, session_ids
                FROM worker_runs
                ORDER BY finished_at DESC, started_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            WorkerRunRecord(
                run_id=row[0],
                started_at=row[1],
                finished_at=row[2],
                scanned=int(row[3]),
                advanced=int(row[4]),
                skipped=int(row[5]),
                errors=json.loads(row[6]),
                session_ids=json.loads(row[7]),
            )
            for row in rows
        ]

    def list_dead_letter_notifications(self, limit: int = 50) -> list[DeadLetterNotification]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT payload
                FROM travel_sessions
                ORDER BY updated_at DESC
                """
            ).fetchall()

        records: list[DeadLetterNotification] = []
        for row in rows:
            records.extend(_dead_letters_from_context(context_from_dict(json.loads(row[0]))))
            if len(records) >= limit:
                return records[:limit]
        return records

    def list_dead_letter_calendar_syncs(self, limit: int = 50) -> list[DeadLetterCalendarSync]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT payload
                FROM travel_sessions
                ORDER BY updated_at DESC
                """
            ).fetchall()

        records: list[DeadLetterCalendarSync] = []
        for row in rows:
            records.extend(_calendar_dead_letters_from_context(context_from_dict(json.loads(row[0]))))
            if len(records) >= limit:
                return records[:limit]
        return records

    def record_operations_dashboard_snapshot(self, snapshot: dict[str, Any]) -> None:
        snapshot_id = str(snapshot.get("snapshot_id") or "")
        created_at = str(snapshot.get("created_at") or "")
        if not snapshot_id:
            raise ValueError("Operations dashboard snapshot requires snapshot_id.")
        payload = json.dumps(snapshot, ensure_ascii=False, default=_json_default)
        with closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO operations_dashboard_snapshots(snapshot_id, created_at, payload)
                VALUES (?, ?, ?)
                ON CONFLICT(snapshot_id) DO UPDATE SET
                    created_at = excluded.created_at,
                    payload = excluded.payload
                """,
                (snapshot_id, created_at, payload),
            )
            connection.commit()

    def list_operations_dashboard_snapshots(self, limit: int = 20) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT payload
                FROM operations_dashboard_snapshots
                ORDER BY created_at DESC, rowid DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def record_oncall_ticket_status(self, status: dict[str, Any]) -> None:
        ticket_id = str(status.get("ticket_id") or "")
        updated_at = str(status.get("updated_at") or "")
        if not ticket_id:
            raise ValueError("OnCall ticket status requires ticket_id.")
        payload = json.dumps(status, ensure_ascii=False, default=_json_default)
        with closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO oncall_ticket_statuses(ticket_id, status, updated_at, payload)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(ticket_id) DO UPDATE SET
                    status = excluded.status,
                    updated_at = excluded.updated_at,
                    payload = excluded.payload
                """,
                (ticket_id, str(status.get("status") or "UNKNOWN"), updated_at, payload),
            )
            connection.commit()

    def list_oncall_ticket_statuses(self, limit: int = 20) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT payload
                FROM oncall_ticket_statuses
                ORDER BY updated_at DESC, rowid DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def record_operations_trend_alert(self, alert: dict[str, Any]) -> None:
        alert_id = str(alert.get("alert_id") or "")
        if not alert_id:
            raise ValueError("Operations trend alert requires alert_id.")
        payload = json.dumps(alert, ensure_ascii=False, default=_json_default)
        with closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO operations_trend_alerts(alert_id, severity, metric, route, payload, created_at)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(alert_id) DO UPDATE SET
                    severity = excluded.severity,
                    metric = excluded.metric,
                    route = excluded.route,
                    payload = excluded.payload,
                    created_at = excluded.created_at
                """,
                (
                    alert_id,
                    str(alert.get("severity") or "warning"),
                    str(alert.get("metric") or ""),
                    str(alert.get("route") or ""),
                    payload,
                ),
            )
            connection.commit()

    def list_operations_trend_alerts(self, limit: int = 20) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT payload
                FROM operations_trend_alerts
                ORDER BY created_at DESC, rowid DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def record_operations_action_item(self, item: dict[str, Any]) -> None:
        action_id = str(item.get("action_id") or "")
        if not action_id:
            raise ValueError("Operations action item requires action_id.")
        payload = json.dumps(item, ensure_ascii=False, default=_json_default)
        with closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO operations_action_items(action_id, status, owner, updated_at, payload)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(action_id) DO UPDATE SET
                    status = excluded.status,
                    owner = excluded.owner,
                    updated_at = excluded.updated_at,
                    payload = excluded.payload
                """,
                (
                    action_id,
                    str(item.get("status") or "OPEN"),
                    str(item.get("owner") or "travel-ops"),
                    str(item.get("updated_at") or item.get("created_at") or ""),
                    payload,
                ),
            )
            connection.commit()

    def list_operations_action_items(self, limit: int = 20) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT payload
                FROM operations_action_items
                ORDER BY updated_at DESC, rowid DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def record_operations_knowledge_entry(self, entry: dict[str, Any]) -> None:
        entry_id = str(entry.get("entry_id") or "")
        if not entry_id:
            raise ValueError("Operations knowledge entry requires entry_id.")
        payload = json.dumps(entry, ensure_ascii=False, default=_json_default)
        with closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO operations_knowledge_entries(entry_id, topic, updated_at, payload)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(entry_id) DO UPDATE SET
                    topic = excluded.topic,
                    updated_at = excluded.updated_at,
                    payload = excluded.payload
                """,
                (
                    entry_id,
                    str(entry.get("topic") or ""),
                    str(entry.get("updated_at") or entry.get("created_at") or ""),
                    payload,
                ),
            )
            connection.commit()

    def list_operations_knowledge_entries(self, limit: int = 20) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT payload
                FROM operations_knowledge_entries
                ORDER BY updated_at DESC, rowid DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def health_check(self) -> StorageHealth:
        details: dict[str, str] = {}
        try:
            with closing(self._connect()) as connection:
                schema_version = self._schema_version(connection)
                session_count = int(connection.execute("SELECT COUNT(*) FROM travel_sessions").fetchone()[0])
                worker_run_count = int(connection.execute("SELECT COUNT(*) FROM worker_runs").fetchone()[0])
                dashboard_snapshot_count = int(
                    connection.execute("SELECT COUNT(*) FROM operations_dashboard_snapshots").fetchone()[0]
                )
                oncall_status_count = int(
                    connection.execute("SELECT COUNT(*) FROM oncall_ticket_statuses").fetchone()[0]
                )
                trend_alert_count = int(
                    connection.execute("SELECT COUNT(*) FROM operations_trend_alerts").fetchone()[0]
                )
                action_item_count = int(
                    connection.execute("SELECT COUNT(*) FROM operations_action_items").fetchone()[0]
                )
                knowledge_entry_count = int(
                    connection.execute("SELECT COUNT(*) FROM operations_knowledge_entries").fetchone()[0]
                )
                integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
                journal_mode = str(connection.execute("PRAGMA journal_mode").fetchone()[0])
            details["integrity_check"] = integrity
            details["journal_mode"] = journal_mode
            details["dashboard_snapshots"] = str(dashboard_snapshot_count)
            details["oncall_ticket_statuses"] = str(oncall_status_count)
            details["operations_trend_alerts"] = str(trend_alert_count)
            details["operations_action_items"] = str(action_item_count)
            details["operations_knowledge_entries"] = str(knowledge_entry_count)
            return StorageHealth(
                backend="sqlite",
                ok=integrity.lower() == "ok" and schema_version >= SQLITE_SCHEMA_VERSION,
                schema_version=schema_version,
                session_count=session_count,
                worker_run_count=worker_run_count,
                details=details,
            )
        except Exception as exc:
            details["error"] = str(exc)
            return StorageHealth(
                backend="sqlite",
                ok=False,
                schema_version=0,
                session_count=0,
                worker_run_count=0,
                details=details,
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def _init_schema(self) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS storage_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS travel_sessions (
                    session_id TEXT PRIMARY KEY,
                    state TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    version INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            self._ensure_column(connection, "travel_sessions", "version", "INTEGER NOT NULL DEFAULT 1")
            self._ensure_column(connection, "travel_sessions", "created_at", "TEXT")
            connection.execute(
                """
                UPDATE travel_sessions
                SET created_at = COALESCE(created_at, updated_at, CURRENT_TIMESTAMP)
                WHERE created_at IS NULL
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS worker_runs (
                    run_id TEXT PRIMARY KEY,
                    started_at TEXT NOT NULL,
                    finished_at TEXT NOT NULL,
                    scanned INTEGER NOT NULL,
                    advanced INTEGER NOT NULL,
                    skipped INTEGER NOT NULL,
                    errors TEXT NOT NULL,
                    session_ids TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS operations_dashboard_snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS oncall_ticket_statuses (
                    ticket_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS operations_trend_alerts (
                    alert_id TEXT PRIMARY KEY,
                    severity TEXT NOT NULL,
                    metric TEXT NOT NULL,
                    route TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS operations_action_items (
                    action_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    owner TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS operations_knowledge_entries (
                    entry_id TEXT PRIMARY KEY,
                    topic TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_travel_sessions_state_updated ON travel_sessions(state, updated_at)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_travel_sessions_updated ON travel_sessions(updated_at)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_worker_runs_finished ON worker_runs(finished_at, started_at)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_dashboard_snapshots_created ON operations_dashboard_snapshots(created_at)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_oncall_ticket_statuses_updated ON oncall_ticket_statuses(updated_at)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_operations_trend_alerts_created ON operations_trend_alerts(created_at)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_operations_action_items_updated ON operations_action_items(updated_at)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_operations_knowledge_entries_updated ON operations_knowledge_entries(updated_at)"
            )
            connection.execute(
                """
                INSERT INTO storage_meta(key, value)
                VALUES ('schema_version', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (str(SQLITE_SCHEMA_VERSION),),
            )
            connection.commit()

    @staticmethod
    def _ensure_column(
        connection: sqlite3.Connection,
        table_name: str,
        column_name: str,
        definition: str,
    ) -> None:
        columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()}
        if column_name not in columns:
            connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")

    @staticmethod
    def _schema_version(connection: sqlite3.Connection) -> int:
        try:
            row = connection.execute(
                "SELECT value FROM storage_meta WHERE key = 'schema_version'"
            ).fetchone()
        except sqlite3.OperationalError:
            return 1
        if row is None:
            return 1
        try:
            return int(row[0])
        except (TypeError, ValueError):
            return 0


class StoreHttpClient(Protocol):
    def post_json(self, url: str, payload: dict[str, Any], token: str | None = None) -> dict[str, Any]:
        ...


class DefaultStoreHttpClient:
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
            raise RuntimeError(f"HTTP {exc.code} from {url}: {detail}") from exc
        except URLError as exc:
            raise RuntimeError(f"Cannot reach {url}: {exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Invalid JSON response from {url}: {exc}") from exc


class HttpSessionStore:
    def __init__(
        self,
        base_url: str,
        token: str | None = None,
        http_client: StoreHttpClient | None = None,
        timeout_seconds: float = 5.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.http_client = http_client or DefaultStoreHttpClient(timeout_seconds=timeout_seconds)

    def save(self, context: TravelContext) -> None:
        self._post(
            "/sessions/save",
            {
                "session_id": context.session_id,
                "state": context.state,
                "payload": context_to_dict(context),
            },
        )

    def save_if_version(self, context: TravelContext, expected_version: int) -> int:
        response = self._post(
            "/sessions/save-if-version",
            {
                "session_id": context.session_id,
                "state": context.state,
                "expected_version": expected_version,
                "payload": context_to_dict(context),
            },
        )
        if response.get("ok") is False:
            raise StoreConcurrencyError(
                str(response.get("error") or f"Session {context.session_id} version mismatch.")
            )
        return int(response.get("version") or response.get("session_version") or expected_version + 1)

    def get(self, session_id: str) -> TravelContext:
        response = self._post("/sessions/get", {"session_id": session_id})
        return context_from_dict(_session_payload(response))

    def get_with_metadata(self, session_id: str) -> StoredSession:
        response = self._post("/sessions/get", {"session_id": session_id})
        session = _session_body(response)
        return StoredSession(
            context=context_from_dict(_session_payload(response)),
            version=int(session.get("version") or session.get("session_version") or 1),
            created_at=str(session.get("created_at") or ""),
            updated_at=str(session.get("updated_at") or ""),
        )

    def list_by_states(self, states: set[str], limit: int = 50) -> list[TravelContext]:
        if not states:
            return []
        response = self._post(
            "/sessions/list-by-states",
            {
                "states": sorted(states),
                "limit": limit,
            },
        )
        return [context_from_dict(_session_payload(item)) for item in _session_list(response)]

    def list_recent(self, limit: int = 50) -> list[TravelContext]:
        response = self._post("/sessions/list-recent", {"limit": limit})
        return [context_from_dict(_session_payload(item)) for item in _session_list(response)]

    def record_worker_run(self, record: WorkerRunRecord) -> None:
        self._post("/worker-runs/record", {"worker_run": asdict(record)})

    def list_worker_runs(self, limit: int = 20) -> list[WorkerRunRecord]:
        response = self._post("/worker-runs/list", {"limit": limit})
        records = response.get("worker_runs") or response.get("records") or response.get("items") or []
        return [_worker_run_from_dict(item) for item in records]

    def list_dead_letter_notifications(self, limit: int = 50) -> list[DeadLetterNotification]:
        records: list[DeadLetterNotification] = []
        for context in self.list_recent(limit=limit):
            records.extend(_dead_letters_from_context(context))
            if len(records) >= limit:
                return records[:limit]
        return records

    def list_dead_letter_calendar_syncs(self, limit: int = 50) -> list[DeadLetterCalendarSync]:
        records: list[DeadLetterCalendarSync] = []
        for context in self.list_recent(limit=limit):
            records.extend(_calendar_dead_letters_from_context(context))
            if len(records) >= limit:
                return records[:limit]
        return records

    def record_operations_dashboard_snapshot(self, snapshot: dict[str, Any]) -> None:
        self._post("/operations/dashboard-snapshots/record", {"snapshot": snapshot})

    def list_operations_dashboard_snapshots(self, limit: int = 20) -> list[dict[str, Any]]:
        response = self._post("/operations/dashboard-snapshots/list", {"limit": limit})
        records = response.get("snapshots") or response.get("records") or response.get("items") or []
        return [dict(item) for item in records]

    def record_oncall_ticket_status(self, status: dict[str, Any]) -> None:
        self._post("/operations/oncall-statuses/record", {"status": status})

    def list_oncall_ticket_statuses(self, limit: int = 20) -> list[dict[str, Any]]:
        response = self._post("/operations/oncall-statuses/list", {"limit": limit})
        records = response.get("statuses") or response.get("records") or response.get("items") or []
        return [dict(item) for item in records]

    def record_operations_trend_alert(self, alert: dict[str, Any]) -> None:
        self._post("/operations/trend-alerts/record", {"alert": alert})

    def list_operations_trend_alerts(self, limit: int = 20) -> list[dict[str, Any]]:
        response = self._post("/operations/trend-alerts/list", {"limit": limit})
        records = response.get("alerts") or response.get("records") or response.get("items") or []
        return [dict(item) for item in records]

    def record_operations_action_item(self, item: dict[str, Any]) -> None:
        self._post("/operations/action-items/record", {"item": item})

    def list_operations_action_items(self, limit: int = 20) -> list[dict[str, Any]]:
        response = self._post("/operations/action-items/list", {"limit": limit})
        records = response.get("items") or response.get("action_items") or response.get("records") or []
        return [dict(item) for item in records]

    def record_operations_knowledge_entry(self, entry: dict[str, Any]) -> None:
        self._post("/operations/knowledge/record", {"entry": entry})

    def list_operations_knowledge_entries(self, limit: int = 20) -> list[dict[str, Any]]:
        response = self._post("/operations/knowledge/list", {"limit": limit})
        records = response.get("entries") or response.get("records") or response.get("items") or []
        return [dict(item) for item in records]

    def health_check(self) -> StorageHealth:
        try:
            response = self._post("/health", {})
            return StorageHealth(
                backend=str(response.get("backend") or "http"),
                ok=bool(response.get("ok", True)),
                schema_version=int(response.get("schema_version") or 0),
                session_count=int(response.get("session_count") or response.get("sessions") or 0),
                worker_run_count=int(response.get("worker_run_count") or response.get("worker_runs") or 0),
                details={str(key): str(value) for key, value in dict(response.get("details") or {}).items()},
            )
        except Exception as exc:
            return StorageHealth(
                backend="http",
                ok=False,
                schema_version=0,
                session_count=0,
                worker_run_count=0,
                details={"error": str(exc)},
            )

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.http_client.post_json(f"{self.base_url}{path}", payload, self.token)


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
        department=payload["request"].get("department"),
        roles=list(payload["request"].get("roles", [])),
    )
    return TravelContext(
        session_id=payload["session_id"],
        request=request,
        state=payload["state"],
        workflow_generation=int(payload.get("workflow_generation", 1)),
        task_plan=_task_plan(payload.get("task_plan")),
        policy_result=_optional(PolicyResult, payload.get("policy_result")),
        transport_policy_result=_optional(TransportPolicyResult, payload.get("transport_policy_result")),
        itinerary=_itinerary(payload.get("itinerary")),
        hotel_options=[HotelOption(**item) for item in payload.get("hotel_options", [])],
        transport_options=[TransportOption(**item) for item in payload.get("transport_options", [])],
        selected_hotel=_optional(HotelOption, payload.get("selected_hotel")),
        selected_transport=_optional(TransportOption, payload.get("selected_transport")),
        approval=_optional(ApprovalRecord, payload.get("approval")),
        price_check=_optional(PriceCheckResult, payload.get("price_check")),
        inventory_lock=_optional(InventoryLock, payload.get("inventory_lock")),
        order=_optional(TravelOrder, payload.get("order")),
        transport_order=_optional(TransportOrder, payload.get("transport_order")),
        approval_cancellation=_optional(CompensationResult, payload.get("approval_cancellation")),
        order_cancellation=_optional(CompensationResult, payload.get("order_cancellation")),
        transport_order_cancellation=_optional(CompensationResult, payload.get("transport_order_cancellation")),
        inventory_release=_optional(CompensationResult, payload.get("inventory_release")),
        refund_estimates=[RefundEstimate(**item) for item in payload.get("refund_estimates", [])],
        refund_confirmations=[
            RefundConfirmationRecord(**item) for item in payload.get("refund_confirmations", [])
        ],
        change_approvals=[ApprovalRecord(**item) for item in payload.get("change_approvals", [])],
        change_records=[ChangeRecord(**item) for item in payload.get("change_records", [])],
        change_failure_compensations=[
            CompensationResult(**item) for item in payload.get("change_failure_compensations", [])
        ],
        calendar_syncs=[CalendarSyncRecord(**item) for item in payload.get("calendar_syncs", [])],
        notifications=[NotificationRecord(**item) for item in payload.get("notifications", [])],
        notification_keys=list(payload.get("notification_keys", [])),
        recovery_records=[RecoveryRecord(**item) for item in payload.get("recovery_records", [])],
        agent_executions=[AgentExecutionRecord(**item) for item in payload.get("agent_executions", [])],
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


def _dead_letters_from_context(context: TravelContext) -> list[DeadLetterNotification]:
    return [
        DeadLetterNotification(
            session_id=context.session_id,
            state=context.state,
            notification=notification,
        )
        for notification in context.notifications
        if notification.status == "DEAD_LETTER"
    ]


def _calendar_dead_letters_from_context(context: TravelContext) -> list[DeadLetterCalendarSync]:
    return [
        DeadLetterCalendarSync(
            session_id=context.session_id,
            state=context.state,
            calendar_sync=record,
        )
        for record in context.calendar_syncs
        if record.status == "DEAD_LETTER"
    ]


def _session_body(payload: dict[str, Any]) -> dict[str, Any]:
    if "session" in payload and isinstance(payload["session"], dict):
        return payload["session"]
    return payload


def _session_payload(payload: dict[str, Any]) -> dict[str, Any]:
    session = _session_body(payload)
    candidate = session.get("payload")
    if isinstance(candidate, str):
        return json.loads(candidate)
    if isinstance(candidate, dict):
        return candidate
    if "context" in session and isinstance(session["context"], dict):
        return session["context"]
    if "request" in session and "state" in session:
        return session
    raise ValueError("Session response is missing payload.")


def _session_list(payload: dict[str, Any]) -> list[dict[str, Any]]:
    candidate = payload.get("sessions") or payload.get("items") or payload.get("records") or []
    if not isinstance(candidate, list):
        raise ValueError("Session list response must contain a list.")
    return candidate


def _worker_run_from_dict(payload: dict[str, Any]) -> WorkerRunRecord:
    errors = payload.get("errors", {})
    session_ids = payload.get("session_ids", [])
    if isinstance(errors, str):
        errors = json.loads(errors)
    if isinstance(session_ids, str):
        session_ids = json.loads(session_ids)
    return WorkerRunRecord(
        run_id=str(payload["run_id"]),
        started_at=str(payload["started_at"]),
        finished_at=str(payload["finished_at"]),
        scanned=int(payload["scanned"]),
        advanced=int(payload["advanced"]),
        skipped=int(payload["skipped"]),
        errors=dict(errors),
        session_ids=list(session_ids),
    )
