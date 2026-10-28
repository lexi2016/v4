#!/usr/bin/env python3
"""Explicit-scope, read-only code inventory and pinned-baseline size ratchet.

This reports structural size, NOT correctness, performance, owner approval,
whole-repository coverage, deployment status, or a trusted CI policy. Defaults
800/200 are proposed limits for this deliverable. It never refreshes a baseline.
"""
from __future__ import annotations
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import stat
import sys
import tokenize
import io
from typing import Any

MAX_SOURCE_BYTES = 16 * 1024 * 1024
MAX_JSON_BYTES = 16 * 1024 * 1024
MAX_SCOPE_FILES = 20000
MAX_TOTAL_BYTES = 256 * 1024 * 1024
SNAPSHOT_SCHEMA = 'v4.code_size_snapshot.v1'
POLICY_ID = 'v4.explicit_scope_no_new_debt.v1'
SUPPORTED = {'.py', '.pyi', '.ts', '.tsx', '.js', '.jsx', '.vue', '.sh'}
EXCLUDED_COMPONENTS = {'.git', '.venv', 'venv', 'node_modules', 'vendor', 'third_party',
                       'upstreams', '__pycache__', 'site-packages', 'dist'}


def _path(value: Any) -> str:
    if not isinstance(value, str) or not value or '\x00' in value or '\\' in value:
        raise ValueError('UNSAFE_PATH')
    p, w = PurePosixPath(value), PureWindowsPath(value)
    if p.is_absolute() or w.drive or w.root or any(x in {'', '.', '..'} for x in value.split('/')):
        raise ValueError('UNSAFE_PATH')
    if p.as_posix() != value:
        raise ValueError('NONCANONICAL_PATH')
    return value


def _category(path: str) -> str:
    parts = [part.casefold() for part in PurePosixPath(path).parts]
    if any(part in EXCLUDED_COMPONENTS or 'manager' in part or 'wechat' in part
           or 'vibe8910' in part or '公众号' in part for part in parts):
        return 'excluded'
    if 'tests' in parts or 'test' in parts or PurePosixPath(path).name.startswith('test_'):
        return 'test'
    return 'production'


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('DUPLICATE_JSON_KEY: ' + key)
        value[key] = item
    return value


def load_json(path: Path, *, expected_sha256: str | None = None):
    absolute = Path(os.path.abspath(path))
    raw = _read_source(absolute.parent, absolute.name, [MAX_JSON_BYTES])
    if len(raw) > MAX_JSON_BYTES:
        raise ValueError('JSON_TOO_LARGE')
    if expected_sha256 is not None and _sha(raw) != expected_sha256:
        raise ValueError('BASELINE_SHA_MISMATCH')
    return json.loads(raw.decode('utf-8'), object_pairs_hook=_object)


def _read_source(root: Path, relative: str, budget: list[int]) -> bytes:
    """No-follow descriptor walk, bounded read, point-in-time stability checks."""
    if os.name != 'posix' or not hasattr(os, 'O_NOFOLLOW'):
        raise ValueError('PLATFORM_NOFOLLOW_UNSUPPORTED')
    parts = Path(os.path.abspath(root)).parts[1:] + PurePosixPath(relative).parts
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
            os.close(fd)
            fd = child
        source_fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=fd)
        try:
            before = os.fstat(source_fd)
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                raise ValueError('SOURCE_NOT_SINGLE_LINK_REGULAR_FILE')
            if before.st_size > MAX_SOURCE_BYTES or before.st_size > budget[0]:
                raise ValueError('SOURCE_OR_TOTAL_BYTE_LIMIT')
            chunks, total = [], 0
            while True:
                block = os.read(source_fd, min(65536, MAX_SOURCE_BYTES - total + 1, budget[0] + 1))
                if not block:
                    break
                total += len(block)
                budget[0] -= len(block)
                if total > MAX_SOURCE_BYTES or budget[0] < 0:
                    raise ValueError('SOURCE_GROWTH_OR_TOTAL_BYTE_LIMIT')
                chunks.append(block)
            after = os.fstat(source_fd)
            visible = os.stat(parts[-1], dir_fd=fd, follow_symlinks=False)
            fields = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns', 'st_nlink')
            if any(getattr(before, k) != getattr(after, k) for k in fields):
                raise ValueError('SOURCE_CHANGED_DURING_READ')
            if (after.st_dev, after.st_ino) != (visible.st_dev, visible.st_ino):
                raise ValueError('SOURCE_REPLACED_DURING_READ')
            return b''.join(chunks)
        finally:
            os.close(source_fd)
    finally:
        os.close(fd)


