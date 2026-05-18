from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.request import Request, urlopen
from uuid import NAMESPACE_URL, uuid5

from .models import DeadLetterNotification, TravelContext, WorkerRunRecord


PostJson = Callable[[str, dict[str, Any], str | None], int]


@dataclass(frozen=True)
class OtlpExportResult:
    traces_url: str
    metrics_url: str
    traces_status: int
    metrics_status: int
    span_count: int
    metric_count: int
    alert_count: int


def build_otlp_trace_payload(
    worker_runs: list[WorkerRunRecord],
    sessions: list[TravelContext],
    service_name: str = "travel-agent",
) -> dict[str, Any]:
    spans: list[dict[str, Any]] = []
    for run in worker_runs:
        trace_id = _trace_id(f"worker:{run.run_id}")
        spans.append(
            {
                "traceId": trace_id,
                "spanId": _span_id(f"worker:{run.run_id}"),
                "name": "WorkflowWorker.run_once",
                "kind": "SPAN_KIND_INTERNAL",
                "startTimeUnixNano": str(_unix_nano(run.started_at)),
                "endTimeUnixNano": str(_unix_nano(run.finished_at)),
                "attributes": _attributes(
                    {
                        "worker.run_id": run.run_id,
                        "worker.scanned": run.scanned,
                        "worker.advanced": run.advanced,
                        "worker.skipped": run.skipped,
                        "worker.errors": len(run.errors),
                    }
                ),
                "status": _span_status("ERROR" if run.errors else "SUCCESS"),
            }
        )

    for context in sessions:
        trace_id = _trace_id(f"session:{context.session_id}:{context.workflow_generation}")
        for index, record in enumerate(context.agent_executions):
            start = _unix_nano(record.created_at)
            spans.append(
                {
                    "traceId": trace_id,
                    "spanId": _span_id(f"{context.session_id}:{record.agent_name}:{record.action}:{index}"),
                    "name": f"{record.agent_name}.{record.action}",
                    "kind": "SPAN_KIND_INTERNAL",
                    "startTimeUnixNano": str(start),
                    "endTimeUnixNano": str(start + 1_000_000),
                    "attributes": _attributes(
                        {
                            "session.id": context.session_id,
                            "workflow.generation": context.workflow_generation,
                            "workflow.state": context.state,
                            "agent.name": record.agent_name,
                            "agent.action": record.action,
                            "agent.status": record.status,
                            "agent.message": record.message,
                        }
                    ),
                    "status": _span_status(record.status),
                }
            )

    return {
        "resourceSpans": [
            {
                "resource": _resource(service_name),
                "scopeSpans": [
                    {
                        "scope": {"name": "travel-agent.observability", "version": "1.0.0"},
                        "spans": spans,
                    }
                ],
            }
        ]
    }


