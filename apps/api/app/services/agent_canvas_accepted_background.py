"""Private no-throw boundary for already accepted Agent Canvas work."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from time import monotonic
from typing import Any


logger = logging.getLogger(__name__)


class AcceptedBackgroundOperation(str, Enum):
    VARIATION_EXECUTION_RESUME = "variation_execution_resume"
    EDITING_EXPORT_RESUME = "editing_export_resume"
    CHAT_TURN_PROCESS = "chat_turn_process"
    GUIDANCE_RETRY_TURN_PROCESS = "guidance_retry_turn_process"
    GUIDANCE_CONTINUATION_DRAIN = "guidance_continuation_drain"
    DECISION_BUNDLE_TURN_PROCESS = "decision_bundle_turn_process"
    FAILED_TURN_RETRY_PROCESS = "failed_turn_retry_process"
    PROPOSAL_TURN_PROCESS = "proposal_turn_process"
    COMMAND_PLAN_TURN_PROCESS = "command_plan_turn_process"
    GUIDED_ACTION_TURN_PROCESS = "guided_action_turn_process"
    GUIDED_INTERACTION_SUBMIT = "guided_interaction_submit"
    GUIDED_MEDIA_CONFIRMATION_RESUME = "guided_media_confirmation_resume"
    CANVAS_RUN_RESUME = "canvas_run_resume"


class AcceptedBackgroundResourceType(str, Enum):
    TURN = "turn"
    EXECUTION = "execution"
    EDITING_EXPORT = "editing_export"
    INTERACTION = "interaction"
    DELIVERY = "delivery"


@dataclass(frozen=True)
class AcceptedBackgroundWork:
    """One immutable invocation for work that is already durably accepted."""

    operation: AcceptedBackgroundOperation
    workflow_id: str
    resource_type: AcceptedBackgroundResourceType
    resource_id: str
    callback: Callable[..., Any] = field(repr=False, compare=False)
    args: tuple[Any, ...] = field(default=(), repr=False, compare=False)
    kwargs: tuple[tuple[str, Any], ...] = field(default=(), repr=False, compare=False)


@dataclass(frozen=True)
class AcceptedBackgroundDiagnostic:
    """Bounded operational metadata for one contained callback exception."""

    operation: AcceptedBackgroundOperation
    workflow_id: str
    resource_type: AcceptedBackgroundResourceType
    resource_id: str
    code: str
    exception_class: str
    elapsed_ms: int


class AgentCanvasAcceptedBackgroundRunner:
    """Invoke accepted work once and contain ordinary callback exceptions."""

    def __init__(
        self,
        *,
        diagnostic_writer: Callable[[AcceptedBackgroundDiagnostic], None] | None = None,
        monotonic: Callable[[], float] = monotonic,
    ) -> None:
        self._diagnostic_writer = diagnostic_writer or _write_diagnostic
        self._monotonic = monotonic

    def run(self, work: AcceptedBackgroundWork) -> None:
        started_at = self._monotonic()
        try:
            work.callback(*work.args, **dict(work.kwargs))
        except Exception as error:
            elapsed_ms = max(0, int((self._monotonic() - started_at) * 1_000))
            self._diagnostic_writer(
                AcceptedBackgroundDiagnostic(
                    operation=work.operation,
                    workflow_id=work.workflow_id,
                    resource_type=work.resource_type,
                    resource_id=work.resource_id,
                    code="accepted_background_callback_failed",
                    exception_class=type(error).__name__,
                    elapsed_ms=elapsed_ms,
                )
            )


def _write_diagnostic(diagnostic: AcceptedBackgroundDiagnostic) -> None:
    logger.error(
        "Agent Canvas accepted background callback failed "
        "operation=%s workflow_id=%s resource_type=%s resource_id=%s "
        "code=%s exception_class=%s elapsed_ms=%s",
        diagnostic.operation.value,
        diagnostic.workflow_id,
        diagnostic.resource_type.value,
        diagnostic.resource_id,
        diagnostic.code,
        diagnostic.exception_class,
        diagnostic.elapsed_ms,
    )
