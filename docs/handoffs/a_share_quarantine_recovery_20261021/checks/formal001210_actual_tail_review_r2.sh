#!/bin/bash
set -euo pipefail
exec /usr/bin/python3 -B - <<'PY'
from pathlib import Path
import csv,hashlib,json
R=Path('/Users/lexi/Desktop/学习/因子工厂/research/a_share_quarantine_recovery_20261021');Q=R/'windows37_d21_reconcile_20261022/formal001210_repair';V=R/'review/formal001210_repair'
E='A_SHARE_FORMAL001210_ACTUAL_INDEPENDENT_REVIEW_20261022_02'
def read(p):return json.loads(Path(p).read_text())
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def ck(v,s):
 if not v:raise AssertionError(s)
def csvrows(p):
 with Path(p).open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
pkg=read(V/'ACTUAL_TAIL_R2_PACKAGE.json');start=read(R/'registry_receipts/FORMAL001210_ACTUAL_REVIEW_R2_REGISTRY_START.json')
ck(pkg['execution_id']==start['execution_id']==E and start['event_type']=='RUN_STARTED' and start['input_binding_sha256']==sha(V/'ACTUAL_TAIL_R2_PACKAGE.json') and start['code_sha256']==sha(V/'ACTUAL_TAIL_R2_COMMAND.sh'),'new tail START')
for x in pkg['inputs']:ck(sha(x['path'])==x['sha256'],'tail frozen drift:'+x['path'])
prior=read(R/'review/FORMAL001210_ACTUAL_REVIEW_RECEIPT_TRANSCRIPTION.json');oldpkg=read(V/'ACTUAL_PACKAGE.json');oldbound={x['path']:x['sha256'] for x in oldpkg['inputs']}
ck(sha(V/'ACTUAL_COMMAND.sh')==prior['command_sha256']=='65054809124eac8cc9a51ef811f24a1def1229b1871ca566dd7c733b699a1d7d' and sha(V/'ACTUAL_PACKAGE.json')==prior['package_sha256']=='0dcdadc19a58c866c40722aa49ff09b3a272c6558548a7c5cb7c103c3af76a6f','immutable prior identity')
ck(prior['tool_reported_exit_code']==1 and prior['source_writer_error'] is False and prior['stdout_complete'] is True and prior['exact_stdout_sha_match'] is True and sha(prior['stdout_transcription_path'])==prior['stdout_transcription_sha256']=='f1c12f96a451ad73f76fc5656597d46ab90a71cd5c25d8dd043a89b657a93c64','honest prior FAIL')
source=(V/'ACTUAL_COMMAND.sh').read_text().split("<<'PY'\n",1)[1].rsplit('\nPY',1)[0].splitlines();failure=Path(prior['stdout_transcription_path']).read_text()
ck('line 63, in <module>' in failure and 'AssertionError: actual branch:SZ.001210' in failure and "'actual branch:'+code" in source[62] and prior['result']['failure_line']==63,'reached immutable control-flow prefix; no fabricated positive checkpoint')
wt=read(Q/'FRESH_WRITER_TERMINAL.json');c=read(wt['contract']['path']);b=read(wt['input_binding']['path']);out=Path(c['output_dir']);res=read(out/'RESULT.json');comp=read(out/'WINDOWS37_COMPARISON_RESULT.json');counts=read(Q/'SOURCE_ONLY_RESULT_FINAL.json')
for p in [Q/'FRESH_WRITER_TERMINAL.json',Path(wt['contract']['path']),Path(wt['input_binding']['path']),out/'RESULT.json',out/'WINDOWS37_COMPARISON_RESULT.json',out/'WINDOWS37_EXACT_CODE_COMPARISON.csv',out/'tdx_selected.csv',out/'MODEL_UNION_HANDOFF.json',Path(b['prior_selection_handoff']['path']),Path(b['saved_windows_membership']['path']),Q/'FINAL_RESULT.md',Q/'SOURCE_ONLY_RESULT_FINAL.json']:
 ck(oldbound.get(str(p))==sha(p),'same inputs as completed numeric prefix:'+str(p))
