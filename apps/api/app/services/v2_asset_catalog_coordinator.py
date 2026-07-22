"""Application-owned background coordination for one pinned catalog install."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from threading import Lock

from app.schemas.v2_asset_library import RecommendedCatalogStatusResponseV2
from app.services.v2_asset_catalog import V2AssetCatalogService


class V2AssetCatalogCoordinator:
    """Ensure one lifespan-owned installation job exists for a pinned catalog."""

    def __init__(self, service: V2AssetCatalogService) -> None:
        self._service = service
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="v2-catalog")
        self._lock = Lock()
        self._future: Future[RecommendedCatalogStatusResponseV2] | None = None

    def get_recommended_status(self) -> RecommendedCatalogStatusResponseV2:
        """Read durable installation status without starting a background operation."""

        return self._service.get_recommended_status()

    def start_recommended_install(self) -> RecommendedCatalogStatusResponseV2:
        """Start at most one installation job and return its current durable state."""

        manifest, status = self._service.prepare_recommended_install()
        if status.status == "ready":
            return status
        with self._lock:
            if self._future is None or self._future.done():
                self._future = self._executor.submit(
                    self._service.install_prepared_catalog, manifest
                )
        return self._service.get_recommended_status()

    def wait_for_idle(self) -> RecommendedCatalogStatusResponseV2 | None:
        """Wait for the current job; tests use this instead of time-based polling."""

        with self._lock:
            future = self._future
        return None if future is None else future.result()

    def shutdown(self) -> None:
        """Stop accepting queued jobs and wait for the active job before lifespan exit."""

        self._executor.shutdown(wait=True, cancel_futures=True)
