from __future__ import annotations

import json
import hashlib
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from .config import IntegrationSettings
from .data_governance import AuditSinkResult
from .governance import ReleaseReadinessReport, run_release_readiness_report
from .models import DeadLetterCalendarSync, DeadLetterNotification, TravelContext, WorkerRunRecord
from .observability import build_sla_alerts
from .permissions import PermissionDecision, PermissionPolicy, evaluate_permission
from .release_control import RolloutDecision, RolloutPolicy, evaluate_rollout


@dataclass(frozen=True)
class RunbookItem:
    title: str
    when: str
    action: str
    owner: str = "platform"


@dataclass(frozen=True)
class OperationsRunbook:
    lifecycle: list[RunbookItem] = field(default_factory=list)
    incident_handling: list[RunbookItem] = field(default_factory=list)
    incident_drills: list[RunbookItem] = field(default_factory=list)


@dataclass(frozen=True)
class IncidentDrillResult:
    scenario: str
    status: str
    summary: str
    signals: list[str]
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OperationsDrillReport:
    settings_profile: str
    readiness: ReleaseReadinessReport
    alerts: list[dict[str, Any]]
    permission_decision: PermissionDecision
    rollout_decision: RolloutDecision
    drills: list[IncidentDrillResult]


@dataclass(frozen=True)
class OperationsAlertExportResult:
    ok: bool
    endpoint: str
    delivered: int
    failed: int
    detail: str


@dataclass(frozen=True)
class OperationsDrillGateResult:
    passed: bool
    exit_code: int
    report: OperationsDrillReport


@dataclass(frozen=True)
class OperationsDashboard:
    sessions_observed: int
    worker_runs: int
    worker_errors: int
    notification_dead_letters: int
    calendar_dead_letters: int
    active_alerts: int
    critical_alerts: int
    state_counts: dict[str, int]
    action_items: list[str]


@dataclass(frozen=True)
class OperationsDashboardSnapshot:
    snapshot_id: str
    created_at: str
    dashboard: OperationsDashboard
    alerts: list[dict[str, Any]]


@dataclass(frozen=True)
class AlertRouteRule:
    alert_type: str
    severity: str
    route: str
    escalation: str
    silence_hint: str


@dataclass(frozen=True)
class OnCallTicketResult:
    ok: bool
    endpoint: str
    ticket_id: str | None
    delivered: int
    failed: int
    detail: str


@dataclass(frozen=True)
class OnCallTicketStatus:
    ticket_id: str
    status: str
    assignee: str | None
    updated_at: str
    detail: str


@dataclass(frozen=True)
class OperationsTrendMetric:
    name: str
    current: int
    previous: int
    delta: int
    delta_percent: float | None


@dataclass(frozen=True)
class OperationsTrendReport:
    window: int
    snapshot_count: int
    latest_snapshot: OperationsDashboardSnapshot | None
    previous_snapshot: OperationsDashboardSnapshot | None
    metrics: list[OperationsTrendMetric]
    summary: str
    anomalies: list[str]
    action_items: list[str]


@dataclass(frozen=True)
class OperationsDimensionRow:
    key: str
    sessions: int
    orders: int
    compensations: int
    policy_violations: int
    failed: int


@dataclass(frozen=True)
class OperationsDimensionGroup:
    name: str
    rows: list[OperationsDimensionRow]


@dataclass(frozen=True)
class OperationsMultiDimensionalView:
    total_sessions: int
    worker_runs: int
    worker_errors: int
    state_counts: dict[str, int]
    alert_counts: dict[str, int]
    severity_counts: dict[str, int]
    dead_letter_counts: dict[str, int]
    groups: list[OperationsDimensionGroup]
    summary: str
    action_items: list[str]


@dataclass(frozen=True)
class OperationsTimelineEvent:
    timestamp: str
    source: str
    detail: str


@dataclass(frozen=True)
class OperationsPostmortemReport:
    incident_id: str
    generated_at: str
    severity: str
    primary_signal: str
    summary: str
    impact: list[str]
    timeline: list[OperationsTimelineEvent]
    root_causes: list[str]
    evidence: list[str]
    action_items: list[str]
    related_sessions: list[str]
    related_tickets: list[OnCallTicketStatus]
    related_alerts: list[dict[str, Any]]
    drill_findings: list[str]


@dataclass(frozen=True)
class OperationsTrendAlertRule:
    metric: str
    severity: str
    route: str
    escalation: str
    owner: str
    absolute_threshold: int | None = None
    delta_threshold: int | None = None
    delta_percent_threshold: float | None = None
    action_template: str = "Investigate operations trend for {metric}."


@dataclass(frozen=True)
class OperationsTrendAlert:
    alert_id: str
    metric: str
    severity: str
    route: str
    escalation: str
    owner: str
    current: int
    previous: int
    delta: int
    delta_percent: float | None
    reason: str
    action_item: str


@dataclass(frozen=True)
class OperationsActionItem:
    action_id: str
    source_type: str
    source_id: str
    title: str
    owner: str
    status: str
    eta: str | None
    created_at: str
    updated_at: str
    evidence: list[str]
    closure_note: str | None = None


@dataclass(frozen=True)
class OperationsKnowledgeEntry:
    entry_id: str
    topic: str
    title: str
    summary: str
    signals: list[str]
    recommended_actions: list[str]
    source_refs: list[str]
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class OperationsKnowledgeSearchHit:
    entry: OperationsKnowledgeEntry
    score: int
    matched_terms: list[str]


@dataclass(frozen=True)
class OperationsKnowledgeSearchReport:
    query: str
    total_entries: int
    hits: list[OperationsKnowledgeSearchHit]
    suggested_actions: list[str]


@dataclass(frozen=True)
class OperationsActionSlaPolicy:
    warning_after_hours: float = 24.0
    critical_after_hours: float = 48.0
    default_route: str = "travel-ops"
    escalation_template: str = "Notify {owner} via {route}: {title}"
    owner_routes: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class OperationsActionSlaFinding:
    action_id: str
    severity: str
    owner: str
    route: str
    age_hours: float
    overdue_hours: float
    reason: str
    escalation: str
    reminder: str


@dataclass(frozen=True)
class OperationsActionSlaReport:
    now: str
    total_open: int
    findings: list[OperationsActionSlaFinding]
    escalation_count: int
    summary: str


@dataclass(frozen=True)
class OperationsClosedLoopReport:
    generated_at: str
    trend_alerts: int
    action_items_total: int
    action_items_open: int
    action_items_closed: int
    action_items_overdue: int
    closure_rate: float
    knowledge_entries: int
    knowledge_topics: dict[str, int]
    source_counts: dict[str, int]
    recommendations: list[str]


def build_operations_runbook() -> OperationsRunbook:
    return OperationsRunbook(
        lifecycle=[
            RunbookItem(
                title="上线准备",
                when="首次接入真实权限、审计、库存或 OA 环境前",
                action="确认 release gate 通过，检查 session store、权限中心和审计 sink 已就绪。",
            ),
            RunbookItem(
                title="灰度发布",
                when="新版本仅对部分用户或部门开放",
                action="先启用 rollout 控制，再按用户、部门和百分比逐步放量，观察 worker 错误和死信。",
            ),
            RunbookItem(
                title="回滚",
                when="外部系统异常、告警飙升或订单链路失败",
                action="关闭 rollout，冻结新单，保留会话和审计，等待恢复后再重试。",
            ),
        ],
        incident_handling=[
            RunbookItem(
                title="死信处理",
                when="通知或日历同步进入 DEAD_LETTER",
                action="先确认幂等键，再通过 CLI 重放 dead letter，必要时人工补偿原始会话。",
            ),
            RunbookItem(
                title="人工补偿",
                when="订单、库存或审批出现部分成功",
                action="按 session_id 定位上下文，优先执行取消、释放库存、撤回审批和退款确认。",
            ),
            RunbookItem(
                title="权限中心不可用",
                when="外部 IAM 返回失败或超时",
                action="回退到本地权限策略或直接进入 ACTION_REQUIRED，禁止默认放行到生产。",
            ),
            RunbookItem(
                title="审计 sink 不可用",
                when="审计落库接口超时或返回失败",
                action="保留本地脱敏审计事件，补偿重试并上报平台告警。",
            ),
        ],
        incident_drills=[
            RunbookItem(
                title="权限中心不可用演练",
                when="每次发布前或每周一次",
                action="模拟 IAM 超时，确认本地策略接管、审计留痕和告警触发。",
            ),
            RunbookItem(
                title="审计 sink 不可用演练",
                when="每次发布前或每周一次",
                action="模拟审计 HTTP 失败，确认事件仍被脱敏并记录失败结果。",
            ),
            RunbookItem(
                title="供应商下单失败演练",
                when="每次发布前或每周一次",
                action="模拟酒店或交通订单失败，确认订单失败态、补偿和回滚路径可用。",
            ),
            RunbookItem(
                title="回滚开关触发演练",
                when="每次发布前或每次灰度放量前",
                action="启用 rollback 开关，确认 rollout 立即关闭且门禁输出 ROLLED_BACK。",
            ),
        ],
    )


def render_operations_runbook(runbook: OperationsRunbook) -> str:
    lines = ["Operations runbook:"]
    for section_title, items in (
        ("Lifecycle", runbook.lifecycle),
        ("Incident handling", runbook.incident_handling),
        ("Incident drills", runbook.incident_drills),
    ):
        lines.append(f"- {section_title}:")
        for item in items:
            lines.append(f"  - {item.title} [{item.owner}]")
            lines.append(f"    when: {item.when}")
            lines.append(f"    action: {item.action}")
    return "\n".join(lines)


def build_operations_dashboard(
    worker_runs: list[WorkerRunRecord] | None = None,
    dead_letters: list[DeadLetterNotification] | None = None,
    calendar_dead_letters: list[DeadLetterCalendarSync] | None = None,
    sessions: list[TravelContext] | None = None,
    alerts: list[dict[str, Any]] | None = None,
) -> OperationsDashboard:
    worker_runs = worker_runs or []
    dead_letters = dead_letters or []
    calendar_dead_letters = calendar_dead_letters or []
    sessions = sessions or []
    alerts = alerts or []
    state_counts: dict[str, int] = {}
    for context in sessions:
        state_counts[context.state] = state_counts.get(context.state, 0) + 1
    worker_errors = sum(len(record.errors) for record in worker_runs)
    critical_alerts = sum(1 for alert in alerts if _normalize_alert(alert)["severity"] == "critical")
    action_items: list[str] = []
    if worker_errors:
        action_items.append("Inspect worker errors and replay stuck sessions.")
    if dead_letters:
        action_items.append("Replay notification dead letters after checking idempotency keys.")
    if calendar_dead_letters:
        action_items.append("Replay calendar dead letters or create events manually.")
    if any(context.state == "ORDER_FAILED" for context in sessions):
        action_items.append("Run order compensation or operator replan for ORDER_FAILED sessions.")
    if any(_normalize_alert(alert)["alert_type"] == "audit_sink_failed" for alert in alerts):
        action_items.append("Recover audit sink and replay failed audit events.")
    if not action_items:
        action_items.append("No immediate action required.")
    return OperationsDashboard(
        sessions_observed=len(sessions),
        worker_runs=len(worker_runs),
        worker_errors=worker_errors,
        notification_dead_letters=len(dead_letters),
        calendar_dead_letters=len(calendar_dead_letters),
        active_alerts=len(alerts),
        critical_alerts=critical_alerts,
        state_counts=state_counts,
        action_items=action_items,
    )


