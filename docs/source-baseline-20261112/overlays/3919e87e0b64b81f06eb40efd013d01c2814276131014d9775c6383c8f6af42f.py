"""Bounded proxy-aware HTTP transport for public research sources.

Public research fetches use the local proxy first when one is configured.  A
single network failure may fall back to a direct request; an HTTP contract
response (4xx/5xx) is evidence from the upstream and is never retried through
another route.  The transport is deliberately small and injectable so source
producers can be tested without network access.
"""
from __future__ import annotations

import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from time import monotonic
from typing import Any, Callable, Mapping


LOOPBACK_NO_PROXY = "127.0.0.1,localhost,::1"
USER_AGENT = "v3.5-research-http-transport/1.0"
_PROXY_ENVIRONMENT_KEYS = ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy")
_NO_PROXY_ENVIRONMENT_KEYS = ("NO_PROXY", "no_proxy")

_NetworkError = (TimeoutError, urllib.error.URLError, OSError, ConnectionError)
_Opener = Callable[..., Any]


def _system_proxy_url() -> str:
    """Return the active system HTTP(S) proxy, if one is configured."""
    try:
        proxies = urllib.request.getproxies_macosx_sysconf()
    except Exception:
        return ""
    if not isinstance(proxies, Mapping):
        return ""
    for scheme in ("https", "http", "all"):
        candidate = str(proxies.get(scheme) or "").strip()
        if candidate:
            return candidate
    return ""


def build_proxy_environment(
    base: Mapping[str, str] | None = None,
    *,
    proxy_url: str | None = None,
) -> dict[str, str]:
    """Build launchd-safe proxy variables without changing the live process.

    An explicit ``V4_RESEARCH_PROXY_URL`` wins over a programmatic override;
    otherwise the active macOS HTTP(S) proxy is used.  When none is configured,
    inherited HTTP(S)_PROXY values are removed instead of being reused.
    macOS launchd environments are case-sensitive in practice across tools, so
    both common spellings are emitted.  Loopback endpoints remain direct.
    """
    environment = dict(os.environ if base is None else base)
    normalized_proxy = _configured_proxy_url(environment, proxy_url)
    for key in tuple(environment):
        if _is_generic_proxy_environment_key(key):
            environment.pop(key, None)
    if normalized_proxy:
        for key in _PROXY_ENVIRONMENT_KEYS:
            environment[key] = normalized_proxy
    for key in _NO_PROXY_ENVIRONMENT_KEYS:
        environment[key] = LOOPBACK_NO_PROXY
    return environment


# Explicit alias for launchd/plist builders which want to document the seam.
build_launchd_research_environment = build_proxy_environment


def apply_proxy_environment(
    base: Mapping[str, str] | None = None,
    *,
    proxy_url: str | None = None,
) -> dict[str, str]:
    """Replace the process proxy variables with the sanitized environment.

    The returned mapping is suitable for child-process ``env=`` arguments.
    Only proxy and NO_PROXY keys are changed in the live process, so stale or
    mixed-case generic proxy variables are deleted without clearing unrelated
    scheduler state.
    """
    environment = build_proxy_environment(
        os.environ.copy() if base is None else base,
        proxy_url=proxy_url,
    )
    for key in tuple(os.environ):
        if _is_generic_proxy_environment_key(key) or key in _NO_PROXY_ENVIRONMENT_KEYS:
            os.environ.pop(key, None)
    for key in _PROXY_ENVIRONMENT_KEYS + _NO_PROXY_ENVIRONMENT_KEYS:
        if key in environment:
            os.environ[key] = environment[key]
    return environment


def _configured_proxy_url(
    environment: Mapping[str, str], override: str | None = None
) -> str:
    explicit_proxy = str(environment.get("V4_RESEARCH_PROXY_URL") or "").strip()
    calling_override = str(override or "").strip()
    return explicit_proxy or calling_override or _system_proxy_url()


def _is_generic_proxy_environment_key(key: str) -> bool:
    normalized = str(key).upper()
    # Keep only the two conventional NO_PROXY spellings below.  A mixed-case
    # variant such as ``No_Proxy`` is still an inherited generic key and must
    # not bypass the launchd/process sanitization boundary.
    return normalized.endswith("_PROXY") and key not in _NO_PROXY_ENVIRONMENT_KEYS


@dataclass
class FetchResult:
    body: bytes
    receipt: dict[str, Any]


class TransportError(RuntimeError):
    """A bounded network/connection failure with source evidence."""

    def __init__(self, message: str, *, receipt: Mapping[str, Any]) -> None:
        super().__init__(message)
        self.receipt = dict(receipt)


class HTTPContractError(TransportError):
    """An HTTP 4xx/5xx response which must not receive a direct fallback."""


def _error_text(error: BaseException) -> str:
    detail = str(error).strip()
    return f"{type(error).__name__}:{detail[:240]}" if detail else type(error).__name__


