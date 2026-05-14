from __future__ import annotations

import argparse
from datetime import date

from .agent import build_default_agent
from .config import IntegrationSettings
from .models import TravelContext, TravelRequest
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
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = IntegrationSettings.from_env()
    if args.session_db:
        settings = _replace_session_db(settings, args.session_db)

    agent = build_default_agent(settings=settings)
    if args.run_worker_once:
        if not settings.session_db_path:
            raise SystemExit("--run-worker-once requires --session-db or TRAVEL_SESSION_DB_PATH.")
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
    )

    if args.auto_book:
        context = agent.run_to_order(request, args.hotel_id)
    else:
        context = agent.plan(request)
    if not args.auto_book and (args.auto_confirm or args.hotel_id):
        context = agent.confirm_and_create_approval(context, args.hotel_id)
    if args.cancel_after_book:
        context = agent.cancel_trip(context, args.cancel_reason)
    context = agent.notify_current_state(context)

    print(render_context(context))


def render_worker_result(result: WorkflowRunResult) -> str:
    lines = [
        "Worker result:",
        f"- scanned: {result.scanned}",
        f"- advanced: {result.advanced}",
        f"- skipped: {result.skipped}",
        f"- errors: {len(result.errors)}",
    ]
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
    for session_id, error in result.errors.items():
        lines.append(f"- error {session_id}: {error}")
    return "\n".join(lines)


def _replace_session_db(settings: IntegrationSettings, session_db_path: str) -> IntegrationSettings:
    return IntegrationSettings(
        policy_api_url=settings.policy_api_url,
        hotel_inventory_api_url=settings.hotel_inventory_api_url,
        hotel_price_check_api_url=settings.hotel_price_check_api_url,
        hotel_inventory_lock_api_url=settings.hotel_inventory_lock_api_url,
        hotel_inventory_release_api_url=settings.hotel_inventory_release_api_url,
        oa_approval_api_url=settings.oa_approval_api_url,
        oa_approval_status_api_url=settings.oa_approval_status_api_url,
        order_api_url=settings.order_api_url,
        order_status_api_url=settings.order_status_api_url,
        order_cancel_api_url=settings.order_cancel_api_url,
        notification_api_url=settings.notification_api_url,
        policy_api_token=settings.policy_api_token,
        hotel_inventory_api_token=settings.hotel_inventory_api_token,
        oa_approval_api_token=settings.oa_approval_api_token,
        order_api_token=settings.order_api_token,
        notification_api_token=settings.notification_api_token,
        use_mock_fallback=settings.use_mock_fallback,
        notification_use_mock_fallback=settings.notification_use_mock_fallback,
        timeout_seconds=settings.timeout_seconds,
        session_db_path=session_db_path,
    )


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

    if context.selected_hotel:
        lines.extend(["", "已确认酒店:", f"- {context.selected_hotel.hotel_id} {context.selected_hotel.name}"])

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
                "订单:",
                f"- 订单号: {context.order.order_id}",
                f"- 状态: {context.order.status}",
                f"- 金额: {context.order.total_amount} {context.order.currency}",
                f"- 来源: {context.order.source}",
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

    if context.notifications:
        lines.extend(["", "通知:"])
        for notification in context.notifications:
            lines.append(
                f"- {notification.event_type} | {notification.channel} | "
                f"{notification.status} | {notification.title} | 来源 {notification.source}"
            )

    lines.extend(["", "事件:"])
    lines.extend(f"- {event}" for event in context.events)
    return "\n".join(lines)


if __name__ == "__main__":
    main()
