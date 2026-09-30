"""Material-backed source transport: fetch once, reuse everywhere.

The public sources are fetched through the shared MaterialStore so a URL that
one lane retrieved (official PDFs, media events, the public reader) is reused
by every other lane instead of being requested again.  The store keeps the
raw response envelope -- status, final redirect target, body -- so a cache hit
reconstructs the same provenance-carrying response a fresh fetch produced.
Only successful GET responses are cached: POST form flows and non-2xx/empty
responses pass through uncached, a failed fetch persists nothing, and a cache
hit is never reported as a fresh retrieval.
"""
from __future__ import annotations

from base64 import b64decode, b64encode
import json
from typing import Any, Callable, Mapping

from .contracts import canonical_json
from .materials import Material, MaterialError, MaterialStore
from .ports import SourceResponse

ENVELOPE_SCHEMA = 'v4.manager_research.material_envelope.v1'
DEFAULT_DYNAMIC_TTL_SECONDS = 1800.0


class _Passthrough(Exception):
    """Raised to hand a real (non-2xx/empty) response back without caching."""


def _encode_envelope(response: SourceResponse) -> bytes:
    return canonical_json(
        {
            'schema_version': ENVELOPE_SCHEMA,
            'status_code': int(response.status_code),
            'final_url': response.final_url,
            'body_b64': b64encode(response.body).decode('ascii'),
        }
    )


def _decode_envelope(raw: bytes) -> tuple[int, str | None, bytes]:
    try:
        value = json.loads(raw.decode('utf-8'))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise MaterialError('cached response envelope is corrupt') from exc
    if not isinstance(value, Mapping) or value.get('schema_version') != ENVELOPE_SCHEMA:
        raise MaterialError('cached response envelope has an unknown schema')
    status_code = value.get('status_code')
    if not isinstance(status_code, int) or isinstance(status_code, bool):
        raise MaterialError('cached response envelope lacks a status')
    body_b64 = value.get('body_b64')
    if not isinstance(body_b64, str):
        raise MaterialError('cached response envelope lacks a body')
    final_url = value.get('final_url')
    try:
        body = b64decode(body_b64)
    except (ValueError, TypeError) as exc:
        raise MaterialError('cached response envelope body is corrupt') from exc
    return status_code, (final_url if isinstance(final_url, str) else None), body


def _content_type(headers: Mapping[str, str] | None) -> str | None:
    if not headers:
        return None
    for key, value in headers.items():
        if str(key).lower() == 'content-type' and isinstance(value, str):
            return value
    return None


def response_from_material(material: Material) -> SourceResponse:
    """Rebuild the response a fresh fetch recorded, from its cached envelope."""

    status_code, final_url, body = _decode_envelope(material.body)
    headers: dict[str, str] = {}
    if isinstance(material.content_type, str) and material.content_type:
        headers['content-type'] = material.content_type
    return SourceResponse(
        url=material.url,
        status_code=status_code,
        body=body,
        headers=headers,
        retrieved_at=material.retrieved_at,
        final_url=final_url,
    )


class MaterialTransport:
    """``SourceTransport`` adapter over a MaterialStore (GET, success only)."""

    def __init__(
        self,
        store: MaterialStore,
        transport: Callable[..., SourceResponse],
        *,
        namespace: str,
        ttl_seconds: float | None = DEFAULT_DYNAMIC_TTL_SECONDS,
        ttl_for: Callable[[str], float | None] | None = None,
    ) -> None:
        if not isinstance(namespace, str) or not namespace.strip():
            raise MaterialError('namespace must be a non-empty string')
        self._store = store
        self._transport = transport
        self._namespace = namespace.strip()
        self._ttl_seconds = ttl_seconds
        self._ttl_for = ttl_for

    def _ttl(self, url: str) -> float | None:
        if self._ttl_for is not None:
            return self._ttl_for(url)
        return self._ttl_seconds

    def __call__(
        self,
        url: str,
        *,
        timeout: float,
        method: str = 'GET',
        body: bytes | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> SourceResponse:
        if method.upper() != 'GET' or body is not None:
            return self._transport(url, timeout=timeout, method=method, body=body, headers=headers)
        material, response = self._get(url, timeout=timeout, headers=headers)
        if material is None:
            assert response is not None
            return response
        return response_from_material(material)

    def material(
        self,
        url: str,
        *,
        timeout: float,
        headers: Mapping[str, str] | None = None,
    ) -> Material | None:
        """Cached GET: the Material for a 2xx body, or ``None`` (uncached)."""

        material, _ = self._get(url, timeout=timeout, headers=headers)
        return material

    def parsed(
        self,
        material: Material,
        *,
        parser_id: str,
        parser_version: int,
        parse_fn: Callable[[bytes], Any],
        params: Mapping[str, Any] | None = None,
    ) -> Any:
        """Cached parse of a material fetched by this transport.

        ``parse_fn`` receives the original response body (the envelope is
        decoded here); the cache key stays the stored envelope plus the
        declared parser id, version, and params.
        """

        return self._store.parsed(
            material,
            parser_id=parser_id,
            parser_version=parser_version,
            parse_fn=lambda stored: parse_fn(_decode_envelope(stored)[2]),
            params=params,
        )

    def _get(
        self,
        url: str,
        *,
        timeout: float,
        headers: Mapping[str, str] | None,
    ) -> tuple[Material | None, SourceResponse | None]:
        holder: dict[str, SourceResponse] = {}

        def capture(_url: str) -> dict[str, Any]:
            try:
                response = self._transport(url, timeout=timeout, method='GET', headers=headers)
            except TypeError:
                # Small fixture transports expose only ``(url, timeout=...)``.
                if headers is not None:
                    raise
                response = self._transport(url, timeout=timeout)
            if not (200 <= int(response.status_code) < 300) or not response.body:
                holder['response'] = response
                raise _Passthrough()
            return {
                'body': _encode_envelope(response),
                'content_type': _content_type(response.headers),
                'retrieved_at': response.retrieved_at,
            }

        try:
            material = self._store.fetch(
                f'{self._namespace}:{url}',
                url=url,
                ttl_seconds=self._ttl(url),
                transport=capture,
            )
        except _Passthrough:
            return None, holder['response']
        return material, None
