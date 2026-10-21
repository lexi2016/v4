"""Metadata binding only, after the original-chain publication actually exists."""
import copy, hashlib, json, shlex
from pathlib import Path

R = Path(__file__).resolve().parents[1]
W = Path('/Users/lexi/Desktop/学习/因子工厂/worktrees/mac_tdx_month_compare_20261021/research/mac_selection_watchlist_20261021/tdx_today')
E = 'A_SHARE_QUARANTINE_FRESH_TDX_SELECTION_20261021_01'
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p): return json.loads(Path(p).read_text())
def save(p,x):
    with Path(p).open('x') as f: json.dump(x,f,ensure_ascii=False,indent=2);f.write('\n')
def ref(p): return {'path':str(p),'sha256':sha(p)}

def main():
    publication=R/'original_chain_publish/A_SHARE_QUARANTINE_ORIGINAL_CHAIN_PUBLISH_20261021_01/PUBLISH_RECEIPT.json'
    promoted=read(publication)
    assert promoted['status']=='ORIGINAL_CHAIN_PUBLISHED_AND_CONSUMER_READBACK'
    out=R/'selection_replay';out.mkdir(mode=0o700,exist_ok=False);(out/'runs').mkdir()
    binding=read(W/'INPUT_BINDING_R3.json');contract=read(W/'CONTRACT_R3.json')
    original_selector=copy.deepcopy(binding['selector']);new=promoted['roles']['legacy_selector'];pointer=Path(new['pointer_path']);target=Path(new['new_path']);s=target.stat()
    assert pointer.read_text().strip()==str(target)
    p=binding['selector'];p.update(pointer=ref(pointer),target_path=str(target),target_stat={'inode':s.st_ino,'mtime_ns':s.st_mtime_ns,'size_bytes':s.st_size},
        authority_metadata=ref(publication),existing_reported_target_sha256=new['new_sha256'],expected_sha256=new['new_sha256'],
        reported_sha_basis='Actual reviewed original-owner recovery publication receipt; original runner freshly hashes before any market-value decode',
        panel_sha256_source_ref=ref(publication),producer_target_ref=ref(publication),
        content_identity_policy='Exact actual original CURRENT->newversioned target and published SHA; no substitute or staging input')
    # The Mac23 handoff is deliberately immutable, independently of the newly
    # replayed TDX result.  Keep its original provenance trio as frozen inputs.
    removed={original_selector['pointer']['path'],original_selector['authority_metadata']['path'],original_selector['producer_target_ref']['path']}
    binding['frozen_refs']=[x for x in binding['frozen_refs'] if x['path'] not in removed]
    binding['saved_windows_membership']=ref(R.parent/'tdx_windows37_diagnostic_20261021/windows37_membership.csv')
    binding['prior_selection_handoff']=ref(R.parent/'mac_selection_watchlist_20261021/tdx_today/runs/today_tdx_02/MODEL_UNION_HANDOFF.json')
    diff=ref(R/'helpers/compare_repaired_selection.py')
    binding['frozen_refs'] += [ref(publication),ref(pointer),binding['saved_windows_membership'],binding['prior_selection_handoff'],diff]
    binding['source_identity']='Same delivered255 offline formula, fresh actual repaired original authoritative selector panel. Windows client formula body/run date remain CANNOT_CONFIRM. ExistingMac23 retained solely because unchanged runner emits its union; not recomputed or imported.'
    binding['price_basis']['corporate_action_policy']='Original raw-native inputs; no new XDXR fetch/adjustment. Historical adjustment/economic corporate-action completeness CANNOT_CONFIRM.'
    binding['source_reuse_scope']='Full physical re-selection of all exactD SH/SZ/BJ observed rows using original aa3f runner/638a evaluator/afa3 formula and history20260101..20261021. No TopN/tuning/model changes.'
    bp=out/'INPUT_BINDING.json';save(bp,binding)
    cp=out/'CONTRACT.json';gate=contract['external_start_gate']
    contract.update(status='FROZEN_READY_PENDING_REAL_START',writer='/root/windows37_source_diagnosis',reviewer='independent actualrun review',
        route_id='A_SHARE_QUARANTINE_RECOVERY_20261021',execution_id=E,stage='FRESH_PHYSICAL_FULL_REPAIRED_PANEL_SELECTION_AND_SAVED_WINDOWS37_DIFF',
        registry_start_path=str(R/'registry_receipts/FRESH_TDX_SELECTION_REGISTRY_START.json'),input_binding_path=str(bp),input_binding_sha256=sha(bp),
        baseline_id='Oldactual30vsSavedWindows37; source354andwholepanel366reviewed, fullreselectionnewusergoal',
        one_variable='Repaired original source/panel generation only; formula/history/date/resources frozen unchanged',
        allowed_output_parent=str(out/'runs'),output_dir=str(out/'runs/repaired_today_01'),allowed_write_paths=[str(out)],
        forbidden='Any authority/raw/pointer/service/scheduler/Futu/BUY/registry mutation, network, strategy/threshold/TopN/date/history tuning or future labels. SavedWindows37 date/body unknown remains unknown.',
        pass_signal='OriginalR3 full physical5495 exactD replay yields all255assignments/explicitunknown; exact selected CSV+savedWindows37 comparison including2HKscope. Equality is an observed result, never a forced acceptance condition. Independent runtime result review required; not Windows engine parity or trainingREADY.',
        stop_rule='Originalsource/input/schema/stat/date/gate drift, duplicates/malformedkeys or resourcebound=>fail preservepartials, no rerun/tuning to matchWindows. No unknownfalse.',
        revision='FRESH_REPAIRED_ORIGINAL_PANEL_ONLY_SAME_R3_RUNNER',postprocessing=diff)
    gate['receipt_path']=str(out/'START_GATE_RECEIPT.json');contract['external_start_gate']=gate
    save(cp,contract)
    python=binding['python_executable']
    runner=[python,contract['code_path'],'--contract',str(cp),'--binding',str(bp),'--gate-receipt',gate['receipt_path'],
            '--expected-contract-sha256',sha(cp),'--expected-code-sha256',contract['code_sha256'],'--expected-binding-sha256',sha(bp)]
    gatecmd=[python,gate['path'],'--contract',str(cp),'--expected-event-sha256','REGISTRAR_REAL_START_EVENT_SHA_REQUIRED','--output',gate['receipt_path']]
    commands={'gate_argv':gatecmd,'runner_argv':runner,'diff_argv':[python,'-B',diff['path']]};save(out/'COMMAND.json',commands)
    package={'execution_id':E,'route_id':contract['route_id'],'contract_path':str(cp),'contract_sha256':sha(cp),
        'code_path':contract['code_path'],'code_sha256':contract['code_sha256'],'input_binding_path':str(bp),'input_sha256':sha(bp),
        'input_bindings':[ref(bp),*binding['frozen_refs'],ref(gate['path']),ref(contract['code_path'])],
        'baseline_id':contract['baseline_id'],'ONE_VARIABLE':contract['one_variable'],'truth_access':contract['truth_access'],'sealed_status':contract['sealed_status'],
        'signal_date_range':['20261021','20261021'],'target_date_range':None,
        'official_start_required_fields':{'input_sha256':sha(bp),'code_sha256':contract['code_sha256'],'config_sha256':sha(cp),'artifact_must_include':ref(bp)},
        'commands':[{'phase':k,'cwd':str(R),'command':shlex.join(v),'expected_exit_code':0} for k,v in commands.items()],
        'research_only':True,'production_allowed':False,'buy_gate_updated':False,'orders_sent':False}
    pkg=R/'REGISTRATION_PACKAGE_FRESH_TDX_SELECTION.json';save(pkg,package)
    print(json.dumps({'package_path':str(pkg),'package_sha256':sha(pkg),'contract_sha256':sha(cp),'binding_sha256':sha(bp),'code_sha256':contract['code_sha256']}))

if __name__=='__main__':main()
