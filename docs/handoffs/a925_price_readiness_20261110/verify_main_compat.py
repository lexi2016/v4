"""Exact one-line Main reader compatibility; isolated artifact roots only."""
from pathlib import Path
import difflib
import hashlib
import json
import os
import subprocess
import sys

from verify_isolated import HERE, mount, sha

MAIN = Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/candidates/v4-v192-assets-20261109-r1/v4-v192-assets-20261109-r1-main/app')
BEFORE_SHA = '348e19df299d2b67697ec4f145a2d9952dbfdd3d963b3cbde428d5a97bb822cd'
ALGORITHM_SHA = '15fd78695c5c0b345dcbf6b32f884320b1fb51b3f9b40876bfe83fe9655fa896'
NEW_STORE = HERE/'.verification/artifacts'
OLD_STORE = HERE/'.verification/main-legacy-fixture'


def probe(mode):
    from stage_center import selection
    from stage_center.consumer import StageSelectionConsumer
    if mode == 'before':
        row=dict(code='A.000001',name='compat fixture',first_open=10,last_close=10.2,
                 high=10.3,low=9.9,amount=1000,bar_count=5,expected_rows=5,formal_eligible=True)
        envelope=selection.select_a_stage([row],'20261110','STAGE_0930_0935','c'*64)
        assert OLD_STORE.resolve().is_relative_to(HERE)
        selection.publish_selection(OLD_STORE,envelope,market='A_SHARE')
    old=selection.SelectionStore(OLD_STORE).read_verified('20261110','STAGE_0930_0935','A_SHARE')
    assert len(old['rows']) == 1 and old['algorithm_sha256'] != ALGORITHM_SHA
    legacy_get=StageSelectionConsumer(OLD_STORE).get('20261110','STAGE_0930_0935',markets=('A_SHARE',))
    assert legacy_get['markets']['A_SHARE']['selected_rows'] == 1
    result=dict(mode=mode,legacy_reader='PASS',legacy_algorithm_sha256=old['algorithm_sha256'],
                legacy_consumer_get='PASS',allowlist=sorted(selection.ALGORITHM_SHA_ALLOWLIST))
    try:
        output=selection.SelectionStore(NEW_STORE).read_verified('20261109','STAGE_0925','A_SHARE')
    except selection.SelectionError as error:
        assert mode == 'before' and str(error) == 'selection algorithm SHA mismatch'
        result.update(new_reader='EXPECTED_RED',error=str(error))
    else:
        assert mode == 'after' and output['algorithm_sha256'] == ALGORITHM_SHA
        expected=json.loads((HERE/'.verification/envelope.json').read_text())
        assert output['rows'] == expected['rows']
        result.update(new_reader='PASS',selected_rows=len(output['rows']),
                      new_algorithm_sha256=output['algorithm_sha256'],envelope_rows_exact=True)
    response=StageSelectionConsumer(NEW_STORE).get('20261109','STAGE_0925',markets=('A_SHARE',))
    selected=response['markets']['A_SHARE']['selected_rows']
    assert selected == (0 if mode == 'before' else 10)
    result.update(new_consumer_get='EXPECTED_RED' if mode == 'before' else 'PASS',consumer_selected_rows=selected)
    (HERE/f'MAIN_COMPAT_{mode.upper()}_RESULT.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


def main():
    if len(sys.argv)>1:
        return probe(sys.argv[1])
    path=MAIN/'stage_center/selection.py'
    assert sha(path) == BEFORE_SHA
    before=path.read_text()
    needle='        V11_PIT_TOP10_ALGORITHM_SHA256,\n'
    assert before.count(needle) == 1 and ALGORITHM_SHA not in before
    after=before.replace(needle,needle+f'        "{ALGORITHM_SHA}",  # A925 price readiness observation\n')
    (HERE/'main_compat.patch').write_text(''.join(difflib.unified_diff(before.splitlines(True),after.splitlines(True),
        fromfile='a/stage_center/selection.py',tofile='b/stage_center/selection.py')))
    metadata=dict(source=str(path),before_sha256=BEFORE_SHA,after_sha256=hashlib.sha256(after.encode()).hexdigest(),
                  algorithm_sha256=ALGORITHM_SHA,delta='append one allowlist literal only',
                  new_fixture_store=str(NEW_STORE),legacy_fixture_store=str(OLD_STORE))
    (HERE/'MAIN_COMPAT_SHA.json').write_text(json.dumps(metadata,indent=2)+'\n')
    for mode,source in [('before',before),('after',after)]:
        overlay=HERE/f'.verification/main-{mode}'
        mount(MAIN,overlay,{'stage_center/selection.py':source.encode()})
        subprocess.run([sys.executable,str(Path(__file__).resolve()),mode],cwd=overlay,
                       env=dict(os.environ,PYTHONPATH=str(overlay),PYTHONDONTWRITEBYTECODE='1'),check=True)
    old=json.loads((HERE/'MAIN_COMPAT_BEFORE_RESULT.json').read_text())
    new=json.loads((HERE/'MAIN_COMPAT_AFTER_RESULT.json').read_text())
    assert set(new['allowlist']) == set(old['allowlist']) | {ALGORITHM_SHA}
    assert sha(path) == BEFORE_SHA
    print('MAIN_COMPAT_PASS: new reader RED->GREEN, old reader and consumer get preserved; source SHA unchanged')


if __name__=='__main__':main()
