"""Client for the WHES / WEIHENG ECOS Hub Open API.

Authentication is HMAC-SHA1 request signing, reverse-engineered from WHES'
official sign-demo (Java/Go/Python) since the published Signature guide page
returns an empty document.

The string to sign is::

    <METHOD>\\n
    x-wts-date:<unix millis>\\n
    x-wts-signature-method:HMAC-SHA1\\n
    x-wts-signature-nonce:<uuid>\\n
    x-wts-signature-version:1.0\\n
    <path>[?<sorted, encoded query>]

Every header prefixed ``x-wts-`` participates, sorted alphabetically, each
followed by a newline. The path is appended RAW -- slashes must not be
percent-encoded. Only query keys and values are encoded. WHES' own helper is
confusingly named ``percentEncode`` but merely rewrites ``+`` to ``%20``,
``*`` to ``%2A`` and ``%7E`` to ``~``; encoding the path breaks the signature.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import time
import uuid
from typing import Any
from urllib.parse import parse_qsl, quote, urlparse

import aiohttp

from .const import API_PREFIX, MODE_REQUIRED_PARAMS

_LOGGER = logging.getLogger(__name__)

TIMEOUT = aiohttp.ClientTimeout(total=30)


class EcosHubError(Exception):
    """Base error."""


class EcosHubAuthError(EcosHubError):
    """Invalid credentials or signature rejected."""


class EcosHubConnectionError(EcosHubError):
    """Network-level failure."""


class EcosHubApiError(EcosHubError):
    """The API returned a non-200 business code."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message


class EcosHubControlForbidden(EcosHubError):
    """VPP control is not enabled for this account or device.

    The gateway signals this as business code 5000 with an upstream 403, and
    the device reports vpp_mode 0. It is a provisioning issue on WHES' side,
    not something the client can work around.
    """


def _wts_rewrite(value: str) -> str:
    """WHES' 'percentEncode' -- three substitutions, no actual encoding."""
    if not value:
        return ""
    return value.replace("+", "%20").replace("*", "%2A").replace("%7E", "~")


def _encode_component(value: str) -> str:
    """Percent-encode a single query key or value."""
    return quote(value, safe="").replace("+", "%20").replace("*", "%2A").replace("%7E", "~")


def _canonical_resource(path: str, query: str) -> str:
    """Raw path plus alphabetically sorted, encoded query string."""
    pairs = parse_qsl(query, keep_blank_values=True)
    if not pairs:
        return path
    ordered = sorted(pairs, key=lambda kv: kv[0])
    encoded = "&".join(f"{_encode_component(k)}={_encode_component(v)}" for k, v in ordered)
    return f"{path}?{encoded}"


