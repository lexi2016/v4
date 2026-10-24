"""Finite hash-bound release overlay; no service, data or Git operations."""
from __future__ import annotations

import argparse
import base64
import csv
from email.parser import Parser
import io
import platform
import struct
import zipfile
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import plistlib
import re
import shutil
import stat
import subprocess
import sys

sys.dont_write_bytecode = True
SCHEMA = "v4.us_hk.release_scope.v1"
REHEARSAL_BASE = Path(__file__).resolve().parents[4] / '.superpowers/sdd/2026-10-23-us-hk-selection-closure/scratch/deployment'
WORKTREE = Path(__file__).resolve().parents[4]
RELEASES = Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/releases')
LAUNCHAGENTS = Path('/Users/lexi/Library/LaunchAgents')
LABELS = {'api': 'com.lexi.v35.api-only', 'scheduler': 'com.lexi.v35.scheduler'}
HK_CHILD_PARENT = Path('/Users/lexi/Desktop/学习/agents调试/MANAGER_R3_BUSINESS_FIX_20260930/r3a/build/r3a-r9-import-closure-20260930T193024Z')
HK_CHILD_MANIFEST = 'ac239a1c86021da15a321ab7a383822574373bb4f3c976ad27aadc03fb62da91'
HK_CHILD_MODULE = '07aa9770c6ae0bb0cfd012e57843a37fedda6724a57cd52d7c339d854fc6609b'
HK_CHILD_NAME = 'us-hk-selection-hk-child-20261024-r1'
SHARED_PARENT=Path('/Users/lexi/Library/Application Support/com.lexi.v35.local/releases/20260923-hk02-owner-rebase-r2')
SHARED_MANIFEST='160fcc92fb35c943c6d2fe842bb28ff71ec4129e64f43bb2a2b9ee99a7ae9c0a'
SHARED_PREFIX='upstreams/v3_shared_data/'
SHARED_SOURCE_PATHS={SHARED_PREFIX+'scripts/update_hk_0_2_panel.py'}|{
    SHARED_PREFIX+'shared_data/'+name+'.py' for name in ('__init__','allowlist','collectors','constants','consumer',
        'hashing','hk_0_2','hk_history_resolution','hk_panel_audit','hk_d1_evidence','hk_security_master','paths','store')}
CAPTURE_PATHS = {'ops/macos_research_panel_daily.py', 'ops/_hk_provider_capture.py'}
HK_SDK_DISTRIBUTIONS = {
    'futu_api': ('10.6.6608','py3-none-any','futu'),
    'simplejson': ('4.1.1','cp313-cp313-macosx_11_0_arm64','simplejson'),
    'protobuf': ('7.35.1','cp310-abi3-macosx_10_9_universal2','google'),
    'pycryptodome': ('3.23.0','cp37-abi3-macosx_10_9_universal2','Crypto'),
}
HK_SDK_REQUIREMENTS = {'futu_api':['pandas','simplejson','protobuf>=3.20.0','PyCryptodome'],
                       'simplejson':[],'protobuf':[],'pycryptodome':[]}
HK_SDK_REQUIRES_PYTHON = {
    'futu_api':None, 'protobuf':'>=3.10',
    'pycryptodome':'>=2.7, !=3.0.*, !=3.1.*, !=3.2.*, !=3.3.*, !=3.4.*, !=3.5.*, !=3.6.*',
    'simplejson':'>=2.7, !=3.0.*, !=3.1.*, !=3.2.*, !=3.3.*, !=3.4.*, !=3.5.*, !=3.6.*, !=3.7.*',
}
HK_SDK_RELEASE_MAP = 'ce4f2995f0c296195b01cb96c4e6b4790973324566aadf010f0750b5894a9620'
HK_SDK_RELEASE_COUNT, HK_SDK_RELEASE_BYTES = 731, 28388099
HK_SDK_MAX_ENTRIES, HK_SDK_MAX_BYTES, HK_SDK_MAX_FILE_BYTES = 800, 30000000, 9000000
HK_SDK_PYTHON_SHA = '95fb891ec36d4022bdf62172f9d3c757fb3c7b1669a274cacc87fe261a535b7e'
HK_SDK_WRAPPER_SHA = '817900c6e835d5c66fc3c3df4827625cfd3c56dd3d1ebc1b2f82191c197b10a6'
ANNOUNCEMENT_PATHS = {
    'apps/api/v35_api/app.py', 'apps/api/v35_api/hkex_announcements_router.py',
    'v4/manager_research/announcement_source.py', 'v4/manager_research/hkex_directory_protocol.py',
    'v4/manager_research/hkex_provider.py', 'v4/manager_research/hkex_runtime.py',
    'v4/manager_research/workspace_announcements.py',
}


class Stop(ValueError):
    pass


def require(condition, reason):
    if not condition:
        raise Stop(reason)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def sha(path):
    return digest(Path(path).read_bytes())


def exact(path, *, exists=True):
    p = Path(path)
    require(p.is_absolute() and str(p) == os.path.abspath(p), "NON_CANONICAL_PATH")
    require(p.resolve(strict=exists) == p and not p.is_symlink(), "SYMLINK_OR_ALIAS")
    if exists:
        require(p.exists(), "MISSING_PATH:" + str(p))
    return p


def child(root, relative, *, exists=True):
    require(isinstance(relative, str) and relative != "", "EMPTY_RELATIVE")
    rel = PurePosixPath(relative)
    require(not rel.is_absolute() and rel.as_posix() == relative and
            all(x not in (".", "..") for x in rel.parts) and
            "\\" not in relative and "\x00" not in relative, "UNSAFE_RELATIVE")
    p = exact(Path(root) / relative, exists=exists)
    require(p.is_relative_to(root), "PATH_ESCAPE")
    if exists:
        require(p.is_file(), "NOT_REGULAR_FILE")
    return p


def read_json(path, expected):
    p = exact(path)
    require(p.is_file() and sha(p) == expected, "FILE_SHA_DRIFT:" + str(p))
    value = json.loads(p.read_bytes())
    require(isinstance(value, dict), "JSON_NOT_OBJECT")
    return value


def write_new(path, raw):
    p = Path(path)
    exact(p.parent)
    require(not p.exists() and not p.is_symlink(), "EVIDENCE_COLLISION:" + str(p))
    with p.open("xb") as stream:
        stream.write(raw)


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()


def contract_sha(scope):
    return digest(json.dumps({k:v for k,v in scope.items() if k != 'execution_capsule'},
                             sort_keys=True, separators=(',', ':'), allow_nan=False).encode())


def authorized_capsule(scope, action):
    """Authenticate a hash-bound capsule's action and original scope contract."""
    pin = scope.get('execution_capsule')
    require(isinstance(pin, dict), 'FINAL_CONTROLLER_CAPSULE_REQUIRED')
    capsule = read_json(pin['path'], pin['sha256'])
    require(capsule.get('schema') == 'v4.us_hk.execution_capsule.v1' and
            capsule.get('verdict') == 'PASS' and action in capsule.get('authorized_actions', []) and
            capsule.get('scope_contract_sha256') == contract_sha(scope), 'CAPSULE_ACTION_OR_SCOPE_MISMATCH')
    return capsule


def authorize(scope, action):
    """Controller supplies this separately after independent source/helper PASS."""
    capsule = authorized_capsule(scope, action)
    expected_helpers = capsule.get('helper_sha256', {})
    for name in ('prepare_release.py', 'activate_release.py'):
        require(expected_helpers.get(name) == sha(Path(__file__).with_name(name)), 'UNREVIEWED_HELPER')
    return capsule


