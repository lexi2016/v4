"""One fetch-and-parse material store: fetch once, reuse everywhere.

Blobs are content-addressed and immutable; parsed artifacts are keyed by
blob sha plus a declared parser id/version; index entries map a normalized
source key to its latest blob with retrieve metadata.  The manager's fetch
subsystems (official financial PDFs, media/market events, public reader
search) share this store, so a retry or a sibling refresh reuses the same
bytes and the same parse instead of re-fetching.

Safety semantics:
- a cache hit still carries full provenance (url, sha256, retrieved_at);
  freshness decisions use ``retrieved_at``, never the current time in its
  place, and a cache hit is never reported as a fresh retrieval;
- ``force=True`` bypasses both caches;
- fetch or parse failures never persist anything.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import re
from pathlib import Path
from typing import Any, Callable, Mapping

from infrastructure.owned_io import SafeRoot
from .contracts import canonical_json

_BLOB_ROOT = 'blobs'
_INDEX_ROOT = 'index'
_PARSED_ROOT = 'parsed'
_SLUG_RE = re.compile(r'^[a-z0-9][a-z0-9._-]*$')


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


class MaterialError(RuntimeError):
    pass


@dataclass(frozen=True)
class Material:
    """Raw material plus the provenance needed to cite it honestly."""

    source_key: str
    url: str
    sha256: str
    retrieved_at: str
    content_type: str | None
    body: bytes
    from_cache: bool


class MaterialStore:
    def __init__(self, root: Path | str):
        self.root = Path(root)
        self._io = SafeRoot(self.root)

    # -- layout helpers ----------------------------------------------------

    @staticmethod
    def _require_slug(value: str, label: str) -> str:
        if not isinstance(value, str) or not _SLUG_RE.fullmatch(value):
            raise MaterialError(f'{label} must be a safe slug')
        return value

    def _index_relative(self, source_key: str) -> str:
        if not isinstance(source_key, str) or not source_key.strip():
            raise MaterialError('source_key must be a non-empty string')
        digest = sha256(source_key.encode('utf-8')).hexdigest()
        return f'{_INDEX_ROOT}/{digest}.json'

    @staticmethod
    def _blob_relative(digest: str) -> str:
        return f'{_BLOB_ROOT}/{digest}'

    def _parsed_relative(
        self,
        digest: str,
        parser_id: str,
        parser_version: int,
        params: Mapping[str, Any] | None = None,
    ) -> str:
        self._require_slug(parser_id, 'parser_id')
        if not isinstance(parser_version, int) or isinstance(parser_version, bool) or parser_version < 1:
            raise MaterialError('parser_version must be a positive integer')
        suffix = ''
        if params is not None:
            params_digest = sha256(canonical_json(params)).hexdigest()[:16]
            suffix = f'.{params_digest}'
        return f'{_PARSED_ROOT}/{digest}.{parser_id}.v{parser_version}{suffix}.json'

    # -- caches ------------------------------------------------------------

    def _read_index(self, relative: str) -> dict[str, Any] | None:
        try:
            raw = self._io.read_bytes(relative)
        except (FileNotFoundError, ValueError):
            return None
        try:
            value = json.loads(raw.decode('utf-8'))
        except (UnicodeError, json.JSONDecodeError):
            # A corrupt pointer is a cache miss, not evidence of anything.
            return None
        return value if isinstance(value, dict) else None

    @staticmethod
    def _fresh(entry: Mapping[str, Any], ttl_seconds: float | None) -> bool:
        if ttl_seconds is None:
            return True
        retrieved = entry.get('retrieved_at')
        if not isinstance(retrieved, str):
            return False
        try:
            stamp = datetime.fromisoformat(retrieved.replace('Z', '+00:00'))
        except ValueError:
            return False
        if stamp.tzinfo is None:
            return False
        age = (datetime.now(timezone.utc) - stamp.astimezone(timezone.utc)).total_seconds()
        return 0 <= age <= ttl_seconds

    # -- public API --------------------------------------------------------

    def fetch(
        self,
        source_key: str,
        *,
        url: str,
        ttl_seconds: float | None,
        transport: Callable[[str], Any],
        force: bool = False,
    ) -> Material:
        """Return the cached material for ``source_key`` or fetch it once.

        ``ttl_seconds=None`` means the source is treated as immutable
        (e.g. an archived document).  Concurrent callers for the same key
        are serialized by the store's kernel lock, so the transport runs
        at most once per miss.
        """

        index_relative = self._index_relative(source_key)
        lock_name = f'.locks/index-{Path(index_relative).stem}.mutex'
        with self._io.kernel_lock(lock_name, timeout=30, poll=0.02):
            if not force:
                entry = self._read_index(index_relative)
                if entry is not None and self._fresh(entry, ttl_seconds):
                    digest = entry.get('sha256')
                    if isinstance(digest, str):
                        try:
                            body = self._io.read_bytes(self._blob_relative(digest))
                            return Material(
                                source_key=source_key,
                                url=str(entry.get('url') or url),
                                sha256=digest,
                                retrieved_at=str(entry.get('retrieved_at') or ''),
                                content_type=entry.get('content_type'),
                                body=body,
                                from_cache=True,
                            )
                        except (FileNotFoundError, ValueError):
                            pass  # blob gone: fall through to a real fetch
            response = transport(url)
            if isinstance(response, Mapping):
                body = response.get('body')
                content_type = response.get('content_type')
                retrieved_at = response.get('retrieved_at') or _now()
            else:
                body = getattr(response, 'body', None)
                content_type = getattr(response, 'content_type', None)
                retrieved_at = getattr(response, 'retrieved_at', None) or _now()
            if not isinstance(body, bytes) or not body:
                raise MaterialError('transport must return non-empty bytes')
            digest = sha256(body).hexdigest()
            blob_relative = self._blob_relative(digest)
            try:
                self._io.read_bytes(blob_relative)
            except (FileNotFoundError, ValueError):
                self._io.write_bytes(blob_relative, body)
            self._io.write_bytes(
                index_relative,
                canonical_json(
                    {
                        'schema_version': 'v4.manager_research.material_index.v1',
                        'source_key': source_key,
                        'url': url,
                        'sha256': digest,
                        'retrieved_at': str(retrieved_at),
                        'content_type': content_type,
                    }
                ),
            )
            return Material(
                source_key=source_key,
                url=url,
                sha256=digest,
                retrieved_at=str(retrieved_at),
                content_type=content_type,
                body=body,
                from_cache=False,
            )

    def parsed(
        self,
        material: Material,
        *,
        parser_id: str,
        parser_version: int,
        parse_fn: Callable[[bytes], Any],
        params: Mapping[str, Any] | None = None,
    ) -> Any:
        """Return the cached parse of ``material`` or parse it once.

        The parse key is (blob sha, parser id, parser version, params): the
        parser version covers code changes, and ``params`` covers inputs the
        parse depends on beyond the bytes themselves (e.g. a document title
        or a page base URL).  Upgrading re-parses, reusing the same blob and
        params reuses the same parse.  A failed parse persists nothing and
        propagates.
        """

        relative = self._parsed_relative(material.sha256, parser_id, parser_version, params)
        try:
            raw = self._io.read_bytes(relative)
        except (FileNotFoundError, ValueError):
            raw = None
        if raw is not None:
            try:
                return json.loads(raw.decode('utf-8'))
            except (UnicodeError, json.JSONDecodeError):
                pass  # corrupt parse cache: recompute below
        value = parse_fn(material.body)
        self._io.write_bytes(relative, canonical_json(value))
        return value

    def stat_source(self, source_key: str) -> dict[str, Any] | None:
        """Return the persisted index entry (provenance) for a key, if any."""

        return self._read_index(self._index_relative(source_key))
