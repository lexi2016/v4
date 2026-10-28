"""Darwin FD-based exact plist metadata; setters are used only on owned CAS temp.
Python's os xattr API is unavailable in the installed macOS runtime. Signatures:
Apple SDK sys/xattr.h f{list,get,set,remove}xattr. No command subprocess fallback.
"""
from __future__ import annotations
import base64,ctypes,hashlib,json,os,stat
from pathlib import Path
class MetadataError(RuntimeError):pass
_LIB=ctypes.CDLL('/usr/lib/libSystem.B.dylib',use_errno=True)
for name,args,ret in [
 ('flistxattr',[ctypes.c_int,ctypes.c_void_p,ctypes.c_size_t,ctypes.c_int],ctypes.c_ssize_t),
 ('fgetxattr',[ctypes.c_int,ctypes.c_char_p,ctypes.c_void_p,ctypes.c_size_t,ctypes.c_uint32,ctypes.c_int],ctypes.c_ssize_t),
 ('fsetxattr',[ctypes.c_int,ctypes.c_char_p,ctypes.c_void_p,ctypes.c_size_t,ctypes.c_uint32,ctypes.c_int],ctypes.c_int),
 ('fremovexattr',[ctypes.c_int,ctypes.c_char_p,ctypes.c_int],ctypes.c_int)]:
 fn=getattr(_LIB,name);fn.argtypes=args;fn.restype=ret

def _ok(value):
 if value<0:
  code=ctypes.get_errno();raise MetadataError('XATTR_SYSCALL_FAILED:'+str(code)+':'+os.strerror(code))
 return value

def _names(fd):
 size=_ok(_LIB.flistxattr(fd,None,0,0))
 if size>1024*1024:raise MetadataError('XATTR_NAME_SIZE_LIMIT')
 if not size:return []
 buf=ctypes.create_string_buffer(size);got=_ok(_LIB.flistxattr(fd,buf,size,0))
 if got!=size:raise MetadataError('XATTR_NAMES_CHANGED')
 raw=buf.raw[:got]
 if not raw.endswith(b'\0'):raise MetadataError('XATTR_LIST_INVALID')
 names=raw[:-1].split(b'\0')
 if len(names)!=len(set(names)) or any(not n for n in names):raise MetadataError('XATTR_NAMES_INVALID')
 return sorted(names)

def _get(fd,name):
 size=_ok(_LIB.fgetxattr(fd,name,None,0,0,0))
 if size>16*1024*1024:raise MetadataError('XATTR_VALUE_SIZE_LIMIT')
 if not size:return b''
 buf=ctypes.create_string_buffer(size);got=_ok(_LIB.fgetxattr(fd,name,buf,size,0,0))
 if got!=size:raise MetadataError('XATTR_VALUE_CHANGED')
 return buf.raw[:got]

def snapshot_fd(fd):
 before=os.fstat(fd)
 if not stat.S_ISREG(before.st_mode):raise MetadataError('METADATA_NOT_REGULAR')
 names=_names(fd);attrs={}
 for name in names:
  raw=_get(fd,name);attrs[os.fsdecode(name)]={'base64':base64.b64encode(raw).decode(),'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}
 after=os.fstat(fd)
 if (before.st_dev,before.st_ino,before.st_uid,before.st_gid,before.st_mode,before.st_ctime_ns)!=(after.st_dev,after.st_ino,after.st_uid,after.st_gid,after.st_mode,after.st_ctime_ns) or _names(fd)!=names:raise MetadataError('METADATA_CHANGED_DURING_READ')
 return {'uid':after.st_uid,'gid':after.st_gid,'mode':stat.S_IMODE(after.st_mode),'xattrs':attrs}

def snapshot(path):
 p=Path(path)
 if p.resolve()!=p.absolute():raise MetadataError('METADATA_SYMLINK_OR_ESCAPE')
 fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW)
 try:return snapshot_fd(fd)
 finally:os.close(fd)

def require(path,expected):
 if snapshot(path)!=expected:raise MetadataError('PLIST_METADATA_DRIFT:'+str(path))

def apply_fd(fd,expected):
 attrs={}
 for name,v in expected['xattrs'].items():
  raw=base64.b64decode(v['base64'],validate=True)
  if len(raw)!=v['bytes'] or hashlib.sha256(raw).hexdigest()!=v['sha256']:raise MetadataError('FROZEN_XATTR_BYTES_INVALID')
  attrs[os.fsencode(name)]=raw
 s=os.fstat(fd)
 if (s.st_uid,s.st_gid)!=(expected['uid'],expected['gid']):os.fchown(fd,expected['uid'],expected['gid'])
 os.fchmod(fd,expected['mode'])
 for name in _names(fd):
  if name not in attrs:_ok(_LIB.fremovexattr(fd,name,0))
 for name,raw in attrs.items():
  buf=ctypes.create_string_buffer(raw)
  _ok(_LIB.fsetxattr(fd,name,buf,len(raw),0,0))
 os.fsync(fd)
 if snapshot_fd(fd)!=expected:raise MetadataError('TEMP_METADATA_NOT_PRESERVED')

def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()
