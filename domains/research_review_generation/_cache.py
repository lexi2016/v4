"""Explicit migrated Vibe cache; file bytes, not directory presence, establish trust.

The migration inventory is caller-pinned. Files produced in this new root are
recorded in a local ledger under the same kernel lock as their publication.
Neither missing inventory entries nor malformed cached data trigger legacy-root
reads. Calculators can retain their optional-data fallbacks, but the owner must
call assert_clean() before publishing any input or invoking a model.
"""
from __future__ import annotations
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any

from infrastructure.owned_io import SafeRoot
from ._owned_io import BoundaryError


def encoded(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
                       allow_nan=False) + '\n').encode('utf-8')


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def explicit_root(path: Path | str) -> Path:
    p = Path(path)
    if (not p.is_absolute() or '..' in p.parts or '~' in p.parts or
        any(part in {'.duanxian-agents', 'vibe-astock', '.vibe-astock'} for part in p.parts)):
        raise BoundaryError('explicit absolute V4 root required')
    return p


class OwnedCache:
    _FAMILIES = ('cache/market_facts/', 'cache/zt_summary/', 'cache/prev_pool/',
                 'cache/breadth/', 'cache/zt_reasons/', 'leaders/', 'reflections/')
    _LEDGER = '.ownership/generated-cache.json'

    def __init__(self, root: Path, *, manifest_path: Path, manifest_sha256: str):
        self.root = explicit_root(root)
        self.io = SafeRoot(self.root)
        self.io.ensure_directory()
        path = explicit_root(manifest_path)
        raw = SafeRoot(path.parent).read_bytes(path.name, max_bytes=2*1024*1024)
        if digest(raw) != manifest_sha256:
            raise BoundaryError('cache inventory SHA mismatch')
        obj = json.loads(raw)
        if obj.get('schema') != 'v4.vibe_cache_inventory.v1' or not isinstance(obj.get('files'), dict):
            raise BoundaryError('invalid cache inventory')
        self.manifest_sha256 = manifest_sha256
        self.approved = deepcopy(obj['files'])
        self.used: dict[str, dict] = {}
        self.failures: list[str] = []
        for name, binding in self.approved.items():
            self._validate_name(name)
            self._verify(name, binding)

    def _validate_name(self, name: str) -> None:
        SafeRoot._parts(name)
        if not name.startswith(self._FAMILIES) or not name.endswith('.json'):
            raise BoundaryError('cache path outside approved families')
        # Exactly one date-named JSON file under the declared family.
        tail = name[len(next(x for x in self._FAMILIES if name.startswith(x))):]
        if '/' in tail:
            raise BoundaryError('cache filename must be a session filename')
        from datetime import date
        token = tail[:-5]
        fmt = f'{token[:4]}-{token[4:6]}-{token[6:8]}' if len(token)==8 else token
        if date.fromisoformat(fmt).isoformat() != fmt:
            raise BoundaryError('invalid cache session')

    def _verify(self, name: str, binding: dict) -> bytes:
        try:
            raw = self.io.read_bytes(name, max_bytes=32*1024*1024)
        except FileNotFoundError as exc:
            # A bound file disappearing is not a normal cache miss.
            raise BoundaryError('approved cache disappeared: ' + name) from exc
        if len(raw) != binding.get('bytes') or digest(raw) != binding.get('sha256'):
            raise BoundaryError('cache bytes drift: ' + name)
        return raw

    def _ledger(self) -> dict:
        try:
            obj = json.loads(self.io.read_bytes(self._LEDGER, max_bytes=4*1024*1024))
        except FileNotFoundError:
            return {}
        if obj.get('schema') != 'v4.vibe_generated_cache.v1' or not isinstance(obj.get('files'),dict):
            raise BoundaryError('generated cache ledger invalid')
        return obj['files']

    def read_json(self, name: str) -> Any:
        try:
            self._validate_name(name)
            with self.io.kernel_lock('.ownership/cache.mutex', timeout=30):
                binding = self.approved.get(name) or self._ledger().get(name)
                if binding is None:
                    try:
                        self.io.read_bytes(name, max_bytes=1)
                    except FileNotFoundError:
                        raise
                    raise BoundaryError('unapproved existing cache: '+name)
                raw = self._verify(name,binding)
                value = json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite cache')))
                # Leader and object cache envelopes carry a second date check.
                token = Path(name).stem
                requested = f'{token[:4]}-{token[4:6]}-{token[6:8]}' if len(token)==8 else token
                if isinstance(value,dict) and 'date' in value and value['date'] != requested:
                    raise BoundaryError('cache embedded date mismatch: '+name)
                self.used[name] = {'path':name,'bytes':len(raw),'sha256':digest(raw),
                                   'session':requested,'origin':'MIGRATED' if name in self.approved else 'V4_GENERATED'}
                return value
        except FileNotFoundError:
            raise
        except Exception as exc:
            self.failures.append(type(exc).__name__ + ': ' + name)
            if isinstance(exc,BoundaryError):
                raise
            raise BoundaryError('cache boundary refused: '+name) from exc

    def exists(self, name: str) -> bool:
        try:
            self.read_json(name)
            return True
        except FileNotFoundError:
            return False

    def files(self, relative: str) -> list[str]:
        names = self.io.files(relative)
        for name in names:
            self.read_json(relative+'/'+name)
        return names

    def fingerprint(self, name: str) -> tuple[str,int]:
        self.read_json(name)
        b=self.used[name]
        return b['sha256'],b['bytes']

    def write_json(self, name: str, value: Any) -> bool:
        try:
            self._validate_name(name)
            raw=encoded(value)
            with self.io.kernel_lock('.ownership/cache.mutex',timeout=30):
                ledger=self._ledger()
                old=self.approved.get(name) or ledger.get(name)
                if old is not None:
                    prior=self._verify(name,old)
                    # Historical formatting stays byte-for-byte; compare JSON values.
                    if json.loads(prior) != value:
                        raise BoundaryError('immutable cache conflict: '+name)
                    return True
                self.io.write_bytes(name,raw,require_absent=True)
                ledger[name]={'bytes':len(raw),'sha256':digest(raw)}
                self.io.write_bytes(self._LEDGER,encoded({'schema':'v4.vibe_generated_cache.v1','files':ledger}))
            return True
        except Exception as exc:
            self.failures.append(type(exc).__name__ + ': ' + name)
            if isinstance(exc,BoundaryError):
                raise
            raise BoundaryError('cache publication refused: '+name) from exc

    def assert_clean(self) -> None:
        if self.failures:
            raise BoundaryError('cache boundary failed; cannot publish or call model')
        for name,binding in self.used.items():
            self._verify(name,binding)
