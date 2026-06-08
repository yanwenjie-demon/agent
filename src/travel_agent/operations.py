from __future__ import annotations

import json
import hashlib
import hmac
from collections import Counter
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from html import escape
from typing import Any
from uuid import uuid4

from .config import IntegrationSettings
from .data_governance import AuditSink, AuditSinkResult, build_audit_event
from .governance import ReleaseReadinessReport, run_release_readiness_report
from .models import (
    CompensationResult,
    DeadLetterCalendarSync,
    DeadLetterNotification,
    NotificationRecord,
    TravelContext,
    WorkerRunRecord,
)
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
class OperationsClosedLoopExportResult:
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
class OperationsActionSlaNotificationReport:
    notification_count: int
    failed_count: int
    notifications: list[NotificationRecord]


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
    owner_counts: dict[str, int]
    recommendations: list[str]


@dataclass(frozen=True)
class OperationsClosedLoopSnapshot:
    snapshot_id: str
    created_at: str
    report: OperationsClosedLoopReport
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class OperationsActionStatusSyncReport:
    scanned_statuses: int
    matched_items: int
    closed_items: list[OperationsActionItem]
    skipped_items: list[str]


@dataclass(frozen=True)
class RecoveryStrategyDecision:
    decision_id: str
    action: str
    severity: str
    reason: str
    from_state: str
    compensation_required: bool
    manual_escalation_required: bool
    knowledge_refs: list[str]
    guidance: list[str]
    recommended_next_steps: list[str]


@dataclass(frozen=True)
class RecoveryStrategyGateResult:
    decision_id: str
    status: str
    allow_automation: bool
    exit_code: int
    required_approvals: list[str]
    blocked_actions: list[str]
    reasons: list[str]


@dataclass(frozen=True)
class RecoveryStrategyExecutionResult:
    execution_id: str
    decision_id: str
    action: str
    status: str
    from_state: str
    to_state: str
    gate_status: str
    approval_override: bool
    executed_steps: list[str]
    skipped_steps: list[str]
    detail: str
    created_at: str
    idempotency_key: str = ""
    approval_receipt: dict[str, Any] | None = None


@dataclass(frozen=True)
class RecoveryApprovalReceipt:
    receipt_id: str
    decision_id: str
    approved_by: str
    approved_at: str
    reason: str
    required_approvals: list[str]


@dataclass(frozen=True)
class RecoveryApprovalSlaPolicy:
    max_pending_hours: float = 24.0
    allowed_approvers: list[str] = field(default_factory=list)
    approver_prefixes: list[str] = field(default_factory=list)
    required_approval_types: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RecoveryApprovalSlaFinding:
    decision_id: str
    severity: str
    age_hours: float
    reason: str
    required_approvals: list[str]
    approved_by: str | None = None


@dataclass(frozen=True)
class RecoveryApprovalSlaReport:
    now: str
    checked_receipts: int
    findings: list[RecoveryApprovalSlaFinding]
    summary: str


@dataclass(frozen=True)
class RecoveryGovernancePolicy:
    allowed_actions: list[str] = field(default_factory=list)
    blocked_actions: list[str] = field(default_factory=list)
    max_executions_per_session: int | None = None


@dataclass(frozen=True)
class RecoveryGovernanceDecision:
    decision_id: str
    action: str
    status: str
    allow_automation: bool
    reasons: list[str]


@dataclass(frozen=True)
class RecoveryApprovalExportResult:
    ok: bool
    endpoint: str
    delivered: int
    failed: int
    detail: str


@dataclass(frozen=True)
class RecoveryGovernancePolicyFetchResult:
    ok: bool
    endpoint: str
    policy: RecoveryGovernancePolicy
    source: str
    detail: str
    fetched_at: str


@dataclass(frozen=True)
class RecoveryGovernancePolicyAudit:
    audit_id: str
    changed_by: str
    changed_at: str
    before: dict[str, Any]
    after: dict[str, Any]
    changes: list[str]


@dataclass(frozen=True)
class OperationsGovernancePolicyChange:
    change_id: str
    status: str
    policy_type: str
    requested_by: str
    requested_at: str
    before: dict[str, Any]
    after: dict[str, Any]
    changes: list[str]
    approvals: list[str] = field(default_factory=list)
    applied_at: str | None = None
    rolled_back_at: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class OperationsConsoleActionAudit:
    audit_id: str
    action: str
    actor: str
    roles: list[str]
    department: str | None
    status: str
    requested_at: str
    completed_at: str
    authorization: dict[str, Any]
    request_summary: dict[str, Any]
    result_summary: dict[str, Any]


@dataclass(frozen=True)
class OperationsAuditTimelineEvent:
    event_id: str
    event_type: str
    occurred_at: str
    actor: str | None
    action: str | None
    status: str
    summary: str
    refs: dict[str, Any] = field(default_factory=dict)
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OperationsAuditTimeline:
    generated_at: str
    events: list[OperationsAuditTimelineEvent]
    filters: dict[str, str]
    total_events: int
    summary: str


@dataclass(frozen=True)
class OperationsAuditSinkDelivery:
    delivery_id: str
    audit_id: str
    event_type: str
    status: str
    attempted_at: str
    delivered: int
    failed: int
    detail: str
    attempts: int = 1
    last_error: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OperationsAuditSinkReplayReport:
    generated_at: str
    attempted: int
    delivered: int
    failed: int
    deliveries: list[OperationsAuditSinkDelivery]
    summary: str


@dataclass(frozen=True)
class OperationsCompensationTask:
    task_id: str
    source_type: str
    source_id: str
    status: str
    owner: str
    title: str
    severity: str
    created_at: str
    updated_at: str
    due_at: str | None
    linked_ticket_id: str | None
    lifecycle: list[dict[str, Any]]
    refs: dict[str, Any] = field(default_factory=dict)
    payload: dict[str, Any] = field(default_factory=dict)
    closure_note: str | None = None


@dataclass(frozen=True)
class OperationsCompensationTaskBoard:
    generated_at: str
    tasks: list[OperationsCompensationTask]
    status_counts: dict[str, int]
    severity_counts: dict[str, int]
    total_tasks: int
    filters: dict[str, str]
    summary: str


@dataclass(frozen=True)
class OperationsCompensationExecutionPolicy:
    enabled: bool = True
    max_batch_size: int = 20
    retry_window_seconds: int = 900
    max_failures_per_task: int = 3
    allowed_severities: set[str] = field(default_factory=lambda: {"critical", "warning", "info"})
    require_oncall_endpoint_for_sources: set[str] = field(default_factory=set)
    dry_run: bool = False


@dataclass(frozen=True)
class OperationsCompensationExecutionGate:
    allowed: bool
    task_id: str
    status: str
    reason: str
    next_retry_at: str | None = None


@dataclass(frozen=True)
class OperationsCompensationTaskExecution:
    execution_id: str
    task_id: str
    action: str
    status: str
    detail: str
    executed_at: str
    task: OperationsCompensationTask
    ticket_result: OnCallTicketResult | None = None
    gate: OperationsCompensationExecutionGate | None = None


@dataclass(frozen=True)
class OperationsCompensationTaskExecutionReport:
    generated_at: str
    attempted: int
    succeeded: int
    failed: int
    skipped: int
    executions: list[OperationsCompensationTaskExecution]
    summary: str
    policy: OperationsCompensationExecutionPolicy = field(default_factory=OperationsCompensationExecutionPolicy)


@dataclass(frozen=True)
class OperationsCompensationExecutionObservabilityReport:
    generated_at: str
    task_count: int
    attempted: int
    succeeded: int
    failed: int
    skipped: int
    success_rate: float
    manual_interventions: int
    retry_waiting: int
    gate_counts: dict[str, int]
    failure_reasons: dict[str, int]
    action_counts: dict[str, int]
    scheduler_runs: int
    scheduler_attempted: int
    scheduler_failed: int
    console_actions: int
    latest_attempt_at: str | None
    slowest_retry_seconds: int | None
    summary: str


@dataclass(frozen=True)
class OperationsCompensationSloPolicy:
    enabled: bool = True
    min_attempts: int = 1
    success_rate_target: float = 0.95
    warning_burn_rate: float = 1.0
    critical_burn_rate: float = 2.0
    max_failed: int = 0
    max_retry_waiting: int = 5
    max_manual_interventions: int = 5
    max_scheduler_failed: int = 0
    max_retry_seconds: int = 1800
    route: str = "travel-ops"
    escalation: str = "page compensation owner"


@dataclass(frozen=True)
class OperationsCompensationSloReport:
    generated_at: str
    ok: bool
    burn_rate: float
    error_budget_remaining: float
    policy: OperationsCompensationSloPolicy
    observability: OperationsCompensationExecutionObservabilityReport
    alerts: list[dict[str, Any]]
    summary: str


@dataclass(frozen=True)
class OperationsCompensationRemediationPolicy:
    enabled: bool = True
    create_action_items: bool = True
    controlled_retry_enabled: bool = True
    max_retry_tasks: int = 3
    retry_statuses: set[str] = field(default_factory=lambda: {"OPEN", "ESCALATED"})
    retry_severities: set[str] = field(default_factory=lambda: {"critical", "warning"})
    action_owner: str = "travel-ops"
    action_eta: str | None = None
    runbook_owner: str = "travel-ops"
    dry_run: bool = False


@dataclass(frozen=True)
class OperationsCompensationRunbookExecution:
    runbook_id: str
    title: str
    status: str
    trigger: str
    owner: str
    executed_at: str
    action: str
    evidence: list[str]


@dataclass(frozen=True)
class OperationsCompensationRemediationReport:
    generated_at: str
    ok: bool
    policy: OperationsCompensationRemediationPolicy
    slo_report: OperationsCompensationSloReport
    action_items: list[OperationsActionItem]
    runbook_executions: list[OperationsCompensationRunbookExecution]
    retry_candidates: list[OperationsCompensationTask]
    retry_task_ids: list[str]
    retry_execution_report: OperationsCompensationTaskExecutionReport | None
    summary: str


@dataclass(frozen=True)
class OnCallWebhookEvent:
    event_id: str
    ticket_id: str | None
    status: str
    received_at: str
    updated_at: str | None
    accepted: bool
    duplicate: bool
    signature_valid: bool
    replay: bool
    dead_letter: bool
    reason: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class OnCallWebhookReplayResult:
    source_event_id: str
    status: str
    accepted: bool
    replayed_at: str
    ticket_id: str | None
    reason: str


@dataclass(frozen=True)
class OnCallWebhookReplayBatchResult:
    batch_id: str
    generated_at: str
    attempted: int
    accepted: int
    failed: int
    skipped: int
    results: list[OnCallWebhookReplayResult]


@dataclass(frozen=True)
class OnCallWebhookReplayJob:
    job_id: str
    created_at: str
    status: str
    requested_by: str
    event_ids: list[str]
    patch_template_id: str | None
    batch_result: OnCallWebhookReplayBatchResult | None
    audit: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OnCallWebhookPatchTemplate:
    template_id: str
    title: str
    match_reason: str
    patch: dict[str, Any]


@dataclass(frozen=True)
class OnCallWebhookOpsConsole:
    generated_at: str
    total_events: int
    dead_letters: int
    replayed: int
    failed_replays: int
    retryable_event_ids: list[str]
    failure_reasons: dict[str, int]
    patch_templates: list[OnCallWebhookPatchTemplate]


@dataclass(frozen=True)
class OperationsClosedLoopDashboard:
    schema_version: str
    generated_at: str
    snapshot_count: int
    latest_snapshot: OperationsClosedLoopSnapshot | None
    snapshots: list[OperationsClosedLoopSnapshot]
    trends: list[OperationsTrendMetric]
    filters: dict[str, str]
    summary: str
    cursor: str | None = None
    next_cursor: str | None = None
    limit: int = 20
    has_more: bool = False
    checkpoint: str | None = None


@dataclass(frozen=True)
class OperationsClosedLoopSchemaPublishResult:
    ok: bool
    endpoint: str
    schema_version: str
    delivered: int
    failed: int
    detail: str


@dataclass(frozen=True)
class OperationsClosedLoopQualityFinding:
    severity: str
    code: str
    message: str
    snapshot_id: str | None = None


@dataclass(frozen=True)
class OperationsClosedLoopQualityReport:
    ok: bool
    generated_at: str
    snapshot_count: int
    findings: list[OperationsClosedLoopQualityFinding]
    summary: str


@dataclass(frozen=True)
class OperationsClosedLoopCheckpointPlan:
    generated_at: str
    checkpoint: str | None
    next_checkpoint: str | None
    snapshot_count: int
    ready: bool
    summary: str


@dataclass(frozen=True)
class OperationsClosedLoopAcceptanceReport:
    ok: bool
    generated_at: str
    contract_ok: bool
    quality_ok: bool
    publish_ready: bool
    checkpoint_ready: bool
    findings: list[str]


@dataclass(frozen=True)
class OperationsScheduledTask:
    task_id: str
    task_type: str
    cadence: str
    next_run_at: str
    enabled: bool
    params: dict[str, Any] = field(default_factory=dict)
    last_run_at: str | None = None
    last_status: str | None = None
    run_count: int = 0
    failure_count: int = 0
    lease_owner: str | None = None
    lease_expires_at: str | None = None


@dataclass(frozen=True)
class OperationsScheduledTaskResult:
    task_id: str
    task_type: str
    status: str
    started_at: str
    finished_at: str
    detail: str
    output: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OperationsSchedulerRunReport:
    run_id: str
    started_at: str
    finished_at: str
    due_count: int
    executed_count: int
    failed_count: int
    results: list[OperationsScheduledTaskResult]
    summary: str


@dataclass(frozen=True)
class OperationsSchedulerHealthReport:
    generated_at: str
    run_count: int
    task_count: int
    failed_runs: int
    stale_leases: int
    alerts: list[dict[str, Any]]
    summary: str


@dataclass(frozen=True)
class OperationsActionAuthorization:
    allowed: bool
    action: str
    user_id: str
    decision: PermissionDecision
    audit_result: AuditSinkResult | None = None


@dataclass(frozen=True)
class OnCallWebhookReplayJobExecution:
    job: OnCallWebhookReplayJob
    replayed_events: list[OnCallWebhookEvent]
    statuses: list[OnCallTicketStatus]
    result: OnCallWebhookReplayBatchResult


@dataclass(frozen=True)
class OperationsConsoleOverview:
    generated_at: str
    closed_loop_dashboard: OperationsClosedLoopDashboard
    webhook_ops: OnCallWebhookOpsConsole
    replay_jobs: list[OnCallWebhookReplayJob]
    closed_loop_quality: OperationsClosedLoopQualityReport
    closed_loop_acceptance: OperationsClosedLoopAcceptanceReport
    summary: str


@dataclass(frozen=True)
class OperationsConsoleView:
    generated_at: str
    actor: str
    department: str | None
    roles: list[str]
    permissions: dict[str, OperationsActionAuthorization]
    overview: OperationsConsoleOverview
    visible_sections: list[str]
    actions: list[dict[str, Any]]
    read_only: bool


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
                title="补偿 SLO 自动处置",
                when="补偿执行 SLO burn rate、失败、重试等待或调度失败告警触发",
                action="先创建或升级行动项，再按补偿执行策略触发受控重试；所有动作保留 runbook 执行记录和控制台审计。",
                owner="travel-ops",
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


def sync_operations_action_items_from_oncall(
    items: list[OperationsActionItem],
    statuses: list[OnCallTicketStatus],
    updated_at: str | None = None,
) -> OperationsActionStatusSyncReport:
    updated_at = updated_at or datetime.now(timezone.utc).isoformat()
    status_map = {status.ticket_id: status for status in statuses}
    closed_items: list[OperationsActionItem] = []
    skipped_items: list[str] = []
    for item in items:
        if item.status.upper() == "CLOSED":
            skipped_items.append(f"{item.action_id}: already closed")
            continue
        status = _matching_oncall_status(item, status_map)
        if status is None:
            skipped_items.append(f"{item.action_id}: no matching ticket status")
            continue
        if status.status.upper() not in {"RESOLVED", "CLOSED", "DONE"}:
            skipped_items.append(f"{item.action_id}: ticket {status.ticket_id} is {status.status}")
            continue
        closed_items.append(
            close_operations_action_item(
                item,
                f"OnCall ticket {status.ticket_id} {status.status}: {status.detail}",
                updated_at=updated_at,
            )
        )
    return OperationsActionStatusSyncReport(
        scanned_statuses=len(statuses),
        matched_items=len(closed_items),
        closed_items=closed_items,
        skipped_items=skipped_items,
    )


def render_operations_action_status_sync_report(report: OperationsActionStatusSyncReport) -> str:
    lines = [
        "Operations action status sync:",
        f"- scanned_statuses: {report.scanned_statuses}",
        f"- matched_items: {report.matched_items}",
        "- closed_items:",
    ]
    if not report.closed_items:
        lines.append("  - none")
    else:
        for item in report.closed_items:
            lines.append(f"  - {item.action_id}: {item.closure_note}")
    lines.append("- skipped_items:")
    if not report.skipped_items:
        lines.append("  - none")
    else:
        for item in report.skipped_items:
            lines.append(f"  - {item}")
    return "\n".join(lines)


def build_operations_compensation_tasks(
    sessions: list[TravelContext] | None = None,
    replay_jobs: list[OnCallWebhookReplayJob] | None = None,
    action_items: list[OperationsActionItem] | None = None,
    oncall_statuses: list[OnCallTicketStatus] | None = None,
    persisted_tasks: list[OperationsCompensationTask] | None = None,
    sla_report: OperationsActionSlaReport | None = None,
    generated_at: str | None = None,
    owner: str | None = None,
    status: str | None = None,
    source_type: str | None = None,
    limit: int = 20,
) -> OperationsCompensationTaskBoard:
    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    status_map = {item.ticket_id: item for item in oncall_statuses or []}
    sla_map = {finding.action_id: finding for finding in (sla_report.findings if sla_report else [])}
    tasks: list[OperationsCompensationTask] = []
    for context in sessions or []:
        tasks.extend(_compensation_tasks_from_session(context, generated_at))
    for job in replay_jobs or []:
        tasks.append(_compensation_task_from_replay_job(job, generated_at, status_map))
    for item in action_items or []:
        tasks.append(_compensation_task_from_action_item(item, generated_at, status_map, sla_map.get(item.action_id)))
    merged = _merge_compensation_task_overrides(tasks, persisted_tasks or [])
    filtered = [
        task
        for task in merged
        if (owner is None or task.owner == owner)
        and (status is None or task.status == status)
        and (source_type is None or task.source_type == source_type)
    ]
    filtered.sort(key=lambda task: (_severity_rank(task.severity), _timestamp_sort_key(task.updated_at), task.task_id), reverse=True)
    limited = filtered[: max(0, limit)]
    status_counts = dict(Counter(task.status for task in filtered))
    severity_counts = dict(Counter(task.severity for task in filtered))
    filters = {key: value for key, value in {"owner": owner, "status": status, "source_type": source_type}.items() if value}
    summary = f"compensation_tasks={len(limited)}/{len(filtered)} total={len(merged)} open={status_counts.get('OPEN', 0)} escalated={status_counts.get('ESCALATED', 0)}"
    return OperationsCompensationTaskBoard(
        generated_at=generated_at,
        tasks=limited,
        status_counts=status_counts,
        severity_counts=severity_counts,
        total_tasks=len(filtered),
        filters=filters,
        summary=summary,
    )


def close_operations_compensation_task(
    task: OperationsCompensationTask,
    closure_note: str,
    updated_at: str | None = None,
    actor: str | None = None,
) -> OperationsCompensationTask:
    updated_at = updated_at or datetime.now(timezone.utc).isoformat()
    lifecycle = [
        *task.lifecycle,
        {
            "status": "CLOSED",
            "at": updated_at,
            "actor": actor,
            "detail": closure_note,
        },
    ]
    return replace(
        task,
        status="CLOSED",
        updated_at=updated_at,
        lifecycle=lifecycle,
        closure_note=closure_note,
    )


def operations_compensation_task_to_dict(task: OperationsCompensationTask) -> dict[str, Any]:
    return {
        "task_id": task.task_id,
        "source_type": task.source_type,
        "source_id": task.source_id,
        "status": task.status,
        "owner": task.owner,
        "title": task.title,
        "severity": task.severity,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
        "due_at": task.due_at,
        "linked_ticket_id": task.linked_ticket_id,
        "lifecycle": task.lifecycle,
        "refs": task.refs,
        "payload": task.payload,
        "closure_note": task.closure_note,
    }


def operations_compensation_task_from_dict(payload: dict[str, Any]) -> OperationsCompensationTask:
    return OperationsCompensationTask(
        task_id=str(payload["task_id"]),
        source_type=str(payload.get("source_type") or ""),
        source_id=str(payload.get("source_id") or ""),
        status=str(payload.get("status") or "OPEN"),
        owner=str(payload.get("owner") or "travel-ops"),
        title=str(payload.get("title") or ""),
        severity=str(payload.get("severity") or "info"),
        created_at=str(payload.get("created_at") or ""),
        updated_at=str(payload.get("updated_at") or ""),
        due_at=str(payload["due_at"]) if payload.get("due_at") is not None else None,
        linked_ticket_id=str(payload["linked_ticket_id"]) if payload.get("linked_ticket_id") is not None else None,
        lifecycle=[dict(item) for item in payload.get("lifecycle") or []],
        refs=dict(payload.get("refs") or {}),
        payload=dict(payload.get("payload") or {}),
        closure_note=str(payload["closure_note"]) if payload.get("closure_note") is not None else None,
    )


def operations_compensation_task_board_to_dict(board: OperationsCompensationTaskBoard) -> dict[str, Any]:
    return {
        "generated_at": board.generated_at,
        "tasks": [operations_compensation_task_to_dict(task) for task in board.tasks],
        "status_counts": board.status_counts,
        "severity_counts": board.severity_counts,
        "total_tasks": board.total_tasks,
        "filters": board.filters,
        "summary": board.summary,
    }


def render_operations_compensation_tasks(tasks: list[OperationsCompensationTask]) -> str:
    lines = ["Operations compensation tasks:"]
    if not tasks:
        lines.append("- none")
        return "\n".join(lines)
    for task in tasks:
        lines.append(
            f"- {task.task_id}: {task.status} severity={task.severity} owner={task.owner} "
            f"source={task.source_type}/{task.source_id}"
        )
        lines.append(f"  title: {task.title}")
        if task.linked_ticket_id:
            lines.append(f"  ticket: {task.linked_ticket_id}")
        if task.closure_note:
            lines.append(f"  closure: {task.closure_note}")
    return "\n".join(lines)


def render_operations_compensation_task_board_json(board: OperationsCompensationTaskBoard) -> str:
    return json.dumps({"operations_compensation_tasks": operations_compensation_task_board_to_dict(board)}, ensure_ascii=False)


