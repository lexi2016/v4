"""Pinned complete original US collector closure, distinct from its read adapter."""
import argparse,hashlib,importlib,importlib.abc,importlib.util,json,sys
from pathlib import Path
from v5_shadow.composition import no_symlinks
from v5_shadow.cloud_transport import run_original_us_cli
BASE=Path(__file__).resolve().parents[2]
DESCRIPTOR=BASE/'contracts/cloud_us_collector_sources.json'
PIN='34f45318dd89132a496ac0edf98147455b41d9ea926198d83ce1bd8810c20d8b'


def descriptor():
    raw=DESCRIPTOR.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=PIN:raise ValueError('CLOUD_US_COLLECTOR_DESCRIPTOR_SHA')
    return json.loads(raw)


def verify(root):
    root=no_symlinks(root)
    entries={row['path']:row for row in descriptor()['entries']}
    directories={str(parent) for name in entries for parent in Path(name).parents}
    for path in root.rglob('*'):
        path=no_symlinks(path);relative=str(path.relative_to(root))
        if path.is_dir():
            if relative in directories or (path.name=='__pycache__' and str(path.parent.relative_to(root)) in directories):continue
        elif path.is_file():
            if relative in entries:continue
            # Caches from normal prior Python runs are tolerated but NEVER loaded.
            if path.parent.name=='__pycache__' and path.suffix=='.pyc':
                try:source=Path(importlib.util.source_from_cache(str(path)))
                except ValueError:source=None
                if source is not None and str(source.relative_to(root)) in entries:continue
        raise ValueError('CLOUD_US_COLLECTOR_UNLISTED:'+relative)
    for entry in entries.values():
        path=no_symlinks(root/entry['path']);raw=path.read_bytes()
        if not path.is_relative_to(root) or len(raw)!=entry['bytes'] or hashlib.sha256(raw).hexdigest()!=entry['sha256']:
            raise ValueError('CLOUD_US_COLLECTOR_SOURCE_SHA:'+entry['path'])
    return root


class _PinnedLoader(importlib.abc.Loader):
    def __init__(self,path,entry):self.path=path;self.entry=entry
    def create_module(self,spec):return None
    def exec_module(self,module):
        raw=no_symlinks(self.path).read_bytes()
        if len(raw)!=self.entry['bytes'] or hashlib.sha256(raw).hexdigest()!=self.entry['sha256']:
            raise ValueError('CLOUD_US_COLLECTOR_SOURCE_SHA:'+self.entry['path'])
        # Compile the verified bytes directly: neither valid nor poisoned pyc is read.
        exec(compile(raw,str(self.path),'exec',dont_inherit=True),module.__dict__)


class _PinnedFinder(importlib.abc.MetaPathFinder):
    def __init__(self,root):
        self.root=root;self.modules={};self.namespaces={};self.prefixes={'ops','infrastructure','contracts'}
        for row in descriptor()['entries']:
            path=Path(row['path'])
            if path.suffix!='.py':continue
            package=path.name=='__init__.py'
            name='.'.join(path.parent.parts if package else path.with_suffix('').parts)
            self.modules[name]=(root/path,row,package)
            for parent in path.parents:
                if parent!=Path('.'):self.namespaces['.'.join(parent.parts)]=root/parent
    def find_spec(self,fullname,path=None,target=None):
        if fullname.split('.')[0] not in self.prefixes:return None
        if fullname in self.modules:
            source,row,package=self.modules[fullname]
            return importlib.util.spec_from_file_location(fullname,source,loader=_PinnedLoader(source,row),submodule_search_locations=[str(source.parent)] if package else None)
        if fullname in self.namespaces:
            spec=importlib.machinery.ModuleSpec(fullname,None,is_package=True)
            spec.submodule_search_locations=[str(self.namespaces[fullname])]
            return spec
        # Never fall through to a same-named package elsewhere on sys.path.
        raise ModuleNotFoundError('CLOUD_US_COLLECTOR_UNLISTED_MODULE:'+fullname)
    def audit(self):
        for name,module in tuple(sys.modules.items()):
            if name.split('.')[0] not in self.prefixes:continue
            spec=getattr(module,'__spec__',None)
            if name in self.modules:
                source,row,package=self.modules[name]
                valid=(spec is not None and spec.name==name and spec.origin==str(source) and getattr(module,'__file__',None)==str(source)
                       and isinstance(spec.loader,_PinnedLoader) and module.__loader__ is spec.loader and spec.loader.path==source)
                if package:valid=valid and list(module.__path__)==[str(source.parent)] and list(spec.submodule_search_locations)==[str(source.parent)]
            elif name in self.namespaces:
                valid=(spec is not None and spec.name==name and spec.origin is None and list(module.__path__)==[str(self.namespaces[name])]
                       and list(spec.submodule_search_locations)==[str(self.namespaces[name])])
            else:valid=False
            if not valid:raise ValueError('CLOUD_US_COLLECTOR_MODULE_ORIGIN:'+name)


