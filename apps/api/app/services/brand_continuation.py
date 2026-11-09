"""Resume durable Brand work without reinterpreting choices or retrying model failures."""

from __future__ import annotations

from collections.abc import Callable
import logging
import time
from typing import Any

from app.persistence.agent_canvas_conversation_repository import AgentCanvasConversationRepository
from app.persistence.brand_continuation_repository import BrandContinuationRepository
from app.persistence.database import V2Database
from app.persistence.errors import V2PersistenceError
from app.persistence.event_repository import EventRepository

logger = logging.getLogger(__name__)


class BrandContinuationWorker:
    def __init__(
        self, database: V2Database, *, publish: Callable[[str], Any] | None = None
    ) -> None:
        self.database = database
        self.repository = BrandContinuationRepository(database)
        self.publish = publish or self._publish

    def _publish(self, workflow_id: str) -> Any:
        from app.api.v2.endpoints.brand_mode import _prepare_next_question

        return _prepare_next_question(workflow_id, self.database)

    def run_workflow(
        self, workflow_id: str, *, retry_failed: bool = False, join_running: bool = False
    ) -> Any:
        work_id = self.repository.ensure_current(workflow_id)
        if work_id is None:
            return self.publish(workflow_id)
        claim = self.repository.claim(work_id, retry_failed=retry_failed)
        if claim is not None:
            return self._run(claim)
        row = self.repository.get(work_id)
        if join_running:
            while row["status"] == "running" and row["lease_until"] > int(time.time()):
                time.sleep(0.05)
                row = self.repository.get(work_id)
        if row["status"] == "completed":
            # The current card was already published; the existing endpoint reuses it.
            return self.publish(workflow_id)
        raise V2PersistenceError(
            "brand_form_generation_in_progress"
            if row["status"] == "running"
            else "brand_treatment_expansion_retry_required"
            if row["status"] == "failed"
            else "brand_context_stale",
            "The current Brand step is running or requires a retry. Confirmed choices are preserved.",
        )

    def run_once(self) -> bool:
        for work_id in self.repository.due():
            claim = self.repository.claim(work_id)
            if claim is None:
                continue
            try:
                self._run(claim)
            except Exception:
                # Failure is terminal for this attempt; polling never retries it.
                logger.exception("Brand continuation failed work_id=%s", work_id)
            return True
        return False

    def _run(self, claim: dict[str, Any]) -> Any:
        try:
            result = self.publish(claim["workflow_id"])
        except Exception as error:
            detail = getattr(error, "detail", None)
            code = (detail.get("code") if isinstance(detail, dict) else None) or getattr(
                error, "code", None
            )
            code = code[:160] if isinstance(code, str) else "brand_interaction_publication_failed"
            if self.repository.finish(claim, error_code=code):
                AgentCanvasConversationRepository(
                    self.database, EventRepository(self.database)
                ).record_brand_interaction_publication_failure(
                    claim["workflow_id"],
                    failure_id=f"{claim['work_id']}:{claim['attempt_count']}",
                    error_code=code,
                    retryable=code != "brand_context_stale",
                )
            raise
        if not self.repository.finish(claim):
            raise V2PersistenceError("brand_context_stale", "Brand continuation ownership expired.")
        return result
