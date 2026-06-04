from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import Callable
from urllib.parse import parse_qs, urlsplit

from .agent import build_default_agent
from .acceptance import render_integration_acceptance_report, run_integration_acceptance_report
from .config import IntegrationSettings
from .data_governance import AuditSink, HttpAuditSink, build_audit_sink
from .evaluation import render_evaluation_report, run_evaluation_suite
from .governance import render_release_readiness_report, run_release_readiness_report
from .models import DeadLetterCalendarSync, DeadLetterNotification, TravelContext, TravelRequest, WorkerRunRecord
from .observability import build_otlp_payloads, export_otlp_http
from .operations import (
    OnCallWebhookReplayBatchResult,
    OnCallWebhookReplayJobExecution,
    OnCallTicketStatus,
    OperationsClosedLoopSchemaPublishResult,
    advance_operations_scheduled_task,
    authorize_operations_action,
    build_alert_route_rules,
    build_operations_dashboard,
    build_operations_dashboard_snapshot,
    build_operations_dashboard_trend_report,
    build_operations_action_sla_policy,
    build_operations_closed_loop_report,
    build_operations_closed_loop_snapshot,
    build_operations_closed_loop_dashboard,
    build_operations_closed_loop_acceptance_report,
    build_operations_closed_loop_checkpoint_plan,
    build_operations_closed_loop_contract_matrix,
    build_operations_closed_loop_json_schema,
    build_operations_closed_loop_openapi_spec,
    build_operations_knowledge_entries,
    build_operations_scheduled_tasks,
    build_operations_scheduler_health_report,
    build_operations_console_overview,
    build_operations_console_view,
    build_operations_console_action_audit,
    build_operations_audit_timeline,
    build_operations_audit_sink_delivery,
    build_operations_console_action_audit_event,
    build_operations_compensation_tasks,
    build_operations_governance_policy_change,
    build_operations_multidimensional_view,
    build_operations_postmortem_report,
    build_operations_trend_alert_rules,
    build_oncall_webhook_event,
    build_recovery_strategy_metrics,
    RecoveryGovernancePolicy,
    collect_recovery_approval_receipts,
    build_postmortem_action_items,
    build_trend_alert_action_items,
    close_operations_action_item,
    close_operations_compensation_task,
    evaluate_operations_action_sla,
    evaluate_operations_closed_loop_quality,
    evaluate_operations_drill_gate,
    evaluate_operations_trend_alerts,
    evaluate_recovery_approval_sla,
    execute_operations_compensation_tasks,
    execute_oncall_webhook_replay_job,
    export_recovery_approval_receipt_http,
    export_operations_closed_loop_report_http,
    export_operations_alerts_http,
    fetch_recovery_governance_policy_http,
    fetch_oncall_ticket_status_http,
    open_oncall_ticket_http,
    oncall_ticket_status_from_dict,
    oncall_ticket_status_from_webhook,
    oncall_ticket_status_to_dict,
    oncall_webhook_replay_job_execution_to_dict,
    oncall_webhook_replay_job_from_dict,
    oncall_webhook_replay_job_to_dict,
    open_recovery_failure_ticket_http,
    oncall_webhook_event_from_dict,
    oncall_webhook_event_to_dict,
    list_dead_letter_oncall_webhook_events,
    patch_oncall_webhook_event_payload,
    operations_action_item_from_dict,
    operations_action_item_to_dict,
    operations_closed_loop_snapshot_from_dict,
    operations_closed_loop_snapshot_to_dict,
    operations_dashboard_snapshot_from_dict,
    operations_dashboard_snapshot_to_dict,
    operations_governance_policy_change_from_dict,
    operations_governance_policy_change_to_dict,
    operations_console_action_audit_from_dict,
    operations_console_action_audit_to_dict,
    operations_audit_sink_delivery_from_dict,
    operations_audit_sink_delivery_to_dict,
    operations_compensation_task_from_dict,
    operations_compensation_task_to_dict,
    operations_knowledge_entry_from_dict,
    operations_knowledge_entry_to_dict,
    operations_action_authorization_to_dict,
    operations_scheduled_task_from_dict,
    operations_scheduled_task_to_dict,
    operations_scheduler_run_report_from_dict,
    operations_scheduler_run_report_to_dict,
    operations_trend_alert_from_dict,
    operations_trend_alert_to_dict,
    recovery_governance_policy_from_json,
    recovery_governance_policy_from_dict,
    build_recovery_approval_sla_policy,
    build_recovery_governance_policy_audit,
    apply_operations_governance_policy_change,
    approve_operations_governance_policy_change,
    rollback_operations_governance_policy_change,
    recovery_strategy_execution_result_from_dict,
    publish_operations_closed_loop_schema_http,
    render_operations_alert_export_result,
    render_operations_alerts,
    render_operations_alerts_json,
    render_operations_alerts_prometheus,
    build_operations_drill_report,
    build_operations_runbook,
    render_alert_route_rules,
    render_alert_route_rules_json,
    render_operations_action_items,
    render_operations_action_sla_notifications,
    render_operations_action_sla_report,
    render_operations_action_status_sync_report,
    render_operations_closed_loop_export_result,
    render_operations_closed_loop_report,
    render_operations_closed_loop_dashboard_json,
    render_operations_closed_loop_report_json,
    render_operations_closed_loop_report_prometheus,
    render_operations_closed_loop_snapshot,
    render_operations_closed_loop_snapshots,
    render_operations_closed_loop_contract_matrix_json,
    render_operations_closed_loop_json_schema,
    render_operations_closed_loop_openapi_spec,
    render_operations_closed_loop_contract_validation,
    render_operations_closed_loop_acceptance_report,
    render_operations_closed_loop_checkpoint_plan,
    render_operations_closed_loop_quality_report,
    render_operations_closed_loop_schema_publish_result,
    render_operations_action_authorization,
    render_operations_console_overview_json,
    render_operations_console_view_html,
    render_operations_console_view_json,
    render_operations_audit_timeline_json,
    render_operations_audit_sink_deliveries_json,
    render_operations_audit_sink_replay_report_json,
    render_operations_compensation_task_board_json,
    render_operations_compensation_task_execution_report_json,
    render_operations_scheduled_tasks,
    render_operations_scheduler_health_report,
    render_operations_scheduler_run_report,
    render_oncall_webhook_replay_audit_json,
    render_oncall_webhook_replay_batch_result,
    render_oncall_webhook_replay_job_execution,
    render_oncall_webhook_replay_result,
    build_oncall_webhook_replay_job,
    build_oncall_webhook_ops_console,
    render_oncall_webhook_ops_console,
    render_oncall_webhook_ops_console_json,
    render_oncall_webhook_replay_jobs,
    render_oncall_webhook_replay_jobs_json,
    render_operations_dashboard_snapshots,
    render_operations_dashboard_trend_report,
    render_operations_knowledge_entries,
    render_operations_knowledge_search_report,
    render_operations_multidimensional_view,
    render_operations_postmortem_report,
    render_operations_trend_alerts,
    render_operations_trend_alerts_json,
    retry_operations_audit_sink_deliveries,
    search_operations_knowledge,
    sync_operations_action_items_from_oncall,
    render_oncall_ticket_status,
    render_oncall_webhook_event,
    render_oncall_ticket_result,
    render_operations_dashboard,
    render_operations_drill_gate_result,
    render_operations_drill_report,
    render_operations_runbook,
    render_recovery_approval_export_result,
    render_recovery_approval_sla_report,
    render_recovery_governance_policy_audit,
    render_recovery_governance_policy_fetch_result,
    render_recovery_strategy_metrics_prometheus,
    run_operations_scheduled_tasks,
    replay_dead_letter_oncall_webhook_event,
    replay_dead_letter_oncall_webhook_events,
)
from .integrations import JsonHttpClient
from .permissions import PermissionPolicy, evaluate_permission, render_permission_decision
from .release_gate import evaluate_release_gate, render_release_gate_result
from .release_control import RolloutPolicy, evaluate_rollout, render_rollout_decision
from .smoke import render_smoke_probe_report, run_smoke_probes
from .storage import SessionStore, StorageHealth
from .worker import WorkflowLoopResult, WorkflowRunResult, WorkflowWorker


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the travel Agent MVP.")
    parser.add_argument("--user", default="u-demo", help="User id.")
    parser.add_argument("--origin", help="Origin city.")
    parser.add_argument("--destination", help="Destination city.")
    parser.add_argument("--start", help="Start date, yyyy-mm-dd.")
    parser.add_argument("--end", help="End date, yyyy-mm-dd.")
    parser.add_argument("--venue", help="Meeting venue or target location.")
    parser.add_argument("--purpose", help="Business trip purpose.")
    parser.add_argument("--budget", type=int, default=None, help="Hotel budget per night.")
    parser.add_argument(
        "--preference",
        action="append",
        default=[],
        help="Hotel preference. Can be repeated.",
    )
    parser.add_argument(
        "--hotel-id",
        default=None,
        help="Hotel id to confirm. Defaults to the top recommendation when --auto-confirm is set.",
    )
    parser.add_argument(
        "--transport-id",
        default=None,
        help="Transport id to confirm. Defaults to the top recommendation when --auto-confirm is set.",
    )
    parser.add_argument(
        "--auto-confirm",
        action="store_true",
        help="Confirm the selected hotel and create an approval record.",
    )
    parser.add_argument(
        "--auto-book",
        action="store_true",
        help="Confirm, refresh approval status, lock inventory, and create an order.",
    )
    parser.add_argument(
        "--session-db",
        default=None,
        help="SQLite session store path. Overrides TRAVEL_SESSION_DB_PATH.",
    )
    parser.add_argument(
        "--cancel-session",
        default=None,
        help="Load a persisted session id and run cancellation compensation.",
    )
    parser.add_argument(
        "--cancel-after-book",
        action="store_true",
        help="Run cancellation compensation after the current flow.",
    )
    parser.add_argument(
        "--cancel-reason",
        default="user_cancelled",
        help="Cancellation reason passed to compensation tools.",
    )
    parser.add_argument(
        "--replan-session",
        default=None,
        help="Load a persisted exception session, run compensations, and regenerate hotel options.",
    )
    parser.add_argument(
        "--replan-reason",
        default="operator_replan",
        help="Recovery reason passed to approval/order/inventory compensations.",
    )
    parser.add_argument(
        "--execute-recovery-strategy-session",
        default=None,
        help="Load a persisted exception session and execute the selected recovery strategy.",
    )
    parser.add_argument(
        "--enforce-recovery-gate",
        action="store_true",
        help="Stop automated replan when the recovery strategy gate requires approval.",
    )
    parser.add_argument(
        "--recovery-approval-override",
        action="store_true",
        help="Treat required recovery approvals as provided when executing a recovery strategy.",
    )
    parser.add_argument(
        "--recovery-approved-by",
        default=None,
        help="Operator or system principal recorded in the recovery approval receipt.",
    )
    parser.add_argument(
        "--recovery-approval-reason",
        default=None,
        help="Approval receipt reason when --recovery-approval-override is used.",
    )
    parser.add_argument(
        "--recovery-governance-policy-json",
        default=None,
        help="Recovery governance policy JSON with allowed_actions, blocked_actions, and max_executions_per_session.",
    )
    parser.add_argument(
        "--fetch-recovery-governance-policy",
        action="store_true",
        help="Fetch recovery governance policy from a remote config-center endpoint.",
    )
    parser.add_argument(
        "--recovery-governance-policy-endpoint",
        default=None,
        help="Remote config-center endpoint for recovery governance policy. Defaults to TRAVEL_RECOVERY_GOVERNANCE_POLICY_API_URL.",
    )
    parser.add_argument(
        "--audit-recovery-governance-policy",
        action="store_true",
        help="Compare local and remote recovery governance policies and render a policy-change audit.",
    )
    parser.add_argument(
        "--recovery-governance-policy-changed-by",
        default="travel-ops",
        help="Principal recorded in --audit-recovery-governance-policy.",
    )
    parser.add_argument(
        "--recovery-approval-sla",
        action="store_true",
        help="Evaluate recovery approval receipt SLA and approver permissions.",
    )
    parser.add_argument(
        "--recovery-approval-sla-policy-json",
        default=None,
        help="Recovery approval SLA policy JSON with max_pending_hours and approver allow rules.",
    )
    parser.add_argument(
        "--recovery-approval-sla-now",
        default=None,
        help="Optional ISO timestamp used as current time for --recovery-approval-sla.",
    )
    parser.add_argument(
        "--export-recovery-approval-receipts",
        action="store_true",
        help="Export persisted recovery approval receipts to the configured audit/OA endpoint.",
    )
    parser.add_argument(
        "--recovery-approval-endpoint",
        default=None,
        help="Endpoint for --export-recovery-approval-receipts. Defaults to TRAVEL_RECOVERY_APPROVAL_API_URL.",
    )
    parser.add_argument(
        "--open-recovery-failure-ticket-session",
        default=None,
        help="Open an OnCall ticket for the latest failed or blocked recovery execution in a session.",
    )
    parser.add_argument(
        "--reselect-hotel-session",
        default=None,
        help="Load a replanned session and create a new approval for the selected hotel.",
    )
    parser.add_argument(
        "--accept-price-change",
        action="store_true",
        help="Accept a pending price change on a persisted session and continue booking.",
    )
    parser.add_argument(
        "--reject-price-change",
        action="store_true",
        help="Reject a pending price change on a persisted session and cancel the trip.",
    )
    parser.add_argument(
        "--refresh-order-session",
        default=None,
        help="Load a persisted session id and refresh order status.",
    )
    parser.add_argument(
        "--estimate-refund-session",
        default=None,
        help="Load a persisted session id and estimate hotel/transport refund before cancellation.",
    )
    parser.add_argument(
        "--change-session",
        default=None,
        help="Load a persisted completed session id and change transport and/or hotel order.",
    )
    parser.add_argument(
        "--new-depart-at",
        default=None,
        help="New transport departure time for --change-session.",
    )
    parser.add_argument(
        "--new-check-in",
        default=None,
        help="New hotel check-in date yyyy-mm-dd for --change-session.",
    )
    parser.add_argument(
        "--new-check-out",
        default=None,
        help="New hotel check-out date yyyy-mm-dd for --change-session.",
    )
    parser.add_argument(
        "--change-reason",
        default="user_change_requested",
        help="Change reason passed to refund estimate and change tools.",
    )
    parser.add_argument(
        "--sync-calendar-session",
        default=None,
        help="Load a persisted session id and sync booked/changed/cancelled travel to calendar.",
    )
    parser.add_argument(
        "--calendar-event-type",
        default=None,
        help="Optional calendar event type override for --sync-calendar-session.",
    )
    parser.add_argument(
        "--calendar-attendee",
        action="append",
        default=[],
        help="Calendar attendee user id or email. Can be repeated.",
    )
    parser.add_argument(
        "--run-worker-once",
        action="store_true",
        help="Scan persisted sessions and advance approval/order workflows once.",
    )
    parser.add_argument(
        "--worker-limit",
        type=int,
        default=50,
        help="Maximum sessions to scan when --run-worker-once is used.",
    )
    parser.add_argument(
        "--worker-iterations",
        type=int,
        default=1,
        help="Number of worker loop iterations when --run-worker-once is used.",
    )
    parser.add_argument(
        "--worker-interval",
        type=float,
        default=0.0,
        help="Seconds to sleep between worker iterations.",
    )
    parser.add_argument(
        "--worker-auto-recover",
        action="store_true",
        help="Let the worker execute gated recovery strategies for exception states.",
    )
    parser.add_argument(
        "--worker-recovery-approval-override",
        action="store_true",
        help="Treat worker recovery gate approvals as provided.",
    )
    parser.add_argument(
        "--worker-recovery-reason",
        default="worker_auto_recovery",
        help="Recovery reason used when --worker-auto-recover executes a strategy.",
    )
    parser.add_argument(
        "--worker-recovery-rollout-percentage",
        type=int,
        default=None,
        help="Optional percentage gate for worker auto recovery. Omit to skip rollout gating.",
    )
    parser.add_argument(
        "--worker-recovery-rollout-salt",
        default="worker-auto-recovery",
        help="Stable salt used when --worker-recovery-rollout-percentage is set.",
    )
    parser.add_argument(
        "--list-worker-runs",
        action="store_true",
        help="List recent worker run summaries from the session store.",
    )
    parser.add_argument(
        "--list-dead-letters",
        action="store_true",
        help="List notification dead letters from persisted sessions.",
    )
    parser.add_argument(
        "--list-calendar-dead-letters",
        action="store_true",
        help="List calendar sync dead letters from persisted sessions.",
    )
    parser.add_argument(
        "--replay-dead-letter-session",
        default=None,
        help="Session id whose notification dead letter should be replayed.",
    )
    parser.add_argument(
        "--replay-dead-letter-event",
        default=None,
        help="Notification event type to replay for --replay-dead-letter-session.",
    )
    parser.add_argument(
        "--replay-calendar-dead-letter-session",
        default=None,
        help="Session id whose calendar sync dead letter should be replayed.",
    )
    parser.add_argument(
        "--replay-calendar-dead-letter-event",
        default=None,
        help="Calendar event type to replay for --replay-calendar-dead-letter-session.",
    )
    parser.add_argument(
        "--observability-limit",
        type=int,
        default=20,
        help="Maximum worker runs or dead letters to list.",
    )
    parser.add_argument(
        "--metrics",
        action="store_true",
        help="Print a compact metrics summary from worker runs and dead letters.",
    )
    parser.add_argument(
        "--metrics-format",
        choices=("summary", "prometheus"),
        default="summary",
        help="Metrics output format.",
    )
    parser.add_argument(
        "--serve-metrics",
        action="store_true",
        help="Serve Prometheus metrics over HTTP at /metrics.",
    )
    parser.add_argument(
        "--serve-operations-dashboard",
        action="store_true",
        help="Serve operations dashboard JSON over HTTP at /operations/closed-loop.",
    )
    parser.add_argument(
        "--metrics-host",
        default="127.0.0.1",
        help="Host for --serve-metrics.",
    )
    parser.add_argument(
        "--metrics-port",
        type=int,
        default=9108,
        help="Port for --serve-metrics.",
    )
    parser.add_argument(
        "--operations-dashboard-host",
        default="127.0.0.1",
        help="Host for --serve-operations-dashboard.",
    )
    parser.add_argument(
        "--operations-dashboard-port",
        type=int,
        default=9110,
        help="Port for --serve-operations-dashboard.",
    )
    parser.add_argument(
        "--operations-dashboard-token",
        default=None,
        help="Read-only token required by --serve-operations-dashboard. Defaults to TRAVEL_OPERATIONS_DASHBOARD_TOKEN.",
    )
    parser.add_argument(
        "--operations-console-overview",
        action="store_true",
        help="Render the aggregated operations console JSON from closed-loop, webhook ops, replay jobs, and quality gates.",
    )
    parser.add_argument(
        "--operations-schedule-plan",
        action="store_true",
        help="Render the default operations scheduler plan.",
    )
    parser.add_argument(
        "--init-operations-schedule",
        action="store_true",
        help="Persist the default operations scheduler plan into the configured session store.",
    )
    parser.add_argument(
        "--list-operations-schedule",
        action="store_true",
        help="List persisted operations scheduler tasks from the configured session store.",
    )
    parser.add_argument(
        "--operations-scheduler-health",
        action="store_true",
        help="Render scheduler run history and schedule lease health alerts.",
    )
    parser.add_argument(
        "--run-operations-schedule",
        action="store_true",
        help="Run due operations scheduler tasks once using persisted operations data.",
    )
    parser.add_argument(
        "--run-persisted-operations-schedule",
        action="store_true",
        help="Claim due persisted operations scheduler tasks with a lease, run them once, and write back cursors.",
    )
    parser.add_argument(
        "--operations-scheduler-owner",
        default="operations-scheduler",
        help="Lease owner used by --run-persisted-operations-schedule.",
    )
    parser.add_argument(
        "--operations-scheduler-lease-seconds",
        type=int,
        default=300,
        help="Lease TTL in seconds for persisted operations scheduler tasks.",
    )
    parser.add_argument(
        "--execute-oncall-webhook-replay-jobs",
        action="store_true",
        help="Execute persisted pending OnCall webhook replay jobs and write back results.",
    )
    parser.add_argument(
        "--operations-actor",
        default="operator",
        help="User/principal used for operations permission and audit checks.",
    )
    parser.add_argument(
        "--operations-actor-role",
        action="append",
        default=[],
        help="Role used for operations permission and audit checks. Can be repeated.",
    )
    parser.add_argument(
        "--operations-actor-department",
        default=None,
        help="Department used for operations permission and audit checks.",
    )
    parser.add_argument(
        "--operations-authorize-action",
        default=None,
        help="Evaluate operations permission and audit for an action without running it.",
    )
    parser.add_argument(
        "--export-otlp",
        action="store_true",
        help="Export OTLP/HTTP traces and metrics to an OpenTelemetry Collector.",
    )
    parser.add_argument(
        "--otlp-endpoint",
        default=None,
        help="OpenTelemetry Collector OTLP/HTTP endpoint, for example http://localhost:4318.",
    )
    parser.add_argument(
        "--otlp-service-name",
        default="travel-agent",
        help="Service name used in OTLP resource attributes.",
    )
    parser.add_argument(
        "--print-otlp-payload",
        action="store_true",
        help="Print generated OTLP trace and metric payloads instead of sending them.",
    )
    parser.add_argument(
        "--run-evaluation-suite",
        action="store_true",
        help="Run the built-in travel workflow evaluation suite.",
    )
    parser.add_argument(
        "--storage-health",
        action="store_true",
        help="Check the configured persistent session store health.",
    )
    parser.add_argument(
        "--run-integration-acceptance",
        action="store_true",
        help="Render a real-system integration acceptance report.",
    )
    parser.add_argument(
        "--skip-acceptance-evaluation",
        action="store_true",
        help="Skip the built-in evaluation suite when rendering the acceptance report.",
    )
    parser.add_argument(
        "--run-smoke-probes",
        action="store_true",
        help="POST dry-run smoke payloads to configured real-system endpoints.",
    )
    parser.add_argument(
        "--skip-optional-smoke-probes",
        action="store_true",
        help="Skip optional smoke probes such as external session-store health.",
    )
    parser.add_argument(
        "--release-readiness",
        action="store_true",
        help="Render production release readiness governance checks.",
    )
    parser.add_argument(
        "--release-gate",
        action="store_true",
        help="Run release readiness as a CI/CD gate and exit non-zero on failure.",
    )
    parser.add_argument(
        "--allow-action-required",
        action="store_true",
        help="Let --release-gate pass when readiness status is ACTION_REQUIRED.",
    )
    parser.add_argument(
        "--include-acceptance",
        action="store_true",
        help="Include integration acceptance results in --release-readiness.",
    )
    parser.add_argument(
        "--include-smoke-probes",
        action="store_true",
        help="Include dry-run smoke probe results in --release-readiness.",
    )
    parser.add_argument(
        "--rollout-decision",
        action="store_true",
        help="Evaluate rollout and rollback policy for a user.",
    )
    parser.add_argument(
        "--rollout-user",
        default=None,
        help="User id for --rollout-decision. Defaults to --user.",
    )
    parser.add_argument(
        "--rollout-department",
        default=None,
        help="Department for --rollout-decision.",
    )
    parser.add_argument(
        "--rollout-scenario",
        default="default",
        help="Scenario key for --rollout-decision.",
    )
    parser.add_argument(
        "--permission-check",
        action="store_true",
        help="Evaluate permission policy for a user action.",
    )
    parser.add_argument(
        "--permission-action",
        default="plan_trip",
        help="Action for --permission-check, for example plan_trip/create_approval/book_order.",
    )
    parser.add_argument(
        "--permission-user",
        default=None,
        help="User id for --permission-check. Defaults to --user.",
    )
    parser.add_argument(
        "--permission-department",
        default=None,
        help="Department for --permission-check.",
    )
    parser.add_argument(
        "--permission-role",
        action="append",
        default=[],
        help="Role for --permission-check. Can be repeated.",
    )
    parser.add_argument(
        "--operations-runbook",
        action="store_true",
        help="Render the production operations runbook.",
    )
    parser.add_argument(
        "--operations-drill",
        action="store_true",
        help="Run mock incident drills for permission, audit, supplier failure, and rollback scenarios.",
    )
    parser.add_argument(
        "--operations-drill-gate",
        action="store_true",
        help="Run operations drills as a CI/CD gate and exit non-zero on WARN or FAIL.",
    )
    parser.add_argument(
        "--allow-drill-warnings",
        action="store_true",
        help="Let --operations-drill-gate pass when drill status is WARN.",
    )
    parser.add_argument(
        "--operations-alerts",
        action="store_true",
        help="Render operations alerts from the operations drill report.",
    )
    parser.add_argument(
        "--operations-alert-format",
        choices=("summary", "json", "prometheus"),
        default="summary",
        help="Output format for --operations-alerts.",
    )
    parser.add_argument(
        "--export-operations-alerts",
        action="store_true",
        help="POST operations alerts to an alert sink.",
    )
    parser.add_argument(
        "--operations-alert-endpoint",
        default=None,
        help="Alert sink endpoint. Defaults to TRAVEL_ALERT_API_URL.",
    )
    parser.add_argument(
        "--operations-dashboard",
        action="store_true",
        help="Render an operations dashboard from persisted sessions, worker runs, dead letters, and alerts.",
    )
    parser.add_argument(
        "--save-operations-dashboard",
        action="store_true",
        help="Persist the current operations dashboard snapshot to the configured session store.",
    )
    parser.add_argument(
        "--list-operations-dashboard-snapshots",
        action="store_true",
        help="List persisted operations dashboard snapshots from the configured session store.",
    )
    parser.add_argument(
        "--operations-dashboard-trend",
        action="store_true",
        help="Render trend analysis from persisted operations dashboard snapshots.",
    )
    parser.add_argument(
        "--dashboard-trend-window",
        type=int,
        default=7,
        help="Number of persisted dashboard snapshots to include in the trend analysis window.",
    )
    parser.add_argument(
        "--operations-trend-alerts",
        action="store_true",
        help="Evaluate configurable threshold alerts from persisted operations dashboard trend snapshots.",
    )
    parser.add_argument(
        "--trend-alert-format",
        choices=("summary", "json"),
        default="summary",
        help="Output format for --operations-trend-alerts.",
    )
    parser.add_argument(
        "--persist-trend-alerts",
        action="store_true",
        help="Persist generated trend alerts to the session store.",
    )
    parser.add_argument(
        "--create-trend-action-items",
        action="store_true",
        help="Create operations action items from generated trend alerts.",
    )
    parser.add_argument(
        "--operations-multidim-view",
        action="store_true",
        help="Render multi-dimensional operations views from persisted sessions and alerts.",
    )
    parser.add_argument(
        "--multidim-limit",
        type=int,
        default=5,
        help="Maximum rows to show per multi-dimensional slice.",
    )
    parser.add_argument(
        "--operations-postmortem",
        action="store_true",
        help="Generate an incident postmortem from sessions, alerts, snapshots, and OnCall statuses.",
    )
    parser.add_argument(
        "--create-postmortem-action-items",
        action="store_true",
        help="Create persistent operations action items from the generated postmortem.",
    )
    parser.add_argument(
        "--action-owner",
        default="travel-ops",
        help="Default owner for generated operations action items.",
    )
    parser.add_argument(
        "--action-eta",
        default=None,
        help="Optional ETA for generated operations action items.",
    )
    parser.add_argument(
        "--list-operations-action-items",
        action="store_true",
        help="List persisted operations action items.",
    )
    parser.add_argument(
        "--close-operations-action-item",
        default=None,
        help="Close a persisted operations action item by action id.",
    )
    parser.add_argument(
        "--closure-note",
        default="completed",
        help="Closure note for --close-operations-action-item.",
    )
    parser.add_argument(
        "--sync-action-items-from-oncall",
        action="store_true",
        help="Close linked operations action items when synced OnCall tickets are resolved.",
    )
    parser.add_argument(
        "--record-oncall-webhook-json",
        default=None,
        help="Record an OnCall webhook JSON payload as a persisted ticket status.",
    )
    parser.add_argument(
        "--record-oncall-webhook-file",
        default=None,
        help="Read and record an OnCall webhook JSON payload from a file.",
    )
    parser.add_argument(
        "--oncall-webhook-signature",
        default=None,
        help="Webhook signature header value. Supports sha256=<digest>.",
    )
    parser.add_argument(
        "--oncall-webhook-secret",
        default=None,
        help="Webhook signing secret. Defaults to TRAVEL_ONCALL_WEBHOOK_SECRET.",
    )
    parser.add_argument(
        "--oncall-webhook-replay-window-minutes",
        type=int,
        default=1440,
        help="Maximum age for webhook updated_at before treating it as replay.",
    )
    parser.add_argument(
        "--allow-oncall-webhook-replay",
        action="store_true",
        help="Accept webhook payloads outside the replay window.",
    )
    parser.add_argument(
        "--sync-action-items-from-webhook",
        action="store_true",
        help="Close linked action items immediately after recording an accepted webhook.",
    )
    parser.add_argument(
        "--list-oncall-webhook-events",
        action="store_true",
        help="List persisted OnCall webhook events.",
    )
    parser.add_argument(
        "--list-oncall-webhook-dead-letters",
        action="store_true",
        help="List persisted dead-letter OnCall webhook events.",
    )
    parser.add_argument(
        "--oncall-webhook-ops-console",
        action="store_true",
        help="Render dead-letter webhook operations console with retry candidates and patch templates.",
    )
    parser.add_argument(
        "--oncall-webhook-ops-format",
        choices=("summary", "json"),
        default="summary",
        help="Output format for --oncall-webhook-ops-console.",
    )
    parser.add_argument(
        "--replay-oncall-webhook-event",
        default=None,
        help="Replay a persisted dead-letter OnCall webhook event by event id.",
    )
    parser.add_argument(
        "--replay-oncall-webhook-dead-letters",
        action="store_true",
        help="Batch replay persisted dead-letter OnCall webhook events.",
    )
    parser.add_argument(
        "--oncall-webhook-replay-limit",
        type=int,
        default=None,
        help="Maximum dead-letter webhook events to replay in a batch.",
    )
    parser.add_argument(
        "--oncall-webhook-patch-json",
        default=None,
        help="JSON object used to patch a replayed OnCall webhook payload before replay.",
    )
    parser.add_argument(
        "--oncall-webhook-patch-file",
        default=None,
        help="File containing a JSON object used to patch replayed OnCall webhook payloads.",
    )
    parser.add_argument(
        "--oncall-webhook-replay-audit-json",
        action="store_true",
        help="Render replay batch audit JSON after batch replay.",
    )
    parser.add_argument(
        "--persist-oncall-webhook-replay-job",
        action="store_true",
        help="Persist replay job metadata when replaying OnCall webhook dead letters.",
    )
    parser.add_argument(
        "--create-oncall-webhook-replay-job",
        action="store_true",
        help="Create a pending replay job from current dead-letter OnCall webhook candidates.",
    )
    parser.add_argument(
        "--oncall-webhook-replay-requested-by",
        default="operator",
        help="Principal recorded on persisted OnCall webhook replay jobs.",
    )
    parser.add_argument(
        "--oncall-webhook-patch-template-id",
        default=None,
        help="Patch template id recorded on persisted OnCall webhook replay jobs.",
    )
    parser.add_argument(
        "--list-oncall-webhook-replay-jobs",
        action="store_true",
        help="List persisted OnCall webhook replay jobs.",
    )
    parser.add_argument(
        "--oncall-webhook-replay-jobs-format",
        choices=("summary", "json"),
        default="summary",
        help="Output format for --list-oncall-webhook-replay-jobs.",
    )
    parser.add_argument(
        "--save-operations-knowledge",
        action="store_true",
        help="Save operations knowledge entries from trend alerts, postmortem, and closed action items.",
    )
    parser.add_argument(
        "--list-operations-knowledge",
        action="store_true",
        help="List persisted operations knowledge entries.",
    )
    parser.add_argument(
        "--search-operations-knowledge",
        default=None,
        help="Search persisted operations knowledge entries by topic, signal, summary, or recommended action.",
    )
    parser.add_argument(
        "--operations-action-sla",
        action="store_true",
        help="Evaluate SLA and escalation reminders for open operations action items.",
    )
    parser.add_argument(
        "--notify-action-sla",
        action="store_true",
        help="Send SLA escalation reminders through the configured notification integration.",
    )
    parser.add_argument(
        "--action-sla-channel",
        default="im",
        help="Notification channel for --notify-action-sla.",
    )
    parser.add_argument(
        "--action-sla-now",
        default=None,
        help="Optional ISO timestamp used as the current time for --operations-action-sla.",
    )
    parser.add_argument(
        "--operations-closed-loop-report",
        action="store_true",
        help="Summarize trend alerts, action item closure, SLA findings, and knowledge entries.",
    )
    parser.add_argument(
        "--operations-recovery-metrics",
        action="store_true",
        help="Render recovery strategy execution metrics from persisted sessions.",
    )
    parser.add_argument(
        "--operations-recovery-metrics-format",
        choices=("summary", "json", "prometheus"),
        default="summary",
        help="Output format for --operations-recovery-metrics.",
    )
    parser.add_argument(
        "--operations-closed-loop-dashboard",
        action="store_true",
        help="Render persisted closed-loop snapshots as dashboard JSON with filters and cursor pagination.",
    )
    parser.add_argument(
        "--operations-closed-loop-contract",
        choices=("schema", "openapi", "matrix", "validate"),
        default=None,
        help="Render or validate the closed-loop BI contract.",
    )
    parser.add_argument(
        "--closed-loop-contract-server-url",
        default="http://127.0.0.1:9110",
        help="Server URL used in the generated closed-loop OpenAPI contract.",
    )
    parser.add_argument(
        "--closed-loop-dashboard-owner",
        default=None,
        help="Optional owner filter for --operations-closed-loop-dashboard.",
    )
    parser.add_argument(
        "--closed-loop-dashboard-since",
        default=None,
        help="Optional ISO timestamp lower bound for --operations-closed-loop-dashboard.",
    )
    parser.add_argument(
        "--closed-loop-dashboard-cursor",
        default=None,
        help="Optional cursor timestamp for the next closed-loop dashboard page.",
    )
    parser.add_argument(
        "--closed-loop-dashboard-department",
        default=None,
        help="Optional department metadata filter for --operations-closed-loop-dashboard.",
    )
    parser.add_argument(
        "--closed-loop-dashboard-tenant",
        default=None,
        help="Optional tenant metadata filter for --operations-closed-loop-dashboard.",
    )
    parser.add_argument(
        "--closed-loop-dashboard-checkpoint",
        default=None,
        help="Optional checkpoint timestamp for incremental closed-loop dashboard export.",
    )
    parser.add_argument(
        "--closed-loop-dashboard-limit",
        type=int,
        default=None,
        help="Optional page size for --operations-closed-loop-dashboard.",
    )
    parser.add_argument(
        "--closed-loop-snapshot-department",
        default=None,
        help="Department metadata saved with --save-operations-closed-loop.",
    )
    parser.add_argument(
        "--closed-loop-snapshot-tenant",
        default=None,
        help="Tenant metadata saved with --save-operations-closed-loop.",
    )
    parser.add_argument(
        "--save-operations-closed-loop",
        action="store_true",
        help="Save the current closed-loop report as a persistent snapshot.",
    )
    parser.add_argument(
        "--list-operations-closed-loop-snapshots",
        action="store_true",
        help="List persisted closed-loop report snapshots.",
    )
    parser.add_argument(
        "--operations-closed-loop-format",
        choices=("summary", "json", "prometheus"),
        default="summary",
        help="Output format for --operations-closed-loop-report.",
    )
    parser.add_argument(
        "--export-operations-closed-loop",
        action="store_true",
        help="Export the closed-loop report to an HTTP JSON sink.",
    )
    parser.add_argument(
        "--closed-loop-endpoint",
        default=None,
        help="Closed-loop report sink endpoint. Defaults to TRAVEL_CLOSED_LOOP_API_URL.",
    )
    parser.add_argument(
        "--publish-operations-closed-loop-contract",
        action="store_true",
        help="Publish closed-loop JSON Schema/OpenAPI/compatibility matrix to a schema registry.",
    )
    parser.add_argument(
        "--closed-loop-schema-registry-endpoint",
        default=None,
        help="Schema registry endpoint. Defaults to TRAVEL_CLOSED_LOOP_SCHEMA_REGISTRY_URL.",
    )
    parser.add_argument(
        "--operations-closed-loop-quality",
        action="store_true",
        help="Evaluate BI data quality for closed-loop dashboard snapshots.",
    )
    parser.add_argument(
        "--operations-closed-loop-checkpoint-plan",
        action="store_true",
        help="Render the next incremental checkpoint plan for closed-loop BI consumption.",
    )
    parser.add_argument(
        "--operations-closed-loop-acceptance",
        action="store_true",
        help="Run closed-loop BI consumer acceptance checks: contract, data quality, and checkpoint readiness.",
    )
    parser.add_argument(
        "--alert-rules",
        action="store_true",
        help="Render alert routing, escalation, and silence rule templates.",
    )
    parser.add_argument(
        "--alert-rules-format",
        choices=("summary", "json"),
        default="summary",
        help="Output format for --alert-rules.",
    )
    parser.add_argument(
        "--open-oncall-ticket",
        action="store_true",
        help="Open an OnCall or incident ticket with the operations drill report.",
    )
    parser.add_argument(
        "--oncall-endpoint",
        default=None,
        help="OnCall ticket endpoint. Defaults to TRAVEL_ONCALL_API_URL.",
    )
    parser.add_argument(
        "--sync-oncall-ticket",
        default=None,
        help="Fetch and persist status for an OnCall ticket id.",
    )
    parser.add_argument(
        "--oncall-status-endpoint",
        default=None,
        help="OnCall ticket status endpoint. Defaults to TRAVEL_ONCALL_STATUS_API_URL.",
    )
    parser.add_argument(
        "--list-oncall-ticket-statuses",
        action="store_true",
        help="List persisted OnCall ticket statuses from the configured session store.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = IntegrationSettings.from_env()
    if args.session_db:
        settings = _replace_session_db(settings, args.session_db)

    agent = build_default_agent(settings=settings)
    if args.list_worker_runs:
        _require_persistent_session_store(settings, "--list-worker-runs")
        print(render_worker_runs(agent.session_store.list_worker_runs(args.observability_limit)))
        return
    if args.list_dead_letters:
        _require_persistent_session_store(settings, "--list-dead-letters")
        print(render_dead_letters(agent.session_store.list_dead_letter_notifications(args.observability_limit)))
        return
    if args.list_calendar_dead_letters:
        _require_persistent_session_store(settings, "--list-calendar-dead-letters")
        print(
            render_calendar_dead_letters(
                agent.session_store.list_dead_letter_calendar_syncs(args.observability_limit)
            )
        )
        return
    if args.run_evaluation_suite:
        print(render_evaluation_report(run_evaluation_suite()))
        return
    if args.storage_health:
        _require_persistent_session_store(settings, "--storage-health")
        health_check = getattr(agent.session_store, "health_check", None)
        if health_check is None:
            raise SystemExit("--storage-health requires a session store with health_check support.")
        print(render_storage_health(health_check()))
        return
    if args.run_integration_acceptance:
        health = None
        health_check = getattr(agent.session_store, "health_check", None)
        if health_check is not None and _has_persistent_session_store(settings):
            health = health_check()
        report = run_integration_acceptance_report(
            settings,
            storage_health=health,
            include_evaluation=not args.skip_acceptance_evaluation,
        )
        print(render_integration_acceptance_report(report))
        return
    if args.run_smoke_probes:
        report = run_smoke_probes(
            settings,
            JsonHttpClient(settings.timeout_seconds),
            include_optional=not args.skip_optional_smoke_probes,
        )
        print(render_smoke_probe_report(report))
        return
    if args.release_readiness or args.release_gate:
        acceptance = None
        smoke = None
        if args.include_acceptance:
            health = None
            health_check = getattr(agent.session_store, "health_check", None)
            if health_check is not None and _has_persistent_session_store(settings):
                health = health_check()
            acceptance = run_integration_acceptance_report(settings, storage_health=health)
        if args.include_smoke_probes:
            smoke = run_smoke_probes(
                settings,
                JsonHttpClient(settings.timeout_seconds),
                include_optional=not args.skip_optional_smoke_probes,
            )
        report = run_release_readiness_report(settings, acceptance, smoke)
        if args.release_gate:
            gate = evaluate_release_gate(report, allow_action_required=args.allow_action_required)
            print(render_release_gate_result(gate))
            if gate.exit_code:
                raise SystemExit(gate.exit_code)
            return
        print(render_release_readiness_report(report))
        return
    if args.rollout_decision:
        decision = evaluate_rollout(
            RolloutPolicy.from_env(),
            user_id=args.rollout_user or args.user,
            department=args.rollout_department,
            scenario=args.rollout_scenario,
        )
        print(render_rollout_decision(decision))
        return
    if args.permission_check:
        decision = evaluate_permission(
            PermissionPolicy.from_env(),
            user_id=args.permission_user or args.user,
            action=args.permission_action,
            department=args.permission_department,
            roles=args.permission_role,
        )
        print(render_permission_decision(decision))
        return
    if args.operations_runbook:
        print(render_operations_runbook(build_operations_runbook()))
        return
    if args.operations_authorize_action:
        authorization = authorize_operations_action(
            args.operations_authorize_action,
            user_id=args.operations_actor,
            permission_policy=PermissionPolicy.from_env(),
            department=args.operations_actor_department,
            roles=args.operations_actor_role,
            audit_sink=build_audit_sink(settings),
            payload={"source": "cli"},
        )
        print(render_operations_action_authorization(authorization))
        if not authorization.allowed:
            raise SystemExit(1)
        return
    if args.operations_schedule_plan:
        print(render_operations_scheduled_tasks(build_operations_scheduled_tasks()))
        return
    if args.init_operations_schedule:
        _require_persistent_session_store(settings, "--init-operations-schedule")
        tasks = build_operations_scheduled_tasks()
        for task in tasks:
            agent.session_store.record_operations_scheduled_task(operations_scheduled_task_to_dict(task))
        print(render_operations_scheduled_tasks(tasks))
        return
    if args.list_operations_schedule:
        _require_persistent_session_store(settings, "--list-operations-schedule")
        tasks = [
            operations_scheduled_task_from_dict(item)
            for item in agent.session_store.list_operations_scheduled_tasks(args.observability_limit)
        ]
        print(render_operations_scheduled_tasks(tasks))
        return
    if args.operations_scheduler_health:
        _require_persistent_session_store(settings, "--operations-scheduler-health")
        runs = [
            operations_scheduler_run_report_from_dict(item)
            for item in agent.session_store.list_operations_scheduler_runs(args.observability_limit)
        ]
        tasks = [
            operations_scheduled_task_from_dict(item)
            for item in agent.session_store.list_operations_scheduled_tasks(args.observability_limit)
        ]
        print(render_operations_scheduler_health_report(build_operations_scheduler_health_report(runs, tasks)))
        return
    if args.operations_console_overview:
        _require_persistent_session_store(settings, "--operations-console-overview")
        print(build_operations_console_overview_json(agent.session_store, limit=args.observability_limit))
        return
    if args.execute_oncall_webhook_replay_jobs:
        _require_persistent_session_store(settings, "--execute-oncall-webhook-replay-jobs")
        authorization = authorize_operations_action(
            "execute_replay_job",
            user_id=args.operations_actor,
            permission_policy=PermissionPolicy.from_env(),
            department=args.operations_actor_department,
            roles=args.operations_actor_role,
            audit_sink=build_audit_sink(settings),
            payload={"source": "cli", "limit": args.observability_limit},
        )
        print(render_operations_action_authorization(authorization))
        if not authorization.allowed:
            raise SystemExit(1)
        executions = _execute_pending_replay_jobs(agent.session_store, args.observability_limit)
        for execution in executions:
            print(render_oncall_webhook_replay_job_execution(execution))
        if not executions:
            print("OnCall webhook replay job execution:\n- none")
        if any(execution.result.failed for execution in executions):
            raise SystemExit(1)
        return
    if args.run_operations_schedule or args.run_persisted_operations_schedule:
        _require_persistent_session_store(
            settings,
            "--run-persisted-operations-schedule" if args.run_persisted_operations_schedule else "--run-operations-schedule",
        )
        authorization = authorize_operations_action(
            "run_operations_schedule",
            user_id=args.operations_actor,
            permission_policy=PermissionPolicy.from_env(),
            department=args.operations_actor_department,
            roles=args.operations_actor_role,
            audit_sink=build_audit_sink(settings),
            payload={"source": "cli"},
        )
        print(render_operations_action_authorization(authorization))
        if not authorization.allowed:
            raise SystemExit(1)
        handlers = _build_operations_schedule_handlers(agent.session_store, args)
        if args.run_persisted_operations_schedule:
            now = args.recovery_approval_sla_now or None
            started_at = now or None
            tasks = [
                operations_scheduled_task_from_dict(item)
                for item in agent.session_store.claim_due_operations_scheduled_tasks(
                    owner=args.operations_scheduler_owner,
                    now=now or _utc_now(),
                    lease_seconds=args.operations_scheduler_lease_seconds,
                    limit=args.observability_limit,
                )
            ]
            report = run_operations_scheduled_tasks(tasks, handlers, now=started_at)
            results_by_task_id = {result.task_id: result for result in report.results}
            for task in tasks:
                result = results_by_task_id.get(task.task_id)
                if result is None:
                    continue
                agent.session_store.complete_operations_scheduled_task(
                    operations_scheduled_task_to_dict(advance_operations_scheduled_task(task, result))
                )
        else:
            report = run_operations_scheduled_tasks(build_operations_scheduled_tasks(), handlers)
        agent.session_store.record_operations_scheduler_run(operations_scheduler_run_report_to_dict(report))
        print(render_operations_scheduler_run_report(report))
        if report.failed_count:
            raise SystemExit(1)
        return
    if args.list_operations_dashboard_snapshots:
        _require_persistent_session_store(settings, "--list-operations-dashboard-snapshots")
        snapshots = [
            operations_dashboard_snapshot_from_dict(item)
            for item in agent.session_store.list_operations_dashboard_snapshots(args.observability_limit)
        ]
        print(render_operations_dashboard_snapshots(snapshots))
        return
    if args.list_operations_closed_loop_snapshots:
        _require_persistent_session_store(settings, "--list-operations-closed-loop-snapshots")
        snapshots = [
            operations_closed_loop_snapshot_from_dict(item)
            for item in agent.session_store.list_operations_closed_loop_snapshots(args.observability_limit)
        ]
        print(render_operations_closed_loop_snapshots(snapshots))
        return
    if args.operations_dashboard_trend:
        _require_persistent_session_store(settings, "--operations-dashboard-trend")
        snapshots = [
            operations_dashboard_snapshot_from_dict(item)
            for item in agent.session_store.list_operations_dashboard_snapshots(args.observability_limit)
        ]
        report = build_operations_dashboard_trend_report(snapshots, window=args.dashboard_trend_window)
        print(render_operations_dashboard_trend_report(report))
        return
    if args.operations_trend_alerts:
        _require_persistent_session_store(settings, "--operations-trend-alerts")
        snapshots = [
            operations_dashboard_snapshot_from_dict(item)
            for item in agent.session_store.list_operations_dashboard_snapshots(args.observability_limit)
        ]
        trend_report = build_operations_dashboard_trend_report(snapshots, window=args.dashboard_trend_window)
        alerts = evaluate_operations_trend_alerts(
            trend_report,
            build_operations_trend_alert_rules(settings.trend_alert_rules_json),
        )
        if args.persist_trend_alerts:
            for alert in alerts:
                agent.session_store.record_operations_trend_alert(operations_trend_alert_to_dict(alert))
        action_items = []
        if args.create_trend_action_items:
            action_items = build_trend_alert_action_items(alerts, eta=args.action_eta)
            for item in action_items:
                agent.session_store.record_operations_action_item(operations_action_item_to_dict(item))
        if args.trend_alert_format == "json":
            print(render_operations_trend_alerts_json(alerts))
        else:
            print(render_operations_trend_alerts(alerts))
            if action_items:
                print(render_operations_action_items(action_items))
        return
    if args.operations_multidim_view:
        _require_persistent_session_store(settings, "--operations-multidim-view")
        worker_runs = agent.session_store.list_worker_runs(args.observability_limit)
        dead_letters = agent.session_store.list_dead_letter_notifications(args.observability_limit)
        calendar_dead_letters = agent.session_store.list_dead_letter_calendar_syncs(args.observability_limit)
        sessions = agent.session_store.list_recent(args.observability_limit)
        report = build_operations_multidimensional_view(
            sessions=sessions,
            alerts=build_operations_drill_report(
                settings,
                worker_runs=worker_runs,
                dead_letters=dead_letters,
                calendar_dead_letters=calendar_dead_letters,
                sessions=sessions,
                audit_sink_results=agent.gateway.audit_sink_results,
            ).alerts,
            worker_runs=worker_runs,
            dead_letters=dead_letters,
            calendar_dead_letters=calendar_dead_letters,
            limit=args.multidim_limit,
        )
        print(render_operations_multidimensional_view(report))
        return
    if args.list_operations_action_items:
        _require_persistent_session_store(settings, "--list-operations-action-items")
        items = [
            operations_action_item_from_dict(item)
            for item in agent.session_store.list_operations_action_items(args.observability_limit)
        ]
        print(render_operations_action_items(items))
        return
    if args.close_operations_action_item:
        _require_persistent_session_store(settings, "--close-operations-action-item")
        items = [
            operations_action_item_from_dict(item)
            for item in agent.session_store.list_operations_action_items(args.observability_limit)
        ]
        item = next((candidate for candidate in items if candidate.action_id == args.close_operations_action_item), None)
        if item is None:
            raise SystemExit(f"Action item not found: {args.close_operations_action_item}")
        closed = close_operations_action_item(item, args.closure_note)
        agent.session_store.record_operations_action_item(operations_action_item_to_dict(closed))
        print(render_operations_action_items([closed]))
        return
    if args.list_operations_knowledge:
        _require_persistent_session_store(settings, "--list-operations-knowledge")
        entries = [
            operations_knowledge_entry_from_dict(item)
            for item in agent.session_store.list_operations_knowledge_entries(args.observability_limit)
        ]
        print(render_operations_knowledge_entries(entries))
        return
    if args.search_operations_knowledge:
        _require_persistent_session_store(settings, "--search-operations-knowledge")
        entries = [
            operations_knowledge_entry_from_dict(item)
            for item in agent.session_store.list_operations_knowledge_entries(args.observability_limit)
        ]
        report = search_operations_knowledge(entries, args.search_operations_knowledge, limit=args.observability_limit)
        print(render_operations_knowledge_search_report(report))
        return
    if args.operations_action_sla or args.notify_action_sla:
        _require_persistent_session_store(settings, "--operations-action-sla")
        items = [
            operations_action_item_from_dict(item)
            for item in agent.session_store.list_operations_action_items(args.observability_limit)
        ]
        report = evaluate_operations_action_sla(
            items,
            policy=build_operations_action_sla_policy(settings.action_sla_policy_json),
            now=args.action_sla_now,
        )
        print(render_operations_action_sla_report(report))
        if args.notify_action_sla:
            notification_report = agent.notify_operations_action_sla(report, channel=args.action_sla_channel)
            print(render_operations_action_sla_notifications(notification_report))
        return
    if args.recovery_approval_sla:
        _require_persistent_session_store(settings, "--recovery-approval-sla")
        policy = build_recovery_approval_sla_policy(args.recovery_approval_sla_policy_json)
        report = evaluate_recovery_approval_sla(
            agent.session_store.list_recent(args.observability_limit),
            policy=policy,
            now=args.recovery_approval_sla_now,
        )
        print(render_recovery_approval_sla_report(report))
        if report.findings:
            raise SystemExit(1)
        return
    if args.fetch_recovery_governance_policy or args.audit_recovery_governance_policy:
        endpoint = args.recovery_governance_policy_endpoint or settings.recovery_governance_policy_api_url
        local_policy = recovery_governance_policy_from_json(
            args.recovery_governance_policy_json or settings.recovery_governance_policy_json
        )
        if not endpoint:
            if args.audit_recovery_governance_policy:
                audit = build_recovery_governance_policy_audit(
                    local_policy,
                    local_policy,
                    changed_by=args.recovery_governance_policy_changed_by,
                )
                print(render_recovery_governance_policy_audit(audit))
                return
            raise SystemExit(
                "--fetch-recovery-governance-policy requires --recovery-governance-policy-endpoint "
                "or TRAVEL_RECOVERY_GOVERNANCE_POLICY_API_URL."
            )
        result = fetch_recovery_governance_policy_http(
            endpoint,
            token=settings.recovery_governance_policy_api_token,
            fallback_policy=local_policy,
        )
        print(render_recovery_governance_policy_fetch_result(result))
        if args.audit_recovery_governance_policy:
            audit = build_recovery_governance_policy_audit(
                local_policy,
                result.policy,
                changed_by=args.recovery_governance_policy_changed_by,
            )
            print(render_recovery_governance_policy_audit(audit))
        if not result.ok:
            raise SystemExit(1)
        return
    if args.operations_closed_loop_dashboard:
        _require_persistent_session_store(settings, "--operations-closed-loop-dashboard")
        print(
            build_operations_closed_loop_dashboard_json(
                agent.session_store,
                limit=args.closed_loop_dashboard_limit or args.observability_limit,
                owner=args.closed_loop_dashboard_owner,
                since=args.closed_loop_dashboard_since,
                cursor=args.closed_loop_dashboard_cursor,
                department=args.closed_loop_dashboard_department,
                tenant=args.closed_loop_dashboard_tenant,
                checkpoint=args.closed_loop_dashboard_checkpoint,
            )
        )
        return
    if args.operations_closed_loop_contract:
        if args.operations_closed_loop_contract == "schema":
            print(render_operations_closed_loop_json_schema())
            return
        if args.operations_closed_loop_contract == "openapi":
            print(render_operations_closed_loop_openapi_spec(args.closed_loop_contract_server_url))
            return
        if args.operations_closed_loop_contract == "matrix":
            print(render_operations_closed_loop_contract_matrix_json())
            return
        _require_persistent_session_store(settings, "--operations-closed-loop-contract validate")
        snapshots = [
            operations_closed_loop_snapshot_from_dict(item)
            for item in agent.session_store.list_operations_closed_loop_snapshots(
                max(100, args.closed_loop_dashboard_limit or args.observability_limit)
            )
        ]
        dashboard = build_operations_closed_loop_dashboard(
            snapshots,
            limit=args.closed_loop_dashboard_limit or args.observability_limit,
            owner=args.closed_loop_dashboard_owner,
            since=args.closed_loop_dashboard_since,
            cursor=args.closed_loop_dashboard_cursor,
            department=args.closed_loop_dashboard_department,
            tenant=args.closed_loop_dashboard_tenant,
            checkpoint=args.closed_loop_dashboard_checkpoint,
        )
        from .operations import validate_operations_closed_loop_dashboard_contract

        print(render_operations_closed_loop_contract_validation(validate_operations_closed_loop_dashboard_contract(dashboard)))
        return
    if (
        args.operations_closed_loop_quality
        or args.operations_closed_loop_checkpoint_plan
        or args.operations_closed_loop_acceptance
        or args.publish_operations_closed_loop_contract
    ):
        if args.publish_operations_closed_loop_contract:
            endpoint = args.closed_loop_schema_registry_endpoint or settings.closed_loop_schema_registry_url
            if not endpoint:
                raise SystemExit(
                    "--publish-operations-closed-loop-contract requires "
                    "--closed-loop-schema-registry-endpoint or TRAVEL_CLOSED_LOOP_SCHEMA_REGISTRY_URL."
                )
            authorization = authorize_operations_action(
                "publish_closed_loop_schema",
                user_id=args.operations_actor,
                permission_policy=PermissionPolicy.from_env(),
                department=args.operations_actor_department,
                roles=args.operations_actor_role,
                audit_sink=build_audit_sink(settings),
                payload={"endpoint": endpoint},
            )
            print(render_operations_action_authorization(authorization))
            if not authorization.allowed:
                raise SystemExit(1)
            result = publish_operations_closed_loop_schema_http(
                endpoint,
                token=settings.closed_loop_schema_registry_api_token,
                server_url=args.closed_loop_contract_server_url,
            )
            print(render_operations_closed_loop_schema_publish_result(result))
            if not result.ok:
                raise SystemExit(1)
            if not (args.operations_closed_loop_quality or args.operations_closed_loop_checkpoint_plan or args.operations_closed_loop_acceptance):
                return
        _require_persistent_session_store(settings, "--operations-closed-loop-quality")
        snapshots = [
            operations_closed_loop_snapshot_from_dict(item)
            for item in agent.session_store.list_operations_closed_loop_snapshots(
                max(100, args.closed_loop_dashboard_limit or args.observability_limit)
            )
        ]
        dashboard = build_operations_closed_loop_dashboard(
            snapshots,
            limit=args.closed_loop_dashboard_limit or args.observability_limit,
            owner=args.closed_loop_dashboard_owner,
            since=args.closed_loop_dashboard_since,
            cursor=args.closed_loop_dashboard_cursor,
            department=args.closed_loop_dashboard_department,
            tenant=args.closed_loop_dashboard_tenant,
            checkpoint=args.closed_loop_dashboard_checkpoint,
        )
        if args.operations_closed_loop_quality:
            quality = evaluate_operations_closed_loop_quality(dashboard)
            print(render_operations_closed_loop_quality_report(quality))
            if not quality.ok:
                raise SystemExit(1)
        if args.operations_closed_loop_checkpoint_plan:
            print(render_operations_closed_loop_checkpoint_plan(build_operations_closed_loop_checkpoint_plan(dashboard)))
        if args.operations_closed_loop_acceptance:
            acceptance = build_operations_closed_loop_acceptance_report(dashboard)
            print(render_operations_closed_loop_acceptance_report(acceptance))
            if not acceptance.ok:
                raise SystemExit(1)
        return
    if args.operations_recovery_metrics:
        sessions = agent.session_store.list_recent(args.observability_limit)
        metrics = build_recovery_strategy_metrics(sessions)
        if args.operations_recovery_metrics_format == "json":
            print(json.dumps({"recovery_strategy_metrics": metrics}, ensure_ascii=False))
        elif args.operations_recovery_metrics_format == "prometheus":
            print(render_recovery_strategy_metrics_prometheus(sessions))
        else:
            lines = ["Recovery strategy metrics:"]
            if not metrics:
                lines.append("- none")
            else:
                for key, value in sorted(metrics.items()):
                    lines.append(f"- {key}: {value}")
            print("\n".join(lines))
        return
    if args.export_recovery_approval_receipts:
        _require_persistent_session_store(settings, "--export-recovery-approval-receipts")
        endpoint = args.recovery_approval_endpoint or settings.recovery_approval_api_url
        if not endpoint:
            raise SystemExit(
                "--export-recovery-approval-receipts requires --recovery-approval-endpoint "
                "or TRAVEL_RECOVERY_APPROVAL_API_URL."
            )
        receipts = collect_recovery_approval_receipts(agent.session_store.list_recent(args.observability_limit))
        if not receipts:
            print("Recovery approval receipts:\n- none")
            return
        for receipt in receipts:
            result = export_recovery_approval_receipt_http(
                receipt,
                endpoint=endpoint,
                token=settings.recovery_approval_api_token,
            )
            print(render_recovery_approval_export_result(result))
            if not result.ok:
                raise SystemExit(1)
        return
    if args.operations_closed_loop_report or args.export_operations_closed_loop or args.save_operations_closed_loop:
        _require_persistent_session_store(settings, "--operations-closed-loop-report")
        trend_alerts = [
            operations_trend_alert_from_dict(item)
            for item in agent.session_store.list_operations_trend_alerts(args.observability_limit)
        ]
        action_items = [
            operations_action_item_from_dict(item)
            for item in agent.session_store.list_operations_action_items(args.observability_limit)
        ]
        knowledge_entries = [
            operations_knowledge_entry_from_dict(item)
            for item in agent.session_store.list_operations_knowledge_entries(args.observability_limit)
        ]
        sla_report = evaluate_operations_action_sla(
            action_items,
            policy=build_operations_action_sla_policy(settings.action_sla_policy_json),
            now=args.action_sla_now,
        )
        report = build_operations_closed_loop_report(
            trend_alerts=trend_alerts,
            action_items=action_items,
            knowledge_entries=knowledge_entries,
            sla_report=sla_report,
        )
        if args.operations_closed_loop_format == "json":
            print(render_operations_closed_loop_report_json(report))
        elif args.operations_closed_loop_format == "prometheus":
            print(render_operations_closed_loop_report_prometheus(report))
        else:
            print(render_operations_closed_loop_report(report))
        if args.save_operations_closed_loop:
            metadata = {
                key: value
                for key, value in {
                    "department": args.closed_loop_snapshot_department,
                    "tenant": args.closed_loop_snapshot_tenant,
                }.items()
                if value
            }
            snapshot = build_operations_closed_loop_snapshot(report, metadata=metadata)
            agent.session_store.record_operations_closed_loop_snapshot(operations_closed_loop_snapshot_to_dict(snapshot))
            print(render_operations_closed_loop_snapshot(snapshot))
        if args.export_operations_closed_loop:
            endpoint = args.closed_loop_endpoint or settings.closed_loop_api_url
            if not endpoint:
                raise SystemExit(
                    "--export-operations-closed-loop requires --closed-loop-endpoint or TRAVEL_CLOSED_LOOP_API_URL."
                )
            result = export_operations_closed_loop_report_http(
                report,
                endpoint=endpoint,
                token=settings.closed_loop_api_token,
            )
            print(render_operations_closed_loop_export_result(result))
        return
    if args.record_oncall_webhook_json or args.record_oncall_webhook_file:
        _require_persistent_session_store(settings, "--record-oncall-webhook-json")
        raw_body = _load_webhook_body(args.record_oncall_webhook_json, args.record_oncall_webhook_file)
        try:
            webhook_payload = json.loads(raw_body)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"OnCall webhook payload is not valid JSON: {exc}") from exc
        if not isinstance(webhook_payload, dict):
            raise SystemExit("OnCall webhook payload requires a JSON object.")
        existing_events = [
            oncall_webhook_event_from_dict(item)
            for item in agent.session_store.list_oncall_webhook_events(args.observability_limit)
        ]
        event = build_oncall_webhook_event(
            webhook_payload,
            raw_body=raw_body,
            secret=args.oncall_webhook_secret or settings.oncall_webhook_secret,
            signature=args.oncall_webhook_signature,
            seen_event_ids={item.event_id for item in existing_events},
            replay_window_minutes=args.oncall_webhook_replay_window_minutes,
            allow_replay=args.allow_oncall_webhook_replay,
        )
        agent.session_store.record_oncall_webhook_event(oncall_webhook_event_to_dict(event))
        print(render_oncall_webhook_event(event))
        if event.accepted:
            status = oncall_ticket_status_from_webhook(webhook_payload)
            agent.session_store.record_oncall_ticket_status(oncall_ticket_status_to_dict(status))
            print(render_oncall_ticket_status(status))
            if args.sync_action_items_from_webhook:
                items = [
                    operations_action_item_from_dict(item)
                    for item in agent.session_store.list_operations_action_items(args.observability_limit)
                ]
                report = sync_operations_action_items_from_oncall(items, [status])
                for item in report.closed_items:
                    agent.session_store.record_operations_action_item(operations_action_item_to_dict(item))
                print(render_operations_action_status_sync_report(report))
        elif event.dead_letter:
            raise SystemExit(1)
        return
    if args.sync_action_items_from_webhook and not (
        args.replay_oncall_webhook_event or args.replay_oncall_webhook_dead_letters
    ):
        raise SystemExit(
            "--sync-action-items-from-webhook requires --record-oncall-webhook-json, "
            "--record-oncall-webhook-file, --replay-oncall-webhook-event, or --replay-oncall-webhook-dead-letters."
        )
    if args.list_oncall_webhook_events:
        _require_persistent_session_store(settings, "--list-oncall-webhook-events")
        events = [
            oncall_webhook_event_from_dict(item)
            for item in agent.session_store.list_oncall_webhook_events(args.observability_limit)
        ]
        lines = ["OnCall webhook events:"]
        if not events:
            lines.append("- none")
        else:
            for event in events:
                lines.append(
                    f"- {event.event_id}: status={event.status} accepted={event.accepted} "
                    f"duplicate={event.duplicate} replay={event.replay} ticket={event.ticket_id or '-'}"
                )
        print("\n".join(lines))
        return
    if args.list_oncall_webhook_dead_letters:
        _require_persistent_session_store(settings, "--list-oncall-webhook-dead-letters")
        events = list_dead_letter_oncall_webhook_events(
            [
                oncall_webhook_event_from_dict(item)
                for item in agent.session_store.list_oncall_webhook_events(args.observability_limit)
            ]
        )
        lines = ["OnCall webhook dead letters:"]
        if not events:
            lines.append("- none")
        else:
            for event in events:
                lines.append(
                    f"- {event.event_id}: status={event.status} accepted={event.accepted} "
                    f"replay={event.replay} ticket={event.ticket_id or '-'}"
                )
        print("\n".join(lines))
        return
    if args.oncall_webhook_ops_console:
        _require_persistent_session_store(settings, "--oncall-webhook-ops-console")
        authorization = authorize_operations_action(
            "view_operations_console",
            user_id=args.operations_actor,
            permission_policy=PermissionPolicy.from_env(),
            department=args.operations_actor_department,
            roles=args.operations_actor_role,
            audit_sink=build_audit_sink(settings),
            payload={"source": "cli", "view": "oncall_webhook_ops_console"},
        )
        print(render_operations_action_authorization(authorization))
        if not authorization.allowed:
            raise SystemExit(1)
        events = [
            oncall_webhook_event_from_dict(item)
            for item in agent.session_store.list_oncall_webhook_events(args.observability_limit)
        ]
        console = build_oncall_webhook_ops_console(events)
        if args.oncall_webhook_ops_format == "json":
            print(render_oncall_webhook_ops_console_json(console))
        else:
            print(render_oncall_webhook_ops_console(console))
        return
    if args.list_oncall_webhook_replay_jobs:
        _require_persistent_session_store(settings, "--list-oncall-webhook-replay-jobs")
        jobs = [
            oncall_webhook_replay_job_from_dict(item)
            for item in agent.session_store.list_oncall_webhook_replay_jobs(args.observability_limit)
        ]
        if args.oncall_webhook_replay_jobs_format == "json":
            print(render_oncall_webhook_replay_jobs_json(jobs))
        else:
            print(render_oncall_webhook_replay_jobs(jobs))
        return
    if args.create_oncall_webhook_replay_job:
        _require_persistent_session_store(settings, "--create-oncall-webhook-replay-job")
        authorization = authorize_operations_action(
            "create_replay_job",
            user_id=args.operations_actor,
            permission_policy=PermissionPolicy.from_env(),
            department=args.operations_actor_department,
            roles=args.operations_actor_role,
            audit_sink=build_audit_sink(settings),
            payload={"source": "cli", "limit": args.oncall_webhook_replay_limit},
        )
        print(render_operations_action_authorization(authorization))
        if not authorization.allowed:
            raise SystemExit(1)
        events = [
            oncall_webhook_event_from_dict(item)
            for item in agent.session_store.list_oncall_webhook_events(args.observability_limit)
        ]
        dead_letters = list_dead_letter_oncall_webhook_events(events)
        if args.oncall_webhook_replay_limit is not None:
            dead_letters = dead_letters[: max(0, args.oncall_webhook_replay_limit)]
        job = build_oncall_webhook_replay_job(
            [event.event_id for event in dead_letters],
            requested_by=args.oncall_webhook_replay_requested_by,
            patch_template_id=args.oncall_webhook_patch_template_id,
            audit={
                "status": "PENDING",
                "candidate_count": len(dead_letters),
                "source": "cli",
            },
        )
        agent.session_store.record_oncall_webhook_replay_job(oncall_webhook_replay_job_to_dict(job))
        print(render_oncall_webhook_replay_jobs([job]))
        return
    if args.replay_oncall_webhook_event:
        _require_persistent_session_store(settings, "--replay-oncall-webhook-event")
        authorization = authorize_operations_action(
            "execute_replay_job",
            user_id=args.operations_actor,
            permission_policy=PermissionPolicy.from_env(),
            department=args.operations_actor_department,
            roles=args.operations_actor_role,
            audit_sink=build_audit_sink(settings),
            payload={"source": "cli", "mode": "single", "event_id": args.replay_oncall_webhook_event},
        )
        print(render_operations_action_authorization(authorization))
        if not authorization.allowed:
            raise SystemExit(1)
        events = {
            event.event_id: event
            for event in (
                oncall_webhook_event_from_dict(item)
                for item in agent.session_store.list_oncall_webhook_events(args.observability_limit)
            )
        }
        event = events.get(args.replay_oncall_webhook_event)
        if event is None:
            raise SystemExit(f"OnCall webhook event not found: {args.replay_oncall_webhook_event}")
        patch = _load_json_object(
            args.oncall_webhook_patch_json,
            args.oncall_webhook_patch_file,
            "--oncall-webhook-patch-json",
            "--oncall-webhook-patch-file",
        )
        if patch:
            event = patch_oncall_webhook_event_payload(event, patch)
        replayed_event, status, replay_result = replay_dead_letter_oncall_webhook_event(event)
        agent.session_store.record_oncall_webhook_event(oncall_webhook_event_to_dict(replayed_event))
        print(render_oncall_webhook_replay_result(replay_result))
        if status is not None:
            agent.session_store.record_oncall_ticket_status(oncall_ticket_status_to_dict(status))
            print(render_oncall_ticket_status(status))
            if args.sync_action_items_from_webhook:
                items = [
                    operations_action_item_from_dict(item)
                    for item in agent.session_store.list_operations_action_items(args.observability_limit)
                ]
                report = sync_operations_action_items_from_oncall(items, [status])
                for item in report.closed_items:
                    agent.session_store.record_operations_action_item(operations_action_item_to_dict(item))
                print(render_operations_action_status_sync_report(report))
        if args.persist_oncall_webhook_replay_job:
            batch_result = OnCallWebhookReplayBatchResult(
                batch_id=replay_result.source_event_id,
                generated_at=replay_result.replayed_at,
                attempted=1,
                accepted=1 if replay_result.accepted else 0,
                failed=1 if replay_result.status == "FAILED" else 0,
                skipped=1 if replay_result.status == "SKIPPED" else 0,
                results=[replay_result],
            )
            job = build_oncall_webhook_replay_job(
                [replay_result.source_event_id],
                requested_by=args.oncall_webhook_replay_requested_by,
                patch_template_id=args.oncall_webhook_patch_template_id,
                batch_result=batch_result,
                audit={"source": "cli", "mode": "single"},
            )
            agent.session_store.record_oncall_webhook_replay_job(oncall_webhook_replay_job_to_dict(job))
            print(render_oncall_webhook_replay_jobs([job]))
        if not replay_result.accepted:
            raise SystemExit(1)
        return
    if args.replay_oncall_webhook_dead_letters:
        _require_persistent_session_store(settings, "--replay-oncall-webhook-dead-letters")
        authorization = authorize_operations_action(
            "execute_replay_job",
            user_id=args.operations_actor,
            permission_policy=PermissionPolicy.from_env(),
            department=args.operations_actor_department,
            roles=args.operations_actor_role,
            audit_sink=build_audit_sink(settings),
            payload={"source": "cli", "mode": "batch", "limit": args.oncall_webhook_replay_limit},
        )
        print(render_operations_action_authorization(authorization))
        if not authorization.allowed:
            raise SystemExit(1)
        events = [
            oncall_webhook_event_from_dict(item)
            for item in agent.session_store.list_oncall_webhook_events(args.observability_limit)
        ]
        dead_letters = list_dead_letter_oncall_webhook_events(events)
        patch = _load_json_object(
            args.oncall_webhook_patch_json,
            args.oncall_webhook_patch_file,
            "--oncall-webhook-patch-json",
            "--oncall-webhook-patch-file",
        )
        patches = {event.event_id: patch for event in dead_letters} if patch else None
        replayed_events, statuses, batch_result = replay_dead_letter_oncall_webhook_events(
            events,
            limit=args.oncall_webhook_replay_limit,
            patches=patches,
        )
        for event in replayed_events:
            agent.session_store.record_oncall_webhook_event(oncall_webhook_event_to_dict(event))
        for status in statuses:
            agent.session_store.record_oncall_ticket_status(oncall_ticket_status_to_dict(status))
        print(render_oncall_webhook_replay_batch_result(batch_result))
        if args.persist_oncall_webhook_replay_job:
            job = build_oncall_webhook_replay_job(
                [result.source_event_id for result in batch_result.results],
                requested_by=args.oncall_webhook_replay_requested_by,
                patch_template_id=args.oncall_webhook_patch_template_id,
                batch_result=batch_result,
                audit={"source": "cli", "mode": "batch"},
            )
            agent.session_store.record_oncall_webhook_replay_job(oncall_webhook_replay_job_to_dict(job))
            print(render_oncall_webhook_replay_jobs([job]))
        if args.sync_action_items_from_webhook and statuses:
            items = [
                operations_action_item_from_dict(item)
                for item in agent.session_store.list_operations_action_items(args.observability_limit)
            ]
            report = sync_operations_action_items_from_oncall(items, statuses)
            for item in report.closed_items:
                agent.session_store.record_operations_action_item(operations_action_item_to_dict(item))
            print(render_operations_action_status_sync_report(report))
        if args.oncall_webhook_replay_audit_json:
            print(render_oncall_webhook_replay_audit_json(batch_result))
        if batch_result.failed:
            raise SystemExit(1)
        return
    if args.sync_action_items_from_oncall:
        _require_persistent_session_store(settings, "--sync-action-items-from-oncall")
        items = [
            operations_action_item_from_dict(item)
            for item in agent.session_store.list_operations_action_items(args.observability_limit)
        ]
        statuses = [
            oncall_ticket_status_from_dict(item)
            for item in agent.session_store.list_oncall_ticket_statuses(args.observability_limit)
        ]
        report = sync_operations_action_items_from_oncall(items, statuses)
        for item in report.closed_items:
            agent.session_store.record_operations_action_item(operations_action_item_to_dict(item))
        print(render_operations_action_status_sync_report(report))
        return
    if args.list_oncall_ticket_statuses:
        _require_persistent_session_store(settings, "--list-oncall-ticket-statuses")
        statuses = [
            oncall_ticket_status_from_dict(item)
            for item in agent.session_store.list_oncall_ticket_statuses(args.observability_limit)
        ]
        lines = ["OnCall ticket statuses:"]
        if not statuses:
            lines.append("- none")
        else:
            for status in statuses:
                lines.append(f"- {status.ticket_id}: {status.status} assignee={status.assignee or '-'} updated_at={status.updated_at}")
        print("\n".join(lines))
        return
    if args.sync_oncall_ticket:
        _require_persistent_session_store(settings, "--sync-oncall-ticket")
        endpoint = args.oncall_status_endpoint or settings.oncall_status_api_url
        if not endpoint:
            raise SystemExit("--sync-oncall-ticket requires --oncall-status-endpoint or TRAVEL_ONCALL_STATUS_API_URL.")
        status = fetch_oncall_ticket_status_http(
            args.sync_oncall_ticket,
            endpoint=endpoint,
            token=settings.oncall_api_token,
        )
        agent.session_store.record_oncall_ticket_status(oncall_ticket_status_to_dict(status))
        print(render_oncall_ticket_status(status))
        if status.status == "SYNC_FAILED":
            raise SystemExit(1)
        return
    if args.alert_rules:
        rules = build_alert_route_rules(settings.alert_rules_json)
        if args.alert_rules_format == "json":
            print(render_alert_route_rules_json(rules))
        else:
            print(render_alert_route_rules(rules))
        return
    if args.operations_postmortem:
        _require_persistent_session_store(settings, "--operations-postmortem")
        worker_runs = agent.session_store.list_worker_runs(args.observability_limit)
        dead_letters = agent.session_store.list_dead_letter_notifications(args.observability_limit)
        calendar_dead_letters = agent.session_store.list_dead_letter_calendar_syncs(args.observability_limit)
        sessions = agent.session_store.list_recent(args.observability_limit)
        snapshots = [
            operations_dashboard_snapshot_from_dict(item)
            for item in agent.session_store.list_operations_dashboard_snapshots(args.observability_limit)
        ]
        statuses = [
            oncall_ticket_status_from_dict(item)
            for item in agent.session_store.list_oncall_ticket_statuses(args.observability_limit)
        ]
        drill_report = build_operations_drill_report(
            settings,
            worker_runs=worker_runs,
            dead_letters=dead_letters,
            calendar_dead_letters=calendar_dead_letters,
            sessions=sessions,
            audit_sink_results=agent.gateway.audit_sink_results,
        )
        report = build_operations_postmortem_report(
            sessions=sessions,
            snapshots=snapshots,
            oncall_statuses=statuses,
            alerts=drill_report.alerts,
            worker_runs=worker_runs,
            dead_letters=dead_letters,
            calendar_dead_letters=calendar_dead_letters,
            drill_report=drill_report,
        )
        print(render_operations_postmortem_report(report))
        if args.create_postmortem_action_items:
            action_items = build_postmortem_action_items(report, owner=args.action_owner, eta=args.action_eta)
            for item in action_items:
                agent.session_store.record_operations_action_item(operations_action_item_to_dict(item))
            print(render_operations_action_items(action_items))
        if args.save_operations_knowledge:
            trend_report = build_operations_dashboard_trend_report(snapshots, window=args.dashboard_trend_window)
            trend_alerts = evaluate_operations_trend_alerts(
                trend_report,
                build_operations_trend_alert_rules(settings.trend_alert_rules_json),
            )
            action_items = [
                operations_action_item_from_dict(item)
                for item in agent.session_store.list_operations_action_items(args.observability_limit)
            ]
            entries = build_operations_knowledge_entries(
                postmortem=report,
                trend_alerts=trend_alerts,
                action_items=action_items,
            )
            for entry in entries:
                agent.session_store.record_operations_knowledge_entry(operations_knowledge_entry_to_dict(entry))
            print(render_operations_knowledge_entries(entries))
        return
    if (
        args.operations_drill
        or args.operations_drill_gate
        or args.operations_alerts
        or args.export_operations_alerts
        or args.operations_dashboard
        or args.save_operations_dashboard
        or args.open_oncall_ticket
        or args.operations_multidim_view
    ):
        worker_runs: list[WorkerRunRecord] = []
        dead_letters: list[DeadLetterNotification] = []
        calendar_dead_letters: list[DeadLetterCalendarSync] = []
        sessions: list[TravelContext] = []
        if _has_persistent_session_store(settings):
            worker_runs = agent.session_store.list_worker_runs(args.observability_limit)
            dead_letters = agent.session_store.list_dead_letter_notifications(args.observability_limit)
            calendar_dead_letters = agent.session_store.list_dead_letter_calendar_syncs(args.observability_limit)
            sessions = agent.session_store.list_recent(args.observability_limit)
        report = build_operations_drill_report(
            settings,
            worker_runs=worker_runs,
            dead_letters=dead_letters,
            calendar_dead_letters=calendar_dead_letters,
            sessions=sessions,
            audit_sink_results=agent.gateway.audit_sink_results,
        )
        if args.operations_dashboard or args.save_operations_dashboard:
            dashboard = build_operations_dashboard(
                worker_runs=worker_runs,
                dead_letters=dead_letters,
                calendar_dead_letters=calendar_dead_letters,
                sessions=sessions,
                alerts=report.alerts,
            )
            if args.save_operations_dashboard:
                _require_persistent_session_store(settings, "--save-operations-dashboard")
                snapshot = build_operations_dashboard_snapshot(dashboard, report.alerts)
                agent.session_store.record_operations_dashboard_snapshot(
                    operations_dashboard_snapshot_to_dict(snapshot)
                )
                print(render_operations_dashboard_snapshots([snapshot]))
                return
            print(render_operations_dashboard(dashboard))
            return
        if args.operations_alerts:
            if args.operations_alert_format == "json":
                print(render_operations_alerts_json(report.alerts))
            elif args.operations_alert_format == "prometheus":
                print(render_operations_alerts_prometheus(report.alerts))
            else:
                print(render_operations_alerts(report.alerts))
            return
        if args.export_operations_alerts:
            endpoint = args.operations_alert_endpoint or settings.alert_api_url
            if not endpoint:
                raise SystemExit("--export-operations-alerts requires --operations-alert-endpoint or TRAVEL_ALERT_API_URL.")
            result = export_operations_alerts_http(
                report.alerts,
                endpoint=endpoint,
                token=settings.alert_api_token,
            )
            print(render_operations_alert_export_result(result))
            if not result.ok:
                raise SystemExit(1)
            return
        if args.open_oncall_ticket:
            endpoint = args.oncall_endpoint or settings.oncall_api_url
            if not endpoint:
                raise SystemExit("--open-oncall-ticket requires --oncall-endpoint or TRAVEL_ONCALL_API_URL.")
            result = open_oncall_ticket_http(
                report,
                endpoint=endpoint,
                token=settings.oncall_api_token,
            )
            print(render_oncall_ticket_result(result))
            if not result.ok:
                raise SystemExit(1)
            return
        if args.operations_drill_gate:
            gate = evaluate_operations_drill_gate(report, allow_warnings=args.allow_drill_warnings)
            print(render_operations_drill_gate_result(gate))
            if gate.exit_code:
                raise SystemExit(gate.exit_code)
            return
        print(render_operations_drill_report(report))
        return
    if args.metrics:
        _require_persistent_session_store(settings, "--metrics")
        worker_runs = agent.session_store.list_worker_runs(args.observability_limit)
        dead_letters = agent.session_store.list_dead_letter_notifications(args.observability_limit)
        sessions = agent.session_store.list_recent(args.observability_limit)
        if args.metrics_format == "prometheus":
            print(render_prometheus_metrics(worker_runs, dead_letters, sessions))
        else:
            print(render_metrics(worker_runs, dead_letters, sessions))
        return
    if args.serve_metrics:
        _require_persistent_session_store(settings, "--serve-metrics")
        serve_metrics(
            session_store=agent.session_store,
            host=args.metrics_host,
            port=args.metrics_port,
            limit=args.observability_limit,
        )
        return
    if args.serve_operations_dashboard:
        _require_persistent_session_store(settings, "--serve-operations-dashboard")
        serve_operations_dashboard(
            session_store=agent.session_store,
            host=args.operations_dashboard_host,
            port=args.operations_dashboard_port,
            limit=args.observability_limit,
            token=args.operations_dashboard_token or settings.operations_dashboard_token,
            audit_sink=build_audit_sink(settings),
        )
        return
    if args.export_otlp:
        _require_persistent_session_store(settings, "--export-otlp")
        endpoint = args.otlp_endpoint or settings.otlp_http_endpoint
        if not endpoint and not args.print_otlp_payload:
            raise SystemExit("--export-otlp requires --otlp-endpoint or TRAVEL_OTLP_HTTP_ENDPOINT.")
        worker_runs = agent.session_store.list_worker_runs(args.observability_limit)
        dead_letters = agent.session_store.list_dead_letter_notifications(args.observability_limit)
        sessions = agent.session_store.list_recent(args.observability_limit)
        traces_payload, metrics_payload, alerts = build_otlp_payloads(
            worker_runs,
            dead_letters,
            sessions,
            service_name=args.otlp_service_name,
        )
        if args.print_otlp_payload:
            print(json.dumps({"traces": traces_payload, "metrics": metrics_payload, "alerts": alerts}, ensure_ascii=False))
            return
        result = export_otlp_http(
            endpoint=endpoint,
            traces_payload=traces_payload,
            metrics_payload=metrics_payload,
            token=settings.otlp_api_token,
        )
        print(render_otlp_export_result(result))
        return
    if args.replay_dead_letter_session or args.replay_dead_letter_event:
        _require_persistent_session_store(settings, "--replay-dead-letter-session")
        if not args.replay_dead_letter_session or not args.replay_dead_letter_event:
            raise SystemExit("--replay-dead-letter-session requires --replay-dead-letter-event.")
        context = agent.get_session(args.replay_dead_letter_session)
        context = agent.replay_dead_letter_notification(context, args.replay_dead_letter_event)
        print(render_context(context))
        return
    if args.replay_calendar_dead_letter_session or args.replay_calendar_dead_letter_event:
        _require_persistent_session_store(settings, "--replay-calendar-dead-letter-session")
        if not args.replay_calendar_dead_letter_session or not args.replay_calendar_dead_letter_event:
            raise SystemExit(
                "--replay-calendar-dead-letter-session requires --replay-calendar-dead-letter-event."
            )
        context = agent.get_session(args.replay_calendar_dead_letter_session)
        context = agent.replay_dead_letter_calendar_sync(context, args.replay_calendar_dead_letter_event)
        print(render_context(context))
        return
    if args.execute_recovery_strategy_session:
        context = agent.get_session(args.execute_recovery_strategy_session)
        governance_policy_json = args.recovery_governance_policy_json or settings.recovery_governance_policy_json
        governance_policy = recovery_governance_policy_from_json(governance_policy_json)
        context = agent.execute_recovery_strategy(
            context,
            reason=args.replan_reason,
            enforce_strategy_gate=args.enforce_recovery_gate,
            approval_override=args.recovery_approval_override,
            approved_by=args.recovery_approved_by,
            approval_reason=args.recovery_approval_reason,
            governance_policy=governance_policy,
        )
        context = agent.notify_current_state(context)
        print(render_context(context))
        return
    if args.open_recovery_failure_ticket_session:
        _require_persistent_session_store(settings, "--open-recovery-failure-ticket-session")
        endpoint = args.oncall_endpoint or settings.oncall_api_url
        if not endpoint:
            raise SystemExit("--open-recovery-failure-ticket-session requires --oncall-endpoint or TRAVEL_ONCALL_API_URL.")
        context = agent.get_session(args.open_recovery_failure_ticket_session)
        execution_payload = _latest_recovery_execution_payload(context)
        if execution_payload is None:
            raise SystemExit(f"No recovery execution found for session: {context.session_id}")
        execution = recovery_strategy_execution_result_from_dict(execution_payload)
        result = open_recovery_failure_ticket_http(
            context,
            execution,
            endpoint=endpoint,
            token=settings.oncall_api_token,
        )
        print(render_oncall_ticket_result(result))
        if not result.ok:
            raise SystemExit(1)
        return
    if args.replan_session:
        context = agent.get_session(args.replan_session)
        context = agent.replan_after_exception(
            context,
            reason=args.replan_reason,
            enforce_strategy_gate=args.enforce_recovery_gate,
            recovery_approval_override=args.recovery_approval_override,
        )
        context = agent.notify_current_state(context)
        print(render_context(context))
        return
    if args.reselect_hotel_session:
        context = agent.get_session(args.reselect_hotel_session)
        context = agent.reselect_hotel_and_create_approval(context, args.hotel_id, args.transport_id)
        context = agent.notify_current_state(context)
        print(render_context(context))
        return
    if args.run_worker_once:
        _require_persistent_session_store(settings, "--run-worker-once")
        recovery_rollout_policy = None
        if args.worker_recovery_rollout_percentage is not None:
            recovery_rollout_policy = RolloutPolicy(
                enabled=True,
                percentage=args.worker_recovery_rollout_percentage,
                salt=args.worker_recovery_rollout_salt,
            )
        worker = WorkflowWorker(
            agent,
            auto_recover=args.worker_auto_recover,
            recovery_approval_override=args.worker_recovery_approval_override,
            recovery_reason=args.worker_recovery_reason,
            recovery_rollout_policy=recovery_rollout_policy,
        )
        if args.worker_iterations <= 1:
            result = worker.run_once(limit=args.worker_limit)
            print(render_worker_result(result))
        else:
            result = worker.run_loop(
                iterations=args.worker_iterations,
                interval_seconds=args.worker_interval,
                limit=args.worker_limit,
            )
            print(render_worker_loop_result(result))
        return
    if args.accept_price_change or args.reject_price_change:
        if not args.cancel_session:
            raise SystemExit("--accept-price-change/--reject-price-change requires --cancel-session <session-id>.")
        context = agent.get_session(args.cancel_session)
        context = agent.confirm_price_change(context, accept=args.accept_price_change)
        context = agent.notify_current_state(context)
        print(render_context(context))
        return
    if args.refresh_order_session:
        context = agent.get_session(args.refresh_order_session)
        context = agent.refresh_order_status(context)
        context = agent.notify_current_state(context)
        print(render_context(context))
        return
    if args.estimate_refund_session:
        context = agent.get_session(args.estimate_refund_session)
        context = agent.estimate_cancellation_refund(context, args.cancel_reason)
        print(render_context(context))
        return
    if args.change_session:
        context = agent.get_session(args.change_session)
        new_check_in = date.fromisoformat(args.new_check_in) if args.new_check_in else None
        new_check_out = date.fromisoformat(args.new_check_out) if args.new_check_out else None
        context = agent.change_trip(
            context,
            new_depart_at=args.new_depart_at,
            new_check_in=new_check_in,
            new_check_out=new_check_out,
            reason=args.change_reason,
        )
        context = agent.notify_current_state(context)
        print(render_context(context))
        return
    if args.sync_calendar_session:
        context = agent.get_session(args.sync_calendar_session)
        context = agent.sync_calendar(context, args.calendar_event_type, attendees=args.calendar_attendee or None)
        print(render_context(context))
        return
    if args.cancel_session:
        context = agent.get_session(args.cancel_session)
        context = agent.cancel_trip(context, args.cancel_reason)
        context = agent.notify_current_state(context)
        print(render_context(context))
        return

    _validate_required_trip_args(args)
    request = TravelRequest(
        user_id=args.user,
        origin_city=args.origin,
        destination_city=args.destination,
        start_date=date.fromisoformat(args.start),
        end_date=date.fromisoformat(args.end),
        purpose=args.purpose,
        venue=args.venue,
        budget_per_night=args.budget,
        preferences=args.preference,
        department=args.permission_department,
        roles=args.permission_role,
    )

    if args.auto_book:
        context = agent.run_to_order(request, args.hotel_id, args.transport_id)
    else:
        context = agent.plan(request)
    if not args.auto_book and (args.auto_confirm or args.hotel_id or args.transport_id):
        context = agent.confirm_and_create_approval(context, args.hotel_id, args.transport_id)
    if args.cancel_after_book:
        context = agent.cancel_trip(context, args.cancel_reason)
    context = agent.notify_current_state(context)

    print(render_context(context))


