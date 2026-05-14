from __future__ import annotations

from dataclasses import dataclass, field
from time import sleep

from .agent import TravelAgent
from .models import TravelContext
from .state import TravelState


AUTO_ADVANCE_STATES = {
    TravelState.APPROVAL_CREATED.value,
    TravelState.APPROVAL_APPROVED.value,
    TravelState.COMPLETED.value,
    TravelState.ORDER_CREATED.value,
}


@dataclass(frozen=True)
class WorkflowRunResult:
    scanned: int
    advanced: int
    skipped: int
    errors: dict[str, str] = field(default_factory=dict)
    session_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class WorkflowLoopResult:
    iterations: int
    scanned: int
    advanced: int
    skipped: int
    errors: dict[str, str] = field(default_factory=dict)


class WorkflowWorker:
    def __init__(self, agent: TravelAgent) -> None:
        self.agent = agent

    def run_once(self, limit: int = 50) -> WorkflowRunResult:
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
                session_ids.append(updated.session_id)
                if updated.state != before_state or len(updated.events) != before_event_count:
                    advanced += 1
                else:
                    skipped += 1
            except Exception as exc:
                errors[context.session_id] = str(exc)

        return WorkflowRunResult(
            scanned=len(contexts),
            advanced=advanced,
            skipped=skipped,
            errors=errors,
            session_ids=session_ids,
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

        for index in range(iterations):
            result = self.run_once(limit=limit)
            total_scanned += result.scanned
            total_advanced += result.advanced
            total_skipped += result.skipped
            errors.update(result.errors)
            if interval_seconds > 0 and index < iterations - 1:
                sleep(interval_seconds)

        return WorkflowLoopResult(
            iterations=iterations,
            scanned=total_scanned,
            advanced=total_advanced,
            skipped=total_skipped,
            errors=errors,
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

        context.append_event(f"Worker skipped state: {context.state}.")
        self.agent.session_store.save(context)
        return context

    def _contexts_to_process(self, limit: int) -> list[TravelContext]:
        contexts = self.agent.session_store.list_by_states(AUTO_ADVANCE_STATES, limit)
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
            if self._has_retryable_notification(context):
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