def render_operations_dashboard(dashboard: OperationsDashboard) -> str:
    lines = [
        "Operations dashboard:",
        f"- sessions_observed: {dashboard.sessions_observed}",
        f"- worker_runs: {dashboard.worker_runs}",
        f"- worker_errors: {dashboard.worker_errors}",
        f"- notification_dead_letters: {dashboard.notification_dead_letters}",
        f"- calendar_dead_letters: {dashboard.calendar_dead_letters}",
        f"- active_alerts: {dashboard.active_alerts}",
        f"- critical_alerts: {dashboard.critical_alerts}",
        "- states:",
    ]
    if dashboard.state_counts:
        for state, count in sorted(dashboard.state_counts.items()):
            lines.append(f"  - {state}: {count}")
    else:
        lines.append("  - none: 0")
    lines.append("- action_items:")
    for item in dashboard.action_items:
        lines.append(f"  - {item}")
    return "\n".join(lines)


def build_operations_dashboard_snapshot(
    dashboard: OperationsDashboard,
    alerts: list[dict[str, Any]] | None = None,
    snapshot_id: str | None = None,
    created_at: str | None = None,
) -> OperationsDashboardSnapshot:
    return OperationsDashboardSnapshot(
        snapshot_id=snapshot_id or "DASH-" + uuid4().hex[:12].upper(),
        created_at=created_at or datetime.now(timezone.utc).isoformat(),
        dashboard=dashboard,
        alerts=[_normalize_alert(alert) for alert in alerts or []],
    )


def operations_dashboard_snapshot_to_dict(snapshot: OperationsDashboardSnapshot) -> dict[str, Any]:
    return {
        "snapshot_id": snapshot.snapshot_id,
        "created_at": snapshot.created_at,
        "dashboard": {
            "sessions_observed": snapshot.dashboard.sessions_observed,
            "worker_runs": snapshot.dashboard.worker_runs,
            "worker_errors": snapshot.dashboard.worker_errors,
            "notification_dead_letters": snapshot.dashboard.notification_dead_letters,
            "calendar_dead_letters": snapshot.dashboard.calendar_dead_letters,
            "active_alerts": snapshot.dashboard.active_alerts,
            "critical_alerts": snapshot.dashboard.critical_alerts,
            "state_counts": snapshot.dashboard.state_counts,
            "action_items": snapshot.dashboard.action_items,
        },
        "alerts": [_normalize_alert(alert) for alert in snapshot.alerts],
    }


def operations_dashboard_snapshot_from_dict(payload: dict[str, Any]) -> OperationsDashboardSnapshot:
    dashboard = payload.get("dashboard") or {}
    return OperationsDashboardSnapshot(
        snapshot_id=str(payload.get("snapshot_id") or payload.get("id") or ""),
        created_at=str(payload.get("created_at") or ""),
        dashboard=OperationsDashboard(
            sessions_observed=int(dashboard.get("sessions_observed") or 0),
            worker_runs=int(dashboard.get("worker_runs") or 0),
            worker_errors=int(dashboard.get("worker_errors") or 0),
            notification_dead_letters=int(dashboard.get("notification_dead_letters") or 0),
            calendar_dead_letters=int(dashboard.get("calendar_dead_letters") or 0),
            active_alerts=int(dashboard.get("active_alerts") or 0),
            critical_alerts=int(dashboard.get("critical_alerts") or 0),
            state_counts={str(key): int(value) for key, value in dict(dashboard.get("state_counts") or {}).items()},
            action_items=[str(item) for item in dashboard.get("action_items") or []],
        ),
        alerts=[_normalize_alert(alert) for alert in payload.get("alerts") or []],
    )


def render_operations_dashboard_snapshots(snapshots: list[OperationsDashboardSnapshot]) -> str:
    lines = ["Operations dashboard snapshots:"]
    if not snapshots:
        lines.append("- none")
        return "\n".join(lines)
    for snapshot in snapshots:
        lines.append(
            f"- {snapshot.snapshot_id} at {snapshot.created_at}: "
            f"sessions={snapshot.dashboard.sessions_observed} "
            f"alerts={snapshot.dashboard.active_alerts} critical={snapshot.dashboard.critical_alerts}"
        )
    return "\n".join(lines)


def build_operations_dashboard_trend_report(
    snapshots: list[OperationsDashboardSnapshot],
    window: int = 7,
) -> OperationsTrendReport:
    window = max(1, int(window))
    selected = sorted(snapshots, key=lambda snapshot: _timestamp_sort_key(snapshot.created_at))[-window:]
    latest = selected[-1] if selected else None
    previous = selected[-2] if len(selected) >= 2 else None

    if latest is None:
        return OperationsTrendReport(
            window=window,
            snapshot_count=0,
            latest_snapshot=None,
            previous_snapshot=None,
            metrics=[],
            summary="No operations dashboard snapshots are persisted yet.",
            anomalies=[],
            action_items=["Persist dashboard snapshots before analyzing operational trends."],
        )

    latest_metrics = _dashboard_trend_metrics(latest.dashboard)
    previous_metrics = _dashboard_trend_metrics(previous.dashboard) if previous else latest_metrics
    metrics = [
        _operations_trend_metric(name, latest_metrics.get(name, 0), previous_metrics.get(name, 0))
        for name in sorted(set(latest_metrics) | set(previous_metrics))
    ]
    anomalies = _operations_trend_anomalies(metrics)
    action_items = _operations_trend_action_items(metrics, anomalies, previous is None)
    if previous is None:
        summary = f"Baseline snapshot {latest.snapshot_id} captured; add another snapshot for delta analysis."
    else:
        summary = _operations_trend_summary(latest, previous, metrics)
    return OperationsTrendReport(
        window=window,
        snapshot_count=len(selected),
        latest_snapshot=latest,
        previous_snapshot=previous,
        metrics=metrics,
        summary=summary,
        anomalies=anomalies,
        action_items=action_items,
    )


def render_operations_dashboard_trend_report(report: OperationsTrendReport) -> str:
    lines = [
        "Operations dashboard trends:",
        f"- window: {report.window}",
        f"- snapshots_analyzed: {report.snapshot_count}",
        f"- latest_snapshot: {report.latest_snapshot.snapshot_id if report.latest_snapshot else '-'}",
        f"- previous_snapshot: {report.previous_snapshot.snapshot_id if report.previous_snapshot else '-'}",
        f"- summary: {report.summary}",
        "- metrics:",
    ]
    if not report.metrics:
        lines.append("  - none")
    else:
        for metric in report.metrics:
            if report.previous_snapshot is None:
                lines.append(f"  - {metric.name}: {metric.current} (baseline)")
            else:
                lines.append(
                    f"  - {metric.name}: {metric.current} "
                    f"(previous {metric.previous}, delta {_signed_int(metric.delta)}, "
                    f"{_format_delta_percent(metric.delta_percent)})"
                )
    lines.append("- anomalies:")
    if report.anomalies:
        for anomaly in report.anomalies:
            lines.append(f"  - {anomaly}")
    else:
        lines.append("  - none")
    lines.append("- action_items:")
    for item in report.action_items:
        lines.append(f"  - {item}")
    return "\n".join(lines)


def build_operations_trend_alert_rules(config_json: str | None = None) -> list[OperationsTrendAlertRule]:
    if config_json:
        return _trend_alert_rules_from_config(config_json)
    return [
        OperationsTrendAlertRule(
            metric="critical_alerts",
            severity="critical",
            route="incident-oncall",
            escalation="page immediately when critical alerts increase",
            owner="platform-oncall",
            absolute_threshold=1,
            delta_threshold=1,
            action_template="Review critical alerts and confirm incident owner for {metric}.",
        ),
        OperationsTrendAlertRule(
            metric="worker_errors",
            severity="critical",
            route="workflow-oncall",
            escalation="page when worker errors appear or increase",
            owner="workflow-oncall",
            absolute_threshold=1,
            delta_threshold=1,
            action_template="Inspect worker failures and replay affected sessions.",
        ),
        OperationsTrendAlertRule(
            metric="notification_dead_letters",
            severity="warning",
            route="workflow-oncall",
            escalation="create ticket when notification dead letters increase",
            owner="workflow-oncall",
            absolute_threshold=1,
            delta_threshold=1,
            action_template="Replay notification dead letters after provider recovery.",
        ),
        OperationsTrendAlertRule(
            metric="calendar_dead_letters",
            severity="warning",
            route="collaboration-platform-oncall",
            escalation="create ticket when calendar dead letters increase",
            owner="collaboration-oncall",
            absolute_threshold=1,
            delta_threshold=1,
            action_template="Replay calendar dead letters or create manual events.",
        ),
        OperationsTrendAlertRule(
            metric="active_alerts",
            severity="warning",
            route="travel-ops",
            escalation="create ticket when total alerts grow by 50 percent",
            owner="travel-ops",
            delta_percent_threshold=50.0,
            delta_threshold=2,
            action_template="Review alert mix and update routing if {metric} keeps growing.",
        ),
        OperationsTrendAlertRule(
            metric="state:ORDER_FAILED",
            severity="critical",
            route="supplier-and-booking-oncall",
            escalation="page when failed orders appear",
            owner="booking-oncall",
            absolute_threshold=1,
            delta_threshold=1,
            action_template="Run supplier reconciliation and compensation for failed orders.",
        ),
    ]


def build_operations_action_sla_policy(config_json: str | None = None) -> OperationsActionSlaPolicy:
    if not config_json:
        return OperationsActionSlaPolicy(
            owner_routes={
                "booking-oncall": "supplier-and-booking-oncall",
                "compliance-platform-oncall": "compliance-platform-oncall",
                "iam-platform-oncall": "iam-platform-oncall",
                "platform-oncall": "incident-oncall",
                "workflow-oncall": "workflow-oncall",
            }
        )
    payload = json.loads(config_json)
    if not isinstance(payload, dict):
        raise ValueError("Action SLA policy config must be an object.")
    owner_routes = payload.get("owner_routes") or {}
    if not isinstance(owner_routes, dict):
        raise ValueError("Action SLA policy owner_routes must be an object.")
    return OperationsActionSlaPolicy(
        warning_after_hours=float(payload.get("warning_after_hours") or 24.0),
        critical_after_hours=float(payload.get("critical_after_hours") or 48.0),
        default_route=str(payload.get("default_route") or "travel-ops"),
        escalation_template=str(
            payload.get("escalation_template") or "Notify {owner} via {route}: {title}"
        ),
        owner_routes={str(key): str(value) for key, value in owner_routes.items()},
    )


