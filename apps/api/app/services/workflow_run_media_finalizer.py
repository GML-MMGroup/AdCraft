from __future__ import annotations


from app.schemas.workflow_nodes import (
    WorkflowRunRequest,
)


class WorkflowRunMediaFinalizerMixin:
    def _post_run_media_status(self, workflow_id: str, request: WorkflowRunRequest):
        if request.download_media or request.compose_when_ready:
            return self._media_tasks.poll_media(
                workflow_id,
                download_media=request.download_media,
                compose_when_ready=request.compose_when_ready,
            )
        return self._media_tasks.media_status(workflow_id)
