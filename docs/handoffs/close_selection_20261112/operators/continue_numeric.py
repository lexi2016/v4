"""One-shot event-driven continuation of the already running batch, no schedule."""
import pathlib,json,os,select,subprocess,sys,traceback,datetime
N=pathlib.Path(__file__).resolve().parents[1]
PANEL='/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python'
MODEL='/Users/lexi/Desktop/学习/runtime/venvs/v02-parity/bin/python'
def save(name,x):(N/name).write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n')
def main():
 fd=os.open(N,os.O_RDONLY);q=select.kqueue();q.control([select.kevent(fd,filter=select.KQ_FILTER_VNODE,flags=select.KQ_EV_ADD|select.KQ_EV_CLEAR,fflags=select.KQ_NOTE_WRITE)],0,0)
 try:
  while True:
   if (N/'ENGINE_RUN_FAILURE.json').exists():raise RuntimeError('ORIGINAL_ENGINE_FAILED_PRESERVED_CHECKPOINT')
   p=json.loads((N/'ENGINE_PROGRESS.json').read_text())
   if p['status']=='FRESH_FULL_UNIVERSE_COMPLETE':break
   q.control([],1,60)
 finally:q.close();os.close(fd)
 stages=[('remaining_projection',PANEL,'project_and_ledger.py',['remaining'],'validation/REMAINING_PROJECTION.json'),('remaining_features',MODEL,'features_and_scores.py',['remaining'],'NUMERIC_COMPLETION.json'),('structure',MODEL,'structure_and_queues.py',[],'REVIEW_QUEUE.json'),('charts',PANEL,'render_review_queue.py',[],'REVIEW_CHARTS_READY.json')]
 for stage,python,script,args,done in stages:
  if (N/done).exists():continue
  command=[python,'-B',str(N/'writer'/script),*args];save('CONTINUATION_PROGRESS.json',dict(stage=stage,status='RUNNING',command=command,at=datetime.datetime.now().astimezone().isoformat()))
  with (N/'writer'/(stage+'.stdout.log')).open('x')as out,(N/'writer'/(stage+'.stderr.log')).open('x')as err:
   r=subprocess.run(command,env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1'),stdout=out,stderr=err)
  if r.returncode:raise RuntimeError('STAGE_FAILED:'+stage+':'+str(r.returncode))
 save('CONTINUATION_PROGRESS.json',dict(status='NUMERIC_STRUCTURE_AND_CHARTS_COMPLETE',at=datetime.datetime.now().astimezone().isoformat()))
if __name__=='__main__':
 try:main()
 except BaseException as e:save('CONTINUATION_FAILURE.json',dict(error=str(e),traceback=traceback.format_exc()));raise
