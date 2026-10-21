"""Frozen dummy-only regression for two publish-review findings.

No native decoding, formula invocation, authority path or network access.
"""
import copy, hashlib, importlib.util, json
from pathlib import Path
from unittest.mock import patch

def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def put(path, x): Path(path).write_text(json.dumps(x, indent=2) + '\n')

def fixture(root, module):
    root.mkdir()
    raw, replacement, backup = root/'dummy_raw.bin', root/'new.bin', root/'backup.bin'
    original, updated = b'ORIGINAL-DUMMY-BYTES\n', b'REVIEWED-DUMMY-BYTES\n'
    raw.write_bytes(original); replacement.write_bytes(updated); backup.write_bytes(original)
    csv_path, proofs = root/'file_results.csv', root/'proofs.json'
    csv_path.write_text('path\n'); put(proofs,{})
    item={'path':str(raw),'replacement_path':str(replacement),'backup_path':str(backup),
          'old_sha256':sha(raw),'new_sha256':sha(replacement),'class':'DUMMY_ONLY'}
    prepared={'sources':[item],'prepared_csv':{'path':str(csv_path),'sha256':sha(csv_path)},
              'proofs':{'path':str(proofs),'sha256':sha(proofs)}}
    put(root/'PREPARE_RECEIPT.json',prepared)
    plan=root/'source_plan.json';put(plan,{'sources':[item]})
    gate_path=root/'gate.json'
    cfg={'publish_gate_path':str(gate_path),'input_bindings':[],'panels':{},
         'lock_path':str(root/'dummy.lock'),'lock_scope':'DUMMY_ONLY', 'source_plan_path':str(plan)}
    cfg_path=root/'original_contract.json';put(cfg_path,cfg)
    approved=root/'approved_review.json';put(approved,{'decision':'DUMMY_APPROVED'})
    activation={'original_contract':{'path':str(cfg_path),'sha256':sha(cfg_path)},
                'source_plan':{'path':str(plan),'sha256':sha(plan)},'helper_sha256':sha(module.__file__),
                'prepared_receipt':{'path':str(root/'PREPARE_RECEIPT.json'),'sha256':sha(root/'PREPARE_RECEIPT.json')},
                'input_bindings':[],'publish_gate_path':str(gate_path)}
    activation_path=root/'activation.json';put(activation_path,activation)
    gate={'allow_publish':True,'execution_id':module.E,'activation_contract_sha256':sha(activation_path),
          'helper_sha256':sha(module.__file__),'original_contract_sha256':sha(cfg_path),
          'source_plan_sha256':sha(plan),'prepare_receipt_sha256':sha(root/'PREPARE_RECEIPT.json'),
          'independent_review_receipt':{'path':str(approved),'sha256':sha(approved)}}
    put(gate_path,gate)
    return cfg,activation,activation_path,gate,raw,original,updated

def fail_journal_after_first_cas(module, root, is_r2):
    cfg,activation,ap,gate,raw,original,updated=fixture(root,module)
    real_open=Path.open; triggered={'value':False};journal=root/'TRANSACTION_JOURNAL.jsonl'
    def faulty_open(path,*args,**kwargs):
        if path == journal:
            if triggered['value'] or raw.read_bytes()==updated:
                triggered['value']=True
                raise OSError('INJECTED_PERSISTENT_JOURNAL_IO_AFTER_FIRST_SOURCE_CAS')
        return real_open(path,*args,**kwargs)
    caught=None
    with patch.object(module,'active_writers',return_value=[]), patch.object(Path,'open',faulty_open):
        if is_r2:
            with patch.object(module,'ACTIVATION_CONTRACT',ap):
                try:module.publish(cfg,root)
                except OSError as exc:caught=str(exc)
        else:
            try:module.publish(cfg,root)
            except OSError as exc:caught=str(exc)
    assert triggered['value'] and caught
    after=raw.read_bytes()
    if is_r2:
        assert after==original,'R2 failed to roll back after persistent journal I/O failure'
        receipt=json.loads((root/'PUBLISH_FAILURE_RECEIPT.json').read_text())
        assert receipt['status']=='FAILED_ROLLED_BACK' and not receipt['rollback_conflicts']
        assert len(receipt['rollback_journal_failures']) >= 2
    else:
        assert after==updated,'Original journal bug was not reproduced'
    return {'persistent_journal_error_observed':True,'raw_restored':after==original,
            'original_bug_reproduced':not is_r2,'error':caught}

def run(module, activation):
    root=Path(activation['canary_stage']);root.mkdir(parents=True,exist_ok=False)
    old_path=Path(activation['original_helper']['path'])
    assert sha(old_path)==activation['original_helper']['sha256']
    spec=importlib.util.spec_from_file_location('immutable_original_publish_red',old_path)
    old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
    before=fail_journal_after_first_cas(old,root/'original_red',False)
    after=fail_journal_after_first_cas(module,root/'r2_green',True)
    cfg,a,ap,gate,raw,original,updated=fixture(root/'identity_guards',module)
    results=[]
    with patch.object(module,'ACTIVATION_CONTRACT',ap):
        module.verify_publish_gate(gate,cfg,root/'identity_guards',a)
        for key in ('activation_contract_sha256','helper_sha256','original_contract_sha256','source_plan_sha256','prepare_receipt_sha256'):
            changed=copy.deepcopy(gate);changed[key]='0'*64;refused=False
            try:module.verify_publish_gate(changed,cfg,root/'identity_guards',a)
            except AssertionError:refused=True
            assert refused and raw.read_bytes()==original
            results.append({'case':key,'refused_before_cas':True})
        changed=copy.deepcopy(cfg);changed['panels']={'unapproved_destination':{'new_path':'DUMMY_UNAPPROVED'}}
        refused=False
        try:module.verify_publish_gate(gate,changed,root/'identity_guards',a)
        except AssertionError:refused=True
        assert refused and raw.read_bytes()==original
        results.append({'case':'unapproved_runtime_panel_destination','refused_before_cas':True})
    receipt={'execution_id':module.E,'status':'TWO_REVIEW_FINDINGS_DUMMY_REGRESSION_PASS',
             'original_red':before,'r2_green':after,'exact_identity_guards':results,
             'real_prepared_artifacts_reused_unchanged':True,'authority_writes':0,'pointer_writes':0,
             'market_decode_calls':0,'formula_calls':0,'network_calls':0}
    module.save(root/'CANARY_RECEIPT.json',receipt)
    print(json.dumps(receipt))