class _Functions(ast.NodeVisitor):
    def __init__(self):
        self.stack, self.rows, self.occurrences = [], [], {}

    def visit_ClassDef(self, node):
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    def _function(self, node):
        qualified = '.'.join(self.stack + [node.name])
        ordinal = self.occurrences.get(qualified, 0) + 1
        self.occurrences[qualified] = ordinal
        start = min([node.lineno] + [d.lineno for d in node.decorator_list])
        self.rows.append({'key': qualified + '#' + str(ordinal), 'qualname': qualified,
                          'start': start, 'end': node.end_lineno,
                          'lines': node.end_lineno - start + 1,
                          'ast_sha256': _sha(ast.dump(node, include_attributes=False).encode())})
        self.stack.append(node.name + '.<locals>')
        self.generic_visit(node)
        self.stack.pop()

    visit_FunctionDef = _function
    visit_AsyncFunctionDef = _function


def scan(root: Path, scope: dict) -> dict:
    if not isinstance(scope, dict) or set(scope) != {'schema', 'scope_id', 'files'}:
        raise ValueError('INVALID_SCOPE_SCHEMA')
    if scope['schema'] != 'v4.code_scope.v1' or not isinstance(scope['scope_id'], str) or not scope['scope_id'].strip():
        raise ValueError('INVALID_SCOPE_ID')
    paths = scope['files']
    if not isinstance(paths, list) or len(paths) > MAX_SCOPE_FILES:
        raise ValueError('INVALID_SCOPE_FILE_SET')
    paths = [_path(p) for p in paths]
    if len({p.casefold() for p in paths}) != len(paths):
        raise ValueError('DUPLICATE_OR_CASE_ALIAS_PATH')
    root = Path(os.path.abspath(root))
    if _category(str(root)) == 'excluded':
        raise ValueError('ROOT_IN_EXCLUDED_AREA')
    budget, records = [MAX_TOTAL_BYTES], []
    for relative in sorted(paths):
        category = _category(relative)
        row = {'path': relative, 'category': category}
        if category == 'excluded':
            records.append({**row, 'status': 'EXCLUDED', 'content_read': False})
            continue
        try:
            if PurePosixPath(relative).suffix not in SUPPORTED:
                raise ValueError('UNSUPPORTED_CODE_EXTENSION')
            raw = _read_source(root, relative, budget)
            if relative.endswith(('.py', '.pyi')):
                encoding, _ = tokenize.detect_encoding(io.BytesIO(raw).readline)
                text = raw.decode(encoding)
                tree = ast.parse(raw, filename=relative)
                visitor = _Functions(); visitor.visit(tree)
                functions = visitor.rows
                imports = sorted({
                    ('.' * n.level + (n.module or '')) if isinstance(n, ast.ImportFrom)
                    else alias.name
                    for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))
                    for alias in (n.names if isinstance(n, ast.Import) else [None])
                })
                analysis = 'PYTHON_AST'
            else:
                text = raw.decode('utf-8')
                functions, imports, analysis = [], [], 'NOT_ANALYZED'
            records.append({**row, 'status': 'OK', 'bytes': len(raw), 'sha256': _sha(raw),
                            'physical_lines': len(text.splitlines()),
                            'nonblank_lines': sum(bool(line.strip()) for line in text.splitlines()),
                            'functions': functions, 'imports': imports, 'function_analysis': analysis})
        except (OSError, ValueError, UnicodeError, SyntaxError, RecursionError) as error:
            records.append({**row, 'status': 'ERROR', 'error_type': type(error).__name__, 'error': str(error)})
    return {'schema': SNAPSHOT_SCHEMA, 'policy_id': POLICY_ID, 'scope_id': scope['scope_id'],
            'scope_sha256': _sha(_json_bytes(scope)), 'root_observation': str(root),
            'coverage': 'EXPLICIT_FILE_LIST_ONLY_NOT_WHOLE_REPOSITORY',
            'policy_adoption': 'PROPOSED_NOT_CI_ENABLED',
            'consistency': 'POINT_IN_TIME_NOT_A_LOCK_OR_LEASE',
            'status': 'ERROR' if any(r['status'] == 'ERROR' for r in records) else 'SCANNED',
            'read_bytes': MAX_TOTAL_BYTES - budget[0], 'files': records}


