"""Application-owned coordination for one local catalog indexing job."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from threading import Lock

from app.schemas.v2_asset_library import RecommendedCatalogStatusResponseV2
from app.services.v2_asset_catalog import V2AssetCatalogService


class V2AssetCatalogCoordinator:
    """Ensure at most one local catalog index operation is active."""

    def __init__(self, service: V2AssetCatalogService) -> None:
        self._service = service
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="v2-catalog")
        self._lock = Lock()
        self._future: Future[RecommendedCatalogStatusResponseV2] | None = None

    def ensure_indexed(self) -> RecommendedCatalogStatusResponseV2:
        """Discover a local package and schedule at most one metadata index job."""

        candidate = self._service.discover_latest_package()
        if candidate is None:
            return self._service.catalog_missing_status()
        try:
            current = self._service.status_for_candidate(candidate)
        except Exception as error:  # Service maps only expected catalog errors publicly.
            from app.services.v2_asset_catalog import V2AssetCatalogError

            if isinstance(error, V2AssetCatalogError):
                return self._service.invalid_status(error)
            raise
        if current.status == "ready":
            return current
        with self._lock:
            if self._future is None or self._future.done():
                self._future = self._executor.submit(self._service.index_package, candidate)
        return current

    def get_recommended_status(self) -> RecommendedCatalogStatusResponseV2:
        """Compatibility read now follows the same discovery path."""

        return self.ensure_indexed()

    def wait_for_idle(self) -> RecommendedCatalogStatusResponseV2 | None:
        """Wait for the current job; tests use this instead of time-based polling."""

        with self._lock:
            future = self._future
        return None if future is None else future.result()

    def shutdown(self) -> None:
        """Stop accepting queued jobs and wait for the active job before lifespan exit."""

        self._executor.shutdown(wait=True, cancel_futures=True)
