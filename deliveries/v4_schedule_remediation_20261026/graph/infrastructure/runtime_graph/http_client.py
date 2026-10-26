'''Bounded, same-origin HTTP access for runtime-graph evidence probes.'''

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from typing import Any


# The 2026-10-26 frozen-reader preselection DTO is 2,652,719 bytes.
# Keep a finite fail-closed ceiling for that complete, non-truncated response.
MAX_BODY_BYTES = 4 * 1024 * 1024
REQUEST_TIMEOUT_SECONDS = 3.0
API_PORT = 8873


def validate_api_base(value: str) -> str:
    parsed = urllib.parse.urlsplit(value)
    if (
        parsed.scheme != 'http'
        or parsed.username
        or parsed.password
        or parsed.path not in ('', '/')
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError('API_BASE_UNSAFE')
    try:
        port = parsed.port
    except ValueError as error:
        raise ValueError('API_BASE_UNSAFE') from error
    host = (parsed.hostname or '').lower()
    if host not in {'127.0.0.1', 'localhost', '::1'} or port != API_PORT:
        raise ValueError('API_BASE_UNSAFE')
    return f'http://[{host}]:{API_PORT}' if host == '::1' else f'http://{host}:{API_PORT}'


def _api_path(value: str) -> str:
    parsed = urllib.parse.urlsplit(value)
    decoded_once = urllib.parse.unquote(parsed.path)
    decoded_twice = urllib.parse.unquote(decoded_once)
    unsafe = (parsed.path, decoded_once, decoded_twice, parsed.query)
    if (
        '%' in value
        or parsed.scheme
        or parsed.netloc
        or parsed.fragment
        or not value.startswith('/api/')
        or any(
            '\\' in item
            or '..' in item
            or any(ord(char) < 32 for char in item)
            for item in unsafe
        )
    ):
        raise ValueError('API_PATH_UNSAFE')
    if parsed.query:
        try:
            pairs = urllib.parse.parse_qsl(
                parsed.query,
                keep_blank_values=True,
                strict_parsing=True,
            )
        except ValueError as error:
            raise ValueError('API_PATH_UNSAFE') from error
        if not pairs or any(not key for key, _value in pairs):
            raise ValueError('API_PATH_UNSAFE')
    return parsed.path + (f'?{parsed.query}' if parsed.query else '')


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        del args, kwargs
        return None


def make_http_get(api_base: str) -> Callable[[str], Mapping[str, Any]]:
    base = validate_api_base(api_base)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())

    def get(path: str) -> Mapping[str, Any]:
        target = base + _api_path(path)
        request = urllib.request.Request(
            target,
            method='GET',
            headers={'Accept': 'application/json'},
        )
        try:
            with opener.open(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                if response.geturl() != target:
                    raise ValueError('API_REDIRECT')
                declared = response.headers.get('Content-Length')
                if declared and int(declared) > MAX_BODY_BYTES:
                    raise ValueError('API_BODY_TOO_LARGE')
                raw = response.read(MAX_BODY_BYTES + 1)
        except ValueError as error:
            if str(error) == 'API_BODY_TOO_LARGE':
                raise
            raise ValueError('API_UNAVAILABLE') from error
        except (OSError, urllib.error.URLError) as error:
            raise ValueError('API_UNAVAILABLE') from error
        if len(raw) > MAX_BODY_BYTES:
            raise ValueError('API_BODY_TOO_LARGE')
        try:
            payload = json.loads(raw.decode('utf-8'))
        except (UnicodeError, json.JSONDecodeError) as error:
            raise ValueError('API_UNAVAILABLE') from error
        if not isinstance(payload, Mapping):
            raise ValueError('API_UNAVAILABLE')
        return payload

    return get