def evaluate_operations_trend_alerts(
    trend_report: OperationsTrendReport,
    rules: list[OperationsTrendAlertRule] | None = None,
) -> list[OperationsTrendAlert]:
    rules = rules or build_operations_trend_alert_rules()
    metric_map = {metric.name: metric for metric in trend_report.metrics}
    alerts: list[OperationsTrendAlert] = []
    latest_id = trend_report.latest_snapshot.snapshot_id if trend_report.latest_snapshot else "NO-SNAPSHOT"
    for rule in rules:
        metric = metric_map.get(rule.metric)
        if metric is None:
            continue
        reason = _trend_alert_reason(metric, rule, trend_report.previous_snapshot is None)
        if reason is None:
            continue
        alert_id = _stable_id("TREND", latest_id, rule.metric, str(metric.current), str(metric.delta))
        alerts.append(
            OperationsTrendAlert(
                alert_id=alert_id,
                metric=metric.name,
                severity=rule.severity,
                route=rule.route,
                escalation=rule.escalation,
                owner=rule.owner,
                current=metric.current,
                previous=metric.previous,
                delta=metric.delta,
                delta_percent=metric.delta_percent,
                reason=reason,
                action_item=rule.action_template.format(metric=metric.name),
            )
        )
    alerts.sort(key=lambda alert: (_severity_rank(alert.severity), alert.metric))
    return alerts


def render_operations_trend_alerts(alerts: list[OperationsTrendAlert]) -> str:
    lines = ["Operations trend alerts:"]
    if not alerts:
        lines.append("- none")
        return "\n".join(lines)
    for alert in alerts:
        lines.append(
            f"- {alert.severity} {alert.metric} -> {alert.route} "
            f"current={alert.current} previous={alert.previous} delta={_signed_int(alert.delta)}"
        )
        lines.append(f"  owner: {alert.owner}")
        lines.append(f"  escalation: {alert.escalation}")
        lines.append(f"  reason: {alert.reason}")
        lines.append(f"  action: {alert.action_item}")
    return "\n".join(lines)


def render_operations_trend_alerts_json(alerts: list[OperationsTrendAlert]) -> str:
    return json.dumps({"alerts": [operations_trend_alert_to_dict(alert) for alert in alerts]}, ensure_ascii=False)


def operations_trend_alert_to_dict(alert: OperationsTrendAlert) -> dict[str, Any]:
    return {
        "alert_id": alert.alert_id,
        "metric": alert.metric,
        "severity": alert.severity,
        "route": alert.route,
        "escalation": alert.escalation,
        "owner": alert.owner,
        "current": alert.current,
        "previous": alert.previous,
        "delta": alert.delta,
        "delta_percent": alert.delta_percent,
        "reason": alert.reason,
        "action_item": alert.action_item,
    }


def operations_trend_alert_from_dict(payload: dict[str, Any]) -> OperationsTrendAlert:
    delta_percent = payload.get("delta_percent")
    return OperationsTrendAlert(
        alert_id=str(payload["alert_id"]),
        metric=str(payload["metric"]),
        severity=str(payload.get("severity") or "warning"),
        route=str(payload.get("route") or "travel-ops"),
        escalation=str(payload.get("escalation") or "create ticket"),
        owner=str(payload.get("owner") or "travel-ops"),
        current=int(payload.get("current") or 0),
        previous=int(payload.get("previous") or 0),
        delta=int(payload.get("delta") or 0),
        delta_percent=float(delta_percent) if delta_percent is not None else None,
        reason=str(payload.get("reason") or ""),
        action_item=str(payload.get("action_item") or ""),
    )


def build_postmortem_action_items(
    postmortem: OperationsPostmortemReport,
    owner: str = "travel-ops",
    eta: str | None = None,
    created_at: str | None = None,
) -> list[OperationsActionItem]:
    created_at = created_at or datetime.now(timezone.utc).isoformat()
    items: list[OperationsActionItem] = []
    for index, title in enumerate(postmortem.action_items, start=1):
        action_id = _stable_id("ACT", postmortem.incident_id, title)
        items.append(
            OperationsActionItem(
                action_id=action_id,
                source_type="postmortem",
                source_id=postmortem.incident_id,
                title=title,
                owner=_action_owner(title, owner),
                status="OPEN",
                eta=eta,
                created_at=created_at,
                updated_at=created_at,
                evidence=[*postmortem.evidence[:3], f"postmortem_action_index={index}"],
            )
        )
    return items


def build_trend_alert_action_items(
    alerts: list[OperationsTrendAlert],
    eta: str | None = None,
    created_at: str | None = None,
) -> list[OperationsActionItem]:
    created_at = created_at or datetime.now(timezone.utc).isoformat()
    return [
        OperationsActionItem(
            action_id=_stable_id("ACT", alert.alert_id, alert.action_item),
            source_type="trend_alert",
            source_id=alert.alert_id,
            title=alert.action_item,
            owner=alert.owner,
            status="OPEN",
            eta=eta,
            created_at=created_at,
            updated_at=created_at,
            evidence=[
                f"metric={alert.metric}",
                f"current={alert.current}",
                f"previous={alert.previous}",
                f"delta={alert.delta}",
                f"reason={alert.reason}",
            ],
        )
        for alert in alerts
    ]


def close_operations_action_item(
    item: OperationsActionItem,
    closure_note: str,
    updated_at: str | None = None,
) -> OperationsActionItem:
    updated_at = updated_at or datetime.now(timezone.utc).isoformat()
    return OperationsActionItem(
        action_id=item.action_id,
        source_type=item.source_type,
        source_id=item.source_id,
        title=item.title,
        owner=item.owner,
        status="CLOSED",
        eta=item.eta,
        created_at=item.created_at,
        updated_at=updated_at,
        evidence=item.evidence,
        closure_note=closure_note,
    )


def operations_action_item_to_dict(item: OperationsActionItem) -> dict[str, Any]:
    return {
        "action_id": item.action_id,
        "source_type": item.source_type,
        "source_id": item.source_id,
        "title": item.title,
        "owner": item.owner,
        "status": item.status,
        "eta": item.eta,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
        "evidence": item.evidence,
        "closure_note": item.closure_note,
    }


def operations_action_item_from_dict(payload: dict[str, Any]) -> OperationsActionItem:
    return OperationsActionItem(
        action_id=str(payload["action_id"]),
        source_type=str(payload.get("source_type") or ""),
        source_id=str(payload.get("source_id") or ""),
        title=str(payload.get("title") or ""),
        owner=str(payload.get("owner") or "travel-ops"),
        status=str(payload.get("status") or "OPEN"),
        eta=str(payload["eta"]) if payload.get("eta") is not None else None,
        created_at=str(payload.get("created_at") or ""),
        updated_at=str(payload.get("updated_at") or ""),
        evidence=[str(item) for item in payload.get("evidence") or []],
        closure_note=str(payload["closure_note"]) if payload.get("closure_note") is not None else None,
    )


def render_operations_action_items(items: list[OperationsActionItem]) -> str:
    lines = ["Operations action items:"]
    if not items:
        lines.append("- none")
        return "\n".join(lines)
    for item in items:
        lines.append(f"- {item.action_id}: {item.status} {item.title}")
        lines.append(f"  owner: {item.owner}")
        lines.append(f"  source: {item.source_type}/{item.source_id}")
        lines.append(f"  eta: {item.eta or '-'}")
        if item.closure_note:
            lines.append(f"  closure: {item.closure_note}")
    return "\n".join(lines)


def build_operations_knowledge_entries(
    postmortem: OperationsPostmortemReport | None = None,
    trend_alerts: list[OperationsTrendAlert] | None = None,
    action_items: list[OperationsActionItem] | None = None,
    created_at: str | None = None,
) -> list[OperationsKnowledgeEntry]:
    created_at = created_at or datetime.now(timezone.utc).isoformat()
    entries: list[OperationsKnowledgeEntry] = []
    if postmortem is not None:
        entries.append(
            OperationsKnowledgeEntry(
                entry_id=_stable_id("KB", postmortem.incident_id, postmortem.primary_signal),
                topic=postmortem.primary_signal,
                title=f"{postmortem.severity.upper()} {postmortem.primary_signal} playbook",
                summary=postmortem.summary,
                signals=[
                    *postmortem.root_causes[:5],
                    *[alert["alert_type"] for alert in postmortem.related_alerts[:5]],
                ],
                recommended_actions=postmortem.action_items,
                source_refs=[postmortem.incident_id, *postmortem.related_sessions[:5]],
                created_at=created_at,
                updated_at=created_at,
            )
        )
    for alert in trend_alerts or []:
        entries.append(
            OperationsKnowledgeEntry(
                entry_id=_stable_id("KB", alert.metric, alert.route, alert.action_item),
                topic=alert.metric,
                title=f"Trend alert response for {alert.metric}",
                summary=f"{alert.reason}; route={alert.route}; escalation={alert.escalation}.",
                signals=[alert.metric, alert.severity, alert.route],
                recommended_actions=[alert.action_item],
                source_refs=[alert.alert_id],
                created_at=created_at,
                updated_at=created_at,
            )
        )
    closed_items = [item for item in action_items or [] if item.status == "CLOSED"]
    if closed_items:
        entries.append(
            OperationsKnowledgeEntry(
                entry_id=_stable_id("KB", "closed-actions", *[item.action_id for item in closed_items[:5]]),
                topic="action_item_closure",
                title="Closed operations action follow-up",
                summary=f"{len(closed_items)} operations action items were closed and can be reused as follow-up guidance.",
                signals=[item.source_type for item in closed_items],
                recommended_actions=[item.closure_note or item.title for item in closed_items[:5]],
                source_refs=[item.action_id for item in closed_items[:5]],
                created_at=created_at,
                updated_at=created_at,
            )
        )
    return _dedupe_knowledge_entries(entries)


def operations_knowledge_entry_to_dict(entry: OperationsKnowledgeEntry) -> dict[str, Any]:
    return {
        "entry_id": entry.entry_id,
        "topic": entry.topic,
        "title": entry.title,
        "summary": entry.summary,
        "signals": entry.signals,
        "recommended_actions": entry.recommended_actions,
        "source_refs": entry.source_refs,
        "created_at": entry.created_at,
        "updated_at": entry.updated_at,
    }


def operations_knowledge_entry_from_dict(payload: dict[str, Any]) -> OperationsKnowledgeEntry:
    return OperationsKnowledgeEntry(
        entry_id=str(payload["entry_id"]),
        topic=str(payload.get("topic") or ""),
        title=str(payload.get("title") or ""),
        summary=str(payload.get("summary") or ""),
        signals=[str(item) for item in payload.get("signals") or []],
        recommended_actions=[str(item) for item in payload.get("recommended_actions") or []],
        source_refs=[str(item) for item in payload.get("source_refs") or []],
        created_at=str(payload.get("created_at") or ""),
        updated_at=str(payload.get("updated_at") or ""),
    )


def render_operations_knowledge_entries(entries: list[OperationsKnowledgeEntry]) -> str:
    lines = ["Operations knowledge entries:"]
    if not entries:
        lines.append("- none")
        return "\n".join(lines)
    for entry in entries:
        lines.append(f"- {entry.entry_id}: {entry.title}")
        lines.append(f"  topic: {entry.topic}")
        lines.append(f"  summary: {entry.summary}")
        if entry.recommended_actions:
            lines.append(f"  actions: {'; '.join(entry.recommended_actions)}")
    return "\n".join(lines)


