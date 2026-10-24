"""Frozen candidate read-only probe. Writes only one JSON result to inherited stdout.

Do not run without an independently accepted program/input and controller capsule.
This is a finite pinned-code guard, not an OS sandbox for arbitrary native code.
"""
from __future__ import annotations
import argparse
import ast
import builtins
import contextlib
from copy import deepcopy
import dataclasses
import hashlib
import importlib
import importlib.util
import inspect
import io
import json
import os
from pathlib import Path
import platform
import re
import runpy
import socket
import subprocess
import sys


class ProbeFailure(RuntimeError):
    def __init__(self, kind, code):
        super().__init__(code)
        self.kind, self.code = kind, code


def require(ok, code, kind='MODULE_BINDING_FAILURE'):
    if not ok:
        raise ProbeFailure(kind, code)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def file_sha(path):
    value = hashlib.sha256()
    with open(path, 'rb') as stream:
        for raw in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(raw)
    return value.hexdigest()


def pinned(pin):
    p = Path(pin['path'])
    require(p.is_file() and file_sha(p) == pin['sha256'], 'PIN_DRIFT', pin.get('failure_classification','MODULE_BINDING_FAILURE'))
    return p


def read_json(pin):
    p = pinned(pin)
    require(p.stat().st_size <= 512 * 1024 * 1024, 'JSON_SIZE_LIMIT')
    return json.loads(p.read_bytes())


def exception_record(exc):
    # No exception repr, inputs, tokens, arguments or traceback locals in stdout.
    value = dict(type=type(exc).__name__, classification='MODULE_BINDING_FAILURE' if isinstance(exc, (ImportError, ModuleNotFoundError)) else 'DATA_CANNOT_CONFIRM')
    if isinstance(exc, ProbeFailure):
        value.update(classification=exc.kind, code=exc.code)
    if isinstance(exc, ModuleNotFoundError):
        name = getattr(exc, 'name', '')
        if isinstance(name, str) and re.fullmatch(r'[A-Za-z0-9_.]+', name):
            value['missing_module'] = name
    return value


class ReadOnlyGuard:
    def __init__(self):
        self.denials = []

    def deny(self, operation):
        self.denials.append(operation)
        raise ProbeFailure('PROBE_GUARD_REFUSAL', operation)

    def install(self):
        original_open, original_os_open = builtins.open, os.open
        def read_open(file, mode='r', *args, **kwargs):
            if not isinstance(mode, str) or any(c in mode for c in 'wax+'):
                self.deny('FILESYSTEM_WRITE')
            return original_open(file, mode, *args, **kwargs)
        def os_read_open(path, flags, *args, **kwargs):
            if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
                self.deny('FILESYSTEM_WRITE')
            return original_os_open(path, flags, *args, **kwargs)
        builtins.open = read_open
        io.open = read_open
        os.open = os_read_open
        def deny_call(*args, **kwargs):
            self.deny('WRITE_NETWORK_OR_PROCESS_API')
        for name in ('mkdir','makedirs','unlink','remove','rename','replace','rmdir','chmod','chown','lchown',
                     'link','symlink','truncate','ftruncate','utime','system','popen','fork','forkpty',
                     'posix_spawn','posix_spawnp','execl','execle','execlp','execlpe','execv','execve','execvp','execvpe'):
            if hasattr(os, name):
                setattr(os, name, deny_call)
        subprocess.Popen = deny_call
        socket.create_connection = deny_call
        for name in ('connect','connect_ex','bind','listen','send','sendall','sendto','sendmsg'):
            if hasattr(socket.socket, name):
                setattr(socket.socket, name, deny_call)
        def audit(event, args):
            if event == 'open':
                mode, flags = args[1], args[2]
                if (isinstance(mode, str) and any(c in mode for c in 'wax+')) or (
                    isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)):
                    self.deny('AUDIT_FILESYSTEM_WRITE')
            if event.startswith(('subprocess.', 'os.exec', 'os.spawn', 'os.fork')) or event in (
                'os.system','os.remove','os.rename','os.mkdir','os.rmdir','os.link','os.symlink','os.chmod','os.chown',
                'os.truncate','os.utime','socket.connect','socket.bind','socket.sendto','socket.getaddrinfo'):
                self.deny('AUDIT_WRITE_NETWORK_OR_PROCESS')
        sys.addaudithook(audit)


