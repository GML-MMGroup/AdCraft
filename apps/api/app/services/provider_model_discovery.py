"""Bounded provider metadata discovery; never submits generation requests."""

from __future__ import annotations

import json
import re

from app.services.provider_credentials import ProviderHttpTransport, UrllibProviderHttpTransport


class SiliconFlowCatalogAdapter:
    provider_id = "siliconflow"
    discovery_mode = "remote"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.siliconflow.cn/v1",
        transport: ProviderHttpTransport | None = None,
    ) -> None:
        if base_url.rstrip("/") != "https://api.siliconflow.cn/v1":
            raise ValueError("model_catalog_sync_failed")
        if not api_key.strip() or any(char in api_key for char in ("\r", "\n", "\x00")):
            raise ValueError("model_catalog_sync_failed")
        self._api_key = api_key.strip()
        self._transport = transport or UrllibProviderHttpTransport()

    def discover_model_ids(self) -> tuple[str, ...]:
        try:
            response = self._transport.get(
                url="https://api.siliconflow.cn/v1/models",
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout_seconds=5.0,
                max_response_bytes=1024 * 1024,
            )
            if not 200 <= response.status_code < 300:
                raise ValueError("model_catalog_sync_failed")
            payload = json.loads(response.body)
            data = payload.get("data") if isinstance(payload, dict) else None
            if not isinstance(data, list) or len(data) > 5000:
                raise ValueError("model_catalog_sync_failed")
            ids: set[str] = set()
            for item in data:
                model_id = item.get("id") if isinstance(item, dict) else None
                if not isinstance(model_id, str) or not re.fullmatch(
                    r"[A-Za-z0-9][A-Za-z0-9._/:-]{0,199}", model_id
                ):
                    raise ValueError("model_catalog_sync_failed")
                ids.add(model_id)
            return tuple(sorted(ids))
        except (OSError, ValueError, TypeError) as error:
            raise ValueError("model_catalog_sync_failed") from error