def build_operations_compensation_execution_policy(
    config_json: str | None = None,
) -> OperationsCompensationExecutionPolicy:
    if not config_json:
        return OperationsCompensationExecutionPolicy()
    try:
        payload = json.loads(config_json)
    except (TypeError, ValueError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    return operations_compensation_execution_policy_from_dict(payload)


def operations_compensation_execution_policy_to_dict(
    policy: OperationsCompensationExecutionPolicy,
) -> dict[str, Any]:
    return {
        "enabled": policy.enabled,
        "max_batch_size": policy.max_batch_size,
        "retry_window_seconds": policy.retry_window_seconds,
        "max_failures_per_task": policy.max_failures_per_task,
        "allowed_severities": sorted(policy.allowed_severities),
        "require_oncall_endpoint_for_sources": sorted(policy.require_oncall_endpoint_for_sources),
        "dry_run": policy.dry_run,
    }


def operations_compensation_execution_policy_from_dict(
    payload: dict[str, Any] | None,
) -> OperationsCompensationExecutionPolicy:
    payload = dict(payload or {})
    return OperationsCompensationExecutionPolicy(
        enabled=_safe_bool(payload.get("enabled"), True),
        max_batch_size=max(0, _safe_int(payload.get("max_batch_size"), 20)),
        retry_window_seconds=max(0, _safe_int(payload.get("retry_window_seconds"), 900)),
        max_failures_per_task=max(0, _safe_int(payload.get("max_failures_per_task"), 3)),
        allowed_severities=_string_set(payload.get("allowed_severities")) or {"critical", "warning", "info"},
        require_oncall_endpoint_for_sources=_string_set(payload.get("require_oncall_endpoint_for_sources")),
        dry_run=_safe_bool(payload.get("dry_run"), False),
    )


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _string_set(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        items = value.split(",")
    elif isinstance(value, (list, tuple, set)):
        items = value
    else:
        return set()
    return {str(item).strip() for item in items if str(item).strip()}


def _upper_string_set(value: Any) -> set[str]:
    return {item.upper() for item in _string_set(value)}


def _lower_string_set(value: Any) -> set[str]:
    return {item.lower() for item in _string_set(value)}


def operations_compensation_execution_gate_to_dict(
    gate: OperationsCompensationExecutionGate,
) -> dict[str, Any]:
    return {
        "allowed": gate.allowed,
        "task_id": gate.task_id,
        "status": gate.status,
        "reason": gate.reason,
        "next_retry_at": gate.next_retry_at,
    }


def execute_operations_compensation_tasks(
    tasks: list[OperationsCompensationTask],
    limit: int = 20,
    oncall_endpoint: str | None = None,
    oncall_token: str | None = None,
    http_client: Any | None = None,
    executed_at: str | None = None,
    actor: str = "operations",
    policy: OperationsCompensationExecutionPolicy | None = None,
) -> OperationsCompensationTaskExecutionReport:
    executed_at = executed_at or datetime.now(timezone.utc).isoformat()
    policy = policy or OperationsCompensationExecutionPolicy()
    policy_limit = min(max(0, limit), policy.max_batch_size)
    candidates = [task for task in tasks if task.status in {"OPEN", "ESCALATED"}]
    selected = candidates[:policy_limit]
    executions: list[OperationsCompensationTaskExecution] = []
    for task in selected:
        gate = evaluate_operations_compensation_execution_gate(
            task,
            policy=policy,
            oncall_endpoint=oncall_endpoint,
            now=executed_at,
        )
        if not gate.allowed:
            executions.append(_skipped_compensation_task_execution(task, gate, executed_at, actor))
            continue
        if policy.dry_run:
            dry_run_gate = OperationsCompensationExecutionGate(
                allowed=False,
                task_id=task.task_id,
                status="DRY_RUN",
                reason="dry run policy",
            )
            executions.append(_skipped_compensation_task_execution(task, dry_run_gate, executed_at, actor))
            continue
        execution = _execute_single_compensation_task(
            task,
            oncall_endpoint=oncall_endpoint,
            oncall_token=oncall_token,
            http_client=http_client,
            executed_at=executed_at,
            actor=actor,
            gate=gate,
        )
        executions.append(execution)
    succeeded = sum(1 for item in executions if item.status == "SUCCESS")
    failed = sum(1 for item in executions if item.status == "FAILED")
    skipped = sum(1 for item in executions if item.status == "SKIPPED")
    summary = (
        f"compensation_task_executions attempted={len(executions)} selected={len(selected)} "
        f"candidates={len(candidates)} succeeded={succeeded} failed={failed} skipped={skipped}"
    )
    return OperationsCompensationTaskExecutionReport(
        generated_at=executed_at,
        attempted=len(executions),
        succeeded=succeeded,
        failed=failed,
        skipped=skipped,
        executions=executions,
        summary=summary,
        policy=policy,
    )


def evaluate_operations_compensation_execution_gate(
    task: OperationsCompensationTask,
    policy: OperationsCompensationExecutionPolicy | None = None,
    oncall_endpoint: str | None = None,
    now: str | None = None,
) -> OperationsCompensationExecutionGate:
    policy = policy or OperationsCompensationExecutionPolicy()
    now = now or datetime.now(timezone.utc).isoformat()
    if not policy.enabled:
        return OperationsCompensationExecutionGate(False, task.task_id, "POLICY_DISABLED", "compensation execution policy disabled")
    if task.status not in {"OPEN", "ESCALATED"}:
        return OperationsCompensationExecutionGate(False, task.task_id, "STATUS_NOT_ELIGIBLE", f"task status {task.status} is not executable")
    if task.severity not in policy.allowed_severities:
        return OperationsCompensationExecutionGate(False, task.task_id, "SEVERITY_BLOCKED", f"severity {task.severity} is not allowed")
    if policy.require_oncall_endpoint_for_sources and task.source_type in policy.require_oncall_endpoint_for_sources and not oncall_endpoint and not task.linked_ticket_id:
        return OperationsCompensationExecutionGate(False, task.task_id, "ONCALL_ENDPOINT_REQUIRED", "oncall endpoint is required by policy")
    failures = _compensation_execution_failure_count(task)
    if failures >= policy.max_failures_per_task:
        return OperationsCompensationExecutionGate(False, task.task_id, "FAILURE_THRESHOLD_EXCEEDED", f"failure threshold exceeded: {failures}")
    last_attempt_at = _last_compensation_execution_attempt_at(task)
    if last_attempt_at and policy.retry_window_seconds > 0:
        next_retry_at = datetime.fromtimestamp(
            _parse_iso_datetime(last_attempt_at).timestamp() + policy.retry_window_seconds,
            timezone.utc,
        ).isoformat()
        if _timestamp_sort_key(now) < _timestamp_sort_key(next_retry_at):
            return OperationsCompensationExecutionGate(
                False,
                task.task_id,
                "RETRY_WINDOW_ACTIVE",
                "retry window is still active",
                next_retry_at=next_retry_at,
            )
    return OperationsCompensationExecutionGate(True, task.task_id, "ALLOWED", "policy allowed")


def operations_compensation_task_execution_to_dict(
    execution: OperationsCompensationTaskExecution,
) -> dict[str, Any]:
    return {
        "execution_id": execution.execution_id,
        "task_id": execution.task_id,
        "action": execution.action,
        "status": execution.status,
        "detail": execution.detail,
        "executed_at": execution.executed_at,
        "task": operations_compensation_task_to_dict(execution.task),
        "ticket_result": (
            {
                "ok": execution.ticket_result.ok,
                "endpoint": execution.ticket_result.endpoint,
                "ticket_id": execution.ticket_result.ticket_id,
                "delivered": execution.ticket_result.delivered,
                "failed": execution.ticket_result.failed,
                "detail": execution.ticket_result.detail,
            }
            if execution.ticket_result is not None
            else None
        ),
        "gate": operations_compensation_execution_gate_to_dict(execution.gate) if execution.gate is not None else None,
    }


def operations_compensation_task_execution_report_to_dict(
    report: OperationsCompensationTaskExecutionReport,
) -> dict[str, Any]:
    return {
        "generated_at": report.generated_at,
        "attempted": report.attempted,
        "succeeded": report.succeeded,
        "failed": report.failed,
        "skipped": report.skipped,
        "executions": [operations_compensation_task_execution_to_dict(item) for item in report.executions],
        "summary": report.summary,
        "policy": operations_compensation_execution_policy_to_dict(report.policy),
    }


def render_operations_compensation_task_execution_report_json(
    report: OperationsCompensationTaskExecutionReport,
) -> str:
    return json.dumps(
        {"operations_compensation_task_execution": operations_compensation_task_execution_report_to_dict(report)},
        ensure_ascii=False,
    )


def build_operations_compensation_execution_observability_report(
    tasks: list[OperationsCompensationTask],
    scheduler_runs: list[OperationsSchedulerRunReport] | None = None,
    action_audits: list[OperationsConsoleActionAudit] | None = None,
    generated_at: str | None = None,
) -> OperationsCompensationExecutionObservabilityReport:
    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    attempted = 0
    succeeded = 0
    failed = 0
    skipped = 0
    retry_waiting = 0
    manual_task_ids: set[str] = set()
    gate_counts: Counter[str] = Counter()
    failure_reasons: Counter[str] = Counter()
    action_counts: Counter[str] = Counter()
    latest_attempt_at: str | None = None
    slowest_retry_seconds: int | None = None

    for task in tasks:
        if task.status == "PENDING_MANUAL":
            manual_task_ids.add(task.task_id)
        for event in task.lifecycle:
            if not isinstance(event, dict):
                continue
            event_status = str(event.get("status") or "").upper()
            if event_status == "EXECUTION_ATTEMPT":
                attempted += 1
                execution_status = str(event.get("execution_status") or "UNKNOWN").upper()
                action = str(event.get("action") or "unknown")
                action_counts[action] += 1
                if execution_status == "SUCCESS":
                    succeeded += 1
                elif execution_status == "FAILED":
                    failed += 1
                    failure_reasons[_compensation_observability_reason_key(event.get("detail"))] += 1
                elif execution_status == "SKIPPED":
                    skipped += 1
                if action == "mark_pending_manual":
                    manual_task_ids.add(task.task_id)
                attempt_at = str(event.get("at") or "")
                if attempt_at and (
                    latest_attempt_at is None
                    or _timestamp_sort_key(attempt_at) >= _timestamp_sort_key(latest_attempt_at)
                ):
                    latest_attempt_at = attempt_at
            elif event_status == "EXECUTION_GATE":
                gate_status = str(event.get("gate_status") or "UNKNOWN").upper()
                gate_counts[gate_status] += 1
                if gate_status == "RETRY_WINDOW_ACTIVE":
                    retry_waiting += 1
                retry_seconds = _compensation_observability_retry_seconds(event)
                if retry_seconds is not None and (
                    slowest_retry_seconds is None or retry_seconds > slowest_retry_seconds
                ):
                    slowest_retry_seconds = retry_seconds

    scheduler_run_count = 0
    scheduler_attempted = 0
    scheduler_failed = 0
    for run in scheduler_runs or []:
        has_compensation_result = False
        for result in run.results:
            if result.task_type != "compensation_task_execution":
                continue
            has_compensation_result = True
            output = result.output or {}
            scheduler_attempted += _safe_int(output.get("attempted"), 0)
            scheduler_failed += _safe_int(
                output.get("failed"),
                1 if result.status == "FAILED" else 0,
            )
        if has_compensation_result:
            scheduler_run_count += 1

    console_actions = sum(
        1
        for audit in action_audits or []
        if audit.action == "execute_compensation_tasks"
    )
    success_rate = round(succeeded / attempted, 4) if attempted else 0.0
    summary = (
        f"compensation_execution tasks={len(tasks)} attempted={attempted} "
        f"success_rate={success_rate:.2%} failed={failed} skipped={skipped} "
        f"retry_waiting={retry_waiting} manual_interventions={len(manual_task_ids)} "
        f"scheduler_runs={scheduler_run_count} console_actions={console_actions}"
    )
    return OperationsCompensationExecutionObservabilityReport(
        generated_at=generated_at,
        task_count=len(tasks),
        attempted=attempted,
        succeeded=succeeded,
        failed=failed,
        skipped=skipped,
        success_rate=success_rate,
        manual_interventions=len(manual_task_ids),
        retry_waiting=retry_waiting,
        gate_counts=dict(sorted(gate_counts.items())),
        failure_reasons=dict(sorted(failure_reasons.items(), key=lambda item: (-item[1], item[0]))),
        action_counts=dict(sorted(action_counts.items())),
        scheduler_runs=scheduler_run_count,
        scheduler_attempted=scheduler_attempted,
        scheduler_failed=scheduler_failed,
        console_actions=console_actions,
        latest_attempt_at=latest_attempt_at,
        slowest_retry_seconds=slowest_retry_seconds,
        summary=summary,
    )


def operations_compensation_execution_observability_report_to_dict(
    report: OperationsCompensationExecutionObservabilityReport,
) -> dict[str, Any]:
    return {
        "generated_at": report.generated_at,
        "task_count": report.task_count,
        "attempted": report.attempted,
        "succeeded": report.succeeded,
        "failed": report.failed,
        "skipped": report.skipped,
        "success_rate": report.success_rate,
        "manual_interventions": report.manual_interventions,
        "retry_waiting": report.retry_waiting,
        "gate_counts": report.gate_counts,
        "failure_reasons": report.failure_reasons,
        "action_counts": report.action_counts,
        "scheduler_runs": report.scheduler_runs,
        "scheduler_attempted": report.scheduler_attempted,
        "scheduler_failed": report.scheduler_failed,
        "console_actions": report.console_actions,
        "latest_attempt_at": report.latest_attempt_at,
        "slowest_retry_seconds": report.slowest_retry_seconds,
        "summary": report.summary,
    }


def render_operations_compensation_execution_observability_report_json(
    report: OperationsCompensationExecutionObservabilityReport,
) -> str:
    return json.dumps(
        {
            "operations_compensation_execution_observability": (
                operations_compensation_execution_observability_report_to_dict(report)
            )
        },
        ensure_ascii=False,
    )


def build_operations_compensation_slo_policy(
    config_json: str | None = None,
) -> OperationsCompensationSloPolicy:
    if not config_json:
        return OperationsCompensationSloPolicy()
    try:
        payload = json.loads(config_json)
    except (TypeError, ValueError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    return operations_compensation_slo_policy_from_dict(payload)


def operations_compensation_slo_policy_to_dict(policy: OperationsCompensationSloPolicy) -> dict[str, Any]:
    return {
        "enabled": policy.enabled,
        "min_attempts": policy.min_attempts,
        "success_rate_target": policy.success_rate_target,
        "warning_burn_rate": policy.warning_burn_rate,
        "critical_burn_rate": policy.critical_burn_rate,
        "max_failed": policy.max_failed,
        "max_retry_waiting": policy.max_retry_waiting,
        "max_manual_interventions": policy.max_manual_interventions,
        "max_scheduler_failed": policy.max_scheduler_failed,
        "max_retry_seconds": policy.max_retry_seconds,
        "route": policy.route,
        "escalation": policy.escalation,
    }


def operations_compensation_slo_policy_from_dict(payload: dict[str, Any] | None) -> OperationsCompensationSloPolicy:
    payload = dict(payload or {})
    return OperationsCompensationSloPolicy(
        enabled=_safe_bool(payload.get("enabled"), True),
        min_attempts=max(0, _safe_int(payload.get("min_attempts"), 1)),
        success_rate_target=min(0.9999, max(0.0, _safe_float(payload.get("success_rate_target"), 0.95))),
        warning_burn_rate=max(0.0, _safe_float(payload.get("warning_burn_rate"), 1.0)),
        critical_burn_rate=max(0.0, _safe_float(payload.get("critical_burn_rate"), 2.0)),
        max_failed=max(0, _safe_int(payload.get("max_failed"), 0)),
        max_retry_waiting=max(0, _safe_int(payload.get("max_retry_waiting"), 5)),
        max_manual_interventions=max(0, _safe_int(payload.get("max_manual_interventions"), 5)),
        max_scheduler_failed=max(0, _safe_int(payload.get("max_scheduler_failed"), 0)),
        max_retry_seconds=max(0, _safe_int(payload.get("max_retry_seconds"), 1800)),
        route=str(payload.get("route") or "travel-ops"),
        escalation=str(payload.get("escalation") or "page compensation owner"),
    )


def evaluate_operations_compensation_slo(
    observability: OperationsCompensationExecutionObservabilityReport,
    policy: OperationsCompensationSloPolicy | None = None,
    generated_at: str | None = None,
) -> OperationsCompensationSloReport:
    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    policy = policy or OperationsCompensationSloPolicy()
    error_budget = max(0.0001, 1.0 - policy.success_rate_target)
    has_enough_attempts = observability.attempted >= policy.min_attempts
    actual_error_rate = 1.0 - observability.success_rate if has_enough_attempts else 0.0
    burn_rate = round(actual_error_rate / error_budget, 4) if policy.enabled else 0.0
    error_budget_remaining = round(max(0.0, 1.0 - burn_rate), 4)
    alerts: list[dict[str, Any]] = []
    if policy.enabled:
        if has_enough_attempts and burn_rate >= policy.warning_burn_rate:
            severity = "critical" if burn_rate >= policy.critical_burn_rate else "warning"
            alerts.append(
                _compensation_slo_alert(
                    "compensation_slo_burn_rate",
                    severity,
                    f"compensation execution burn rate {burn_rate:.2f} exceeds {policy.warning_burn_rate:.2f}",
                    int(round(burn_rate * 100)),
                    policy,
                    generated_at,
                    burn_rate=burn_rate,
                    success_rate=observability.success_rate,
                )
            )
        if observability.failed > policy.max_failed:
            alerts.append(
                _compensation_slo_alert(
                    "compensation_execution_failed",
                    "critical",
                    f"compensation execution failed={observability.failed} exceeds {policy.max_failed}",
                    observability.failed,
                    policy,
                    generated_at,
                )
            )
        if observability.retry_waiting > policy.max_retry_waiting:
            alerts.append(
                _compensation_slo_alert(
                    "compensation_retry_waiting_high",
                    "warning",
                    f"compensation retry waiting={observability.retry_waiting} exceeds {policy.max_retry_waiting}",
                    observability.retry_waiting,
                    policy,
                    generated_at,
                )
            )
        if observability.manual_interventions > policy.max_manual_interventions:
            alerts.append(
                _compensation_slo_alert(
                    "compensation_manual_intervention_high",
                    "warning",
                    f"compensation manual interventions={observability.manual_interventions} exceeds {policy.max_manual_interventions}",
                    observability.manual_interventions,
                    policy,
                    generated_at,
                )
            )
        if observability.scheduler_failed > policy.max_scheduler_failed:
            alerts.append(
                _compensation_slo_alert(
                    "compensation_scheduler_failed",
                    "critical",
                    f"compensation scheduler failed={observability.scheduler_failed} exceeds {policy.max_scheduler_failed}",
                    observability.scheduler_failed,
                    policy,
                    generated_at,
                )
            )
        if (
            observability.slowest_retry_seconds is not None
            and observability.slowest_retry_seconds > policy.max_retry_seconds
        ):
            alerts.append(
                _compensation_slo_alert(
                    "compensation_retry_latency_high",
                    "warning",
                    f"compensation retry wait seconds={observability.slowest_retry_seconds} exceeds {policy.max_retry_seconds}",
                    observability.slowest_retry_seconds,
                    policy,
                    generated_at,
                )
            )
    ok = not alerts
    summary = (
        f"compensation_slo ok={ok} burn_rate={burn_rate:.2f} "
        f"success_rate={observability.success_rate:.2%} alerts={len(alerts)}"
    )
    return OperationsCompensationSloReport(
        generated_at=generated_at,
        ok=ok,
        burn_rate=burn_rate,
        error_budget_remaining=error_budget_remaining,
        policy=policy,
        observability=observability,
        alerts=alerts,
        summary=summary,
    )


def operations_compensation_slo_report_to_dict(report: OperationsCompensationSloReport) -> dict[str, Any]:
    return {
        "generated_at": report.generated_at,
        "ok": report.ok,
        "burn_rate": report.burn_rate,
        "error_budget_remaining": report.error_budget_remaining,
        "policy": operations_compensation_slo_policy_to_dict(report.policy),
        "observability": operations_compensation_execution_observability_report_to_dict(report.observability),
        "alerts": [_normalize_alert(alert) for alert in report.alerts],
        "summary": report.summary,
    }


def render_operations_compensation_slo_report_json(report: OperationsCompensationSloReport) -> str:
    return json.dumps(
        {"operations_compensation_slo": operations_compensation_slo_report_to_dict(report)},
        ensure_ascii=False,
    )


def open_operations_compensation_slo_ticket_http(
    report: OperationsCompensationSloReport,
    endpoint: str,
    token: str | None = None,
    http_client: Any | None = None,
) -> OnCallTicketResult:
    from .integrations import JsonHttpClient

    payload = {
        "source": "travel-agent",
        "summary": "Travel compensation execution SLO alert",
        "slo": operations_compensation_slo_report_to_dict(report),
        "alerts": [_normalize_alert(alert) for alert in report.alerts],
    }
    try:
        client = http_client or JsonHttpClient()
        response = client.post_json(endpoint, payload, token)
    except Exception as exc:
        return OnCallTicketResult(False, endpoint, None, 0, 1, str(exc))
    ticket_id = response.get("ticket_id") or response.get("id") or response.get("incident_id")
    ok = bool(response.get("ok", True))
    return OnCallTicketResult(
        ok=ok,
        endpoint=endpoint,
        ticket_id=str(ticket_id) if ticket_id is not None else None,
        delivered=1 if ok else 0,
        failed=0 if ok else 1,
        detail=str(response.get("detail") or "compensation slo ticket opened"),
    )


def build_operations_compensation_remediation_policy(
    config_json: str | None = None,
) -> OperationsCompensationRemediationPolicy:
    if not config_json:
        return OperationsCompensationRemediationPolicy()
    try:
        payload = json.loads(config_json)
    except (TypeError, ValueError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    return operations_compensation_remediation_policy_from_dict(payload)


def operations_compensation_remediation_policy_to_dict(
    policy: OperationsCompensationRemediationPolicy,
) -> dict[str, Any]:
    return {
        "enabled": policy.enabled,
        "create_action_items": policy.create_action_items,
        "controlled_retry_enabled": policy.controlled_retry_enabled,
        "max_retry_tasks": policy.max_retry_tasks,
        "retry_statuses": sorted(policy.retry_statuses),
        "retry_severities": sorted(policy.retry_severities),
        "action_owner": policy.action_owner,
        "action_eta": policy.action_eta,
        "runbook_owner": policy.runbook_owner,
        "dry_run": policy.dry_run,
    }


def operations_compensation_remediation_policy_from_dict(
    payload: dict[str, Any] | None,
) -> OperationsCompensationRemediationPolicy:
    payload = dict(payload or {})
    return OperationsCompensationRemediationPolicy(
        enabled=_safe_bool(payload.get("enabled"), True),
        create_action_items=_safe_bool(payload.get("create_action_items"), True),
        controlled_retry_enabled=_safe_bool(payload.get("controlled_retry_enabled"), True),
        max_retry_tasks=max(0, _safe_int(payload.get("max_retry_tasks"), 3)),
        retry_statuses=_upper_string_set(payload.get("retry_statuses")) or {"OPEN", "ESCALATED"},
        retry_severities=_lower_string_set(payload.get("retry_severities")) or {"critical", "warning"},
        action_owner=str(payload.get("action_owner") or "travel-ops"),
        action_eta=str(payload["action_eta"]) if payload.get("action_eta") is not None else None,
        runbook_owner=str(payload.get("runbook_owner") or "travel-ops"),
        dry_run=_safe_bool(payload.get("dry_run"), False),
    )


def build_operations_compensation_remediation_report(
    slo_report: OperationsCompensationSloReport,
    tasks: list[OperationsCompensationTask] | None = None,
    retry_execution_report: OperationsCompensationTaskExecutionReport | None = None,
    policy: OperationsCompensationRemediationPolicy | None = None,
    generated_at: str | None = None,
) -> OperationsCompensationRemediationReport:
    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    policy = policy or OperationsCompensationRemediationPolicy()
    alerts = [_normalize_alert(alert) for alert in slo_report.alerts]
    action_items = (
        _compensation_remediation_action_items(alerts, policy, generated_at)
        if policy.enabled and policy.create_action_items and alerts
        else []
    )
    retry_candidates = (
        _compensation_remediation_retry_candidates(tasks or [], policy)
        if policy.enabled and policy.controlled_retry_enabled and alerts
        else []
    )
    retry_task_ids = [task.task_id for task in retry_candidates[: policy.max_retry_tasks]]
    runbook_executions = (
        _compensation_remediation_runbooks(alerts, retry_task_ids, policy, generated_at)
        if policy.enabled and alerts
        else []
    )
    ok = slo_report.ok or (not alerts and not retry_candidates)
    summary = (
        f"compensation_remediation ok={ok} alerts={len(alerts)} "
        f"action_items={len(action_items)} retry_candidates={len(retry_candidates)} "
        f"retry_selected={len(retry_task_ids)} runbooks={len(runbook_executions)} dry_run={policy.dry_run}"
    )
    return OperationsCompensationRemediationReport(
        generated_at=generated_at,
        ok=ok,
        policy=policy,
        slo_report=slo_report,
        action_items=action_items,
        runbook_executions=runbook_executions,
        retry_candidates=retry_candidates,
        retry_task_ids=retry_task_ids,
        retry_execution_report=retry_execution_report,
        summary=summary,
    )


def operations_compensation_runbook_execution_to_dict(
    execution: OperationsCompensationRunbookExecution,
) -> dict[str, Any]:
    return {
        "runbook_id": execution.runbook_id,
        "title": execution.title,
        "status": execution.status,
        "trigger": execution.trigger,
        "owner": execution.owner,
        "executed_at": execution.executed_at,
        "action": execution.action,
        "evidence": execution.evidence,
    }


def operations_compensation_remediation_report_to_dict(
    report: OperationsCompensationRemediationReport,
) -> dict[str, Any]:
    return {
        "generated_at": report.generated_at,
        "ok": report.ok,
        "policy": operations_compensation_remediation_policy_to_dict(report.policy),
        "slo": operations_compensation_slo_report_to_dict(report.slo_report),
        "action_items": [operations_action_item_to_dict(item) for item in report.action_items],
        "runbook_executions": [
            operations_compensation_runbook_execution_to_dict(item)
            for item in report.runbook_executions
        ],
        "retry_candidates": [operations_compensation_task_to_dict(task) for task in report.retry_candidates],
        "retry_task_ids": report.retry_task_ids,
        "retry_execution": (
            operations_compensation_task_execution_report_to_dict(report.retry_execution_report)
            if report.retry_execution_report is not None
            else None
        ),
        "summary": report.summary,
    }


def render_operations_compensation_remediation_report_json(
    report: OperationsCompensationRemediationReport,
) -> str:
    return json.dumps(
        {
            "operations_compensation_remediation": (
                operations_compensation_remediation_report_to_dict(report)
            )
        },
        ensure_ascii=False,
    )


def open_compensation_task_ticket_http(
    task: OperationsCompensationTask,
    endpoint: str,
    token: str | None = None,
    http_client: Any | None = None,
) -> OnCallTicketResult:
    from .integrations import JsonHttpClient

    payload = {
        "source": "travel-agent",
        "summary": task.title,
        "task_id": task.task_id,
        "severity": task.severity,
        "status": task.status,
        "owner": task.owner,
        "source_type": task.source_type,
        "source_id": task.source_id,
        "refs": task.refs,
        "lifecycle": task.lifecycle,
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
        detail=str(response.get("detail") or "compensation task ticket opened"),
    )


def _execute_single_compensation_task(
    task: OperationsCompensationTask,
    oncall_endpoint: str | None,
    oncall_token: str | None,
    http_client: Any | None,
    executed_at: str,
    actor: str,
    gate: OperationsCompensationExecutionGate | None = None,
) -> OperationsCompensationTaskExecution:
    if task.linked_ticket_id:
        attempt_event = _compensation_execution_attempt_event("SUCCESS", "wait_oncall", executed_at, actor, f"waiting for ticket {task.linked_ticket_id}")
        updated = replace(
            task,
            status="WAITING_ONCALL",
            updated_at=executed_at,
            lifecycle=[
                *task.lifecycle,
                attempt_event,
                {
                    "status": "WAITING_ONCALL",
                    "at": executed_at,
                    "actor": actor,
                    "detail": f"waiting for ticket {task.linked_ticket_id}",
                },
            ],
        )
        return OperationsCompensationTaskExecution(
            execution_id=_stable_id("OCTX", task.task_id, executed_at, "wait"),
            task_id=task.task_id,
            action="wait_oncall",
            status="SUCCESS",
            detail=f"waiting for ticket {task.linked_ticket_id}",
            executed_at=executed_at,
            task=updated,
            gate=gate,
        )
    if not oncall_endpoint:
        attempt_event = _compensation_execution_attempt_event("SKIPPED", "mark_pending_manual", executed_at, actor, "oncall endpoint is not configured")
        updated = replace(
            task,
            status="PENDING_MANUAL",
            updated_at=executed_at,
            lifecycle=[
                *task.lifecycle,
                attempt_event,
                {
                    "status": "PENDING_MANUAL",
                    "at": executed_at,
                    "actor": actor,
                    "detail": "oncall endpoint is not configured",
                },
            ],
        )
        return OperationsCompensationTaskExecution(
            execution_id=_stable_id("OCTX", task.task_id, executed_at, "manual"),
            task_id=task.task_id,
            action="mark_pending_manual",
            status="SKIPPED",
            detail="oncall endpoint is not configured",
            executed_at=executed_at,
            task=updated,
            gate=gate,
        )
    ticket = open_compensation_task_ticket_http(task, oncall_endpoint, token=oncall_token, http_client=http_client)
    next_status = "WAITING_ONCALL" if ticket.ok and ticket.ticket_id else "ESCALATED"
    execution_status = "SUCCESS" if ticket.ok and ticket.ticket_id else "FAILED"
    attempt_event = _compensation_execution_attempt_event(execution_status, "open_oncall_ticket", executed_at, actor, ticket.detail)
    updated = replace(
        task,
        status=next_status,
        updated_at=executed_at,
        linked_ticket_id=ticket.ticket_id or task.linked_ticket_id,
        lifecycle=[
            *task.lifecycle,
            attempt_event,
            {
                "status": next_status,
                "at": executed_at,
                "actor": actor,
                "detail": ticket.detail,
                "ticket_id": ticket.ticket_id,
            },
        ],
        payload={
            **task.payload,
            "ticket_result": {
                "ok": ticket.ok,
                "endpoint": ticket.endpoint,
                "ticket_id": ticket.ticket_id,
                "delivered": ticket.delivered,
                "failed": ticket.failed,
                "detail": ticket.detail,
            },
        },
    )
    return OperationsCompensationTaskExecution(
        execution_id=_stable_id("OCTX", task.task_id, executed_at, "ticket", ticket.ticket_id or ticket.detail),
        task_id=task.task_id,
        action="open_oncall_ticket",
        status=execution_status,
        detail=ticket.detail,
        executed_at=executed_at,
        task=updated,
        ticket_result=ticket,
        gate=gate,
    )


def _skipped_compensation_task_execution(
    task: OperationsCompensationTask,
    gate: OperationsCompensationExecutionGate,
    executed_at: str,
    actor: str,
) -> OperationsCompensationTaskExecution:
    gate_event = {
        "status": "EXECUTION_GATE",
        "gate_status": gate.status,
        "action": "policy_gate",
        "at": executed_at,
        "actor": actor,
        "detail": gate.reason,
        "next_retry_at": gate.next_retry_at,
    }
    updated = replace(
        task,
        updated_at=executed_at,
        lifecycle=[*task.lifecycle, gate_event],
        payload={**task.payload, "execution_gate": operations_compensation_execution_gate_to_dict(gate)},
    )
    return OperationsCompensationTaskExecution(
        execution_id=_stable_id("OCTX", task.task_id, executed_at, "gate", gate.status),
        task_id=task.task_id,
        action="policy_gate",
        status="SKIPPED",
        detail=gate.reason,
        executed_at=executed_at,
        task=updated,
        gate=gate,
    )


def _compensation_execution_attempt_event(
    status: str,
    action: str,
    at: str,
    actor: str,
    detail: str,
) -> dict[str, Any]:
    return {
        "status": "EXECUTION_ATTEMPT",
        "execution_status": status,
        "action": action,
        "at": at,
        "actor": actor,
        "detail": detail,
    }


def _compensation_execution_failure_count(task: OperationsCompensationTask) -> int:
    return sum(
        1
        for event in task.lifecycle
        if str(event.get("status") or "").upper() == "EXECUTION_ATTEMPT"
        and str(event.get("execution_status") or "").upper() == "FAILED"
    )


def _last_compensation_execution_attempt_at(task: OperationsCompensationTask) -> str | None:
    attempts = [
        str(event.get("at"))
        for event in task.lifecycle
        if str(event.get("status") or "").upper() == "EXECUTION_ATTEMPT" and event.get("at")
    ]
    if not attempts:
        return None
    attempts.sort(key=_timestamp_sort_key, reverse=True)
    return attempts[0]


def _compensation_observability_reason_key(detail: object) -> str:
    normalized = str(detail or "").strip().lower()
    if not normalized:
        return "unknown"
    if "timeout" in normalized:
        return "timeout"
    if "endpoint" in normalized or "configured" in normalized:
        return "endpoint_unavailable"
    if "ticket" in normalized and ("missing" in normalized or "not" in normalized):
        return "ticket_missing"
    if "http" in normalized or "status" in normalized:
        return "http_failure"
    return normalized[:80]


def _compensation_observability_retry_seconds(event: dict[str, Any]) -> int | None:
    at = str(event.get("at") or "")
    next_retry_at = str(event.get("next_retry_at") or "")
    if not at or not next_retry_at:
        return None
    seconds = int(_timestamp_sort_key(next_retry_at) - _timestamp_sort_key(at))
    return seconds if seconds >= 0 else None


def _compensation_slo_alert(
    alert_type: str,
    severity: str,
    message: str,
    value: int,
    policy: OperationsCompensationSloPolicy,
    generated_at: str,
    **extra: Any,
) -> dict[str, Any]:
    return {
        "alert_type": alert_type,
        "severity": severity,
        "message": message,
        "value": value,
        "route": policy.route,
        "escalation": policy.escalation,
        "generated_at": generated_at,
        **extra,
    }


def _compensation_remediation_action_items(
    alerts: list[dict[str, Any]],
    policy: OperationsCompensationRemediationPolicy,
    generated_at: str,
) -> list[OperationsActionItem]:
    items: list[OperationsActionItem] = []
    for alert in alerts:
        alert_type = str(alert.get("alert_type") or "unknown")
        severity = str(alert.get("severity") or "warning")
        owner = str(alert.get("route") or policy.action_owner or "travel-ops")
        title = f"Remediate compensation SLO alert: {alert_type}"
        evidence = [
            f"alert_type={alert_type}",
            f"severity={severity}",
            f"value={alert.get('value')}",
            f"message={alert.get('message')}",
        ]
        if alert.get("burn_rate") is not None:
            evidence.append(f"burn_rate={alert.get('burn_rate')}")
        if alert.get("escalation"):
            evidence.append(f"escalation={alert.get('escalation')}")
        items.append(
            OperationsActionItem(
                action_id=_stable_id("ACT", "compensation_slo", alert_type, severity, str(alert.get("generated_at") or generated_at)),
                source_type="compensation_slo",
                source_id=alert_type,
                title=title,
                owner=owner,
                status="OPEN",
                eta=policy.action_eta,
                created_at=generated_at,
                updated_at=generated_at,
                evidence=evidence,
            )
        )
    return items


def _compensation_remediation_retry_candidates(
    tasks: list[OperationsCompensationTask],
    policy: OperationsCompensationRemediationPolicy,
) -> list[OperationsCompensationTask]:
    candidates = [
        task
        for task in tasks
        if task.status.upper() in policy.retry_statuses
        and task.severity.lower() in policy.retry_severities
    ]
    candidates.sort(key=lambda task: (_severity_rank(task.severity), _timestamp_sort_key(task.updated_at), task.task_id), reverse=True)
    return candidates[: policy.max_retry_tasks]


def _compensation_remediation_runbooks(
    alerts: list[dict[str, Any]],
    retry_task_ids: list[str],
    policy: OperationsCompensationRemediationPolicy,
    generated_at: str,
) -> list[OperationsCompensationRunbookExecution]:
    if not alerts:
        return []
    alert_types = [str(alert.get("alert_type") or "unknown") for alert in alerts]
    status = "DRY_RUN" if policy.dry_run else "RECORDED"
    action = (
        "Create or update compensation SLO action items; trigger controlled compensation retry for selected tasks."
        if retry_task_ids
        else "Create or update compensation SLO action items; no retry candidate selected."
    )
    return [
        OperationsCompensationRunbookExecution(
            runbook_id=_stable_id("ORB", "compensation_slo_remediation", generated_at, ",".join(alert_types)),
            title="补偿 SLO 自动处置",
            status=status,
            trigger=",".join(_dedupe(alert_types)),
            owner=policy.runbook_owner,
            executed_at=generated_at,
            action=action,
            evidence=[
                f"alerts={len(alerts)}",
                f"retry_task_ids={','.join(retry_task_ids) if retry_task_ids else '-'}",
                f"dry_run={policy.dry_run}",
            ],
        )
    ]


def _compensation_tasks_from_session(context: TravelContext, generated_at: str) -> list[OperationsCompensationTask]:
    tasks: list[OperationsCompensationTask] = []
    for label, compensation in (
        ("approval_cancellation", context.approval_cancellation),
        ("order_cancellation", context.order_cancellation),
        ("transport_order_cancellation", context.transport_order_cancellation),
        ("inventory_release", context.inventory_release),
    ):
        if compensation is not None:
            tasks.append(_compensation_task_from_result(context, label, compensation, generated_at))
    for index, compensation in enumerate(context.change_failure_compensations):
        tasks.append(_compensation_task_from_result(context, f"change_failure_compensation_{index + 1}", compensation, generated_at))
    for record in context.recovery_records:
        execution = record.payload.get("strategy_execution")
        if isinstance(execution, dict):
            result = recovery_strategy_execution_result_from_dict(execution)
            tasks.append(_compensation_task_from_recovery_execution(context, record, result, generated_at))
    return tasks


def _compensation_task_from_result(
    context: TravelContext,
    label: str,
    compensation: CompensationResult,
    generated_at: str,
) -> OperationsCompensationTask:
    normalized_status = _normalize_status_value(compensation.status)
    status = "CLOSED" if normalized_status in {"SUCCESS", "COMPLETED", "DONE", "CANCELLED", "RELEASED"} else "ESCALATED"
    severity = "info" if status == "CLOSED" else "critical"
    task_id = _stable_id("OCT", context.session_id, label, compensation.action, compensation.target_id)
    lifecycle = [
        {
            "status": status,
            "at": generated_at,
            "actor": "system",
            "detail": f"{compensation.action} {compensation.status}",
        }
    ]
    return OperationsCompensationTask(
        task_id=task_id,
        source_type="compensation_result",
        source_id=f"{context.session_id}:{label}",
        status=status,
        owner="travel-ops",
        title=f"{label} for {compensation.target_id}",
        severity=severity,
        created_at=generated_at,
        updated_at=generated_at,
        due_at=None,
        linked_ticket_id=_ticket_id_from_payload(compensation.payload),
        lifecycle=lifecycle,
        refs={"session_id": context.session_id, "target_id": compensation.target_id, "action": compensation.action},
        payload={"compensation": compensation.__dict__},
    )


def _compensation_task_from_recovery_execution(
    context: TravelContext,
    record: Any,
    result: RecoveryStrategyExecutionResult,
    generated_at: str,
) -> OperationsCompensationTask:
    status = "CLOSED" if result.status.upper() in {"SUCCESS", "SKIPPED"} else "ESCALATED"
    if result.gate_status.upper() in {"BLOCKED", "REQUIRES_APPROVAL"} and not result.approval_override:
        status = "OPEN"
    severity = "critical" if status == "ESCALATED" else "warning" if status == "OPEN" else "info"
    return OperationsCompensationTask(
        task_id=_stable_id("OCT", context.session_id, record.recovery_id, result.execution_id),
        source_type="recovery_strategy_execution",
        source_id=result.execution_id,
        status=status,
        owner="travel-ops",
        title=f"{result.action} recovery for {context.session_id}",
        severity=severity,
        created_at=result.created_at or record.created_at or generated_at,
        updated_at=result.created_at or record.created_at or generated_at,
        due_at=None,
        linked_ticket_id=_ticket_id_from_payload(record.payload),
        lifecycle=[
            {
                "status": status,
                "at": result.created_at or generated_at,
                "actor": "RecoveryStrategyExecutor",
                "detail": result.detail,
            }
        ],
        refs={"session_id": context.session_id, "recovery_id": record.recovery_id, "decision_id": result.decision_id},
        payload={"recovery_record": record.__dict__, "strategy_execution": recovery_strategy_execution_result_to_dict(result)},
    )


def _compensation_task_from_replay_job(
    job: OnCallWebhookReplayJob,
    generated_at: str,
    status_map: dict[str, OnCallTicketStatus],
) -> OperationsCompensationTask:
    status = "OPEN" if job.status == "PENDING" else "CLOSED" if job.status == "COMPLETED" else "ESCALATED"
    linked_status = _status_for_replay_job(job, status_map)
    if linked_status and linked_status.status.upper() in {"RESOLVED", "CLOSED", "DONE"}:
        status = "CLOSED"
    severity = "warning" if status == "OPEN" else "critical" if status == "ESCALATED" else "info"
    ticket_id = linked_status.ticket_id if linked_status else None
    return OperationsCompensationTask(
        task_id=_stable_id("OCT", "replay_job", job.job_id),
        source_type="replay_job",
        source_id=job.job_id,
        status=status,
        owner=job.requested_by or "travel-ops",
        title=f"Replay {len(job.event_ids)} webhook event(s)",
        severity=severity,
        created_at=job.created_at,
        updated_at=str(job.audit.get("executed_at") or job.created_at),
        due_at=None,
        linked_ticket_id=ticket_id,
        lifecycle=[
            {"status": job.status, "at": job.created_at, "actor": job.requested_by, "detail": "replay job created"},
            *(
                [{"status": status, "at": str(job.audit.get("executed_at")), "actor": "replay_executor", "detail": "replay job executed"}]
                if job.audit.get("executed_at")
                else []
            ),
        ],
        refs={"job_id": job.job_id, "event_ids": job.event_ids},
        payload=oncall_webhook_replay_job_to_dict(job),
    )


def _compensation_task_from_action_item(
    item: OperationsActionItem,
    generated_at: str,
    status_map: dict[str, OnCallTicketStatus],
    sla_finding: OperationsActionSlaFinding | None,
) -> OperationsCompensationTask:
    linked_status = _matching_oncall_status(item, status_map)
    status = "CLOSED" if item.status.upper() == "CLOSED" else "OPEN"
    if linked_status and linked_status.status.upper() in {"RESOLVED", "CLOSED", "DONE"}:
        status = "CLOSED"
    elif sla_finding is not None:
        status = "ESCALATED"
    severity = sla_finding.severity if sla_finding is not None else "info" if status == "CLOSED" else "warning"
    lifecycle = [
        {"status": item.status, "at": item.created_at, "actor": item.owner, "detail": item.title},
    ]
    if sla_finding is not None:
        lifecycle.append({"status": "ESCALATED", "at": generated_at, "actor": "action_sla", "detail": sla_finding.reason})
    if item.closure_note:
        lifecycle.append({"status": "CLOSED", "at": item.updated_at, "actor": item.owner, "detail": item.closure_note})
    return OperationsCompensationTask(
        task_id=_stable_id("OCT", "action_item", item.action_id),
        source_type="action_item",
        source_id=item.action_id,
        status=status,
        owner=item.owner,
        title=item.title,
        severity=severity,
        created_at=item.created_at,
        updated_at=item.updated_at or item.created_at or generated_at,
        due_at=item.eta,
        linked_ticket_id=linked_status.ticket_id if linked_status else _ticket_id_from_texts(item.evidence),
        lifecycle=lifecycle,
        refs={"action_id": item.action_id, "source_type": item.source_type, "source_id": item.source_id},
        payload={"action_item": operations_action_item_to_dict(item), "sla_finding": sla_finding.__dict__ if sla_finding else None},
        closure_note=item.closure_note,
    )


def _merge_compensation_task_overrides(
    derived_tasks: list[OperationsCompensationTask],
    persisted_tasks: list[OperationsCompensationTask],
) -> list[OperationsCompensationTask]:
    by_id = {task.task_id: task for task in derived_tasks}
    for persisted in persisted_tasks:
        existing = by_id.get(persisted.task_id)
        if existing is None:
            by_id[persisted.task_id] = persisted
            continue
        by_id[persisted.task_id] = replace(
            existing,
            status=persisted.status,
            owner=persisted.owner or existing.owner,
            updated_at=persisted.updated_at or existing.updated_at,
            lifecycle=persisted.lifecycle or existing.lifecycle,
            closure_note=persisted.closure_note,
            payload={**existing.payload, "override": operations_compensation_task_to_dict(persisted)},
        )
    return list(by_id.values())


def _status_for_replay_job(
    job: OnCallWebhookReplayJob,
    status_map: dict[str, OnCallTicketStatus],
) -> OnCallTicketStatus | None:
    for result in (job.batch_result.results if job.batch_result is not None else []):
        ticket_id = result.ticket_id
        if ticket_id and ticket_id in status_map:
            return status_map[ticket_id]
    return None


def _ticket_id_from_payload(payload: dict[str, Any]) -> str | None:
    for key in ("ticket_id", "incident_id", "oncall_ticket_id"):
        value = payload.get(key)
        if value:
            return str(value)
    ticket = payload.get("ticket")
    if isinstance(ticket, dict):
        for key in ("ticket_id", "id", "incident_id"):
            if ticket.get(key):
                return str(ticket[key])
    return None


def _ticket_id_from_texts(values: list[str]) -> str | None:
    for value in values:
        for token in value.replace(",", " ").split():
            if token.startswith(("INC-", "TICKET-", "ISSUE-")):
                return token.strip()
    return None


def decide_recovery_strategy(
    context: TravelContext,
    from_state: str,
    reason: str,
    knowledge_refs: list[str] | None = None,
    guidance: list[str] | None = None,
) -> RecoveryStrategyDecision:
    knowledge_refs = knowledge_refs or []
    guidance = guidance or []
    normalized_state = from_state.strip().upper()
    reasons: list[str] = [f"state={normalized_state}", f"reason={reason}"]
    recommended_steps: list[str] = []

    compensation_targets = _recovery_compensation_targets(context, normalized_state)
    failed_compensations = _failed_recovery_compensations(context)
    if knowledge_refs:
        reasons.append(f"knowledge_hits={len(knowledge_refs)}")
    if compensation_targets:
        reasons.append("compensation_targets=" + ",".join(compensation_targets))
    if failed_compensations:
        reasons.append("failed_compensations=" + ",".join(failed_compensations))

    policy_noncompliant = (
        (context.policy_result is not None and not context.policy_result.compliant)
        or (context.transport_policy_result is not None and not context.transport_policy_result.compliant)
    )
    price_requires_confirmation = bool(
        context.price_check is not None
        and (
            context.price_check.requires_confirmation
            or _normalize_status_value(context.price_check.status) == "PRICE_CHANGED"
            or not context.price_check.policy_compliant
        )
    )
    order_failed = any(
        _normalize_status_value(getattr(order, "status", "")) in {"FAILED", "ERROR", "REJECTED"}
        for order in (context.order, context.transport_order)
        if order is not None
    )

    if failed_compensations:
        action = "manual_escalation"
        severity = "critical"
        manual = True
        recommended_steps.append("Open or update an incident ticket before continuing automated recovery.")
    elif order_failed or normalized_state == "ORDER_FAILED":
        action = "compensate_then_replan"
        severity = "critical"
        manual = False
        recommended_steps.append("Complete order, inventory, and approval compensation before resubmitting.")
    elif policy_noncompliant:
        action = "manual_escalation"
        severity = "critical"
        manual = True
        reasons.append("policy_noncompliant=true")
        recommended_steps.append("Route to travel policy owner before rebuilding the plan.")
    elif normalized_state in {"PRICE_CHANGED", "INVENTORY_EXPIRED"} and not compensation_targets:
        action = "retry_status_refresh"
        severity = "warning"
        manual = False
        recommended_steps.append("Refresh supplier price or inventory status before creating a new approval.")
    elif normalized_state == "APPROVAL_REJECTED":
        action = "knowledge_guided_replan" if knowledge_refs else "replan"
        severity = "warning"
        manual = False
        recommended_steps.append("Adjust hotel or transport options and resubmit approval.")
    elif price_requires_confirmation:
        action = "replan"
        severity = "warning"
        manual = False
        reasons.append("price_requires_confirmation=true")
        recommended_steps.append("Rebuild candidate set using current price and policy constraints.")
    else:
        action = "knowledge_guided_replan" if knowledge_refs else "replan"
        severity = "info"
        manual = False
        recommended_steps.append("Rebuild policy, itinerary, hotel, and transport candidates.")

    recommended_steps.extend(guidance)
    return RecoveryStrategyDecision(
        decision_id=_stable_id("RSD", context.session_id, str(context.workflow_generation), normalized_state, reason),
        action=action,
        severity=severity,
        reason="; ".join(_dedupe(reasons)),
        from_state=normalized_state,
        compensation_required=bool(compensation_targets),
        manual_escalation_required=manual,
        knowledge_refs=list(knowledge_refs),
        guidance=list(guidance),
        recommended_next_steps=_dedupe(recommended_steps),
    )


def recovery_strategy_decision_to_dict(decision: RecoveryStrategyDecision) -> dict[str, Any]:
    return {
        "decision_id": decision.decision_id,
        "action": decision.action,
        "severity": decision.severity,
        "reason": decision.reason,
        "from_state": decision.from_state,
        "compensation_required": decision.compensation_required,
        "manual_escalation_required": decision.manual_escalation_required,
        "knowledge_refs": decision.knowledge_refs,
        "guidance": decision.guidance,
        "recommended_next_steps": decision.recommended_next_steps,
    }


def recovery_strategy_decision_from_dict(payload: dict[str, Any]) -> RecoveryStrategyDecision:
    return RecoveryStrategyDecision(
        decision_id=str(payload["decision_id"]),
        action=str(payload["action"]),
        severity=str(payload.get("severity") or "info"),
        reason=str(payload.get("reason") or ""),
        from_state=str(payload.get("from_state") or ""),
        compensation_required=bool(payload.get("compensation_required", False)),
        manual_escalation_required=bool(payload.get("manual_escalation_required", False)),
        knowledge_refs=[str(item) for item in payload.get("knowledge_refs") or []],
        guidance=[str(item) for item in payload.get("guidance") or []],
        recommended_next_steps=[str(item) for item in payload.get("recommended_next_steps") or []],
    )


def render_recovery_strategy_decision(decision: RecoveryStrategyDecision) -> str:
    lines = [
        "Recovery strategy decision:",
        f"- decision_id: {decision.decision_id}",
        f"- action: {decision.action}",
        f"- severity: {decision.severity}",
        f"- from_state: {decision.from_state}",
        f"- compensation_required: {decision.compensation_required}",
        f"- manual_escalation_required: {decision.manual_escalation_required}",
        f"- reason: {decision.reason}",
        "- recommended_next_steps:",
    ]
    if not decision.recommended_next_steps:
        lines.append("  - none")
    else:
        for step in decision.recommended_next_steps:
            lines.append(f"  - {step}")
    return "\n".join(lines)


def evaluate_recovery_strategy_gate(
    decision: RecoveryStrategyDecision,
    approved: bool = False,
    allow_critical_auto: bool = False,
) -> RecoveryStrategyGateResult:
    required: list[str] = []
    blocked: list[str] = []
    reasons: list[str] = []
    if decision.manual_escalation_required:
        required.append("incident_owner_approval")
        blocked.append(decision.action)
        reasons.append("manual escalation is required by the recovery strategy")
    if decision.severity == "critical" and not allow_critical_auto:
        required.append("critical_recovery_approval")
        blocked.append(decision.action)
        reasons.append("critical recovery requires approval before automated continuation")
    if decision.compensation_required and decision.action == "compensate_then_replan" and not allow_critical_auto:
        required.append("compensation_owner_approval")
        reasons.append("compensation path requires owner acknowledgement")
    required = _dedupe(required)
    blocked = _dedupe(blocked)
    if required and not approved:
        status = "APPROVAL_REQUIRED"
        allow = False
        exit_code = 2
    else:
        status = "PASS"
        allow = True
        exit_code = 0
        if not reasons:
            reasons.append("strategy is eligible for automated continuation")
        elif approved:
            reasons.append("required approval has been provided")
    return RecoveryStrategyGateResult(
        decision_id=decision.decision_id,
        status=status,
        allow_automation=allow,
        exit_code=exit_code,
        required_approvals=required,
        blocked_actions=blocked if not allow else [],
        reasons=_dedupe(reasons),
    )


def recovery_strategy_gate_result_to_dict(result: RecoveryStrategyGateResult) -> dict[str, Any]:
    return {
        "decision_id": result.decision_id,
        "status": result.status,
        "allow_automation": result.allow_automation,
        "exit_code": result.exit_code,
        "required_approvals": result.required_approvals,
        "blocked_actions": result.blocked_actions,
        "reasons": result.reasons,
    }


def recovery_strategy_gate_result_from_dict(payload: dict[str, Any]) -> RecoveryStrategyGateResult:
    return RecoveryStrategyGateResult(
        decision_id=str(payload["decision_id"]),
        status=str(payload.get("status") or "PASS"),
        allow_automation=bool(payload.get("allow_automation", True)),
        exit_code=int(payload.get("exit_code") or 0),
        required_approvals=[str(item) for item in payload.get("required_approvals") or []],
        blocked_actions=[str(item) for item in payload.get("blocked_actions") or []],
        reasons=[str(item) for item in payload.get("reasons") or []],
    )


def render_recovery_strategy_gate_result(result: RecoveryStrategyGateResult) -> str:
    lines = [
        "Recovery strategy gate:",
        f"- decision_id: {result.decision_id}",
        f"- status: {result.status}",
        f"- allow_automation: {result.allow_automation}",
        f"- exit_code: {result.exit_code}",
    ]
    _append_list_section(lines, "required_approvals", result.required_approvals)
    _append_list_section(lines, "blocked_actions", result.blocked_actions)
    _append_list_section(lines, "reasons", result.reasons)
    return "\n".join(lines)


def build_recovery_approval_receipt(
    decision_id: str,
    required_approvals: list[str],
    approved_by: str | None = None,
    reason: str | None = None,
    approved_at: str | None = None,
) -> RecoveryApprovalReceipt:
    approved_at = approved_at or datetime.now(timezone.utc).isoformat()
    approved_by = approved_by or "operator"
    reason = reason or "recovery approval override"
    return RecoveryApprovalReceipt(
        receipt_id=_stable_id("RAP", decision_id, approved_by, approved_at, reason),
        decision_id=decision_id,
        approved_by=approved_by,
        approved_at=approved_at,
        reason=reason,
        required_approvals=list(required_approvals),
    )


def recovery_governance_policy_from_dict(payload: dict[str, Any] | None) -> RecoveryGovernancePolicy:
    payload = payload or {}
    max_executions = payload.get("max_executions_per_session")
    return RecoveryGovernancePolicy(
        allowed_actions=[str(item) for item in payload.get("allowed_actions") or []],
        blocked_actions=[str(item) for item in payload.get("blocked_actions") or []],
        max_executions_per_session=int(max_executions) if max_executions is not None else None,
    )


def recovery_governance_policy_from_json(value: str | None) -> RecoveryGovernancePolicy:
    if not value:
        return RecoveryGovernancePolicy()
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError("Recovery governance policy JSON requires an object.")
    return recovery_governance_policy_from_dict(parsed)


def recovery_governance_policy_to_dict(policy: RecoveryGovernancePolicy) -> dict[str, Any]:
    return {
        "allowed_actions": policy.allowed_actions,
        "blocked_actions": policy.blocked_actions,
        "max_executions_per_session": policy.max_executions_per_session,
    }


def fetch_recovery_governance_policy_http(
    endpoint: str,
    token: str | None = None,
    http_client: Any | None = None,
    fallback_policy: RecoveryGovernancePolicy | None = None,
) -> RecoveryGovernancePolicyFetchResult:
    from .integrations import JsonHttpClient

    fetched_at = datetime.now(timezone.utc).isoformat()
    fallback_policy = fallback_policy or RecoveryGovernancePolicy()
    try:
        client = http_client or JsonHttpClient()
        response = client.post_json(endpoint, {"source": "travel-agent", "kind": "recovery_governance_policy"}, token)
        payload = response.get("policy") or response.get("data") or response
        if not isinstance(payload, dict):
            raise ValueError("Recovery governance policy endpoint returned a non-object payload.")
        policy = recovery_governance_policy_from_dict(payload)
    except Exception as exc:
        return RecoveryGovernancePolicyFetchResult(
            ok=False,
            endpoint=endpoint,
            policy=fallback_policy,
            source="fallback",
            detail=str(exc),
            fetched_at=fetched_at,
        )
    return RecoveryGovernancePolicyFetchResult(
        ok=True,
        endpoint=endpoint,
        policy=policy,
        source=str(response.get("source") or "remote-config"),
        detail=str(response.get("detail") or "recovery governance policy fetched"),
        fetched_at=fetched_at,
    )


def recovery_governance_policy_fetch_result_to_dict(result: RecoveryGovernancePolicyFetchResult) -> dict[str, Any]:
    return {
        "ok": result.ok,
        "endpoint": result.endpoint,
        "policy": recovery_governance_policy_to_dict(result.policy),
        "source": result.source,
        "detail": result.detail,
        "fetched_at": result.fetched_at,
    }


def render_recovery_governance_policy_fetch_result(result: RecoveryGovernancePolicyFetchResult) -> str:
    return "\n".join(
        [
            "Recovery governance policy fetch:",
            f"- ok: {result.ok}",
            f"- endpoint: {result.endpoint}",
            f"- source: {result.source}",
            f"- fetched_at: {result.fetched_at}",
            f"- detail: {result.detail}",
            f"- allowed_actions: {', '.join(result.policy.allowed_actions) or '-'}",
            f"- blocked_actions: {', '.join(result.policy.blocked_actions) or '-'}",
            f"- max_executions_per_session: {result.policy.max_executions_per_session}",
        ]
    )


def build_recovery_governance_policy_audit(
    previous: RecoveryGovernancePolicy,
    current: RecoveryGovernancePolicy,
    changed_by: str,
    changed_at: str | None = None,
) -> RecoveryGovernancePolicyAudit:
    changed_at = changed_at or datetime.now(timezone.utc).isoformat()
    before = recovery_governance_policy_to_dict(previous)
    after = recovery_governance_policy_to_dict(current)
    changes = [
        f"{key}: {before.get(key)!r} -> {after.get(key)!r}"
        for key in sorted(set(before) | set(after))
        if before.get(key) != after.get(key)
    ]
    if not changes:
        changes.append("no policy changes")
    return RecoveryGovernancePolicyAudit(
        audit_id=_stable_id("RGA", changed_by, changed_at, json.dumps(after, sort_keys=True)),
        changed_by=changed_by,
        changed_at=changed_at,
        before=before,
        after=after,
        changes=changes,
    )


def recovery_governance_policy_audit_to_dict(audit: RecoveryGovernancePolicyAudit) -> dict[str, Any]:
    return {
        "audit_id": audit.audit_id,
        "changed_by": audit.changed_by,
        "changed_at": audit.changed_at,
        "before": audit.before,
        "after": audit.after,
        "changes": audit.changes,
    }


def render_recovery_governance_policy_audit(audit: RecoveryGovernancePolicyAudit) -> str:
    lines = [
        "Recovery governance policy audit:",
        f"- audit_id: {audit.audit_id}",
        f"- changed_by: {audit.changed_by}",
        f"- changed_at: {audit.changed_at}",
    ]
    _append_list_section(lines, "changes", audit.changes)
    return "\n".join(lines)


def build_operations_governance_policy_change(
    previous: RecoveryGovernancePolicy,
    current: RecoveryGovernancePolicy,
    requested_by: str,
    requested_at: str | None = None,
    policy_type: str = "recovery_governance",
    reason: str | None = None,
) -> OperationsGovernancePolicyChange:
    requested_at = requested_at or datetime.now(timezone.utc).isoformat()
    before = recovery_governance_policy_to_dict(previous)
    after = recovery_governance_policy_to_dict(current)
    changes = _dict_changes(before, after)
    return OperationsGovernancePolicyChange(
        change_id=_stable_id(
            "OGP",
            policy_type,
            requested_by,
            requested_at,
            json.dumps(before, sort_keys=True),
            json.dumps(after, sort_keys=True),
        ),
        status="PENDING_APPROVAL",
        policy_type=policy_type,
        requested_by=requested_by,
        requested_at=requested_at,
        before=before,
        after=after,
        changes=changes,
        approvals=[],
        reason=reason,
    )


def approve_operations_governance_policy_change(
    change: OperationsGovernancePolicyChange,
    approver: str,
) -> OperationsGovernancePolicyChange:
    approvals = list(change.approvals)
    if approver and approver not in approvals:
        approvals.append(approver)
    status = "APPROVED" if len({item for item in approvals if item and item != change.requested_by}) >= 1 else change.status
    return replace(change, status=status, approvals=approvals)


def apply_operations_governance_policy_change(
    change: OperationsGovernancePolicyChange,
    applied_at: str | None = None,
) -> OperationsGovernancePolicyChange:
    applied_at = applied_at or datetime.now(timezone.utc).isoformat()
    return replace(change, status="APPLIED", applied_at=applied_at)


def rollback_operations_governance_policy_change(
    change: OperationsGovernancePolicyChange,
    requested_by: str,
    requested_at: str | None = None,
    reason: str | None = None,
) -> OperationsGovernancePolicyChange:
    requested_at = requested_at or datetime.now(timezone.utc).isoformat()
    rollback = OperationsGovernancePolicyChange(
        change_id=_stable_id("OGR", change.change_id, requested_by, requested_at),
        status="ROLLED_BACK",
        policy_type=change.policy_type,
        requested_by=requested_by,
        requested_at=requested_at,
        before=dict(change.after),
        after=dict(change.before),
        changes=_dict_changes(change.after, change.before),
        approvals=[requested_by] if requested_by else [],
        rolled_back_at=requested_at,
        reason=reason or f"rollback {change.change_id}",
    )
    return rollback


def operations_governance_policy_change_to_dict(change: OperationsGovernancePolicyChange) -> dict[str, Any]:
    return {
        "change_id": change.change_id,
        "status": change.status,
        "policy_type": change.policy_type,
        "requested_by": change.requested_by,
        "requested_at": change.requested_at,
        "before": change.before,
        "after": change.after,
        "changes": change.changes,
        "approvals": change.approvals,
        "applied_at": change.applied_at,
        "rolled_back_at": change.rolled_back_at,
        "reason": change.reason,
    }


def operations_governance_policy_change_from_dict(payload: dict[str, Any]) -> OperationsGovernancePolicyChange:
    return OperationsGovernancePolicyChange(
        change_id=str(payload["change_id"]),
        status=str(payload.get("status") or "PENDING_APPROVAL"),
        policy_type=str(payload.get("policy_type") or "recovery_governance"),
        requested_by=str(payload.get("requested_by") or "operator"),
        requested_at=str(payload.get("requested_at") or ""),
        before=dict(payload.get("before") or {}),
        after=dict(payload.get("after") or {}),
        changes=[str(item) for item in payload.get("changes") or []],
        approvals=[str(item) for item in payload.get("approvals") or []],
        applied_at=str(payload["applied_at"]) if payload.get("applied_at") is not None else None,
        rolled_back_at=str(payload["rolled_back_at"]) if payload.get("rolled_back_at") is not None else None,
        reason=str(payload["reason"]) if payload.get("reason") is not None else None,
    )


def render_operations_governance_policy_changes(changes: list[OperationsGovernancePolicyChange]) -> str:
    lines = ["Operations governance policy changes:"]
    if not changes:
        lines.append("- none")
        return "\n".join(lines)
    for change in changes:
        lines.append(
            f"- {change.change_id}: status={change.status} type={change.policy_type} "
            f"requested_by={change.requested_by} approvals={','.join(change.approvals) or '-'}"
        )
        for item in change.changes:
            lines.append(f"  - {item}")
    return "\n".join(lines)


def build_operations_console_action_audit(
    action: str,
    actor: str,
    roles: list[str] | set[str] | tuple[str, ...] | None,
    department: str | None,
    authorization: dict[str, Any],
    request_payload: dict[str, Any],
    result_body: dict[str, Any],
    requested_at: str | None = None,
    completed_at: str | None = None,
) -> OperationsConsoleActionAudit:
    requested_at = requested_at or datetime.now(timezone.utc).isoformat()
    completed_at = completed_at or datetime.now(timezone.utc).isoformat()
    status = "SUCCESS" if bool(result_body.get("ok")) else "FAILED"
    if authorization and not bool(authorization.get("allowed", True)):
        status = "DENIED"
    request_summary = _summarize_operations_console_action_request(request_payload)
    result_summary = _summarize_operations_console_action_result(result_body)
    return OperationsConsoleActionAudit(
        audit_id=_stable_id("OCA", action, actor, requested_at, completed_at, json.dumps(result_summary, sort_keys=True)),
        action=action,
        actor=actor,
        roles=sorted({str(role) for role in roles or [] if str(role).strip()}),
        department=department,
        status=status,
        requested_at=requested_at,
        completed_at=completed_at,
        authorization=dict(authorization or {}),
        request_summary=request_summary,
        result_summary=result_summary,
    )


def operations_console_action_audit_to_dict(audit: OperationsConsoleActionAudit) -> dict[str, Any]:
    return {
        "audit_id": audit.audit_id,
        "action": audit.action,
        "actor": audit.actor,
        "roles": audit.roles,
        "department": audit.department,
        "status": audit.status,
        "requested_at": audit.requested_at,
        "completed_at": audit.completed_at,
        "authorization": audit.authorization,
        "request_summary": audit.request_summary,
        "result_summary": audit.result_summary,
    }


def operations_console_action_audit_from_dict(payload: dict[str, Any]) -> OperationsConsoleActionAudit:
    return OperationsConsoleActionAudit(
        audit_id=str(payload["audit_id"]),
        action=str(payload.get("action") or ""),
        actor=str(payload.get("actor") or ""),
        roles=[str(item) for item in payload.get("roles") or []],
        department=str(payload["department"]) if payload.get("department") is not None else None,
        status=str(payload.get("status") or "UNKNOWN"),
        requested_at=str(payload.get("requested_at") or ""),
        completed_at=str(payload.get("completed_at") or ""),
        authorization=dict(payload.get("authorization") or {}),
        request_summary=dict(payload.get("request_summary") or {}),
        result_summary=dict(payload.get("result_summary") or {}),
    )


def render_operations_console_action_audits(audits: list[OperationsConsoleActionAudit]) -> str:
    lines = ["Operations console action audits:"]
    if not audits:
        lines.append("- none")
        return "\n".join(lines)
    for audit in audits:
        lines.append(
            f"- {audit.audit_id}: action={audit.action} actor={audit.actor} "
            f"status={audit.status} completed_at={audit.completed_at}"
        )
    return "\n".join(lines)


def build_operations_audit_sink_delivery(
    audit: OperationsConsoleActionAudit,
    result: AuditSinkResult,
    attempted_at: str | None = None,
    previous: OperationsAuditSinkDelivery | None = None,
) -> OperationsAuditSinkDelivery:
    attempted_at = attempted_at or datetime.now(timezone.utc).isoformat()
    attempts = (previous.attempts + 1) if previous is not None else 1
    status = "DELIVERED" if result.ok and result.failed == 0 else "FAILED"
    event = build_operations_console_action_audit_event(audit)
    return OperationsAuditSinkDelivery(
        delivery_id=_stable_id("OASD", audit.audit_id, event.event_type),
        audit_id=audit.audit_id,
        event_type=event.event_type,
        status=status,
        attempted_at=attempted_at,
        delivered=result.delivered,
        failed=result.failed,
        detail=result.detail,
        attempts=attempts,
        last_error=None if status == "DELIVERED" else result.detail,
        payload={
            "event": {
                "event_type": event.event_type,
                "detail": event.detail,
                "redacted_keys": event.redacted_keys,
                "payload": event.redacted_payload,
            },
            "result": {
                "ok": result.ok,
                "delivered": result.delivered,
                "failed": result.failed,
                "detail": result.detail,
            },
        },
    )


def build_operations_console_action_audit_event(audit: OperationsConsoleActionAudit) -> Any:
    return build_audit_event(
        f"operations.console_action.{audit.action}",
        {
            "audit_id": audit.audit_id,
            "action": audit.action,
            "actor": audit.actor,
            "roles": audit.roles,
            "department": audit.department,
            "status": audit.status,
            "requested_at": audit.requested_at,
            "completed_at": audit.completed_at,
            "authorization": audit.authorization,
            "request_summary": audit.request_summary,
            "result_summary": audit.result_summary,
        },
    )


def operations_audit_sink_delivery_to_dict(delivery: OperationsAuditSinkDelivery) -> dict[str, Any]:
    return {
        "delivery_id": delivery.delivery_id,
        "audit_id": delivery.audit_id,
        "event_type": delivery.event_type,
        "status": delivery.status,
        "attempted_at": delivery.attempted_at,
        "delivered": delivery.delivered,
        "failed": delivery.failed,
        "detail": delivery.detail,
        "attempts": delivery.attempts,
        "last_error": delivery.last_error,
        "payload": delivery.payload,
    }


def operations_audit_sink_delivery_from_dict(payload: dict[str, Any]) -> OperationsAuditSinkDelivery:
    return OperationsAuditSinkDelivery(
        delivery_id=str(payload["delivery_id"]),
        audit_id=str(payload.get("audit_id") or ""),
        event_type=str(payload.get("event_type") or ""),
        status=str(payload.get("status") or "UNKNOWN"),
        attempted_at=str(payload.get("attempted_at") or ""),
        delivered=int(payload.get("delivered") or 0),
        failed=int(payload.get("failed") or 0),
        detail=str(payload.get("detail") or ""),
        attempts=int(payload.get("attempts") or 1),
        last_error=str(payload["last_error"]) if payload.get("last_error") is not None else None,
        payload=dict(payload.get("payload") or {}),
    )


def retry_operations_audit_sink_deliveries(
    audits: list[OperationsConsoleActionAudit],
    deliveries: list[OperationsAuditSinkDelivery],
    audit_sink: AuditSink,
    limit: int = 20,
    now: str | None = None,
    status: str = "FAILED",
) -> OperationsAuditSinkReplayReport:
    generated_at = now or datetime.now(timezone.utc).isoformat()
    audits_by_id = {audit.audit_id: audit for audit in audits}
    candidates = [delivery for delivery in deliveries if delivery.status == status and delivery.audit_id in audits_by_id]
    selected = candidates[: max(0, limit)]
    updated: list[OperationsAuditSinkDelivery] = []
    delivered_count = 0
    failed_count = 0
    for delivery in selected:
        audit = audits_by_id[delivery.audit_id]
        result = audit_sink.write([build_operations_console_action_audit_event(audit)])
        next_delivery = build_operations_audit_sink_delivery(
            audit,
            result,
            attempted_at=generated_at,
            previous=delivery,
        )
        updated.append(next_delivery)
        delivered_count += next_delivery.delivered
        failed_count += next_delivery.failed
    summary = f"audit_sink_replay attempted={len(updated)} delivered={delivered_count} failed={failed_count}"
    return OperationsAuditSinkReplayReport(
        generated_at=generated_at,
        attempted=len(updated),
        delivered=delivered_count,
        failed=failed_count,
        deliveries=updated,
        summary=summary,
    )


def operations_audit_sink_replay_report_to_dict(report: OperationsAuditSinkReplayReport) -> dict[str, Any]:
    return {
        "generated_at": report.generated_at,
        "attempted": report.attempted,
        "delivered": report.delivered,
        "failed": report.failed,
        "deliveries": [operations_audit_sink_delivery_to_dict(item) for item in report.deliveries],
        "summary": report.summary,
    }


def render_operations_audit_sink_deliveries(deliveries: list[OperationsAuditSinkDelivery]) -> str:
    lines = ["Operations audit sink deliveries:"]
    if not deliveries:
        lines.append("- none")
        return "\n".join(lines)
    for delivery in deliveries:
        lines.append(
            f"- {delivery.delivery_id}: audit_id={delivery.audit_id} status={delivery.status} "
            f"attempts={delivery.attempts} delivered={delivery.delivered} failed={delivery.failed}"
        )
    return "\n".join(lines)


def render_operations_audit_sink_deliveries_json(deliveries: list[OperationsAuditSinkDelivery]) -> str:
    return json.dumps(
        {"operations_audit_sink_deliveries": [operations_audit_sink_delivery_to_dict(item) for item in deliveries]},
        ensure_ascii=False,
    )


def render_operations_audit_sink_replay_report_json(report: OperationsAuditSinkReplayReport) -> str:
    return json.dumps({"operations_audit_sink_replay": operations_audit_sink_replay_report_to_dict(report)}, ensure_ascii=False)


def build_operations_audit_timeline(
    action_audits: list[OperationsConsoleActionAudit] | None = None,
    governance_changes: list[OperationsGovernancePolicyChange] | None = None,
    replay_jobs: list[OnCallWebhookReplayJob] | None = None,
    scheduler_runs: list[OperationsSchedulerRunReport] | None = None,
    limit: int = 20,
    event_type: str | None = None,
    actor: str | None = None,
    action: str | None = None,
    status: str | None = None,
    generated_at: str | None = None,
) -> OperationsAuditTimeline:
    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    filters = {
        key: value
        for key, value in {
            "event_type": event_type,
            "actor": actor,
            "action": action,
            "status": status,
        }.items()
        if value
    }
    events: list[OperationsAuditTimelineEvent] = []
    for audit in action_audits or []:
        events.append(_timeline_event_from_console_action_audit(audit))
    for change in governance_changes or []:
        events.append(_timeline_event_from_governance_change(change))
    for job in replay_jobs or []:
        events.append(_timeline_event_from_replay_job(job))
    for run in scheduler_runs or []:
        events.append(_timeline_event_from_scheduler_run(run))
    filtered = [
        item
        for item in events
        if _timeline_event_matches(item, event_type=event_type, actor=actor, action=action, status=status)
    ]
    filtered.sort(key=lambda item: (_timestamp_sort_key(item.occurred_at), item.event_id), reverse=True)
    limited = filtered[: max(0, limit)]
    summary = f"audit_timeline_events={len(limited)}/{len(filtered)} total={len(events)}"
    return OperationsAuditTimeline(
        generated_at=generated_at,
        events=limited,
        filters=filters,
        total_events=len(filtered),
        summary=summary,
    )


def operations_audit_timeline_event_to_dict(event: OperationsAuditTimelineEvent) -> dict[str, Any]:
    return {
        "event_id": event.event_id,
        "event_type": event.event_type,
        "occurred_at": event.occurred_at,
        "actor": event.actor,
        "action": event.action,
        "status": event.status,
        "summary": event.summary,
        "refs": event.refs,
        "payload": event.payload,
    }


def operations_audit_timeline_to_dict(timeline: OperationsAuditTimeline) -> dict[str, Any]:
    return {
        "generated_at": timeline.generated_at,
        "events": [operations_audit_timeline_event_to_dict(event) for event in timeline.events],
        "filters": timeline.filters,
        "total_events": timeline.total_events,
        "summary": timeline.summary,
    }


def render_operations_audit_timeline_json(timeline: OperationsAuditTimeline) -> str:
    return json.dumps({"operations_audit_timeline": operations_audit_timeline_to_dict(timeline)}, ensure_ascii=False)


def render_operations_audit_timeline(timeline: OperationsAuditTimeline) -> str:
    lines = [
        "Operations audit timeline:",
        f"- generated_at: {timeline.generated_at}",
        f"- total_events: {timeline.total_events}",
        f"- summary: {timeline.summary}",
    ]
    if timeline.filters:
        lines.append(f"- filters: {timeline.filters}")
    if not timeline.events:
        lines.append("- events: none")
        return "\n".join(lines)
    lines.append("- events:")
    for event in timeline.events:
        lines.append(
            f"  - {event.occurred_at} {event.event_type} status={event.status} "
            f"actor={event.actor or '-'} action={event.action or '-'}"
        )
        lines.append(f"    {event.summary}")
    return "\n".join(lines)


def _timeline_event_from_console_action_audit(audit: OperationsConsoleActionAudit) -> OperationsAuditTimelineEvent:
    result = audit.result_summary
    return OperationsAuditTimelineEvent(
        event_id=audit.audit_id,
        event_type="console_action",
        occurred_at=audit.completed_at,
        actor=audit.actor,
        action=audit.action,
        status=audit.status,
        summary=f"{audit.action} {audit.status.lower()}",
        refs={
            "audit_id": audit.audit_id,
            "change_id": result.get("change_id"),
            "job_id": result.get("job_id"),
            "scheduler_run_id": result.get("scheduler_run_id"),
        },
        payload={
            "request_summary": audit.request_summary,
            "result_summary": audit.result_summary,
            "authorization": audit.authorization,
        },
    )


def _timeline_event_from_governance_change(change: OperationsGovernancePolicyChange) -> OperationsAuditTimelineEvent:
    return OperationsAuditTimelineEvent(
        event_id=change.change_id,
        event_type="governance_policy_change",
        occurred_at=change.applied_at or change.rolled_back_at or change.requested_at,
        actor=change.requested_by,
        action="update_governance_policy",
        status=change.status,
        summary=f"{change.policy_type} {change.status.lower()} with {len(change.changes)} change(s)",
        refs={"change_id": change.change_id},
        payload=operations_governance_policy_change_to_dict(change),
    )


def _timeline_event_from_replay_job(job: OnCallWebhookReplayJob) -> OperationsAuditTimelineEvent:
    return OperationsAuditTimelineEvent(
        event_id=job.job_id,
        event_type="replay_job",
        occurred_at=str(job.audit.get("executed_at") or job.created_at),
        actor=job.requested_by,
        action="execute_replay_job" if job.batch_result is not None else "create_replay_job",
        status=job.status,
        summary=f"replay job {job.status.lower()} for {len(job.event_ids)} event(s)",
        refs={"job_id": job.job_id, "event_ids": job.event_ids},
        payload=oncall_webhook_replay_job_to_dict(job),
    )


def _timeline_event_from_scheduler_run(run: OperationsSchedulerRunReport) -> OperationsAuditTimelineEvent:
    return OperationsAuditTimelineEvent(
        event_id=run.run_id,
        event_type="scheduler_run",
        occurred_at=run.finished_at or run.started_at,
        actor=None,
        action="run_operations_schedule",
        status="FAILED" if run.failed_count else "SUCCESS",
        summary=run.summary,
        refs={"run_id": run.run_id},
        payload=operations_scheduler_run_report_to_dict(run),
    )


def _timeline_event_matches(
    event: OperationsAuditTimelineEvent,
    event_type: str | None = None,
    actor: str | None = None,
    action: str | None = None,
    status: str | None = None,
) -> bool:
    if event_type and event.event_type != event_type:
        return False
    if actor and event.actor != actor:
        return False
    if action and event.action != action:
        return False
    if status and event.status != status:
        return False
    return True


def _summarize_operations_console_action_request(payload: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key in (
        "action",
        "limit",
        "requested_by",
        "patch_template_id",
        "persisted",
        "owner",
        "endpoint",
        "server_url",
        "change_id",
        "approved_by",
        "reason",
    ):
        if key in payload:
            summary[key] = payload.get(key)
    for key in ("before", "after", "policy", "proposed_policy", "patch", "patches", "token"):
        if key in payload:
            value = payload.get(key)
            summary[key] = {
                "present": True,
                "type": type(value).__name__,
                "keys": sorted(str(item) for item in value) if isinstance(value, dict) else None,
            }
    return summary


def _summarize_operations_console_action_result(body: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "ok": bool(body.get("ok")),
        "action": body.get("action"),
    }
    if body.get("error") is not None:
        summary["error"] = body.get("error")
    if isinstance(body.get("job"), dict):
        summary["job_id"] = body["job"].get("job_id")
        summary["job_status"] = body["job"].get("status")
    if isinstance(body.get("executions"), list):
        summary["execution_count"] = len(body["executions"])
    if isinstance(body.get("scheduler_run"), dict):
        summary["scheduler_run_id"] = body["scheduler_run"].get("run_id")
        summary["scheduler_failed_count"] = body["scheduler_run"].get("failed_count")
    if isinstance(body.get("publish_result"), dict):
        summary["publish_endpoint"] = body["publish_result"].get("endpoint")
        summary["publish_failed"] = body["publish_result"].get("failed")
    if isinstance(body.get("change"), dict):
        summary["change_id"] = body["change"].get("change_id")
        summary["change_status"] = body["change"].get("status")
    return summary


def _dict_changes(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    changes = [
        f"{key}: {before.get(key)!r} -> {after.get(key)!r}"
        for key in sorted(set(before) | set(after))
        if before.get(key) != after.get(key)
    ]
    return changes or ["no policy changes"]


def evaluate_recovery_governance_policy(
    decision: RecoveryStrategyDecision,
    context: TravelContext,
    policy: RecoveryGovernancePolicy | None = None,
) -> RecoveryGovernanceDecision:
    policy = policy or RecoveryGovernancePolicy()
    reasons: list[str] = []
    allowed_actions = set(policy.allowed_actions)
    blocked_actions = set(policy.blocked_actions)
    executed_count = _recovery_strategy_execution_count(context)
    if allowed_actions and decision.action not in allowed_actions:
        reasons.append(f"action {decision.action} is not in the recovery allowlist")
    if decision.action in blocked_actions:
        reasons.append(f"action {decision.action} is blocked by recovery governance policy")
    if policy.max_executions_per_session is not None and executed_count >= policy.max_executions_per_session:
        reasons.append(
            f"recovery execution limit reached: {executed_count}/{policy.max_executions_per_session}"
        )
    allow = not reasons
    if allow:
        reasons.append("recovery governance policy passed")
    return RecoveryGovernanceDecision(
        decision_id=decision.decision_id,
        action=decision.action,
        status="PASS" if allow else "BLOCKED",
        allow_automation=allow,
        reasons=_dedupe(reasons),
    )


def recovery_governance_decision_to_dict(decision: RecoveryGovernanceDecision) -> dict[str, Any]:
    return {
        "decision_id": decision.decision_id,
        "action": decision.action,
        "status": decision.status,
        "allow_automation": decision.allow_automation,
        "reasons": decision.reasons,
    }


def recovery_governance_decision_from_dict(payload: dict[str, Any]) -> RecoveryGovernanceDecision:
    return RecoveryGovernanceDecision(
        decision_id=str(payload["decision_id"]),
        action=str(payload.get("action") or ""),
        status=str(payload.get("status") or "UNKNOWN"),
        allow_automation=bool(payload.get("allow_automation", False)),
        reasons=[str(item) for item in payload.get("reasons") or []],
    )


def render_recovery_governance_decision(decision: RecoveryGovernanceDecision) -> str:
    lines = [
        "Recovery governance decision:",
        f"- decision_id: {decision.decision_id}",
        f"- action: {decision.action}",
        f"- status: {decision.status}",
        f"- allow_automation: {decision.allow_automation}",
    ]
    _append_list_section(lines, "reasons", decision.reasons)
    return "\n".join(lines)


def export_recovery_approval_receipt_http(
    receipt: RecoveryApprovalReceipt | dict[str, Any],
    endpoint: str,
    token: str | None = None,
    http_client: Any | None = None,
) -> RecoveryApprovalExportResult:
    from .integrations import JsonHttpClient

    receipt_payload = (
        recovery_approval_receipt_to_dict(receipt)
        if isinstance(receipt, RecoveryApprovalReceipt)
        else dict(receipt)
    )
    payload = {"source": "travel-agent", "approval_receipt": receipt_payload}
    try:
        client = http_client or JsonHttpClient()
        response = client.post_json(endpoint, payload, token)
    except Exception as exc:
        return RecoveryApprovalExportResult(
            ok=False,
            endpoint=endpoint,
            delivered=0,
            failed=1,
            detail=str(exc),
        )
    delivered = int(response.get("accepted") or response.get("delivered") or 1)
    failed = 0 if delivered > 0 else 1
    return RecoveryApprovalExportResult(
        ok=bool(response.get("ok", failed == 0)),
        endpoint=endpoint,
        delivered=delivered,
        failed=failed,
        detail=str(response.get("detail") or "recovery approval receipt exported"),
    )


def render_recovery_approval_export_result(result: RecoveryApprovalExportResult) -> str:
    return "\n".join(
        [
            "Recovery approval export:",
            f"- ok: {result.ok}",
            f"- endpoint: {result.endpoint}",
            f"- delivered: {result.delivered}",
            f"- failed: {result.failed}",
            f"- detail: {result.detail}",
        ]
    )


def recovery_approval_receipt_to_dict(receipt: RecoveryApprovalReceipt) -> dict[str, Any]:
    return {
        "receipt_id": receipt.receipt_id,
        "decision_id": receipt.decision_id,
        "approved_by": receipt.approved_by,
        "approved_at": receipt.approved_at,
        "reason": receipt.reason,
        "required_approvals": receipt.required_approvals,
    }


def recovery_approval_receipt_from_dict(payload: dict[str, Any]) -> RecoveryApprovalReceipt:
    return RecoveryApprovalReceipt(
        receipt_id=str(payload["receipt_id"]),
        decision_id=str(payload["decision_id"]),
        approved_by=str(payload.get("approved_by") or "operator"),
        approved_at=str(payload.get("approved_at") or ""),
        reason=str(payload.get("reason") or ""),
        required_approvals=[str(item) for item in payload.get("required_approvals") or []],
    )


def collect_recovery_approval_receipts(sessions: list[TravelContext]) -> list[RecoveryApprovalReceipt]:
    receipts: list[RecoveryApprovalReceipt] = []
    seen: set[str] = set()
    for context in sessions:
        for record in context.recovery_records:
            execution = record.payload.get("strategy_execution") if isinstance(record.payload, dict) else None
            if not isinstance(execution, dict):
                continue
            receipt_payload = execution.get("approval_receipt")
            if not isinstance(receipt_payload, dict):
                continue
            receipt = recovery_approval_receipt_from_dict(receipt_payload)
            if receipt.receipt_id in seen:
                continue
            seen.add(receipt.receipt_id)
            receipts.append(receipt)
    return receipts


def build_recovery_approval_sla_policy(policy_json: str | None = None) -> RecoveryApprovalSlaPolicy:
    if not policy_json:
        return RecoveryApprovalSlaPolicy()
    parsed = json.loads(policy_json)
    if not isinstance(parsed, dict):
        raise ValueError("Recovery approval SLA policy JSON requires an object.")
    return RecoveryApprovalSlaPolicy(
        max_pending_hours=float(parsed.get("max_pending_hours") or 24.0),
        allowed_approvers=[str(item) for item in parsed.get("allowed_approvers") or []],
        approver_prefixes=[str(item) for item in parsed.get("approver_prefixes") or []],
        required_approval_types=[str(item) for item in parsed.get("required_approval_types") or []],
    )


def validate_recovery_approver(
    receipt: RecoveryApprovalReceipt,
    policy: RecoveryApprovalSlaPolicy | None = None,
) -> tuple[bool, list[str]]:
    policy = policy or RecoveryApprovalSlaPolicy()
    reasons: list[str] = []
    if policy.allowed_approvers and receipt.approved_by not in policy.allowed_approvers:
        reasons.append(f"approver {receipt.approved_by} is not in allowed approvers")
    if policy.approver_prefixes and not any(
        receipt.approved_by.startswith(prefix) for prefix in policy.approver_prefixes
    ):
        reasons.append(f"approver {receipt.approved_by} does not match required prefixes")
    missing_types = [
        required
        for required in policy.required_approval_types
        if required not in set(receipt.required_approvals)
    ]
    for required in missing_types:
        reasons.append(f"required approval type missing: {required}")
    return not reasons, reasons or ["approver permission passed"]


def evaluate_recovery_approval_sla(
    sessions: list[TravelContext],
    policy: RecoveryApprovalSlaPolicy | None = None,
    now: str | None = None,
) -> RecoveryApprovalSlaReport:
    policy = policy or RecoveryApprovalSlaPolicy()
    now = now or datetime.now(timezone.utc).isoformat()
    now_dt = _parse_iso_datetime(now)
    receipts = collect_recovery_approval_receipts(sessions)
    findings: list[RecoveryApprovalSlaFinding] = []
    for receipt in receipts:
        approved_at = _parse_iso_datetime(receipt.approved_at)
        age_hours = max(0.0, (now_dt - approved_at).total_seconds() / 3600.0)
        approver_ok, approver_reasons = validate_recovery_approver(receipt, policy)
        if age_hours > policy.max_pending_hours:
            findings.append(
                RecoveryApprovalSlaFinding(
                    decision_id=receipt.decision_id,
                    severity="critical",
                    age_hours=round(age_hours, 2),
                    reason=f"approval receipt age exceeds {policy.max_pending_hours:g}h",
                    required_approvals=list(receipt.required_approvals),
                    approved_by=receipt.approved_by,
                )
            )
        if not approver_ok:
            findings.append(
                RecoveryApprovalSlaFinding(
                    decision_id=receipt.decision_id,
                    severity="critical",
                    age_hours=round(age_hours, 2),
                    reason="; ".join(approver_reasons),
                    required_approvals=list(receipt.required_approvals),
                    approved_by=receipt.approved_by,
                )
            )
    summary = (
        "Recovery approval SLA passed."
        if not findings
        else f"Recovery approval SLA found {len(findings)} issue(s)."
    )
    return RecoveryApprovalSlaReport(
        now=now,
        checked_receipts=len(receipts),
        findings=findings,
        summary=summary,
    )


def recovery_approval_sla_finding_to_dict(finding: RecoveryApprovalSlaFinding) -> dict[str, Any]:
    return {
        "decision_id": finding.decision_id,
        "severity": finding.severity,
        "age_hours": finding.age_hours,
        "reason": finding.reason,
        "required_approvals": finding.required_approvals,
        "approved_by": finding.approved_by,
    }


def recovery_approval_sla_report_to_dict(report: RecoveryApprovalSlaReport) -> dict[str, Any]:
    return {
        "now": report.now,
        "checked_receipts": report.checked_receipts,
        "findings": [recovery_approval_sla_finding_to_dict(item) for item in report.findings],
        "summary": report.summary,
    }


def render_recovery_approval_sla_report(report: RecoveryApprovalSlaReport) -> str:
    lines = [
        "Recovery approval SLA:",
        f"- now: {report.now}",
        f"- checked_receipts: {report.checked_receipts}",
        f"- findings: {len(report.findings)}",
        f"- summary: {report.summary}",
    ]
    if report.findings:
        lines.append("- details:")
        for finding in report.findings:
            lines.append(
                f"  - {finding.decision_id}: severity={finding.severity} "
                f"age_hours={finding.age_hours:.2f} approver={finding.approved_by or '-'} "
                f"reason={finding.reason}"
            )
    return "\n".join(lines)


def open_recovery_failure_ticket_http(
    context: TravelContext,
    execution: RecoveryStrategyExecutionResult | dict[str, Any],
    endpoint: str,
    token: str | None = None,
    http_client: Any | None = None,
) -> OnCallTicketResult:
    from .integrations import JsonHttpClient

    execution_payload = (
        recovery_strategy_execution_result_to_dict(execution)
        if isinstance(execution, RecoveryStrategyExecutionResult)
        else dict(execution)
    )
    payload = {
        "source": "travel-agent",
        "summary": "Travel Agent recovery failure",
        "session_id": context.session_id,
        "state": context.state,
        "workflow_generation": context.workflow_generation,
        "user_id": context.request.user_id,
        "department": context.request.department,
        "recovery_execution": execution_payload,
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
        detail=str(response.get("detail") or "recovery failure ticket opened"),
    )


def recovery_strategy_execution_result_to_dict(result: RecoveryStrategyExecutionResult) -> dict[str, Any]:
    return {
        "execution_id": result.execution_id,
        "decision_id": result.decision_id,
        "action": result.action,
        "status": result.status,
        "from_state": result.from_state,
        "to_state": result.to_state,
        "gate_status": result.gate_status,
        "approval_override": result.approval_override,
        "executed_steps": result.executed_steps,
        "skipped_steps": result.skipped_steps,
        "detail": result.detail,
        "created_at": result.created_at,
        "idempotency_key": result.idempotency_key,
        "approval_receipt": result.approval_receipt,
    }


def recovery_strategy_execution_result_from_dict(payload: dict[str, Any]) -> RecoveryStrategyExecutionResult:
    return RecoveryStrategyExecutionResult(
        execution_id=str(payload["execution_id"]),
        decision_id=str(payload["decision_id"]),
        action=str(payload.get("action") or ""),
        status=str(payload.get("status") or "UNKNOWN"),
        from_state=str(payload.get("from_state") or ""),
        to_state=str(payload.get("to_state") or ""),
        gate_status=str(payload.get("gate_status") or ""),
        approval_override=bool(payload.get("approval_override", False)),
        executed_steps=[str(item) for item in payload.get("executed_steps") or []],
        skipped_steps=[str(item) for item in payload.get("skipped_steps") or []],
        detail=str(payload.get("detail") or ""),
        created_at=str(payload.get("created_at") or ""),
        idempotency_key=str(payload.get("idempotency_key") or ""),
        approval_receipt=dict(payload["approval_receipt"]) if isinstance(payload.get("approval_receipt"), dict) else None,
    )


def render_recovery_strategy_execution_result(result: RecoveryStrategyExecutionResult) -> str:
    lines = [
        "Recovery strategy execution:",
        f"- execution_id: {result.execution_id}",
        f"- decision_id: {result.decision_id}",
        f"- action: {result.action}",
        f"- status: {result.status}",
        f"- from_state: {result.from_state}",
        f"- to_state: {result.to_state}",
        f"- gate_status: {result.gate_status}",
        f"- approval_override: {result.approval_override}",
        f"- idempotency_key: {result.idempotency_key or '-'}",
        f"- detail: {result.detail}",
    ]
    if result.approval_receipt:
        lines.append(f"- approval_receipt: {result.approval_receipt.get('receipt_id', '-')}")
    _append_list_section(lines, "executed_steps", result.executed_steps)
    _append_list_section(lines, "skipped_steps", result.skipped_steps)
    return "\n".join(lines)


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


def render_operations_action_sla_notifications(report: OperationsActionSlaNotificationReport) -> str:
    lines = [
        "Operations action SLA notifications:",
        f"- notification_count: {report.notification_count}",
        f"- failed_count: {report.failed_count}",
        "- notifications:",
    ]
    if not report.notifications:
        lines.append("  - none")
        return "\n".join(lines)
    for notification in report.notifications:
        lines.append(
            f"  - {notification.event_type}: {notification.status} "
            f"recipient={notification.recipient_id} source={notification.source}"
        )
        if notification.last_error:
            lines.append(f"    error: {notification.last_error}")
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
    owner_counts = dict(Counter(item.owner for item in action_items))
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
        owner_counts=owner_counts,
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
    _append_count_section(lines, "owners", report.owner_counts)
    _append_list_section(lines, "recommendations", report.recommendations)
    return "\n".join(lines)


def operations_closed_loop_report_to_dict(report: OperationsClosedLoopReport) -> dict[str, Any]:
    return {
        "generated_at": report.generated_at,
        "trend_alerts": report.trend_alerts,
        "action_items_total": report.action_items_total,
        "action_items_open": report.action_items_open,
        "action_items_closed": report.action_items_closed,
        "action_items_overdue": report.action_items_overdue,
        "closure_rate": report.closure_rate,
        "knowledge_entries": report.knowledge_entries,
        "knowledge_topics": report.knowledge_topics,
        "source_counts": report.source_counts,
        "owner_counts": report.owner_counts,
        "recommendations": report.recommendations,
    }


def build_operations_closed_loop_snapshot(
    report: OperationsClosedLoopReport,
    snapshot_id: str | None = None,
    created_at: str | None = None,
    metadata: dict[str, str] | None = None,
) -> OperationsClosedLoopSnapshot:
    created_at = created_at or datetime.now(timezone.utc).isoformat()
    snapshot_id = snapshot_id or _stable_id(
        "CLP",
        report.generated_at,
        str(report.trend_alerts),
        str(report.action_items_total),
        str(report.action_items_closed),
        str(report.closure_rate),
    )
    return OperationsClosedLoopSnapshot(
        snapshot_id=snapshot_id,
        created_at=created_at,
        report=report,
        metadata={str(key): str(value) for key, value in dict(metadata or {}).items()},
    )


def render_operations_closed_loop_report_json(report: OperationsClosedLoopReport) -> str:
    return json.dumps({"closed_loop": operations_closed_loop_report_to_dict(report)}, ensure_ascii=False)


def render_operations_closed_loop_report_prometheus(report: OperationsClosedLoopReport) -> str:
    lines = [
        "# HELP travel_operations_closed_loop_action_items Operations closed-loop action item counts.",
        "# TYPE travel_operations_closed_loop_action_items gauge",
        f'travel_operations_closed_loop_action_items{{status="total"}} {report.action_items_total}',
        f'travel_operations_closed_loop_action_items{{status="open"}} {report.action_items_open}',
        f'travel_operations_closed_loop_action_items{{status="closed"}} {report.action_items_closed}',
        f'travel_operations_closed_loop_action_items{{status="overdue"}} {report.action_items_overdue}',
        "# HELP travel_operations_closed_loop_trend_alerts Trend alerts included in the closed-loop report.",
        "# TYPE travel_operations_closed_loop_trend_alerts gauge",
        f"travel_operations_closed_loop_trend_alerts {report.trend_alerts}",
        "# HELP travel_operations_closed_loop_closure_rate_percent Closed action item percentage.",
        "# TYPE travel_operations_closed_loop_closure_rate_percent gauge",
        f"travel_operations_closed_loop_closure_rate_percent {report.closure_rate:.1f}",
        "# HELP travel_operations_closed_loop_knowledge_entries Knowledge entries included in the closed-loop report.",
        "# TYPE travel_operations_closed_loop_knowledge_entries gauge",
        f"travel_operations_closed_loop_knowledge_entries {report.knowledge_entries}",
        "# HELP travel_operations_closed_loop_knowledge_topics Knowledge entries by topic.",
        "# TYPE travel_operations_closed_loop_knowledge_topics gauge",
    ]
    if report.knowledge_topics:
        for topic, count in _sorted_count_items(report.knowledge_topics):
            lines.append(
                f'travel_operations_closed_loop_knowledge_topics{{topic="{_metric_label(topic)}"}} {count}'
            )
    else:
        lines.append('travel_operations_closed_loop_knowledge_topics{topic="none"} 0')
    lines.extend(
        [
            "# HELP travel_operations_closed_loop_action_sources Action items by source type.",
            "# TYPE travel_operations_closed_loop_action_sources gauge",
        ]
    )
    if report.source_counts:
        for source, count in _sorted_count_items(report.source_counts):
            lines.append(
                f'travel_operations_closed_loop_action_sources{{source_type="{_metric_label(source)}"}} {count}'
            )
    else:
        lines.append('travel_operations_closed_loop_action_sources{source_type="none"} 0')
    lines.extend(
        [
            "# HELP travel_operations_closed_loop_action_owners Action items by owner.",
            "# TYPE travel_operations_closed_loop_action_owners gauge",
        ]
    )
    if report.owner_counts:
        for owner, count in _sorted_count_items(report.owner_counts):
            lines.append(f'travel_operations_closed_loop_action_owners{{owner="{_metric_label(owner)}"}} {count}')
    else:
        lines.append('travel_operations_closed_loop_action_owners{owner="none"} 0')
    return "\n".join(lines)


def build_recovery_strategy_metrics(sessions: list[TravelContext]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for context in sessions:
        for record in context.recovery_records:
            execution = record.payload.get("strategy_execution") if isinstance(record.payload, dict) else None
            if not isinstance(execution, dict):
                continue
            status = str(execution.get("status") or "UNKNOWN")
            action = str(execution.get("action") or record.action or "unknown")
            counts[f"status:{status}"] += 1
            counts[f"action:{action}"] += 1
            if execution.get("approval_override"):
                counts["approval_override"] += 1
            if execution.get("approval_receipt"):
                counts["approval_receipt"] += 1
            if execution.get("idempotent"):
                counts["idempotent_skip"] += 1
    return dict(counts)


def render_recovery_strategy_metrics_prometheus(sessions: list[TravelContext]) -> str:
    metrics = build_recovery_strategy_metrics(sessions)
    lines = [
        "# HELP travel_recovery_strategy_executions_total Recovery strategy execution records.",
        "# TYPE travel_recovery_strategy_executions_total counter",
    ]
    emitted = False
    for key, count in sorted(metrics.items()):
        prefix, value = key.split(":", 1) if ":" in key else ("kind", key)
        if prefix in {"status", "action"}:
            emitted = True
            lines.append(
                "travel_recovery_strategy_executions_total"
                f'{{{prefix}="{_metric_label(value)}"}} {count}'
            )
    if not emitted:
        lines.append("travel_recovery_strategy_executions_total 0")
    lines.extend(
        [
            "# HELP travel_recovery_strategy_approval_overrides_total Recovery executions using approval override.",
            "# TYPE travel_recovery_strategy_approval_overrides_total counter",
            f"travel_recovery_strategy_approval_overrides_total {metrics.get('approval_override', 0)}",
            "# HELP travel_recovery_strategy_approval_receipts_total Recovery executions with approval receipts.",
            "# TYPE travel_recovery_strategy_approval_receipts_total counter",
            f"travel_recovery_strategy_approval_receipts_total {metrics.get('approval_receipt', 0)}",
            "# HELP travel_recovery_strategy_idempotent_skips_total Duplicate recovery execution requests skipped.",
            "# TYPE travel_recovery_strategy_idempotent_skips_total counter",
            f"travel_recovery_strategy_idempotent_skips_total {metrics.get('idempotent_skip', 0)}",
        ]
    )
    return "\n".join(lines)


def export_operations_closed_loop_report_http(
    report: OperationsClosedLoopReport,
    endpoint: str,
    token: str | None = None,
    http_client: Any | None = None,
) -> OperationsClosedLoopExportResult:
    from .integrations import JsonHttpClient

    payload = {
        "source": "travel-agent",
        "closed_loop": operations_closed_loop_report_to_dict(report),
    }
    try:
        client = http_client or JsonHttpClient()
        response = client.post_json(endpoint, payload, token)
    except Exception as exc:
        return OperationsClosedLoopExportResult(
            ok=False,
            endpoint=endpoint,
            delivered=0,
            failed=1,
            detail=str(exc),
        )
    delivered = int(response.get("accepted") or response.get("delivered") or 1)
    failed = 0 if delivered > 0 else 1
    return OperationsClosedLoopExportResult(
        ok=bool(response.get("ok", failed == 0)),
        endpoint=endpoint,
        delivered=delivered,
        failed=failed,
        detail=str(response.get("detail") or "sent to closed-loop sink"),
    )


def render_operations_closed_loop_export_result(result: OperationsClosedLoopExportResult) -> str:
    return "\n".join(
        [
            "Operations closed-loop export:",
            f"- ok: {result.ok}",
            f"- endpoint: {result.endpoint}",
            f"- delivered: {result.delivered}",
            f"- failed: {result.failed}",
            f"- detail: {result.detail}",
        ]
    )


def operations_closed_loop_snapshot_to_dict(snapshot: OperationsClosedLoopSnapshot) -> dict[str, Any]:
    return {
        "snapshot_id": snapshot.snapshot_id,
        "created_at": snapshot.created_at,
        "report": operations_closed_loop_report_to_dict(snapshot.report),
        "metadata": dict(snapshot.metadata),
    }


def operations_closed_loop_snapshot_from_dict(payload: dict[str, Any]) -> OperationsClosedLoopSnapshot:
    return OperationsClosedLoopSnapshot(
        snapshot_id=str(payload["snapshot_id"]),
        created_at=str(payload.get("created_at") or ""),
        report=OperationsClosedLoopReport(
            generated_at=str(payload["report"]["generated_at"]),
            trend_alerts=int(payload["report"].get("trend_alerts") or 0),
            action_items_total=int(payload["report"].get("action_items_total") or 0),
            action_items_open=int(payload["report"].get("action_items_open") or 0),
            action_items_closed=int(payload["report"].get("action_items_closed") or 0),
            action_items_overdue=int(payload["report"].get("action_items_overdue") or 0),
            closure_rate=float(payload["report"].get("closure_rate") or 0.0),
            knowledge_entries=int(payload["report"].get("knowledge_entries") or 0),
            knowledge_topics={
                str(key): int(value) for key, value in dict(payload["report"].get("knowledge_topics") or {}).items()
            },
            source_counts={
                str(key): int(value) for key, value in dict(payload["report"].get("source_counts") or {}).items()
            },
            owner_counts={
                str(key): int(value) for key, value in dict(payload["report"].get("owner_counts") or {}).items()
            },
            recommendations=[str(item) for item in payload["report"].get("recommendations") or []],
        ),
        metadata={str(key): str(value) for key, value in dict(payload.get("metadata") or {}).items()},
    )


def render_operations_closed_loop_snapshot(snapshot: OperationsClosedLoopSnapshot) -> str:
    lines = [
        "Operations closed-loop snapshot:",
        f"- snapshot_id: {snapshot.snapshot_id}",
        f"- created_at: {snapshot.created_at}",
        f"- closure_rate: {snapshot.report.closure_rate:.1f}%",
        f"- action_items_total: {snapshot.report.action_items_total}",
        f"- knowledge_entries: {snapshot.report.knowledge_entries}",
    ]
    if snapshot.metadata:
        lines.append("- metadata:")
        for key, value in sorted(snapshot.metadata.items()):
            lines.append(f"  - {key}: {value}")
    return "\n".join(lines)


def render_operations_closed_loop_snapshots(snapshots: list[OperationsClosedLoopSnapshot]) -> str:
    lines = ["Operations closed-loop snapshots:"]
    if not snapshots:
        lines.append("- none")
        return "\n".join(lines)
    for snapshot in snapshots:
        lines.append(
            f"- {snapshot.snapshot_id}: generated_at={snapshot.report.generated_at} "
            f"closure_rate={snapshot.report.closure_rate:.1f}%"
        )
        lines.append(f"  created_at: {snapshot.created_at}")
        if snapshot.metadata:
            metadata = ", ".join(f"{key}={value}" for key, value in sorted(snapshot.metadata.items()))
            lines.append(f"  metadata: {metadata}")
        if snapshot.report.recommendations:
            lines.append(f"  recommendations: {'; '.join(snapshot.report.recommendations)}")
    return "\n".join(lines)


def build_operations_closed_loop_dashboard(
    snapshots: list[OperationsClosedLoopSnapshot] | None = None,
    generated_at: str | None = None,
    limit: int = 20,
    owner: str | None = None,
    since: str | None = None,
    cursor: str | None = None,
    department: str | None = None,
    tenant: str | None = None,
    checkpoint: str | None = None,
) -> OperationsClosedLoopDashboard:
    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    limit = max(1, int(limit))
    filtered = list(snapshots or [])
    if owner:
        filtered = [snapshot for snapshot in filtered if snapshot.report.owner_counts.get(owner, 0) > 0]
    if department:
        filtered = [snapshot for snapshot in filtered if snapshot.metadata.get("department") == department]
    if tenant:
        filtered = [snapshot for snapshot in filtered if snapshot.metadata.get("tenant") == tenant]
    if since:
        since_ts = _timestamp_sort_key(since)
        filtered = [snapshot for snapshot in filtered if _timestamp_sort_key(snapshot.created_at) >= since_ts]
    effective_cursor = cursor or checkpoint
    if effective_cursor:
        cursor_ts = _timestamp_sort_key(effective_cursor)
        filtered = [snapshot for snapshot in filtered if _timestamp_sort_key(snapshot.created_at) < cursor_ts]
    ordered_candidates = sorted(filtered, key=lambda snapshot: snapshot.created_at, reverse=True)
    ordered = ordered_candidates[:limit]
    has_more = len(ordered_candidates) > limit
    next_cursor = ordered[-1].created_at if has_more and ordered else None
    checkpoint_value = next_cursor or (ordered[-1].created_at if ordered else effective_cursor)
    latest = ordered[0] if ordered else None
    previous = ordered[1] if len(ordered) > 1 else None
    trends = _closed_loop_dashboard_trends(latest, previous)
    if latest is None:
        summary = "No closed-loop snapshots are available."
    elif previous is None:
        summary = f"Latest closed-loop snapshot {latest.snapshot_id} is ready; trend baseline is not available yet."
    else:
        closure_delta = latest.report.closure_rate - previous.report.closure_rate
        summary = (
            f"Latest closed-loop snapshot {latest.snapshot_id} compared with {previous.snapshot_id}; "
            f"closure_rate_delta={closure_delta:.1f}."
        )
    return OperationsClosedLoopDashboard(
        schema_version="travel.operations.closed_loop.v1",
        generated_at=generated_at,
        snapshot_count=len(ordered),
        latest_snapshot=latest,
        snapshots=ordered,
        trends=trends,
        filters={
            key: value
            for key, value in {
                "owner": owner,
                "since": since,
                "cursor": cursor,
                "department": department,
                "tenant": tenant,
                "checkpoint": checkpoint,
            }.items()
            if value
        },
        summary=summary,
        cursor=cursor,
        next_cursor=next_cursor,
        limit=limit,
        has_more=has_more,
        checkpoint=checkpoint_value,
    )


def operations_closed_loop_dashboard_to_dict(dashboard: OperationsClosedLoopDashboard) -> dict[str, Any]:
    return {
        "schema_version": dashboard.schema_version,
        "generated_at": dashboard.generated_at,
        "snapshot_count": dashboard.snapshot_count,
        "latest_snapshot": (
            operations_closed_loop_snapshot_to_dict(dashboard.latest_snapshot)
            if dashboard.latest_snapshot is not None
            else None
        ),
        "snapshots": [operations_closed_loop_snapshot_to_dict(snapshot) for snapshot in dashboard.snapshots],
        "trends": [
            {
                "name": metric.name,
                "current": metric.current,
                "previous": metric.previous,
                "delta": metric.delta,
                "delta_percent": metric.delta_percent,
            }
            for metric in dashboard.trends
        ],
        "filters": dashboard.filters,
        "summary": dashboard.summary,
        "cursor": dashboard.cursor,
        "next_cursor": dashboard.next_cursor,
        "limit": dashboard.limit,
        "has_more": dashboard.has_more,
        "checkpoint": dashboard.checkpoint,
    }


def render_operations_closed_loop_dashboard_json(dashboard: OperationsClosedLoopDashboard) -> str:
    return json.dumps(
        {"closed_loop_dashboard": operations_closed_loop_dashboard_to_dict(dashboard)},
        ensure_ascii=False,
    )


def build_operations_closed_loop_json_schema() -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://travel-agent.local/schemas/travel.operations.closed_loop.v1.json",
        "title": "Travel Operations Closed Loop Dashboard",
        "type": "object",
        "required": ["closed_loop_dashboard"],
        "properties": {
            "closed_loop_dashboard": {
                "type": "object",
                "required": [
                    "schema_version",
                    "generated_at",
                    "snapshot_count",
                    "snapshots",
                    "trends",
                    "filters",
                    "summary",
                    "limit",
                    "has_more",
                ],
                "properties": {
                    "schema_version": {"const": "travel.operations.closed_loop.v1"},
                    "generated_at": {"type": "string"},
                    "snapshot_count": {"type": "integer", "minimum": 0},
                    "latest_snapshot": {"anyOf": [{"$ref": "#/$defs/snapshot"}, {"type": "null"}]},
                    "snapshots": {"type": "array", "items": {"$ref": "#/$defs/snapshot"}},
                    "trends": {"type": "array", "items": {"$ref": "#/$defs/trend"}},
                    "filters": {"type": "object", "additionalProperties": {"type": "string"}},
                    "summary": {"type": "string"},
                    "cursor": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                    "next_cursor": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                    "checkpoint": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                    "limit": {"type": "integer", "minimum": 1},
                    "has_more": {"type": "boolean"},
                },
                "additionalProperties": False,
            }
        },
        "$defs": {
            "snapshot": {
                "type": "object",
                "required": ["snapshot_id", "created_at", "report", "metadata"],
                "properties": {
                    "snapshot_id": {"type": "string"},
                    "created_at": {"type": "string"},
                    "metadata": {"type": "object", "additionalProperties": {"type": "string"}},
                    "report": {"$ref": "#/$defs/report"},
                },
                "additionalProperties": False,
            },
            "report": {
                "type": "object",
                "required": [
                    "generated_at",
                    "trend_alerts",
                    "action_items_total",
                    "action_items_open",
                    "action_items_closed",
                    "action_items_overdue",
                    "closure_rate",
                    "knowledge_entries",
                    "knowledge_topics",
                    "source_counts",
                    "owner_counts",
                    "recommendations",
                ],
                "properties": {
                    "generated_at": {"type": "string"},
                    "trend_alerts": {"type": "integer"},
                    "action_items_total": {"type": "integer"},
                    "action_items_open": {"type": "integer"},
                    "action_items_closed": {"type": "integer"},
                    "action_items_overdue": {"type": "integer"},
                    "closure_rate": {"type": "number"},
                    "knowledge_entries": {"type": "integer"},
                    "knowledge_topics": {"type": "object", "additionalProperties": {"type": "integer"}},
                    "source_counts": {"type": "object", "additionalProperties": {"type": "integer"}},
                    "owner_counts": {"type": "object", "additionalProperties": {"type": "integer"}},
                    "recommendations": {"type": "array", "items": {"type": "string"}},
                },
                "additionalProperties": False,
            },
            "trend": {
                "type": "object",
                "required": ["name", "current", "previous", "delta", "delta_percent"],
                "properties": {
                    "name": {"type": "string"},
                    "current": {"type": "integer"},
                    "previous": {"type": "integer"},
                    "delta": {"type": "integer"},
                    "delta_percent": {"anyOf": [{"type": "number"}, {"type": "null"}]},
                },
                "additionalProperties": False,
            },
        },
        "additionalProperties": False,
    }


def render_operations_closed_loop_json_schema() -> str:
    return json.dumps(build_operations_closed_loop_json_schema(), ensure_ascii=False, indent=2)


def build_operations_closed_loop_openapi_spec(
    server_url: str = "http://127.0.0.1:9110",
) -> dict[str, Any]:
    schema = build_operations_closed_loop_json_schema()["properties"]["closed_loop_dashboard"]
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "Travel Agent Operations Closed Loop API",
            "version": "travel.operations.closed_loop.v1",
        },
        "servers": [{"url": server_url}],
        "paths": {
            "/operations/closed-loop": {
                "get": {
                    "summary": "Query closed-loop dashboard snapshots",
                    "parameters": [
                        _openapi_query_param("owner"),
                        _openapi_query_param("since"),
                        _openapi_query_param("cursor"),
                        _openapi_query_param("department"),
                        _openapi_query_param("tenant"),
                        _openapi_query_param("checkpoint"),
                        _openapi_query_param("limit", "integer"),
                    ],
                    "responses": {
                        "200": {
                            "description": "Closed-loop dashboard payload",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {"closed_loop_dashboard": schema},
                                        "required": ["closed_loop_dashboard"],
                                    }
                                }
                            },
                        },
                        "401": {"description": "Missing or invalid dashboard token"},
                    },
                }
            },
            "/operations/closed-loop/snapshots": {
                "get": {
                    "summary": "Alias for closed-loop snapshot dashboard query",
                    "responses": {"200": {"description": "Closed-loop dashboard payload"}},
                }
            },
        },
    }


def render_operations_closed_loop_openapi_spec(server_url: str = "http://127.0.0.1:9110") -> str:
    return json.dumps(build_operations_closed_loop_openapi_spec(server_url), ensure_ascii=False, indent=2)


def build_operations_closed_loop_contract_matrix() -> list[dict[str, Any]]:
    return [
        {
            "schema_version": "travel.operations.closed_loop.v1",
            "status": "current",
            "required_fields": [
                "schema_version",
                "generated_at",
                "snapshot_count",
                "snapshots",
                "trends",
                "filters",
                "summary",
                "limit",
                "has_more",
            ],
            "optional_fields": ["latest_snapshot", "cursor", "next_cursor", "checkpoint"],
            "compatible_consumers": ["dashboard-http", "bi-snapshot-export", "scheduled-checkpoint"],
        }
    ]


def render_operations_closed_loop_contract_matrix_json() -> str:
    return json.dumps(
        {"closed_loop_contract_matrix": build_operations_closed_loop_contract_matrix()},
        ensure_ascii=False,
        indent=2,
    )


def validate_operations_closed_loop_dashboard_contract(
    dashboard: OperationsClosedLoopDashboard,
) -> dict[str, Any]:
    payload = operations_closed_loop_dashboard_to_dict(dashboard)
    required = [
        "schema_version",
        "generated_at",
        "snapshot_count",
        "snapshots",
        "trends",
        "filters",
        "summary",
        "limit",
        "has_more",
    ]
    missing = [field for field in required if field not in payload]
    errors: list[str] = []
    if payload.get("schema_version") != "travel.operations.closed_loop.v1":
        errors.append("schema_version must be travel.operations.closed_loop.v1")
    if payload.get("limit", 0) < 1:
        errors.append("limit must be >= 1")
    for snapshot in payload.get("snapshots") or []:
        if "metadata" not in snapshot:
            errors.append(f"snapshot {snapshot.get('snapshot_id', '-')} missing metadata")
        if "report" not in snapshot:
            errors.append(f"snapshot {snapshot.get('snapshot_id', '-')} missing report")
    errors.extend(f"missing required field: {field}" for field in missing)
    return {
        "schema_version": payload.get("schema_version"),
        "ok": not errors,
        "errors": errors,
        "checkpoint": payload.get("checkpoint"),
        "snapshot_count": payload.get("snapshot_count", 0),
    }


def publish_operations_closed_loop_schema_http(
    endpoint: str,
    token: str | None = None,
    http_client: Any | None = None,
    server_url: str = "http://127.0.0.1:9110",
) -> OperationsClosedLoopSchemaPublishResult:
    from .integrations import JsonHttpClient

    payload = {
        "source": "travel-agent",
        "schema_version": "travel.operations.closed_loop.v1",
        "schema": build_operations_closed_loop_json_schema(),
        "openapi": build_operations_closed_loop_openapi_spec(server_url),
        "compatibility_matrix": build_operations_closed_loop_contract_matrix(),
    }
    try:
        client = http_client or JsonHttpClient()
        response = client.post_json(endpoint, payload, token)
    except Exception as exc:
        return OperationsClosedLoopSchemaPublishResult(
            ok=False,
            endpoint=endpoint,
            schema_version="travel.operations.closed_loop.v1",
            delivered=0,
            failed=1,
            detail=str(exc),
        )
    delivered = int(response.get("accepted") or response.get("delivered") or 1)
    failed = 0 if delivered > 0 else 1
    return OperationsClosedLoopSchemaPublishResult(
        ok=bool(response.get("ok", failed == 0)),
        endpoint=endpoint,
        schema_version=str(response.get("schema_version") or "travel.operations.closed_loop.v1"),
        delivered=delivered,
        failed=failed,
        detail=str(response.get("detail") or "closed-loop schema published"),
    )


def render_operations_closed_loop_schema_publish_result(
    result: OperationsClosedLoopSchemaPublishResult,
) -> str:
    return "\n".join(
        [
            "Operations closed-loop schema publish:",
            f"- ok: {result.ok}",
            f"- endpoint: {result.endpoint}",
            f"- schema_version: {result.schema_version}",
            f"- delivered: {result.delivered}",
            f"- failed: {result.failed}",
            f"- detail: {result.detail}",
        ]
    )


def evaluate_operations_closed_loop_quality(
    dashboard: OperationsClosedLoopDashboard,
    generated_at: str | None = None,
) -> OperationsClosedLoopQualityReport:
    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    findings: list[OperationsClosedLoopQualityFinding] = []
    if dashboard.snapshot_count != len(dashboard.snapshots):
        findings.append(
            OperationsClosedLoopQualityFinding(
                severity="critical",
                code="snapshot_count_mismatch",
                message="snapshot_count does not match snapshots length",
            )
        )
    if dashboard.limit < 1:
        findings.append(
            OperationsClosedLoopQualityFinding(
                severity="critical",
                code="invalid_limit",
                message="dashboard limit must be >= 1",
            )
        )
    if dashboard.latest_snapshot is None:
        findings.append(
            OperationsClosedLoopQualityFinding(
                severity="warning",
                code="empty_dashboard",
                message="no closed-loop snapshot is available for BI consumption",
            )
        )
    for snapshot in dashboard.snapshots:
        report = snapshot.report
        if "tenant" not in snapshot.metadata:
            findings.append(
                OperationsClosedLoopQualityFinding(
                    severity="warning",
                    code="missing_tenant",
                    message="snapshot metadata should include tenant",
                    snapshot_id=snapshot.snapshot_id,
                )
            )
        if "department" not in snapshot.metadata:
            findings.append(
                OperationsClosedLoopQualityFinding(
                    severity="warning",
                    code="missing_department",
                    message="snapshot metadata should include department",
                    snapshot_id=snapshot.snapshot_id,
                )
            )
        numeric_fields = {
            "trend_alerts": report.trend_alerts,
            "action_items_total": report.action_items_total,
            "action_items_open": report.action_items_open,
            "action_items_closed": report.action_items_closed,
            "action_items_overdue": report.action_items_overdue,
            "knowledge_entries": report.knowledge_entries,
        }
        for field_name, value in numeric_fields.items():
            if value < 0:
                findings.append(
                    OperationsClosedLoopQualityFinding(
                        severity="critical",
                        code="negative_metric",
                        message=f"{field_name} must be non-negative",
                        snapshot_id=snapshot.snapshot_id,
                    )
                )
        if not 0.0 <= report.closure_rate <= 100.0:
            findings.append(
                OperationsClosedLoopQualityFinding(
                    severity="critical",
                    code="closure_rate_out_of_range",
                    message="closure_rate must be between 0 and 100",
                    snapshot_id=snapshot.snapshot_id,
                )
            )
    ok = not any(finding.severity == "critical" for finding in findings)
    summary = (
        "Closed-loop dashboard quality passed."
        if ok and not findings
        else f"Closed-loop dashboard quality found {len(findings)} finding(s)."
    )
    return OperationsClosedLoopQualityReport(
        ok=ok,
        generated_at=generated_at,
        snapshot_count=dashboard.snapshot_count,
        findings=findings,
        summary=summary,
    )


def operations_closed_loop_quality_finding_to_dict(
    finding: OperationsClosedLoopQualityFinding,
) -> dict[str, Any]:
    return {
        "severity": finding.severity,
        "code": finding.code,
        "message": finding.message,
        "snapshot_id": finding.snapshot_id,
    }


def operations_closed_loop_quality_report_to_dict(report: OperationsClosedLoopQualityReport) -> dict[str, Any]:
    return {
        "ok": report.ok,
        "generated_at": report.generated_at,
        "snapshot_count": report.snapshot_count,
        "findings": [operations_closed_loop_quality_finding_to_dict(item) for item in report.findings],
        "summary": report.summary,
    }


def render_operations_closed_loop_quality_report(report: OperationsClosedLoopQualityReport) -> str:
    lines = [
        "Operations closed-loop quality:",
        f"- ok: {report.ok}",
        f"- generated_at: {report.generated_at}",
        f"- snapshot_count: {report.snapshot_count}",
        f"- findings: {len(report.findings)}",
        f"- summary: {report.summary}",
    ]
    if report.findings:
        lines.append("- details:")
        for finding in report.findings:
            lines.append(
                f"  - {finding.severity}/{finding.code}: "
                f"{finding.snapshot_id or '-'} {finding.message}"
            )
    return "\n".join(lines)


def build_operations_closed_loop_checkpoint_plan(
    dashboard: OperationsClosedLoopDashboard,
    generated_at: str | None = None,
) -> OperationsClosedLoopCheckpointPlan:
    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    next_checkpoint = dashboard.next_cursor or (
        dashboard.snapshots[-1].created_at if dashboard.snapshots else dashboard.checkpoint
    )
    ready = bool(next_checkpoint)
    summary = (
        f"Next checkpoint can continue from {next_checkpoint}."
        if ready
        else "No checkpoint can be created because no snapshots are available."
    )
    return OperationsClosedLoopCheckpointPlan(
        generated_at=generated_at,
        checkpoint=dashboard.checkpoint,
        next_checkpoint=next_checkpoint,
        snapshot_count=dashboard.snapshot_count,
        ready=ready,
        summary=summary,
    )


def operations_closed_loop_checkpoint_plan_to_dict(
    plan: OperationsClosedLoopCheckpointPlan,
) -> dict[str, Any]:
    return {
        "generated_at": plan.generated_at,
        "checkpoint": plan.checkpoint,
        "next_checkpoint": plan.next_checkpoint,
        "snapshot_count": plan.snapshot_count,
        "ready": plan.ready,
        "summary": plan.summary,
    }


def render_operations_closed_loop_checkpoint_plan(plan: OperationsClosedLoopCheckpointPlan) -> str:
    return "\n".join(
        [
            "Operations closed-loop checkpoint plan:",
            f"- generated_at: {plan.generated_at}",
            f"- checkpoint: {plan.checkpoint or '-'}",
            f"- next_checkpoint: {plan.next_checkpoint or '-'}",
            f"- snapshot_count: {plan.snapshot_count}",
            f"- ready: {plan.ready}",
            f"- summary: {plan.summary}",
        ]
    )


def build_operations_closed_loop_acceptance_report(
    dashboard: OperationsClosedLoopDashboard,
    generated_at: str | None = None,
) -> OperationsClosedLoopAcceptanceReport:
    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    contract = validate_operations_closed_loop_dashboard_contract(dashboard)
    quality = evaluate_operations_closed_loop_quality(dashboard, generated_at=generated_at)
    checkpoint = build_operations_closed_loop_checkpoint_plan(dashboard, generated_at=generated_at)
    findings = [str(item) for item in contract.get("errors") or []]
    findings.extend(f"{item.severity}/{item.code}: {item.message}" for item in quality.findings)
    publish_ready = bool(contract.get("ok")) and quality.ok and bool(dashboard.schema_version)
    ok = bool(contract.get("ok")) and quality.ok and checkpoint.ready
    return OperationsClosedLoopAcceptanceReport(
        ok=ok,
        generated_at=generated_at,
        contract_ok=bool(contract.get("ok")),
        quality_ok=quality.ok,
        publish_ready=publish_ready,
        checkpoint_ready=checkpoint.ready,
        findings=_dedupe(findings),
    )


def operations_closed_loop_acceptance_report_to_dict(
    report: OperationsClosedLoopAcceptanceReport,
) -> dict[str, Any]:
    return {
        "ok": report.ok,
        "generated_at": report.generated_at,
        "contract_ok": report.contract_ok,
        "quality_ok": report.quality_ok,
        "publish_ready": report.publish_ready,
        "checkpoint_ready": report.checkpoint_ready,
        "findings": report.findings,
    }


def render_operations_closed_loop_acceptance_report(
    report: OperationsClosedLoopAcceptanceReport,
) -> str:
    lines = [
        "Operations closed-loop acceptance:",
        f"- ok: {report.ok}",
        f"- generated_at: {report.generated_at}",
        f"- contract_ok: {report.contract_ok}",
        f"- quality_ok: {report.quality_ok}",
        f"- publish_ready: {report.publish_ready}",
        f"- checkpoint_ready: {report.checkpoint_ready}",
    ]
    _append_list_section(lines, "findings", report.findings)
    return "\n".join(lines)


def build_operations_scheduled_tasks(
    now: str | None = None,
    include_replay_job_runner: bool = True,
) -> list[OperationsScheduledTask]:
    now = now or datetime.now(timezone.utc).isoformat()
    tasks = [
        OperationsScheduledTask(
            task_id="OPS-SCHED-CLOSED-LOOP-SNAPSHOT",
            task_type="closed_loop_snapshot",
            cadence="hourly",
            next_run_at=now,
            enabled=True,
            params={"metadata_required": ["department", "tenant"]},
        ),
        OperationsScheduledTask(
            task_id="OPS-SCHED-CLOSED-LOOP-CHECKPOINT",
            task_type="closed_loop_checkpoint",
            cadence="hourly",
            next_run_at=now,
            enabled=True,
            params={"limit": 20},
        ),
        OperationsScheduledTask(
            task_id="OPS-SCHED-BI-QUALITY",
            task_type="closed_loop_quality",
            cadence="hourly",
            next_run_at=now,
            enabled=True,
            params={"fail_on_critical": True},
        ),
        OperationsScheduledTask(
            task_id="OPS-SCHED-RECOVERY-APPROVAL-SLA",
            task_type="recovery_approval_sla",
            cadence="hourly",
            next_run_at=now,
            enabled=True,
            params={"max_pending_hours": 24.0},
        ),
        OperationsScheduledTask(
            task_id="OPS-SCHED-COMPENSATION-TASK-EXECUTION",
            task_type="compensation_task_execution",
            cadence="every_15_minutes",
            next_run_at=now,
            enabled=True,
            params={"limit": 20},
        ),
        OperationsScheduledTask(
            task_id="OPS-SCHED-COMPENSATION-SLO",
            task_type="compensation_slo_evaluation",
            cadence="every_15_minutes",
            next_run_at=now,
            enabled=True,
            params={"limit": 20},
        ),
    ]
    if include_replay_job_runner:
        tasks.append(
            OperationsScheduledTask(
                task_id="OPS-SCHED-WEBHOOK-REPLAY-JOBS",
                task_type="webhook_replay_jobs",
                cadence="every_5_minutes",
                next_run_at=now,
                enabled=True,
                params={"limit": 20},
            )
        )
    return tasks


def operations_scheduled_task_to_dict(task: OperationsScheduledTask) -> dict[str, Any]:
    return {
        "task_id": task.task_id,
        "task_type": task.task_type,
        "cadence": task.cadence,
        "next_run_at": task.next_run_at,
        "enabled": task.enabled,
        "params": task.params,
        "last_run_at": task.last_run_at,
        "last_status": task.last_status,
        "run_count": task.run_count,
        "failure_count": task.failure_count,
        "lease_owner": task.lease_owner,
        "lease_expires_at": task.lease_expires_at,
    }


def operations_scheduled_task_from_dict(payload: dict[str, Any]) -> OperationsScheduledTask:
    return OperationsScheduledTask(
        task_id=str(payload["task_id"]),
        task_type=str(payload.get("task_type") or ""),
        cadence=str(payload.get("cadence") or "manual"),
        next_run_at=str(payload.get("next_run_at") or ""),
        enabled=bool(payload.get("enabled", True)),
        params=dict(payload.get("params") or {}),
        last_run_at=str(payload["last_run_at"]) if payload.get("last_run_at") is not None else None,
        last_status=str(payload["last_status"]) if payload.get("last_status") is not None else None,
        run_count=int(payload.get("run_count") or 0),
        failure_count=int(payload.get("failure_count") or 0),
        lease_owner=str(payload["lease_owner"]) if payload.get("lease_owner") is not None else None,
        lease_expires_at=str(payload["lease_expires_at"]) if payload.get("lease_expires_at") is not None else None,
    )


def next_operations_schedule_run_at(
    cadence: str,
    from_time: str | None = None,
) -> str:
    base = _parse_iso_datetime(from_time or datetime.now(timezone.utc).isoformat())
    seconds = _operations_schedule_cadence_seconds(cadence)
    return datetime.fromtimestamp(base.timestamp() + seconds, timezone.utc).isoformat()


def advance_operations_scheduled_task(
    task: OperationsScheduledTask,
    result: OperationsScheduledTaskResult,
) -> OperationsScheduledTask:
    failed = result.status == "FAILED"
    failure_count = task.failure_count + 1 if failed else 0
    if failed:
        retry_delay = int(task.params.get("retry_delay_seconds") or min(3600, 60 * max(1, failure_count)))
        next_run_at = datetime.fromtimestamp(
            _parse_iso_datetime(result.finished_at).timestamp() + retry_delay,
            timezone.utc,
        ).isoformat()
    else:
        next_run_at = next_operations_schedule_run_at(task.cadence, result.finished_at)
    return replace(
        task,
        next_run_at=next_run_at,
        last_run_at=result.finished_at,
        last_status=result.status,
        run_count=task.run_count + 1,
        failure_count=failure_count,
        lease_owner=None,
        lease_expires_at=None,
    )


def operations_scheduled_task_result_to_dict(result: OperationsScheduledTaskResult) -> dict[str, Any]:
    return {
        "task_id": result.task_id,
        "task_type": result.task_type,
        "status": result.status,
        "started_at": result.started_at,
        "finished_at": result.finished_at,
        "detail": result.detail,
        "output": result.output,
    }


def operations_scheduler_run_report_to_dict(report: OperationsSchedulerRunReport) -> dict[str, Any]:
    return {
        "run_id": report.run_id,
        "started_at": report.started_at,
        "finished_at": report.finished_at,
        "due_count": report.due_count,
        "executed_count": report.executed_count,
        "failed_count": report.failed_count,
        "results": [operations_scheduled_task_result_to_dict(item) for item in report.results],
        "summary": report.summary,
    }


def operations_scheduler_run_report_from_dict(payload: dict[str, Any]) -> OperationsSchedulerRunReport:
    return OperationsSchedulerRunReport(
        run_id=str(payload["run_id"]),
        started_at=str(payload.get("started_at") or ""),
        finished_at=str(payload.get("finished_at") or ""),
        due_count=int(payload.get("due_count") or 0),
        executed_count=int(payload.get("executed_count") or 0),
        failed_count=int(payload.get("failed_count") or 0),
        results=[
            OperationsScheduledTaskResult(
                task_id=str(item["task_id"]),
                task_type=str(item.get("task_type") or ""),
                status=str(item.get("status") or "UNKNOWN"),
                started_at=str(item.get("started_at") or ""),
                finished_at=str(item.get("finished_at") or ""),
                detail=str(item.get("detail") or ""),
                output=dict(item.get("output") or {}),
            )
            for item in payload.get("results") or []
        ],
        summary=str(payload.get("summary") or ""),
    )


def build_operations_scheduler_health_report(
    run_reports: list[OperationsSchedulerRunReport],
    tasks: list[OperationsScheduledTask],
    now: str | None = None,
    stale_lease_seconds: int = 900,
    stale_task_seconds: int = 86400,
) -> OperationsSchedulerHealthReport:
    generated_at = now or datetime.now(timezone.utc).isoformat()
    alerts: list[dict[str, Any]] = []
    failed_runs = 0
    for report in run_reports:
        if report.failed_count <= 0:
            continue
        failed_runs += 1
        alerts.append(
            {
                "alert_type": "operations_scheduler_run_failed",
                "severity": "critical",
                "message": f"scheduler run {report.run_id} failed {report.failed_count} task(s)",
                "value": report.failed_count,
                "run_id": report.run_id,
                "generated_at": generated_at,
            }
        )
    stale_leases = 0
    now_ts = _timestamp_sort_key(generated_at)
    for task in tasks:
        lease_owner = task.lease_owner or ""
        lease_expires_at = task.lease_expires_at or ""
        if lease_owner and lease_expires_at:
            lease_age = now_ts - _timestamp_sort_key(lease_expires_at)
            if lease_age >= stale_lease_seconds:
                stale_leases += 1
                alerts.append(
                    {
                        "alert_type": "operations_scheduler_stale_lease",
                        "severity": "warning",
                        "message": f"scheduler task {task.task_id} lease expired but is still owned by {lease_owner}",
                        "value": int(lease_age),
                        "task_id": task.task_id,
                        "lease_owner": lease_owner,
                        "lease_expires_at": lease_expires_at,
                        "generated_at": generated_at,
                    }
                )
        if task.enabled and task.last_run_at:
            idle_seconds = now_ts - _timestamp_sort_key(task.last_run_at)
            if idle_seconds >= stale_task_seconds:
                alerts.append(
                    {
                        "alert_type": "operations_scheduler_task_stale",
                        "severity": "warning",
                        "message": f"scheduler task {task.task_id} has not completed recently",
                        "value": int(idle_seconds),
                        "task_id": task.task_id,
                        "last_run_at": task.last_run_at,
                        "generated_at": generated_at,
                    }
                )
        if task.failure_count >= 3:
            alerts.append(
                {
                    "alert_type": "operations_scheduler_task_repeated_failures",
                    "severity": "critical",
                    "message": f"scheduler task {task.task_id} has {task.failure_count} consecutive failure(s)",
                    "value": task.failure_count,
                    "task_id": task.task_id,
                    "generated_at": generated_at,
                }
            )
    summary = (
        f"scheduler_runs={len(run_reports)}; tasks={len(tasks)}; "
        f"failed_runs={failed_runs}; stale_leases={stale_leases}; alerts={len(alerts)}"
    )
    return OperationsSchedulerHealthReport(
        generated_at=generated_at,
        run_count=len(run_reports),
        task_count=len(tasks),
        failed_runs=failed_runs,
        stale_leases=stale_leases,
        alerts=alerts,
        summary=summary,
    )


def operations_scheduler_health_report_to_dict(report: OperationsSchedulerHealthReport) -> dict[str, Any]:
    return {
        "generated_at": report.generated_at,
        "run_count": report.run_count,
        "task_count": report.task_count,
        "failed_runs": report.failed_runs,
        "stale_leases": report.stale_leases,
        "alerts": [_normalize_alert(alert) for alert in report.alerts],
        "summary": report.summary,
    }


def render_operations_scheduler_health_report(report: OperationsSchedulerHealthReport) -> str:
    lines = [
        "Operations scheduler health:",
        f"- generated_at: {report.generated_at}",
        f"- run_count: {report.run_count}",
        f"- task_count: {report.task_count}",
        f"- failed_runs: {report.failed_runs}",
        f"- stale_leases: {report.stale_leases}",
        f"- summary: {report.summary}",
    ]
    if report.alerts:
        lines.append("- alerts:")
        for alert in report.alerts:
            normalized = _normalize_alert(alert)
            lines.append(
                f"  - {normalized['severity']} {normalized['alert_type']}: {normalized['message']}"
            )
    else:
        lines.append("- alerts: none")
    return "\n".join(lines)


def render_operations_scheduled_tasks(tasks: list[OperationsScheduledTask]) -> str:
    lines = ["Operations scheduled tasks:"]
    if not tasks:
        lines.append("- none")
        return "\n".join(lines)
    for task in tasks:
        lines.append(
            f"- {task.task_id}: type={task.task_type} cadence={task.cadence} "
            f"enabled={task.enabled} next_run_at={task.next_run_at}"
        )
    return "\n".join(lines)


def render_operations_scheduler_run_report(report: OperationsSchedulerRunReport) -> str:
    lines = [
        "Operations scheduler run:",
        f"- run_id: {report.run_id}",
        f"- started_at: {report.started_at}",
        f"- finished_at: {report.finished_at}",
        f"- due_count: {report.due_count}",
        f"- executed_count: {report.executed_count}",
        f"- failed_count: {report.failed_count}",
        f"- summary: {report.summary}",
    ]
    if report.results:
        lines.append("- results:")
        for result in report.results:
            lines.append(f"  - {result.task_id}: status={result.status} detail={result.detail}")
    return "\n".join(lines)


def run_operations_scheduled_tasks(
    tasks: list[OperationsScheduledTask],
    handlers: dict[str, Any],
    now: str | None = None,
) -> OperationsSchedulerRunReport:
    started_at = now or datetime.now(timezone.utc).isoformat()
    due_tasks = [
        task
        for task in tasks
        if task.enabled and _timestamp_sort_key(task.next_run_at) <= _timestamp_sort_key(started_at)
    ]
    results: list[OperationsScheduledTaskResult] = []
    for task in due_tasks:
        handler = handlers.get(task.task_type)
        task_started_at = datetime.now(timezone.utc).isoformat()
        if handler is None:
            results.append(
                OperationsScheduledTaskResult(
                    task_id=task.task_id,
                    task_type=task.task_type,
                    status="SKIPPED",
                    started_at=task_started_at,
                    finished_at=datetime.now(timezone.utc).isoformat(),
                    detail="no handler registered",
                    output={},
                )
            )
            continue
        try:
            output = handler(task)
            status = "SUCCESS"
            detail = "task completed"
        except Exception as exc:
            output = {"error": str(exc)}
            status = "FAILED"
            detail = str(exc)
        results.append(
            OperationsScheduledTaskResult(
                task_id=task.task_id,
                task_type=task.task_type,
                status=status,
                started_at=task_started_at,
                finished_at=datetime.now(timezone.utc).isoformat(),
                detail=detail,
                output=dict(output or {}),
            )
        )
    finished_at = datetime.now(timezone.utc).isoformat()
    failed_count = sum(1 for result in results if result.status == "FAILED")
    executed_count = sum(1 for result in results if result.status == "SUCCESS")
    summary = f"Scheduler executed {executed_count}/{len(due_tasks)} due task(s); failed={failed_count}."
    return OperationsSchedulerRunReport(
        run_id=_stable_id("OSR", started_at, finished_at, ",".join(task.task_id for task in due_tasks)),
        started_at=started_at,
        finished_at=finished_at,
        due_count=len(due_tasks),
        executed_count=executed_count,
        failed_count=failed_count,
        results=results,
        summary=summary,
    )


def authorize_operations_action(
    action: str,
    user_id: str,
    permission_policy: PermissionPolicy | None = None,
    department: str | None = None,
    roles: list[str] | set[str] | tuple[str, ...] | None = None,
    audit_sink: AuditSink | None = None,
    payload: dict[str, Any] | None = None,
) -> OperationsActionAuthorization:
    policy = permission_policy or PermissionPolicy.from_env()
    decision = evaluate_permission(
        policy,
        user_id=user_id,
        action=action,
        department=department,
        roles=roles,
    )
    audit_result = None
    if audit_sink is not None:
        audit_payload = {
            "action": action,
            "user_id": user_id,
            "department": department,
            "roles": sorted({str(role) for role in roles or []}),
            "allowed": decision.allowed,
            "decision_status": decision.status,
            "payload": dict(payload or {}),
        }
        audit_result = audit_sink.write([build_audit_event(f"operations.{action}", audit_payload)])
    return OperationsActionAuthorization(
        allowed=decision.allowed,
        action=action,
        user_id=user_id,
        decision=decision,
        audit_result=audit_result,
    )


def operations_action_authorization_to_dict(
    authorization: OperationsActionAuthorization,
) -> dict[str, Any]:
    audit = authorization.audit_result
    return {
        "allowed": authorization.allowed,
        "action": authorization.action,
        "user_id": authorization.user_id,
        "decision": {
            "allowed": authorization.decision.allowed,
            "enforced": authorization.decision.enforced,
            "status": authorization.decision.status,
            "action": authorization.decision.action,
            "user_id": authorization.decision.user_id,
            "department": authorization.decision.department,
            "roles": authorization.decision.roles,
            "reasons": authorization.decision.reasons,
            "source": authorization.decision.source,
        },
        "audit_result": (
            {
                "ok": audit.ok,
                "delivered": audit.delivered,
                "failed": audit.failed,
                "detail": audit.detail,
            }
            if audit is not None
            else None
        ),
    }


def render_operations_action_authorization(authorization: OperationsActionAuthorization) -> str:
    lines = [
        "Operations action authorization:",
        f"- action: {authorization.action}",
        f"- user_id: {authorization.user_id}",
        f"- allowed: {authorization.allowed}",
        f"- decision: {authorization.decision.status}",
    ]
    if authorization.audit_result is not None:
        lines.append(f"- audit: ok={authorization.audit_result.ok} detail={authorization.audit_result.detail}")
    _append_list_section(lines, "reasons", authorization.decision.reasons)
    return "\n".join(lines)


def execute_oncall_webhook_replay_job(
    job: OnCallWebhookReplayJob,
    events: list[OnCallWebhookEvent],
    patches: dict[str, dict[str, Any]] | None = None,
    executed_at: str | None = None,
) -> OnCallWebhookReplayJobExecution:
    executed_at = executed_at or datetime.now(timezone.utc).isoformat()
    event_ids = set(job.event_ids)
    selected = [event for event in events if event.event_id in event_ids]
    if job.status not in {"PENDING", "FAILED"}:
        result = OnCallWebhookReplayBatchResult(
            batch_id=_stable_id("WHB", executed_at, job.job_id, "skipped"),
            generated_at=executed_at,
            attempted=0,
            accepted=0,
            failed=0,
            skipped=1,
            results=[
                OnCallWebhookReplayResult(
                    source_event_id=job.job_id,
                    status="SKIPPED",
                    accepted=False,
                    replayed_at=executed_at,
                    ticket_id=None,
                    reason=f"job status {job.status} is not executable",
                )
            ],
        )
        updated_job = replace(
            job,
            status="SKIPPED",
            batch_result=result,
            audit={**job.audit, "executed_at": executed_at, "previous_status": job.status},
        )
        return OnCallWebhookReplayJobExecution(updated_job, [], [], result)
    replayed_events, statuses, result = replay_dead_letter_oncall_webhook_events(
        selected,
        replayed_at=executed_at,
        patches=patches,
    )
    if result.failed:
        status = "FAILED"
    elif result.accepted:
        status = "COMPLETED"
    elif result.skipped:
        status = "SKIPPED"
    else:
        status = "EMPTY"
    updated_job = replace(
        job,
        status=status,
        batch_result=result,
        audit={
            **job.audit,
            "executed_at": executed_at,
            "selected_events": len(selected),
            "source": "scheduler",
        },
    )
    return OnCallWebhookReplayJobExecution(updated_job, replayed_events, statuses, result)


def oncall_webhook_replay_job_execution_to_dict(
    execution: OnCallWebhookReplayJobExecution,
) -> dict[str, Any]:
    return {
        "job": oncall_webhook_replay_job_to_dict(execution.job),
        "replayed_events": [oncall_webhook_event_to_dict(event) for event in execution.replayed_events],
        "statuses": [oncall_ticket_status_to_dict(status) for status in execution.statuses],
        "result": oncall_webhook_replay_batch_result_to_dict(execution.result),
    }


def render_oncall_webhook_replay_job_execution(execution: OnCallWebhookReplayJobExecution) -> str:
    lines = [
        "OnCall webhook replay job execution:",
        f"- job_id: {execution.job.job_id}",
        f"- status: {execution.job.status}",
        f"- attempted: {execution.result.attempted}",
        f"- accepted: {execution.result.accepted}",
        f"- failed: {execution.result.failed}",
        f"- skipped: {execution.result.skipped}",
    ]
    return "\n".join(lines)


def build_operations_console_overview(
    closed_loop_dashboard: OperationsClosedLoopDashboard,
    webhook_ops: OnCallWebhookOpsConsole,
    replay_jobs: list[OnCallWebhookReplayJob],
    generated_at: str | None = None,
) -> OperationsConsoleOverview:
    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    quality = evaluate_operations_closed_loop_quality(closed_loop_dashboard, generated_at=generated_at)
    acceptance = build_operations_closed_loop_acceptance_report(closed_loop_dashboard, generated_at=generated_at)
    pending_jobs = sum(1 for job in replay_jobs if job.status == "PENDING")
    summary = (
        f"closed_loop_snapshots={closed_loop_dashboard.snapshot_count}; "
        f"dead_letters={webhook_ops.dead_letters}; pending_replay_jobs={pending_jobs}; "
        f"quality_ok={quality.ok}"
    )
    return OperationsConsoleOverview(
        generated_at=generated_at,
        closed_loop_dashboard=closed_loop_dashboard,
        webhook_ops=webhook_ops,
        replay_jobs=list(replay_jobs),
        closed_loop_quality=quality,
        closed_loop_acceptance=acceptance,
        summary=summary,
    )


def operations_console_overview_to_dict(overview: OperationsConsoleOverview) -> dict[str, Any]:
    return {
        "generated_at": overview.generated_at,
        "closed_loop_dashboard": operations_closed_loop_dashboard_to_dict(overview.closed_loop_dashboard),
        "webhook_ops": oncall_webhook_ops_console_to_dict(overview.webhook_ops),
        "replay_jobs": [oncall_webhook_replay_job_to_dict(job) for job in overview.replay_jobs],
        "closed_loop_quality": operations_closed_loop_quality_report_to_dict(overview.closed_loop_quality),
        "closed_loop_acceptance": operations_closed_loop_acceptance_report_to_dict(overview.closed_loop_acceptance),
        "summary": overview.summary,
    }


def render_operations_console_overview_json(overview: OperationsConsoleOverview) -> str:
    return json.dumps(
        {"operations_console_overview": operations_console_overview_to_dict(overview)},
        ensure_ascii=False,
    )


def build_operations_console_view(
    overview: OperationsConsoleOverview,
    actor: str,
    roles: list[str] | set[str] | tuple[str, ...] | None = None,
    department: str | None = None,
    permission_policy: PermissionPolicy | None = None,
    audit_sink: AuditSink | None = None,
    generated_at: str | None = None,
) -> OperationsConsoleView:
    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    role_list = sorted({str(role) for role in roles or [] if str(role).strip()})
    action_names = [
        "view_operations_console",
        "create_replay_job",
        "execute_replay_job",
        "run_operations_schedule",
        "publish_closed_loop_schema",
        "update_governance_policy",
        "manage_compensation_task",
        "execute_compensation_task",
    ]
    permissions: dict[str, OperationsActionAuthorization] = {}
    for action in action_names:
        permissions[action] = authorize_operations_action(
            action,
            user_id=actor,
            permission_policy=permission_policy,
            department=department,
            roles=role_list,
            audit_sink=audit_sink if action == "view_operations_console" else None,
            payload={"source": "operations_console_view"},
        )
    can_view = permissions["view_operations_console"].allowed
    visible_sections = ["summary"] if can_view else []
    if can_view:
        visible_sections.extend(["closed_loop", "webhook_ops", "replay_jobs", "quality"])
    action_defs = [
        ("create_replay_job", "Create replay job", "Create a dead-letter replay job from retryable webhook events."),
        ("execute_replay_job", "Execute replay jobs", "Run pending replay jobs and write back results."),
        ("run_operations_schedule", "Run scheduler", "Claim and run due persisted operations schedule tasks."),
        ("publish_closed_loop_schema", "Publish BI contract", "Publish closed-loop schema and OpenAPI contract."),
        ("update_governance_policy", "Update governance policy", "Change recovery governance or RBAC policy."),
        ("manage_compensation_task", "Manage compensation tasks", "Close compensation tasks after manual verification."),
        ("execute_compensation_task", "Execute compensation tasks", "Run governed compensation task execution batches."),
    ]
    actions = [
        {
            "action": action,
            "label": label,
            "description": description,
            "allowed": permissions[action].allowed,
            "status": permissions[action].decision.status,
            "reasons": permissions[action].decision.reasons,
        }
        for action, label, description in action_defs
    ]
    read_only = not any(item["allowed"] for item in actions)
    return OperationsConsoleView(
        generated_at=generated_at,
        actor=actor,
        department=department,
        roles=role_list,
        permissions=permissions,
        overview=overview,
        visible_sections=visible_sections,
        actions=actions,
        read_only=read_only,
    )


def operations_console_view_to_dict(view: OperationsConsoleView) -> dict[str, Any]:
    return {
        "generated_at": view.generated_at,
        "actor": view.actor,
        "department": view.department,
        "roles": view.roles,
        "permissions": {
            action: operations_action_authorization_to_dict(authorization)
            for action, authorization in view.permissions.items()
        },
        "overview": operations_console_overview_to_dict(view.overview),
        "visible_sections": view.visible_sections,
        "actions": view.actions,
        "read_only": view.read_only,
    }


def render_operations_console_view_json(view: OperationsConsoleView) -> str:
    return json.dumps({"operations_console_view": operations_console_view_to_dict(view)}, ensure_ascii=False)


def render_operations_console_view_html(view: OperationsConsoleView) -> str:
    if "summary" not in view.visible_sections:
        return _html_page(
            "Operations Console",
            [
                "<main>",
                "<h1>Operations Console</h1>",
                f"<p>Access denied for {escape(view.actor)}.</p>",
                "</main>",
            ],
        )
    overview = view.overview
    action_items = "\n".join(
        "<tr>"
        f"<td>{escape(str(item['label']))}</td>"
        f"<td>{'allowed' if item['allowed'] else 'denied'}</td>"
        f"<td>{escape(str(item['status']))}</td>"
        f"<td>{escape('; '.join(str(reason) for reason in item.get('reasons') or []))}</td>"
        "</tr>"
        for item in view.actions
    )
    replay_rows = "\n".join(
        "<tr>"
        f"<td>{escape(job.job_id)}</td>"
        f"<td>{escape(job.status)}</td>"
        f"<td>{escape(job.requested_by)}</td>"
        f"<td>{len(job.event_ids)}</td>"
        "</tr>"
        for job in overview.replay_jobs[:10]
    ) or "<tr><td colspan=\"4\">none</td></tr>"
    sections = [
        "<main>",
        "<h1>Operations Console</h1>",
        f"<p>{escape(overview.summary)}</p>",
        "<section><h2>Actor</h2>",
        f"<p>{escape(view.actor)} | roles={escape(','.join(view.roles) or '-')} | read_only={str(view.read_only).lower()}</p>",
        "</section>",
        "<section><h2>Closed Loop</h2>",
        "<dl>",
        f"<dt>snapshots</dt><dd>{overview.closed_loop_dashboard.snapshot_count}</dd>",
        f"<dt>quality</dt><dd>{str(overview.closed_loop_quality.ok).lower()}</dd>",
        f"<dt>acceptance</dt><dd>{str(overview.closed_loop_acceptance.ok).lower()}</dd>",
        "</dl></section>",
        "<section><h2>Webhook</h2>",
        "<dl>",
        f"<dt>dead letters</dt><dd>{overview.webhook_ops.dead_letters}</dd>",
        f"<dt>retryable</dt><dd>{len(overview.webhook_ops.retryable_event_ids)}</dd>",
        "</dl></section>",
        "<section><h2>Replay Jobs</h2>",
        "<table><thead><tr><th>job</th><th>status</th><th>requested by</th><th>events</th></tr></thead>",
        f"<tbody>{replay_rows}</tbody></table></section>",
        "<section><h2>Actions</h2>",
        "<table><thead><tr><th>action</th><th>permission</th><th>status</th><th>reason</th></tr></thead>",
        f"<tbody>{action_items}</tbody></table></section>",
        "</main>",
    ]
    return _html_page("Operations Console", sections)


def render_operations_closed_loop_contract_validation(result: dict[str, Any]) -> str:
    lines = [
        "Operations closed-loop contract validation:",
        f"- ok: {bool(result.get('ok'))}",
        f"- schema_version: {result.get('schema_version') or '-'}",
        f"- snapshot_count: {result.get('snapshot_count')}",
        f"- checkpoint: {result.get('checkpoint') or '-'}",
    ]
    _append_list_section(lines, "errors", [str(item) for item in result.get("errors") or []])
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


def oncall_ticket_status_from_webhook(payload: dict[str, Any]) -> OnCallTicketStatus:
    data = _extract_oncall_webhook_ticket(payload)
    ticket_id = _first_text(
        data,
        payload,
        names=("ticket_id", "id", "incident_id", "issue_id", "key", "number"),
    )
    if not ticket_id:
        raise ValueError("OnCall webhook payload requires ticket_id, id, incident_id, issue_id, key, or number.")
    status = _first_text(data, payload, names=("status", "state", "resolution")) or "UNKNOWN"
    updated_at = _first_text(
        data,
        payload,
        names=("updated_at", "updatedAt", "timestamp", "time", "occurred_at", "created_at"),
    ) or datetime.now(timezone.utc).isoformat()
    detail = _first_text(
        data,
        payload,
        names=("detail", "message", "summary", "title", "description", "event_type", "event"),
    ) or "webhook status recorded"
    assignee = _assignee_text(
        data.get("assignee")
        or data.get("owner")
        or data.get("assigned_to")
        or data.get("resolver")
        or payload.get("assignee")
        or payload.get("owner")
    )
    return OnCallTicketStatus(
        ticket_id=ticket_id,
        status=status,
        assignee=assignee,
        updated_at=updated_at,
        detail=detail,
    )


def build_oncall_webhook_event(
    payload: dict[str, Any],
    raw_body: str | None = None,
    secret: str | None = None,
    signature: str | None = None,
    seen_event_ids: set[str] | None = None,
    now: str | None = None,
    replay_window_minutes: int = 1440,
    allow_replay: bool = False,
) -> OnCallWebhookEvent:
    received_at = now or datetime.now(timezone.utc).isoformat()
    seen_event_ids = seen_event_ids or set()
    status: OnCallTicketStatus | None = None
    reasons: list[str] = []
    try:
        status = oncall_ticket_status_from_webhook(payload)
        event_id = _oncall_webhook_event_id(payload, status)
    except Exception as exc:
        event_id = _stable_id("WHK", json.dumps(payload, sort_keys=True, ensure_ascii=False))
        signature_valid = verify_oncall_webhook_signature(raw_body or json.dumps(payload, sort_keys=True), secret, signature)
        return OnCallWebhookEvent(
            event_id=event_id,
            ticket_id=None,
            status="DEAD_LETTER",
            received_at=received_at,
            updated_at=None,
            accepted=False,
            duplicate=event_id in seen_event_ids,
            signature_valid=signature_valid,
            replay=False,
            dead_letter=True,
            reason=f"invalid webhook payload: {exc}",
            payload=payload,
        )

    raw = raw_body or json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    signature_valid = verify_oncall_webhook_signature(raw, secret, signature)
    duplicate = event_id in seen_event_ids
    replay = _oncall_webhook_is_replay(status.updated_at, received_at, replay_window_minutes)
    if not signature_valid:
        reasons.append("signature validation failed")
    if duplicate:
        reasons.append("duplicate event id")
    if replay and not allow_replay:
        reasons.append(f"event is outside replay window {replay_window_minutes} minutes")
    accepted = signature_valid and not duplicate and (allow_replay or not replay)
    if accepted:
        reasons.append("event accepted")
    return OnCallWebhookEvent(
        event_id=event_id,
        ticket_id=status.ticket_id,
        status="ACCEPTED" if accepted else ("DUPLICATE" if duplicate else "DEAD_LETTER"),
        received_at=received_at,
        updated_at=status.updated_at,
        accepted=accepted,
        duplicate=duplicate,
        signature_valid=signature_valid,
        replay=replay,
        dead_letter=not accepted and not duplicate,
        reason="; ".join(_dedupe(reasons)),
        payload={
            "webhook": payload,
            "ticket_status": oncall_ticket_status_to_dict(status),
        },
    )


def verify_oncall_webhook_signature(
    raw_body: str,
    secret: str | None = None,
    signature: str | None = None,
) -> bool:
    if not secret:
        return True
    if not signature:
        return False
    digest = hmac.new(secret.encode("utf-8"), raw_body.encode("utf-8"), hashlib.sha256).hexdigest()
    normalized = signature.strip()
    if normalized.startswith("sha256="):
        normalized = normalized[7:]
    return hmac.compare_digest(digest, normalized)


def oncall_webhook_event_to_dict(event: OnCallWebhookEvent) -> dict[str, Any]:
    return {
        "event_id": event.event_id,
        "ticket_id": event.ticket_id,
        "status": event.status,
        "received_at": event.received_at,
        "updated_at": event.updated_at,
        "accepted": event.accepted,
        "duplicate": event.duplicate,
        "signature_valid": event.signature_valid,
        "replay": event.replay,
        "dead_letter": event.dead_letter,
        "reason": event.reason,
        "payload": event.payload,
    }


def oncall_webhook_event_from_dict(payload: dict[str, Any]) -> OnCallWebhookEvent:
    return OnCallWebhookEvent(
        event_id=str(payload["event_id"]),
        ticket_id=str(payload["ticket_id"]) if payload.get("ticket_id") is not None else None,
        status=str(payload.get("status") or "UNKNOWN"),
        received_at=str(payload.get("received_at") or ""),
        updated_at=str(payload["updated_at"]) if payload.get("updated_at") is not None else None,
        accepted=bool(payload.get("accepted", False)),
        duplicate=bool(payload.get("duplicate", False)),
        signature_valid=bool(payload.get("signature_valid", False)),
        replay=bool(payload.get("replay", False)),
        dead_letter=bool(payload.get("dead_letter", False)),
        reason=str(payload.get("reason") or ""),
        payload=dict(payload.get("payload") or {}),
    )


def list_dead_letter_oncall_webhook_events(events: list[OnCallWebhookEvent]) -> list[OnCallWebhookEvent]:
    return [event for event in events if event.dead_letter]


def patch_oncall_webhook_event_payload(
    event: OnCallWebhookEvent,
    patch: dict[str, Any],
    patched_at: str | None = None,
) -> OnCallWebhookEvent:
    patched_at = patched_at or datetime.now(timezone.utc).isoformat()
    patched_payload = _deep_merge_dict(event.payload, patch)
    patch_audit = {
        "status": "PATCHED",
        "patched_at": patched_at,
        "fields": sorted(str(key) for key in patch),
    }
    patched_payload = _deep_merge_dict(patched_payload, {"patch": patch_audit})
    return replace(
        event,
        payload=patched_payload,
        reason=f"{event.reason}; payload patched" if event.reason else "payload patched",
    )


def replay_dead_letter_oncall_webhook_event(
    event: OnCallWebhookEvent,
    replayed_at: str | None = None,
) -> tuple[OnCallWebhookEvent, OnCallTicketStatus | None, OnCallWebhookReplayResult]:
    replayed_at = replayed_at or datetime.now(timezone.utc).isoformat()
    if not event.dead_letter:
        return (
            event,
            None,
            OnCallWebhookReplayResult(
                source_event_id=event.event_id,
                status="SKIPPED",
                accepted=False,
                replayed_at=replayed_at,
                ticket_id=event.ticket_id,
                reason="webhook event is not a dead letter",
            ),
        )

    status_payload = event.payload.get("ticket_status") if isinstance(event.payload, dict) else None
    webhook_payload = event.payload.get("webhook") if isinstance(event.payload, dict) else None
    try:
        status = (
            oncall_ticket_status_from_dict(status_payload)
            if isinstance(status_payload, dict)
            else oncall_ticket_status_from_webhook(dict(webhook_payload or event.payload))
        )
    except Exception as exc:
        replayed = OnCallWebhookEvent(
            event_id=event.event_id,
            ticket_id=event.ticket_id,
            status="DEAD_LETTER",
            received_at=event.received_at,
            updated_at=event.updated_at,
            accepted=False,
            duplicate=event.duplicate,
            signature_valid=event.signature_valid,
            replay=True,
            dead_letter=True,
            reason=f"{event.reason}; replay failed: {exc}" if event.reason else f"replay failed: {exc}",
            payload={**event.payload, "replay": {"status": "FAILED", "replayed_at": replayed_at, "reason": str(exc)}},
        )
        return (
            replayed,
            None,
            OnCallWebhookReplayResult(
                source_event_id=event.event_id,
                status="FAILED",
                accepted=False,
                replayed_at=replayed_at,
                ticket_id=event.ticket_id,
                reason=str(exc),
            ),
        )

    replayed_payload = {
        **event.payload,
        "ticket_status": oncall_ticket_status_to_dict(status),
        "replay": {
            "status": "ACCEPTED",
            "replayed_at": replayed_at,
            "source_event_id": event.event_id,
        },
    }
    replayed = OnCallWebhookEvent(
        event_id=event.event_id,
        ticket_id=status.ticket_id,
        status="REPLAYED",
        received_at=event.received_at,
        updated_at=status.updated_at,
        accepted=True,
        duplicate=event.duplicate,
        signature_valid=event.signature_valid,
        replay=True,
        dead_letter=False,
        reason="dead-letter webhook replay accepted",
        payload=replayed_payload,
    )
    return (
        replayed,
        status,
        OnCallWebhookReplayResult(
            source_event_id=event.event_id,
            status="REPLAYED",
            accepted=True,
            replayed_at=replayed_at,
            ticket_id=status.ticket_id,
            reason="dead-letter webhook replay accepted",
        ),
    )


def replay_dead_letter_oncall_webhook_events(
    events: list[OnCallWebhookEvent],
    replayed_at: str | None = None,
    limit: int | None = None,
    patches: dict[str, dict[str, Any]] | None = None,
) -> tuple[list[OnCallWebhookEvent], list[OnCallTicketStatus], OnCallWebhookReplayBatchResult]:
    replayed_at = replayed_at or datetime.now(timezone.utc).isoformat()
    patches = patches or {}
    candidates = list_dead_letter_oncall_webhook_events(events)
    if limit is not None:
        candidates = candidates[: max(0, int(limit))]

    replayed_events: list[OnCallWebhookEvent] = []
    statuses: list[OnCallTicketStatus] = []
    results: list[OnCallWebhookReplayResult] = []
    for event in candidates:
        patched = patch_oncall_webhook_event_payload(event, patches[event.event_id], patched_at=replayed_at) if event.event_id in patches else event
        replayed_event, status, result = replay_dead_letter_oncall_webhook_event(patched, replayed_at=replayed_at)
        replayed_events.append(replayed_event)
        if status is not None:
            statuses.append(status)
        results.append(result)

    accepted = sum(1 for result in results if result.accepted)
    failed = sum(1 for result in results if result.status == "FAILED")
    skipped = sum(1 for result in results if result.status == "SKIPPED")
    batch = OnCallWebhookReplayBatchResult(
        batch_id=_stable_id("WHB", replayed_at, ",".join(result.source_event_id for result in results)),
        generated_at=replayed_at,
        attempted=len(results),
        accepted=accepted,
        failed=failed,
        skipped=skipped,
        results=results,
    )
    return replayed_events, statuses, batch


def oncall_webhook_replay_result_to_dict(result: OnCallWebhookReplayResult) -> dict[str, Any]:
    return {
        "source_event_id": result.source_event_id,
        "status": result.status,
        "accepted": result.accepted,
        "replayed_at": result.replayed_at,
        "ticket_id": result.ticket_id,
        "reason": result.reason,
    }


def oncall_webhook_replay_result_from_dict(payload: dict[str, Any]) -> OnCallWebhookReplayResult:
    return OnCallWebhookReplayResult(
        source_event_id=str(payload["source_event_id"]),
        status=str(payload.get("status") or "UNKNOWN"),
        accepted=bool(payload.get("accepted", False)),
        replayed_at=str(payload.get("replayed_at") or ""),
        ticket_id=str(payload["ticket_id"]) if payload.get("ticket_id") is not None else None,
        reason=str(payload.get("reason") or ""),
    )


def oncall_webhook_replay_batch_result_to_dict(result: OnCallWebhookReplayBatchResult) -> dict[str, Any]:
    return {
        "batch_id": result.batch_id,
        "generated_at": result.generated_at,
        "attempted": result.attempted,
        "accepted": result.accepted,
        "failed": result.failed,
        "skipped": result.skipped,
        "results": [oncall_webhook_replay_result_to_dict(item) for item in result.results],
    }


def oncall_webhook_replay_batch_result_from_dict(payload: dict[str, Any]) -> OnCallWebhookReplayBatchResult:
    return OnCallWebhookReplayBatchResult(
        batch_id=str(payload["batch_id"]),
        generated_at=str(payload.get("generated_at") or ""),
        attempted=int(payload.get("attempted") or 0),
        accepted=int(payload.get("accepted") or 0),
        failed=int(payload.get("failed") or 0),
        skipped=int(payload.get("skipped") or 0),
        results=[oncall_webhook_replay_result_from_dict(item) for item in payload.get("results") or []],
    )


def build_oncall_webhook_replay_job(
    event_ids: list[str],
    requested_by: str = "operator",
    patch_template_id: str | None = None,
    batch_result: OnCallWebhookReplayBatchResult | None = None,
    created_at: str | None = None,
    status: str | None = None,
    audit: dict[str, Any] | None = None,
) -> OnCallWebhookReplayJob:
    created_at = created_at or datetime.now(timezone.utc).isoformat()
    normalized_event_ids = [str(item) for item in event_ids]
    if status is None:
        if batch_result is None:
            status = "PENDING"
        elif batch_result.failed:
            status = "FAILED"
        elif batch_result.accepted:
            status = "COMPLETED"
        else:
            status = "SKIPPED"
    return OnCallWebhookReplayJob(
        job_id=_stable_id("WHJ", created_at, requested_by, ",".join(normalized_event_ids), patch_template_id or ""),
        created_at=created_at,
        status=status,
        requested_by=requested_by,
        event_ids=normalized_event_ids,
        patch_template_id=patch_template_id,
        batch_result=batch_result,
        audit=dict(audit or {}),
    )


def oncall_webhook_replay_job_to_dict(job: OnCallWebhookReplayJob) -> dict[str, Any]:
    return {
        "job_id": job.job_id,
        "created_at": job.created_at,
        "status": job.status,
        "requested_by": job.requested_by,
        "event_ids": job.event_ids,
        "patch_template_id": job.patch_template_id,
        "batch_result": (
            oncall_webhook_replay_batch_result_to_dict(job.batch_result)
            if job.batch_result is not None
            else None
        ),
        "audit": job.audit,
    }


def oncall_webhook_replay_job_from_dict(payload: dict[str, Any]) -> OnCallWebhookReplayJob:
    batch_payload = payload.get("batch_result")
    return OnCallWebhookReplayJob(
        job_id=str(payload["job_id"]),
        created_at=str(payload.get("created_at") or ""),
        status=str(payload.get("status") or "UNKNOWN"),
        requested_by=str(payload.get("requested_by") or "operator"),
        event_ids=[str(item) for item in payload.get("event_ids") or []],
        patch_template_id=(
            str(payload["patch_template_id"]) if payload.get("patch_template_id") is not None else None
        ),
        batch_result=(
            oncall_webhook_replay_batch_result_from_dict(batch_payload)
            if isinstance(batch_payload, dict)
            else None
        ),
        audit=dict(payload.get("audit") or {}),
    )


def render_oncall_webhook_replay_jobs(jobs: list[OnCallWebhookReplayJob]) -> str:
    lines = ["OnCall webhook replay jobs:"]
    if not jobs:
        lines.append("- none")
        return "\n".join(lines)
    for job in jobs:
        lines.append(
            f"- {job.job_id}: status={job.status} requested_by={job.requested_by} "
            f"events={len(job.event_ids)} created_at={job.created_at}"
        )
        if job.patch_template_id:
            lines.append(f"  patch_template_id: {job.patch_template_id}")
        if job.batch_result is not None:
            lines.append(
                f"  batch={job.batch_result.batch_id} attempted={job.batch_result.attempted} "
                f"accepted={job.batch_result.accepted} failed={job.batch_result.failed}"
            )
    return "\n".join(lines)


def render_oncall_webhook_replay_jobs_json(jobs: list[OnCallWebhookReplayJob]) -> str:
    return json.dumps(
        {"oncall_webhook_replay_jobs": [oncall_webhook_replay_job_to_dict(job) for job in jobs]},
        ensure_ascii=False,
    )


def render_oncall_webhook_replay_result(result: OnCallWebhookReplayResult) -> str:
    return "\n".join(
        [
            "OnCall webhook replay:",
            f"- source_event_id: {result.source_event_id}",
            f"- status: {result.status}",
            f"- accepted: {result.accepted}",
            f"- ticket_id: {result.ticket_id or '-'}",
            f"- replayed_at: {result.replayed_at}",
            f"- reason: {result.reason or '-'}",
        ]
    )


def render_oncall_webhook_replay_batch_result(result: OnCallWebhookReplayBatchResult) -> str:
    lines = [
        "OnCall webhook replay batch:",
        f"- batch_id: {result.batch_id}",
        f"- generated_at: {result.generated_at}",
        f"- attempted: {result.attempted}",
        f"- accepted: {result.accepted}",
        f"- failed: {result.failed}",
        f"- skipped: {result.skipped}",
    ]
    if not result.results:
        lines.append("- results: none")
    else:
        lines.append("- results:")
        for item in result.results:
            lines.append(
                f"  - {item.source_event_id}: status={item.status} accepted={item.accepted} "
                f"ticket={item.ticket_id or '-'}"
            )
    return "\n".join(lines)


def render_oncall_webhook_replay_audit_json(result: OnCallWebhookReplayBatchResult) -> str:
    return json.dumps(
        {"oncall_webhook_replay_audit": oncall_webhook_replay_batch_result_to_dict(result)},
        ensure_ascii=False,
    )


def build_oncall_webhook_ops_console(
    events: list[OnCallWebhookEvent],
    generated_at: str | None = None,
) -> OnCallWebhookOpsConsole:
    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    dead_letters = list_dead_letter_oncall_webhook_events(events)
    replayed = [event for event in events if event.status == "REPLAYED" or event.replay and event.accepted]
    failed_replays = [
        event
        for event in events
        if isinstance(event.payload, dict)
        and isinstance(event.payload.get("replay"), dict)
        and event.payload["replay"].get("status") == "FAILED"
    ]
    failure_reasons: Counter[str] = Counter()
    for event in dead_letters + failed_replays:
        failure_reasons[_webhook_failure_reason_key(event.reason)] += 1
    templates = _default_oncall_webhook_patch_templates(dead_letters)
    return OnCallWebhookOpsConsole(
        generated_at=generated_at,
        total_events=len(events),
        dead_letters=len(dead_letters),
        replayed=len(replayed),
        failed_replays=len(failed_replays),
        retryable_event_ids=[event.event_id for event in dead_letters],
        failure_reasons=dict(failure_reasons),
        patch_templates=templates,
    )


def oncall_webhook_patch_template_to_dict(template: OnCallWebhookPatchTemplate) -> dict[str, Any]:
    return {
        "template_id": template.template_id,
        "title": template.title,
        "match_reason": template.match_reason,
        "patch": template.patch,
    }


def oncall_webhook_ops_console_to_dict(console: OnCallWebhookOpsConsole) -> dict[str, Any]:
    return {
        "generated_at": console.generated_at,
        "total_events": console.total_events,
        "dead_letters": console.dead_letters,
        "replayed": console.replayed,
        "failed_replays": console.failed_replays,
        "retryable_event_ids": console.retryable_event_ids,
        "failure_reasons": console.failure_reasons,
        "patch_templates": [
            oncall_webhook_patch_template_to_dict(template) for template in console.patch_templates
        ],
    }


def render_oncall_webhook_ops_console(console: OnCallWebhookOpsConsole) -> str:
    lines = [
        "OnCall webhook operations console:",
        f"- generated_at: {console.generated_at}",
        f"- total_events: {console.total_events}",
        f"- dead_letters: {console.dead_letters}",
        f"- replayed: {console.replayed}",
        f"- failed_replays: {console.failed_replays}",
    ]
    _append_list_section(lines, "retryable_event_ids", console.retryable_event_ids)
    _append_count_section(lines, "failure_reasons", console.failure_reasons)
    lines.append("- patch_templates:")
    if not console.patch_templates:
        lines.append("  - none")
    else:
        for template in console.patch_templates:
            lines.append(f"  - {template.template_id}: {template.title}")
    return "\n".join(lines)


def render_oncall_webhook_ops_console_json(console: OnCallWebhookOpsConsole) -> str:
    return json.dumps(
        {"oncall_webhook_ops_console": oncall_webhook_ops_console_to_dict(console)},
        ensure_ascii=False,
    )


def render_oncall_webhook_event(event: OnCallWebhookEvent) -> str:
    return "\n".join(
        [
            "OnCall webhook event:",
            f"- event_id: {event.event_id}",
            f"- ticket_id: {event.ticket_id or '-'}",
            f"- status: {event.status}",
            f"- accepted: {event.accepted}",
            f"- duplicate: {event.duplicate}",
            f"- signature_valid: {event.signature_valid}",
            f"- replay: {event.replay}",
            f"- dead_letter: {event.dead_letter}",
            f"- received_at: {event.received_at}",
            f"- reason: {event.reason or '-'}",
        ]
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


def _closed_loop_dashboard_trends(
    latest: OperationsClosedLoopSnapshot | None,
    previous: OperationsClosedLoopSnapshot | None,
) -> list[OperationsTrendMetric]:
    if latest is None:
        return []
    latest_metrics = _closed_loop_report_metrics(latest.report)
    previous_metrics = _closed_loop_report_metrics(previous.report) if previous is not None else {}
    return [
        _operations_trend_metric(name, latest_metrics.get(name, 0), previous_metrics.get(name, 0))
        for name in sorted(latest_metrics)
    ]


def _closed_loop_report_metrics(report: OperationsClosedLoopReport) -> dict[str, int]:
    return {
        "action_items_closed": report.action_items_closed,
        "action_items_open": report.action_items_open,
        "action_items_overdue": report.action_items_overdue,
        "action_items_total": report.action_items_total,
        "closure_rate": int(round(report.closure_rate)),
        "knowledge_entries": report.knowledge_entries,
        "trend_alerts": report.trend_alerts,
    }


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


def _parse_iso_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return datetime.fromtimestamp(0, timezone.utc)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _operations_schedule_cadence_seconds(cadence: str) -> int:
    normalized = cadence.strip().lower().replace("-", "_")
    fixed = {
        "manual": 3600,
        "once": 3600,
        "hourly": 3600,
        "daily": 86400,
        "weekly": 604800,
        "every_5_minutes": 300,
        "every_15_minutes": 900,
        "every_30_minutes": 1800,
    }
    if normalized in fixed:
        return fixed[normalized]
    if normalized.startswith("every_"):
        parts = normalized.removeprefix("every_").split("_", 1)
        if len(parts) == 2:
            try:
                amount = max(1, int(parts[0]))
            except ValueError:
                return 3600
            unit = parts[1].rstrip("s")
            if unit == "second":
                return amount
            if unit == "minute":
                return amount * 60
            if unit == "hour":
                return amount * 3600
            if unit == "day":
                return amount * 86400
    return 3600


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


def _html_page(title: str, body: list[str]) -> str:
    return "\n".join(
        [
            "<!doctype html>",
            "<html lang=\"en\">",
            "<head>",
            "<meta charset=\"utf-8\">",
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">",
            f"<title>{escape(title)}</title>",
            "<style>",
            "body{font-family:Arial,sans-serif;margin:0;background:#f7f8fa;color:#1f2933}",
            "main{max-width:1120px;margin:0 auto;padding:24px}",
            "section{background:#fff;border:1px solid #d9dee7;border-radius:6px;margin:16px 0;padding:16px}",
            "h1{font-size:28px;margin:0 0 8px}h2{font-size:18px;margin:0 0 12px}",
            "table{border-collapse:collapse;width:100%;font-size:14px}th,td{border-bottom:1px solid #e5e8ef;padding:8px;text-align:left}",
            "dl{display:grid;grid-template-columns:160px 1fr;gap:8px;margin:0}dt{font-weight:bold}",
            "</style>",
            "</head>",
            "<body>",
            *body,
            "</body>",
            "</html>",
        ]
    )


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


def _matching_oncall_status(
    item: OperationsActionItem,
    status_map: dict[str, OnCallTicketStatus],
) -> OnCallTicketStatus | None:
    candidates = [item.source_id, item.title, item.action_id, *item.evidence]
    lowered_candidates = [candidate.lower() for candidate in candidates if candidate]
    for status in status_map.values():
        ticket_key = status.ticket_id.lower()
        if any(ticket_key == candidate or ticket_key in candidate or candidate in ticket_key for candidate in lowered_candidates):
            return status
    return None


def _recovery_compensation_targets(context: TravelContext, normalized_state: str) -> list[str]:
    targets: list[str] = []
    if context.transport_order is not None:
        targets.append("transport_order")
    if context.order is not None:
        targets.append("hotel_order")
    if context.inventory_lock is not None:
        targets.append("hotel_inventory")
    if context.approval is not None and _normalize_status_value(context.approval.status) not in {
        "REJECTED",
        "DENIED",
        "REFUSED",
        "CANCELLED",
        "CANCELED",
    }:
        targets.append("approval")
    if normalized_state == "ORDER_FAILED" and not targets:
        targets.append("order_failure_state")
    return targets


def _failed_recovery_compensations(context: TravelContext) -> list[str]:
    failed: list[str] = []
    for name, result in (
        ("transport_order_cancellation", context.transport_order_cancellation),
        ("order_cancellation", context.order_cancellation),
        ("inventory_release", context.inventory_release),
        ("approval_cancellation", context.approval_cancellation),
    ):
        if result is None:
            continue
        if _normalize_status_value(result.status) in {"FAILED", "ERROR", "REJECTED", "TIMEOUT"}:
            failed.append(name)
    return failed


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


def _deep_merge_dict(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge_dict(dict(merged[key]), value)
        else:
            merged[key] = value
    return merged


def _recovery_strategy_execution_count(context: TravelContext) -> int:
    count = 0
    for record in context.recovery_records:
        execution = record.payload.get("strategy_execution") if isinstance(record.payload, dict) else None
        if isinstance(execution, dict) and not execution.get("idempotent"):
            count += 1
    return count


def _default_oncall_webhook_patch_templates(
    dead_letters: list[OnCallWebhookEvent],
) -> list[OnCallWebhookPatchTemplate]:
    templates: list[OnCallWebhookPatchTemplate] = []
    reasons = " ".join(event.reason.lower() for event in dead_letters)
    if "ticket_id" in reasons or "requires" in reasons:
        templates.append(
            OnCallWebhookPatchTemplate(
                template_id="missing_ticket_status",
                title="补齐 ticket_status",
                match_reason="payload missing ticket id or normalized ticket status",
                patch={
                    "ticket_status": {
                        "ticket_id": "<ticket-id>",
                        "status": "CLOSED",
                        "assignee": "ops",
                        "updated_at": "<iso-time>",
                        "detail": "patched before replay",
                    }
                },
            )
        )
    if "signature" in reasons:
        templates.append(
            OnCallWebhookPatchTemplate(
                template_id="signature_failed_replay",
                title="保留原 payload 并补充 replay 说明",
                match_reason="signature validation failed",
                patch={"replay_note": "signature checked manually before replay"},
            )
        )
    if not templates and dead_letters:
        templates.append(
            OnCallWebhookPatchTemplate(
                template_id="generic_webhook_patch",
                title="通用 webhook payload 修正",
                match_reason="dead-letter payload requires operator correction",
                patch={"ticket_status": {"ticket_id": "<ticket-id>", "status": "<status>", "updated_at": "<iso-time>"}},
            )
        )
    return templates


def _webhook_failure_reason_key(reason: str) -> str:
    normalized = reason.strip().lower()
    if not normalized:
        return "unknown"
    if "signature" in normalized:
        return "signature_validation_failed"
    if "ticket_id" in normalized or "requires" in normalized:
        return "missing_ticket_id"
    if "replay failed" in normalized:
        return "replay_failed"
    return normalized[:80]


def _openapi_query_param(name: str, value_type: str = "string") -> dict[str, Any]:
    return {
        "name": name,
        "in": "query",
        "required": False,
        "schema": {"type": value_type},
    }


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
            settings.closed_loop_api_url,
            settings.closed_loop_schema_registry_url,
            settings.recovery_governance_policy_api_url,
            settings.session_store_api_url,
            settings.session_db_path,
        ]
    ):
        return "production-like"
    return "mock"


def _normalize_alert(alert: dict[str, Any]) -> dict[str, Any]:
    normalized = {
        "alert_type": str(alert.get("alert_type") or "unknown"),
        "severity": str(alert.get("severity") or "warning"),
        "message": str(alert.get("message") or ""),
        "value": int(alert.get("value") or 0),
    }
    for key, value in alert.items():
        if key in normalized:
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            normalized[str(key)] = value
        elif isinstance(value, (list, dict)):
            normalized[str(key)] = value
        else:
            normalized[str(key)] = str(value)
    return normalized


def _extract_oncall_webhook_ticket(payload: dict[str, Any]) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = [payload]
    for key in ("ticket", "data", "incident", "issue", "alert"):
        value = payload.get(key)
        if isinstance(value, dict):
            candidates.append(value)
    event = payload.get("event")
    if isinstance(event, dict):
        candidates.append(event)
        for key in ("ticket", "data", "incident", "issue", "alert"):
            value = event.get(key)
            if isinstance(value, dict):
                candidates.append(value)
    for candidate in candidates:
        if _first_text(candidate, names=("ticket_id", "id", "incident_id", "issue_id", "key", "number")):
            return candidate
    return payload


def _oncall_webhook_event_id(payload: dict[str, Any], status: OnCallTicketStatus) -> str:
    data = _extract_oncall_webhook_ticket(payload)
    event_id = _first_text(
        payload,
        data,
        names=("event_id", "webhook_id", "delivery_id", "deliveryId", "request_id", "uuid"),
    )
    if event_id:
        return event_id
    return _stable_id("WHK", status.ticket_id, status.status, status.updated_at, status.detail)


def _oncall_webhook_is_replay(updated_at: str, received_at: str, replay_window_minutes: int) -> bool:
    if replay_window_minutes < 0:
        return False
    updated_ts = _timestamp_sort_key(updated_at)
    received_ts = _timestamp_sort_key(received_at)
    if updated_ts <= 0.0 or received_ts <= 0.0:
        return False
    return (received_ts - updated_ts) > replay_window_minutes * 60


def _first_text(*payloads: dict[str, Any], names: tuple[str, ...]) -> str | None:
    for payload in payloads:
        for name in names:
            value = payload.get(name)
            if value is None:
                continue
            if isinstance(value, dict):
                text = _assignee_text(value)
            else:
                text = str(value).strip()
            if text:
                return text
    return None


def _assignee_text(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, dict):
        for key in ("name", "username", "user", "id", "email"):
            text = str(value.get(key) or "").strip()
            if text:
                return text
        return None
    text = str(value).strip()
    return text or None


def _normalize_status_value(status: object) -> str:
    return str(status or "").strip().upper()


def _metric_label(value: object) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


class _FailingHttpClient:
    def post_json(self, url: str, payload: dict[str, Any], token: str | None = None) -> dict[str, Any]:
        del url, payload, token
        raise RuntimeError("simulated remote outage")
