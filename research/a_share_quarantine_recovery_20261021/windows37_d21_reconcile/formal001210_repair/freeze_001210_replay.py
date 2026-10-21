"""Metadata-only fresh binding after actual original-pointer publication.

Does not start the replay, hash a large panel or decode values. The unchanged
runner and its registered start gate perform their original runtime checks.
"""
import hashlib,json
from pathlib import Path
R=Path('/Users/lexi/Desktop/学习/因子工厂/research/a_share_quarantine_recovery_20261021')
N=R/'windows37_d21_reconcile_20261022/formal001210_repair'
W=Path(__file__).resolve().parent
E='A_SHARE_FORMAL001210_D21_FRESH_SELECTION_20261022_01'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def ref(p):return {'path':str(p),'sha256':sha(p)}
def save(p,x):
 with Path(p).open('x')as f:json.dump(x,f,ensure_ascii=False,indent=2);f.write('\n')
def main():
 pub=N/'publish/A_SHARE_FORMAL001210_PAIR_PUBLISH_20261022_R2_01/PUBLISH_RECEIPT.json';publication=json.loads(pub.read_text())
 assert publication['status']=='ORIGINAL_TWO_POINTERS_PUBLISHED_CONSUMER_READ_BACK'
 out=N/'selection_replay_r2';out.mkdir(exist_ok=False);(out/'runs').mkdir()
 binding=json.loads((R/'selection_replay/INPUT_BINDING.json').read_text());c=json.loads((R/'selection_replay/CONTRACT.json').read_text())
 p=publication['roles']['legacy_selector'];pointer=Path(p['pointer_path']);target=Path(p['new_path']);s=target.stat()
 assert pointer.read_text(encoding='utf-8-sig').strip()==str(target)
 assert {'inode':s.st_ino,'mtime_ns':s.st_mtime_ns,'size':s.st_size}==p['candidate_stat']
 sel=binding['selector'];sel.update(pointer=ref(pointer),target_path=str(target),target_stat={'inode':s.st_ino,'mtime_ns':s.st_mtime_ns,'size_bytes':s.st_size},
  authority_metadata=ref(pub),existing_reported_target_sha256=p['new_sha256'],expected_sha256=p['new_sha256'],panel_sha256_source_ref=ref(pub),producer_target_ref=ref(pub),
  content_identity_policy='Actual original CURRENT->new immutable reviewed sibling; untouched5495native snapshot. Originalrunner hashesexactpanel beforedecode.')
 # Originalrunner consumes this exact legacy metadata shape. The small view
 # projects only actual transaction facts; it is not a source/data producer.
 compatibility={'schema':'PUBLISHED_SELECTOR_TRANSACTION_COMPATIBILITY_VIEW_V1',
  'source_transaction_receipt':ref(pub),'selector_output':str(target),
  'provenance':{'panel_sha256':p['new_sha256']},'actual_CURRENT_pointer':ref(pointer),
  'identity_policy':'Exact actualindependentlyacceptedpublicationfacts only; originalrunner schemaadapter, not newdata orauthority'}
 meta=out/'PUBLISHED_SELECTOR_METADATA.json';save(meta,compatibility)
 sel['panel_sha256_source_ref']=ref(meta);sel['producer_target_ref']=ref(meta)
 before=R/'windows37_d21_reconcile_20261022/selection_replay_r2/runs/d21_repaired_01/MODEL_UNION_HANDOFF.json';binding['prior_selection_handoff']=ref(before)
 remove={str(pointer),str(R/'helpers/compare_repaired_selection.py'),str(R/'selection_replay/INPUT_BINDING.json')}
 refs=[x for x in binding['frozen_refs']if x['path']not in remove]
 refs.extend([ref(pointer),ref(pub),ref(meta),ref(before),ref(W/'compare_001210.py'),ref(N/'WRITER_TERMINAL.json'),ref(R/'review/FORMAL001210_PANEL_AND_PUBLISH_REVIEW_R2_RECEIPT_TRANSCRIPTION.json')])
 binding['frozen_refs']=list({x['path']:x for x in refs}.values())
 for x in binding['frozen_refs']:assert sha(x['path'])==x['sha256']
 binding['source_identity']='Windows20261021 and same formula USER_CONFIRMED. Local originalfrozen255/rawunadjusted/Jan1 replay; actualWindows adjustment/history/engine settings not inferred. Mac23sideunion remains originalrunner sideartifact and isneverusedincomparison.'
 binding['revision']='D21_FORMAL001210_PANEL_ONLY_REPAIR_ACTUAL_AUTHORITY_FRESH_BINDING'
 save(out/'INPUT_BINDING.json',binding)
 c.update(execution_id=E,stage='D21_PHYSICAL_FULL_SAME_FORMULA_REPLAY_AFTER_FORMAL001210_PANEL_REPAIR',registry_start_path=str(R/'registry_receipts/FORMAL001210_D21_FRESH_SELECTION_REGISTRY_START.json'),
  input_binding_path=str(out/'INPUT_BINDING.json'),input_binding_sha256=sha(out/'INPUT_BINDING.json'),
  baseline_id='Actualpublished5495/TDX34 common33 priorD21; only00121020rawcells plus originaldefineddependencies repair',
  one_variable='Only001210 original two-panel historicaldata repair; date20261021/history20260101/formula255/thresholds/resources unchanged',
  allowed_output_parent=str(out/'runs'),output_dir=str(out/'runs/d21_repaired_01'),allowed_write_paths=[str(out)],
  forbidden='No native/authority/pointer/runtime/scheduler/Futu/BUY/registry/network or formula/date/window tuning. WindowsD21sameformulaUSER_CONFIRMED; adjustment/history settings CANNOT_CONFIRM.',
  postprocessing=ref(W/'compare_001210.py'))
 c['external_start_gate']['receipt_path']=str(out/'START_GATE_RECEIPT.json');c['revision']='ACTUAL_FORMAL001210_REPAIR_SAME_D21_PURE_TDX_SELECTION'
 save(out/'CONTRACT.json',c)
 cmd=json.loads((R/'selection_replay/COMMAND.json').read_text())
 cmd['gate_argv'][cmd['gate_argv'].index('--contract')+1]=str(out/'CONTRACT.json');cmd['gate_argv'][cmd['gate_argv'].index('--output')+1]=str(out/'START_GATE_RECEIPT.json')
 a=cmd['runner_argv']
 for flag,v in {'--contract':str(out/'CONTRACT.json'),'--binding':str(out/'INPUT_BINDING.json'),'--gate-receipt':str(out/'START_GATE_RECEIPT.json'),'--expected-contract-sha256':sha(out/'CONTRACT.json'),'--expected-binding-sha256':sha(out/'INPUT_BINDING.json')}.items():a[a.index(flag)+1]=v
 cmd['diff_argv']=[binding['python_executable'],'-B',str(W/'compare_001210.py')];save(out/'COMMAND.json',cmd)
 old=json.loads((R/'REGISTRATION_PACKAGE_FRESH_TDX_SELECTION.json').read_text())
 old.update(execution_id=E,contract_path=str(out/'CONTRACT.json'),contract_sha256=sha(out/'CONTRACT.json'),config_sha256=sha(out/'CONTRACT.json'),input_binding_path=str(out/'INPUT_BINDING.json'),input_sha256=sha(out/'INPUT_BINDING.json'),
  input_bindings=binding['frozen_refs']+[ref(out/'INPUT_BINDING.json'),ref(out/'COMMAND.json')],baseline_id=c['baseline_id'],ONE_VARIABLE=c['one_variable'],commands=[{'phase':k,'cwd':str(N),'argv':v,'expected_exit_code':0}for k,v in cmd.items()],
  signal_date_range=['20261021','20261021'])
 old['official_start_required_fields']={'input_sha256':sha(out/'INPUT_BINDING.json'),'code_sha256':c['code_sha256'],
  'config_sha256':sha(out/'CONTRACT.json'),'artifact_must_include':ref(out/'INPUT_BINDING.json')}
 # The previous package used command_file in addition to commands; bind both
 # explicitly to this new artifact whenever present.
 for k in ('command_path','command_file'):
  if k in old:old[k]=str(out/'COMMAND.json')
 if 'command_sha256'in old:old['command_sha256']=sha(out/'COMMAND.json')
 save(N/'REGISTRATION_PACKAGE_FRESH_SELECTION_R2.json',old)
 print(json.dumps({'package':ref(N/'REGISTRATION_PACKAGE_FRESH_SELECTION_R2.json'),'contract':ref(out/'CONTRACT.json'),'binding':ref(out/'INPUT_BINDING.json'),'command':ref(out/'COMMAND.json'),'market_decode':0,'large_panel_hash':0}))
if __name__=='__main__':main()