def search_operations_knowledge(
    entries: list[OperationsKnowledgeEntry],
    query: str,
    limit: int = 5,
) -> OperationsKnowledgeSearchReport:
    terms = _search_terms(query)
    hits: list[OperationsKnowledgeSearchHit] = []
    for entry in entries:
        score, matched_terms = _knowledge_entry_score(entry, terms)
        if score <= 0:
            continue
        hits.append(OperationsKnowledgeSearchHit(entry=entry, score=score, matched_terms=matched_terms))
    hits.sort(key=lambda hit: (-hit.score, hit.entry.updated_at, hit.entry.title))
    selected = hits[: max(1, int(limit))]
    suggested_actions = _dedupe(
        [action for hit in selected for action in hit.entry.recommended_actions]
    )[: max(1, int(limit))]
    return OperationsKnowledgeSearchReport(
        query=query,
        total_entries=len(entries),
        hits=selected,
        suggested_actions=suggested_actions,
    )


def render_operations_knowledge_search_report(report: OperationsKnowledgeSearchReport) -> str:
    lines = [
        "Operations knowledge search:",
        f"- query: {report.query}",
        f"- total_entries: {report.total_entries}",
        "- hits:",
    ]
    if not report.hits:
        lines.append("  - none")
    else:
        for hit in report.hits:
            lines.append(f"  - {hit.entry.entry_id}: score={hit.score} title={hit.entry.title}")
            lines.append(f"    topic: {hit.entry.topic}")
            lines.append(f"    matched: {', '.join(hit.matched_terms) if hit.matched_terms else '-'}")
    lines.append("- suggested_actions:")
    if report.suggested_actions:
        for action in report.suggested_actions:
            lines.append(f"  - {action}")
    else:
        lines.append("  - none")
    return "\n".join(lines)


def evaluate_operations_action_sla(
    items: list[OperationsActionItem],
    policy: OperationsActionSlaPolicy | None = None,
    now: str | None = None,
) -> OperationsActionSlaReport:
    policy = policy or OperationsActionSlaPolicy()
    now = now or datetime.now(timezone.utc).isoformat()
    now_ts = _timestamp_sort_key(now)
    open_items = [item for item in items if item.status.upper() != "CLOSED"]
    findings: list[OperationsActionSlaFinding] = []
    for item in open_items:
        anchor = item.eta or item.created_at or item.updated_at
        anchor_ts = _timestamp_sort_key(anchor)
        if anchor_ts <= 0 or now_ts <= anchor_ts:
            age_hours = 0.0
        else:
            age_hours = round((now_ts - anchor_ts) / 3600.0, 2)
        severity = ""
        overdue_hours = 0.0
        if age_hours >= policy.critical_after_hours:
            severity = "critical"
            overdue_hours = round(age_hours - policy.critical_after_hours, 2)
        elif age_hours >= policy.warning_after_hours:
            severity = "warning"
            overdue_hours = round(age_hours - policy.warning_after_hours, 2)
        if not severity:
            continue
        route = policy.owner_routes.get(item.owner) or policy.default_route
        reason = f"open for {age_hours:.2f}h; threshold={policy.critical_after_hours if severity == 'critical' else policy.warning_after_hours:.2f}h"
        escalation = policy.escalation_template.format(owner=item.owner, route=route, title=item.title)
        findings.append(
            OperationsActionSlaFinding(
                action_id=item.action_id,
                severity=severity,
                owner=item.owner,
                route=route,
                age_hours=age_hours,
                overdue_hours=overdue_hours,
                reason=reason,
                escalation=escalation,
                reminder=f"{item.action_id} remains {item.status}: {item.title}",
            )
        )
    findings.sort(key=lambda finding: (_severity_rank(finding.severity), -finding.age_hours, finding.action_id))
    summary = (
        f"{len(findings)} SLA findings across {len(open_items)} open action items."
        if findings
        else f"No SLA findings across {len(open_items)} open action items."
    )
    return OperationsActionSlaReport(
        now=now,
        total_open=len(open_items),
        findings=findings,
        escalation_count=len(findings),
        summary=summary,
    )


def render_operations_action_sla_report(report: OperationsActionSlaReport) -> str:
    lines = [
        "Operations action SLA:",
        f"- now: {report.now}",
        f"- total_open: {report.total_open}",
        f"- escalation_count: {report.escalation_count}",
        f"- summary: {report.summary}",
        "- findings:",
    ]
    if not report.findings:
        lines.append("  - none")
    else:
        for finding in report.findings:
            lines.append(
                f"  - {finding.severity} {finding.action_id}: owner={finding.owner} "
                f"route={finding.route} age_hours={finding.age_hours:.2f}"
            )
            lines.append(f"    reason: {finding.reason}")
            lines.append(f"    escalation: {finding.escalation}")
    return "\n".join(lines)


def build_operations_closed_loop_report(
    trend_alerts: list[OperationsTrendAlert] | None = None,
    action_items: list[OperationsActionItem] | None = None,
    knowledge_entries: list[OperationsKnowledgeEntry] | None = None,
    sla_report: OperationsActionSlaReport | None = None,
    generated_at: str | None = None,
) -> OperationsClosedLoopReport:
    trend_alerts = trend_alerts or []
    action_items = action_items or []
    knowledge_entries = knowledge_entries or []
    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    closed = [item for item in action_items if item.status.upper() == "CLOSED"]
    open_items = [item for item in action_items if item.status.upper() != "CLOSED"]
    closure_rate = round((len(closed) / len(action_items)) * 100, 1) if action_items else 0.0
    knowledge_topics = dict(Counter(entry.topic for entry in knowledge_entries))
    source_counts = dict(Counter(item.source_type for item in action_items))
    action_items_overdue = len(sla_report.findings) if sla_report else 0
    recommendations = _closed_loop_recommendations(
        trend_alerts=trend_alerts,
        action_items=action_items,
        open_items=open_items,
        closure_rate=closure_rate,
        knowledge_entries=knowledge_entries,
        action_items_overdue=action_items_overdue,
    )
    return OperationsClosedLoopReport(
        generated_at=generated_at,
        trend_alerts=len(trend_alerts),
        action_items_total=len(action_items),
        action_items_open=len(open_items),
        action_items_closed=len(closed),
        action_items_overdue=action_items_overdue,
        closure_rate=closure_rate,
        knowledge_entries=len(knowledge_entries),
        knowledge_topics=knowledge_topics,
        source_counts=source_counts,
        recommendations=recommendations,
    )


def render_operations_closed_loop_report(report: OperationsClosedLoopReport) -> str:
    lines = [
        "Operations closed-loop report:",
        f"- generated_at: {report.generated_at}",
        f"- trend_alerts: {report.trend_alerts}",
        f"- action_items_total: {report.action_items_total}",
        f"- action_items_open: {report.action_items_open}",
        f"- action_items_closed: {report.action_items_closed}",
        f"- action_items_overdue: {report.action_items_overdue}",
        f"- closure_rate: {report.closure_rate:.1f}%",
        f"- knowledge_entries: {report.knowledge_entries}",
    ]
    _append_count_section(lines, "knowledge_topics", report.knowledge_topics)
    _append_count_section(lines, "action_sources", report.source_counts)
    _append_list_section(lines, "recommendations", report.recommendations)
    return "\n".join(lines)


def build_operations_multidimensional_view(
    sessions: list[TravelContext] | None = None,
    alerts: list[dict[str, Any]] | None = None,
    worker_runs: list[WorkerRunRecord] | None = None,
    dead_letters: list[DeadLetterNotification] | None = None,
    calendar_dead_letters: list[DeadLetterCalendarSync] | None = None,
    limit: int = 5,
) -> OperationsMultiDimensionalView:
    sessions = sessions or []
    alerts = alerts or []
    worker_runs = worker_runs or []
    dead_letters = dead_letters or []
    calendar_dead_letters = calendar_dead_letters or []
    limit = max(1, int(limit))

    groups = [
        _dimension_group(
            "departments",
            sessions,
            lambda context: [_dimension_key(context.request.department, "unknown")],
            limit,
        ),
        _dimension_group("users", sessions, lambda context: [context.request.user_id], limit),
        _dimension_group(
            "routes",
            sessions,
            lambda context: [f"{context.request.origin_city}->{context.request.destination_city}"],
            limit,
        ),
        _dimension_group(
            "origin_cities",
            sessions,
            lambda context: [context.request.origin_city],
            limit,
        ),
        _dimension_group(
            "destination_cities",
            sessions,
            lambda context: [context.request.destination_city],
            limit,
        ),
        _dimension_group(
            "hotel_suppliers",
            sessions,
            lambda context: [_dimension_key(context.selected_hotel.name if context.selected_hotel else None, "unselected")],
            limit,
        ),
        _dimension_group(
            "transport_providers",
            sessions,
            lambda context: [
                _dimension_key(context.selected_transport.provider if context.selected_transport else None, "unselected")
            ],
            limit,
        ),
        _dimension_group("policy_sources", sessions, _policy_source_keys, limit),
    ]
    state_counts = dict(Counter(context.state for context in sessions))
    alert_counts, severity_counts = _alert_counters(alerts)
    dead_letter_counts = {
        "notification": len(dead_letters),
        "calendar": len(calendar_dead_letters),
    }
    worker_errors = sum(len(record.errors) for record in worker_runs)
    total_alerts = sum(alert_counts.values())
    summary = (
        f"{len(sessions)} sessions across {len(state_counts)} states; "
        f"{worker_errors} worker errors; {total_alerts} alert signals; "
        f"{sum(dead_letter_counts.values())} dead letters."
    )
    action_items = _operations_dimension_action_items(
        sessions=sessions,
        worker_errors=worker_errors,
        alert_counts=alert_counts,
        severity_counts=severity_counts,
        dead_letter_counts=dead_letter_counts,
    )
    return OperationsMultiDimensionalView(
        total_sessions=len(sessions),
        worker_runs=len(worker_runs),
        worker_errors=worker_errors,
        state_counts=state_counts,
        alert_counts=alert_counts,
        severity_counts=severity_counts,
        dead_letter_counts=dead_letter_counts,
        groups=groups,
        summary=summary,
        action_items=action_items,
    )


def render_operations_multidimensional_view(view: OperationsMultiDimensionalView) -> str:
    lines = [
        "Operations multi-dimensional view:",
        f"- summary: {view.summary}",
        f"- total_sessions: {view.total_sessions}",
        f"- worker_runs: {view.worker_runs}",
        f"- worker_errors: {view.worker_errors}",
    ]
    _append_count_section(lines, "states", view.state_counts)
    _append_count_section(lines, "alert_types", view.alert_counts)
    _append_count_section(lines, "alert_severities", view.severity_counts)
    _append_count_section(lines, "dead_letters", view.dead_letter_counts)
    lines.append("- dimensions:")
    for group in view.groups:
        lines.append(f"  - {group.name}:")
        if not group.rows:
            lines.append("    - none")
            continue
        for row in group.rows:
            lines.append(
                f"    - {row.key}: sessions={row.sessions} orders={row.orders} "
                f"compensations={row.compensations} policy_violations={row.policy_violations} "
                f"failed={row.failed}"
            )
    lines.append("- action_items:")
    for item in view.action_items:
        lines.append(f"  - {item}")
    return "\n".join(lines)