_ACTIVE_FINDER=None


def audit_modules():
    if _ACTIVE_FINDER is None:raise ValueError('CLOUD_US_COLLECTOR_NOT_LOADED')
    _ACTIVE_FINDER.audit()


def load_owner(root):
    global _ACTIVE_FINDER
    root=verify(root)
    if any(name.split('.')[0] in ('ops','infrastructure','contracts') for name in sys.modules):
        raise ValueError('CLOUD_US_COLLECTOR_FRESH_PROCESS_REQUIRED')
    finder=_PinnedFinder(root);sys.meta_path.insert(0,finder);_ACTIVE_FINDER=finder
    owner=importlib.import_module('ops.us_market_digest');transport=importlib.import_module('infrastructure.http_transport')
    verify(root);audit_modules()
    return owner,transport


MARKER='.v5-cloud-us-capture-root'
MARKER_BYTES=b'v5.cloud-us-capture-root.v1\n'


def initialize_output(path,owner_root):
    path=no_symlinks(path)
    if path.exists():raise ValueError('CLOUD_US_NEW_OUTPUT_REQUIRED')
    if path.is_relative_to(BASE) or BASE.is_relative_to(path) or path.is_relative_to(owner_root) or owner_root.is_relative_to(path):
        raise ValueError('CLOUD_US_OUTPUT_SOURCE_OVERLAP')
    path.mkdir(parents=True);(path/MARKER).write_bytes(MARKER_BYTES)
    return path


def admit_output(path,owner_root):
    path=no_symlinks(path)
    if path.is_relative_to(BASE) or BASE.is_relative_to(path) or path.is_relative_to(owner_root) or owner_root.is_relative_to(path):
        raise ValueError('CLOUD_US_OUTPUT_SOURCE_OVERLAP')
    marker=no_symlinks(path/MARKER)
    if not marker.is_file() or marker.read_bytes()!=MARKER_BYTES:raise ValueError('CLOUD_US_MARKED_PRIVATE_OUTPUT_REQUIRED')
    return path


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--owner-root',type=Path,required=True)
    mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check-only',action='store_true')
    mode.add_argument('--init-data-root',type=Path)
    mode.add_argument('--allow-network-capture',action='store_true')
    parser.add_argument('original_args',nargs=argparse.REMAINDER)
    args=parser.parse_args(argv)
    if args.init_data_root is not None:
        root=verify(args.owner_root);output=initialize_output(args.init_data_root,root)
        print(json.dumps(dict(status='PRIVATE_OUTPUT_INITIALIZED_NOT_CAPTURED',data_root=str(output))))
        return 0
    owner,transport=load_owner(args.owner_root)
    if args.check_only:
        print(json.dumps(dict(status='ORIGINAL_COLLECTOR_SOURCE_VERIFIED',source_commit=descriptor()['source_commit'],files=len(descriptor()['entries']),network_checked=False,capture_executed=False)))
        return 0
    values=args.original_args
    if values[:1]==['--']:values=values[1:]
    parsed=owner.parse_args(values)
    admit_output(parsed.data_root,args.owner_root.resolve())
    try:return run_original_us_cli(owner,transport,values,allow_network_capture=True)
    finally:
        verify(args.owner_root);audit_modules()


if __name__=='__main__':raise SystemExit(main())
