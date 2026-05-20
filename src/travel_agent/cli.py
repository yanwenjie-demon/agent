from __future__ import annotations

import argparse
import json
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from typing import Callable
from urllib.parse import urlsplit

from .agent import build_default_agent
from .acceptance import render_integration_acceptance_report, run_integration_acceptance_report
from .config import IntegrationSettings
from .evaluation import render_evaluation_report, run_evaluation_suite
from .governance import render_release_readiness_report, run_release_readiness_report
from .models import DeadLetterCalendarSync, DeadLetterNotification, TravelContext, TravelRequest, WorkerRunRecord
from .observability import build_otlp_payloads, export_otlp_http
from .operations import (
    build_alert_route_rules,
    build_operations_dashboard,
    build_operations_dashboard_snapshot,
    build_operations_dashboard_trend_report,
    build_operations_action_sla_policy,
    build_operations_closed_loop_report,
    build_operations_knowledge_entries,
    build_operations_multidimensional_view,
    build_operations_postmortem_report,
    build_operations_trend_alert_rules,
    build_postmortem_action_items,
    build_trend_alert_action_items,
    close_operations_action_item,
    evaluate_operations_action_sla,
    evaluate_operations_drill_gate,
    evaluate_operations_trend_alerts,
    export_operations_alerts_http,
    fetch_oncall_ticket_status_http,
    open_oncall_ticket_http,
    oncall_ticket_status_from_dict,
    oncall_ticket_status_to_dict,
    operations_action_item_from_dict,
    operations_action_item_to_dict,
    operations_dashboard_snapshot_from_dict,
    operations_dashboard_snapshot_to_dict,
    operations_knowledge_entry_from_dict,
    operations_knowledge_entry_to_dict,
    operations_trend_alert_from_dict,
    operations_trend_alert_to_dict,
    render_operations_alert_export_result,
    render_operations_alerts,
    render_operations_alerts_json,
    render_operations_alerts_prometheus,
    build_operations_drill_report,
    build_operations_runbook,
    render_alert_route_rules,
    render_alert_route_rules_json,
    render_operations_action_items,
    render_operations_action_sla_report,
    render_operations_closed_loop_report,
    render_operations_dashboard_snapshots,
    render_operations_dashboard_trend_report,
    render_operations_knowledge_entries,
    render_operations_knowledge_search_report,
    render_operations_multidimensional_view,
    render_operations_postmortem_report,
    render_operations_trend_alerts,
    render_operations_trend_alerts_json,
    search_operations_knowledge,
    render_oncall_ticket_status,
    render_oncall_ticket_result,
    render_operations_dashboard,
    render_operations_drill_gate_result,
    render_operations_drill_report,
    render_operations_runbook,
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
    if args.list_operations_dashboard_snapshots:
        _require_persistent_session_store(settings, "--list-operations-dashboard-snapshots")
        snapshots = [
            operations_dashboard_snapshot_from_dict(item)
            for item in agent.session_store.list_operations_dashboard_snapshots(args.observability_limit)
        ]
        print(render_operations_dashboard_snapshots(snapshots))
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
    if args.operations_action_sla:
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
        return
    if args.operations_closed_loop_report:
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
        print(render_operations_closed_loop_report(report))
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
    if args.replan_session:
        context = agent.get_session(args.replan_session)
        context = agent.replan_after_exception(context, reason=args.replan_reason)
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
        if args.worker_iterations <= 1:
            result = WorkflowWorker(agent).run_once(limit=args.worker_limit)
            print(render_worker_result(result))
        else:
            result = WorkflowWorker(agent).run_loop(
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


def make_metrics_handler(metrics_provider: Callable[[], str]) -> type[BaseHTTPRequestHandler]:
    class MetricsHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            path = urlsplit(self.path).path
            if path == "/health":
                self._send_text("ok\n", "text/plain; charset=utf-8")
                return
            if path == "/metrics":
                self._send_text(metrics_provider() + "\n", "text/plain; version=0.0.4; charset=utf-8")
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


def run_metrics_server_in_thread(server: ThreadingHTTPServer) -> Thread:
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return thread


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