def build_operations_postmortem_report(
    sessions: list[TravelContext] | None = None,
    snapshots: list[OperationsDashboardSnapshot] | None = None,
    oncall_statuses: list[OnCallTicketStatus] | None = None,
    alerts: list[dict[str, Any]] | None = None,
    worker_runs: list[WorkerRunRecord] | None = None,
    dead_letters: list[DeadLetterNotification] | None = None,
    calendar_dead_letters: list[DeadLetterCalendarSync] | None = None,
    drill_report: OperationsDrillReport | None = None,
    incident_id: str | None = None,
    generated_at: str | None = None,
) -> OperationsPostmortemReport:
    sessions = sessions or []
    snapshots = sorted(snapshots or [], key=lambda snapshot: _timestamp_sort_key(snapshot.created_at))
    oncall_statuses = sorted(
        oncall_statuses or [],
        key=lambda status: _timestamp_sort_key(status.updated_at),
        reverse=True,
    )
    alerts = [_normalize_alert(alert) for alert in alerts or []]
    worker_runs = worker_runs or []
    dead_letters = dead_letters or []
    calendar_dead_letters = calendar_dead_letters or []
    generated_at = generated_at or datetime.now(timezone.utc).isoformat()

    dimension_view = build_operations_multidimensional_view(
        sessions=sessions,
        alerts=alerts,
        worker_runs=worker_runs,
        dead_letters=dead_letters,
        calendar_dead_letters=calendar_dead_letters,
        limit=3,
    )
    failed_sessions = [context for context in sessions if _is_failure_state(context.state)]
    compensated_sessions = [context for context in sessions if _session_compensation_count(context)]
    unresolved_tickets = [
        status for status in oncall_statuses if status.status.upper() not in {"RESOLVED", "CLOSED", "DONE"}
    ]
    primary_signal = _postmortem_primary_signal(
        dimension_view.alert_counts,
        failed_sessions,
        dead_letters,
        calendar_dead_letters,
        unresolved_tickets,
    )
    severity = _postmortem_severity(
        dimension_view.severity_counts,
        failed_sessions,
        dead_letters,
        calendar_dead_letters,
        unresolved_tickets,
    )
    incident_id = incident_id or _postmortem_incident_id(primary_signal, generated_at, oncall_statuses)
    impact = _postmortem_impact(dimension_view, failed_sessions, compensated_sessions, unresolved_tickets)
    timeline = _postmortem_timeline(snapshots, worker_runs, oncall_statuses)
    root_causes = _postmortem_root_causes(
        dimension_view.alert_counts,
        failed_sessions,
        dead_letters,
        calendar_dead_letters,
        unresolved_tickets,
    )
    related_sessions = _related_session_ids(sessions, failed_sessions)
    drill_findings = [
        f"{drill.scenario}: {drill.status} - {drill.summary}"
        for drill in (drill_report.drills if drill_report else [])
    ]
    evidence = _postmortem_evidence(
        snapshots=snapshots,
        worker_runs=worker_runs,
        alert_counts=dimension_view.alert_counts,
        related_sessions=related_sessions,
        oncall_statuses=oncall_statuses,
    )
    action_items = _postmortem_action_items(
        root_causes=root_causes,
        latest_snapshot=snapshots[-1] if snapshots else None,
        drill_report=drill_report,
        unresolved_tickets=unresolved_tickets,
    )
    summary = (
        f"{severity.upper()} {primary_signal}; {len(sessions)} sessions observed, "
        f"{len(failed_sessions)} failed sessions, {len(compensated_sessions)} compensated sessions, "
        f"{len(unresolved_tickets)} unresolved tickets."
    )
    return OperationsPostmortemReport(
        incident_id=incident_id,
        generated_at=generated_at,
        severity=severity,
        primary_signal=primary_signal,
        summary=summary,
        impact=impact,
        timeline=timeline,
        root_causes=root_causes,
        evidence=evidence,
        action_items=action_items,
        related_sessions=related_sessions,
        related_tickets=oncall_statuses[:5],
        related_alerts=alerts[:5],
        drill_findings=drill_findings,
    )


def render_operations_postmortem_report(report: OperationsPostmortemReport) -> str:
    lines = [
        "Operations incident postmortem:",
        f"- incident_id: {report.incident_id}",
        f"- generated_at: {report.generated_at}",
        f"- severity: {report.severity}",
        f"- primary_signal: {report.primary_signal}",
        f"- summary: {report.summary}",
    ]
    _append_list_section(lines, "impact", report.impact)
    lines.append("- timeline:")
    if report.timeline:
        for event in report.timeline:
            lines.append(f"  - {event.timestamp} [{event.source}] {event.detail}")
    else:
        lines.append("  - none")
    _append_list_section(lines, "root_causes", report.root_causes)
    _append_list_section(lines, "evidence", report.evidence)
    _append_list_section(lines, "related_sessions", report.related_sessions)
    lines.append("- related_tickets:")
    if report.related_tickets:
        for status in report.related_tickets:
            lines.append(
                f"  - {status.ticket_id}: {status.status} assignee={status.assignee or '-'} "
                f"updated_at={status.updated_at}"
            )
    else:
        lines.append("  - none")
    lines.append("- related_alerts:")
    if report.related_alerts:
        for alert in report.related_alerts:
            lines.append(
                f"  - {alert['severity']} {alert['alert_type']} value={alert['value']} "
                f"message={alert['message']}"
            )
    else:
        lines.append("  - none")
    _append_list_section(lines, "drill_findings", report.drill_findings)
    _append_list_section(lines, "action_items", report.action_items)
    return "\n".join(lines)


def build_alert_route_rules(config_json: str | None = None) -> list[AlertRouteRule]:
    if config_json:
        return _alert_route_rules_from_config(config_json)
    return [
        AlertRouteRule(
            alert_type="worker_errors",
            severity="critical",
            route="workflow-oncall",
            escalation="page immediately when value >= 1 in production",
            silence_hint="silence only during worker maintenance window",
        ),
        AlertRouteRule(
            alert_type="order_failed",
            severity="critical",
            route="supplier-and-booking-oncall",
            escalation="page immediately and open compensation ticket",
            silence_hint="silence only for scoped supplier outage with active incident",
        ),
        AlertRouteRule(
            alert_type="audit_sink_failed",
            severity="critical",
            route="compliance-platform-oncall",
            escalation="page immediately and preserve local audit buffer",
            silence_hint="do not silence unless audit replay backlog is stable",
        ),
        AlertRouteRule(
            alert_type="permission_denied",
            severity="warning",
            route="iam-and-travel-ops",
            escalation="create ticket when repeated denies affect a department",
            silence_hint="silence by user or department after policy owner approval",
        ),
        AlertRouteRule(
            alert_type="permission_center_fallback",
            severity="warning",
            route="iam-platform-oncall",
            escalation="page if fallback lasts longer than one check interval",
            silence_hint="silence only during IAM maintenance with local policy verified",
        ),
        AlertRouteRule(
            alert_type="notification_dead_letters",
            severity="warning",
            route="workflow-oncall",
            escalation="create ticket and replay after notification recovery",
            silence_hint="silence by channel during notification provider maintenance",
        ),
        AlertRouteRule(
            alert_type="calendar_dead_letters",
            severity="warning",
            route="collaboration-platform-oncall",
            escalation="create ticket and replay or manually create calendar events",
            silence_hint="silence by calendar provider during planned maintenance",
        ),
    ]


def render_alert_route_rules(rules: list[AlertRouteRule]) -> str:
    lines = ["Alert route rules:"]
    for rule in rules:
        lines.append(f"- {rule.severity} {rule.alert_type} -> {rule.route}")
        lines.append(f"  escalation: {rule.escalation}")
        lines.append(f"  silence: {rule.silence_hint}")
    return "\n".join(lines)


def render_alert_route_rules_json(rules: list[AlertRouteRule]) -> str:
    return json.dumps(
        {
            "rules": [
                {
                    "alert_type": rule.alert_type,
                    "severity": rule.severity,
                    "route": rule.route,
                    "escalation": rule.escalation,
                    "silence_hint": rule.silence_hint,
                }
                for rule in rules
            ]
        },
        ensure_ascii=False,
    )


def _alert_route_rules_from_config(config_json: str) -> list[AlertRouteRule]:
    payload = json.loads(config_json)
    items = payload.get("rules") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        raise ValueError("Alert route rules config must be a list or an object with a rules list.")
    rules: list[AlertRouteRule] = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Each alert route rule must be an object.")
        rules.append(
            AlertRouteRule(
                alert_type=str(item["alert_type"]),
                severity=str(item.get("severity") or "warning"),
                route=str(item["route"]),
                escalation=str(item.get("escalation") or "create ticket"),
                silence_hint=str(item.get("silence_hint") or item.get("silence") or "silence with owner approval"),
            )
        )
    return rules


def _trend_alert_rules_from_config(config_json: str) -> list[OperationsTrendAlertRule]:
    payload = json.loads(config_json)
    items = payload.get("rules") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        raise ValueError("Trend alert rules config must be a list or an object with a rules list.")
    rules: list[OperationsTrendAlertRule] = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Each trend alert rule must be an object.")
        rules.append(
            OperationsTrendAlertRule(
                metric=str(item["metric"]),
                severity=str(item.get("severity") or "warning"),
                route=str(item.get("route") or "travel-ops"),
                escalation=str(item.get("escalation") or "create ticket"),
                owner=str(item.get("owner") or "travel-ops"),
                absolute_threshold=_optional_int(item.get("absolute_threshold")),
                delta_threshold=_optional_int(item.get("delta_threshold")),
                delta_percent_threshold=_optional_float(item.get("delta_percent_threshold")),
                action_template=str(
                    item.get("action_template") or item.get("action") or "Investigate operations trend for {metric}."
                ),
            )
        )
    return rules


def build_operations_drill_report(
    settings: IntegrationSettings,
    worker_runs: list[WorkerRunRecord] | None = None,
    dead_letters: list[DeadLetterNotification] | None = None,
    calendar_dead_letters: list[DeadLetterCalendarSync] | None = None,
    sessions: list[TravelContext] | None = None,
    audit_sink_results: list[AuditSinkResult] | None = None,
) -> OperationsDrillReport:
    worker_runs = worker_runs or []
    dead_letters = dead_letters or []
    calendar_dead_letters = calendar_dead_letters or []
    sessions = sessions or []
    readiness = run_release_readiness_report(settings)

    permission_decision = evaluate_permission(
        PermissionPolicy(enabled=True, required_roles={"traveler"}, api_url="https://iam.example/check"),
        user_id="u-demo",
        action="plan_trip",
        roles={"traveler"},
        http_client=_FailingHttpClient(),
    )
    permission_denied = evaluate_permission(
        PermissionPolicy(enabled=True, blocked_actions={"book_order"}),
        user_id="u-demo",
        action="book_order",
        roles={"traveler"},
    )
    simulated_audit_failure = AuditSinkResult(
        ok=False,
        delivered=0,
        failed=1,
        detail="simulated audit sink outage",
    )
    alerts = build_operations_alerts(
        worker_runs=worker_runs,
        dead_letters=dead_letters,
        calendar_dead_letters=calendar_dead_letters,
        sessions=sessions,
        permission_decisions=[permission_decision, permission_denied],
        audit_sink_results=[*(audit_sink_results or []), simulated_audit_failure],
    )
    if not any(alert["alert_type"] == "order_failed" for alert in alerts):
        alerts.append(
            {
                "alert_type": "order_failed",
                "severity": "critical",
                "message": "Simulated supplier order failure should trigger compensation.",
                "value": 1,
            }
        )
    rollout_decision = evaluate_rollout(
        RolloutPolicy(enabled=True, rollback_enabled=True, rollback_reason="incident rollback"),
        user_id="u-demo",
    )
    drills = [
        IncidentDrillResult(
            scenario="permission_unavailable",
            status="PASS" if permission_decision.source == "local" and permission_decision.allowed else "WARN",
            summary="Local permission fallback is used when IAM is unavailable.",
            signals=[permission_decision.status, permission_decision.source],
            details={"reasons": permission_decision.reasons},
        ),
        IncidentDrillResult(
            scenario="audit_sink_unavailable",
            status="PASS" if any(alert["alert_type"] == "audit_sink_failed" for alert in alerts) else "WARN",
            summary="Audit events remain redacted and can be retained locally when sink delivery fails.",
            signals=["audit_sink_failure", "redaction"],
            details={
                "audit_alerts": [
                    alert for alert in alerts if alert["alert_type"] in {"audit_sink_failed", "notification_dead_letters"}
                ]
            },
        ),
        IncidentDrillResult(
            scenario="supplier_order_failure",
            status="PASS" if any(alert["alert_type"] == "order_failed" for alert in alerts) else "WARN",
            summary="Order failure alerts identify supplier-side failures.",
            signals=[alert["alert_type"] for alert in alerts if alert["alert_type"] == "order_failed"],
        ),
        IncidentDrillResult(
            scenario="rollback_trigger",
            status="PASS" if rollout_decision.status == "ROLLED_BACK" else "WARN",
            summary="Rollback switch suppresses rollout immediately.",
            signals=[rollout_decision.status],
            details={"reasons": rollout_decision.reasons},
        ),
    ]
    return OperationsDrillReport(
        settings_profile=_profile_name(settings),
        readiness=readiness,
        alerts=alerts,
        permission_decision=permission_decision,
        rollout_decision=rollout_decision,
        drills=drills,
    )


