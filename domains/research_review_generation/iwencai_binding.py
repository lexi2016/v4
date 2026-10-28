"""Optional, pinned Iwencai client binding for the existing V4 data owner.

This module contains no credential or provider behavior at import time. The
external client source is read and compiled only for an explicitly enabled
binding, and the resulting query object is passed through LiveTransport's
existing Iwencai seam.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import stat
import sys
import types
from collections.abc import Mapping
from urllib.parse import urljoin, urlsplit

from ._owned_io import BoundaryError


CLIENT_SOURCE_PATH = Path(
    "/Users/lexi/Desktop/学习/vibe-astock/vr/iwencai_client.py"
)
CLIENT_SOURCE_SHA256 = "1edc981681cc77db1d4448ac36d7b923cd26b71be52c34fdf0c91d6f11160412"
CLIENT_BASE_URL = "https://openapi.iwencai.com"
CLIENT_QUERY_PATH = "/v1/query2data"
CREDENTIAL_REFERENCE = "env:V4_IWENCAI_API_KEY"
CREDENTIAL_ENVIRONMENT_NAME = "V4_IWENCAI_API_KEY"

_BINDING_KEYS = frozenset(
    {
        "enabled",
        "client_source_path",
        "client_source_sha256",
        "credential_ref",
        "base_url",
        "timeout_seconds",
        "max_retries",
        "retry_delay_seconds",
    }
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_MODULE_PREFIX = "_v4_pinned_iwencai_client_"


class IwencaiRequestFailure(BoundaryError):
    """A provider failure with no response body, URL, or credential details."""


def validate_iwencai_binding(value: object) -> dict:
    """Validate the one closed, non-secret binding schema without I/O."""
    if not isinstance(value, Mapping) or set(value) != _BINDING_KEYS:
        raise BoundaryError("IWENCAI_BINDING_SCHEMA_INVALID")
    if type(value.get("enabled")) is not bool:
        raise BoundaryError("IWENCAI_BINDING_SCHEMA_INVALID")
    if value.get("client_source_path") != str(CLIENT_SOURCE_PATH):
        raise BoundaryError("IWENCAI_CLIENT_SOURCE_IDENTITY_INVALID")
    if value.get("client_source_sha256") != CLIENT_SOURCE_SHA256 or not _SHA256_RE.fullmatch(
        str(value.get("client_source_sha256", ""))
    ):
        raise BoundaryError("IWENCAI_CLIENT_SOURCE_IDENTITY_INVALID")
    if value.get("credential_ref") != CREDENTIAL_REFERENCE:
        raise BoundaryError("IWENCAI_CREDENTIAL_REFERENCE_INVALID")
    if value.get("base_url") != CLIENT_BASE_URL:
        raise BoundaryError("IWENCAI_ENDPOINT_CONFIGURATION_INVALID")
    if type(value.get("timeout_seconds")) is not int or value["timeout_seconds"] != 30:
        raise BoundaryError("IWENCAI_RETRY_CONFIGURATION_INVALID")
    if type(value.get("max_retries")) is not int or value["max_retries"] != 1:
        raise BoundaryError("IWENCAI_RETRY_CONFIGURATION_INVALID")
    delay = value.get("retry_delay_seconds")
    if isinstance(delay, bool) or not isinstance(delay, (int, float)) or delay != 0:
        raise BoundaryError("IWENCAI_RETRY_CONFIGURATION_INVALID")
    return dict(value)


def _read_pinned_client_source(binding: Mapping[str, object]) -> bytes:
    """Read only the exact approved source path, refusing symlinked sources."""
    validate_iwencai_binding(binding)
    path = CLIENT_SOURCE_PATH
    try:
        info = path.lstat()
        if path.is_symlink() or not path.is_file() or path.resolve(strict=True) != path:
            raise BoundaryError("IWENCAI_CLIENT_SOURCE_UNSAFE")
        if info.st_size > 2 * 1024 * 1024:
            raise BoundaryError("IWENCAI_CLIENT_SOURCE_SIZE_INVALID")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path, flags)
        try:
            opened = os.fstat(fd)
            if not stat.S_ISREG(opened.st_mode) or opened.st_size > 2 * 1024 * 1024:
                raise BoundaryError("IWENCAI_CLIENT_SOURCE_UNSAFE")
            with os.fdopen(fd, "rb", closefd=False) as stream:
                raw = stream.read(2 * 1024 * 1024 + 1)
        finally:
            os.close(fd)
    except BoundaryError:
        raise
    except (OSError, ValueError):
        raise BoundaryError("IWENCAI_CLIENT_SOURCE_UNAVAILABLE") from None
    if len(raw) > 2 * 1024 * 1024:
        raise BoundaryError("IWENCAI_CLIENT_SOURCE_SIZE_INVALID")
    if hashlib.sha256(raw).hexdigest() != CLIENT_SOURCE_SHA256:
        raise BoundaryError("IWENCAI_CLIENT_SOURCE_SHA_MISMATCH")
    return raw


def _load_pinned_client_module(raw: bytes) -> types.ModuleType:
    """Compile pinned bytes in memory under a dataclass-compatible module."""
    digest = hashlib.sha256(raw).hexdigest()
    if digest != CLIENT_SOURCE_SHA256:
        raise BoundaryError("IWENCAI_CLIENT_SOURCE_SHA_MISMATCH")
    module_name = _MODULE_PREFIX + digest[:16]
    current = sys.modules.get(module_name)
    if current is not None:
        if getattr(current, "__v4_client_source_sha256__", None) != digest:
            raise BoundaryError("IWENCAI_CLIENT_MODULE_IDENTITY_INVALID")
        return current
    module = types.ModuleType(module_name)
    module.__file__ = str(CLIENT_SOURCE_PATH)
    module.__package__ = ""
    module.__v4_client_source_sha256__ = digest
    # dataclasses resolves the defining module through sys.modules.
    sys.modules[module_name] = module
    try:
        code = compile(raw, str(CLIENT_SOURCE_PATH), "exec", dont_inherit=True)
        exec(code, module.__dict__)
    except Exception:
        sys.modules.pop(module_name, None)
        raise BoundaryError("IWENCAI_CLIENT_SOURCE_LOAD_FAILED") from None
    if not callable(getattr(module, "IwencaiClient", None)):
        sys.modules.pop(module_name, None)
        raise BoundaryError("IWENCAI_CLIENT_INTERFACE_INVALID")
    return module


def _assert_query_endpoint(url: str) -> None:
    """Allow only the official HTTPS query endpoint; reject redirects elsewhere."""
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except (TypeError, ValueError):
        raise BoundaryError("IWENCAI_ENDPOINT_FORBIDDEN") from None
    if (
        parsed.scheme.lower() != "https"
        or parsed.hostname is None
        or parsed.hostname.lower() != "openapi.iwencai.com"
        or port not in (None, 443)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path != CLIENT_QUERY_PATH
        or parsed.query
        or parsed.fragment
    ):
        raise BoundaryError("IWENCAI_ENDPOINT_FORBIDDEN")


def _install_pinned_session(client: object) -> None:
    """Disable environment proxy/netrc use and guard every outgoing request."""
    import requests

    original = getattr(client, "_session", None)
    if not isinstance(original, requests.Session):
        raise BoundaryError("IWENCAI_CLIENT_SESSION_INVALID")

    class PinnedIwencaiSession(requests.Session):
        def send(self, request, **kwargs):
            try:
                _assert_query_endpoint(request.url)
            except BoundaryError:
                raise requests.RequestException("IWENCAI_ENDPOINT_FORBIDDEN") from None
            # Do not let requests follow a redirect. Validate its target first;
            # even a same-endpoint redirect is returned as a bounded failure.
            kwargs["allow_redirects"] = False
            response = super().send(request, **kwargs)
            if 300 <= response.status_code < 400:
                location = response.headers.get("Location", "")
                target = urljoin(request.url, location)
                try:
                    _assert_query_endpoint(target)
                except BoundaryError:
                    raise requests.RequestException("IWENCAI_REDIRECT_FORBIDDEN") from None
                raise requests.RequestException("IWENCAI_REDIRECT_FORBIDDEN") from None
            return response

    guarded = PinnedIwencaiSession()
    guarded.trust_env = False
    guarded.proxies.clear()
    guarded.auth = None
    guarded.headers.clear()
    guarded.headers.update(original.headers)
    guarded.cookies.update(original.cookies)
    original.close()
    client._session = guarded


class _RedactedQueryClient:
    """Expose only query(); collapse arbitrary SDK/response errors to a code."""

    def __init__(self, client: object):
        self._client = client

    def query(self, query: str, **kwargs):
        try:
            return self._client.query(query, **kwargs)
        except Exception:
            raise IwencaiRequestFailure("IWENCAI_REQUEST_FAILED") from None


def _resolve_explicit_credential() -> str:
    value = os.environ.get(CREDENTIAL_ENVIRONMENT_NAME)
    if not isinstance(value, str) or not value.strip():
        raise BoundaryError("IWENCAI_CREDENTIAL_UNAVAILABLE")
    return value.strip()


def create_iwencai_query_client(
    binding: object, *, _api_key_for_testing: str | None = None
) -> _RedactedQueryClient | None:
    """Build an in-memory query adapter only for a valid enabled binding.

    ``_api_key_for_testing`` is a Python test seam; the public CLI never sets it.
    The normal path reads only the explicitly named V4 environment variable.
    """
    config = validate_iwencai_binding(binding)
    if not config["enabled"]:
        return None
    raw = _read_pinned_client_source(config)
    module = _load_pinned_client_module(raw)
    api_key = _api_key_for_testing
    if api_key is None:
        api_key = _resolve_explicit_credential()
    if not isinstance(api_key, str) or not api_key.strip():
        raise BoundaryError("IWENCAI_CREDENTIAL_UNAVAILABLE")
    try:
        client = module.IwencaiClient(
            api_key=api_key.strip(),
            base_url=CLIENT_BASE_URL,
            timeout=30,
            max_retries=1,
            retry_delay=0,
        )
        _install_pinned_session(client)
    except BoundaryError:
        raise
    except Exception:
        raise BoundaryError("IWENCAI_CLIENT_INITIALIZATION_FAILED") from None
    return _RedactedQueryClient(client)
