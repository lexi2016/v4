"""Single-host, V5-only version composition; never controls a V4 service."""
import fcntl
import json
import os
import stat
import tempfile
from dataclasses import asdict
from pathlib import Path
from .contracts import Binding, Composition, ModuleManifest, exact_keys, parse_manifest, sha
from .digests import canonical_bytes, sha256_json


def plain(value):
    if hasattr(value, '__dataclass_fields__'):
        return plain(asdict(value))
    if isinstance(value,Path):return str(value)
    if isinstance(value,dict):return {k:plain(v) for k,v in value.items()}
    if isinstance(value,(tuple,list)):return [plain(v) for v in value]
    return value


def no_symlinks(path: Path) -> Path:
    path=Path(path)
    if not path.is_absolute() or '..' in path.parts:
        raise ValueError('PATH_INVALID')
    for part in (path,*path.parents):
        if part.is_symlink():raise ValueError('SYMLINK_REJECTED')
    return path.resolve()


def shadow_root(path: Path) -> Path:
    root=no_symlinks(path)
    marker=root/'.v5-shadow-root'
    if marker.is_symlink() or not marker.is_file() or marker.read_text()!='v5.shadow-root.v1\n':
        raise ValueError('SHADOW_ROOT_NOT_INITIALIZED')
    return root


def parse_binding(value: dict) -> Binding:
    exact_keys(value,Binding.__dataclass_fields__)
    root=shadow_root(Path(value['shadow_root']))
    source=value['authority_root']
    if source is not None:
        source=no_symlinks(Path(source))
        if source.is_relative_to(root) or root.is_relative_to(source):
            raise ValueError('SOURCE_OUTPUT_OVERLAP')
    inp=value['input_snapshot_sha256']
    if inp is not None:sha(inp)
    return Binding(source,root,sha(value['calendar_sha256']),sha(value['source_capsule_sha256']),inp)


def validate_composition(value: dict, manifests: dict[str,ModuleManifest]) -> Composition:
    exact_keys(value,Composition.__dataclass_fields__)
    canonical_bytes(value)
    if value['schema_version']!='v5.composition.v1' or type(value['revision']) is not int or value['revision']<1:
        raise ValueError('COMPOSITION_INVALID')
    if not isinstance(value['modules'],dict) or not isinstance(value['bindings'],dict):
        raise ValueError('COMPOSITION_INVALID')
    modules={key:parse_manifest(val) for key,val in value['modules'].items()}
    if set(modules)!=set(manifests):raise ValueError('MODULE_MANIFEST_MISMATCH')
    for key,module in modules.items():
        if key!=module.module_id or module!=manifests[key]:raise ValueError('MODULE_MANIFEST_MISMATCH')
        for dependency in module.requires:
            provider=modules.get(dependency.module_id)
            if provider is None or provider.output_contract!=dependency.input_contract or not set(dependency.required_capabilities)<=set(provider.capabilities):
                raise ValueError('INCOMPATIBLE_DEPENDENCY')
    if 'rebound_shadow' not in modules or 'rebound_shadow' not in value['bindings']:
        raise ValueError('COMPOSITION_REBOUND_MISSING')
    if set(value['bindings'])-set(modules):raise ValueError('BINDING_MODULE_UNKNOWN')
    bindings={key:parse_binding(val) for key,val in value['bindings'].items()}
    return Composition(value['schema_version'],value['revision'],modules,bindings)


def render_effective_config(composition: Composition,module_id: str) -> dict:
    if module_id!='rebound_shadow':raise ValueError('MODULE_EXECUTION_NOT_ALLOWED')
    return {'module':plain(composition.modules[module_id]),'binding':plain(composition.bindings[module_id])}


def atomic_bytes(path: Path,data: bytes):
    path=no_symlinks(path)
    fd,name=tempfile.mkstemp(prefix='.'+path.name+'.',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as output:
            output.write(data);output.flush();os.fsync(output.fileno())
        os.replace(name,path)
        directory=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(directory)
        finally:os.close(directory)
    finally:
        if os.path.exists(name):os.unlink(name)


def switch_module(path: Path,module_id: str,new_manifest: ModuleManifest,expected_sha256: str) -> str:
    if module_id!='rebound_shadow' or new_manifest.module_id!=module_id:
        raise ValueError('MODULE_SWITCH_NOT_ALLOWED')
    sha(expected_sha256)
    path=no_symlinks(path)
    raw=json.loads(path.read_text())
    initial=validate_composition(raw,{k:parse_manifest(v) for k,v in raw['modules'].items()})
    root=initial.bindings[module_id].shadow_root
    if not path.is_relative_to(root):raise ValueError('COMPOSITION_PATH_OUTSIDE_SHADOW')
    lockpath=root/'.composition.lock'
    fd=os.open(lockpath,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):raise ValueError('LOCK_INVALID')
        fcntl.flock(fd,fcntl.LOCK_EX)
        raw=json.loads(no_symlinks(path).read_text())
        validate_composition(raw,{k:parse_manifest(v) for k,v in raw['modules'].items()})
        if sha256_json(raw)!=expected_sha256:raise ValueError('STALE_COMPOSITION')
        raw['modules'][module_id]=plain(new_manifest)
        raw['revision']+=1
        validate_composition(raw,{k:parse_manifest(v) for k,v in raw['modules'].items()})
        atomic_bytes(path,canonical_bytes(raw))
        return sha256_json(raw)
    finally:
        os.close(fd)
