#!/usr/bin/env python3
"""Finite outcome-free replay; all writes stay under the inventory's scratch directory."""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
import json
import os
from pathlib import Path
import resource
import sys
import time

SOURCE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE_ROOT))
sys.dont_write_bytecode = True

from v4.manager_workbench.us_mapping_replay import (
    INVENTORY_SHA, ReplayError, aggregate, atomic_json, digest, load_inventory,
    make_freeze, output_root, run_to_checkpoint, source_manifest,
)


def install_read_only_guard(root, deny_processes=True):
    """Process-local hard stop for network/processes or writes beyond derived outputs."""
    boundary = Path(root).absolute()

    def safe(path):
        if isinstance(path, int):
            return
        path = Path(os.fsdecode(path)).absolute()
        if '..' in path.parts or not path.is_relative_to(boundary):
            raise ReplayError('WRITE_OUTSIDE_ISOLATED_REPLAY_OUTPUT')

    def audit(event, args):
        if event.startswith('socket.') or (deny_processes and event in {
                'subprocess.Popen', 'os.system', 'os.exec', 'os.posix_spawn', 'os.fork', 'os.forkpty'}):
            raise ReplayError('NETWORK_OR_PROCESS_FORBIDDEN_IN_REPLAY')
        if event == 'open':
            mode, flags = args[1], args[2]
            if (isinstance(mode, str) and any(c in mode for c in 'wax+')) or (
                    isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)):
                safe(args[0])
        elif event in {'os.mkdir', 'os.remove', 'os.rmdir', 'os.chmod'}:
            safe(args[0])
        elif event in {'os.rename', 'os.link', 'os.symlink'}:
            safe(args[0]); safe(args[1])
    sys.addaudithook(audit)


def _worker(task):
    inventory, row, freeze, root, deterministic = task
    return run_to_checkpoint(inventory, row, freeze, root, deterministic=deterministic)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inventory', type=Path, required=True)
    parser.add_argument('--inventory-sha', default=INVENTORY_SHA)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--run-id', action='append', default=[])
    parser.add_argument('--workers', type=int, choices=(1, 2, 3, 4), default=1)
    parser.add_argument('--deterministic', action='store_true', help='Call the true entry twice with the identical input')
    parser.add_argument('--freeze-only', action='store_true')
    args = parser.parse_args(argv)
    inventory = load_inventory(args.inventory, args.inventory_sha)
    root = output_root(args.output, args.inventory)
    root.mkdir(parents=True, exist_ok=True)
    freeze = make_freeze(inventory, args.inventory_sha, SOURCE_ROOT)
    # Only this coordinator may bootstrap the explicitly requested pool. Business
    # entries run in guarded children; in serial mode this process denies spawning.
    install_read_only_guard(root, deny_processes=args.workers == 1)
    freeze_path = root / ('freeze-' + freeze['freeze_sha256'] + '.json')
    atomic_json(freeze_path, freeze)
    if args.freeze_only:
        print(json.dumps({'status': 'FROZEN_NO_LABELS', 'freeze': str(freeze_path)}, indent=2))
        return 0
    requested = set(args.run_id)
    rows = [r for r in inventory['runs'] if not requested or r['run_id'] in requested]
    if requested - {r['run_id'] for r in rows}:
        raise ReplayError('REQUESTED_RUN_NOT_IN_FROZEN_INVENTORY')
    started = time.monotonic()
    usage_before = resource.getrusage(resource.RUSAGE_SELF)
    # Freeze is written before importing the business entry, reading outcomes or executing cases.
    tasks = [(inventory, row, freeze, root, args.deterministic) for row in rows]
    if args.workers == 1:
        refs = [_worker(task) for task in tasks]
    else:
        with ProcessPoolExecutor(max_workers=args.workers, initializer=install_read_only_guard, initargs=(root,)) as executor:
            refs = list(executor.map(_worker, tasks))
    if source_manifest(SOURCE_ROOT) != freeze['code']:
        raise ReplayError('SOURCE_CHANGED_DURING_REPLAY; CASES_RETAINED_NOT_ACCEPTED')
    result = aggregate(inventory, freeze, refs)
    usage_after = resource.getrusage(resource.RUSAGE_SELF)
    result['execution'] = {'workers': args.workers, 'elapsed_seconds': round(time.monotonic() - started, 6),
                           'parent_peak_rss_bytes_macos': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                           'children_peak_rss_bytes_macos': resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss,
                           'guard': 'NETWORK_PROCESS_DENIED; WRITES_ONLY_DERIVED_ROOT',
                           'reused_case_count': sum(r['reused'] for r in refs)}
    result['execution'].update(input_blocks=usage_after.ru_inblock - usage_before.ru_inblock,
                               output_blocks=usage_after.ru_oublock - usage_before.ru_oublock,
                               child_input_blocks=resource.getrusage(resource.RUSAGE_CHILDREN).ru_inblock,
                               child_output_blocks=resource.getrusage(resource.RUSAGE_CHILDREN).ru_oublock,
                               processed_runs_per_second=len(rows) / (time.monotonic() - started))
    path = root / ('aggregate-' + digest(result) + '.json')
    atomic_json(path, result)
    print(json.dumps({'aggregate': str(path), 'freeze': str(freeze_path),
                      'processed_runs': result['processed_runs'], 'status_counts': result['status_counts'],
                      'coverage_denominator': result['coverage_denominator'], 'effect_status': result['effect_status'],
                      'execution': result['execution']}, indent=2))
    return 1 if result['status_counts'].get('RUNTIME_FAILURE') else 0


if __name__ == '__main__':
    raise SystemExit(main())