def release_paths(scope):
    require(exact(scope['source_root']) == exact(WORKTREE), 'RELEASE_SOURCE_ROOT_MISMATCH')
    candidate = exact(scope['candidate_root'], exists=False)
    require(candidate.parent == exact(RELEASES) and candidate.name.startswith('us-hk-selection-' + scope['role'] + '-'),
            'RELEASE_CANDIDATE_OUTSIDE_GRANT')
    evidence = exact(scope['evidence_root'])
    require(evidence.is_relative_to(exact(REHEARSAL_BASE)) and evidence != REHEARSAL_BASE,
            'RELEASE_EVIDENCE_OUTSIDE_LOCAL_SCRATCH')
    if scope['role'] in LABELS:
        require(exact(scope['plist']['path']) == exact(LAUNCHAGENTS / (LABELS[scope['role']] + '.plist')),
                'RELEASE_PLIST_OUTSIDE_ROLE')
        require(exact(scope['parent_root']).parent == exact(RELEASES), 'RELEASE_PARENT_OUTSIDE_GRANT')
    elif scope['role']=='hk-child':
        require(candidate.name==HK_CHILD_NAME and exact(scope['parent_root'])==exact(HK_CHILD_PARENT) and
                scope['parent_manifest_sha256']==HK_CHILD_MANIFEST,'HK_CHILD_FIXED_BASE_REQUIRED')
        require(scope.get('plist') is None and not scope.get('clone_subtree'),'HK_CHILD_HAS_NO_SERVICE_OR_SUBTREE')
        probe=scope.get('runtime_probe') or {}
        require(probe.get('wrapper') is not None and probe.get('modules')=={
            'ops.macos_research_panel_daily':'ops/macos_research_panel_daily.py',
            'ops._hk_provider_capture':'ops/_hk_provider_capture.py'},'HK_CHILD_WRAPPER_AND_CAPTURE_PROBE_REQUIRED')
    else:
        require(scope['role']=='shared' and exact(scope['parent_root'])==exact(SHARED_PARENT) and
                scope['parent_manifest_sha256']==SHARED_MANIFEST,'SHARED_FIXED_PARENT_REQUIRED')
        require(scope.get('plist') is None and scope.get('clone_subtree') == 'upstreams/v3_shared_data',
                'SHARED_RELEASE_REQUIRES_FINITE_PACKAGE_NO_SERVICE')
        require(scope.get('runtime_probe',{}).get('updater_relative')=='upstreams/v3_shared_data/scripts/update_hk_0_2_panel.py' and
                scope['runtime_probe'].get('wrapper') is not None,'SHARED_EXACT_UPDATER_WRAPPER_PROBE_REQUIRED')
    require(scope.get('runtime_probe') is not None, 'ACTUAL_ROLE_RUNTIME_PROBE_REQUIRED')
    if scope['role'] == 'api':
        require(ANNOUNCEMENT_PATHS <= {p['path'] for p in scope.get('preserved_app_files', [])},
                'LATEST_ANNOUNCEMENT_DEPENDENCIES_REQUIRED')


def source_file(scope, row):
    if row.get('origin', 'source') == 'build':
        require(scope.get('frontend_build') is not None, 'UNBOUND_BUILD_INPUT')
        root = scope['frontend_build']['output_root']
    else:
        require(row.get('origin', 'source') == 'source', 'OVERLAY_ORIGIN_INVALID')
        root = scope['source_root']
    return child(root, row['source'])


def inventory_tool(pin):
    path = exact(pin["path"])
    require(sha(path) == pin["sha256"], "INVENTORY_TOOL_DRIFT")
    spec = importlib.util.spec_from_file_location("us_hk_retained_inventory", path)
    module = importlib.util.module_from_spec(spec)
    old_path = list(sys.path)
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path[:] = old_path
    return module


def load_scope(path, expected):
    scope = read_json(path, expected)
    require(scope.get("schema") == SCHEMA and scope.get("state") == "READY", "SCOPE_NOT_READY")
    require(scope.get("mode") in ("REHEARSAL", "RELEASE"), "SCOPE_MODE")
    require(scope.get("role") in ("api", "scheduler", "shared", "hk-child"), "ROLE_INVALID")
    require(scope.get("safety") == dict(research_only=True, production_allowed=False,
            buy_gate_updated=False, orders_sent=False), "SAFETY_SCOPE_INVALID")
    require(isinstance(scope.get("source_commit"), str) and len(scope["source_commit"]) == 40 and
            all(x in "0123456789abcdef" for x in scope["source_commit"]), "SOURCE_COMMIT_INVALID")
    require(scope.get("data_pointer_changes") == [], "DATA_PROMOTION_FORBIDDEN")
    for name in ("source_root", "evidence_root"):
        require(exact(scope[name]).is_dir(), "ROOT_INVALID")
    parent = exact(scope["parent_root"])
    candidate = exact(scope["candidate_root"], exists=False)
    require(parent != candidate and not candidate.is_relative_to(parent) and
            not parent.is_relative_to(candidate), "CANDIDATE_PARENT_OVERLAP")
    require(not candidate.exists(), "CANDIDATE_COLLISION")
    exact(candidate.parent)
    if scope["mode"] == "REHEARSAL":
        boundary = exact(scope["rehearsal_root"])
        require(boundary.is_relative_to(exact(REHEARSAL_BASE)) and boundary != REHEARSAL_BASE and
                boundary.name.startswith('rehearsal-'), "REHEARSAL_BOUNDARY_INVALID")
        for p in [parent, candidate, Path(scope["source_root"]), Path(scope["evidence_root"])]:
            require(p.is_relative_to(boundary) and p != boundary, "REHEARSAL_PATH_ESCAPE")
        for pin in scope.get("dependencies", []):
            require(exact(pin["path"]).is_relative_to(boundary), "REHEARSAL_DEPENDENCY_ESCAPE")
        if scope.get("plist"):
            require(exact(scope["plist"]["path"]).is_relative_to(boundary), "REHEARSAL_PLIST_ESCAPE")
    else:
        authorize(scope, 'prepare')
        release_paths(scope)
    return scope


def validated_parent_inventory(scope,tool,manifest,observed,generated_cache=()):
    """Consume each retained native schema without changing its manifest."""
    app=Path(scope['parent_root'])/'app'
    if scope['role']=='shared' and 'shared_package_inventory' in manifest:
        native=manifest['shared_package_inventory'];expected=native['candidate_entries']
        require(native.get('algorithm')=='sha256(canonical JSON records; cache, bytecode and node_modules excluded)' and
                native.get('candidate_entry_count')==len(expected) and
                tool.inventory_digest(expected)==native['candidate_aggregate_sha256'],'SHARED_NATIVE_INVENTORY_DIGEST')
        declared={}
        for row in expected:
            relative=row['path'];parts=PurePosixPath(relative)
            require(not parts.is_absolute() and parts.as_posix()==relative and all(x not in ('.','..') for x in parts.parts)
                    and row.get('kind')=='file' and set(row)=={'path','kind','mode','size','sha256'},'SHARED_NATIVE_ENTRY_INVALID')
            require(relative not in declared,'SHARED_NATIVE_DUPLICATE_PATH');declared[relative]=row
        found={};excluded=[]
        for row in [*observed,*generated_cache]:
            require(row['path'].startswith(SHARED_PREFIX),'SHARED_NATIVE_OUTSIDE_PACKAGE')
            relative=row['path'][len(SHARED_PREFIX):];normalized=dict(row,path=relative)
            if relative in declared:
                require(normalized==declared[relative],'SHARED_NATIVE_ENTRY_DRIFT:'+relative);found[relative]=normalized;continue
            parts=PurePosixPath(relative);match=re.fullmatch(r'(.+)\.cpython-(313|314)\.pyc',parts.name)
            source=(parts.parent.parent/(match.group(1)+'.py')).as_posix() if match and parts.parent.name=='__pycache__' else None
            require(source in declared and row['kind'] in {'file','generated_python_bytecode_cache'},
                    'SHARED_NATIVE_UNEXPECTED_ENTRY:'+relative)
            excluded.append(row)
        require(found==declared,'SHARED_NATIVE_ENTRY_MISSING')
        normalized=[dict(row,path=SHARED_PREFIX+row['path']) for row in expected]
        return normalized,dict(native_schema='shared_package_inventory',native_entry_count=len(expected),
            native_aggregate_sha256=native['candidate_aggregate_sha256'],verified_original_entries=expected,
            excluded_generated_cache=excluded,original_manifest_unchanged=True)
    native=manifest['application_inventory'];expected=native['entries']
    require(native.get('entry_count',len(expected))==len(expected) and tool.inventory_digest(expected)==native['aggregate_sha256'],
            'PARENT_INVENTORY_DIGEST')
    directories=[row for row in expected if row.get('kind')=='directory']
    if directories:
        require(scope['role']=='scheduler','DIRECTORY_NATIVE_SCHEMA_ROLE_UNSUPPORTED')
        expected_paths=set()
        for row in directories:
            require(set(row)=={'path','kind','mode'} and row['path'] not in expected_paths,'PARENT_DIRECTORY_RECORD_INVALID')
            relative=row['path'];target=app if relative=='.' else exact(app/relative)
            require(target.is_relative_to(app) and target.is_dir() and not target.is_symlink() and
                    format(stat.S_IMODE(target.stat().st_mode),'04o')==row['mode'],'PARENT_DIRECTORY_DRIFT:'+relative)
            expected_paths.add(relative)
        actual_paths={'.'}
        for directory,names,_ in os.walk(app,followlinks=False):
            for name in names:
                target=Path(directory)/name
                if not target.is_symlink():actual_paths.add(target.relative_to(app).as_posix())
        extras=actual_paths-expected_paths;cache_paths={row['path'] for row in generated_cache}
        native_files={row['path'] for row in expected if row.get('kind')=='file'}
        for relative in extras:
            directory=app/relative;members=list(directory.iterdir())
            require(directory.name=='__pycache__' and members and all(
                path.is_file() and not path.is_symlink() and path.relative_to(app).as_posix() in cache_paths for path in members),
                'PARENT_DIRECTORY_SET_DRIFT')
            for path in members:
                match=re.fullmatch(r'(.+)\.cpython-314\.pyc',path.name)
                source=(directory.parent/(match.group(1)+'.py')).relative_to(app).as_posix() if match else None
                require(source in native_files,'PARENT_CACHE_SOURCE_UNDECLARED')
        require(expected_paths<=actual_paths,'PARENT_DIRECTORY_SET_DRIFT')
    leaves=[row for row in expected if row.get('kind')!='directory']
    require(observed==leaves,'PARENT_INVENTORY_DRIFT')
    return observed,dict(native_schema='application_inventory',native_entry_count=len(expected),
        native_aggregate_sha256=native['aggregate_sha256'],verified_directory_entries=directories,
        excluded_generated_cache=list(generated_cache),
        excluded_generated_cache_directories=sorted(extras) if directories else [],
        normalized_leaf_count=len(observed),normalized_leaf_aggregate_sha256=tool.inventory_digest(observed),
        original_manifest_unchanged=True)