def render_operations_drill_report(report: OperationsDrillReport) -> str:
    lines = [
        "Operations drill report:",
        f"- settings_profile: {report.settings_profile}",
        f"- readiness_status: {report.readiness.status}",
        f"- alert_count: {len(report.alerts)}",
        f"- permission: {report.permission_decision.status}/{report.permission_decision.source}",
        f"- rollout: {report.rollout_decision.status}",
    ]
    for drill in report.drills:
        lines.append(f"- drill {drill.scenario}: {drill.status}")
        lines.append(f"  summary: {drill.summary}")
        if drill.signals:
            lines.append(f"  signals: {', '.join(drill.signals)}")
        for key, value in drill.details.items():
            lines.append(f"  {key}: {value}")
    return "\n".join(lines)


def evaluate_operations_drill_gate(
    report: OperationsDrillReport,
    allow_warnings: bool = False,
) -> OperationsDrillGateResult:
    statuses = {drill.status for drill in report.drills}
    if "FAIL" in statuses:
        return OperationsDrillGateResult(passed=False, exit_code=1, report=report)
    if "WARN" in statuses and not allow_warnings:
        return OperationsDrillGateResult(passed=False, exit_code=2, report=report)
    return OperationsDrillGateResult(passed=True, exit_code=0, report=report)


def render_operations_drill_gate_result(result: OperationsDrillGateResult) -> str:
    return "\n".join(
        [
            "Operations drill gate:",
            f"- passed: {result.passed}",
            f"- exit_code: {result.exit_code}",
            render_operations_drill_report(result.report),
        ]
    )


def build_operations_alerts(
    worker_runs: list[WorkerRunRecord] | None = None,
    dead_letters: list[DeadLetterNotification] | None = None,
    calendar_dead_letters: list[DeadLetterCalendarSync] | None = None,
    sessions: list[TravelContext] | None = None,
    permission_decisions: list[PermissionDecision] | None = None,
    audit_sink_results: list[AuditSinkResult] | None = None,
) -> list[dict[str, Any]]:
    alerts = build_sla_alerts(worker_runs or [], dead_letters or [], sessions or [])
    calendar_dead_letter_count = len(calendar_dead_letters or [])
    if calendar_dead_letter_count:
        alerts.append(
            {
                "alert_type": "calendar_dead_letters",
                "severity": "warning",
                "message": "Calendar dead letters require replay or manual handling.",
                "value": calendar_dead_letter_count,
            }
        )

    denied = [decision for decision in permission_decisions or [] if not decision.allowed]
    if denied:
        alerts.append(
            {
                "alert_type": "permission_denied",
                "severity": "warning",
                "message": "Permission decisions denied user actions.",
                "value": len(denied),
            }
        )
    remote_fallbacks = [
        decision
        for decision in permission_decisions or []
        if decision.allowed and decision.enforced and decision.source == "local"
    ]
    if remote_fallbacks:
        alerts.append(
            {
                "alert_type": "permission_center_fallback",
                "severity": "warning",
                "message": "Permission checks used local fallback during remote outage.",
                "value": len(remote_fallbacks),
            }
        )

    audit_failures = [result for result in audit_sink_results or [] if not result.ok or result.failed]
    if audit_failures:
        alerts.append(
            {
                "alert_type": "audit_sink_failed",
                "severity": "critical",
                "message": "Audit sink delivery failed and requires replay.",
                "value": sum(max(1, result.failed) for result in audit_failures),
            }
        )
    return alerts


def render_operations_alerts(alerts: list[dict[str, Any]]) -> str:
    lines = ["Operations alerts:"]
    if not alerts:
        lines.append("- none")
        return "\n".join(lines)
    for alert in alerts:
        normalized = _normalize_alert(alert)
        lines.append(
            "- "
            f"{normalized['severity']} {normalized['alert_type']} "
            f"value={normalized['value']} message={normalized['message']}"
        )
    return "\n".join(lines)


def render_operations_alerts_json(alerts: list[dict[str, Any]]) -> str:
    return json.dumps({"alerts": [_normalize_alert(alert) for alert in alerts]}, ensure_ascii=False)


def render_operations_alerts_prometheus(alerts: list[dict[str, Any]]) -> str:
    lines = [
        "# HELP travel_operations_alerts Operations alerts by type, severity, and message.",
        "# TYPE travel_operations_alerts gauge",
    ]
    if not alerts:
        lines.append('travel_operations_alerts{alert_type="none",severity="none",message="no active alerts"} 0')
        return "\n".join(lines)
    for alert in alerts:
        normalized = _normalize_alert(alert)
        lines.append(
            "travel_operations_alerts"
            f'{{alert_type="{_metric_label(normalized["alert_type"])}",'
            f'severity="{_metric_label(normalized["severity"])}",'
            f'message="{_metric_label(normalized["message"])}"}} '
            f"{normalized['value']}"
        )
    return "\n".join(lines)


def export_operations_alerts_http(
    alerts: list[dict[str, Any]],
    endpoint: str,
    token: str | None = None,
    http_client: Any | None = None,
) -> OperationsAlertExportResult:
    from .integrations import JsonHttpClient

    normalized = [_normalize_alert(alert) for alert in alerts]
    payload = {
        "source": "travel-agent",
        "alerts": normalized,
    }
    try:
        client = http_client or JsonHttpClient()
        response = client.post_json(endpoint, payload, token)
    except Exception as exc:
        return OperationsAlertExportResult(
            ok=False,
            endpoint=endpoint,
            delivered=0,
            failed=len(normalized),
            detail=str(exc),
        )
    accepted = min(len(normalized), int(response.get("accepted") or response.get("delivered") or len(normalized)))
    failed = max(0, len(normalized) - accepted)
    return OperationsAlertExportResult(
        ok=bool(response.get("ok", failed == 0)),
        endpoint=endpoint,
        delivered=accepted,
        failed=failed,
        detail=str(response.get("detail") or "sent to alert sink"),
    )


def render_operations_alert_export_result(result: OperationsAlertExportResult) -> str:
    return "\n".join(
        [
            "Operations alert export:",
            f"- ok: {result.ok}",
            f"- endpoint: {result.endpoint}",
            f"- delivered: {result.delivered}",
            f"- failed: {result.failed}",
            f"- detail: {result.detail}",
        ]
    )


def open_oncall_ticket_http(
    report: OperationsDrillReport,
    endpoint: str,
    token: str | None = None,
    http_client: Any | None = None,
) -> OnCallTicketResult:
    from .integrations import JsonHttpClient

    alerts = [_normalize_alert(alert) for alert in report.alerts]
    critical = [alert for alert in alerts if alert["severity"] == "critical"]
    payload = {
        "source": "travel-agent",
        "summary": "Travel Agent operations incident",
        "readiness_status": report.readiness.status,
        "alerts": alerts,
        "critical_alerts": critical,
        "drills": [
            {
                "scenario": drill.scenario,
                "status": drill.status,
                "summary": drill.summary,
                "signals": drill.signals,
                "details": drill.details,
            }
            for drill in report.drills
        ],
    }
    try:
        client = http_client or JsonHttpClient()
        response = client.post_json(endpoint, payload, token)
    except Exception as exc:
        return OnCallTicketResult(
            ok=False,
            endpoint=endpoint,
            ticket_id=None,
            delivered=0,
            failed=1,
            detail=str(exc),
        )
    ticket_id = response.get("ticket_id") or response.get("id") or response.get("incident_id")
    ok = bool(response.get("ok", True))
    return OnCallTicketResult(
        ok=ok,
        endpoint=endpoint,
        ticket_id=str(ticket_id) if ticket_id is not None else None,
        delivered=1 if ok else 0,
        failed=0 if ok else 1,
        detail=str(response.get("detail") or "on-call ticket opened"),
    )


def render_oncall_ticket_result(result: OnCallTicketResult) -> str:
    return "\n".join(
        [
            "OnCall ticket:",
            f"- ok: {result.ok}",
            f"- endpoint: {result.endpoint}",
            f"- ticket_id: {result.ticket_id or '-'}",
            f"- delivered: {result.delivered}",
            f"- failed: {result.failed}",
            f"- detail: {result.detail}",
        ]
    )


def fetch_oncall_ticket_status_http(
    ticket_id: str,
    endpoint: str,
    token: str | None = None,
    http_client: Any | None = None,
) -> OnCallTicketStatus:
    from .integrations import JsonHttpClient

    try:
        client = http_client or JsonHttpClient()
        response = client.post_json(endpoint, {"ticket_id": ticket_id}, token)
    except Exception as exc:
        return OnCallTicketStatus(
            ticket_id=ticket_id,
            status="SYNC_FAILED",
            assignee=None,
            updated_at=datetime.now(timezone.utc).isoformat(),
            detail=str(exc),
        )
    data = response.get("ticket") or response.get("data") or response
    return OnCallTicketStatus(
        ticket_id=str(data.get("ticket_id") or data.get("id") or ticket_id),
        status=str(data.get("status") or "UNKNOWN"),
        assignee=str(data.get("assignee")) if data.get("assignee") is not None else None,
        updated_at=str(data.get("updated_at") or datetime.now(timezone.utc).isoformat()),
        detail=str(data.get("detail") or data.get("message") or "status synced"),
    )


def oncall_ticket_status_to_dict(status: OnCallTicketStatus) -> dict[str, Any]:
    return {
        "ticket_id": status.ticket_id,
        "status": status.status,
        "assignee": status.assignee,
        "updated_at": status.updated_at,
        "detail": status.detail,
    }


