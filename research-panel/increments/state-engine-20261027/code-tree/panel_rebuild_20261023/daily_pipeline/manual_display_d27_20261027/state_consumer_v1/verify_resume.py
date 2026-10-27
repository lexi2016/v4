import consumer as C
import sys,json,time,copy,resource
calls={'step':0,'original_compute':0};t=time.monotonic()
def guard(frame,event,arg):
 if event=='call':
  if frame.f_code.co_name=='step'and frame.f_code.co_filename.endswith('/state_consumer_v1/state_engine.py'):calls['step']+=1;raise AssertionError('RESUME_MUST_NOT_STEP')
  if frame.f_code.co_name=='compute'and frame.f_code.co_filename.endswith('/formula/formula_engine.py'):calls['original_compute']+=1;raise AssertionError('RESUME_MUST_NOT_COMPUTE')
sys.setprofile(guard);c=C.Consumer(C.COMPLETED_RUN);restored=c.resume_candidates();checks=[]
for symbol in sorted(c.index):
 old=copy.deepcopy(c.index[symbol]);assert c.run_one(symbol)==old
 allrows=[];cursor=None
 while True:
  p=c.inspect(symbol,limit=177,before_date=cursor);allrows=p['rows']+allrows;cursor=p['next_before_date']
  if cursor is None:break
 assert len(allrows)==old['old_rows']+1;assert all(x['trade_date']<y['trade_date']for x,y in zip(allrows,allrows[1:]));checks.append({'symbol':symbol,'rows':len(allrows),'resume_step0':True,'same_day_reuse_exact':True})
 bad=copy.deepcopy(old);bad['source_bar_exact']['amount']+=100;c.index[symbol]=bad
 try:c.inspect(symbol);raise AssertionError('BAD_SOURCE_ACCEPTED')
 except ValueError:pass
 c.index[symbol]=old
for kwargs in ({'asof':20261026},{'limit':0},{'fields':['secrets']},{'before_date':19990101}):
 try:c.inspect('002608.SZ',**kwargs);raise AssertionError('INVALID_QUERY_ACCEPTED')
 except ValueError:pass
fresh=C.Consumer.__new__(C.Consumer);fresh.index={}
try:fresh.run_one('300053.SZ');raise AssertionError('RECOMPUTE_ACCEPTED')
except ValueError as ex:assert 'ALREADY_COMPLETED'in str(ex)
sys.setprofile(None);result={'status':'PASS_READONLY_RESUME_AND_NEGATIVE_GATES','checks':checks,'calls':calls,'source_tampering_rejected':3,'invalid_queries_rejected':4,'new_run_recompute_rejected':True,'elapsed_seconds':time.monotonic()-t,'peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'display_allowed':False,'consumer_sha256':C.sha((C.H/'consumer.py').read_bytes())};C.output(c.journal.root/'RESUME_WITH_REUSE_REVIEW_CHECK.json',result);print(json.dumps(result))