class EcosHubClient:
    """Minimal async client covering the read-only endpoints we rely on."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        access_key: str,
        access_secret: str,
    ) -> None:
        self._session = session
        self._host = host.rstrip("/")
        self._access_key = access_key
        self._access_secret = access_secret

    def _sign(self, method: str, url: str) -> dict[str, str]:
        parsed = urlparse(url)
        headers = {
            "x-wts-date": str(int(time.time() * 1000)),
            "x-wts-signature-method": "HMAC-SHA1",
            "x-wts-signature-version": "1.0",
            "x-wts-signature-nonce": str(uuid.uuid4()),
        }

        string_to_sign = f"{method.upper()}\n"
        for key in sorted(headers):
            string_to_sign += f"{key}:{headers[key]}\n"
        string_to_sign += _wts_rewrite(_canonical_resource(parsed.path, parsed.query))

        digest = hmac.new(
            self._access_secret.encode("utf-8"),
            string_to_sign.encode("utf-8"),
            hashlib.sha1,
        ).digest()
        signature = base64.standard_b64encode(digest).decode("utf-8")
        headers["Authorization"] = f"wts {self._access_key}:{signature}"
        return headers

    async def _request(
        self, method: str, path: str, json_body: dict[str, Any] | None = None
    ) -> Any:
        url = f"{self._host}{path}"
        headers = self._sign(method, url)
        if json_body is not None:
            headers["Content-Type"] = "application/json"

        try:
            async with self._session.request(
                method, url, headers=headers, json=json_body, timeout=TIMEOUT
            ) as response:
                response.raise_for_status()
                payload = await response.json(content_type=None)
        except aiohttp.ClientResponseError as err:
            raise EcosHubConnectionError(f"HTTP {err.status} from {path}") from err
        except aiohttp.ClientError as err:
            raise EcosHubConnectionError(str(err)) from err

        if not isinstance(payload, dict):
            raise EcosHubApiError(-1, f"Unexpected response body: {payload!r}")

        # The gateway answers HTTP 200 even for failures; the real status is in
        # the body's "code" field.
        code = payload.get("code")
        if code != 200:
            message = payload.get("msg") or "unknown error"
            if code == 4000 and "signature" in message.lower():
                raise EcosHubAuthError(message)
            if code in (4001, 4003):
                raise EcosHubAuthError(message)
            raise EcosHubApiError(code if isinstance(code, int) else -1, message)

        return payload

    async def async_get_devices(self) -> list[dict[str, Any]]:
        """Return every device bound to these credentials."""
        payload = await self._request("GET", f"{API_PREFIX}/devices?page=1&size=100")
        data = payload.get("data") or []
        return data if isinstance(data, list) else [data]

    async def async_get_device(self, device_sn: str) -> dict[str, Any]:
        """Return details for one device."""
        payload = await self._request("GET", f"{API_PREFIX}/devices/{device_sn}")
        return payload.get("data") or {}

    async def async_get_latest_metrics(
        self, device_sn: str, start_ms: int, end_ms: int, columns: list[str]
    ) -> dict[str, Any]:
        """Return the most recent metrics sample as a flat mapping.

        The endpoint answers with ``{"columns": [...], "rows": [[...], ...]}``
        ordered oldest-first, so the newest sample is the final row. Returns an
        empty dict when the device has not reported in the requested window.

        Never request the ``time`` column: it is returned automatically and
        asking for it fails with "column time not valid". Models differ in which
        fields they expose, so if any requested column is rejected we fall back
        to asking for everything and let the entities pick what they need.
        """
        body: dict[str, Any] = {"start": start_ms, "end": end_ms, "columns": columns}
        path = f"{API_PREFIX}/devices/{device_sn}/metrics"

        try:
            payload = await self._request("POST", path, json_body=body)
        except EcosHubApiError as err:
            if "not valid" not in err.message.lower():
                raise
            _LOGGER.warning(
                "The API rejected a requested metrics column (%s); "
                "falling back to fetching all columns",
                err.message,
            )
            payload = await self._request(
                "POST", path, json_body={"start": start_ms, "end": end_ms}
            )

        data = payload.get("data") or {}
        rows = data.get("rows") or []
        names = data.get("columns") or []
        if not rows or not names:
            _LOGGER.debug("No metrics rows returned for %s", device_sn)
            return {}

        return dict(zip(names, rows[-1]))

    async def async_set_control_mode(
        self, device_sn: str, mode: str, **params: float
    ) -> None:
        """Set the VPP control mode.

        ``mode`` must be one of the keys in ``MODE_REQUIRED_PARAMS``; each mode
        demands a different set of parameters and the API rejects incomplete
        requests, so we validate before sending.

        SIGN CONVENTION: ``bat_power`` is negative to CHARGE and positive to
        DISCHARGE -- the reverse of the ``bat_p`` metric. Callers are
        responsible for passing the value in this endpoint's convention.

        Raises EcosHubControlForbidden when VPP control is not provisioned.
        """
        if mode not in MODE_REQUIRED_PARAMS:
            raise ValueError(
                f"Unknown control mode {mode!r}; "
                f"expected one of {', '.join(MODE_REQUIRED_PARAMS)}"
            )

        required = MODE_REQUIRED_PARAMS[mode]
        supplied = {key: value for key, value in params.items() if value is not None}

        missing = [key for key in required if key not in supplied]
        if missing:
            raise ValueError(
                f"Mode {mode} requires {', '.join(missing)}"
            )

        # Send only what this mode uses; extra keys have been seen to confuse
        # the upstream device handler.
        body: dict[str, Any] = {"mode": mode}
        body.update({key: supplied[key] for key in required})

        try:
            await self._request(
                "PUT", f"{API_PREFIX}/devices/{device_sn}/vpp/control-mode", json_body=body
            )
        except EcosHubApiError as err:
            if "403" in err.message or "permission" in err.message.lower():
                raise EcosHubControlForbidden(
                    "VPP control is not enabled for this account or device. "
                    "Ask WHES to enable VPP control mode for your AccessKey."
                ) from err
            raise

        _LOGGER.debug("Set control mode %s on %s with %s", mode, device_sn, body)

    async def async_bind_vpp_devices(self, device_sns: list[str]) -> dict[str, Any]:
        """Bind devices to the VPP user behind these credentials."""
        payload = await self._request(
            "POST", f"{API_PREFIX}/vpp/bind-device", json_body={"devices": device_sns}
        )
        return payload.get("data") or {}
