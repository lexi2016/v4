"""Reconstruct one historical R2 source file; never import or execute that file."""
from pathlib import Path
import hashlib
import json
import shutil
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parent
BASE_SHA = '5d06b07077f4adef851e9c0711e41b406da6e51ce75d989561a93c347a27e2c8'
EXPECTED_SHA = '297dc6f5950d3614437378c22e3157b6866823fbf25fd39cb47f112ffea40da7'
RELATIVE = Path('v4/manager_research/us_mapping_research.py')
base_path = ROOT / 'us_mapping_research.page_base.py'
patch_path = ROOT / 'us_mapping_research.daily_r2.patch'
base = base_path.read_bytes()
if hashlib.sha256(base).hexdigest() != BASE_SHA:
    raise SystemExit('STOP: exact historical source preimage SHA mismatch')
patch = patch_path.read_text()
headers = [line for line in patch.splitlines() if line.startswith(('--- ', '+++ '))]
if headers != [f'--- a/{RELATIVE}', f'+++ b/{RELATIVE}']:
    raise SystemExit('STOP: patch is not restricted to the approved single source file')

with tempfile.TemporaryDirectory(prefix='historical-r2-source-', dir=ROOT) as temporary:
    work = Path(temporary)
    target = work / RELATIVE
    target.parent.mkdir(parents=True)
    shutil.copyfile(base_path, target)
    result = subprocess.run(
        ['patch', '--batch', '--fuzz=0', '--forward', '-p1', '-i', str(patch_path)],
        cwd=work, capture_output=True, text=True, check=False,
    )
    output = result.stdout + result.stderr
    if result.returncode or 'offset' in output.lower() or 'fuzz' in output.lower():
        raise SystemExit('STOP: exact patch application failed\n' + output)
    runtime = target.read_bytes()
    actual = hashlib.sha256(runtime).hexdigest()
    if actual != EXPECTED_SHA:
        raise SystemExit('STOP: reconstructed deployment SHA mismatch: ' + actual)
    reference = ROOT / 'us_mapping_research.runtime_r2.py'
    reference.write_bytes(runtime)

receipt = {
    'scope': 'HISTORICAL_R2_SOURCE_RECONSTRUCTION_ONLY_NOT_CURRENT_R3',
    'source_commit': '840b9538c45c9ba8fd56f8e89048aff230df0f0f',
    'page_overlay_git_blob': '61852de6fb4466e4603fb9db8ecf34c301227f93',
    'daily_overlay_git_blob': 'b9f4bcf846925b14bcab1a12d28d21de3f0035e9',
    'before_sha256': BASE_SHA, 'before_bytes': len(base),
    'runtime_sha256': actual, 'runtime_bytes': len(runtime),
    'reference_file': reference.name,
    'exact_single_file_patch': True, 'fuzz_or_offset_used': False,
    'patch_output': output,
    'source_imported_or_executed': False, 'candidate_modified': False,
    'current_R3_module_pin': 'NOT_PROVIDED_IN_INSPECTED_LOCAL_METADATA',
}
(ROOT / 'reconstruction_receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
print(json.dumps(receipt, indent=2))
