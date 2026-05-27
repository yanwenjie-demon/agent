from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from time import sleep
from uuid import uuid4

from .agent import TravelAgent
from .models import TravelContext, WorkerRunRecord
from .release_control import RolloutPolicy, evaluate_rollout
from .state import TravelState


AUTO_ADVANCE_STATES = {
    TravelState.APPROVAL_CREATED.value,
    TravelState.APPROVAL_APPROVED.value,
    TravelState.COMPLETED.value,
    TravelState.ORDER_CREATED.value,
}


RECOVERY_STATES = {
    TravelState.APPROVAL_REJECTED.value,
    TravelState.PRICE_CHANGED.value,
    TravelState.INVENTORY_EXPIRED.value,
    TravelState.ORDER_FAILED.value,
}


@dataclass(frozen=True)
class WorkflowRunResult:
    scanned: int
    advanced: int
    skipped: int
    errors: dict[str, str] = field(default_factory=dict)
    session_ids: list[str] = field(default_factory=list)
    run_id: str | None = None
    started_at: str | None = None
    finished_at: str | None = None


@dataclass(frozen=True)
class WorkflowLoopResult:
    iterations: int
    scanned: int
    advanced: int
    skipped: int
    errors: dict[str, str] = field(default_factory=dict)
    run_ids: list[str] = field(default_factory=list)