class ProxyAwareHTTPTransport:
    """Perform one proxy-first public HTTP request with one direct fallback."""

    def __init__(
        self,
        *,
        proxy_url: str | None = None,
        env: Mapping[str, str] | None = None,
        timeout: float = 20.0,
        proxy_opener: _Opener | Any | None = None,
        direct_opener: _Opener | Any | None = None,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self.env = dict(os.environ if env is None else env)
        self.default_proxy_url = str(proxy_url).strip() if proxy_url is not None else ""
        self.timeout = max(0.1, float(timeout))
        self._clock = clock
        self._proxy_openers: dict[str, Any] = {}
        self._direct_opener = direct_opener or urllib.request.build_opener(
            urllib.request.ProxyHandler({})
        )
        self._injected_proxy_opener = proxy_opener

    def _proxy_url(self, url: str) -> str:
        del url
        return _configured_proxy_url(self.env, self.default_proxy_url)

    def _proxy_opener(self, proxy_url: str) -> Any:
        if self._injected_proxy_opener is not None:
            return self._injected_proxy_opener
        if proxy_url not in self._proxy_openers:
            self._proxy_openers[proxy_url] = urllib.request.build_opener(
                urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})
            )
        return self._proxy_openers[proxy_url]

    @staticmethod
    def _invoke(opener: Any, request: urllib.request.Request, timeout: float) -> Any:
        method = getattr(opener, "open", None)
        if callable(method):
            return method(request, timeout=timeout)
        return opener(request, timeout)

    def _attempt(
        self,
        opener: Any,
        request: urllib.request.Request,
        *,
        timeout: float,
        proxy_used: bool,
        fallback_used: bool,
    ) -> FetchResult:
        started = self._clock()
        try:
            response = self._invoke(opener, request, timeout)
            with response as active:
                raw_status = getattr(active, "status", None)
                if raw_status is None and hasattr(active, "getcode"):
                    raw_status = active.getcode()
                status = int(raw_status) if raw_status is not None else 200
                if status < 200 or status >= 400:
                    receipt = {
                        "elapsed_ms": max(0, int((self._clock() - started) * 1000)),
                        "http_status": status,
                        "error": f"HTTP_STATUS_{status}",
                        "proxy_used": proxy_used,
                        "fallback_used": fallback_used,
                    }
                    raise HTTPContractError(
                        f"public research HTTP contract returned {status}",
                        receipt=receipt,
                    )
                body = active.read()
            return FetchResult(
                body=body if isinstance(body, bytes) else bytes(body),
                receipt={
                    "elapsed_ms": max(0, int((self._clock() - started) * 1000)),
                    "http_status": status,
                    "error": None,
                    "proxy_used": proxy_used,
                    "fallback_used": fallback_used,
                },
            )
        except HTTPContractError:
            raise
        except urllib.error.HTTPError as error:
            receipt = {
                "elapsed_ms": max(0, int((self._clock() - started) * 1000)),
                "http_status": int(error.code),
                "error": f"HTTP_STATUS_{int(error.code)}",
                "proxy_used": proxy_used,
                "fallback_used": fallback_used,
            }
            # ``HTTPError`` owns the response file object.  Close it before
            # retaining the error as a cause so bounded failures do not leak
            # temporary response files into the scheduler process.
            error.close()
            raise HTTPContractError(
                f"public research HTTP contract returned {error.code}",
                receipt=receipt,
            ) from error
        except _NetworkError as error:
            receipt = {
                "elapsed_ms": max(0, int((self._clock() - started) * 1000)),
                "http_status": None,
                "error": _error_text(error),
                "proxy_used": proxy_used,
                "fallback_used": fallback_used,
            }
            raise TransportError("public research network request failed", receipt=receipt) from error

    def fetch(
        self,
        url: str,
        *,
        timeout: float | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> FetchResult:
        request_headers = {"User-Agent": USER_AGENT}
        request_headers.update({str(key): str(value) for key, value in (headers or {}).items()})
        request = urllib.request.Request(url, headers=request_headers)
        bounded_timeout = max(0.1, float(timeout if timeout is not None else self.timeout))
        proxy_url = self._proxy_url(url)
        if not proxy_url:
            return self._attempt(
                self._direct_opener,
                request,
                timeout=bounded_timeout,
                proxy_used=False,
                fallback_used=False,
            )
        try:
            return self._attempt(
                self._proxy_opener(proxy_url),
                request,
                timeout=bounded_timeout,
                proxy_used=True,
                fallback_used=False,
            )
        except HTTPContractError:
            raise
        except TransportError as proxy_error:
            try:
                direct = self._attempt(
                    self._direct_opener,
                    request,
                    timeout=bounded_timeout,
                    proxy_used=True,
                    fallback_used=True,
                )
            except TransportError as direct_error:
                direct_error.receipt["elapsed_ms"] = (
                    int(proxy_error.receipt.get("elapsed_ms") or 0)
                    + int(direct_error.receipt.get("elapsed_ms") or 0)
                )
                raise
            direct.receipt["elapsed_ms"] = (
                int(proxy_error.receipt.get("elapsed_ms") or 0)
                + int(direct.receipt.get("elapsed_ms") or 0)
            )
            return direct


__all__ = [
    "LOOPBACK_NO_PROXY",
    "FetchResult",
    "HTTPContractError",
    "ProxyAwareHTTPTransport",
    "TransportError",
    "apply_proxy_environment",
    "build_launchd_research_environment",
    "build_proxy_environment",
]