def build_otlp_metric_payload(
    worker_runs: list[WorkerRunRecord],
    dead_letters: list[DeadLetterNotification],
    sessions: list[TravelContext],
    service_name: str = "travel-agent",
) -> dict[str, Any]:
    scanned = sum(record.scanned for record in worker_runs)
    advanced = sum(record.advanced for record in worker_runs)
    skipped = sum(record.skipped for record in worker_runs)
    worker_errors = sum(len(record.errors) for record in worker_runs)
    metrics = [
        _sum_metric("travel.worker.runs", len(worker_runs), "Total recorded workflow worker runs."),
        _sum_metric(
            "travel.worker.sessions",
            None,
            "Total sessions scanned by workflow workers.",
            points=[
                _point(scanned, {"result": "scanned"}),
                _point(advanced, {"result": "advanced"}),
                _point(skipped, {"result": "skipped"}),
            ],
        ),
        _sum_metric("travel.worker.errors", worker_errors, "Total workflow worker errors."),
        _gauge_metric(
            "travel.sessions.observed",
            len(sessions),
            "Sessions included in this observability snapshot.",
        ),
        _gauge_metric(
            "travel.session.states",
            None,
            "Sessions by current workflow state.",
            points=[
                _point(count, {"state": state})
                for state, count in sorted(_count_by(sessions, lambda item: item.state).items())
            ]
            or [_point(0, {"state": "none"})],
        ),
        _sum_metric(
            "travel.agent.executions",
            None,
            "Agent execution records by agent, action, and status.",
            points=[
                _point(count, {"agent": agent, "action": action, "status": status})
                for (agent, action, status), count in sorted(_agent_execution_counts(sessions).items())
            ]
            or [_point(0, {"agent": "none", "action": "none", "status": "none"})],
        ),
        _sum_metric(
            "travel.calendar.syncs",
            None,
            "Calendar sync records by event type, status, and source.",
            points=[
                _point(count, {"event_type": event_type, "status": status, "source": source})
                for (event_type, status, source), count in sorted(_calendar_counts(sessions).items())
            ]
            or [_point(0, {"event_type": "none", "status": "none", "source": "none"})],
        ),
        _gauge_metric(
            "travel.notification.dead_letters",
            None,
            "Notification dead letters by workflow state and event type.",
            points=[
                _point(count, {"state": state, "event_type": event_type})
                for (state, event_type), count in sorted(_dead_letter_counts(dead_letters).items())
            ]
            or [_point(0, {"state": "none", "event_type": "none"})],
        ),
    ]
    alerts = build_sla_alerts(worker_runs, dead_letters, sessions)
    metrics.append(
        _gauge_metric(
            "travel.sla.alerts",
            None,
            "SLA alerts by alert type and severity.",
            points=[
                _point(
                    alert["value"],
                    {
                        "alert_type": alert["alert_type"],
                        "severity": alert["severity"],
                        "message": alert["message"],
                    },
                )
                for alert in alerts
            ]
            or [_point(0, {"alert_type": "none", "severity": "none", "message": "no active alerts"})],
        )
    )
    return {
        "resourceMetrics": [
            {
                "resource": _resource(service_name),
                "scopeMetrics": [
                    {
                        "scope": {"name": "travel-agent.observability", "version": "1.0.0"},
                        "metrics": metrics,
                    }
                ],
            }
        ]
    }


def build_sla_alerts(
    worker_runs: list[WorkerRunRecord],
    dead_letters: list[DeadLetterNotification],
    sessions: list[TravelContext],
) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    worker_error_count = sum(len(record.errors) for record in worker_runs)
    if worker_error_count:
        alerts.append(
            {
                "alert_type": "worker_errors",
                "severity": "critical",
                "message": "Workflow worker reported errors.",
                "value": worker_error_count,
            }
        )
    if dead_letters:
        alerts.append(
            {
                "alert_type": "notification_dead_letters",
                "severity": "warning",
                "message": "Notification dead letters require replay or manual handling.",
                "value": len(dead_letters),
            }
        )
    order_failed = sum(1 for context in sessions if context.state == "ORDER_FAILED")
    if order_failed:
        alerts.append(
            {
                "alert_type": "order_failed",
                "severity": "critical",
                "message": "Travel sessions are stuck in ORDER_FAILED.",
                "value": order_failed,
            }
        )
    price_changed = sum(1 for context in sessions if context.state == "PRICE_CHANGED")
    if price_changed:
        alerts.append(
            {
                "alert_type": "manual_price_confirmation",
                "severity": "info",
                "message": "Travel sessions are waiting for price-change confirmation.",
                "value": price_changed,
            }
        )
    calendar_failed = sum(
        1
        for context in sessions
        for record in context.calendar_syncs
        if record.status not in {"SYNCED", "DONE", "SUCCESS"}
    )
    if calendar_failed:
        alerts.append(
            {
                "alert_type": "calendar_sync_failed",
                "severity": "warning",
                "message": "Calendar sync records are not successful.",
                "value": calendar_failed,
            }
        )
    return alerts