def render_worker_result(result: WorkflowRunResult) -> str:
    lines = [
        "Worker result:",
        f"- run_id: {result.run_id or '-'}",
        f"- scanned: {result.scanned}",
        f"- advanced: {result.advanced}",
        f"- skipped: {result.skipped}",
        f"- errors: {len(result.errors)}",
    ]
    if result.started_at and result.finished_at:
        lines.append(f"- window: {result.started_at} -> {result.finished_at}")
    if result.session_ids:
        lines.append("- sessions: " + ", ".join(result.session_ids))
    for session_id, error in result.errors.items():
        lines.append(f"- error {session_id}: {error}")
    return "\n".join(lines)


def render_worker_loop_result(result: WorkflowLoopResult) -> str:
    lines = [
        "Worker loop result:",
        f"- iterations: {result.iterations}",
        f"- scanned: {result.scanned}",
        f"- advanced: {result.advanced}",
        f"- skipped: {result.skipped}",
        f"- errors: {len(result.errors)}",
    ]
    if result.run_ids:
        lines.append("- run_ids: " + ", ".join(result.run_ids))
    for session_id, error in result.errors.items():
        lines.append(f"- error {session_id}: {error}")
    return "\n".join(lines)


def render_worker_runs(records: list[WorkerRunRecord]) -> str:
    lines = ["Worker runs:"]
    if not records:
        lines.append("- none")
        return "\n".join(lines)
    for record in records:
        lines.append(
            f"- {record.run_id} | {record.finished_at} | scanned={record.scanned} "
            f"advanced={record.advanced} skipped={record.skipped} errors={len(record.errors)}"
        )
        if record.session_ids:
            lines.append("  sessions: " + ", ".join(record.session_ids))
    return "\n".join(lines)


