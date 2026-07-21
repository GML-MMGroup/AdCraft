"""Volcengine OpenAPI HMAC-SHA256 signing for the AI Music service."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
from typing import Iterable
from urllib.parse import quote, urlsplit


@dataclass(frozen=True)
class VolcengineSignedHeaders:
    """Headers required for one signed Volcengine OpenAPI request."""

    headers: dict[str, str]


class VolcengineOpenApiSigner:
    """Create deterministic Volcengine OpenAPI v4-style request signatures."""

    algorithm = "HMAC-SHA256"
    terminal = "request"

    def sign(
        self,
        *,
        method: str,
        endpoint: str,
        query: Iterable[tuple[str, str]],
        body: bytes,
        access_key_id: str,
        secret_access_key: str,
        timestamp: datetime,
        region: str,
        service: str,
    ) -> VolcengineSignedHeaders:
        parsed = urlsplit(endpoint)
        if not parsed.scheme or not parsed.netloc:
            raise ValueError("Volcengine endpoint must include scheme and host.")
        if not access_key_id or not secret_access_key:
            raise ValueError("Volcengine access key and secret access key are required.")
        current = timestamp.astimezone(timezone.utc)
        date_stamp = current.strftime("%Y%m%d")
        x_date = current.strftime("%Y%m%dT%H%M%SZ")
        payload_hash = hashlib.sha256(body).hexdigest()
        canonical_query = "&".join(
            f"{quote(str(key), safe='-_.~')}={quote(str(value), safe='-_.~')}"
            for key, value in query
        )
        canonical_uri = quote(parsed.path or "/", safe="/-_.~")
        canonical_headers = (
            f"content-type:application/json\n"
            f"host:{parsed.netloc}\n"
            f"x-content-sha256:{payload_hash}\n"
            f"x-date:{x_date}\n"
        )
        signed_headers = "content-type;host;x-content-sha256;x-date"
        canonical_request = "\n".join(
            (
                method.upper(),
                canonical_uri,
                canonical_query,
                canonical_headers,
                signed_headers,
                payload_hash,
            )
        )
        credential_scope = f"{date_stamp}/{region}/{service}/{self.terminal}"
        string_to_sign = "\n".join(
            (
                self.algorithm,
                x_date,
                credential_scope,
                hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
            )
        )
        signing_key = _signing_key(secret_access_key, date_stamp, region, service)
        signature = hmac.new(
            signing_key,
            string_to_sign.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        authorization = (
            f"{self.algorithm} Credential={access_key_id}/{credential_scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        )
        return VolcengineSignedHeaders(
            headers={
                "Host": parsed.netloc,
                "Content-Type": "application/json",
                "X-Date": x_date,
                "X-Content-Sha256": payload_hash,
                "Authorization": authorization,
            }
        )


def _signing_key(secret_access_key: str, date_stamp: str, region: str, service: str) -> bytes:
    date_key = _hmac(f"VOLC{secret_access_key}".encode("utf-8"), date_stamp)
    region_key = _hmac(date_key, region)
    service_key = _hmac(region_key, service)
    return _hmac(service_key, VolcengineOpenApiSigner.terminal)


def _hmac(key: bytes, value: str) -> bytes:
    return hmac.new(key, value.encode("utf-8"), hashlib.sha256).digest()
