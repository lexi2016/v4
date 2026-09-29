"""Bounded, create-only metadata I/O. No authority or model payload access."""
from __future__ import annotations
import contextlib
import hashlib
import json
import os
import stat
import uuid
from pathlib import Path
from typing import Any, Mapping, Iterator
from .errors import RuntimeV1Error

_SHA=set('0123456789abcdef')
JSON_LIMIT=4*1024*1024

def is_sha256(value: object) -> bool:
    return isinstance(value,str) and len(value)==64 and set(value)<=_SHA

def require_absolute(path: Path, code: str='PATH_NOT_ABSOLUTE') -> Path:
    path=Path(path)
    if not path.is_absolute() or '..' in path.parts or '\\' in str(path) or '\x00' in str(path):
        raise RuntimeV1Error(code,path)
    return path

@contextlib.contextmanager
def directory_fd(path: Path) -> Iterator[int]:
    """Walk from / using O_NOFOLLOW, retaining a descriptor to the final dir."""
    path=require_absolute(path)
    if not hasattr(os,'O_NOFOLLOW') or not hasattr(os,'O_DIRECTORY'):
        raise RuntimeV1Error('NOFOLLOW_NOT_SUPPORTED')
    fd=os.open(path.anchor,os.O_RDONLY|os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            try:
                new=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
            except OSError as exc:
                raise RuntimeV1Error('DIRECTORY_UNSAFE_OR_MISSING',path,part) from exc
            os.close(fd);fd=new
        yield fd
    finally:
        os.close(fd)

def require_directory(path: Path, code: str='DIRECTORY_REQUIRED') -> Path:
    path=require_absolute(path,code)
    with directory_fd(path):
        return path

@contextlib.contextmanager
def regular_fd(path: Path) -> Iterator[int]:
    path=require_absolute(path)
    with directory_fd(path.parent) as parent:
        try:
            fd=os.open(path.name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=parent)
        except OSError as exc:
            raise RuntimeV1Error('FILE_UNSAFE_OR_MISSING',path) from exc
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise RuntimeV1Error('FILE_NOT_REGULAR',path)
            yield fd
        finally:
            os.close(fd)

def require_regular_file(path: Path, code: str='FILE_REQUIRED') -> Path:
    path=require_absolute(path,code)
    with regular_fd(path):
        return path

def read_bytes(path: Path, *, max_bytes: int=JSON_LIMIT) -> bytes:
    with regular_fd(path) as fd:
        if os.fstat(fd).st_size>max_bytes:
            raise RuntimeV1Error('READ_LIMIT_EXCEEDED',path,max_bytes)
        parts=[];size=0
        while True:
            chunk=os.read(fd,min(65536,max_bytes-size+1))
            if not chunk:break
            parts.append(chunk);size+=len(chunk)
            if size>max_bytes:raise RuntimeV1Error('READ_LIMIT_EXCEEDED',path,max_bytes)
        return b''.join(parts)

def sha256_file(path: Path) -> str:
    with regular_fd(path) as fd:
        h=hashlib.sha256()
        while True:
            chunk=os.read(fd,1024*1024)
            if not chunk:break
            h.update(chunk)
        return h.hexdigest()

def _pairs(items):
    result={}
    for k,v in items:
        if k in result:raise ValueError('duplicate key: '+k)
        result[k]=v
    return result

def _constant(text):
    raise ValueError('nonfinite JSON: '+text)

def json_from_bytes(raw: bytes, code: str='JSON_INVALID') -> dict[str,Any]:
    try:
        value=json.loads(raw.decode('utf-8'),object_pairs_hook=_pairs,parse_constant=_constant)
    except (ValueError,UnicodeError,RecursionError) as exc:
        raise RuntimeV1Error(code,str(exc)) from exc
    if not isinstance(value,dict):raise RuntimeV1Error(code,'object required')
    return value

def load_json(path: Path, code: str='JSON_INVALID') -> dict[str,Any]:
    return json_from_bytes(read_bytes(path),code)

def load_json_bound(path: Path, code: str='JSON_INVALID') -> tuple[dict[str,Any],str]:
    raw=read_bytes(path)
    return json_from_bytes(raw,code),hashlib.sha256(raw).hexdigest()

def canonical_json_bytes(value: Mapping[str,Any]) -> bytes:
    try:
        return json.dumps(dict(value),ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
    except (ValueError,TypeError) as exc:
        raise RuntimeV1Error('JSON_SERIALIZATION_INVALID') from exc

def assert_sha(path: Path, expected: str, code: str='SHA256_MISMATCH') -> str:
    if not is_sha256(expected):raise RuntimeV1Error('EXPECTED_SHA256_INVALID',expected)
    actual=sha256_file(path)
    if actual!=expected:raise RuntimeV1Error(code,path,'expected='+expected,'actual='+actual)
    return actual

def within(child: Path,parent: Path) -> bool:
    child=require_absolute(child);parent=require_absolute(parent)
    return child==parent or parent in child.parents

def relative_metadata_path(value: object) -> str:
    if not isinstance(value,str) or not value or '\\' in value or ':' in value or '\x00' in value:
        raise RuntimeV1Error('RESULT_PATH_INVALID',value)
    parts=value.split('/')
    if any(p in ('','.','..') for p in parts) or Path(value).is_absolute() or Path(value).suffix!='.json':
        raise RuntimeV1Error('RESULT_PATH_INVALID',value)
    return value

def require_absent(path: Path) -> None:
    path=require_absolute(path)
    with directory_fd(path.parent) as parent:
        try:os.stat(path.name,dir_fd=parent,follow_symlinks=False)
        except FileNotFoundError:return
        except OSError as exc:raise RuntimeV1Error('OUTPUT_CHECK_FAILED',path) from exc
        raise RuntimeV1Error('OUTPUT_ALREADY_EXISTS',path)

def require_new_output_path(path: Path) -> Path:
    """Keep the original facade API with the closeout no-follow path walk."""
    path = Path(path)
    if not path.is_absolute():
        path = Path.cwd() / path
    require_absolute(path, 'OUTPUT_PATH_NOT_ABSOLUTE')
    require_absent(path)
    return path

def atomic_bytes(path: Path, raw: bytes, *, mode: int=0o600) -> str:
    """Create a complete file atomically. Never replace an existing name/link."""
    path=require_absolute(path)
    with directory_fd(path.parent) as parent:
        tmp='.'+path.name+'.'+uuid.uuid4().hex+'.tmp'
        fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,mode,dir_fd=parent)
        try:
            with os.fdopen(fd,'wb') as out:
                out.write(raw);out.flush();os.fchmod(out.fileno(),mode);os.fsync(out.fileno())
            try:
                os.link(tmp,path.name,src_dir_fd=parent,dst_dir_fd=parent,follow_symlinks=False)
            except FileExistsError as exc:raise RuntimeV1Error('OUTPUT_ALREADY_EXISTS',path) from exc
            os.fsync(parent)
        finally:
            os.unlink(tmp,dir_fd=parent)
    return hashlib.sha256(raw).hexdigest()

def atomic_json(path: Path,payload: Mapping[str,Any],*,mode: int=0o600) -> str:
    return atomic_bytes(path,canonical_json_bytes(payload)+b'\n',mode=mode)

def new_directory(path: Path) -> Path:
    path=require_absolute(path)
    with directory_fd(path.parent) as parent:
        try:os.mkdir(path.name,0o700,dir_fd=parent)
        except FileExistsError as exc:raise RuntimeV1Error('RUN_DIR_ALREADY_EXISTS',path) from exc
    return require_directory(path)

def exclusive_stream(path: Path):
    path=require_absolute(path)
    with directory_fd(path.parent) as parent:
        try:fd=os.open(path.name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=parent)
        except FileExistsError as exc:raise RuntimeV1Error('OUTPUT_ALREADY_EXISTS',path) from exc
    return os.fdopen(fd,'w',encoding='utf-8')