def render_dead_letters(records: list[DeadLetterNotification]) -> str:
    lines = ["Notification dead letters:"]
    if not records:
        lines.append("- none")
        return "\n".join(lines)
    for record in records:
        notification = record.notification
        lines.append(
            f"- session={record.session_id} state={record.state} event={notification.event_type} "
            f"retry={notification.retry_count}/{notification.max_retries} error={notification.last_error or '-'}"
        )
    return "\n".join(lines)


def render_calendar_dead_letters(records: list[DeadLetterCalendarSync]) -> str:
    lines = ["Calendar sync dead letters:"]
    if not records:
        lines.append("- none")
        return "\n".join(lines)
    for record in records:
        calendar = record.calendar_sync
        lines.append(
            f"- session={record.session_id} state={record.state} event={calendar.event_type} "
            f"retry={calendar.retry_count}/{calendar.max_retries} error={calendar.last_error or '-'}"
        )
    return "\n".join(lines)


def render_metrics(
    worker_runs: list[WorkerRunRecord],
    dead_letters: list[DeadLetterNotification],
    sessions: list[TravelContext] | None = None,
) -> str:
    sessions = sessions or []
    scanned = sum(record.scanned for record in worker_runs)
    advanced = sum(record.advanced for record in worker_runs)
    skipped = sum(record.skipped for record in worker_runs)
    errors = sum(len(record.errors) for record in worker_runs)
    agent_executions = sum(len(context.agent_executions) for context in sessions)
    calendar_syncs = sum(len(context.calendar_syncs) for context in sessions)
    recovery_metrics = build_recovery_strategy_metrics(sessions)
    recovery_executions = sum(
        count for key, count in recovery_metrics.items() if key.startswith("status:")
    )
    lines = [
        "Metrics:",
        f"- worker_runs: {len(worker_runs)}",
        f"- scanned: {scanned}",
        f"- advanced: {advanced}",
        f"- skipped: {skipped}",
        f"- worker_errors: {errors}",
        f"- dead_letters: {len(dead_letters)}",
        f"- sessions_observed: {len(sessions)}",
        f"- agent_executions: {agent_executions}",
        f"- calendar_syncs: {calendar_syncs}",
        f"- recovery_strategy_executions: {recovery_executions}",
    ]
    return "\n".join(lines)