class WorkflowWorker:
    def __init__(
        self,
        agent: TravelAgent,
        auto_recover: bool = False,
        recovery_approval_override: bool = False,
        recovery_reason: str = "worker_auto_recovery",
        recovery_rollout_policy: RolloutPolicy | None = None,
        recovery_approved_by: str = "workflow-worker",
    ) -> None:
        self.agent = agent
        self.auto_recover = auto_recover
        self.recovery_approval_override = recovery_approval_override
        self.recovery_reason = recovery_reason
        self.recovery_rollout_policy = recovery_rollout_policy
        self.recovery_approved_by = recovery_approved_by

    def run_once(self, limit: int = 50) -> WorkflowRunResult:
        run_id = "WRK-" + uuid4().hex[:12].upper()
        started_at = _utc_now()
        contexts = self._contexts_to_process(limit)
        advanced = 0
        skipped = 0
        errors: dict[str, str] = {}
        session_ids: list[str] = []

        for context in contexts:
            before_state = context.state
            before_event_count = len(context.events)
            try:
                updated = self.advance(context)
                updated = self.agent.notify_current_state(updated)
                updated = self._retry_calendar_syncs(updated)
                session_ids.append(updated.session_id)
                if updated.state != before_state or len(updated.events) != before_event_count:
                    advanced += 1
                else:
                    skipped += 1
            except Exception as exc:
                errors[context.session_id] = str(exc)

        finished_at = _utc_now()
        self.agent.session_store.record_worker_run(
            WorkerRunRecord(
                run_id=run_id,
                started_at=started_at,
                finished_at=finished_at,
                scanned=len(contexts),
                advanced=advanced,
                skipped=skipped,
                errors=errors,
                session_ids=session_ids,
            )
        )
        return WorkflowRunResult(
            scanned=len(contexts),
            advanced=advanced,
            skipped=skipped,
            errors=errors,
            session_ids=session_ids,
            run_id=run_id,
            started_at=started_at,
            finished_at=finished_at,
        )

    def run_loop(
        self,
        iterations: int = 1,
        interval_seconds: float = 0.0,
        limit: int = 50,
    ) -> WorkflowLoopResult:
        total_scanned = 0
        total_advanced = 0
        total_skipped = 0
        errors: dict[str, str] = {}
        run_ids: list[str] = []

        for index in range(iterations):
            result = self.run_once(limit=limit)
            total_scanned += result.scanned
            total_advanced += result.advanced
            total_skipped += result.skipped
            errors.update(result.errors)
            if result.run_id:
                run_ids.append(result.run_id)
            if interval_seconds > 0 and index < iterations - 1:
                sleep(interval_seconds)

        return WorkflowLoopResult(
            iterations=iterations,
            scanned=total_scanned,
            advanced=total_advanced,
            skipped=total_skipped,
            errors=errors,
            run_ids=run_ids,
        )

    def advance(self, context: TravelContext) -> TravelContext:
        if context.state == TravelState.APPROVAL_CREATED.value:
            context = self.agent.refresh_approval_status(context)
            if context.state == TravelState.APPROVAL_APPROVED.value:
                context = self.agent.book_after_approval(context)
            return context

        if context.state == TravelState.APPROVAL_APPROVED.value:
            return self.agent.book_after_approval(context)

        if context.state in {TravelState.ORDER_CREATED.value, TravelState.COMPLETED.value} and context.order is not None:
            return self.agent.refresh_order_status(context)

        if self.auto_recover and context.state in RECOVERY_STATES:
            rollout = self._evaluate_recovery_rollout(context)
            if rollout is not None and not rollout.enabled:
                context.append_event(
                    f"Worker recovery rollout skipped: {rollout.status}; {'; '.join(rollout.reasons)}."
                )
                self.agent.session_store.save(context)
                return context
            if self._recovery_blocked_without_override(context):
                return context
            return self.agent.execute_recovery_strategy(
                context,
                reason=self.recovery_reason,
                enforce_strategy_gate=True,
                approval_override=self.recovery_approval_override,
                approved_by=self.recovery_approved_by,
                approval_reason=self.recovery_reason,
            )

        context.append_event(f"Worker skipped state: {context.state}.")
        self.agent.session_store.save(context)
        return context

    def _retry_calendar_syncs(self, context: TravelContext) -> TravelContext:
        retryable = [
            record
            for record in context.calendar_syncs
            if record.status == "FAILED" and record.retry_count < record.max_retries
        ]
        for record in retryable:
            context = self.agent.sync_calendar(
                context,
                event_type=record.event_type,
                attendees=record.attendees,
                existing=record,
            )
        return context

    def _contexts_to_process(self, limit: int) -> list[TravelContext]:
        states = set(AUTO_ADVANCE_STATES)
        if self.auto_recover:
            states.update(RECOVERY_STATES)
        contexts = self.agent.session_store.list_by_states(states, limit)
        seen = {context.session_id for context in contexts}
        if len(contexts) >= limit:
            return contexts

        all_candidates = self.agent.session_store.list_by_states(
            {state.value for state in TravelState},
            limit,
        )
        for context in all_candidates:
            if context.session_id in seen:
                continue
            if self._has_retryable_notification(context) or self._has_retryable_calendar_sync(context):
                contexts.append(context)
                seen.add(context.session_id)
            if len(contexts) >= limit:
                break
        return contexts

    @staticmethod
    def _has_retryable_notification(context: TravelContext) -> bool:
        return any(
            notification.status == "FAILED" and notification.retry_count < notification.max_retries
            for notification in context.notifications
        )

    @staticmethod
    def _has_retryable_calendar_sync(context: TravelContext) -> bool:
        return any(
            record.status == "FAILED" and record.retry_count < record.max_retries
            for record in context.calendar_syncs
        )

    def _recovery_blocked_without_override(self, context: TravelContext) -> bool:
        if self.recovery_approval_override:
            return False
        for record in reversed(context.recovery_records):
            if record.to_state != context.state:
                continue
            execution = record.payload.get("strategy_execution")
            if not isinstance(execution, dict):
                continue
            return execution.get("status") == "BLOCKED"
        return False

    def _evaluate_recovery_rollout(self, context: TravelContext):
        if self.recovery_rollout_policy is None:
            return None
        return evaluate_rollout(
            self.recovery_rollout_policy,
            user_id=context.request.user_id,
            department=context.request.department,
            scenario="worker_auto_recovery",
        )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
