"""First real caller-load canary; synthetic native fixture, zero providers."""
from pathlib import Path
import hashlib
import json
import struct
import sys

B=Path(__file__).resolve().parent
W=Path('/Users/lexi/.codex/worktrees/mac-lifecycle-retry-guard-20261027/v4_app')
sys.path.insert(0,str(W))
from ops.macos_research_panel_daily_authority import _load_authority_module, _row_classification


def main():
    p=B/'canary_601198/tdx/vipdoc/sh/lday/sh601198.day'
    p.parent.mkdir(parents=True,exist_ok=False)
    original=struct.pack('<IIIIIfII',20261016,1000,1100,900,1000,100000.,10000,0)
    p.write_bytes(original)
    m=_load_authority_module(W/'ops/a_share_daily_sync.py','mac_lifecycle_canary_601198')
    targets=[m.DailyTarget(code='601198',market=1,path=p)]
    progress=m._new_progress(20261026,targets,dry_run=False)
    old=dict(status='CANNOT_CONFIRM',classification='QUARANTINED',reason_code='A_SYNC_TIMEOUT',
             failure_type='A_SYNC_TIMEOUT:SYMBOL',raw_response_snapshots=['original-old-timeout-evidence'])
    progress['symbol_progress']={'601198':old}
    progress_path=B/'canary_601198/progress.json';progress_path.write_text(json.dumps(progress))
    calls=[]
    def forbidden(*args,**kwargs):
        calls.append('provider');raise AssertionError('REAL_PROVIDER_FORBIDDEN')
    result=m.run_sync(targets,target_date='20261026',api_factory=forbidden,
        host_candidates=[('sentinel.invalid',7709)],progress_path=progress_path)
    row=result['by_symbol']['601198']
    assert calls==[] and row['lifecycle_skip'] is True
    assert row['reason_code']=='VERIFIED_DELISTED_NO_CURRENT_BARS'
    assert row['target_date_ready'] is False and row['attempt_ordinal']==0
    assert result['target_count']==1 and result['accepted_count']==0 and result['quarantine_count']==1
    assert result['technical_failure_count']==0 and result['lifecycle_skipped_count']==1
    assert result['authority_status']!='PASS' and result['status']!='PASS'
    assert _row_classification(row)=='QUARANTINED'
    assert result['progress']['symbol_progress']['601198']==old
    assert p.read_bytes()==original and result['raw_response_snapshots']==[]
    out=dict(status='PASS_601198_ORIGINAL_CALLER_LOAD_ZERO_PROVIDER',provider_calls=0,
        source_bytes_unchanged=True,old_timeout_record_preserved=True,
        target_count=result['target_count'],accepted_count=result['accepted_count'],
        quarantine_count=result['quarantine_count'],lifecycle_skipped_count=result['lifecycle_skipped_count'],
        technical_failure_count=result['technical_failure_count'],source_result=result)
    (B/'canary_601198/RESULT.json').write_text(json.dumps(out,ensure_ascii=False,sort_keys=True,indent=2)+'\n')
    print(json.dumps({k:v for k,v in out.items() if k!='source_result'}))


if __name__=='__main__':main()