rows=csvrows(out/'tdx_selected.csv');now={x['futu_code'] for x in rows};previous=set(read(b['prior_selection_handoff']['path'])['tdx']);handoff=read(out/'MODEL_UNION_HANDOFF.json');wr=csvrows(b['saved_windows_membership']['path']);win={x['canonical_code'] for x in wr}
ck(len(now)==len(rows)==33 and len(previous)==34 and len(win)==len(wr)==37 and now==set(handoff['tdx']) and all(x['selected']=='True' and x['signal_date']=='20261021' for x in rows),'pure CSV/handoff')
ck(not now-previous and previous-now=={'SZ.001210'} and len(now&win)==33 and not now-win and win-now=={'HK.02603','HK.06821','SZ.300949','SZ.301087'},'exact pure set delta')
for key,value in [('common_all',sorted(win&now)),('windows_only_all',sorted(win-now)),('local_only_all',sorted(now-win)),('newly_selected_codes',[]),('no_longer_selected_codes',['SZ.001210'])]:ck(comp[key]==value,'saved comparison:'+key)
cr=csvrows(out/'WINDOWS37_EXACT_CODE_COMPARISON.csv');bycode={x['canonical_code']:x for x in cr};ck(len(bycode)==len(cr) and set(bycode)==win|previous|now,'comparison CSV keys')
for code,x in bycode.items():ck(x['windows_saved_member']==str(code in win) and x['before_local_member']==str(code in previous) and x['after_local_member']==str(code in now),'comparison CSV membership')
for code,want in [('SZ.001210',{'XG':0,'ENTRYPOOL':1,'RELAX':0,'FRESH':49,'CONT0':66,'B3ROLE':0}),('SZ.300949',{'XG':0,'ENTRYPOOL':0,'FRESH':40,'CONT0':55,'B2ROLE':0,'B3ROLE':0}),('SZ.301087',{'XG':0,'ENTRYPOOL':0,'FRESH':64,'CONT0':90,'B3ROLE':1})]:
 x=bycode[code];actual=json.loads(x['after_reject_or_unknown']);ck(float(x['after_XG'])==0 and all(actual[k]==v for k,v in want.items()),'separate actual branches:'+code)
ck(counts['before_pureTDX_count']==34 and counts['after_pureTDX_count']==33 and counts['common_count']==33 and counts['Mac_only_count']==0 and counts['oldMac23_union_sideartifact_count']==res['union_count']==34 and counts['compared_union'] is False,'pure33 versus historical union34')
ck(counts['source_context_bars']==304 and counts['source_context_first_date']=='20250718' and counts['earlier_archive_mixed'] is False and counts['repair_raw_cells_per_role']==20 and counts['replacement_keys_per_role']==60 and counts['native_writes']==0 and counts['pointer_CAS']==2 and counts['observed_universe']==5495 and counts['unknown_count']==0,'counts scoped facts')
report=(Q/'FINAL_RESULT.md').read_text();ck('选中33只' in report and '交集33' in report and 'Mac独有0' in report and '只移除001210' in report and 'union=34' in report and '不作为本次纯TDX33' in report and '不能确认Windows实际复权/历史配置' in report and '304' in report and '1263' in report,'report facts and explicit limits')
for obj in [wt,res,comp,counts]:ck(obj['research_only'] is True and obj['production_allowed'] is False and obj['buy_gate_updated'] is False and obj['orders_sent'] is False,'research-only boundary')
print(json.dumps({'verdict':'REVIEWED/PASS','execution_id':E,'acceptance_basis':'COMBINED_PRIOR_ACTUAL_EXIT1_SUCCESSFUL_CONTROL_FLOW_PREFIX_AND_R2_REMAINING_TAIL; prior failure unchanged; no fabricated positive checkpoint','behavior_verified':'actual2CURRENT/preimages/originalconsumer/physicalR3identity from prior independent prefix plus completed pureCSV/set/branch/report tail','universe':5495,'unknown':0,'before_pureTDX':34,'after_pureTDX':33,'historical_union_sideartifact':34,'compared_union':False,'added':[],'removed':['SZ.001210'],'Windows_common':33,'local_only':[],'Windows_only':sorted(win-now),'001210':{'XG':0,'ENTRYPOOL':1,'RELAX':0},'new_formula_calls':0,'new_consumer_calls':0,'new_part_hashes':0,'new_5495_scan':0,'source_sync':'NOT_SYNCED','cannot_confirm':['Windows actual adjustment/history/engine parity and remaining two positive Windows causes','full207/API/UI/fullhistory unification','allA1020']},sort_keys=True))
PY