def render_prometheus_metrics(
    worker_runs: list[WorkerRunRecord],
    dead_letters: list[DeadLetterNotification],
    sessions: list[TravelContext],
) -> str:
    scanned = sum(record.scanned for record in worker_runs)
    advanced = sum(record.advanced for record in worker_runs)
    skipped = sum(record.skipped for record in worker_runs)
    errors = sum(len(record.errors) for record in worker_runs)
    lines = [
        "# HELP travel_worker_runs_total Total recorded workflow worker runs.",
        "# TYPE travel_worker_runs_total counter",
        f"travel_worker_runs_total {len(worker_runs)}",
        "# HELP travel_worker_sessions_total Total sessions scanned by workflow workers.",
        "# TYPE travel_worker_sessions_total counter",
        f'travel_worker_sessions_total{{result="scanned"}} {scanned}',
        f'travel_worker_sessions_total{{result="advanced"}} {advanced}',
        f'travel_worker_sessions_total{{result="skipped"}} {skipped}',
        "# HELP travel_worker_errors_total Total workflow worker errors.",
        "# TYPE travel_worker_errors_total counter",
        f"travel_worker_errors_total {errors}",
        "# HELP travel_notification_dead_letters_total Notification dead letters by event type.",
        "# TYPE travel_notification_dead_letters_total gauge",
    ]

    dead_letter_counts: dict[tuple[str, str], int] = {}
    for record in dead_letters:
        key = (record.state, record.notification.event_type)
        dead_letter_counts[key] = dead_letter_counts.get(key, 0) + 1
    if dead_letter_counts:
        for (state, event_type), count in sorted(dead_letter_counts.items()):
            lines.append(
                "travel_notification_dead_letters_total"
                f'{{state="{_metric_label(state)}",event_type="{_metric_label(event_type)}"}} {count}'
            )
    else:
        lines.append("travel_notification_dead_letters_total 0")

    lines.extend(
        [
            "# HELP travel_sessions_observed_total Sessions included in this metrics snapshot.",
            "# TYPE travel_sessions_observed_total gauge",
            f"travel_sessions_observed_total {len(sessions)}",
            "# HELP travel_session_states_total Sessions by current workflow state.",
            "# TYPE travel_session_states_total gauge",
        ]
    )
    state_counts: dict[str, int] = {}
    for context in sessions:
        state_counts[context.state] = state_counts.get(context.state, 0) + 1
    if state_counts:
        for state, count in sorted(state_counts.items()):
            lines.append(f'travel_session_states_total{{state="{_metric_label(state)}"}} {count}')
    else:
        lines.append("travel_session_states_total 0")

    lines.extend(
        [
            "# HELP travel_agent_executions_total Agent execution records by agent, action, and status.",
            "# TYPE travel_agent_executions_total counter",
        ]
    )
    execution_counts: dict[tuple[str, str, str], int] = {}
    for context in sessions:
        for record in context.agent_executions:
            key = (record.agent_name, record.action, record.status)
            execution_counts[key] = execution_counts.get(key, 0) + 1
    if execution_counts:
        for (agent_name, action, status), count in sorted(execution_counts.items()):
            lines.append(
                "travel_agent_executions_total"
                f'{{agent="{_metric_label(agent_name)}",action="{_metric_label(action)}",status="{_metric_label(status)}"}} {count}'
            )
    else:
        lines.append("travel_agent_executions_total 0")

    lines.extend(
        [
            "# HELP travel_calendar_syncs_total Calendar sync records by event type, status, and source.",
            "# TYPE travel_calendar_syncs_total counter",
        ]
    )
    calendar_counts: dict[tuple[str, str, str], int] = {}
    for context in sessions:
        for record in context.calendar_syncs:
            key = (record.event_type, record.status, record.source)
            calendar_counts[key] = calendar_counts.get(key, 0) + 1
    if calendar_counts:
        for (event_type, status, source), count in sorted(calendar_counts.items()):
            lines.append(
                "travel_calendar_syncs_total"
                f'{{event_type="{_metric_label(event_type)}",status="{_metric_label(status)}",source="{_metric_label(source)}"}} {count}'
            )
    else:
        lines.append("travel_calendar_syncs_total 0")

    lines.append(render_recovery_strategy_metrics_prometheus(sessions))
    return "\n".join(lines)