def oncall_ticket_status_from_dict(payload: dict[str, Any]) -> OnCallTicketStatus:
    return OnCallTicketStatus(
        ticket_id=str(payload["ticket_id"]),
        status=str(payload["status"]),
        assignee=str(payload["assignee"]) if payload.get("assignee") is not None else None,
        updated_at=str(payload.get("updated_at") or ""),
        detail=str(payload.get("detail") or ""),
    )


def render_oncall_ticket_status(status: OnCallTicketStatus) -> str:
    return "\n".join(
        [
            "OnCall ticket status:",
            f"- ticket_id: {status.ticket_id}",
            f"- status: {status.status}",
            f"- assignee: {status.assignee or '-'}",
            f"- updated_at: {status.updated_at}",
            f"- detail: {status.detail}",
        ]
    )


def _dashboard_trend_metrics(dashboard: OperationsDashboard) -> dict[str, int]:
    metrics = {
        "active_alerts": dashboard.active_alerts,
        "calendar_dead_letters": dashboard.calendar_dead_letters,
        "critical_alerts": dashboard.critical_alerts,
        "notification_dead_letters": dashboard.notification_dead_letters,
        "sessions_observed": dashboard.sessions_observed,
        "worker_errors": dashboard.worker_errors,
        "worker_runs": dashboard.worker_runs,
    }
    for state, count in dashboard.state_counts.items():
        metrics[f"state:{state}"] = count
    return metrics


def _operations_trend_metric(name: str, current: int, previous: int) -> OperationsTrendMetric:
    delta = current - previous
    delta_percent = None if previous == 0 else round((delta / previous) * 100, 1)
    return OperationsTrendMetric(
        name=name,
        current=current,
        previous=previous,
        delta=delta,
        delta_percent=delta_percent,
    )


def _operations_trend_anomalies(metrics: list[OperationsTrendMetric]) -> list[str]:
    watched = {
        "active_alerts",
        "calendar_dead_letters",
        "critical_alerts",
        "notification_dead_letters",
        "worker_errors",
    }
    anomalies: list[str] = []
    for metric in metrics:
        if metric.delta <= 0:
            continue
        if metric.name in watched or (metric.name.startswith("state:") and _is_failure_state(metric.name[6:])):
            anomalies.append(f"{metric.name} increased by {metric.delta} to {metric.current}.")
    return anomalies


def _operations_trend_action_items(
    metrics: list[OperationsTrendMetric],
    anomalies: list[str],
    baseline_only: bool,
) -> list[str]:
    if baseline_only:
        return ["Persist at least one more dashboard snapshot to calculate deltas and volatility."]
    metric_map = {metric.name: metric for metric in metrics}
    action_items: list[str] = []
    if metric_map.get("worker_errors") and metric_map["worker_errors"].delta > 0:
        action_items.append("Inspect worker errors and replay affected sessions.")
    if metric_map.get("critical_alerts") and metric_map["critical_alerts"].delta > 0:
        action_items.append("Review critical alert routes and open or update the incident owner.")
    if metric_map.get("notification_dead_letters") and metric_map["notification_dead_letters"].delta > 0:
        action_items.append("Replay notification dead letters after checking idempotency keys.")
    if metric_map.get("calendar_dead_letters") and metric_map["calendar_dead_letters"].delta > 0:
        action_items.append("Replay calendar dead letters or create manual calendar events.")
    if any(metric.name.startswith("state:") and _is_failure_state(metric.name[6:]) and metric.delta > 0 for metric in metrics):
        action_items.append("Prioritize compensation and operator recovery for newly failed sessions.")
    if not action_items:
        action_items.append("No trend anomaly detected in the selected window.")
    if anomalies and "Review critical alert routes and open or update the incident owner." not in action_items:
        action_items.append("Review anomaly rows and compare with alert routing rules.")
    return _dedupe(action_items)


def _operations_trend_summary(
    latest: OperationsDashboardSnapshot,
    previous: OperationsDashboardSnapshot,
    metrics: list[OperationsTrendMetric],
) -> str:
    meaningful = [metric for metric in metrics if metric.name != "sessions_observed"]
    largest = max(meaningful, key=lambda metric: abs(metric.delta), default=None)
    if largest is None or largest.delta == 0:
        return f"{latest.snapshot_id} is stable compared with {previous.snapshot_id}."
    return (
        f"{latest.snapshot_id} changed most on {largest.name} "
        f"({_signed_int(largest.delta)}) compared with {previous.snapshot_id}."
    )


def _dimension_group(
    name: str,
    sessions: list[TravelContext],
    key_fn: Any,
    limit: int,
) -> OperationsDimensionGroup:
    buckets: dict[str, list[TravelContext]] = {}
    for context in sessions:
        keys = key_fn(context)
        for key in keys:
            buckets.setdefault(_dimension_key(key, "unknown"), []).append(context)
    rows = [_dimension_row(key, contexts) for key, contexts in buckets.items()]
    rows.sort(key=lambda row: (-row.sessions, -row.failed, row.key))
    return OperationsDimensionGroup(name=name, rows=rows[:limit])


def _dimension_row(key: str, sessions: list[TravelContext]) -> OperationsDimensionRow:
    return OperationsDimensionRow(
        key=key,
        sessions=len(sessions),
        orders=sum(_session_order_count(context) for context in sessions),
        compensations=sum(_session_compensation_count(context) for context in sessions),
        policy_violations=sum(_session_policy_violation_count(context) for context in sessions),
        failed=sum(1 for context in sessions if _is_failure_state(context.state)),
    )


def _policy_source_keys(context: TravelContext) -> list[str]:
    keys: list[str] = []
    if context.policy_result:
        keys.append(f"hotel_policy:{context.policy_result.source}")
    if context.transport_policy_result:
        keys.append(f"transport_policy:{context.transport_policy_result.source}")
    return keys or ["unknown"]


def _session_order_count(context: TravelContext) -> int:
    return int(context.order is not None) + int(context.transport_order is not None)


def _session_compensation_count(context: TravelContext) -> int:
    return (
        int(context.approval_cancellation is not None)
        + int(context.order_cancellation is not None)
        + int(context.transport_order_cancellation is not None)
        + int(context.inventory_release is not None)
        + len(context.refund_confirmations)
        + len(context.change_failure_compensations)
        + len(context.recovery_records)
    )


def _session_policy_violation_count(context: TravelContext) -> int:
    return (
        int(context.policy_result is not None and not context.policy_result.compliant)
        + int(context.transport_policy_result is not None and not context.transport_policy_result.compliant)
    )


def _alert_counters(alerts: list[dict[str, Any]]) -> tuple[dict[str, int], dict[str, int]]:
    alert_counts: Counter[str] = Counter()
    severity_counts: Counter[str] = Counter()
    for alert in alerts:
        normalized = _normalize_alert(alert)
        value = max(1, normalized["value"])
        alert_counts[normalized["alert_type"]] += value
        severity_counts[normalized["severity"]] += value
    return dict(alert_counts), dict(severity_counts)


def _operations_dimension_action_items(
    sessions: list[TravelContext],
    worker_errors: int,
    alert_counts: dict[str, int],
    severity_counts: dict[str, int],
    dead_letter_counts: dict[str, int],
) -> list[str]:
    action_items: list[str] = []
    if not sessions:
        action_items.append("No persisted sessions are available for dimensional slicing.")
    if worker_errors:
        action_items.append("Slice worker errors by user and route before retrying sessions.")
    if any(_is_failure_state(context.state) for context in sessions):
        action_items.append("Use failed dimension rows to prioritize compensation and operator recovery.")
    if any(_session_policy_violation_count(context) for context in sessions):
        action_items.append("Review policy violations with policy owners by department and route.")
    if severity_counts.get("critical"):
        action_items.append("Escalate critical alert dimensions to the configured OnCall route.")
    if alert_counts.get("permission_denied") or alert_counts.get("permission_center_fallback"):
        action_items.append("Compare permission alert volume with policy-source rows.")
    if sum(dead_letter_counts.values()):
        action_items.append("Replay dead letters after upstream providers recover.")
    if not action_items:
        action_items.append("No dimensional hotspot detected.")
    return _dedupe(action_items)


def _postmortem_primary_signal(
    alert_counts: dict[str, int],
    failed_sessions: list[TravelContext],
    dead_letters: list[DeadLetterNotification],
    calendar_dead_letters: list[DeadLetterCalendarSync],
    unresolved_tickets: list[OnCallTicketStatus],
) -> str:
    if alert_counts:
        alert_type, _ = max(alert_counts.items(), key=lambda item: (item[1], item[0]))
        return alert_type
    if failed_sessions:
        return "failed_sessions"
    if dead_letters or calendar_dead_letters:
        return "dead_letters"
    if unresolved_tickets:
        return "unresolved_oncall_tickets"
    return "no_active_incident"


def _postmortem_severity(
    severity_counts: dict[str, int],
    failed_sessions: list[TravelContext],
    dead_letters: list[DeadLetterNotification],
    calendar_dead_letters: list[DeadLetterCalendarSync],
    unresolved_tickets: list[OnCallTicketStatus],
) -> str:
    if severity_counts.get("critical") or failed_sessions:
        return "critical"
    if severity_counts or dead_letters or calendar_dead_letters or unresolved_tickets:
        return "warning"
    return "info"


def _postmortem_incident_id(
    primary_signal: str,
    generated_at: str,
    oncall_statuses: list[OnCallTicketStatus],
) -> str:
    if oncall_statuses:
        return oncall_statuses[0].ticket_id
    stamp = generated_at.replace("-", "").replace(":", "").replace("+", "").replace("T", "-")[:18]
    slug = primary_signal.upper().replace("_", "-")[:24]
    return f"INC-{slug}-{stamp}"


def _postmortem_impact(
    view: OperationsMultiDimensionalView,
    failed_sessions: list[TravelContext],
    compensated_sessions: list[TravelContext],
    unresolved_tickets: list[OnCallTicketStatus],
) -> list[str]:
    impact = [
        f"sessions_observed={view.total_sessions}",
        f"failed_sessions={len(failed_sessions)}",
        f"compensated_sessions={len(compensated_sessions)}",
        f"unresolved_oncall_tickets={len(unresolved_tickets)}",
        f"alert_signal_volume={sum(view.alert_counts.values())}",
        f"dead_letters={sum(view.dead_letter_counts.values())}",
    ]
    for group_name in ("departments", "routes", "hotel_suppliers", "transport_providers"):
        group = next((item for item in view.groups if item.name == group_name), None)
        if group and group.rows:
            top = group.rows[0]
            impact.append(f"top_{group_name}={top.key} sessions={top.sessions} failed={top.failed}")
    return impact