def build_otlp_payloads(
    worker_runs: list[WorkerRunRecord],
    dead_letters: list[DeadLetterNotification],
    sessions: list[TravelContext],
    service_name: str = "travel-agent",
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    alerts = build_sla_alerts(worker_runs, dead_letters, sessions)
    return (
        build_otlp_trace_payload(worker_runs, sessions, service_name),
        build_otlp_metric_payload(worker_runs, dead_letters, sessions, service_name),
        alerts,
    )


def export_otlp_http(
    endpoint: str,
    traces_payload: dict[str, Any],
    metrics_payload: dict[str, Any],
    token: str | None = None,
    post_json: PostJson | None = None,
) -> OtlpExportResult:
    post = post_json or _post_json
    base = endpoint.rstrip("/")
    traces_url = f"{base}/v1/traces"
    metrics_url = f"{base}/v1/metrics"
    traces_status = post(traces_url, traces_payload, token)
    metrics_status = post(metrics_url, metrics_payload, token)
    span_count = sum(
        len(scope_spans.get("spans", []))
        for resource_span in traces_payload.get("resourceSpans", [])
        for scope_spans in resource_span.get("scopeSpans", [])
    )
    metric_count = sum(
        len(scope_metrics.get("metrics", []))
        for resource_metric in metrics_payload.get("resourceMetrics", [])
        for scope_metrics in resource_metric.get("scopeMetrics", [])
    )
    alert_count = sum(
        len(metric.get("gauge", {}).get("dataPoints", []))
        for resource_metric in metrics_payload.get("resourceMetrics", [])
        for scope_metrics in resource_metric.get("scopeMetrics", [])
        for metric in scope_metrics.get("metrics", [])
        if metric.get("name") == "travel.sla.alerts"
    )
    return OtlpExportResult(
        traces_url=traces_url,
        metrics_url=metrics_url,
        traces_status=traces_status,
        metrics_status=metrics_status,
        span_count=span_count,
        metric_count=metric_count,
        alert_count=alert_count,
    )


def _post_json(url: str, payload: dict[str, Any], token: str | None) -> int:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(url, data=body, headers=headers, method="POST")
    with urlopen(request, timeout=10) as response:
        return int(response.status)


def _sum_metric(
    name: str,
    value: int | None,
    description: str,
    points: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "unit": "1",
        "sum": {
            "aggregationTemporality": "AGGREGATION_TEMPORALITY_CUMULATIVE",
            "isMonotonic": True,
            "dataPoints": points if points is not None else [_point(value or 0)],
        },
    }


def _gauge_metric(
    name: str,
    value: int | None,
    description: str,
    points: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "unit": "1",
        "gauge": {
            "dataPoints": points if points is not None else [_point(value or 0)],
        },
    }


def _point(value: int, attributes: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "asInt": str(value),
        "timeUnixNano": str(_now_nano()),
        "attributes": _attributes(attributes or {}),
    }


def _resource(service_name: str) -> dict[str, Any]:
    return {"attributes": _attributes({"service.name": service_name})}


def _attributes(values: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"key": key, "value": _attribute_value(value)} for key, value in values.items()]


def _attribute_value(value: Any) -> dict[str, Any]:
    if isinstance(value, bool):
        return {"boolValue": value}
    if isinstance(value, int):
        return {"intValue": str(value)}
    if isinstance(value, float):
        return {"doubleValue": value}
    return {"stringValue": str(value)}


def _span_status(status: str) -> dict[str, str]:
    normalized = status.upper()
    if normalized in {"SUCCESS", "SUCCEEDED", "DONE", "SYNCED", "CREATED", "CONFIRMED"}:
        return {"code": "STATUS_CODE_OK"}
    if normalized in {"FAILED", "ERROR", "DEAD_LETTER"}:
        return {"code": "STATUS_CODE_ERROR"}
    return {"code": "STATUS_CODE_UNSET"}


def _unix_nano(value: str) -> int:
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp() * 1_000_000_000)


def _now_nano() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1_000_000_000)


def _trace_id(value: str) -> str:
    return uuid5(NAMESPACE_URL, value).hex


def _span_id(value: str) -> str:
    return uuid5(NAMESPACE_URL, value).hex[:16]


def _count_by(items: list[Any], key_fn: Callable[[Any], Any]) -> dict[Any, int]:
    counts: dict[Any, int] = {}
    for item in items:
        key = key_fn(item)
        counts[key] = counts.get(key, 0) + 1
    return counts


def _dead_letter_counts(records: list[DeadLetterNotification]) -> dict[tuple[str, str], int]:
    counts: dict[tuple[str, str], int] = {}
    for record in records:
        key = (record.state, record.notification.event_type)
        counts[key] = counts.get(key, 0) + 1
    return counts


def _agent_execution_counts(sessions: list[TravelContext]) -> dict[tuple[str, str, str], int]:
    counts: dict[tuple[str, str, str], int] = {}
    for context in sessions:
        for record in context.agent_executions:
            key = (record.agent_name, record.action, record.status)
            counts[key] = counts.get(key, 0) + 1
    return counts


def _calendar_counts(sessions: list[TravelContext]) -> dict[tuple[str, str, str], int]:
    counts: dict[tuple[str, str, str], int] = {}
    for context in sessions:
        for record in context.calendar_syncs:
            key = (record.event_type, record.status, record.source)
            counts[key] = counts.get(key, 0) + 1
    return counts