class CallWitness:
    def __init__(self, manifest, guard):
        self.phase = 'imports'
        self.guard = guard
        self.targets = manifest.get('call_targets', {})
        self.counts = {}
        self.completed = {}
        self.native_chains = set()
        self.module_exceptions = []
        self.dataclass_factory_code = None
        # Only the reviewed CPython 3.14 stdlib builder may generate executor
        # methods during import. A filename/name alone cannot attest its caller.
        source = Path(dataclasses.__file__).resolve()
        factory = getattr(getattr(dataclasses, '_FuncBuilder', None), 'add_fns_to_class', None)
        if sys.version_info[:2] == (3, 14) and source == Path(sys.base_prefix).resolve() / 'lib/python3.14/dataclasses.py' and (
            file_sha(source) == '2dedf70270f45c6a909ae1eac734fcf3ae3f2764bb71a330f4825aca3a79784b'
            and factory.__globals__ is dataclasses.__dict__ and Path(factory.__code__.co_filename).resolve() == source):
            self.dataclass_factory_code = factory.__code__

    def profile(self, frame, event, value):
        if event not in ('call','return'):
            return
        module = frame.f_globals.get('__name__', '')
        function = frame.f_code.co_qualname
        if event == 'call':
            # CPython profiles class bodies as calls, but unlike real functions
            # they use a separate namespace without optimized/new-locals flags.
            executor_class_body = module.startswith('v4.manager_workbench.executors.') and (
                not frame.f_code.co_flags & (inspect.CO_OPTIMIZED | inspect.CO_NEWLOCALS)
                and frame.f_locals is not frame.f_globals)
            caller = frame.f_back
            executor_dataclass_factory = False
            if module.startswith('v4.manager_workbench.executors.') and caller is not None and (
                self.dataclass_factory_code is not None and caller.f_code is self.dataclass_factory_code
                and caller.f_globals is dataclasses.__dict__ and frame.f_code.co_filename == '<string>'
                and function == '__create_fn__'):
                builder, generated = caller.f_locals.get('self'), caller.f_locals.get('ns')
                executor_dataclass_factory = type(builder) is dataclasses._FuncBuilder and type(generated) is dict and (
                    frame.f_globals is builder.globals
                    and getattr(generated.get('__create_fn__'), '__code__', None) is frame.f_code)
            if function in ('WorkbenchStore.__init__','JobCoordinator.__init__','CaptureJobs.__init__') or (
                module.startswith(('v4.manager_workbench.executors.', 'futu.', 'requests.', 'httpx.'))
                and function != '<module>' and not executor_class_body and not executor_dataclass_factory) or (
                module.startswith('v4.manager_workbench.inputs.capture') and function in ('capture_window', 'CaptureStore.__init__', 'CaptureJobs.__init__')) or (
                module == 'ops.macos_research_panel_daily' and frame.f_code.co_name in ('main','collect_hk_futu_rows','_run_hk_retained','_run_hk')):
                self.guard.deny('FORBIDDEN_BUSINESS_ENTRY')
        key = module + '::' + function
        expected = self.targets.get(key)
        if expected is None:
            return
        require(str(Path(frame.f_code.co_filename).resolve()) == expected['path'], 'CALL_ORIGIN_MISMATCH')
        if event == 'call':
            tag = self.phase + ':' + key
            self.counts[tag] = self.counts.get(tag, 0) + 1
            if self.phase == 'native':
                ancestors = []
                parent = frame.f_back
                while parent is not None and len(ancestors) < 80:
                    ancestors.append(parent.f_globals.get('__name__', '') + '::' + parent.f_code.co_qualname)
                    parent = parent.f_back
                if all(name in ancestors for name in expected.get('required_ancestors', [])):
                    self.native_chains.add(key)
        elif isinstance(value, (dict, list)) or value is not None:
            tag = self.phase + ':' + key
            self.completed[tag] = self.completed.get(tag, 0) + 1

    def trace(self, frame, event, value):
        if event == 'exception' and self.phase == 'native' and frame.f_globals.get('__name__', '') in (
            'v4.manager_workbench.inputs.native','v4.manager_workbench.inputs.strict_us_selection'):
            exc = value[1]
            if isinstance(exc, (ModuleNotFoundError, ImportError, ProbeFailure)) and len(self.module_exceptions) < 32:
                self.module_exceptions.append(exception_record(exc))
        return self.trace if frame.f_globals.get('__name__', '') in (
            'v4.manager_workbench.inputs.native','v4.manager_workbench.inputs.strict_us_selection') else None