def render_otlp_export_result(result: object) -> str:
    return "\n".join(
        [
            "OTLP export result:",
            f"- traces_url: {getattr(result, 'traces_url')}",
            f"- traces_status: {getattr(result, 'traces_status')}",
            f"- metrics_url: {getattr(result, 'metrics_url')}",
            f"- metrics_status: {getattr(result, 'metrics_status')}",
            f"- spans: {getattr(result, 'span_count')}",
            f"- metrics: {getattr(result, 'metric_count')}",
            f"- sla_alert_points: {getattr(result, 'alert_count')}",
        ]
    )


def render_storage_health(health: StorageHealth) -> str:
    lines = [
        "Storage health:",
        f"- backend: {health.backend}",
        f"- ok: {health.ok}",
        f"- schema_version: {health.schema_version}",
        f"- sessions: {health.session_count}",
        f"- worker_runs: {health.worker_run_count}",
    ]
    for key, value in sorted(health.details.items()):
        lines.append(f"- {key}: {value}")
    return "\n".join(lines)


def build_prometheus_metrics(session_store: SessionStore, limit: int = 50) -> str:
    return render_prometheus_metrics(
        worker_runs=session_store.list_worker_runs(limit),
        dead_letters=session_store.list_dead_letter_notifications(limit),
        sessions=session_store.list_recent(limit),
    )