def _snapshot(value: Any) -> dict[str, dict]:
    if not isinstance(value, dict) or value.get('schema') != SNAPSHOT_SCHEMA or value.get('policy_id') != POLICY_ID:
        raise ValueError('INVALID_SNAPSHOT_SCHEMA_OR_POLICY')
    if not isinstance(value.get('scope_id'), str) or not isinstance(value.get('files'), list):
        raise ValueError('INVALID_SNAPSHOT_FIELDS')
    if value.get('status') != 'SCANNED':
        raise ValueError('SNAPSHOT_CONTAINS_ERRORS')
    rows = {}
    aliases = set()
    for row in value['files']:
        if not isinstance(row, dict): raise ValueError('INVALID_SNAPSHOT_ROW')
        path = _path(row.get('path'))
        if path.casefold() in aliases: raise ValueError('DUPLICATE_SNAPSHOT_PATH')
        aliases.add(path.casefold())
        if row.get('category') != _category(path): raise ValueError('CATEGORY_DRIFT')
        if row['category'] == 'excluded':
            if row.get('status') != 'EXCLUDED': raise ValueError('BAD_EXCLUSION')
        else:
            if row.get('status') != 'OK': raise ValueError('SOURCE_ERROR')
            for key in ('physical_lines','nonblank_lines','bytes'):
                if type(row.get(key)) is not int or row[key] < 0: raise ValueError('INVALID_COUNT')
            if row['nonblank_lines'] > row['physical_lines']: raise ValueError('INVALID_LINE_COUNTS')
            if not isinstance(row.get('sha256'), str) or len(row['sha256']) != 64: raise ValueError('INVALID_SOURCE_SHA')
            if not isinstance(row.get('functions'), list): raise ValueError('INVALID_FUNCTION_LIST')
            seen = set()
            for fn in row['functions']:
                if not isinstance(fn,dict) or not isinstance(fn.get('key'),str) or fn['key'] in seen:
                    raise ValueError('INVALID_FUNCTION_KEY')
                seen.add(fn['key'])
                if type(fn.get('lines')) is not int or fn['lines'] < 1: raise ValueError('INVALID_FUNCTION_LINES')
        rows[path] = row
    return rows


def compare(baseline: dict, current: dict, *, file_limit: int = 800, function_limit: int = 200) -> dict:
    result = {'schema': 'v4.code_size_comparison.v1', 'status': 'FAIL',
              'meaning': 'SIZE_RATCHET_ONLY_NOT_BEHAVIOR_OR_CI_AUTHORIZATION',
              'file_limit': file_limit, 'function_limit': function_limit,
              'violations': [], 'remaining_file_debt': [], 'remaining_function_debt': [], 'closed_file_debt': []}
    try:
        if type(file_limit) is not int or type(function_limit) is not int or min(file_limit,function_limit) < 1:
            raise ValueError('INVALID_LIMITS')
        old, new = _snapshot(baseline), _snapshot(current)
        if baseline['scope_id'] != current['scope_id']: raise ValueError('SCOPE_ID_DRIFT')
        removed = sorted(set(old) - set(new))
        if removed: result['violations'].append('SCOPE_SHRUNK: ' + ', '.join(removed))
        for path, row in new.items():
            if row['category'] != 'production': continue
            prior = old.get(path)
            old_lines = prior['physical_lines'] if prior and prior['status']=='OK' else 0
            if row['physical_lines'] > file_limit:
                result['remaining_file_debt'].append(path)
                if row['physical_lines'] > max(file_limit, old_lines): result['violations'].append('FILE_SIZE_GROWTH: ' + path)
            elif old_lines > file_limit:
                result['closed_file_debt'].append(path)
            old_functions = {f['key']:f for f in prior['functions']} if prior and prior['status']=='OK' else {}
            for fn in row['functions']:
                prior_fn = old_functions.get(fn['key'])
                old_length = prior_fn['lines'] if prior_fn else 0
                if fn['lines'] > function_limit:
                    key = path + '::' + fn['key']; result['remaining_function_debt'].append(key)
                    if fn['lines'] > max(function_limit, old_length): result['violations'].append('FUNCTION_SIZE_GROWTH: ' + key)
        result['physical_line_delta'] = sum(r.get('physical_lines',0) for r in new.values()) - sum(r.get('physical_lines',0) for r in old.values())
        result['added_paths'] = sorted(set(new)-set(old))
        result['status'] = 'FAIL' if result['violations'] else 'PASS_NO_NEW_SIZE_DEBT'
    except (ValueError, TypeError, KeyError) as error:
        result['violations'].append(str(error))
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('scan','check'):
        cmd = sub.add_parser(name)
        cmd.add_argument('--root', required=True, type=Path)
        cmd.add_argument('--scope', required=True, type=Path)
        if name == 'check':
            cmd.add_argument('--baseline', required=True, type=Path)
            cmd.add_argument('--baseline-sha256', required=True)
            cmd.add_argument('--file-limit',type=int,default=800)
            cmd.add_argument('--function-limit',type=int,default=200)
    args = parser.parse_args(argv)
    try:
        current = scan(args.root,load_json(args.scope))
        output = current if args.command=='scan' else compare(
            load_json(args.baseline,expected_sha256=args.baseline_sha256), current,
            file_limit=args.file_limit, function_limit=args.function_limit)
        print(json.dumps(output,ensure_ascii=False,indent=2,sort_keys=True))
        return 0 if output['status'] in {'SCANNED','PASS_NO_NEW_SIZE_DEBT'} else 3
    except (OSError,ValueError,TypeError,KeyError) as error:
        print(json.dumps({'status':'ERROR','error':str(error)},ensure_ascii=False))
        return 2

if __name__ == '__main__':
    raise SystemExit(main())
