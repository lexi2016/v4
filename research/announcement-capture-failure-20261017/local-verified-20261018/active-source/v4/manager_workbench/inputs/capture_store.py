"""Private capture cache with source-wide, token-bound revocable ownership.

Grant/revoke are explicit cutover operations. Construction never grants ownership.
Every network boundary and every write checks the lease. Successful raw objects
and attempts are immutable; failed pages have no reusable success pointer.
"""
from __future__ import annotations
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path
from uuid import uuid4
from urllib.parse import urlsplit
from infrastructure.owned_io import SafeRoot

OWNER = 'v4.manager_workbench.capture_announcements'
SOURCES = {'EASTMONEY_HK', 'HKEX_OFFICIAL'}
# Product JSON is consumed downstream with a 256 MiB bound. Keep this limit
# local to the product contract; SafeRoot's shared 64 MiB default stays intact.
PRODUCT_MAX_BYTES = 256 * 1024 * 1024


def encoded(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',', ':'),allow_nan=False).encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def aware(value):
    result=datetime.fromisoformat(value) if isinstance(value,str) else value
    if not isinstance(result,datetime) or result.tzinfo is None or result.utcoffset() is None:
        raise ValueError('CAPTURE_CLOCK_MUST_BE_AWARE')
    return result


class CaptureStore:
    def __init__(self, root: Path | str, *, source='EASTMONEY_HK', token=None, lease_root=None, clock=None):
        if source not in SOURCES: raise ValueError('CAPTURE_SOURCE_INVALID')
        self.io=SafeRoot(root); self.leases=SafeRoot(lease_root or root)
        self.source=source; self.token=token; self.clock=clock or (lambda: datetime.now(timezone.utc))
        self._request_index=None

    def now(self): return aware(self.clock())
    @property
    def lease_path(self): return f'leases/{self.source}.json'
    @property
    def lock_path(self): return f'leases/{self.source}.lock'

    def _json(self, io, path):
        try: return json.loads(io.read_bytes(path))
        except FileNotFoundError: return None

    def grant(self, *, expires_at, owner=OWNER):
        """Explicit cutover, never invoked automatically by capture or supervisor."""
        finish=aware(expires_at)
        if finish<=self.now() or owner!=OWNER: raise ValueError('CAPTURE_LEASE_GRANT_INVALID')
        with self.leases.kernel_lock(self.lock_path):
            old=self._json(self.leases,self.lease_path)
            if old and old.get('enabled') and aware(old['expires_at'])>self.now():
                raise ValueError('ANNOUNCEMENT_EXCLUSIVE_OWNER_ALREADY_HELD')
            token=uuid4().hex
            self.leases.write_bytes(self.lease_path,encoded(dict(owner=owner,source=self.source,token=token,
                enabled=True,granted_at=self.now().isoformat(),expires_at=finish.isoformat())))
        self.token=token
        return token

    def _assert(self, owner=OWNER):
        record=self._json(self.leases,self.lease_path)
        if (owner!=OWNER or not self.token or not record or record.get('source')!=self.source
                or record.get('owner')!=owner or record.get('token')!=self.token
                or record.get('enabled') is not True or aware(record['expires_at'])<=self.now()):
            raise ValueError('ANNOUNCEMENT_EXCLUSIVE_OWNER_NOT_BOUND_OR_REVOKED')

    def assert_exclusive_owner(self, owner=OWNER):
        # A missing/revoked lease fails without creating a directory or lock.
        self._assert(owner)
        with self.leases.kernel_lock(self.lock_path): self._assert(owner)

    @contextmanager
    def guard(self):
        self._assert()
        with self.leases.kernel_lock(self.lock_path):
            self._assert(); yield

    def revoke(self):
        with self.guard():
            record=self._json(self.leases,self.lease_path)
            record.update(enabled=False,revoked_at=self.now().isoformat())
            self.leases.write_bytes(self.lease_path,encoded(record))

    def _object(self, raw):
        identity=sha(raw); path=f'objects/{identity}.bin'
        try:
            previous=self.io.read_bytes(path)
            if previous!=raw: raise ValueError('CAPTURE_IMMUTABLE_OBJECT_CONFLICT')
        except FileNotFoundError: self.io.write_bytes(path,raw,require_absent=True)
        return path,identity

    def _reusable_receipts(self, request, reusable_scope):
        """Find immutable successful receipts for the same source URL and stable scope."""
        if not isinstance(reusable_scope,dict) or not reusable_scope:
            raise ValueError('CAPTURE_REUSE_SCOPE_INVALID')
        if self._request_index is None:
            index={}
            for name in self.io.files('requests'):
                path=f'requests/{name}'
                try: receipt=json.loads(self.io.read_bytes(path))
                except (ValueError,UnicodeDecodeError): continue
                original=receipt.get('request') if isinstance(receipt,dict) else None
                if (not isinstance(original,dict) or original.get('method')!='GET'
                        or receipt.get('status')!='CAPTURED'):
                    continue
                identity=(original.get('source'),original.get('method'),original.get('url'))
                index.setdefault(identity,[]).append((name,receipt))
            self._request_index=index
        identity=(request['source'],request['method'],request['url'])
        candidates=[]
        for name,receipt in self._request_index.get(identity,[]):
            original_scope=receipt.get('request',{}).get('scope')
            if not isinstance(original_scope,dict): continue
            if all(original_scope.get(key)==value for key,value in reusable_scope.items()):
                candidates.append((name,receipt))
        return candidates

    def fetch(self, url, *, scope, transport, validate, max_bytes=32*1024*1024,
              reusable_scope=None, reuse_before=None):
        self.assert_exclusive_owner()
        if (reusable_scope is None) != (reuse_before is None):
            raise ValueError('CAPTURE_REUSE_BOUNDARY_REQUIRED')
        if reuse_before is not None: reuse_before=aware(reuse_before)
        parts=urlsplit(url)
        allowed=({'np-anotice-stock.eastmoney.com':'/api/security/ann',
                  'np-cnotice-stock.eastmoney.com':'/api/content/ann'} if self.source=='EASTMONEY_HK' else
                 {'www1.hkexnews.hk':None,'www.hkexnews.hk':None})
        if (parts.scheme!='https' or parts.hostname not in allowed or parts.username or parts.password
                or parts.port not in (None,443) or parts.fragment
                or (allowed[parts.hostname] is not None and parts.path!=allowed[parts.hostname])):
            raise ValueError('CAPTURE_APPROVED_SOURCE_URL_REQUIRED')
        request=dict(source=self.source,method='GET',url=url,scope=scope)
        key=sha(encoded(request)); pointer=f'requests/{key}.json'
        # Concurrent calls for the same frozen request reuse the first success.
        with self.io.kernel_lock(f'locks/{key}.lock'):
            self.assert_exclusive_owner()
            previous=self._json(self.io,pointer)
            def checked(receipt, *, expected_request=request, expected_key=key, verify_content=True):
                capsule={k:v for k,v in receipt.items() if k!='receipt_sha256'}
                if (receipt.get('request')!=expected_request or receipt.get('request_sha256')!=expected_key
                        or receipt.get('receipt_sha256')!=sha(encoded(capsule))
                        or receipt.get('status')!='CAPTURED' or receipt.get('http_status')!=200
                        or receipt.get('artifact_ref')!=f"objects/{receipt.get('sha256')}.bin"):
                    raise ValueError('CAPTURE_REQUEST_OR_RECEIPT_IDENTITY_CONFLICT')
                aware(receipt['captured_at']);aware(receipt['available_at'])
                raw=self.io.read_bytes(receipt['artifact_ref'],max_bytes=max_bytes)
                if sha(raw)!=receipt['sha256']: raise ValueError('CAPTURE_CACHED_SHA_MISMATCH')
                if verify_content: validate(raw)
                return raw
            def reused_success():
                for name,original in self._reusable_receipts(request,reusable_scope):
                    original_request=original.get('request')
                    if not isinstance(original_request,dict): continue
                    original_key=sha(encoded(original_request))
                    if name!=f'{original_key}.json': continue
                    raw=checked(original,expected_request=original_request,expected_key=original_key,
                                verify_content=False)
                    if aware(original['available_at'])>reuse_before: continue
                    try: validate(raw)
                    except ValueError: continue
                    origin=original.get('reused_from')
                    if not isinstance(origin,dict):
                        origin=dict(request_sha256=original_key,
                                    receipt_sha256=original['receipt_sha256'],
                                    artifact_ref=original['artifact_ref'],
                                    captured_at=original['captured_at'],
                                    available_at=original['available_at'])
                    derived=dict(request=request,request_sha256=key,status='CAPTURED',http_status=200,
                        captured_at=original['captured_at'],available_at=original['available_at'],
                        sha256=original['sha256'],response_bytes=original['response_bytes'],
                        artifact_ref=original['artifact_ref'],from_cache=True,reused_from=origin)
                    derived['receipt_sha256']=sha(encoded(derived))
                    with self.guard(): self.io.write_bytes(pointer,encoded(derived),require_absent=True)
                    return raw,derived
                return None
            if previous: return checked(previous),dict(previous,from_cache=True)
            # Crash after the immutable success receipt but before the pointer:
            # recover that same successful page, without another source request.
            completed=[]
            for name in self.io.files(f'attempts/{key}'):
                receipt=self._json(self.io,f'attempts/{key}/{name}')
                if receipt and receipt.get('status')=='CAPTURED': completed.append(receipt)
            if completed:
                receipt=max(completed,key=lambda r:aware(r['available_at']))
                result=(checked(receipt),dict(receipt,from_cache=True))
                with self.guard(): self.io.write_bytes(pointer,encoded(receipt),require_absent=True)
                return result
            if reusable_scope is not None:
                reused=reused_success()
                if reused is not None: return reused
            if transport is None: raise ValueError('CAPTURE_TRANSPORT_NOT_BOUND')
            self.assert_exclusive_owner()
            receipt=dict(request=request,request_sha256=key,attempt_id=uuid4().hex,
                started_at=self.now().isoformat(),status='FAILED')
            raw=None
            try:
                response=transport.get(url,timeout=(5,20),allow_redirects=False)
                self.assert_exclusive_owner()  # revocation during I/O discards result
                if response.status_code!=200: raise ValueError('CAPTURE_HTTP_STATUS_NOT_200')
                if getattr(response,'url',url)!=url: raise ValueError('CAPTURE_REDIRECT_NOT_ALLOWED')
                raw=response.content
                if not isinstance(raw,bytes) or len(raw)>max_bytes: raise ValueError('CAPTURE_RESPONSE_SIZE_INVALID')
                validate(raw)
                receipt.update(status='CAPTURED',captured_at=self.now().isoformat(),available_at=self.now().isoformat(),
                    sha256=sha(raw),response_bytes=len(raw),http_status=200,from_cache=False)
            except Exception as exc:
                # A revoked operation must leave no attempt, blob or pointer.
                self.assert_exclusive_owner()
                receipt['error']=str(exc)[:200]
                with self.guard():
                    if isinstance(raw,bytes) and len(raw)<=max_bytes:
                        receipt['artifact_ref'],receipt['sha256']=self._object(raw)
                    receipt['receipt_sha256']=sha(encoded(receipt))
                    self.io.write_bytes(f'attempts/{key}/{receipt["attempt_id"]}.json',encoded(receipt),require_absent=True)
                raise
            with self.guard():
                receipt['artifact_ref'],_=self._object(raw)
                receipt['receipt_sha256']=sha(encoded(receipt))
                self.io.write_bytes(f'attempts/{key}/{receipt["attempt_id"]}.json',encoded(receipt),require_absent=True)
                self.io.write_bytes(pointer,encoded(receipt),require_absent=True)
            return raw,receipt

    def save_product(self, value):
        raw=encoded(value); identity=sha(raw); path=f'products/{identity}.json'
        with self.guard():
            try:
                if self.io.read_bytes(path, max_bytes=PRODUCT_MAX_BYTES)!=raw: raise ValueError('CAPTURE_PRODUCT_CONFLICT')
            except FileNotFoundError: self.io.write_bytes(path,raw,require_absent=True)
            if self.io.read_bytes(path, max_bytes=PRODUCT_MAX_BYTES)!=raw: raise ValueError('CAPTURE_PRODUCT_READBACK_FAILED')
        return dict(artifact_ref=path,sha256=identity,owner=OWNER,source=self.source)
