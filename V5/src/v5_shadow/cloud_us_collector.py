"""Pinned complete original US collector closure, distinct from its read adapter."""
import argparse,hashlib,importlib,json,sys
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
    for entry in descriptor()['entries']:
        path=no_symlinks(root/entry['path']);raw=path.read_bytes()
        if not path.is_relative_to(root) or len(raw)!=entry['bytes'] or hashlib.sha256(raw).hexdigest()!=entry['sha256']:
            raise ValueError('CLOUD_US_COLLECTOR_SOURCE_SHA:'+entry['path'])
    return root


def load_owner(root):
    root=verify(root)
    if any(name.split('.')[0] in ('ops','infrastructure','contracts') for name in sys.modules):
        raise ValueError('CLOUD_US_COLLECTOR_FRESH_PROCESS_REQUIRED')
    sys.path.insert(0,str(root))
    owner=importlib.import_module('ops.us_market_digest');transport=importlib.import_module('infrastructure.http_transport')
    verify(root)
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
    finally:verify(args.owner_root)


if __name__=='__main__':raise SystemExit(main())
