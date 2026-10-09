"""Apply pinned V5 changes to an existing isolated copy, never build or deploy."""
import argparse
import hashlib
import json
from pathlib import Path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--web-root', required=True, type=Path)
    args=parser.parse_args()
    root=args.web_root.resolve(strict=True)
    # The existing Mac task creates this marker in its disposable copy only.
    if (root/'.v5-ui-candidate').read_text() != 'v5.ui-candidate.v1\n':
        raise ValueError('ISOLATED_UI_CANDIDATE_MARKER_REQUIRED')
    base=Path(__file__).resolve().parent
    manifest=json.loads((base/'overlay-manifest.json').read_text())
    pending=[]
    for relative,expected in manifest['unchanged'].items():
        target=root/relative
        if target.is_symlink() or not target.resolve().is_relative_to(root) or digest(target)!=expected:
            raise ValueError('UI_BASE_DEPENDENCY_MISMATCH:'+relative)
    for row in manifest['changes']:
        target=root/row['path'];source=base/row['source']
        if target.is_symlink() or not target.resolve().is_relative_to(root):
            raise ValueError('UI_TARGET_PATH_INVALID:'+row['path'])
        if digest(source)!=row['after_sha256']:
            raise ValueError('UI_OVERLAY_SOURCE_MISMATCH:'+row['path'])
        actual=digest(target) if target.exists() else None
        if actual not in (row['before_sha256'],row['after_sha256'],row.get('previous_candidate_sha256', row['before_sha256'])):
            raise ValueError('UI_BASE_FILE_MISMATCH:'+row['path'])
        pending.append((target,source.read_bytes(),row))
    # Validate all original files before any replacement. No dependency install,
    # application run, build, static sync, API mutation or preview switch here.
    for target,raw,row in pending:
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(raw)
        if digest(target)!=row['after_sha256']:
            raise ValueError('UI_CANDIDATE_READBACK_MISMATCH:'+row['path'])
    print(json.dumps({'status':'SOURCE_OVERLAY_APPLIED_NOT_TESTED_OR_BUILT',
                      'web_root':str(root),'files':{row['path']:digest(target) for target,_,row in pending}},indent=2))


if __name__=='__main__':main()