def module_origins(manifest):
    result = {}
    for name, pin in manifest['expected_modules'].items():
        module = sys.modules.get(name)
        if module is None:
            result[name] = dict(state='NOT_LOADED_NOT_SUBSTITUTED')
            continue
        path = Path(module.__file__).resolve()
        require(str(path) == pin['path'] and file_sha(path) == pin['sha256'], 'LOADED_MODULE_IDENTITY_MISMATCH')
        result[name] = dict(state='LOADED_IDENTITY_MATCH', path=str(path), sha256=pin['sha256'])
    return result


def native_behavior(manifest, witness):
    from v4.manager_workbench.config import load_config
    from v4.manager_workbench.contracts import RunContext
    from v4.manager_workbench.inputs.native import NativeAdapters
    original = read_json(manifest['frozen_input'])
    context = RunContext.model_validate(deepcopy(original['context']))
    before = context.model_dump(mode='json')
    expected = manifest['frozen_context_expectation']
    require(all(before.get(k) == v for k, v in expected.items() if k != 'source_cutoff'), 'ORIGINAL_CONTEXT_MISMATCH', 'DATA_CANNOT_CONFIRM')
    require(before['scope_refs'].get('source_cutoff') == expected['source_cutoff'], 'ORIGINAL_SOURCE_CUTOFF_MISMATCH', 'DATA_CANNOT_CONFIRM')
    config = load_config(pinned(manifest['config']))
    witness.phase = 'native'
    try:
        value = NativeAdapters(config).us_mapping(context)
        body = value.model_dump(mode='json')
        histories = [r.get('us_factor_payload', {}).get('strict_selection_payload', {}).get('hk_history', {})
                     for r in body.get('records', []) if isinstance(r.get('us_factor_payload'), dict)]
        status = dict(returned=True, record_count=len(body.get('records', [])),
                      history_states=sorted({h.get('status','UNKNOWN') for h in histories}),
                      history_gaps=sorted({h['gap'] for h in histories if isinstance(h.get('gap'),str) and re.fullmatch(r'[A-Z0-9_]+',h['gap'])}))
    except Exception as exc:
        status = dict(returned=False, classification='MODULE_BINDING_FAILURE' if isinstance(exc,(ImportError,ModuleNotFoundError)) else 'DATA_CANNOT_CONFIRM', error=exception_record(exc))
    finally:
        witness.phase = 'between'
    require(context.model_dump(mode='json') == before, 'NATIVE_MUTATED_FROZEN_CONTEXT', 'DATA_CANNOT_CONFIRM')
    required = set(manifest['required_native_witnesses'])
    reached = required <= witness.native_chains and witness.completed.get('native:upstreams.v3_shared_data.shared_data.hk_panel_audit::strict_window_readiness', 0) > 0
    status.update(call_witness_complete=reached, required=sorted(required), reached=sorted(witness.native_chains),
                  classification='MODULE_BINDING_FAILURE' if witness.module_exceptions else status.get('classification', 'CALL_WITNESS_VERIFIED' if reached else 'DATA_CANNOT_CONFIRM'))
    return status


