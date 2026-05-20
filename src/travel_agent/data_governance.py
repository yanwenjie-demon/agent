from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .config import IntegrationSettings


SENSITIVE_KEYS = {
    "id_card",
    "id_card_no",
    "identity_card",
    "phone",
    "mobile",
    "mobile_phone",
    "email",
    "bank_card",
    "card_no",
    "payment",
    "credit_card",
    "passport",
    "passport_no",
    "tax_id",
}


@dataclass(frozen=True)
class RedactionResult:
    redacted: dict[str, Any]
    redacted_keys: list[str]


@dataclass(frozen=True)
class GovernanceAuditEvent:
    event_type: str
    detail: str
    redacted_keys: list[str]
    redacted_payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AuditSinkResult:
    ok: bool
    delivered: int
    failed: int
    detail: str


def redact_payload(payload: dict[str, Any]) -> RedactionResult:
    redacted: dict[str, Any] = {}
    redacted_keys: list[str] = []
    for key, value in payload.items():
        if _is_sensitive_key(key):
            redacted[key] = "***"
            redacted_keys.append(key)
            continue
        if isinstance(value, dict):
            nested = redact_payload(value)
            redacted[key] = nested.redacted
            redacted_keys.extend(f"{key}.{item}" for item in nested.redacted_keys)
            continue
        if isinstance(value, list):
            items: list[Any] = []
            for index, item in enumerate(value):
                if isinstance(item, dict):
                    nested = redact_payload(item)
                    items.append(nested.redacted)
                    redacted_keys.extend(f"{key}[{index}].{item_key}" for item_key in nested.redacted_keys)
                else:
                    items.append(item)
            redacted[key] = items
            continue
        redacted[key] = value
    return RedactionResult(redacted=redacted, redacted_keys=redacted_keys)


def build_audit_event(event_type: str, payload: dict[str, Any]) -> GovernanceAuditEvent:
    result = redact_payload(payload)
    detail = "payload redacted" if result.redacted_keys else "payload clean"
    return GovernanceAuditEvent(
        event_type=event_type,
        detail=detail,
        redacted_keys=result.redacted_keys,
        redacted_payload=result.redacted,
    )


def summarize_audit_events(events: list[GovernanceAuditEvent]) -> dict[str, int]:
    summary: dict[str, int] = {}
    for event in events:
        summary[event.event_type] = summary.get(event.event_type, 0) + 1
    return summary


class AuditSink:
    def write(self, events: list[GovernanceAuditEvent]) -> AuditSinkResult:
        raise NotImplementedError


class InMemoryAuditSink(AuditSink):
    def __init__(self) -> None:
        self.events: list[GovernanceAuditEvent] = []

    def write(self, events: list[GovernanceAuditEvent]) -> AuditSinkResult:
        self.events.extend(events)
        return AuditSinkResult(ok=True, delivered=len(events), failed=0, detail="stored in memory")


class HttpAuditSink(AuditSink):
    def __init__(self, url: str, token: str | None = None, http_client: Any | None = None) -> None:
        from .integrations import JsonHttpClient

        self.url = url
        self.token = token
        self.http_client = http_client or JsonHttpClient()

    def write(self, events: list[GovernanceAuditEvent]) -> AuditSinkResult:
        payload = {
            "events": [
                {
                    "event_type": event.event_type,
                    "detail": event.detail,
                    "redacted_keys": event.redacted_keys,
                    "payload": event.redacted_payload,
                }
                for event in events
            ]
        }
        try:
            response = self.http_client.post_json(self.url, payload, self.token)
        except Exception as exc:
            return AuditSinkResult(ok=False, delivered=0, failed=len(events), detail=str(exc))
        accepted = int(response.get("accepted") or response.get("delivered") or len(events))
        failed = max(0, len(events) - accepted)
        return AuditSinkResult(
            ok=bool(response.get("ok", failed == 0)),
            delivered=accepted,
            failed=failed,
            detail=str(response.get("detail") or "sent to audit sink"),
        )


def build_audit_sink(settings: IntegrationSettings, http_client: Any | None = None) -> AuditSink | None:
    if not settings.audit_log_api_url:
        return None
    return HttpAuditSink(settings.audit_log_api_url, settings.audit_log_api_token, http_client=http_client)


def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return any(token in normalized for token in SENSITIVE_KEYS)
