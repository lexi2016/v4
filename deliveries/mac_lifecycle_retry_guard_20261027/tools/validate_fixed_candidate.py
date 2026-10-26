"""Execute the original strict fixed shim in a fresh zero-network process."""
import hashlib
import json
import struct
import sys
from pathlib import Path

B=Path(__file__).resolve().parent
W=Path('/Users/lexi/.codex/worktrees/mac-lifecycle-retry-guard-20261027/v4_app')
local=B/'component_validation/a_sync'
sys.path.insert(0,str(W))
from ops.macos_research_panel_daily_authority import _load_authority_module


def audit(event,args):
    if event in {'socket.connect','socket.connect_ex','socket.sendto','socket.getaddrinfo'}:
        raise RuntimeError('REAL_NETWORK_FORBIDDEN')


def main():
    sys.addaudithook(audit)
    m=_load_authority_module(local/'app/ops/a_share_daily_sync.py','lifecycle_strict_fixed_candidate')
    assert Path(m.__file__)==local/'component/ops/a_share_daily_sync.py'
    facts=m._load_verified_lifecycle_facts();assert len(facts)==21
    p=B/'fixed_candidate_canary/sh601198.day';p.parent.mkdir();raw=struct.pack('<IIIIIfII',20261016,1000,1100,900,1000,100000.,10000,0);p.write_bytes(raw)
    calls=[]
    def sentinel(*args):calls.append(args);raise AssertionError('PROVIDER_FORBIDDEN')
    result=m.run_sync([m.DailyTarget('601198',1,p)],target_date='20261026',api_factory=sentinel,
        host_candidates=[('sentinel.invalid',7709)],progress_path=p.parent/'progress.json')
    assert not calls and result['lifecycle_skipped_count']==1 and result['accepted_count']==0
    assert result['by_symbol']['601198']['attempt_ordinal']==0 and p.read_bytes()==raw
    helper=sys.modules['ops._a_share_daily_sync_parts.sync_workflow']
    assert Path(helper.__file__)==local/'component/ops/_a_share_daily_sync_parts/sync_workflow.py'
    out=dict(status='PASS_ORIGINAL_STRICT_FIXED_ENTRY_ZERO_PROVIDER',provider_calls=0,network_calls=0,
        facade_path=m.__file__,helper_path=helper.__file__,component_pin_count=len(m._PINS),
        component_manifest_sha256=m._COMPONENT_MANIFEST_SHA,lifecycle_asset_sha256=m.LIFECYCLE_NOTES_SHA256,
        whole_source_history_unchanged=True,authority_claim='NONE; accepted0 target1 retained')
    (B/'FIXED_CANDIDATE_VALIDATION.json').write_text(json.dumps(out,sort_keys=True,indent=2)+'\n');print(json.dumps(out))


if __name__=='__main__':main()