def pure_preopen(manifest, witness):
    from v4.manager_workbench.engines.strict_us_selection import engine_identity
    from v4.manager_workbench.engines.us_mapping_policy import POLICY_SHA256
    from v4.manager_workbench.engines.us_mapping import run_us_mapping
    from v4.manager_workbench.contracts import LaneResult
    from v4.manager_workbench.service import project_preopen_lane
    require(engine_identity() == manifest['engine_identity'], 'ENGINE_IDENTITY_MISMATCH')
    require(POLICY_SHA256 == manifest['policy_sha256'], 'POLICY_IDENTITY_MISMATCH')
    service_pin = manifest['expected_modules']['v4.manager_workbench.service']
    text = pinned(service_pin).read_text()
    node = next(n for n in ast.parse(text).body if isinstance(n, ast.FunctionDef) and n.name == 'project_preopen_lane')
    source_hash = digest(ast.get_source_segment(text,node).encode())
    ast_hash = digest((json.dumps(ast.dump(node,include_attributes=False),ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode())
    require(source_hash == manifest['preopen']['source_segment_sha256'], 'PREOPEN_SOURCE_HASH_MISMATCH')
    require(ast_hash == manifest['preopen']['replay_ast_sha256'], 'PREOPEN_AST_HASH_MISMATCH')
    original = read_json(manifest['frozen_input'])
    snapshot = read_json(manifest['frozen_snapshot'])
    require(snapshot['run_id'] == manifest['source_run'] and snapshot['changes']['input_snapshot_sha256'] == manifest['frozen_input']['sha256'], 'SOURCE_RUN_INPUT_BINDING_MISMATCH', 'DATA_CANNOT_CONFIRM')
    context = deepcopy(original['context'])
    batch = deepcopy(next(b for b in original['batches'] if b['lane'] == 'US_MAPPING'))
    before_context, before_batch = deepcopy(context), deepcopy(batch)
    witness.phase = 'preopen'
    try:
        lane = LaneResult.model_validate(run_us_mapping(context,batch))
        lane_before = lane.model_dump(mode='json')
        projected = project_preopen_lane(lane,cutoff=manifest['preopen']['cutoff'])
    finally:
        witness.phase = 'between'
    require(witness.counts.get('preopen:v4.manager_workbench.service::project_preopen_lane') == 1, 'PURE_PREOPEN_CALL_WITNESS_MISSING')
    require(context == before_context and batch == before_batch, 'PURE_ENGINE_MUTATED_FROZEN_INPUT', 'DATA_CANNOT_CONFIRM')
    require(lane.model_dump(mode='json') == lane_before, 'PREOPEN_MUTATED_SOURCE_LANE', 'DATA_CANNOT_CONFIRM')
    require([c.symbol for c in projected.selection.candidates] == [c.symbol for c in lane.selection.candidates], 'PREOPEN_CANDIDATE_ORDER_CHANGED', 'DATA_CANNOT_CONFIRM')
    for value in (lane.selection, projected.selection):
        require(all(value.counts[k] == v for k,v in manifest['preopen']['expected_counts'].items()), 'FROZEN22_COUNTS_MISMATCH', 'DATA_CANNOT_CONFIRM')
        require(len({c.symbol for c in value.candidates}) == 670, 'FROZEN22_CANDIDATE_IDENTITY_MISMATCH', 'DATA_CANNOT_CONFIRM')
    return dict(state='PURE_PREOPEN_VERIFIED',source_segment_sha256=source_hash,replay_ast_sha256=ast_hash,
                ast_python=platform.python_version(),engine_identity=engine_identity(),policy_sha256=POLICY_SHA256,
                counts=projected.selection.counts,source_context_unchanged=True,source_lane_unchanged=True,financial_readiness='UNCHANGED_NOT_VERIFIED')


def wrapper_imports(manifest):
    if manifest['role'] == 'shared':
        runpy.run_path(str(pinned(manifest['updater_entry'])),run_name='_US_HK_READONLY_OWNER_PROBE')
    for name in manifest['expected_modules']:
        importlib.import_module(name)
    # SDK metadata only. Missing SDK is not patched by adding a package path.
    spec = importlib.util.find_spec('futu')
    sdk = dict(state='SDK_UNRESOLVED' if spec is None else 'SDK_RESOLVED_UNAPPROVED_IDENTITY',
               origin=None if spec is None else spec.origin, imported=False, provider_called=False)
    return dict(state='WRAPPER_SOURCE_IMPORTS_VERIFIED',SDK=sdk)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--manifest',required=True)
    parser.add_argument('--manifest-sha256',required=True)
    parser.add_argument('--execution-capsule',required=True)
    parser.add_argument('--capsule-sha256',required=True)
    args = parser.parse_args()
    result = dict(schema='v4.us_hk.readonly_role_probe_result.v1',executed=True,financial_readiness='UNCHANGED_NOT_VERIFIED')
    guard, witness = ReadOnlyGuard(), None
    try:
        manifest_pin = dict(path=args.manifest,sha256=args.manifest_sha256)
        manifest = read_json(manifest_pin)
        capsule = read_json(dict(path=args.execution_capsule,sha256=args.capsule_sha256))
        require(capsule.get('schema') == 'v4.us_hk.role_probe_capsule.v1' and capsule.get('verdict') == 'PASS'
                and capsule.get('authorized_action') == 'READ_ONLY_CANDIDATE_ROLE_PROBE' and capsule.get('role') == manifest['role']
                and capsule.get('program_sha256') == file_sha(__file__) and capsule.get('manifest_sha256') == args.manifest_sha256,
                'INDEPENDENT_PROBE_CAPSULE_REQUIRED')
        prepared = read_json(capsule['prepared_receipt'])
        require(prepared['state'] == 'PREPARED' and prepared['candidate_root'] == manifest['candidate_root'], 'PREPARED_CANDIDATE_REQUIRED')
        pinned(dict(path=str(Path(manifest['candidate_root'])/'release-manifest.json'),sha256=prepared['candidate_manifest_sha256']))
        py = manifest['python']
        require(str(Path(sys.executable).resolve()) == py['resolved_path'] and file_sha(py['path']) == py['sha256'] and platform.python_version() == py['version'], 'ACTUAL_ROLE_PYTHON_MISMATCH')
        require(Path.cwd() == Path(manifest['candidate_root'])/'app', 'CANDIDATE_CWD_MISMATCH')
        if manifest.get('wrapper'):
            pinned(manifest['wrapper'])
            require(all(os.environ.get(k)==v for k,v in manifest['wrapper_environment'].items()), 'WRAPPER_ENVIRONMENT_DRIFT')
        for value in manifest['dependencies']:
            pinned(value)
        for value in manifest['expected_modules'].values():
            pinned(value)
        sys.dont_write_bytecode = True
        # Keep only this interpreter's standard library roots, not worktree/program directories.
        base = Path(sys.base_prefix).resolve()
        standard = [p for p in sys.path if p and Path(p).resolve().is_relative_to(base) and 'site-packages' not in Path(p).parts]
        roots = manifest['initial_search_roots']
        require(all(Path(p).is_dir() for p in roots), 'EXACT_ROLE_SEARCH_ROOT_MISSING')
        sys.path[:] = roots + [p for p in standard if p not in roots]
        guard.install()
        witness = CallWitness(manifest,guard)
        sys.setprofile(witness.profile)
        sys.settrace(witness.trace)
        result.update(role=manifest['role'],python=py,source_commit=manifest['source_commit'],program_sha256=file_sha(__file__))
        captured = io.StringIO()
        with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
            if manifest['role'] in ('api','scheduler'):
                result['native'] = native_behavior(manifest,witness)
                try:
                    result['preopen'] = pure_preopen(manifest,witness)
                except Exception as exc:
                    result['preopen'] = dict(state='CANNOT_CONFIRM',error=exception_record(exc))
                result['state'] = 'BEHAVIORAL_WITNESS_VERIFIED' if result['native']['classification']=='CALL_WITNESS_VERIFIED' and result['preopen'].get('state')=='PURE_PREOPEN_VERIFIED' else 'CANNOT_CONFIRM'
            else:
                result['wrapper_imports'] = wrapper_imports(manifest)
                result['state'] = 'CANNOT_CONFIRM_SDK_DEPENDENCY'
        result['suppressed_business_output_sha256'] = digest(captured.getvalue().encode())
        result['loaded_modules'] = module_origins(manifest)
        for key in ('frozen_input','frozen_snapshot'):
            if key in manifest:
                pinned(manifest[key])
        result['original_frozen_files_unchanged'] = manifest['role'] in ('api','scheduler')
    except Exception as exc:
        result.update(state='CANNOT_CONFIRM',failure=exception_record(exc))
    finally:
        sys.setprofile(None)
        sys.settrace(None)
    if witness is not None:
        result['call_counts'] = witness.counts
        result['completed_calls'] = witness.completed
        result['module_exceptions_in_native'] = witness.module_exceptions
    result['guard_denials'] = guard.denials
    if guard.denials:
        result['state'] = 'CANNOT_CONFIRM_GUARD_REFUSAL'
    print(json.dumps(result,ensure_ascii=False,sort_keys=True,allow_nan=False))
    return 0 if result.get('state')=='BEHAVIORAL_WITNESS_VERIFIED' else 2


if __name__ == '__main__':
    raise SystemExit(main())
