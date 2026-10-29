"""Root-only stage/CAS install adapter; does not stop/start any service."""
from pathlib import Path
import argparse, fcntl, hashlib, importlib.util, json, os, plistlib, shutil, subprocess, sys
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from ops.api_release_integration import inventory_tree
E = Path('/Users/lexi/Desktop/学习/因子工厂/research/a_daily_1530_20261029_r1')

def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def verify_inventory(root, expected, label):
    if inventory_tree(root) != expected:
        raise ValueError(label + '_FULL_INVENTORY_DRIFT')

def main():
    p = argparse.ArgumentParser()
    p.add_argument('action', choices=['stage', 'install', 'rollback'])
    p.add_argument('--review', type=Path, required=True)
    p.add_argument('--review-sha256', required=True)
    a = p.parse_args()
    plan = json.loads((E / 'CONTROL_PLAN.json').read_text())
    if sha(Path(__file__)) != plan['control_helper_sha256']:
        raise ValueError('CONTROL_HELPER_DRIFT')
    if not sha(a.review) == a.review_sha256:
        raise ValueError('REVIEW_DRIFT')
    review = json.loads(a.review.read_text())
    if not (review.get('verdict') == 'PASS' and review.get('control_plan_sha256') == sha(E / 'CONTROL_PLAN.json')):
        raise ValueError('SCOPED_REVIEW_REQUIRED')
    lock = plan['main_control_lock']
    fd = os.open(lock['path'], os.O_RDWR | os.O_NOFOLLOW)
    try:
        st = os.fstat(fd)
        if not [st.st_dev, st.st_ino] == [lock['device'], lock['inode']]:
            raise ValueError('MAIN_LOCK_INODE_DRIFT')
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        marker = Path(lock['marker'])
        if not sha(marker) == lock['marker_sha256']:
            raise ValueError('MAIN_MARKER_DRIFT')
        m = json.loads(marker.read_text())
        if not (m.get('active') is False and m.get('phase') == 'DONE'):
            raise ValueError('PRIOR_MAIN_OWNER_ACTIVE')
        source = Path(plan['candidate_root'])
        target = Path(plan['durable_root'])
        manifest = E / 'durable_release-manifest.json'
        if not sha(manifest) == plan['manifest_sha256']:
            raise ValueError('MANIFEST_DRIFT')
        verify_inventory(source / 'app', json.loads(manifest.read_text())['application_inventory']['entries'], 'SOURCE')
        for item in json.loads(manifest.read_text())['application_inventory']['entries']:
            f = source / 'app' / item['path']
            if not (item['kind'] == 'file' and (not f.is_symlink()) and (sha(f) == item['sha256'])):
                raise ValueError(('SOURCE_DRIFT', str(f)))
        if not sha(Path(plan['operator'])) == plan['operator_sha256']:
            raise ValueError('OPERATOR_DRIFT')
        spec = importlib.util.spec_from_file_location('existing_operator', plan['operator'])
        op = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(op)
        row = plan['operation']
        if not sha(Path(row['template_path'])) == row['template_sha256']:
            raise ValueError('TEMPLATE_DRIFT')
        template = plistlib.loads(Path(row['template_path']).read_bytes())
        env = template['EnvironmentVariables']
        if env.get('V4_RELEASE_MANIFEST_SHA256') != sha(manifest):
            raise ValueError('FINAL_PLIST_MANIFEST_SHA_BINDING_MISMATCH')
        if env.get('V4_RELEASE_MANIFEST_PATH') != str(target / 'release-manifest.json'):
            raise ValueError('FINAL_PLIST_MANIFEST_PATH_BINDING_MISMATCH')
        if a.action == 'stage':
            if not sha(Path(row['plist'])) == row['before_sha256']:
                raise ValueError('ACTIVE_PLIST_CAS_DRIFT')
            if target.exists():
                raise ValueError('DURABLE_ROOT_ALREADY_EXISTS')
            tmp = target.with_name('.' + target.name + '.staging-' + str(os.getpid()))
            if tmp.exists():
                raise ValueError('CONTROL_CHECK_FAILED')
            tmp.mkdir()
            subprocess.run(['/bin/cp', '-cR', str(source / 'app'), str(tmp / 'app')], check=True)
            shutil.copy2(manifest, tmp / 'release-manifest.json')
            for item in json.loads(manifest.read_text())['application_inventory']['entries']:
                if not sha(tmp / 'app' / item['path']) == item['sha256']:
                    raise ValueError('STAGE_DRIFT')
            verify_inventory(tmp / 'app', json.loads(manifest.read_text())['application_inventory']['entries'], 'STAGE')
            if target.exists():
                raise ValueError('CONTROL_CHECK_FAILED')
            tmp.rename(target)
            print('STAGED_NOT_ACTIVATED')
        else:
            if not sha(target / 'release-manifest.json') == plan['manifest_sha256']:
                raise ValueError('DURABLE_MANIFEST_DRIFT')
            verify_inventory(target / 'app', json.loads(manifest.read_text())['application_inventory']['entries'], 'DURABLE')
            for item in json.loads(manifest.read_text())['application_inventory']['entries']:
                f = target / 'app' / item['path']
                if not (not f.is_symlink() and sha(f) == item['sha256']):
                    raise ValueError('DURABLE_SOURCE_DRIFT')
            print(op.install_plist(row, rollback=a.action == 'rollback'))
    finally:
        os.close(fd)
if __name__ == '__main__':
    main()
