from __future__ import annotations

from dataclasses import dataclass

from .governance import ReleaseReadinessReport, render_release_readiness_report


@dataclass(frozen=True)
class ReleaseGateResult:
    passed: bool
    exit_code: int
    report: ReleaseReadinessReport


def evaluate_release_gate(report: ReleaseReadinessReport, allow_action_required: bool = False) -> ReleaseGateResult:
    if report.status == "PASS":
        return ReleaseGateResult(passed=True, exit_code=0, report=report)
    if report.status == "ACTION_REQUIRED" and allow_action_required:
        return ReleaseGateResult(passed=True, exit_code=0, report=report)
    return ReleaseGateResult(passed=False, exit_code=2 if report.status == "ACTION_REQUIRED" else 1, report=report)


def render_release_gate_result(result: ReleaseGateResult) -> str:
    lines = [
        "Release gate:",
        f"- passed: {result.passed}",
        f"- exit_code: {result.exit_code}",
        render_release_readiness_report(result.report),
    ]
    return "\n".join(lines)