def build_operations_closed_loop_dashboard_json(
    session_store: SessionStore,
    limit: int = 20,
    owner: str | None = None,
    since: str | None = None,
    cursor: str | None = None,
    department: str | None = None,
    tenant: str | None = None,
    checkpoint: str | None = None,
) -> str:
    fetch_limit = max(100, limit + 1)
    snapshots = [
        operations_closed_loop_snapshot_from_dict(item)
        for item in session_store.list_operations_closed_loop_snapshots(fetch_limit)
    ]
    dashboard = build_operations_closed_loop_dashboard(
        snapshots,
        limit=limit,
        owner=owner,
        since=since,
        cursor=cursor,
        department=department,
        tenant=tenant,
        checkpoint=checkpoint,
    )
    return render_operations_closed_loop_dashboard_json(dashboard)


def build_oncall_webhook_ops_console_json(session_store: SessionStore, limit: int = 20) -> str:
    events = [
        oncall_webhook_event_from_dict(item)
        for item in session_store.list_oncall_webhook_events(limit)
    ]
    return render_oncall_webhook_ops_console_json(build_oncall_webhook_ops_console(events))


def build_oncall_webhook_replay_jobs_json(session_store: SessionStore, limit: int = 20) -> str:
    jobs = [
        oncall_webhook_replay_job_from_dict(item)
        for item in session_store.list_oncall_webhook_replay_jobs(limit)
    ]
    return render_oncall_webhook_replay_jobs_json(jobs)


def build_operations_console_overview_json(session_store: SessionStore, limit: int = 20) -> str:
    snapshots = [
        operations_closed_loop_snapshot_from_dict(item)
        for item in session_store.list_operations_closed_loop_snapshots(max(100, limit + 1))
    ]
    dashboard = build_operations_closed_loop_dashboard(snapshots, limit=limit)
    events = [
        oncall_webhook_event_from_dict(item)
        for item in session_store.list_oncall_webhook_events(limit)
    ]
    jobs = [
        oncall_webhook_replay_job_from_dict(item)
        for item in session_store.list_oncall_webhook_replay_jobs(limit)
    ]
    overview = build_operations_console_overview(
        dashboard,
        build_oncall_webhook_ops_console(events),
        jobs,
    )
    return render_operations_console_overview_json(overview)


def build_operations_audit_timeline_json(
    session_store: SessionStore,
    limit: int = 20,
    event_type: str | None = None,
    actor: str | None = None,
    action: str | None = None,
    status: str | None = None,
) -> str:
    read_limit = max(100, limit * 2)
    action_audits = [
        operations_console_action_audit_from_dict(item)
        for item in session_store.list_operations_console_action_audits(read_limit)
    ]
    governance_changes = [
        operations_governance_policy_change_from_dict(item)
        for item in session_store.list_operations_governance_policy_changes(read_limit)
    ]
    replay_jobs = [
        oncall_webhook_replay_job_from_dict(item)
        for item in session_store.list_oncall_webhook_replay_jobs(read_limit)
    ]
    scheduler_runs = [
        operations_scheduler_run_report_from_dict(item)
        for item in session_store.list_operations_scheduler_runs(read_limit)
    ]
    timeline = build_operations_audit_timeline(
        action_audits=action_audits,
        governance_changes=governance_changes,
        replay_jobs=replay_jobs,
        scheduler_runs=scheduler_runs,
        limit=limit,
        event_type=event_type,
        actor=actor,
        action=action,
        status=status,
    )
    return render_operations_audit_timeline_json(timeline)


def build_operations_audit_sink_deliveries_json(session_store: SessionStore, limit: int = 20) -> str:
    deliveries = [
        operations_audit_sink_delivery_from_dict(item)
        for item in session_store.list_operations_audit_sink_deliveries(limit)
    ]
    return render_operations_audit_sink_deliveries_json(deliveries)


def build_operations_compensation_tasks_json(
    session_store: SessionStore,
    limit: int = 20,
    owner: str | None = None,
    status: str | None = None,
    source_type: str | None = None,
) -> str:
    read_limit = max(100, limit * 2)
    sessions = session_store.list_recent(read_limit)
    replay_jobs = [
        oncall_webhook_replay_job_from_dict(item)
        for item in session_store.list_oncall_webhook_replay_jobs(read_limit)
    ]
    action_items = [
        operations_action_item_from_dict(item)
        for item in session_store.list_operations_action_items(read_limit)
    ]
    oncall_statuses = [
        oncall_ticket_status_from_dict(item)
        for item in session_store.list_oncall_ticket_statuses(read_limit)
    ]
    persisted_tasks = [
        operations_compensation_task_from_dict(item)
        for item in session_store.list_operations_compensation_tasks(read_limit)
    ]
    sla_report = evaluate_operations_action_sla(action_items, policy=build_operations_action_sla_policy())
    board = build_operations_compensation_tasks(
        sessions=sessions,
        replay_jobs=replay_jobs,
        action_items=action_items,
        oncall_statuses=oncall_statuses,
        persisted_tasks=persisted_tasks,
        sla_report=sla_report,
        limit=limit,
        owner=owner,
        status=status,
        source_type=source_type,
    )
    return render_operations_compensation_task_board_json(board)


def execute_operations_compensation_tasks_json(
    session_store: SessionStore,
    limit: int = 20,
    oncall_endpoint: str | None = None,
    oncall_token: str | None = None,
) -> str:
    board_payload = json.loads(build_operations_compensation_tasks_json(session_store, max(100, limit * 2)))
    tasks = [
        operations_compensation_task_from_dict(item)
        for item in board_payload["operations_compensation_tasks"]["tasks"]
    ]
    report = execute_operations_compensation_tasks(
        tasks,
        limit=limit,
        oncall_endpoint=oncall_endpoint,
        oncall_token=oncall_token,
        actor="operations_console",
    )
    for execution in report.executions:
        session_store.record_operations_compensation_task(operations_compensation_task_to_dict(execution.task))
        if execution.ticket_result is not None and execution.ticket_result.ticket_id:
            session_store.record_oncall_ticket_status(
                oncall_ticket_status_to_dict(
                    OnCallTicketStatus(
                        ticket_id=execution.ticket_result.ticket_id,
                        status="OPEN",
                        assignee=None,
                        updated_at=execution.executed_at,
                        detail=execution.ticket_result.detail,
                    )
                )
            )
    return render_operations_compensation_task_execution_report_json(report)


def retry_operations_audit_sink_deliveries_json(
    session_store: SessionStore,
    audit_sink: AuditSink,
    limit: int = 20,
) -> str:
    read_limit = max(100, limit * 2)
    audits = [
        operations_console_action_audit_from_dict(item)
        for item in session_store.list_operations_console_action_audits(read_limit)
    ]
    deliveries = [
        operations_audit_sink_delivery_from_dict(item)
        for item in session_store.list_operations_audit_sink_deliveries(read_limit)
    ]
    report = retry_operations_audit_sink_deliveries(
        audits=audits,
        deliveries=deliveries,
        audit_sink=audit_sink,
        limit=limit,
    )
    for delivery in report.deliveries:
        session_store.record_operations_audit_sink_delivery(operations_audit_sink_delivery_to_dict(delivery))
    return render_operations_audit_sink_replay_report_json(report)


def build_operations_console_view_json(
    session_store: SessionStore,
    limit: int = 20,
    actor: str = "operator",
    roles: list[str] | None = None,
    department: str | None = None,
) -> str:
    return render_operations_console_view_json(
        _build_operations_console_view(session_store, limit, actor, roles, department)
    )


def build_operations_console_view_html(
    session_store: SessionStore,
    limit: int = 20,
    actor: str = "operator",
    roles: list[str] | None = None,
    department: str | None = None,
) -> str:
    return render_operations_console_view_html(
        _build_operations_console_view(session_store, limit, actor, roles, department)
    )


def _build_operations_console_view(
    session_store: SessionStore,
    limit: int,
    actor: str,
    roles: list[str] | None,
    department: str | None,
) -> object:
    snapshots = [
        operations_closed_loop_snapshot_from_dict(item)
        for item in session_store.list_operations_closed_loop_snapshots(max(100, limit + 1))
    ]
    dashboard = build_operations_closed_loop_dashboard(snapshots, limit=limit)
    events = [
        oncall_webhook_event_from_dict(item)
        for item in session_store.list_oncall_webhook_events(limit)
    ]
    jobs = [
        oncall_webhook_replay_job_from_dict(item)
        for item in session_store.list_oncall_webhook_replay_jobs(limit)
    ]
    overview = build_operations_console_overview(
        dashboard,
        build_oncall_webhook_ops_console(events),
        jobs,
    )
    return build_operations_console_view(
        overview,
        actor=actor,
        roles=roles or [],
        department=department,
        permission_policy=PermissionPolicy.from_env(),
    )


def run_operations_console_action(
    session_store: SessionStore,
    action: str,
    actor: str,
    roles: list[str] | None = None,
    department: str | None = None,
    payload: dict[str, object] | None = None,
    audit_sink: object | None = None,
    limit: int = 20,
) -> str:
    payload = dict(payload or {})
    action = action.strip()
    requested_at = _utc_now()
    action_limit = _payload_limit(payload, limit)
    permission_action = {
        "create_replay_job": "create_replay_job",
        "execute_replay_jobs": "execute_replay_job",
        "run_operations_schedule": "run_operations_schedule",
        "publish_closed_loop_schema": "publish_closed_loop_schema",
        "propose_governance_policy_change": "update_governance_policy",
        "approve_governance_policy_change": "update_governance_policy",
        "rollback_governance_policy_change": "update_governance_policy",
        "retry_audit_sink_deliveries": "retry_audit_sink_delivery",
        "close_compensation_task": "manage_compensation_task",
        "execute_compensation_tasks": "manage_compensation_task",
    }.get(action)
    if permission_action is None:
        return _finalize_operations_console_action(
            session_store,
            {
                "ok": False,
                "action": action,
                "error": "unsupported action",
            },
            action,
            actor,
            roles,
            department,
            payload,
            {},
            requested_at,
            audit_sink,
        )
    authorization = authorize_operations_action(
        permission_action,
        user_id=actor,
        permission_policy=PermissionPolicy.from_env(),
        department=department,
        roles=roles or [],
        audit_sink=audit_sink,
        payload={"source": "operations_console_action", **payload},
    )
    if not authorization.allowed:
        authorization_payload = operations_action_authorization_to_dict(authorization)
        return _finalize_operations_console_action(
            session_store,
            {
                "ok": False,
                "action": action,
                "authorization": authorization_payload,
            },
            action,
            actor,
            roles,
            department,
            payload,
            authorization_payload,
            requested_at,
            audit_sink,
        )
    if action == "create_replay_job":
        events = [
            oncall_webhook_event_from_dict(item)
            for item in session_store.list_oncall_webhook_events(action_limit)
        ]
        if action_limit <= 0:
            events = []
        dead_letters = list_dead_letter_oncall_webhook_events(events)
        dead_letters = dead_letters[:action_limit]
        job = build_oncall_webhook_replay_job(
            [event.event_id for event in dead_letters],
            requested_by=str(payload.get("requested_by") or actor),
            patch_template_id=(
                str(payload["patch_template_id"]) if payload.get("patch_template_id") is not None else None
            ),
            audit={
                "status": "PENDING",
                "candidate_count": len(dead_letters),
                "source": "operations_console_action",
            },
        )
        session_store.record_oncall_webhook_replay_job(oncall_webhook_replay_job_to_dict(job))
        body = {
            "ok": True,
            "action": action,
            "authorization": operations_action_authorization_to_dict(authorization),
            "job": oncall_webhook_replay_job_to_dict(job),
        }
    elif action == "execute_replay_jobs":
        executions = _execute_pending_replay_jobs(
            session_store,
            action_limit,
            patches=_payload_replay_patches(payload),
        )
        body = {
            "ok": not any(execution.result.failed for execution in executions),
            "action": action,
            "authorization": operations_action_authorization_to_dict(authorization),
            "executions": [
                oncall_webhook_replay_job_execution_to_dict(execution)
                for execution in executions
            ],
        }
    elif action == "run_operations_schedule":
        report = _run_operations_schedule_action(session_store, payload, limit=action_limit)
        body = {
            "ok": report.failed_count == 0,
            "action": action,
            "authorization": operations_action_authorization_to_dict(authorization),
            "scheduler_run": operations_scheduler_run_report_to_dict(report),
        }
    elif action == "publish_closed_loop_schema":
        result = _publish_closed_loop_schema_action(payload)
        body = {
            "ok": result.ok,
            "action": action,
            "authorization": operations_action_authorization_to_dict(authorization),
            "publish_result": {
                "ok": result.ok,
                "endpoint": result.endpoint,
                "schema_version": result.schema_version,
                "delivered": result.delivered,
                "failed": result.failed,
                "detail": result.detail,
            },
        }
    elif action == "propose_governance_policy_change":
        change = _propose_governance_policy_change(session_store, payload, actor)
        body = {
            "ok": True,
            "action": action,
            "authorization": operations_action_authorization_to_dict(authorization),
            "change": operations_governance_policy_change_to_dict(change),
        }
    elif action == "approve_governance_policy_change":
        change = _approve_governance_policy_change(session_store, payload, actor)
        body = {
            "ok": change is not None,
            "action": action,
            "authorization": operations_action_authorization_to_dict(authorization),
            "change": operations_governance_policy_change_to_dict(change) if change is not None else None,
            "error": None if change is not None else "governance policy change not found",
        }
    elif action == "rollback_governance_policy_change":
        change = _rollback_governance_policy_change(session_store, payload, actor)
        body = {
            "ok": change is not None,
            "action": action,
            "authorization": operations_action_authorization_to_dict(authorization),
            "change": operations_governance_policy_change_to_dict(change) if change is not None else None,
            "error": None if change is not None else "governance policy change not found",
        }
    elif action == "retry_audit_sink_deliveries":
        retry_sink = _audit_sink_from_console_payload(payload, audit_sink)
        if retry_sink is None:
            body = {
                "ok": False,
                "action": action,
                "authorization": operations_action_authorization_to_dict(authorization),
                "error": "audit sink endpoint is not configured",
            }
        else:
            retry_payload = json.loads(retry_operations_audit_sink_deliveries_json(session_store, retry_sink, action_limit))
            report = retry_payload["operations_audit_sink_replay"]
            body = {
                "ok": int(report.get("failed") or 0) == 0,
                "action": action,
                "authorization": operations_action_authorization_to_dict(authorization),
                "audit_sink_replay": report,
            }
    elif action == "close_compensation_task":
        task_id = str(payload.get("task_id") or "")
        if not task_id:
            body = {
                "ok": False,
                "action": action,
                "authorization": operations_action_authorization_to_dict(authorization),
                "error": "task_id is required",
            }
        else:
            board_payload = json.loads(build_operations_compensation_tasks_json(session_store, max(100, action_limit)))
            tasks = [
                operations_compensation_task_from_dict(item)
                for item in board_payload["operations_compensation_tasks"]["tasks"]
            ]
            task = next((item for item in tasks if item.task_id == task_id), None)
            if task is None:
                body = {
                    "ok": False,
                    "action": action,
                    "authorization": operations_action_authorization_to_dict(authorization),
                    "error": "compensation task not found",
                    "task_id": task_id,
                }
            else:
                closed = close_operations_compensation_task(
                    task,
                    closure_note=str(payload.get("closure_note") or "closed from operations console"),
                    actor=actor,
                )
                session_store.record_operations_compensation_task(operations_compensation_task_to_dict(closed))
                body = {
                    "ok": True,
                    "action": action,
                    "authorization": operations_action_authorization_to_dict(authorization),
                    "task": operations_compensation_task_to_dict(closed),
                }
    else:
        endpoint = payload.get("endpoint") or payload.get("oncall_endpoint")
        execution_payload = json.loads(
            execute_operations_compensation_tasks_json(
                session_store,
                limit=action_limit,
                oncall_endpoint=str(endpoint) if endpoint is not None else None,
                oncall_token=str(payload["token"]) if payload.get("token") is not None else None,
            )
        )
        report = execution_payload["operations_compensation_task_execution"]
        body = {
            "ok": int(report.get("failed") or 0) == 0,
            "action": action,
            "authorization": operations_action_authorization_to_dict(authorization),
            "compensation_task_execution": report,
        }
    return _finalize_operations_console_action(
        session_store,
        body,
        action,
        actor,
        roles,
        department,
        payload,
        body.get("authorization") if isinstance(body.get("authorization"), dict) else {},
        requested_at,
        audit_sink,
    )


def _audit_sink_from_console_payload(payload: dict[str, object], audit_sink: object | None) -> AuditSink | None:
    if isinstance(audit_sink, AuditSink):
        return audit_sink
    endpoint = payload.get("endpoint") or payload.get("audit_sink_endpoint")
    if endpoint is None:
        return None
    return HttpAuditSink(str(endpoint), str(payload["token"]) if payload.get("token") is not None else None)


def _finalize_operations_console_action(
    session_store: SessionStore,
    body: dict[str, object],
    action: str,
    actor: str,
    roles: list[str] | None,
    department: str | None,
    payload: dict[str, object],
    authorization: dict[str, object],
    requested_at: str,
    audit_sink: object | None = None,
) -> str:
    audit = build_operations_console_action_audit(
        action=action,
        actor=actor,
        roles=roles or [],
        department=department,
        authorization=dict(authorization),
        request_payload=payload,
        result_body=body,
        requested_at=requested_at,
        completed_at=_utc_now(),
    )
    try:
        session_store.record_operations_console_action_audit(operations_console_action_audit_to_dict(audit))
        body["action_audit"] = {
            "audit_id": audit.audit_id,
            "status": audit.status,
            "recorded": True,
        }
        if isinstance(audit_sink, AuditSink):
            result = audit_sink.write([build_operations_console_action_audit_event(audit)])
            delivery = build_operations_audit_sink_delivery(audit, result)
            session_store.record_operations_audit_sink_delivery(operations_audit_sink_delivery_to_dict(delivery))
            body["action_audit"]["sink_delivery"] = {
                "delivery_id": delivery.delivery_id,
                "status": delivery.status,
                "delivered": delivery.delivered,
                "failed": delivery.failed,
                "attempts": delivery.attempts,
            }
    except Exception as exc:
        body["action_audit"] = {
            "audit_id": audit.audit_id,
            "status": audit.status,
            "recorded": False,
            "error": str(exc),
        }
    return json.dumps({"operations_console_action": body}, ensure_ascii=False)


