"""Explicit local reference registration; never copy or modify source archives.

Run from V4 root: python -m ops.index_wechat_research --help
No recursive discovery, network, automatic research or background execution.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import stat
import json
import os
from pathlib import Path
from uuid import uuid4

from infrastructure.wechat_research_archive import (
    ArchiveError, WechatResearchArchive, canonical, directory, read_bytes,
)


def register_return(reader: WechatResearchArchive, *, receipt: str, receipt_sha256: str,
                    manifest: str | None = None, manifest_sha256: str | None = None,
                    require_frozen_input: bool = False) -> dict:
    record=reader.prepare(receipt,receipt_sha256,manifest=manifest,manifest_sha256=manifest_sha256,
                          require_frozen_input=require_frozen_input)
    # Bootstrap the index under a stable parent lock. Creating the index root and
    # opening a lock inside it at the same time raced for first registration.
    # The sidecar is a local registration lock, not a service or source write.
    with directory(reader.archive_root):
        pass
    lock_root = reader.index_root.parent
    lock_name = '.wechat-register-' + hashlib.sha256(str(reader.index_root).encode('utf-8')).hexdigest()[:16] + '.lock'
    with directory(lock_root, create=True):
        # macOS can sporadically return ENOENT for concurrent O_CREAT opens
        # when the same name is passed through dir_fd.  The parent has just
        # been walked with O_NOFOLLOW; use the absolute lock path while still
        # rejecting a lock symlink at open time.
        lock_path = lock_root / lock_name
        lock_fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
                          0o600)
        with os.fdopen(lock_fd, 'r+b') as lock:
            if not stat.S_ISREG(os.fstat(lock.fileno()).st_mode):
                raise ArchiveError('UNSAFE_INDEX_LOCK')
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                # Keep the existing index-local lock for readers/processes that
                # already have an initialized root, while the parent lock makes
                # the first root creation deterministic.
                with directory(reader.index_root, create=True) as root_fd:
                    index_lock_fd = os.open('.register.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
                                            0o600, dir_fd=root_fd)
                    with os.fdopen(index_lock_fd, 'r+b') as index_lock:
                        if not stat.S_ISREG(os.fstat(index_lock.fileno()).st_mode):
                            raise ArchiveError('UNSAFE_INDEX_LOCK')
                        fcntl.flock(index_lock.fileno(), fcntl.LOCK_EX)
                        try:
                            return _insert_locked(reader, record)
                        finally:
                            fcntl.flock(index_lock.fileno(), fcntl.LOCK_UN)
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _insert_locked(reader, record):
    for old in reader._records():
        fid, other = record['fingerprint'], old['fingerprint']
        if fid['binding'].get('package_id') and fid['binding']['package_id'] == other['binding'].get('package_id'):
            for key, value in fid['binding'].items():
                previous = other['binding'].get(key)
                if value and previous and value != previous:
                    raise ArchiveError('PACKAGE_ID_CONFLICT')
        if old['record_id'] == record['record_id']:
            # Idempotency returns the old reference, not the new candidate.
            # Verify that reference still serves its original return bytes;
            # never silently claim recovery or rewrite an immutable index.
            inspected = reader._inspect(old, include_report=False)
            if (inspected['status'] != 'READY'
                    or any(item['kind'] == 'CHAT_RETURN' and item['status'] != 'HASH_MATCH'
                           for item in inspected['artifacts'])):
                raise ArchiveError('IDEMPOTENT_SOURCE_UNAVAILABLE')
            if old.get('manifest') != record.get('manifest'):
                raise ArchiveError('REGISTRATION_METADATA_CONFLICT')
            return {'record_id': old['record_id'], 'idempotent': True, 'status': 'INDEXED',
                    'receipt_sha256': old['receipt']['sha256']}
        if fid['return_id'] and fid['return_id'] == other['return_id']:
            raise ArchiveError('RETURN_ID_CONFLICT')
    payload = canonical(record) + b'\n'
    filename = record['record_id'] + '.json'
    with directory(reader.index_root / 'records', create=True) as fd:
        temporary = '.tmp-' + uuid4().hex
        out = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
        try:
            with os.fdopen(out, 'wb') as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            # link is atomic create-if-absent. The temporary inode is never served.
            os.link(temporary, filename, src_dir_fd=fd, dst_dir_fd=fd, follow_symlinks=False)
            os.fsync(fd)
        except FileExistsError as exc:
            raise ArchiveError('INDEX_WRITE_CONFLICT') from exc
        finally:
            os.unlink(temporary, dir_fd=fd)
    return {'record_id': record['record_id'], 'idempotent': False, 'status': 'INDEXED',
            'receipt_sha256': record['receipt']['sha256']}


def main(argv=None) -> int:
    parser=argparse.ArgumentParser(description='Register one immutable WeChat receipt as a Stage A reference; no source writes.')
    parser.add_argument('--archive-root',required=True)
    parser.add_argument('--data-root',required=True,help='V4 data root; writes only research/wechat_materials/records')
    parser.add_argument('--receipt',required=True,help='Relative path below archive root')
    parser.add_argument('--receipt-sha256',required=True,help='Expected SHA from the explicitly selected local receipt')
    parser.add_argument('--manifest',help='Optional extracted frozen manifest path below archive root; must bind same v2 input')
    parser.add_argument('--manifest-sha256')
    parser.add_argument('--require-frozen-input', action='store_true',
                        help='Require and verify the selected IMPORT_RECEIPT frozen-input extraction binding')
    args=parser.parse_args(argv)
    try:
        reader=WechatResearchArchive(args.archive_root,Path(args.data_root)/'research/wechat_materials')
        result=register_return(reader,receipt=args.receipt,receipt_sha256=args.receipt_sha256,
                               manifest=args.manifest,manifest_sha256=args.manifest_sha256,
                               require_frozen_input=args.require_frozen_input)
        print(json.dumps(result,ensure_ascii=False)); return 0
    except (ArchiveError,OSError) as exc:
        print(json.dumps({'status':'REJECTED','reason':exc.code if isinstance(exc,ArchiveError) else 'INDEX_IO_ERROR'}))
        return 2


if __name__=='__main__':
    raise SystemExit(main())
