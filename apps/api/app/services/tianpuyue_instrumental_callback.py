"""Callback wake-up handling for Tianpuyue instrumental provider tasks."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.schemas.tianpuyue_pure_music import TianpuyueInstrumentalCallbackRequest
from app.services.v2_provider_task_service import V2ProviderTaskService


@dataclass(frozen=True)
class TianpuyueInstrumentalCallbackAcceptance:
    matched_task_ids: list[str]


class TianpuyueInstrumentalCallbackService:
    def __init__(self, data_dir: Path) -> None:
        self._tasks = V2ProviderTaskService(data_dir)

    def accept(
        self,
        workflow_id: str,
        callback_id: str,
        payload: TianpuyueInstrumentalCallbackRequest,
    ) -> TianpuyueInstrumentalCallbackAcceptance:
        matched_task_ids: list[str] = []
        for record in payload.instrumentals:
            task = self._tasks.wake_task_for_callback(
                workflow_id,
                provider="tianpuyue",
                callback_id=callback_id,
                remote_task_id=record.item_id,
            )
            if task is not None and task.task_id not in matched_task_ids:
                matched_task_ids.append(task.task_id)
        return TianpuyueInstrumentalCallbackAcceptance(matched_task_ids=matched_task_ids)