def _postmortem_timeline(
    snapshots: list[OperationsDashboardSnapshot],
    worker_runs: list[WorkerRunRecord],
    oncall_statuses: list[OnCallTicketStatus],
) -> list[OperationsTimelineEvent]:
    events: list[OperationsTimelineEvent] = []
    for snapshot in snapshots[-3:]:
        events.append(
            OperationsTimelineEvent(
                timestamp=snapshot.created_at,
                source="dashboard",
                detail=(
                    f"{snapshot.snapshot_id}: sessions={snapshot.dashboard.sessions_observed} "
                    f"alerts={snapshot.dashboard.active_alerts} critical={snapshot.dashboard.critical_alerts}"
                ),
            )
        )
    for record in worker_runs[:3]:
        events.append(
            OperationsTimelineEvent(
                timestamp=record.finished_at,
                source="worker",
                detail=(
                    f"{record.run_id}: scanned={record.scanned} advanced={record.advanced} "
                    f"errors={len(record.errors)}"
                ),
            )
        )
    for status in oncall_statuses[:3]:
        events.append(
            OperationsTimelineEvent(
                timestamp=status.updated_at,
                source="oncall",
                detail=f"{status.ticket_id}: {status.status} assignee={status.assignee or '-'}",
            )
        )
    events.sort(key=lambda event: _timestamp_sort_key(event.timestamp))
    return events


def _postmortem_root_causes(
    alert_counts: dict[str, int],
    failed_sessions: list[TravelContext],
    dead_letters: list[DeadLetterNotification],
    calendar_dead_letters: list[DeadLetterCalendarSync],
    unresolved_tickets: list[OnCallTicketStatus],
) -> list[str]:
    causes: list[str] = []
    if alert_counts.get("order_failed") or any(context.state == "ORDER_FAILED" for context in failed_sessions):
        causes.append("Supplier order or inventory path produced failed orders.")
    if alert_counts.get("audit_sink_failed"):
        causes.append("Audit sink delivery failed and requires replay.")
    if alert_counts.get("permission_denied") or alert_counts.get("permission_center_fallback"):
        causes.append("Permission policy or IAM fallback contributed to the incident.")
    if alert_counts.get("notification_dead_letters") or dead_letters:
        causes.append("Notification provider dead letters require replay.")
    if alert_counts.get("calendar_dead_letters") or calendar_dead_letters:
        causes.append("Calendar provider dead letters require replay or manual creation.")
    if unresolved_tickets:
        causes.append("OnCall ticket is not resolved yet, so recovery ownership remains open.")
    if failed_sessions and not causes:
        causes.append("Failed session states require manual triage.")
    if not causes:
        causes.append("No clear root cause signal; continue collecting snapshots and external notes.")
    return _dedupe(causes)


def _postmortem_evidence(
    snapshots: list[OperationsDashboardSnapshot],
    worker_runs: list[WorkerRunRecord],
    alert_counts: dict[str, int],
    related_sessions: list[str],
    oncall_statuses: list[OnCallTicketStatus],
) -> list[str]:
    evidence: list[str] = []
    if snapshots:
        latest = snapshots[-1]
        evidence.append(
            f"latest_snapshot={latest.snapshot_id} active_alerts={latest.dashboard.active_alerts} "
            f"critical_alerts={latest.dashboard.critical_alerts}"
        )
    if worker_runs:
        latest_worker = worker_runs[0]
        evidence.append(f"latest_worker_run={latest_worker.run_id} errors={len(latest_worker.errors)}")
    if alert_counts:
        evidence.append(
            "alert_counts="
            + ", ".join(f"{key}:{value}" for key, value in _sorted_count_items(alert_counts))
        )
    if related_sessions:
        evidence.append("related_sessions=" + ", ".join(related_sessions))
    if oncall_statuses:
        latest_ticket = oncall_statuses[0]
        evidence.append(f"latest_ticket={latest_ticket.ticket_id} status={latest_ticket.status}")
    if not evidence:
        evidence.append("No persisted incident evidence is available yet.")
    return evidence


def _postmortem_action_items(
    root_causes: list[str],
    latest_snapshot: OperationsDashboardSnapshot | None,
    drill_report: OperationsDrillReport | None,
    unresolved_tickets: list[OnCallTicketStatus],
) -> list[str]:
    action_items: list[str] = []
    joined_causes = " ".join(root_causes).lower()
    if "supplier order" in joined_causes:
        action_items.append("Run supplier reconciliation and compensation for failed orders.")
    if "audit sink" in joined_causes:
        action_items.append("Recover audit sink and replay retained redacted audit events.")
    if "permission" in joined_causes:
        action_items.append("Review IAM fallback and policy-owner approval rules.")
    if "dead letters" in joined_causes or "provider dead letters" in joined_causes:
        action_items.append("Replay notification and calendar dead letters after provider recovery.")
    if unresolved_tickets:
        action_items.append("Update unresolved OnCall tickets with owner, ETA, and recovery notes.")
    if latest_snapshot:
        action_items.extend(latest_snapshot.dashboard.action_items)
    if drill_report:
        for drill in drill_report.drills:
            if drill.status != "PASS":
                action_items.append(f"Resolve drill {drill.scenario} status {drill.status}.")
    if not action_items:
        action_items.append("Close the incident after validating snapshots, alerts, and OnCall status.")
    return _dedupe(action_items)


def _related_session_ids(sessions: list[TravelContext], failed_sessions: list[TravelContext]) -> list[str]:
    ordered = failed_sessions + [context for context in sessions if context not in failed_sessions]
    return _dedupe([context.session_id for context in ordered])[:5]


def _is_failure_state(state: str) -> bool:
    normalized = state.upper()
    return any(token in normalized for token in ("FAILED", "ERROR", "DEAD_LETTER", "REJECTED"))


def _dimension_key(value: object, default: str) -> str:
    text = str(value).strip() if value is not None else ""
    return text or default


def _timestamp_sort_key(value: str) -> float:
    try:
        normalized = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()
    except (TypeError, ValueError):
        return 0.0


def _append_count_section(lines: list[str], title: str, counts: dict[str, int]) -> None:
    lines.append(f"- {title}:")
    if not counts:
        lines.append("  - none: 0")
        return
    for key, value in _sorted_count_items(counts):
        lines.append(f"  - {key}: {value}")


def _append_list_section(lines: list[str], title: str, items: list[str]) -> None:
    lines.append(f"- {title}:")
    if not items:
        lines.append("  - none")
        return
    for item in items:
        lines.append(f"  - {item}")


def _sorted_count_items(counts: dict[str, int]) -> list[tuple[str, int]]:
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))


def _signed_int(value: int) -> str:
    return f"{value:+d}"


def _format_delta_percent(value: float | None) -> str:
    if value is None:
        return "new baseline"
    return f"{value:+.1f}%"


def _search_terms(query: str) -> list[str]:
    normalized = query.lower()
    for char in ",.;:|/\\()[]{}\"'":
        normalized = normalized.replace(char, " ")
    terms = [term.strip() for term in normalized.split() if term.strip()]
    if not terms and query.strip():
        terms = [query.strip().lower()]
    return _dedupe(terms)


def _knowledge_entry_score(entry: OperationsKnowledgeEntry, terms: list[str]) -> tuple[int, list[str]]:
    if not terms:
        return (1, [])
    fields = {
        "topic": entry.topic,
        "title": entry.title,
        "summary": entry.summary,
        "signals": " ".join(entry.signals),
        "actions": " ".join(entry.recommended_actions),
        "refs": " ".join(entry.source_refs),
    }
    weights = {
        "topic": 5,
        "title": 4,
        "signals": 3,
        "summary": 2,
        "actions": 2,
        "refs": 1,
    }
    score = 0
    matched: list[str] = []
    for term in terms:
        term_score = 0
        for field_name, value in fields.items():
            if term in value.lower():
                term_score += weights[field_name]
        if term_score:
            score += term_score
            matched.append(term)
    return score, matched


def _closed_loop_recommendations(
    trend_alerts: list[OperationsTrendAlert],
    action_items: list[OperationsActionItem],
    open_items: list[OperationsActionItem],
    closure_rate: float,
    knowledge_entries: list[OperationsKnowledgeEntry],
    action_items_overdue: int,
) -> list[str]:
    recommendations: list[str] = []
    if trend_alerts and not action_items:
        recommendations.append("Create action items for active trend alerts.")
    if open_items:
        recommendations.append("Review open action items and assign ETA or closure notes.")
    if action_items_overdue:
        recommendations.append("Escalate overdue action items through owner routes.")
    if action_items and closure_rate < 80.0:
        recommendations.append("Improve action item closure rate before closing incidents.")
    if not knowledge_entries:
        recommendations.append("Save postmortem and trend response knowledge for future reuse.")
    if knowledge_entries and closure_rate >= 80.0 and not action_items_overdue:
        recommendations.append("Closed-loop health is stable; reuse knowledge entries in future planning.")
    return _dedupe(recommendations) or ["No immediate closed-loop follow-up required."]


def _trend_alert_reason(
    metric: OperationsTrendMetric,
    rule: OperationsTrendAlertRule,
    baseline_only: bool,
) -> str | None:
    reasons: list[str] = []
    if rule.absolute_threshold is not None and metric.current >= rule.absolute_threshold:
        reasons.append(f"current {metric.current} >= threshold {rule.absolute_threshold}")
    if not baseline_only and rule.delta_threshold is not None and metric.delta >= rule.delta_threshold:
        reasons.append(f"delta {metric.delta} >= threshold {rule.delta_threshold}")
    if (
        not baseline_only
        and rule.delta_percent_threshold is not None
        and metric.delta_percent is not None
        and metric.delta_percent >= rule.delta_percent_threshold
    ):
        reasons.append(f"delta_percent {metric.delta_percent:.1f}% >= threshold {rule.delta_percent_threshold:.1f}%")
    if not reasons:
        return None
    return "; ".join(reasons)


def _severity_rank(severity: str) -> int:
    ranks = {"critical": 0, "warning": 1, "info": 2}
    return ranks.get(severity.lower(), 3)


def _optional_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _optional_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _action_owner(title: str, default_owner: str) -> str:
    lowered = title.lower()
    if "audit" in lowered:
        return "compliance-platform-oncall"
    if "supplier" in lowered or "order" in lowered:
        return "booking-oncall"
    if "iam" in lowered or "permission" in lowered:
        return "iam-platform-oncall"
    if "calendar" in lowered:
        return "collaboration-oncall"
    if "notification" in lowered or "dead letter" in lowered:
        return "workflow-oncall"
    return default_owner


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha1("|".join(str(part) for part in parts).encode("utf-8")).hexdigest()[:12].upper()
    return f"{prefix}-{digest}"


def _dedupe_knowledge_entries(entries: list[OperationsKnowledgeEntry]) -> list[OperationsKnowledgeEntry]:
    seen: set[str] = set()
    result: list[OperationsKnowledgeEntry] = []
    for entry in entries:
        if entry.entry_id in seen:
            continue
        seen.add(entry.entry_id)
        result.append(entry)
    return result


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _profile_name(settings: IntegrationSettings) -> str:
    if any(
        [
            settings.permission_api_url,
            settings.audit_log_api_url,
            settings.alert_api_url,
            settings.oncall_api_url,
            settings.session_store_api_url,
            settings.session_db_path,
        ]
    ):
        return "production-like"
    return "mock"


def _normalize_alert(alert: dict[str, Any]) -> dict[str, Any]:
    return {
        "alert_type": str(alert.get("alert_type") or "unknown"),
        "severity": str(alert.get("severity") or "warning"),
        "message": str(alert.get("message") or ""),
        "value": int(alert.get("value") or 0),
    }


def _metric_label(value: object) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


class _FailingHttpClient:
    def post_json(self, url: str, payload: dict[str, Any], token: str | None = None) -> dict[str, Any]:
        del url, payload, token
        raise RuntimeError("simulated remote outage")
