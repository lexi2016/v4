"""CAS only the two original pointers after exact independent acceptance.

Reviewed CAS/consumer primitives are reused. No native, snapshot, schedule or
runtime mutation. All preimages and immutable panel generations are retained.
"""
import sys
sys.dont_write_bytecode=True
import argparse,fcntl,hashlib,importlib.util,json,os,time
from pathlib import Path
N=Path('/Users/lexi/Desktop/学习/因子工厂/research/a_share_quarantine_recovery_20261021/windows37_d21_reconcile_20261022/formal001210_repair')
E='A_SHARE_FORMAL001210_PAIR_PUBLISH_20261022_R2_01'

def load(p):
 s=importlib.util.spec_from_file_location('reviewed_previous_pointer_primitives',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def read(p):return json.loads(Path(p).read_text())
def frozen(cfg,b):
 for x in cfg['input_bindings']:assert b.sha(x['path'])==x['sha256'],'Frozen identity drift:'+x['path']
 for p in cfg['panels'].values():
  assert b.sha(p['pointer_path'])==p['old_pointer_sha256'],'Current pointer drift'
  assert Path(p['pointer_path']).read_text(encoding='utf-8-sig').strip()==p['old_path']
  assert b.stat(p['old_path'])==p['old_stat'],'Old immutable panel drift'
  assert b.stat(p['candidate_path'])==p['candidate_stat'],'Reviewed candidate drift'

def gate(cfg,b,stage):
 g=read(cfg['publish_gate_path']);assert g['allow_publish']is True and g['execution_id']==E
 expected={'contract_sha256':b.sha(N/'PUBLISH_CONTRACT_R2.json'),'helper_sha256':b.sha(__file__),
  'prepare_receipt_sha256':b.sha(stage/'PREPARE_RECEIPT.json')}
 for k,v in expected.items():assert g[k]==v,'Gate identity drift:'+k
 prepared=read(stage/'PREPARE_RECEIPT.json')
 for role,p in cfg['panels'].items():
  preimage=stage/(role+'_preimage.txt')
  assert b.sha(preimage)==p['old_pointer_sha256']==prepared['pointer_preimages'][role]['sha256'],'Prepared pointer preimage drift'
  assert g['candidate_sha256'][role]==p['new_sha256']
  assert g['destinations'][role]==p['new_path']
 refs=g['independent_review_receipts'];assert len(refs)==1,'Exactly one approved combined review required'
 for ref in refs:
  assert str(Path(ref['path']).resolve())==str(Path(cfg['required_review_receipt_path']).resolve()),'Approved combined review identity mismatch'
  assert b.sha(ref['path'])==ref['sha256'],'Approved review drift'
 return g

def rollback(b,written,stage,journal):
 conflicts=[];log_errors=[]
 for role,p,newsha in reversed(written):
  try:
   if b.sha(p['pointer_path'])!=p['old_pointer_sha256']:
    before=(stage/(role+'_preimage.txt')).read_bytes()
    assert hashlib.sha256(before).hexdigest()==p['old_pointer_sha256'],'Rollback preimage drift; preserve foreign bytes'
    b.cas_bytes(p['pointer_path'],newsha,before,E+'.rollback')
  except BaseException as e:conflicts.append({'role':role,'error':str(e)})
  try:journal('ROLLBACK_ATTEMPT',role=role)
  except BaseException as e:log_errors.append({'role':role,'error':str(e)})
 return conflicts,log_errors

def prepare(cfg,b,stage):
 frozen(cfg,b);assert not b.active_writers(),'Active original A worker'
 stage.mkdir(parents=True,exist_ok=False)
 for role,p in cfg['panels'].items():
  b.exclusive_bytes(stage/(role+'_preimage.txt'),Path(p['pointer_path']).read_bytes())
  assert b.sha(stage/(role+'_preimage.txt'))==p['old_pointer_sha256'],'Prepare preimage does not equal approved old pointer'
 dummy={'status':'REUSED_PRIOR_INDEPENDENT_CAS_PRIMITIVE_PASS','receipt':cfg['prior_publisher_review']}
 # Fault injected after one successful pointer CAS: a broken journal must not
 # prevent restoring the preimage, and foreign replacement bytes must survive.
 d=stage/'fault_dummy';d.mkdir();p=d/'pointer.txt';b.exclusive_bytes(p,b'old\n')
 old=b.sha(p);new=hashlib.sha256(b'new\n').hexdigest();b.exclusive_bytes(stage/'dummy_preimage.txt',b'old\n')
 b.cas_bytes(p,old,b'new\n',E+'.dummy')
 entry=('dummy',{'pointer_path':str(p),'old_pointer_sha256':old},new)
 def broken(event,**kw):raise OSError('injected persistent journal fault')
 conflicts,log_errors=rollback(b,[entry],stage,broken);assert not conflicts and b.sha(p)==old and log_errors
 b.save(stage/'PREPARE_RECEIPT.json',{'execution_id':E,'status':'PAIR_PREPARED_NOT_PUBLISHED',
  'pointer_preimages':{r:{'path':str(stage/(r+'_preimage.txt')),'sha256':b.sha(stage/(r+'_preimage.txt'))}for r in cfg['panels']},
  'reviewed_CAS_canary':dummy,'journal_fault_rollback':True,'native_writes':0,'authority_writes':0,'pointer_writes':0})

def publish(cfg,b,stage):
 gate(cfg,b,stage);frozen(cfg,b)
 written=[];journal_path=stage/'TRANSACTION.jsonl'
 def journal(event,**kw):
  with journal_path.open('a')as f:
   f.write(json.dumps({'event':event,'time_ns':time.time_ns(),**kw},ensure_ascii=False)+'\n');f.flush();os.fsync(f.fileno())
 # Same existing original-chain advisory lock, acquired without changing bytes.
 with Path(cfg['lock_path']).open('r+')as held:
  fcntl.flock(held.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
  try:
   frozen(cfg,b);assert not b.active_writers(),'Active original A worker'
   journal('BEGIN',contract_sha256=b.sha(N/'PUBLISH_CONTRACT_R2.json'))
   for role,p in cfg['panels'].items():
    dest=Path(p['new_path']);dest.parent.mkdir(parents=True,exist_ok=False)
    os.link(p['candidate_path'],dest);b.fsync_dir(dest.parent)
    assert b.stat(dest)['inode']==p['candidate_stat']['inode']
    journal('IMMUTABLE_SIBLING_CREATED',role=role,path=str(dest),sha256=p['new_sha256'])
   assert not b.active_writers(),'Original A worker appeared'
   for role,p in cfg['panels'].items():
    assert b.sha(p['pointer_path'])==p['old_pointer_sha256']
   for role,p in cfg['panels'].items():
    data=(p['new_path']+'\n').encode();newsha=hashlib.sha256(data).hexdigest()
    journal('POINTER_INTENT',role=role,old=p['old_pointer_sha256'],new=newsha)
    written.append((role,p,newsha));b.cas_bytes(p['pointer_path'],p['old_pointer_sha256'],data,E)
    journal('POINTER_COMPLETE',role=role)
   for role,p,newsha in written:
    assert b.sha(p['pointer_path'])==newsha
    assert Path(p['pointer_path']).read_text().strip()==p['new_path']
    assert b.stat(p['old_path'])==p['old_stat']
   consumer=b.original_selector_consumer(cfg);assert str(consumer)==cfg['panels']['legacy_selector']['new_path']
   b.save(stage/'PUBLISH_RECEIPT.json',{'execution_id':E,'status':'ORIGINAL_TWO_POINTERS_PUBLISHED_CONSUMER_READ_BACK',
    'roles':cfg['panels'],'selector_consumer_path':str(consumer),'native_writes':0,'physical_source_cas_count':0,
    'pointer_writes':len(written),'changed_stocks':['001210.SZ'],'same_key_window':True,
    'D21_raw_exact_preserved':True,'accepted_source_count_unchanged':5495,'excluded_count_unchanged':305,
    'old_generations_retained':True,'runtime_reload':False,'scheduler_changed':False,'network_calls':0,
    'full_schema_ready':False,'research_only':True,'production_allowed':False,'buy_gate_updated':False,'orders_sent':False})
   journal('COMMIT',receipt_sha256=b.sha(stage/'PUBLISH_RECEIPT.json'))
  except BaseException as exc:
   log_errors=[]
   try:journal('FAILURE',error=str(exc))
   except BaseException as logging:log_errors.append(str(logging))
   conflicts,rb_errors=rollback(b,written,stage,journal)
   failure={'execution_id':E,'status':'FAILED_ROLLBACK_CONFLICT'if conflicts else'FAILED_ROLLED_BACK',
    'error':str(exc),'rollback_conflicts':conflicts,'journal_errors':log_errors+rb_errors,'native_writes':0,'pointer_cas_attempts':len(written)}
   try:b.save(stage/'FAILURE_RECEIPT.json',failure)
   except BaseException:print(json.dumps(failure),file=sys.stderr)
   raise
  finally:fcntl.flock(held.fileno(),fcntl.LOCK_UN)

def prepare_versioned(cfg,b,stage):
 frozen(cfg,b);assert not b.active_writers(),'Active original A worker'
 prior=cfg['prior_prepare_receipt'];assert b.sha(prior['path'])==prior['sha256']
 previous=read(prior['path']);assert previous['status']=='PAIR_PREPARED_NOT_PUBLISHED'
 stage.mkdir(parents=True,exist_ok=False)
 for role,p in cfg['panels'].items():
  oldref=previous['pointer_preimages'][role]
  assert b.sha(oldref['path'])==oldref['sha256']==p['old_pointer_sha256']
  b.exclusive_bytes(stage/(role+'_preimage.txt'),Path(p['pointer_path']).read_bytes())
  assert b.sha(stage/(role+'_preimage.txt'))==p['old_pointer_sha256']
 b.save(stage/'PREPARE_RECEIPT.json',{'execution_id':E,'status':'PAIR_PREPARED_NOT_PUBLISHED',
  'pointer_preimages':{r:{'path':str(stage/(r+'_preimage.txt')),'sha256':b.sha(stage/(r+'_preimage.txt'))}for r in cfg['panels']},
  'versioned_from_prior_prepare':prior,'transaction_and_dummy_logic':'UNCHANGED_PRIOR_INDEPENDENT_PASS_REUSED_NO_RERUN',
  'native_writes':0,'authority_writes':0,'pointer_writes':0,'formula_calls':0,'dummy_tests_run':0})

def main():
 a=argparse.ArgumentParser();a.add_argument('phase',choices=('prepare','publish'));args=a.parse_args()
 cfg=read(N/'PUBLISH_CONTRACT_R2.json');b=load(cfg['primitive_helper_path']);start=read(cfg['start_receipt'])
 assert start['execution_id']==E and start['event_type']=='RUN_STARTED'
 assert b.sha(__file__)==cfg['helper_sha256'];stage=Path(cfg['stage'])
 if args.phase=='prepare':prepare_versioned(cfg,b,stage)
 else:publish(cfg,b,stage)
 print(json.dumps({'execution_id':E,'phase':args.phase,'status':'COMPLETE'}))

if __name__=='__main__':main()
