from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
import json
import logging
import os
from pathlib import Path
from uuid import uuid4

from filelock import FileLock, Timeout
import httpx
from pydantic import ValidationError

from app.schemas.tianpuyue_callback_lease import (
    TianpuyueCallbackLease,
    WebhookSiteTokenResponse,
)
from app.services.v2_data_boundary import validate_v2_data_path


_TOKEN_ENDPOINT = "https://webhook.site/token"
_TOKEN_EXPIRY_SECONDS = 604800
_RENEW_BEFORE = timedelta(hours=24)
_LOCK_TIMEOUT_SECONDS = 10
_LOGGER = logging.getLogger(__name__)


class TianpuyueCallbackLeaseError(RuntimeError):
    def __init__(
        self,
        code: str = "bgm_callback_lease_unavailable",
        message: str = "Automatic Tianpuyue callback setup is temporarily unavailable.",
        *,
        retryable: bool = True,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class TianpuyueCallbackLeaseService:
    def __init__(
        self,
        data_dir: Path,
        *,
        timeout_seconds: int = 30,
        client: httpx.Client | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._timeout_seconds = max(1, timeout_seconds)
        self._client = client
        self._now = now or (lambda: datetime.now(timezone.utc))
        state_dir = data_dir / "v2" / "runtime" / "provider-callbacks"
        self._state_path = validate_v2_data_path(
            data_dir,
            state_dir / "tianpuyue.json",
            operation="v2-tianpuyue-callback-lease",
        )
        self._lock_path = validate_v2_data_path(
            data_dir,
            state_dir / "tianpuyue.lock",
            operation="v2-tianpuyue-callback-lease-lock",
        )

    def resolve_base_url(self) -> str:
        current = self._load()
        now = self._utc_now()
        if current is not None and now < current.renew_after:
            return current.base_url
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise TianpuyueCallbackLeaseError() from exc
        try:
            with FileLock(str(self._lock_path), timeout=_LOCK_TIMEOUT_SECONDS):
                current = self._load()
                now = self._utc_now()
                if current is not None and now < current.renew_after:
                    return current.base_url
                try:
                    lease = self._acquire(now)
                    self._save(lease)
                except TianpuyueCallbackLeaseError:
                    if current is not None and now < current.expires_at:
                        _LOGGER.warning(
                            "Tianpuyue callback lease renewal failed; reusing valid lease."
                        )
                        return current.base_url
                    raise
                return lease.base_url
        except Timeout as exc:
            current = self._load()
            now = self._utc_now()
            if current is not None and now < current.expires_at:
                return current.base_url
            raise TianpuyueCallbackLeaseError() from exc

    def _utc_now(self) -> datetime:
        value = self._now()
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def _load(self) -> TianpuyueCallbackLease | None:
        try:
            raw = json.loads(self._state_path.read_text(encoding="utf-8"))
            lease = TianpuyueCallbackLease.model_validate(raw)
        except (FileNotFoundError, OSError, json.JSONDecodeError, ValidationError):
            return None
        return lease if self._utc_now() < lease.expires_at else None

    def _acquire(self, now: datetime) -> TianpuyueCallbackLease:
        body = {
            "default_status": 200,
            "default_content": "success",
            "default_content_type": "text/plain",
            "timeout": 0,
            "listen": 0,
            "expiry": _TOKEN_EXPIRY_SECONDS,
            "request_limit": 0,
            "cors": False,
            "actions": False,
        }
        try:
            headers = {
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
            if self._client is not None:
                response = self._client.post(
                    _TOKEN_ENDPOINT,
                    json=body,
                    headers=headers,
                )
            else:
                with httpx.Client(timeout=self._timeout_seconds) as client:
                    response = client.post(
                        _TOKEN_ENDPOINT,
                        json=body,
                        headers=headers,
                    )
            if response.status_code >= 400:
                raise TianpuyueCallbackLeaseError()
            token = WebhookSiteTokenResponse.model_validate(response.json())
            expires_at = _utc(token.expires_at)
            if expires_at <= now:
                raise TianpuyueCallbackLeaseError()
            return TianpuyueCallbackLease(
                base_url=f"https://webhook.site/{token.uuid}",
                created_at=now,
                expires_at=expires_at,
                renew_after=max(now, expires_at - _RENEW_BEFORE),
            )
        except TianpuyueCallbackLeaseError:
            raise
        except (httpx.HTTPError, ValueError, ValidationError) as exc:
            raise TianpuyueCallbackLeaseError() from exc

    def _save(self, lease: TianpuyueCallbackLease) -> None:
        temporary_path = self._state_path.with_name(
            f".{self._state_path.name}.{uuid4().hex}.tmp"
        )
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(
                temporary_path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                json.dump(
                    lease.model_dump(mode="json"),
                    output,
                    ensure_ascii=True,
                    indent=2,
                )
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            os.chmod(temporary_path, 0o600)
            os.replace(temporary_path, self._state_path)
        except OSError as exc:
            raise TianpuyueCallbackLeaseError() from exc
        finally:
            temporary_path.unlink(missing_ok=True)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