def sdk_map_sha(entries):
    return digest(json.dumps(entries,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode())


def sdk_native_arm64(raw):
    """Read Mach-O headers; never load a dependency while validating inputs."""
    require(len(raw)>=32,'HK_SDK_NATIVE_HEADER')
    magic=struct.unpack_from('>I',raw)[0];slices=[]
    if magic in (0xcafebabe,0xbebafeca,0xcafebabf,0xbfbafeca):
        endian='>' if magic in (0xcafebabe,0xcafebabf) else '<'
        fmt=endian+('IIQQII' if magic in (0xcafebabf,0xbfbafeca) else 'IIIII')
        count=struct.unpack_from(endian+'I',raw,4)[0]
        require(0<count<=8,'HK_SDK_NATIVE_ARCH_COUNT')
        for i in range(count):
            row=struct.unpack_from(fmt,raw,8+i*struct.calcsize(fmt));slices.append((row[0],row[2]))
    else:
        require(raw[:4]==b'\xcf\xfa\xed\xfe','HK_SDK_NATIVE_FORMAT')
        slices=[(struct.unpack_from('<I',raw,4)[0],0)]
    arm=[offset for cpu,offset in slices if cpu==0x0100000c]
    require(arm,'HK_SDK_NATIVE_ARM64_REQUIRED')
    for offset in arm:
        view=raw[offset:];require(view[:4]==b'\xcf\xfa\xed\xfe','HK_SDK_NATIVE_FORMAT')
        count=struct.unpack_from('<I',view,16)[0];require(count<=128,'HK_SDK_NATIVE_COMMANDS')
        pos=32
        for _ in range(count):
            cmd,size=struct.unpack_from('<II',view,pos)
            require(size>=8 and pos+size<=len(view),'HK_SDK_NATIVE_COMMAND_SIZE')
            if cmd in (0xc,0x80000018,0x8000001f):
                name_offset=struct.unpack_from('<I',view,pos+8)[0]
                require(8<=name_offset<size,'HK_SDK_NATIVE_LIBRARY_OFFSET')
                name=view[pos+name_offset:pos+size].split(b'\0')[0].decode()
                require(name.startswith(('/usr/lib/','/System/Library/')),'HK_SDK_NATIVE_EXTERNAL_LINK')
            if cmd in (0x24,0x32):
                version=struct.unpack_from('<I',view,pos+(8 if cmd==0x24 else 12))[0]
                require((version>>16)<=int(platform.mac_ver()[0].split('.')[0]),'HK_SDK_NATIVE_MACOS_TOO_OLD')
            pos+=size


def sdk_record(raw):
    values={}
    for relative,encoded,size in csv.reader(io.StringIO(raw.decode())):
        require(relative not in values,'HK_SDK_RECORD_DUPLICATE')
        if encoded:
            algorithm,value=encoded.split('=',1)
            require(algorithm=='sha256','HK_SDK_RECORD_ALGORITHM')
            values[relative]=(base64.urlsafe_b64decode(value+'='*((-len(value))%4)).hex(),int(size))
    return values


def hk_sdk_bytes(row,distribution):
    """One approved source/member; no extraction, resolver or package import."""
    source=row['source'];relative=row['target']
    if source['kind']=='PINNED_EXISTING_DISTRIBUTION_RECORD':
        require(distribution['kind']=='INSTALLED_RECORD' and
                source['path']==str(Path(distribution['site_root'])/relative),'HK_SDK_SOURCE_OWNER')
        p=child(exact(distribution['site_root']),relative)
        require(stat.S_IMODE(p.stat().st_mode)==int(row['mode'],8),'HK_SDK_SOURCE_MODE')
        require(p.stat().st_size==row['bytes'],'HK_SDK_SOURCE_SIZE')
        raw=p.read_bytes()
    else:
        require(source['kind']=='OFFICIAL_MATCHING_WHEEL_MEMBER' and distribution['kind']=='OFFICIAL_WHEEL' and
                source['member']==relative and source['wheel_path']==distribution['archive']['path'] and
                source['wheel_sha256']==distribution['archive']['sha256'],'HK_SDK_WHEEL_SOURCE_OWNER')
        archive=exact(distribution['archive']['path']);require(sha(archive)==distribution['archive']['sha256'],'HK_SDK_WHEEL_DRIFT')
        with zipfile.ZipFile(archive) as wheel:
            info=wheel.getinfo(relative)
            require(not info.is_dir() and stat.S_IFMT(info.external_attr>>16)!=stat.S_IFLNK and
                    info.file_size==row['bytes'] and info.file_size<=HK_SDK_MAX_FILE_BYTES,'HK_SDK_WHEEL_MEMBER_TYPE_SIZE')
            require((info.external_attr>>16&0o777 or 0o644)==int(row['mode'],8),'HK_SDK_WHEEL_MEMBER_MODE')
            raw=wheel.read(info)
    require(len(raw)==row['bytes'] and digest(raw)==row['sha256'],'HK_SDK_PAYLOAD_DRIFT')
    if relative.endswith(('.so','.dylib')):
        name=distribution['name']
        require((name in ('protobuf','pycryptodome') and relative.endswith('.abi3.so')) or
                (name=='simplejson' and relative=='simplejson/_speedups.cpython-313-darwin.so'),'HK_SDK_NATIVE_ABI')
        try:sdk_native_arm64(raw)
        except (struct.error,UnicodeError,IndexError) as exc:raise Stop('HK_SDK_NATIVE_HEADER_INVALID') from exc
    return raw


def hk_sdk_runtime_binding(scope):
    probe=scope['runtime_probe'];app=str(Path(scope['candidate_root'])/'app')
    return dict(python={k:probe['python'][k] for k in ('path','resolved_path','sha256','version')},
                wrapper=probe.get('wrapper'),site_packages=probe['site_packages'],
                search_roots=probe.get('search_roots',[app,app+'/upstreams']),
                environment=probe.get('environment',{}),updater_relative=probe.get('updater_relative'))


def hk_sdk_artifact(scope):
    """Optional DATA07 only. The independent receipt approves one exact file map."""
    pin=scope.get('hk_sdk_artifact')
    if pin is None:return None
    require(scope['role']=='hk-child','HK_SDK_ONLY_CHILD_ROLE')
    require(isinstance(pin,dict) and set(pin)=={'manifest','review_receipt'},'HK_SDK_PIN_SHAPE')
    value=read_json(pin['manifest']['path'],pin['manifest']['sha256'])
    require(value.get('schema')=='v4.us_hk.hk_sdk_artifact.v1' and
            value.get('artifact_class')=='DEPENDENCY_ARTIFACT' and value.get('not_in_git_source_commit') is True,
            'HK_SDK_MANIFEST_CLASS')
    entries=value['entries'];require(isinstance(entries,list) and entries,'HK_SDK_ENTRIES_REQUIRED')
    require(len(entries)==value['entry_count']<=HK_SDK_MAX_ENTRIES and
            sum(r['bytes'] for r in entries)==value['total_bytes']<=HK_SDK_MAX_BYTES,'HK_SDK_FINITE_SIZE')
    require(sdk_map_sha(entries)==value['artifact_map_sha256'],'HK_SDK_MAP_DRIFT')
    if scope['mode']=='RELEASE':
        require(value['artifact_map_sha256']==HK_SDK_RELEASE_MAP and value['entry_count']==HK_SDK_RELEASE_COUNT and
                value['total_bytes']==HK_SDK_RELEASE_BYTES,'HK_SDK_RELEASE_EXACT_ARTIFACT')
    review=read_json(pin['review_receipt']['path'],pin['review_receipt']['sha256'])
    expected_files={r['target']:r['sha256'] for r in entries}
    require(review.get('schema')=='v4.us_hk.hk_sdk_artifact_review.v1' and review.get('verdict')=='PASS' and
            review.get('manifest_sha256')==pin['manifest']['sha256'] and
            review.get('artifact_map_sha256')==value['artifact_map_sha256'] and
            review.get('entry_count')==len(entries) and review.get('total_bytes')==value['total_bytes'] and
            review.get('files')==expected_files,'HK_SDK_INDEPENDENT_REVIEW_REQUIRED')
    distributions=value['distributions']
    require(set(distributions)==set(HK_SDK_DISTRIBUTIONS),'HK_SDK_EXACT_FOUR_DISTRIBUTIONS')
    records={};covered={name:set() for name in distributions};wheels={}
    for name,dist in distributions.items():
        version,tag,package=HK_SDK_DISTRIBUTIONS[name]
        require(dist['name']==name and dist['version']==version,'HK_SDK_VERSION')
        prefix=f'{name}-{version}.dist-info/'
        if dist['kind']=='INSTALLED_RECORD':
            require(name!='simplejson','HK_SDK_SIMPLEJSON_CP313_WHEEL_REQUIRED')
            site=exact(dist['site_root'])
            raw={field:child(site,prefix+filename).read_bytes() for field,filename in
                 [('metadata','METADATA'),('wheel','WHEEL'),('record','RECORD')]}
        else:
            require(dist['kind']=='OFFICIAL_WHEEL' and name=='simplejson','HK_SDK_SOURCE_KIND')
            archive=exact(dist['archive']['path'])
            require(archive.is_relative_to(exact(scope['source_root'])) and sha(archive)==dist['archive']['sha256'],
                    'HK_SDK_WHEEL_DRIFT_OR_BOUNDARY')
            with zipfile.ZipFile(archive) as z:
                require(len(z.namelist())==len(set(z.namelist()))<=HK_SDK_MAX_ENTRIES,'HK_SDK_WHEEL_DUPLICATE_OR_SIZE')
                raw={field:z.read(prefix+filename) for field,filename in [('metadata','METADATA'),('wheel','WHEEL'),('record','RECORD')]}
                wheels[name]={n for n in z.namelist() if not z.getinfo(n).is_dir()}
        for field,data in raw.items():require(digest(data)==dist[field+'_sha256'],'HK_SDK_METADATA_DRIFT')
        metadata=Parser().parsestr(raw['metadata'].decode());wheel=Parser().parsestr(raw['wheel'].decode())
        require(metadata['Name'].lower()==name.lower() and metadata['Version']==version,'HK_SDK_METADATA_IDENTITY')
        require(metadata['Requires-Python']==HK_SDK_REQUIRES_PYTHON[name],'HK_SDK_REQUIRES_PYTHON')
        require(wheel.get_all('Tag')==[tag] and wheel['Root-Is-Purelib']==('true' if name=='futu_api' else 'false'),
                'HK_SDK_WHEEL_ABI_TAG')
        requires=metadata.get_all('Requires-Dist',[])
        require(sorted(requires)==sorted(HK_SDK_REQUIREMENTS[name]),'HK_SDK_NEW_DEPENDENCY')
        records[name]=sdk_record(raw['record'])
        # RECORD's self entry is intentionally unhashed in wheel format.
        records[name][prefix+'RECORD']=(dist['record_sha256'],len(raw['record']))
    targets=set()
    for row in entries:
        relative=row['target'];parts=PurePosixPath(relative).parts
        require(relative not in targets,'HK_SDK_DUPLICATE_TARGET');targets.add(relative)
        require(parts and not set(parts)&{'__pycache__','.git','.superpowers','node_modules'} and
                not any(p.startswith('.env') or p in ('sitecustomize.py','usercustomize.py') or p.endswith('.pth') for p in parts),
                'HK_SDK_FORBIDDEN_TARGET')
        child(Path(scope['parent_root'])/'app',relative,exists=False)
        require(not (Path(scope['parent_root'])/'app'/parts[0]).exists(),'HK_SDK_PARENT_ROOT_COLLISION')
        require(row.get('artifact_class')=='DEPENDENCY_ARTIFACT' and row.get('not_in_git_source_commit') is True and
                row.get('before_sha256') is None and not (Path(scope['parent_root'])/'app'/relative).exists(),
                'HK_SDK_PARENT_COLLISION_OR_CLASS')
        require(isinstance(row['bytes'],int) and 0<=row['bytes']<=HK_SDK_MAX_FILE_BYTES and
                (row['mode'] in ('0644','0755') or
                 (row['mode']=='0664' and relative=='simplejson-4.1.1.dist-info/RECORD')),
                'HK_SDK_FILE_SIZE_MODE')
        source=row['source'];name=source['distribution'];require(name in distributions,'HK_SDK_UNKNOWN_DISTRIBUTION')
        version,tag,package=HK_SDK_DISTRIBUTIONS[name]
        require(source['version']==version and source['record_sha256']==distributions[name]['record_sha256'] and
                (parts[0]==package or parts[0]==f'{name}-{version}.dist-info'),'HK_SDK_TARGET_ROOT_OR_RECORD')
        require(records[name].get(relative)==(row['sha256'],row['bytes']),'HK_SDK_RECORD_ENTRY_MISMATCH')
        covered[name].add(relative)
        hk_sdk_bytes(row,distributions[name])
    for name,record in records.items():
        excluded={r for r in record if r.endswith(('/INSTALLER','/REQUESTED','/direct_url.json')) or '__pycache__' in PurePosixPath(r).parts}
        require(covered[name]==set(record)-excluded,'HK_SDK_INCOMPLETE_DISTRIBUTION')
        if name in wheels:require(wheels[name]==covered[name],'HK_SDK_UNKNOWN_WHEEL_MEMBER')
    probe=scope['runtime_probe']
    require(probe['python']['version']=='3.13.12' and probe['python']['sha256']==HK_SDK_PYTHON_SHA and
            probe.get('wrapper',{}).get('sha256')==HK_SDK_WRAPPER_SHA,'HK_SDK_RETAINED_HK_RUNTIME_REQUIRED')
    require(not probe.get('updater_relative') and hk_sdk_runtime_binding(scope)==value.get('runtime_binding'),
            'HK_SDK_RETAINED_RUNTIME_BINDING_DRIFT')
    preserved=value['preserved_modules'];require(set(preserved)=={'pandas','numpy'},'HK_SDK_PRESERVED_MODULES')
    for name,item in preserved.items():
        require(any(item['path']==str(Path(site)/name/'__init__.py') for site in probe['site_packages']) and
                sha(exact(item['path']))==item['sha256'],'HK_SDK_PANDAS_NUMPY_OWNER')
    require(probe.get('hk_sdk_canary') is True,'HK_SDK_CANARY_REQUIRED')
    hk_sdk_expected(scope,value)
    return value


def verify_hk_sdk_inventory(artifact,entries):
    if artifact is None:return
    current={r['path']:r for r in entries}
    for row in artifact['entries']:
        actual=current.get(row['target'],{})
        require(actual.get('kind')=='file' and actual.get('sha256')==row['sha256'] and
                actual.get('mode')==row['mode'] and actual.get('size')==row['bytes'],
                'HK_SDK_CANDIDATE_CONTENT_DRIFT')


def hk_sdk_expected(scope,artifact):
    app=Path(scope['candidate_root'])/'app';rows={r['target']:r for r in artifact['entries']}
    modules={'futu':'futu/__init__.py','simplejson':'simplejson/__init__.py',
             'simplejson._speedups':'simplejson/_speedups.cpython-313-darwin.so',
             'google.protobuf':'google/protobuf/__init__.py','google._upb._message':'google/_upb/_message.abi3.so',
             'Crypto':'Crypto/__init__.py'}
    require(set(modules.values())<=set(rows),'HK_SDK_NATIVE_CANARY_CLOSURE')
    expected={name:dict(path=str(app/rel),sha256=rows[rel]['sha256']) for name,rel in modules.items()}
    expected.update(artifact['preserved_modules'])
    return expected


def precheck(scope, tool, *, build_pending=False):
    parent = Path(scope["parent_root"])
    manifest = read_json(parent / "release-manifest.json", scope["parent_manifest_sha256"])
    before,caches=(tool._inventory_tree_with_generated_cache(parent/'app') if scope['role'] in ('shared','scheduler') else
                   (tool.inventory_tree(parent/'app'),[]))
    before,reconciliation=validated_parent_inventory(scope,tool,manifest,before,caches)
    for pin in scope.get("dependencies", []):
        require(sha(exact(pin["path"])) == pin["sha256"], "DEPENDENCY_DRIFT")
    if scope.get("plist"):
        require(sha(exact(scope["plist"]["path"])) == scope["plist"]["sha256"], "PLIST_DRIFT")
    approved = {}
    reviews = scope.get("review_receipts", [])
    require(reviews, "NO_INDEPENDENT_REVIEW")
    for pin in reviews:
        review = read_json(pin["path"], pin["sha256"])
        require(review.get("verdict") == "PASS" and review.get("source_commit") == scope["source_commit"], "SOURCE_REVIEW_NOT_PASS")
        for key, value in review["files"].items():
            require(key not in approved or approved[key] == value, "REVIEW_CONFLICT")
            approved[key] = value
    artifact=hk_sdk_artifact(scope)
    targets = set()
    if scope['role']=='hk-child':
        require({r['target'] for r in scope['overlays']}==CAPTURE_PATHS,'HK_CHILD_EXACT_CAPTURE_OVERLAY_REQUIRED')
        require(sha(child(parent/'app','ops/macos_research_panel_daily.py'))==HK_CHILD_MODULE,
                'HK_CHILD_ORIGINAL_MODULE_DRIFT')
    for row in scope["overlays"]:
        rel = row["target"]
        if scope['role'] in LABELS:
            require(rel not in CAPTURE_PATHS,'LEGACY_CAPTURE_CANNOT_OVERLAY_MODERN_ROLE')
        if scope.get('clone_subtree'):
            require(rel.startswith(scope['clone_subtree']+'/'),'SHARED_OVERLAY_OUTSIDE_PACKAGE')
        require(rel not in targets, "DUPLICATE_OVERLAY")
        targets.add(rel)
        require(approved.get(rel) == row["sha256"], "UNREVIEWED_OVERLAY")
        require(not set(PurePosixPath(rel).parts) & {"node_modules", ".git", ".superpowers", "__pycache__"}, "FORBIDDEN_RUNTIME_OVERLAY")
        require(not any(x.startswith(".env") for x in PurePosixPath(rel).parts), "SECRET_OVERLAY_FORBIDDEN")
        if build_pending and row.get('origin')=='build':
            build=scope.get('frontend_build')
            require(build is not None and build['outputs'].get(row['source'])==row['sha256'],
                    'UNBOUND_PENDING_BUILD_OVERLAY')
            child(build['output_root'],row['source'],exists=False)
        else:
            require(sha(source_file(scope, row)) == row["sha256"], "SOURCE_DRIFT")
        target = child(parent / "app", rel, exists=False)
        require((sha(target) if target.exists() else None) == row["before_sha256"], "OVERLAY_PREIMAGE_DRIFT")
        require(row["before_sha256"] != row["sha256"], "NO_BYTE_CHANGE_OVERLAY")
        require(isinstance(row["mode"], int) and row["mode"] in (0o644, 0o755), "OVERLAY_MODE_INVALID")
    preserved = {pin["path"] for pin in scope.get("preserved_app_files", [])}
    require(not targets & preserved, "PRESERVED_DEPENDENCY_OVERLAY")
    if artifact:
        require(not targets & {r['target'] for r in artifact['entries']},'HK_SDK_SOURCE_ARTIFACT_OVERLAP')
    for pin in scope.get("preserved_app_files", []):
        require(sha(child(parent / "app", pin["path"])) == pin["sha256"], "PRESERVED_DEPENDENCY_DRIFT")
    subtree=scope.get('clone_subtree')
    if subtree:
        require(scope['role']=='shared' and subtree=='upstreams/v3_shared_data', 'CLONE_SUBTREE_FORBIDDEN')
        projection=scope.get('shared_source_paths')
        require(isinstance(projection,list) and len(projection)==len(set(projection)) and projection,'SHARED_SOURCE_PROJECTION_REQUIRED')
        if scope['mode']=='RELEASE':require(set(projection)==SHARED_SOURCE_PATHS,'SHARED_EXACT_SOURCE_CLOSURE_REQUIRED')
        require(all(relative.startswith((SHARED_PREFIX+'scripts/',SHARED_PREFIX+'shared_data/')) and
                    relative.endswith('.py') for relative in projection),'SHARED_PROJECTION_NON_SOURCE_FORBIDDEN')
        require(targets<=set(projection),'SHARED_OVERLAY_OUTSIDE_PROJECTION')
        require(set(projection)<={entry['path'] for entry in before}|targets,'SHARED_PROJECTION_DEPENDENCY_MISSING')
        reconciliation['source_projection_paths']=sorted(projection)
        reconciliation['excluded_native_entries']=[entry for entry in before if entry['path'] not in projection]
        before=[entry for entry in before if entry['path'] in projection]
        require(all(entry['kind']=='file' for entry in before),'SHARED_PROJECTION_REGULAR_SOURCE_REQUIRED')
        require(before, 'EMPTY_SHARED_PACKAGE')
    if scope['role']=='scheduler' and scope.get('hk_child_prepared') is not None:
        hk_child_binding(scope)
    return dict(manifest,task6_inventory_reconciliation=reconciliation), before


def hk_child_binding(scope,original_env=None):
    """Consume a prepared child as a dependency of the same scheduler owner."""
    pin=scope.get('hk_child_prepared')
    if pin is None:return {}
    prepared=read_json(pin['path'],pin['sha256'])
    child_scope=read_json(prepared['scope_path'],prepared['scope_sha256'])
    require(prepared.get('state')=='PREPARED' and prepared.get('mode')=='RELEASE' and
            child_scope.get('role')=='hk-child' and child_scope.get('mode')=='RELEASE' and
            prepared['helper_sha256']==sha(Path(__file__)),'HK_CHILD_PREPARED_IDENTITY_INVALID')
    authorize(child_scope,'prepare');release_paths(child_scope)
    require(prepared['candidate_root']==child_scope['candidate_root'] and
            prepared['parent_root']==child_scope['parent_root'],'HK_CHILD_PREPARED_ROOT_MISMATCH')
    tool=inventory_tool(child_scope['inventory_tool']);_,before=precheck(child_scope,tool)
    candidate=exact(prepared['candidate_root'])
    manifest=read_json(candidate/'release-manifest.json',prepared['candidate_manifest_sha256'])
    entries=tool.inventory_tree(candidate/'app')
    require(entries==manifest['application_inventory']['entries'] and
            tool.inventory_digest(entries)==prepared['candidate_inventory_sha256'] and
            manifest['task_overlay']['scope_sha256']==prepared['scope_sha256'],'HK_CHILD_CANDIDATE_DRIFT')
    artifact=hk_sdk_artifact(child_scope)
    verify_hk_sdk_inventory(artifact,entries)
    if artifact:
        require(manifest['task_overlay'].get('hk_sdk_artifact')==child_scope['hk_sdk_artifact'] and
                manifest['task_overlay'].get('hk_sdk_artifact_map_sha256')==artifact['artifact_map_sha256'],
                'HK_SDK_CANDIDATE_PROVENANCE_DRIFT')
    original={r['path']:r for r in before};current={r['path']:r for r in entries}
    require({k for k in original.keys()|current.keys() if original.get(k)!=current.get(k)}==(CAPTURE_PATHS|{r['target'] for r in (artifact or {}).get('entries',[])}) and
            not original.keys()-current.keys(),'HK_CHILD_UNEXPECTED_DELTA')
    for row in child_scope['overlays']:
        require(sha(child(candidate/'app',row['target']))==row['sha256'],'HK_CHILD_REVIEWED_BYTES_DRIFT')
    probe=child_scope['runtime_probe'];wrapper=probe['wrapper']
    python_pin(probe['python'])
    require(sha(exact(wrapper['path']))==wrapper['sha256'],'HK_CHILD_RETAINED_WRAPPER_DRIFT')
    prefix='V35_RESEARCH_PANEL_HK_CHILD_'
    if original_env is not None:
        expected_old={prefix+'APP_ROOT':str(HK_CHILD_PARENT/'app'),prefix+'RELEASE_ID':HK_CHILD_PARENT.name,
            prefix+'RELEASE_MANIFEST_PATH':str(HK_CHILD_PARENT/'release-manifest.json'),
            prefix+'RELEASE_MANIFEST_SHA256':HK_CHILD_MANIFEST,prefix+'MODULE_SHA256':HK_CHILD_MODULE}
        require(all(original_env.get(k)==v for k,v in expected_old.items()),'HK_CHILD_ORIGINAL_BINDING_DRIFT')
        require(original_env.get('V35_RESEARCH_PANEL_HK_PYTHON_EXECUTABLE')==wrapper['path'] and
                original_env.get('V35_RUNTIME_ROOT')==wrapper['runtime_root'] and
                original_env.get('V35_SHARED_PACKAGE_ROOT')==wrapper['shared_package_root'],
                'HK_CHILD_PROBE_WRAPPER_ENV_MISMATCH')
    return {prefix+'APP_ROOT':str(candidate/'app'),prefix+'RELEASE_ID':candidate.name,
        prefix+'RELEASE_MANIFEST_PATH':str(candidate/'release-manifest.json'),
        prefix+'RELEASE_MANIFEST_SHA256':prepared['candidate_manifest_sha256'],
        prefix+'MODULE_SHA256':sha(child(candidate/'app','ops/macos_research_panel_daily.py'))}


def proposed_plist(raw, scope, manifest_sha):
    value = plistlib.loads(raw)
    candidate = Path(scope["candidate_root"])
    fields = dict(root=str(candidate), app=str(candidate / "app"), release_id=candidate.name,
                  manifest=str(candidate / "release-manifest.json"), manifest_sha256=manifest_sha)
    seen = set()
    for update in scope["plist"]["updates"]:
        keys = update["keys"]
        require(keys and tuple(keys) not in seen, "PLIST_UPDATE_DUPLICATE")
        seen.add(tuple(keys))
        node = value
        for key in keys[:-1]:
            node = node[key]
        require(node[keys[-1]] == update["before"], "PLIST_FIELD_DRIFT")
        node[keys[-1]] = update["after"].format(**fields)
    require(value.get("WorkingDirectory") == str(candidate / "app"), "PLIST_CWD_NOT_REBOUND")
    if scope['mode']=='RELEASE':
        env=dict(value.get('EnvironmentVariables', {}))
        args=value.get('ProgramArguments', [])
        inline={arg.split('=',1)[0]:arg.split('=',1)[1] for arg in args
                if isinstance(arg,str) and '=' in arg and not arg.startswith('/')}
        identity={'V35_APP_ROOT':fields['app'],'V35_RELEASE_ID':fields['release_id'],
                  'V35_RELEASE_MANIFEST_PATH':fields['manifest'], 'V35_RELEASE_MANIFEST_SHA256':fields['manifest_sha256']}
        for key,expected in identity.items():
            require(env.get(key)==expected, 'PLIST_ENV_IDENTITY_NOT_REBOUND:'+key)
            if key in inline: require(inline[key]==expected, 'PLIST_INLINE_IDENTITY_NOT_REBOUND:'+key)
        merged=dict(env,**inline)
        require(merged.get('RESEARCH_ONLY') in ('1','true','True'),'PLIST_RESEARCH_ONLY_REQUIRED')
        for key in ('production_allowed','buy_gate_updated','orders_sent'):
            require(any(k in merged for k in (key,key.upper())),'PLIST_SAFETY_FLAG_MISSING')
            for bindings in (env,inline):
                for name in (key,key.upper()):
                    if name in bindings:require(bindings[name] in ('0','false','False'),'PLIST_UNSAFE_FLAG')
        for bindings in (env,inline):
            if 'PYTHONPATH' in bindings:
                require(str(Path(scope['parent_root'])/'app') not in bindings['PYTHONPATH'] and
                        fields['app'] in bindings['PYTHONPATH'], 'PLIST_STALE_PYTHONPATH')
        original=plistlib.loads(raw)
        for key in ('KeepAlive','RunAtLoad','Label'):
            require(value.get(key)==original.get(key), 'PLIST_LIFECYCLE_SETTING_CHANGED')
        if scope['role']=='scheduler':
            require(len(args)>=2 and args[0]=='/bin/bash' and args[1]==str(candidate/'app/ops/launch_v35_macos_scheduler.sh'),
                    'SCHEDULER_LAUNCHER_NOT_REBOUND')
            require(args[2:]==original.get('ProgramArguments',[])[2:],'SCHEDULER_PROVIDER_ARGS_CHANGED')
            updater=scope.get('shared_updater')
            require(isinstance(updater,dict) and sha(exact(updater['path']))==updater['sha256'], 'REVIEWED_UPDATER_REQUIRED')
            require(env.get('V35_RESEARCH_PANEL_HK_UPDATER_SCRIPT')==updater['path'], 'UPDATER_SCRIPT_NOT_BOUND')
            child_bindings=hk_child_binding(scope,original.get('EnvironmentVariables',{}))
            for key,expected in child_bindings.items():
                require(key in original.get('EnvironmentVariables',{}) and env.get(key)==expected,
                        'HK_CHILD_FIVE_BINDINGS_REQUIRED')
                if key in inline:require(inline[key]==expected,'HK_CHILD_INLINE_BINDING_DRIFT')
            for key in original.get('EnvironmentVariables',{}):
                if key.startswith('V35_RESEARCH_PANEL_HK_CHILD_') or key in (
                        'V35_RESEARCH_PANEL_HK_PYTHON_EXECUTABLE','V35_HK_0_2_REAL_PYTHON',
                        'V35_HK_0_2_PYTHON','V35_SHARED_PACKAGE_ROOT','V35_RUNTIME_ROOT'):
                    require(env.get(key)==child_bindings.get(key,original['EnvironmentVariables'][key]),
                            'HK_CHILD_OR_RUNTIME_DEPENDENCY_CHANGED')
        elif scope['role']=='api':
            require('apps.api.v35_api.run' in args and scope['runtime_probe']['python']['path'] in args,
                    'API_ENTRYPOINT_OR_INTERPRETER_CHANGED')
    # Scope permits exact fields only. No recursive string/global rebinding.
    return plistlib.dumps(value, sort_keys=False)


def checked_command(argv, *, cwd, env, timeout, runner):
    require(isinstance(argv,list) and argv and all(isinstance(x,str) for x in argv), 'COMMAND_NOT_ARGV')
    result=runner(argv,cwd=str(cwd),env=env,capture_output=True,text=True,timeout=timeout)
    require(result.returncode==0,'SUBPROCESS_FAILED:'+str(result.returncode))
    return result


def python_pin(pin):
    path=Path(pin['path'])
    require(path.is_absolute() and path.resolve(strict=True)==Path(pin['resolved_path']) and
            sha(path)==pin['sha256'], 'ROLE_INTERPRETER_DRIFT')
    return str(path)


def runtime_probe(scope, runner):
    probe=scope['runtime_probe']
    python=python_pin(probe['python'])
    app=Path(scope['candidate_root'])/'app'
    sites=[str(exact(p)) for p in probe['site_packages']]
    artifact=hk_sdk_artifact(scope)
    sdk_modules=hk_sdk_expected(scope,artifact) if artifact else {}
    for pin in sdk_modules.values():require(sha(exact(pin['path']))==pin['sha256'],'HK_SDK_PROBE_INPUT_DRIFT')
    modules=probe['modules']
    require(modules and all(isinstance(k,str) and isinstance(v,str) for k,v in modules.items()), 'IMPORT_PROBE_MODULES_REQUIRED')
    updater=probe.get('updater_relative')
    search=([*sites,*[str(exact(p)) for p in probe.get('retained_search_roots',[])]] if updater else
            [*[str(exact(p)) for p in probe.get('search_roots',[str(app),str(app/'upstreams')])],*sites])
    script='''import sys,os,json,platform,socket,builtins,importlib,runpy,subprocess,hashlib
def denied(*a,**k):raise RuntimeError('IMPORT_PROBE_WRITE_OR_NETWORK_FORBIDDEN')
old_open=builtins.open
def ro_open(file,mode='r',*a,**k):
 if any(x in mode for x in 'wax+'):denied()
 return old_open(file,mode,*a,**k)
old_os_open=os.open
def ro_os_open(path,flags,*a,**k):
 if flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND):denied()
 return old_os_open(path,flags,*a,**k)
builtins.open=ro_open;os.open=ro_os_open
for name in ('mkdir','makedirs','unlink','remove','rename','replace','rmdir'):setattr(os,name,denied)
subprocess.Popen=denied
for name in ('system','popen','fork','forkpty','posix_spawn','posix_spawnp','execl','execle','execlp','execlpe','execv','execve','execvp','execvpe'):
 if hasattr(os,name):setattr(os,name,denied)
socket.create_connection=denied
for name in ('connect','connect_ex','bind','listen','send','sendall','sendto','sendmsg'):
 if hasattr(socket.socket,name):setattr(socket.socket,name,denied)
sys.path[:0]=json.loads(sys.argv[1]);expected=json.loads(sys.argv[-1]);found={};hashes={}
if len(sys.argv)>3:runpy.run_path(sys.argv[2],run_name='_US_HK_OWNER_IMPORT_PROBE')
for name,path in expected.items():
 module=importlib.import_module(name);actual=os.path.realpath(module.__file__)
 if actual!=path:raise RuntimeError('IMPORT_ORIGIN_MISMATCH:'+name)
 found[name]=actual
 hashes[name]=hashlib.sha256(old_open(actual,'rb').read()).hexdigest()
PROBE_RESULT_MARKER
'''
    sdk_guard='''
import io
io.open=ro_open
for name in ('getaddrinfo','gethostbyname','gethostbyname_ex','gethostbyaddr','getnameinfo'):setattr(socket,name,denied)
def sdk_profile(frame,event,value):
 if event=='call' and ((frame.f_globals.get('__name__','').startswith('futu.') and 'Context' in frame.f_code.co_qualname and frame.f_code.co_name=='__init__') or frame.f_code.co_qualname=='Thread.start'):denied()
 if event=='c_call' and getattr(value,'__module__','')=='_thread' and getattr(value,'__name__','') in ('start_new_thread','start_joinable_thread'):denied()
sys.setprofile(sdk_profile)
def sdk_audit(event,args):
 if event=='open':
  mode,flags=args[1],args[2]
  if (isinstance(mode,str) and any(c in mode for c in 'wax+')) or (isinstance(flags,int) and flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND)):denied()
 if event.startswith(('subprocess.','os.exec','os.spawn','os.fork')) or event in ('os.system','os.remove','os.rename','os.mkdir','os.rmdir','os.link','os.symlink','os.chmod','os.chown','os.truncate','os.utime','socket.connect','socket.bind','socket.sendto','socket.getaddrinfo','socket.gethostbyname','socket.gethostbyaddr','socket.getnameinfo'):denied()
sys.addaudithook(sdk_audit)
'''
    sdk_canary='''
import importlib.metadata
from google.protobuf.internal import api_implementation
from Crypto.Cipher import AES
import simplejson as sdk_json
if sdk_json._speedups is not sys.modules['simplejson._speedups']:raise RuntimeError('HK_SDK_SIMPLEJSON_FALLBACK')
if api_implementation.Type()!='upb':raise RuntimeError('HK_SDK_PROTOBUF_FALLBACK')
answer=AES.new(bytes(16),AES.MODE_ECB).encrypt(bytes(16)).hex()
if answer!='66e94bd4ef8a2c3b884cfa59ca342b2e':raise RuntimeError('HK_SDK_AES_NATIVE_FAILURE')
versions={name:importlib.metadata.version(name) for name in ('futu_api','simplejson','protobuf','pycryptodome')}
sdk_check=dict(versions=versions,simplejson_native=True,protobuf_backend='upb',aes_known_answer=answer,provider_initialized=False)
'''
    if artifact:
        script=script.replace('sys.path[:0]=',sdk_guard+'\nsys.path[:0]=',1)
        script=script.replace('PROBE_RESULT_MARKER',sdk_canary+"\nprint(json.dumps({'version':platform.python_version(),'origins':found,'module_sha256':hashes,'sdk_canary':sdk_check}))")
    else:script=script.replace('PROBE_RESULT_MARKER',"print(json.dumps({'version':platform.python_version(),'origins':found,'module_sha256':hashes}))")
    expected={name:str(child(app,rel)) for name,rel in modules.items()}
    expected.update({name:pin['path'] for name,pin in sdk_modules.items()})
    env={'PATH':'/usr/bin:/bin','PYTHONDONTWRITEBYTECODE':'1','PYTHONNOUSERSITE':'1'}
    for key,value in probe.get('environment',{}).items():
        require(key.startswith(('V35_','V4_')) and isinstance(value,str),'PROBE_ENV_OUTSIDE_ROLE_BINDINGS')
        env[key]=value
    if updater or scope['role']=='hk-child':
        wrapper=probe['wrapper'];path=exact(wrapper['path'])
        require(sha(path)==wrapper['sha256'],'HK_WRAPPER_DRIFT')
        env.update(V35_RUNTIME_ROOT=wrapper['runtime_root'],V35_SHARED_PACKAGE_ROOT=wrapper['shared_package_root'],V35_HK_0_2_REAL_PYTHON=python)
        if scope['role']=='hk-child':env['PYTHONPATH']=str(app)
        argv=[str(path),'-B','-c',script,json.dumps(search)]
        if updater:argv.append(str(child(app,updater)))
        argv.append(json.dumps(expected))
    else:argv=[python,'-I','-S','-B','-c',script,json.dumps(search),json.dumps(expected)]
    if artifact:
        for name in ('HOME','CODEX_HOME'):
            if name in os.environ:env[name]=os.environ[name]
    result=checked_command(argv,cwd=app,env=env,timeout=60,runner=runner)
    observed=json.loads(result.stdout)
    require(observed.get('version')==probe['python']['version'] and observed.get('origins')==expected,
            'ROLE_RUNTIME_PROBE_MISMATCH')
    hashes={name:sha(path) for name,path in expected.items()}
    require(observed.get('module_sha256')==hashes,'ROLE_MODULE_SHA_PROBE_MISMATCH')
    for name,pin in sdk_modules.items():require(hashes[name]==pin['sha256'],'HK_SDK_PROBE_INPUT_DRIFT')
    if artifact:
        require(observed.get('sdk_canary')==dict(versions={name:value[0] for name,value in HK_SDK_DISTRIBUTIONS.items()},
            simplejson_native=True,protobuf_backend='upb',aes_known_answer='66e94bd4ef8a2c3b884cfa59ca342b2e',provider_initialized=False),
            'HK_SDK_NATIVE_CANARY_FAILURE')
    receipt=dict(python=probe['python'],site_packages=sites,origins=observed['origins'],wrapper=probe.get('wrapper'),
                module_sha256=hashes,search_roots=search,environment=probe.get('environment',{}),
                updater_run_name='_US_HK_OWNER_IMPORT_PROBE' if updater else None,
                command_kind='READ_ONLY_IMPORT_NO_NETWORK',stdout_sha256=digest(result.stdout.encode()))
    if artifact:receipt.update(sdk_canary=observed['sdk_canary'],hk_sdk_artifact_map_sha256=artifact['artifact_map_sha256'])
    return receipt


def frontend_build(scope, runner):
    build=scope.get('frontend_build')
    if build is None:return None
    require(scope['role']=='api','FRONTEND_BUILD_ROLE')
    evidence=Path(scope['evidence_root'])
    stage=exact(build['stage_root'],exists=False);output=exact(build['output_root'],exists=False)
    require(stage.is_relative_to(evidence) and output.is_relative_to(evidence) and
            not stage.exists() and not output.exists() and not output.is_relative_to(stage), 'BUILD_COLLISION_OR_ESCAPE')
    node=exact(build['node']['path']);vite=exact(build['vite']['path'])
    require(sha(node)==build['node']['sha256'] and sha(vite)==build['vite']['sha256'],'BUILD_EXECUTABLE_DRIFT')
    dependencies=exact(build['node_modules'])
    parent_web=Path(scope['parent_root'])/'app/apps/web'
    require(sha(child(parent_web,'package-lock.json'))==build['package_lock_sha256'],'BUILD_PARENT_LOCK_DRIFT')
    approved={}
    for pin in scope['review_receipts']:
        review=read_json(pin['path'],pin['sha256'])
        require(review.get('verdict')=='PASS' and review.get('source_commit')==scope['source_commit'],'BUILD_SOURCE_REVIEW_NOT_PASS')
        approved.update(review['files'])
    manifest=read_json(Path(scope['parent_root'])/'release-manifest.json',scope['parent_manifest_sha256'])
    expected_stage={}
    for entry in manifest['application_inventory']['entries']:
        if not entry['path'].startswith('apps/web/'):continue
        relative=entry['path'][len('apps/web/'):]
        if set(PurePosixPath(relative).parts)&{'dist','node_modules'}:continue
        expected_stage[relative]=dict(entry,path=relative)
    shutil.copytree(parent_web,stage,symlinks=True,ignore=shutil.ignore_patterns('dist','node_modules'))
    for item in build['source_files']:
        source=child(scope['source_root'],item['source']);target=child(stage,item['target'],exists=False)
        require(sha(source)==item['sha256'] and approved.get('apps/web/'+item['target'])==item['sha256'],'BUILD_SOURCE_DRIFT_OR_UNREVIEWED')
        target.parent.mkdir(parents=True,exist_ok=True)
        if target.exists():target.unlink()
        shutil.copyfile(source,target)
        target.chmod(0o644)
        expected_stage[item['target']]=dict(path=item['target'],kind='file',sha256=item['sha256'],
            size=source.stat().st_size,mode='0644')
    observed_stage=inventory_tool(scope['inventory_tool']).inventory_tree(stage)
    normalize=lambda row:{k:v for k,v in row.items() if k!='target_exists'}
    require({r['path']:normalize(r) for r in observed_stage}==
            {k:normalize(r) for k,r in expected_stage.items()},'BUILD_STAGE_INVENTORY_DRIFT')
    require(sha(child(stage,'package-lock.json'))==build['package_lock_sha256'],'BUILD_STAGED_LOCK_DRIFT')
    old_package=json.loads(child(parent_web,'package.json').read_bytes())
    package=json.loads(child(stage,'package.json').read_bytes())
    for key in ('dependencies','devDependencies','peerDependencies','optionalDependencies','engines'):
        require(package.get(key)==old_package.get(key),'FRONTEND_DEPENDENCY_CHANGE_REQUIRES_LOCK_RECONCILIATION:'+key)
    for pin in build['dependency_identity_files']:
        p=exact(pin['path']);require(p.is_relative_to(dependencies) and sha(p)==pin['sha256'],'FRONTEND_EXTERNAL_DEPENDENCY_DRIFT')
    node_version=checked_command([str(node),'--version'],cwd=stage,env={'PATH':'/usr/bin:/bin'},timeout=10,runner=runner).stdout.strip()
    vite_version=checked_command([str(node),str(vite),'--version'],cwd=stage,env={'PATH':'/usr/bin:/bin'},timeout=10,runner=runner).stdout.strip()
    require(node_version==build['node']['version'] and vite_version==build['vite']['version'],'FRONTEND_TOOL_VERSION_DRIFT')
    (stage/'node_modules').symlink_to(dependencies,target_is_directory=True)
    result=checked_command([str(node),str(vite),'build','--outDir',str(output)],cwd=stage,
        env={'PATH':'/usr/bin:/bin','HOME':str(evidence),'CI':'1'},timeout=180,runner=runner)
    for relative,expected in build['outputs'].items():
        require(relative=='manager-selection/index.html' or relative.startswith('assets/'),'BUILD_OUTPUT_OUTSIDE_MANAGER_CLOSURE')
        require(sha(child(output,relative))==expected,'BUILD_OUTPUT_DRIFT')
    require('manager-selection/index.html' in build['outputs'],'MANAGER_HTML_REQUIRED')
    pending=['manager-selection/index.html'];seen=set()
    overlays={row['target']:row['sha256'] for row in scope['overlays'] if row.get('origin')=='build'}
    while pending:
        relative=pending.pop()
        if relative in seen:continue
        seen.add(relative);p=child(output,relative)
        target='apps/web/dist/'+relative
        if target not in overlays:
            require(sha(child(Path(scope['parent_root'])/'app',target))==sha(p),'UNBOUND_BUILD_CLOSURE_ASSET')
        else:require(overlays[target]==sha(p),'BUILD_CLOSURE_OVERLAY_MISMATCH')
        if p.suffix in ('.html','.js','.css'):
            raw=p.read_text()
            refs=re.findall(r'''(?:/|["'])assets/([^"'\s<>\)]+)''',raw)
            if relative.startswith('assets/'):
                refs+=re.findall(r'''["'](?:\./)?([^/"']+\.(?:js|css))["']''',raw)
            pending.extend('assets/'+value for value in refs)
    write_new(evidence/'frontend-build.log',(result.stdout+'\n'+result.stderr).encode())
    return dict(node=build['node'],vite=build['vite'],node_modules=str(dependencies),
                dependency_identity_files=build['dependency_identity_files'],dependency_sections_unchanged=True,
                package_scripts_changed=package.get('scripts')!=old_package.get('scripts'),
                package_lock_sha256=build['package_lock_sha256'],outputs=build['outputs'])


def prepare(scope_path, scope_sha, receipt_path, *, runner=None):
    runner=runner or subprocess.run
    scope = load_scope(scope_path, scope_sha)
    tool = inventory_tool(scope["inventory_tool"])
    # Validate every retained byte/dependency and overlay preimage before any
    # Node version/config/plugin/build process. Generated bytes are checked after.
    precheck(scope, tool, build_pending=True)
    build_receipt=frontend_build(scope,runner)
    parent_manifest, before = precheck(scope, tool)
    evidence = Path(scope["evidence_root"])
    receipt_path = exact(receipt_path, exists=False)
    require(receipt_path.is_relative_to(evidence) and not receipt_path.exists(), "PREPARED_RECEIPT_COLLISION_OR_ESCAPE")
    candidate = Path(scope["candidate_root"])
    # Exclusive mkdir: failed copies remain available for inspection, never reused.
    candidate.mkdir()
    if scope.get('clone_subtree'):
        # Copy only the explicit validated Python closure. No historical data,
        # tests, fixtures, bytecode or unrelated acquisition script enters it.
        for entry in before:
            source=child(Path(scope['parent_root'])/'app',entry['path']);target=candidate/'app'/entry['path']
            target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
    else:
        shutil.copytree(Path(scope["parent_root"]) / "app", candidate / "app", symlinks=True)
    for row in scope["overlays"]:
        source = source_file(scope,row)
        require(sha(source) == row["sha256"], "SOURCE_CHANGED_DURING_PREPARE")
        child(candidate / "app", row["target"], exists=False)
        # Reuse the pinned existing candidate-only directory-mode guard.
        with tool._candidate_parent_writable(candidate / "app", row["target"]) as target:
            # Never write through a retained hardlink or symlink.
            if target.exists():
                target.unlink()
            shutil.copyfile(source, target)
            target.chmod(row["mode"])
            require(sha(target) == row["sha256"], "COPIED_SOURCE_SHA_MISMATCH")
    artifact=hk_sdk_artifact(scope)
    if artifact:
        for row in artifact['entries']:
            raw=hk_sdk_bytes(row,artifact['distributions'][row['source']['distribution']])
            with tool._candidate_parent_writable(candidate/'app',row['target']) as target:
                require(not target.exists() and not target.is_symlink(),'HK_SDK_CANDIDATE_COLLISION')
                with target.open('xb') as stream:stream.write(raw)
                target.chmod(int(row['mode'],8))
                require(sha(target)==row['sha256'],'HK_SDK_COPIED_SHA_MISMATCH')
    after = tool.inventory_tree(candidate / "app")
    verify_hk_sdk_inventory(artifact,after)
    a, b = ({row["path"]: row for row in entries} for entries in (before, after))
    changed = sorted(key for key in a.keys() | b.keys() if a.get(key) != b.get(key))
    require(set(changed) == ({row["target"] for row in scope["overlays"]}|
            {row['target'] for row in (artifact or {}).get('entries',[])}), "UNEXPECTED_CANDIDATE_DELTA")
    require(not a.keys() - b.keys(), "CANDIDATE_DELETED_PATH")
    probe_receipt=runtime_probe(scope,runner) if scope['mode']=='RELEASE' else None
    manifest = dict(schema_version="v4.release_candidate.v1", activation_status="PREPARED",
        candidate=dict(root=str(candidate), app_root=str(candidate / "app"), release_id=candidate.name),
        application_inventory=dict(entries=after, entry_count=len(after), aggregate_sha256=tool.inventory_digest(after)),
        task_overlay=dict(scope_sha256=scope_sha, source_commit=scope["source_commit"], source_root=scope["source_root"],
            parent_root=scope["parent_root"], parent_manifest_sha256=scope["parent_manifest_sha256"],
            review_receipts=scope["review_receipts"], dependencies=scope.get("dependencies", []),
            source_overlays=scope['overlays'],runtime_probe=probe_receipt,frontend_build=build_receipt,
            parent_inventory_reconciliation=parent_manifest['task6_inventory_reconciliation'],
            hk_child_prepared=scope.get('hk_child_prepared'),
            clone_subtree=scope.get('clone_subtree'),
            preserved_app_files=scope.get("preserved_app_files", []), role=scope["role"],
            delta=[dict(path=k, before=a.get(k), after=b.get(k)) for k in changed],
            non_delta_preserved=True,retained_projection_only=bool(scope.get('clone_subtree')),
            full_branch_equivalence_claimed=False))
    if artifact:manifest['task_overlay'].update(hk_sdk_artifact=scope['hk_sdk_artifact'],hk_sdk_artifact_map_sha256=artifact['artifact_map_sha256'])
    write_new(candidate / "release-manifest.json", json_bytes(manifest))
    original = proposal = None
    if scope.get("plist"):
        raw = Path(scope["plist"]["path"]).read_bytes()
        require(digest(raw) == scope["plist"]["sha256"], "PLIST_CHANGED_DURING_PREPARE")
        original, proposal = evidence / "original.plist", evidence / "candidate.plist"
        write_new(original, raw)
        write_new(proposal, proposed_plist(raw, scope, sha(candidate / "release-manifest.json")))
    precheck(scope, tool)
    result = dict(schema="v4.us_hk.release_prepared.v1", state="PREPARED", mode=scope["mode"],
        scope_path=str(exact(scope_path)), scope_sha256=scope_sha, candidate_root=str(candidate),
        parent_root=scope["parent_root"], candidate_manifest_sha256=sha(candidate / "release-manifest.json"),
        candidate_inventory_sha256=tool.inventory_digest(after), changed_paths=changed,
        original_plist=str(original) if original else None, original_plist_sha256=sha(original) if original else None,
        candidate_plist=str(proposal) if proposal else None, candidate_plist_sha256=sha(proposal) if proposal else None,
        original_plist_mode=stat.S_IMODE(Path(scope["plist"]["path"]).stat().st_mode) if original else None,
        helper_sha256=sha(Path(__file__)), activation_executed=False, data_pointer_changes=[])
    write_new(receipt_path, json_bytes(result))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", required=True)
    parser.add_argument("--scope-sha256", required=True)
    parser.add_argument("--receipt", required=True)
    args = parser.parse_args()
    result = prepare(args.scope, args.scope_sha256, args.receipt)
    print(json.dumps(dict(state=result["state"], changed_paths=result["changed_paths"], receipt=args.receipt)))


if __name__ == "__main__":
    main()