def make_metrics_handler(
    metrics_provider: Callable[[], str],
    closed_loop_dashboard_provider: Callable[
        [str | None, str | None, str | None, str | None, str | None, str | None, int | None],
        str,
    ]
    | None = None,
    oncall_webhook_ops_provider: Callable[[int | None], str] | None = None,
    oncall_webhook_replay_jobs_provider: Callable[[int | None], str] | None = None,
    operations_console_provider: Callable[[int | None], str] | None = None,
    operations_console_view_provider: Callable[[int | None, str, list[str], str | None], str] | None = None,
    operations_console_html_provider: Callable[[int | None, str, list[str], str | None], str] | None = None,
    operations_audit_timeline_provider: Callable[
        [int | None, str | None, str | None, str | None, str | None],
        str,
    ]
    | None = None,
    operations_audit_sink_deliveries_provider: Callable[[int | None], str] | None = None,
    operations_compensation_tasks_provider: Callable[
        [int | None, str | None, str | None, str | None],
        str,
    ]
    | None = None,
    operations_console_action_provider: Callable[[str, str, list[str], str | None, dict[str, object]], str] | None = None,
    dashboard_token: str | None = None,
) -> type[BaseHTTPRequestHandler]:
    class MetricsHandler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            parsed = urlsplit(self.path)
            path = parsed.path
            if path == "/operations/console/actions":
                if operations_console_action_provider is None:
                    self.send_response(404)
                    self.end_headers()
                    return
                if not self._authorized():
                    self.send_response(401)
                    self.end_headers()
                    return
                payload = self._json_body()
                action = str(payload.get("action") or "")
                if not action:
                    self.send_response(400)
                    self.end_headers()
                    return
                self._send_text(
                    operations_console_action_provider(
                        action,
                        self._actor(),
                        self._roles(),
                        self._department(),
                        payload,
                    ) + "\n",
                    "application/json; charset=utf-8",
                )
                return
            self.send_response(404)
            self.end_headers()

        def do_GET(self) -> None:
            parsed = urlsplit(self.path)
            path = parsed.path
            if path == "/health":
                self._send_text("ok\n", "text/plain; charset=utf-8")
                return
            if path == "/metrics":
                self._send_text(metrics_provider() + "\n", "text/plain; version=0.0.4; charset=utf-8")
                return
            if path in {"/operations/closed-loop", "/operations/closed-loop/snapshots"}:
                if closed_loop_dashboard_provider is None:
                    self.send_response(404)
                    self.end_headers()
                    return
                if not self._authorized():
                    self.send_response(401)
                    self.end_headers()
                    return
                query = parse_qs(parsed.query)
                self._send_text(
                    closed_loop_dashboard_provider(
                        _first_query_value(query, "owner"),
                        _first_query_value(query, "since"),
                        _first_query_value(query, "cursor"),
                        _first_query_value(query, "department"),
                        _first_query_value(query, "tenant"),
                        _first_query_value(query, "checkpoint"),
                        _first_query_int(query, "limit"),
                    ) + "\n",
                    "application/json; charset=utf-8",
                )
                return
            if path == "/operations/oncall-webhook-ops":
                if oncall_webhook_ops_provider is None:
                    self.send_response(404)
                    self.end_headers()
                    return
                if not self._authorized():
                    self.send_response(401)
                    self.end_headers()
                    return
                query = parse_qs(parsed.query)
                self._send_text(
                    oncall_webhook_ops_provider(_first_query_int(query, "limit")) + "\n",
                    "application/json; charset=utf-8",
                )
                return
            if path == "/operations/oncall-webhook-replay-jobs":
                if oncall_webhook_replay_jobs_provider is None:
                    self.send_response(404)
                    self.end_headers()
                    return
                if not self._authorized():
                    self.send_response(401)
                    self.end_headers()
                    return
                query = parse_qs(parsed.query)
                self._send_text(
                    oncall_webhook_replay_jobs_provider(_first_query_int(query, "limit")) + "\n",
                    "application/json; charset=utf-8",
                )
                return
            if path == "/operations/console":
                if operations_console_provider is None:
                    self.send_response(404)
                    self.end_headers()
                    return
                if not self._authorized():
                    self.send_response(401)
                    self.end_headers()
                    return
                query = parse_qs(parsed.query)
                self._send_text(
                    operations_console_provider(_first_query_int(query, "limit")) + "\n",
                    "application/json; charset=utf-8",
                )
                return
            if path == "/operations/console/view":
                if operations_console_view_provider is None:
                    self.send_response(404)
                    self.end_headers()
                    return
                if not self._authorized():
                    self.send_response(401)
                    self.end_headers()
                    return
                query = parse_qs(parsed.query)
                self._send_text(
                    operations_console_view_provider(
                        _first_query_int(query, "limit"),
                        self._actor(),
                        self._roles(),
                        self._department(),
                    ) + "\n",
                    "application/json; charset=utf-8",
                )
                return
            if path == "/operations/console/audit-timeline":
                if operations_audit_timeline_provider is None:
                    self.send_response(404)
                    self.end_headers()
                    return
                if not self._authorized():
                    self.send_response(401)
                    self.end_headers()
                    return
                query = parse_qs(parsed.query)
                self._send_text(
                    operations_audit_timeline_provider(
                        _first_query_int(query, "limit"),
                        _first_query_value(query, "event_type"),
                        _first_query_value(query, "actor"),
                        _first_query_value(query, "action"),
                        _first_query_value(query, "status"),
                    ) + "\n",
                    "application/json; charset=utf-8",
                )
                return
            if path == "/operations/console/audit-sink-deliveries":
                if operations_audit_sink_deliveries_provider is None:
                    self.send_response(404)
                    self.end_headers()
                    return
                if not self._authorized():
                    self.send_response(401)
                    self.end_headers()
                    return
                query = parse_qs(parsed.query)
                self._send_text(
                    operations_audit_sink_deliveries_provider(_first_query_int(query, "limit")) + "\n",
                    "application/json; charset=utf-8",
                )
                return
            if path == "/operations/console/compensation-tasks":
                if operations_compensation_tasks_provider is None:
                    self.send_response(404)
                    self.end_headers()
                    return
                if not self._authorized():
                    self.send_response(401)
                    self.end_headers()
                    return
                query = parse_qs(parsed.query)
                self._send_text(
                    operations_compensation_tasks_provider(
                        _first_query_int(query, "limit"),
                        _first_query_value(query, "owner"),
                        _first_query_value(query, "status"),
                        _first_query_value(query, "source_type"),
                    ) + "\n",
                    "application/json; charset=utf-8",
                )
                return
            if path == "/operations/console/ui":
                if operations_console_html_provider is None:
                    self.send_response(404)
                    self.end_headers()
                    return
                if not self._authorized():
                    self.send_response(401)
                    self.end_headers()
                    return
                query = parse_qs(parsed.query)
                self._send_text(
                    operations_console_html_provider(
                        _first_query_int(query, "limit"),
                        self._actor(),
                        self._roles(),
                        self._department(),
                    ) + "\n",
                    "text/html; charset=utf-8",
                )
                return
            self.send_response(404)
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            del format, args

        def _send_text(self, body: str, content_type: str) -> None:
            encoded = body.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def _authorized(self) -> bool:
            if not dashboard_token:
                return True
            auth = self.headers.get("Authorization") or ""
            token = self.headers.get("X-Operations-Dashboard-Token") or ""
            if auth.startswith("Bearer "):
                token = auth[7:]
            return token == dashboard_token

        def _actor(self) -> str:
            return self.headers.get("X-Operations-Actor") or "operator"

        def _roles(self) -> list[str]:
            raw = self.headers.get("X-Operations-Roles") or ""
            return [item.strip() for item in raw.split(",") if item.strip()]

        def _department(self) -> str | None:
            value = self.headers.get("X-Operations-Department")
            return value.strip() if value and value.strip() else None

        def _json_body(self) -> dict[str, object]:
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0:
                return {}
            raw = self.rfile.read(length).decode("utf-8")
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                return {}
            return dict(payload) if isinstance(payload, dict) else {}

    return MetricsHandler


def create_metrics_server(
    session_store: SessionStore,
    host: str = "127.0.0.1",
    port: int = 9108,
    limit: int = 50,
) -> ThreadingHTTPServer:
    return ThreadingHTTPServer(
        (host, port),
        make_metrics_handler(lambda: build_prometheus_metrics(session_store, limit)),
    )


def create_operations_dashboard_server(
    session_store: SessionStore,
    host: str = "127.0.0.1",
    port: int = 9110,
    limit: int = 20,
    token: str | None = None,
    audit_sink: AuditSink | None = None,
) -> ThreadingHTTPServer:
    return ThreadingHTTPServer(
        (host, port),
        make_metrics_handler(
            lambda: build_prometheus_metrics(session_store, limit),
            lambda owner, since, cursor, department, tenant, checkpoint, request_limit: build_operations_closed_loop_dashboard_json(
                session_store,
                request_limit or limit,
                owner=owner,
                since=since,
                cursor=cursor,
                department=department,
                tenant=tenant,
                checkpoint=checkpoint,
            ),
            lambda request_limit: build_oncall_webhook_ops_console_json(session_store, request_limit or limit),
            lambda request_limit: build_oncall_webhook_replay_jobs_json(session_store, request_limit or limit),
            lambda request_limit: build_operations_console_overview_json(session_store, request_limit or limit),
            lambda request_limit, actor, roles, department: build_operations_console_view_json(
                session_store,
                request_limit or limit,
                actor=actor,
                roles=roles,
                department=department,
            ),
            lambda request_limit, actor, roles, department: build_operations_console_view_html(
                session_store,
                request_limit or limit,
                actor=actor,
                roles=roles,
                department=department,
            ),
            lambda request_limit, event_type, actor, action, status: build_operations_audit_timeline_json(
                session_store,
                request_limit or limit,
                event_type=event_type,
                actor=actor,
                action=action,
                status=status,
            ),
            lambda request_limit: build_operations_audit_sink_deliveries_json(session_store, request_limit or limit),
            lambda request_limit, owner, status, source_type: build_operations_compensation_tasks_json(
                session_store,
                request_limit or limit,
                owner=owner,
                status=status,
                source_type=source_type,
            ),
            lambda action, actor, roles, department, payload: run_operations_console_action(
                session_store,
                action,
                actor=actor,
                roles=roles,
                department=department,
                payload=payload,
                audit_sink=audit_sink,
                limit=limit,
            ),
            dashboard_token=token,
        ),
    )


def serve_metrics(
    session_store: SessionStore,
    host: str = "127.0.0.1",
    port: int = 9108,
    limit: int = 50,
) -> None:
    server = create_metrics_server(session_store, host=host, port=port, limit=limit)
    actual_host, actual_port = server.server_address
    print(f"Serving metrics on http://{actual_host}:{actual_port}/metrics")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def serve_operations_dashboard(
    session_store: SessionStore,
    host: str = "127.0.0.1",
    port: int = 9110,
    limit: int = 20,
    token: str | None = None,
    audit_sink: AuditSink | None = None,
) -> None:
    server = create_operations_dashboard_server(
        session_store,
        host=host,
        port=port,
        limit=limit,
        token=token,
        audit_sink=audit_sink,
    )
    actual_host, actual_port = server.server_address
    print(f"Serving operations dashboard on http://{actual_host}:{actual_port}/operations/closed-loop")
    print(f"Serving OnCall webhook ops on http://{actual_host}:{actual_port}/operations/oncall-webhook-ops")
    print(f"Serving operations console on http://{actual_host}:{actual_port}/operations/console")
    print(f"Serving operations audit timeline on http://{actual_host}:{actual_port}/operations/console/audit-timeline")
    print(f"Serving operations audit sink deliveries on http://{actual_host}:{actual_port}/operations/console/audit-sink-deliveries")
    print(f"Serving operations compensation tasks on http://{actual_host}:{actual_port}/operations/console/compensation-tasks")
    print(f"Serving operations console UI on http://{actual_host}:{actual_port}/operations/console/ui")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def run_metrics_server_in_thread(server: ThreadingHTTPServer) -> Thread:
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return thread


def _first_query_value(query: dict[str, list[str]], key: str) -> str | None:
    values = query.get(key) or []
    return values[0] if values else None


def _first_query_int(query: dict[str, list[str]], key: str) -> int | None:
    value = _first_query_value(query, key)
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _metric_label(value: object) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _replace_session_db(settings: IntegrationSettings, session_db_path: str) -> IntegrationSettings:
    return IntegrationSettings(
        policy_api_url=settings.policy_api_url,
        transport_policy_api_url=settings.transport_policy_api_url,
        hotel_inventory_api_url=settings.hotel_inventory_api_url,
        hotel_price_check_api_url=settings.hotel_price_check_api_url,
        hotel_inventory_lock_api_url=settings.hotel_inventory_lock_api_url,
        hotel_inventory_release_api_url=settings.hotel_inventory_release_api_url,
        oa_approval_api_url=settings.oa_approval_api_url,
        oa_approval_status_api_url=settings.oa_approval_status_api_url,
        oa_approval_cancel_api_url=settings.oa_approval_cancel_api_url,
        order_api_url=settings.order_api_url,
        order_status_api_url=settings.order_status_api_url,
        order_cancel_api_url=settings.order_cancel_api_url,
        refund_estimate_api_url=settings.refund_estimate_api_url,
        refund_confirm_api_url=settings.refund_confirm_api_url,
        change_approval_api_url=settings.change_approval_api_url,
        change_failure_compensation_api_url=settings.change_failure_compensation_api_url,
        hotel_change_api_url=settings.hotel_change_api_url,
        transport_inventory_api_url=settings.transport_inventory_api_url,
        transport_order_api_url=settings.transport_order_api_url,
        transport_order_status_api_url=settings.transport_order_status_api_url,
        transport_order_cancel_api_url=settings.transport_order_cancel_api_url,
        transport_change_api_url=settings.transport_change_api_url,
        notification_api_url=settings.notification_api_url,
        calendar_api_url=settings.calendar_api_url,
        permission_api_url=settings.permission_api_url,
        audit_log_api_url=settings.audit_log_api_url,
        alert_api_url=settings.alert_api_url,
        oncall_api_url=settings.oncall_api_url,
        oncall_status_api_url=settings.oncall_status_api_url,
        oncall_webhook_secret=settings.oncall_webhook_secret,
        closed_loop_api_url=settings.closed_loop_api_url,
        closed_loop_schema_registry_url=settings.closed_loop_schema_registry_url,
        recovery_approval_api_url=settings.recovery_approval_api_url,
        recovery_governance_policy_json=settings.recovery_governance_policy_json,
        recovery_governance_policy_api_url=settings.recovery_governance_policy_api_url,
        operations_dashboard_token=settings.operations_dashboard_token,
        alert_rules_json=settings.alert_rules_json,
        trend_alert_rules_json=settings.trend_alert_rules_json,
        action_sla_policy_json=settings.action_sla_policy_json,
        otlp_http_endpoint=settings.otlp_http_endpoint,
        policy_api_token=settings.policy_api_token,
        transport_api_token=settings.transport_api_token,
        hotel_inventory_api_token=settings.hotel_inventory_api_token,
        oa_approval_api_token=settings.oa_approval_api_token,
        order_api_token=settings.order_api_token,
        notification_api_token=settings.notification_api_token,
        calendar_api_token=settings.calendar_api_token,
        permission_api_token=settings.permission_api_token,
        audit_log_api_token=settings.audit_log_api_token,
        alert_api_token=settings.alert_api_token,
        oncall_api_token=settings.oncall_api_token,
        closed_loop_api_token=settings.closed_loop_api_token,
        closed_loop_schema_registry_api_token=settings.closed_loop_schema_registry_api_token,
        recovery_approval_api_token=settings.recovery_approval_api_token,
        recovery_governance_policy_api_token=settings.recovery_governance_policy_api_token,
        otlp_api_token=settings.otlp_api_token,
        use_mock_fallback=settings.use_mock_fallback,
        notification_use_mock_fallback=settings.notification_use_mock_fallback,
        calendar_use_mock_fallback=settings.calendar_use_mock_fallback,
        timeout_seconds=settings.timeout_seconds,
        session_db_path=session_db_path,
        session_store_backend=settings.session_store_backend,
        session_store_api_url=settings.session_store_api_url,
        session_store_api_token=settings.session_store_api_token,
    )


def _require_persistent_session_store(settings: IntegrationSettings, command_name: str) -> None:
    backend = settings.session_store_backend.strip().lower()
    has_sqlite = bool(settings.session_db_path)
    has_http = bool(settings.session_store_api_url)
    if backend == "memory":
        raise SystemExit(
            f"{command_name} requires a persistent session store; configure SQLite or HTTP session store."
        )
    if backend == "sqlite" and not has_sqlite:
        raise SystemExit(f"{command_name} requires --session-db or TRAVEL_SESSION_DB_PATH.")
    if backend == "http" and not has_http:
        raise SystemExit(f"{command_name} requires TRAVEL_SESSION_STORE_API_URL.")
    if backend == "auto" and not has_sqlite and not has_http:
        raise SystemExit(
            f"{command_name} requires --session-db, TRAVEL_SESSION_DB_PATH, or TRAVEL_SESSION_STORE_API_URL."
        )


def _has_persistent_session_store(settings: IntegrationSettings) -> bool:
    backend = settings.session_store_backend.strip().lower()
    if backend == "memory":
        return False
    return bool(settings.session_db_path or settings.session_store_api_url)


def _load_webhook_body(webhook_json: str | None, webhook_file: str | None) -> str:
    if webhook_json and webhook_file:
        raise SystemExit("Use either --record-oncall-webhook-json or --record-oncall-webhook-file, not both.")
    if webhook_file:
        return Path(webhook_file).read_text(encoding="utf-8-sig")
    if webhook_json is None:
        raise SystemExit("OnCall webhook payload is required.")
    return webhook_json


def _load_json_object(
    json_text: str | None,
    json_file: str | None,
    json_flag: str,
    file_flag: str,
) -> dict[str, Any]:
    if json_text and json_file:
        raise SystemExit(f"Use either {json_flag} or {file_flag}, not both.")
    raw = None
    if json_file:
        raw = Path(json_file).read_text(encoding="utf-8-sig")
    elif json_text is not None:
        raw = json_text
    if raw is None:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"JSON payload is not valid: {exc}") from exc
    if not isinstance(payload, dict):
        raise SystemExit("JSON payload requires an object.")
    return payload


def _payload_limit(payload: dict[str, object], default: int) -> int:
    value = payload.get("limit")
    if value is None:
        return max(0, default)
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return max(0, default)


def _payload_replay_patches(payload: dict[str, object]) -> dict[str, dict[str, Any]] | None:
    patches = payload.get("patches")
    if isinstance(patches, dict):
        normalized = {
            str(event_id): dict(patch)
            for event_id, patch in patches.items()
            if isinstance(patch, dict)
        }
        return normalized or None
    patch = payload.get("patch")
    if not isinstance(patch, dict):
        return None
    event_ids = payload.get("event_ids")
    if isinstance(event_ids, list):
        ids = [str(event_id) for event_id in event_ids if str(event_id)]
    else:
        single = payload.get("event_id")
        ids = [str(single)] if single else []
    return {event_id: dict(patch) for event_id in ids} or None


def _run_operations_schedule_action(
    session_store: SessionStore,
    payload: dict[str, object],
    limit: int,
):
    schedule_args = _operations_schedule_action_args(payload, limit)
    handlers = _build_operations_schedule_handlers(session_store, schedule_args)
    if bool(payload.get("persisted")):
        now = str(payload.get("now") or _utc_now())
        tasks = [
            operations_scheduled_task_from_dict(item)
            for item in session_store.claim_due_operations_scheduled_tasks(
                owner=str(payload.get("owner") or "operations-console"),
                now=now,
                lease_seconds=_payload_int(payload, "lease_seconds", 300),
                limit=limit,
            )
        ]
        report = run_operations_scheduled_tasks(tasks, handlers, now=now)
        results_by_task_id = {result.task_id: result for result in report.results}
        for task in tasks:
            result = results_by_task_id.get(task.task_id)
            if result is None:
                continue
            session_store.complete_operations_scheduled_task(
                operations_scheduled_task_to_dict(advance_operations_scheduled_task(task, result))
            )
    else:
        now = str(payload.get("now")) if payload.get("now") is not None else None
        report = run_operations_scheduled_tasks(build_operations_scheduled_tasks(now=now), handlers, now=now)
    session_store.record_operations_scheduler_run(operations_scheduler_run_report_to_dict(report))
    return report


