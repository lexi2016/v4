"""Copy verified original observation fixtures into the original test-relative layout.

Requires Mac-verified bytes and the separately reported binding SHA. Never generates
fixtures, alters JSON, runs tests, or writes to the original web source.
"""
import argparse
import hashlib
import json
from pathlib import Path

PINNED = {
    'close_recapture.json': '3b5a84bbaae7d2b04f758691506f0665878b62bfb7f769f7c1746f13a2c3ec56',
    'close_recapture.receipt.json': '540a7818a50ccf516658bd38f5df14a1abd5c84dc3f73d068d626094bea50994',
    'close_recapture.candidates.json': '548804c308701e694f575deca2a3a361203bfaf3255aac4edca53ac065d4e454',
    'inputs/close_recapture_pytdx.json': 'a5b1484f0411529c8accaac0c7eeed56d1b9c35cdf335a009061c601e86ca3e3',
}
BINDING_SHA256 = '9e5fd49a35fa70aa8d2a85b4b06547fecaae5af9f9248fbffa99e5aa48b28c0c'


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--binding-sha256', required=True)
    parser.add_argument('--web-root', type=Path, required=True)
    args=parser.parse_args()
    source=args.source.resolve(strict=True);web=args.web_root.resolve(strict=True)
    if (web/'.v5-ui-candidate').read_text()!='v5.ui-candidate.v1\n':
        raise ValueError('ISOLATED_UI_CANDIDATE_MARKER_REQUIRED')
    binding_raw=(source/'FIXTURE_BINDING.json').read_bytes()
    if args.binding_sha256!=BINDING_SHA256 or hashlib.sha256(binding_raw).hexdigest()!=BINDING_SHA256:
        raise ValueError('ORIGINAL_FIXTURE_BINDING_SHA_MISMATCH')
    binding=json.loads(binding_raw)
    expected=dict(PINNED)
    for name,entry in binding['files'].items():
        if name in expected and expected[name]!=entry['sha256']:
            raise ValueError('FIXTURE_BINDING_CONTRADICTS_FROZEN_TEST:'+name)
    for name in ('close_recapture.json','close_recapture.candidates.json'):
        if binding['files'][name]['sha256']!=PINNED[name]:
            raise ValueError('ORIGINAL_UI_FIXTURE_BINDING_MISMATCH:'+name)
    files={'FIXTURE_BINDING.json':binding_raw}
    for name,sha in expected.items():
        path=Path(name)
        if path.is_absolute() or '..' in path.parts or '\\' in name:
            raise ValueError('FIXTURE_RELATIVE_PATH_REQUIRED')
        target=source/path
        if target.is_symlink() or not target.resolve().is_relative_to(source):
            raise ValueError('FIXTURE_SOURCE_PATH_INVALID')
        raw=target.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=sha:
            raise ValueError('ORIGINAL_FIXTURE_SHA_MISMATCH:'+name)
        files[name]=raw
    # Same resolution as import.meta.url in src/manager-selection/runtime.spec:
    # ../../../../tests/... from that directory == web-root/../../tests/...
    destination=web.parents[1]/'tests/fixtures/manager_current_observation_20261002'
    if destination.resolve().is_relative_to(source) or source.is_relative_to(destination.resolve()):
        raise ValueError('FIXTURE_SOURCE_DESTINATION_OVERLAP')
    for name,raw in files.items():
        target=destination/name
        if target.is_symlink() or not target.resolve().is_relative_to(destination.resolve()):
            raise ValueError('FIXTURE_DESTINATION_PATH_INVALID')
        if target.exists() and target.read_bytes()!=raw:
            raise ValueError('EXISTING_FIXTURE_DIFFERS:'+name)
    for name,raw in files.items():
        target=destination/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
        if target.read_bytes()!=raw:raise ValueError('FIXTURE_COPY_READBACK_MISMATCH')
    print(json.dumps({'status':'MAC_VERIFIED_FIXTURE_COPIED_NOT_TESTED','destination':str(destination),
        'provenance_limit':'Historical upstream binding referenced by this binding is unavailable; its declared hash is not independently verified.',
        'sha256':{name:hashlib.sha256(raw).hexdigest() for name,raw in files.items()}},indent=2))


if __name__=='__main__':main()
