"""Run the existing three-stock F10 plan with the actual Main owner modules.

This entry only binds the already reviewed plan to the frozen running Main;
it does not collect F10 or implement an index/event publisher.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
from pathlib import Path
import plistlib
import re
import runpy
import subprocess
import sys

MAIN = Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/candidates/f10-daily-20261101-c94609b4e5fff848-main/app')
PLIST = Path('/Users/lexi/Library/LaunchAgents/com.lexi.v4.scheduler.plist')
MANIFEST = MAIN.parent / 'release-manifest.json'
EVIDENCE = Path('/Users/lexi/Desktop/学习/agents调试/DOT_TO_LOCAL_QWEN_MIGRATION_V1_20261101/kb_panel_upgrade_20261101/libang_300206_20261102_r1/f10_three_completion_r1')
SCRIPT = EVIDENCE / 'prepare_three_f10.py'
PLAN = EVIDENCE / 'THREE_F10_PUBLICATION_PLAN_R2.json'
PIN = {
    'plist': '534168016c0308fef27a4fba8d3b02351352765fac45c8fdb44fa3d5ec26a25f',
    'manifest': '3f9a184c28884411bfc79872b44e6b2189cd33a44bc8413da0f79b9644a83388',
    'script': 'dfb70cf0b96296548470857bad48668024b552d125f7cd5c6581f2c53830510b',
    'plan': 'fc0bd29cf67c7f2b719cb07b5bdb7e649d212dd07b6112eba67b706a00fd6ae0',
    'ops.research_panel_f10': '8c17e7905de4310d65e34589abd62cf32a0cc1a70ed6b3c5048d52707d7f6bd6',
    'ops.sync_stock_history_completion': '8ac31ebf6aca340ef9f4262e959cf72d16c29c86b185b4058e73c96ea872f6da',
    'ops.research_panel_daily_product': '1dd77a2f793de38c53f62e3eb4260356a09cceb4d1b466293d0244dee2477c80',
}
MAIN_PID = 24081


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify_entrypoint(expected_sha):
    if not re.fullmatch('[0-9a-f]{64}', expected_sha or '') or _sha(__file__) != expected_sha:
        raise ValueError('F10_BINDING_ENTRYPOINT_DRIFT')


def verify_running_owner(expected_plan_sha):
    if expected_plan_sha != PIN['plan'] or _sha(PLAN) != PIN['plan'] or _sha(SCRIPT) != PIN['script']:
        raise ValueError('F10_OWNER_PLAN_OR_SCRIPT_DRIFT')
    if _sha(PLIST) != PIN['plist'] or _sha(MANIFEST) != PIN['manifest']:
        raise ValueError('F10_MAIN_CONFIGURATION_DRIFT')
    value = plistlib.loads(PLIST.read_bytes()); env = value.get('EnvironmentVariables', {})
    if (value.get('Label') != 'com.lexi.v4.scheduler' or value.get('WorkingDirectory') != str(MAIN)
            or env.get('V4_APP_ROOT') != str(MAIN) or env.get('V4_RELEASE_MANIFEST_PATH') != str(MANIFEST)
            or env.get('V4_RELEASE_MANIFEST_SHA256') != PIN['manifest']):
        raise ValueError('F10_MAIN_CONFIGURATION_IDENTITY_CONFLICT')
    printed = subprocess.check_output(['launchctl', 'print', f'gui/{os.getuid()}/com.lexi.v4.scheduler'], text=True)
    match = re.search(r'^\s*pid = (\d+)\s*$', printed, re.MULTILINE)
    if not match or int(match.group(1)) != MAIN_PID:
        raise ValueError('F10_MAIN_PID_CHANGED')
    cwd = subprocess.check_output(['lsof', '-a', '-p', str(MAIN_PID), '-d', 'cwd', '-Fn'], text=True).splitlines()
    if 'n' + str(MAIN) not in cwd:
        raise ValueError('F10_MAIN_CWD_CHANGED')
    for module in ('ops.research_panel_f10', 'ops.sync_stock_history_completion', 'ops.research_panel_daily_product'):
        if _sha(MAIN / (module.replace('.', '/') + '.py')) != PIN[module]:
            raise ValueError('F10_MAIN_MODULE_DRIFT:' + module)
    return {'pid': MAIN_PID, 'app_root': str(MAIN), 'plist_sha256': PIN['plist'],
            'manifest_sha256': PIN['manifest'], 'plan_sha256': PIN['plan']}


def _load_bound_modules():
    modules = {}
    for name in ('ops.research_panel_f10', 'ops.sync_stock_history_completion', 'ops.research_panel_daily_product'):
        module = importlib.import_module(name); path = Path(module.__file__).resolve()
        if path != MAIN / (name.replace('.', '/') + '.py') or _sha(path) != PIN[name]:
            raise ValueError('F10_IMPORTED_OWNER_MISMATCH:' + name)
        modules[name] = module
    if not callable(modules['ops.sync_stock_history_completion']._inherited_owner_duplicate):
        raise ValueError('F10_OWNER_LOCK_INTERFACE_MISSING')
    return modules


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('check', 'publish'))
    parser.add_argument('--plan-sha256', required=True)
    parser.add_argument('--owner-code-sha256', required=True)
    parser.add_argument('--verified-child', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    verify_entrypoint(args.owner_code_sha256)
    verify_running_owner(args.plan_sha256)
    if not args.verified_child:
        env = dict(os.environ); env.pop('PYTHONHOME', None); env['PYTHONPATH'] = str(MAIN)
        os.chdir(MAIN)
        os.execve(sys.executable, [sys.executable, '-B', '-P', str(Path(__file__).resolve()),
            args.action, '--plan-sha256', args.plan_sha256, '--owner-code-sha256', args.owner_code_sha256,
            '--verified-child'], env)
    modules = _load_bound_modules()
    # Keep the actual publisher and its lock order. Check Main immediately
    # before invoking it, after the original plan's own read-only CAS check.
    f10 = modules['ops.research_panel_f10']; original = f10.publish_f10_completion
    def owner_checked_publish(*values, **options):
        verify_entrypoint(args.owner_code_sha256)
        verify_running_owner(args.plan_sha256)
        return original(*values, **options)
    f10.publish_f10_completion = owner_checked_publish
    print(json.dumps({'status':'F10_ACTUAL_MAIN_OWNER_BOUND', **verify_running_owner(args.plan_sha256)},
                     ensure_ascii=False), flush=True)
    sys.argv = [str(SCRIPT), args.action, '--plan-sha256', args.plan_sha256]
    runpy.run_path(str(SCRIPT), run_name='__main__')


if __name__ == '__main__':
    main()