def _operations_schedule_action_args(payload: dict[str, object], limit: int) -> argparse.Namespace:
    return argparse.Namespace(
        observability_limit=limit,
        closed_loop_dashboard_limit=_payload_int(payload, "closed_loop_dashboard_limit", limit),
        closed_loop_dashboard_owner=_payload_optional_str(payload, "owner_filter"),
        closed_loop_dashboard_since=_payload_optional_str(payload, "since"),
        closed_loop_dashboard_cursor=_payload_optional_str(payload, "cursor"),
        closed_loop_dashboard_department=_payload_optional_str(payload, "department_filter"),
        closed_loop_dashboard_tenant=_payload_optional_str(payload, "tenant"),
        closed_loop_dashboard_checkpoint=_payload_optional_str(payload, "checkpoint"),
        recovery_approval_sla_policy_json=_payload_optional_str(payload, "recovery_approval_sla_policy_json"),
        recovery_approval_sla_now=_payload_optional_str(payload, "now"),
    )


def _publish_closed_loop_schema_action(payload: dict[str, object]) -> OperationsClosedLoopSchemaPublishResult:
    endpoint = _payload_optional_str(payload, "endpoint") or IntegrationSettings.from_env().closed_loop_schema_registry_url
    if not endpoint:
        return OperationsClosedLoopSchemaPublishResult(
            ok=False,
            endpoint="",
            schema_version="travel.operations.closed_loop.v1",
            delivered=0,
            failed=1,
            detail="missing schema registry endpoint",
        )
    token = _payload_optional_str(payload, "token") or IntegrationSettings.from_env().closed_loop_schema_registry_api_token
    return publish_operations_closed_loop_schema_http(
        endpoint,
        token=token,
        server_url=_payload_optional_str(payload, "server_url") or "http://127.0.0.1:9110",
    )


def _propose_governance_policy_change(
    session_store: SessionStore,
    payload: dict[str, object],
    actor: str,
):
    previous = (
        _payload_governance_policy(payload, "before")
        or _payload_governance_policy(payload, "previous_policy")
        or _current_governance_policy(session_store)
    )
    proposed = (
        _payload_governance_policy(payload, "after")
        or _payload_governance_policy(payload, "policy")
        or _payload_governance_policy(payload, "proposed_policy")
        or RecoveryGovernancePolicy()
    )
    change = build_operations_governance_policy_change(
        previous,
        proposed,
        requested_by=str(payload.get("requested_by") or actor),
        requested_at=_payload_optional_str(payload, "requested_at"),
        reason=_payload_optional_str(payload, "reason"),
    )
    session_store.record_operations_governance_policy_change(operations_governance_policy_change_to_dict(change))
    return change


def _approve_governance_policy_change(
    session_store: SessionStore,
    payload: dict[str, object],
    actor: str,
):
    change = _find_governance_policy_change(
        session_store,
        _payload_optional_str(payload, "change_id"),
        statuses={"PENDING_APPROVAL", "APPROVED"},
    )
    if change is None:
        return None
    approved = approve_operations_governance_policy_change(
        change,
        approver=str(payload.get("approved_by") or actor),
    )
    if approved.status == "APPROVED" and _payload_bool(payload, "apply", True):
        approved = apply_operations_governance_policy_change(
            approved,
            applied_at=_payload_optional_str(payload, "applied_at"),
        )
    session_store.record_operations_governance_policy_change(operations_governance_policy_change_to_dict(approved))
    return approved


def _rollback_governance_policy_change(
    session_store: SessionStore,
    payload: dict[str, object],
    actor: str,
):
    change = _find_governance_policy_change(
        session_store,
        _payload_optional_str(payload, "change_id"),
        statuses={"APPLIED", "ROLLED_BACK"},
    )
    if change is None:
        return None
    rollback = rollback_operations_governance_policy_change(
        change,
        requested_by=str(payload.get("requested_by") or actor),
        requested_at=_payload_optional_str(payload, "requested_at"),
        reason=_payload_optional_str(payload, "reason"),
    )
    session_store.record_operations_governance_policy_change(operations_governance_policy_change_to_dict(rollback))
    return rollback


def _find_governance_policy_change(
    session_store: SessionStore,
    change_id: str | None,
    statuses: set[str] | None = None,
):
    for item in session_store.list_operations_governance_policy_changes(100):
        change = operations_governance_policy_change_from_dict(item)
        if change_id and change.change_id != change_id:
            continue
        if statuses and change.status not in statuses:
            continue
        return change
    return None


def _current_governance_policy(session_store: SessionStore) -> RecoveryGovernancePolicy:
    for item in session_store.list_operations_governance_policy_changes(100):
        change = operations_governance_policy_change_from_dict(item)
        if change.status in {"APPLIED", "ROLLED_BACK"}:
            return recovery_governance_policy_from_dict(change.after)
    return recovery_governance_policy_from_json(IntegrationSettings.from_env().recovery_governance_policy_json)


def _payload_governance_policy(payload: dict[str, object], key: str) -> RecoveryGovernancePolicy | None:
    value = payload.get(key)
    if isinstance(value, dict):
        return recovery_governance_policy_from_dict(value)
    if isinstance(value, str) and value.strip():
        return recovery_governance_policy_from_json(value)
    return None


def _payload_int(payload: dict[str, object], key: str, default: int) -> int:
    value = payload.get(key)
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _payload_optional_str(payload: dict[str, object], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _payload_bool(payload: dict[str, object], key: str, default: bool) -> bool:
    value = payload.get(key)
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _execute_pending_replay_jobs(
    session_store: SessionStore,
    limit: int,
    patches: dict[str, dict[str, Any]] | None = None,
) -> list[OnCallWebhookReplayJobExecution]:
    if limit <= 0:
        return []
    events = [
        oncall_webhook_event_from_dict(item)
        for item in session_store.list_oncall_webhook_events(limit)
    ]
    jobs = [
        oncall_webhook_replay_job_from_dict(item)
        for item in session_store.list_oncall_webhook_replay_jobs(limit)
    ]
    executions = []
    for job in jobs:
        if job.status != "PENDING":
            continue
        execution = execute_oncall_webhook_replay_job(job, events, patches=patches)
        executions.append(execution)
        session_store.record_oncall_webhook_replay_job(oncall_webhook_replay_job_to_dict(execution.job))
        for event in execution.replayed_events:
            session_store.record_oncall_webhook_event(oncall_webhook_event_to_dict(event))
        for status in execution.statuses:
            session_store.record_oncall_ticket_status(oncall_ticket_status_to_dict(status))
    return executions


def _save_scheduled_closed_loop_snapshot(
    session_store: SessionStore,
    limit: int,
    sla_policy_json: str | None,
    sla_now: str | None,
) -> dict[str, object]:
    trend_alerts = [
        operations_trend_alert_from_dict(item)
        for item in session_store.list_operations_trend_alerts(limit)
    ]
    action_items = [
        operations_action_item_from_dict(item)
        for item in session_store.list_operations_action_items(limit)
    ]
    knowledge_entries = [
        operations_knowledge_entry_from_dict(item)
        for item in session_store.list_operations_knowledge_entries(limit)
    ]
    sla_report = evaluate_operations_action_sla(
        action_items,
        now=sla_now,
    )
    report = build_operations_closed_loop_report(
        trend_alerts=trend_alerts,
        action_items=action_items,
        knowledge_entries=knowledge_entries,
        sla_report=sla_report,
    )
    snapshot = build_operations_closed_loop_snapshot(report)
    session_store.record_operations_closed_loop_snapshot(operations_closed_loop_snapshot_to_dict(snapshot))
    return {"snapshot_id": snapshot.snapshot_id, "closure_rate": snapshot.report.closure_rate}


def _build_operations_schedule_handlers(session_store: SessionStore, args: argparse.Namespace) -> dict[str, Callable[[object], dict[str, object]]]:
    def _load_closed_loop_dashboard() -> object:
        snapshots = [
            operations_closed_loop_snapshot_from_dict(item)
            for item in session_store.list_operations_closed_loop_snapshots(
                max(100, args.closed_loop_dashboard_limit or args.observability_limit)
            )
        ]
        return build_operations_closed_loop_dashboard(
            snapshots,
            limit=args.closed_loop_dashboard_limit or args.observability_limit,
            owner=args.closed_loop_dashboard_owner,
            since=args.closed_loop_dashboard_since,
            cursor=args.closed_loop_dashboard_cursor,
            department=args.closed_loop_dashboard_department,
            tenant=args.closed_loop_dashboard_tenant,
            checkpoint=args.closed_loop_dashboard_checkpoint,
        )

    def _execute_replay_jobs(_: object) -> dict[str, object]:
        executions = _execute_pending_replay_jobs(session_store, args.observability_limit)
        return {
            "executed_jobs": len(executions),
            "failed_jobs": sum(1 for execution in executions if execution.result.failed),
        }

    return {
        "closed_loop_snapshot": lambda task: _save_scheduled_closed_loop_snapshot(
            session_store,
            args.observability_limit,
            args.recovery_approval_sla_policy_json,
            args.recovery_approval_sla_now,
        ),
        "closed_loop_checkpoint": lambda task: {
            "checkpoint": build_operations_closed_loop_checkpoint_plan(_load_closed_loop_dashboard()).next_checkpoint
        },
        "closed_loop_quality": lambda task: {
            "ok": evaluate_operations_closed_loop_quality(_load_closed_loop_dashboard()).ok
        },
        "recovery_approval_sla": lambda task: {
            "findings": len(
                evaluate_recovery_approval_sla(
                    session_store.list_recent(args.observability_limit),
                    policy=build_recovery_approval_sla_policy(args.recovery_approval_sla_policy_json),
                    now=args.recovery_approval_sla_now,
                ).findings
            )
        },
        "webhook_replay_jobs": _execute_replay_jobs,
    }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _latest_recovery_execution_payload(context: TravelContext) -> dict[str, Any] | None:
    for record in reversed(context.recovery_records):
        execution = record.payload.get("strategy_execution") if isinstance(record.payload, dict) else None
        if isinstance(execution, dict):
            return execution
    return None


def _validate_required_trip_args(args: argparse.Namespace) -> None:
    missing = [
        name
        for name in ("origin", "destination", "start", "end", "venue", "purpose")
        if getattr(args, name) is None
    ]
    if missing:
        raise SystemExit(f"Missing required trip arguments: {', '.join('--' + name for name in missing)}")


def render_context(context: TravelContext) -> str:
    lines = [
        f"会话: {context.session_id}",
        f"状态: {context.state}",
        f"流程轮次: {context.workflow_generation}",
        f"目标: {context.task_plan.goal if context.task_plan else '-'}",
        "",
        "任务计划:",
    ]
    if context.task_plan:
        for task in context.task_plan.tasks:
            deps = f" depends_on={','.join(task.depends_on)}" if task.depends_on else ""
            lines.append(f"- {task.task_id}: {task.description}{deps}")
        if context.task_plan.knowledge_refs or context.task_plan.guidance:
            lines.extend(["", "规划知识:"])
            if context.task_plan.knowledge_refs:
                lines.append(f"- 命中知识: {', '.join(context.task_plan.knowledge_refs)}")
            for action in context.task_plan.guidance:
                lines.append(f"- 建议: {action}")

    if context.policy_result:
        lines.extend(
            [
                "",
                "政策结果:",
                f"- 政策: {context.policy_result.policy_id}",
                f"- 来源: {context.policy_result.source}",
                f"- 酒店预算上限: {context.policy_result.approved_budget}",
                f"- 是否合规: {context.policy_result.compliant}",
            ]
        )
        for reason in context.policy_result.reasons:
            lines.append(f"- 说明: {reason}")

    if context.transport_policy_result:
        lines.extend(
            [
                "",
                "交通政策:",
                f"- 政策: {context.transport_policy_result.policy_id}",
                f"- 来源: {context.transport_policy_result.source}",
                f"- 交通预算上限: {context.transport_policy_result.max_transport_price}",
                f"- 允许舱等/座席: {', '.join(context.transport_policy_result.allowed_seat_classes)}",
                f"- 是否合规: {context.transport_policy_result.compliant}",
            ]
        )
        for reason in context.transport_policy_result.reasons:
            lines.append(f"- 说明: {reason}")

    if context.itinerary:
        lines.extend(
            [
                "",
                "行程草案:",
                f"- {context.itinerary.summary}",
                f"- 入住: {context.itinerary.check_in.isoformat()}",
                f"- 离店: {context.itinerary.check_out.isoformat()}",
            ]
        )
        for item in context.itinerary.agenda:
            lines.append(f"- {item}")

    if context.hotel_options:
        lines.extend(["", "酒店推荐:"])
        for hotel in context.hotel_options:
            lines.append(
                f"- {hotel.hotel_id} {hotel.name} | {hotel.nightly_price}/晚 | "
                f"{hotel.distance_km}km | 评分 {hotel.rating} | 合规 {hotel.policy_compliant} | 来源 {hotel.source}"
            )

    if context.transport_options:
        lines.extend(["", "交通推荐:"])
        for option in context.transport_options:
            lines.append(
                f"- {option.transport_id} {option.mode}/{option.provider} | {option.origin_city}->{option.destination_city} | "
                f"{option.depart_at}->{option.arrive_at} | {option.seat_class} | {option.price} | "
                f"合规 {option.policy_compliant} | 来源 {option.source}"
            )

    if context.selected_hotel:
        lines.extend(["", "已确认酒店:", f"- {context.selected_hotel.hotel_id} {context.selected_hotel.name}"])

    if context.selected_transport:
        lines.extend(
            [
                "",
                "已确认交通:",
                f"- {context.selected_transport.transport_id} {context.selected_transport.mode}/{context.selected_transport.provider}",
            ]
        )

    if context.approval:
        lines.extend(
            [
                "",
                "审批记录:",
                f"- 审批单: {context.approval.approval_id}",
                f"- 状态: {context.approval.status}",
                f"- 来源: {context.approval.source}",
            ]
        )

    if context.approval_cancellation:
        lines.extend(
            [
                "",
                "审批补偿:",
                f"- 动作: {context.approval_cancellation.action}",
                f"- 目标: {context.approval_cancellation.target_id}",
                f"- 状态: {context.approval_cancellation.status}",
                f"- 来源: {context.approval_cancellation.source}",
            ]
        )

    if context.inventory_lock:
        lines.extend(
            [
                "",
                "库存锁定:",
                f"- 锁定单: {context.inventory_lock.lock_id}",
                f"- 酒店: {context.inventory_lock.hotel_id}",
                f"- 状态: {context.inventory_lock.status}",
                f"- 过期时间: {context.inventory_lock.expires_at}",
                f"- 来源: {context.inventory_lock.source}",
            ]
        )

    if context.price_check:
        lines.extend(
            [
                "",
                "价格校验:",
                f"- 酒店: {context.price_check.hotel_id}",
                f"- 状态: {context.price_check.status}",
                f"- 原价: {context.price_check.original_price}",
                f"- 当前价: {context.price_check.current_price}",
                f"- 合规: {context.price_check.policy_compliant}",
                f"- 需要确认: {context.price_check.requires_confirmation}",
                f"- 来源: {context.price_check.source}",
            ]
        )

    if context.order:
        lines.extend(
            [
                "",
                "酒店订单:",
                f"- 订单号: {context.order.order_id}",
                f"- 状态: {context.order.status}",
                f"- 金额: {context.order.total_amount} {context.order.currency}",
                f"- 来源: {context.order.source}",
            ]
        )

    if context.transport_order:
        lines.extend(
            [
                "",
                "交通订单:",
                f"- 订单号: {context.transport_order.order_id}",
                f"- 状态: {context.transport_order.status}",
                f"- 金额: {context.transport_order.total_amount} {context.transport_order.currency}",
                f"- 来源: {context.transport_order.source}",
            ]
        )

    if context.order_cancellation:
        lines.extend(
            [
                "",
                "订单补偿:",
                f"- 动作: {context.order_cancellation.action}",
                f"- 目标: {context.order_cancellation.target_id}",
                f"- 状态: {context.order_cancellation.status}",
                f"- 来源: {context.order_cancellation.source}",
            ]
        )

    if context.transport_order_cancellation:
        lines.extend(
            [
                "",
                "交通订单补偿:",
                f"- 动作: {context.transport_order_cancellation.action}",
                f"- 目标: {context.transport_order_cancellation.target_id}",
                f"- 状态: {context.transport_order_cancellation.status}",
                f"- 来源: {context.transport_order_cancellation.source}",
            ]
        )

    if context.inventory_release:
        lines.extend(
            [
                "",
                "库存补偿:",
                f"- 动作: {context.inventory_release.action}",
                f"- 目标: {context.inventory_release.target_id}",
                f"- 状态: {context.inventory_release.status}",
                f"- 来源: {context.inventory_release.source}",
            ]
        )

    if context.refund_estimates:
        lines.extend(["", "退款预估:"])
        for estimate in context.refund_estimates:
            lines.append(
                f"- {estimate.target_type} {estimate.target_id} | 可退 {estimate.refundable_amount} "
                f"{estimate.currency} | 手续费 {estimate.penalty_amount} | 来源 {estimate.source}"
            )

    if context.change_approvals:
        lines.extend(["", "改签审批:"])
        for approval in context.change_approvals:
            lines.append(f"- {approval.approval_id} | {approval.status} | 来源 {approval.source}")

    if context.refund_confirmations:
        lines.extend(["", "退款确认:"])
        for confirmation in context.refund_confirmations:
            lines.append(
                f"- {confirmation.target_type} {confirmation.target_id} | {confirmation.status} | "
                f"确认退款 {confirmation.confirmed_amount} {confirmation.currency} | 来源 {confirmation.source}"
            )

    if context.change_records:
        lines.extend(["", "改签记录:"])
        for record in context.change_records:
            lines.append(
                f"- {record.target_type} {record.target_id} | {record.status} | "
                f"手续费 {record.penalty_amount} {record.currency} | 来源 {record.source}"
            )

    if context.change_failure_compensations:
        lines.extend(["", "改签失败补偿:"])
        for result in context.change_failure_compensations:
            lines.append(
                f"- 动作: {result.action} | 目标: {result.target_id} | 状态: {result.status} | 来源 {result.source}"
            )

    if context.calendar_syncs:
        lines.extend(["", "日历同步:"])
        for record in context.calendar_syncs:
            lines.append(
                f"- {record.event_type} | {record.calendar_event_id} | {record.status} | "
                f"{record.start_at}->{record.end_at} | 重试 {record.retry_count}/{record.max_retries} | 来源 {record.source}"
            )
            if record.attendees:
                lines.append(f"  参会人: {', '.join(record.attendees)}")
            if record.last_error:
                lines.append(f"  错误: {record.last_error}")

    if context.notifications:
        lines.extend(["", "通知:"])
        for notification in context.notifications:
            lines.append(
                f"- {notification.event_type} | {notification.channel} | "
                f"{notification.status} | {notification.title} | 来源 {notification.source}"
            )

    if context.recovery_records:
        lines.extend(["", "恢复记录:"])
        for record in context.recovery_records:
            lines.append(
                f"- {record.recovery_id} | {record.action} | {record.from_state}->{record.to_state} | "
                f"原因 {record.reason} | 来源 {record.source}"
            )

    if context.agent_executions:
        lines.extend(["", "Agent 执行摘要:"])
        for record in context.agent_executions:
            lines.append(
                f"- {record.agent_name}.{record.action} | {record.status} | "
                f"轮次 {record.input_refs.get('workflow_generation', '-')} | {record.message}"
            )

    lines.extend(["", "事件:"])
    lines.extend(f"- {event}" for event in context.events)
    return "\n".join(lines)


if __name__ == "__main__":
    main()
