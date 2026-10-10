"""Reconstruct a private build root from exact tracked source objects; no capture."""
import argparse, hashlib, json, subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
BASE = '164c010c7eaa1659db9bfed0ff5f123c7a39eefc'
UI = '8342862f05ca9f6516f51b3164b6110651e5af77'
DEPS = '7d2b71a91ad4d54f85fe03f5973248af686d7a87'

def git(*args):
    return subprocess.check_output(['git', '-C', str(REPO), *args])

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    root = args.out.absolute()
    if root.exists():
        raise ValueError('NEW_ISOLATED_WEB_ROOT_REQUIRED')
    inventory = {}
    pending = {}
    def collect(ref, prefix):
        for path in git('ls-tree', '-r', '--name-only', ref, prefix).decode().splitlines():
            relative = path[len(prefix):]
            raw = git('show', ref + ':' + path)
            pending[relative] = raw
            inventory[relative] = dict(commit=ref, path=path, sha256=hashlib.sha256(raw).hexdigest())
    collect(BASE, 'handoff/v4-running-source-20261005/canonical/apps/web/')
    collect(UI, 'handoff/manager-workbench-repair-20261008/after/apps/web/')
    collect(UI, 'handoff/manager-workbench-mac-completion-20261008/source/web/apps/web/')
    dep_paths = [
        'handoff/manager-daily-automation-repair-20261009-r2/dependencies/web_original/apps/web/src/api/managerAnnouncementAnalysis.ts',
        'handoff/manager-daily-automation-repair-20261009-r2/dependencies/web_original/apps/web/src/manager-selection/announcementAnalysis.ts',
        'handoff/manager-daily-r3-repair-20261009/after/web_cumulative/apps/web/src/manager-selection/researchAttention.ts',
        'handoff/manager-daily-r3-repair-20261009/after/web_cumulative/apps/web/src/manager-selection/dailyResearchRun.ts',
    ]
    for path in dep_paths:
        relative = path.split('apps/web/')[1]
        raw = git('show', DEPS + ':' + path)
        pending[relative] = raw
        inventory[relative] = dict(commit=DEPS, path=path, sha256=hashlib.sha256(raw).hexdigest())
    root.mkdir(parents=True)
    for relative, raw in pending.items():
        dest = root / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(raw)
    (root / '.v5-ui-candidate').write_text('v5.ui-candidate.v1\n')
    subprocess.run(['python3', str(REPO/'V5/ui/manager-workbench/apply_candidate.py'), '--web-root', str(root)], check=True)
    for name in ('manager-selection', 'daily-research-command'):
        page = root / name / 'index.html'
        page.parent.mkdir(exist_ok=True)
        title='经理选股工作台 · V4' if name=='manager-selection' else 'V5 云端隔离预览'
        page.write_text(f'<!doctype html><html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title></head><body><div id="{name}"></div><script type="module" src="/src/{name}/main.ts"></script></body></html>\n')
    (root/'tsconfig.cloud-product.json').write_text(json.dumps(dict(extends='./tsconfig.json', exclude=['node_modules','src/**/*.spec.ts','src/**/__tests__/**','src/**/*.testHelper.ts'])))
    (root/'src/manager-selection/cloudActualReadback.spec.ts').write_bytes(Path(__file__).with_name('cloudActualReadback.spec.ts').read_bytes())
    (root/'src/api/cloudRecoveryContract.spec.ts').write_bytes(Path(__file__).with_name('cloudRecoveryContract.spec.ts').read_bytes())
    (root/'cloud-source-provenance.json').write_text(json.dumps(inventory, indent=2))
    print('SOURCE_ONLY: run locked npm install, tests, typecheck and build separately')

if __name__ == '__main__':
    main()
