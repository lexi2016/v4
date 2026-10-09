"""Probe the handoff Vitest invocation from a documented review source cwd."""
from pathlib import Path
import hashlib, io, json, os, subprocess, tarfile, tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PACKAGE = ROOT / 'delivery/manager-three-channel-repair-20261009'
PYTHON = '/workspace/scratch/a154a3323e32/test_env/bin/python'
NODE = '/opt/codex/runtimes/codex-primary-runtime/dependencies/node/bin/node'
MODULES = '/workspace/scratch/a154a3323e32/candidate/apps/web/node_modules'
BASE = '7ca0190a721a7fd0fc0c88b79a872889867d111f'
original_log = HERE / 'package_host_web.log'
red_log = HERE / 'package_host_web_initial_failure.log'
if not red_log.exists():
    red_log.write_bytes(original_log.read_bytes())
archive = subprocess.check_output(['git', '-C', str(ROOT / 'app'), 'archive', BASE])
manifest = json.loads((PACKAGE / 'source_manifest.json').read_text())
records = []
with tempfile.TemporaryDirectory(prefix='cwd-probe-', dir=HERE / 'package_temporary') as directory:
    target = Path(directory)
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(target, filter='data')
    for profile in manifest['profiles'].values():
        subprocess.run(['git', '-C', str(target), 'apply', str(PACKAGE / profile['patch_path'])], check=True)
    (target / 'apps/web/node_modules').symlink_to(MODULES, target_is_directory=True)
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTEST_DISABLE_PLUGIN_AUTOLOAD='1',
               V4_TEST_SOURCE_ROOT=str(target), V4_TEST_PYTHON=PYTHON)
    argv = [NODE, MODULES + '/vitest/vitest.mjs', 'run', '--config',
            str(PACKAGE / 'tools/vitest.config.mjs'),
            'src/api/managerWorkspace.threeChannel.spec.ts',
            'src/api/managerWorkspace.dailyAutomation.spec.ts']
    for name, cwd in [('source_web_cwd', target / 'apps/web'), ('source_root_cwd', target)]:
        result = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True, timeout=60)
        log = HERE / ('package_host_web_' + name + '.log')
        log.write_text(result.stdout + result.stderr)
        records.append({'name': name, 'argv': argv, 'cwd': str(cwd), 'exit_code': result.returncode,
                        'log': log.name, 'log_sha256': hashlib.sha256(log.read_bytes()).hexdigest()})
        print(name, result.returncode, (result.stdout + result.stderr)[-3000:])
(HERE / 'package_host_web_cwd_probe.json').write_text(json.dumps(records, indent=2) + '\n')
