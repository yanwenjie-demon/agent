from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from .data_governance import AuditSink, AuditSinkResult, GovernanceAuditEvent, build_audit_event


ToolHandler = Callable[..., Any]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    required: tuple[str, ...]
    handler: ToolHandler


@dataclass(frozen=True)
class ToolCallLog:
    tool_name: str
    input_keys: tuple[str, ...]
    ok: bool
    error: str | None = None


class ToolValidationError(ValueError):
    pass


@dataclass
class ToolGateway:
    _tools: dict[str, ToolSpec] = field(default_factory=dict)
    call_logs: list[ToolCallLog] = field(default_factory=list)
    audit_events: list[GovernanceAuditEvent] = field(default_factory=list)
    audit_sink: AuditSink | None = None
    audit_sink_results: list[AuditSinkResult] = field(default_factory=list)

    def register(
        self,
        name: str,
        description: str,
        required: tuple[str, ...],
        handler: ToolHandler,
    ) -> None:
        if name in self._tools:
            raise ToolValidationError(f"Tool already registered: {name}")
        self._tools[name] = ToolSpec(
            name=name,
            description=description,
            required=required,
            handler=handler,
        )

    def call(self, name: str, **kwargs: Any) -> Any:
        spec = self._tools.get(name)
        if spec is None:
            raise ToolValidationError(f"Unknown tool: {name}")

        self._record_audit_event(build_audit_event(name, kwargs))
        try:
            self._validate(spec, kwargs)
            result = spec.handler(**kwargs)
            self.call_logs.append(
                ToolCallLog(tool_name=name, input_keys=tuple(sorted(kwargs.keys())), ok=True)
            )
            return result
        except Exception as exc:
            self.call_logs.append(
                ToolCallLog(
                    tool_name=name,
                    input_keys=tuple(sorted(kwargs.keys())),
                    ok=False,
                    error=str(exc),
                )
            )
            raise

    @staticmethod
    def _validate(spec: ToolSpec, kwargs: dict[str, Any]) -> None:
        missing = [key for key in spec.required if key not in kwargs or kwargs[key] in (None, "")]
        if missing:
            raise ToolValidationError(f"Missing required parameters for {spec.name}: {', '.join(missing)}")

    def _record_audit_event(self, event: GovernanceAuditEvent) -> None:
        self.audit_events.append(event)
        if self.audit_sink is None:
            return
        self.audit_sink_results.append(self.audit_sink.write([event]))
