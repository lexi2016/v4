"""Root-only stage/CAS install adapter; does not stop/start any service."""
from pathlib import Path
import argparse,fcntl,hashlib,importlib.util,json,os,plistlib,shutil,subprocess
E=Path('/Users/lexi/Desktop/学习/因子工厂/research/a_daily_1530_20261029_r1')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 p=argparse.ArgumentParser();p.add_argument('action',choices=['stage','install','rollback']);p.add_argument('--review',type=Path,required=True);p.add_argument('--review-sha256',required=True);a=p.parse_args()
 plan=json.loads((E/'CONTROL_PLAN.json').read_text());assert sha(a.review)==a.review_sha256,'REVIEW_DRIFT'
 review=json.loads(a.review.read_text());assert review.get('verdict')=='PASS' and review.get('control_plan_sha256')==sha(E/'CONTROL_PLAN.json'),'SCOPED_REVIEW_REQUIRED'
 lock=plan['main_control_lock'];fd=os.open(lock['path'],os.O_RDWR|os.O_NOFOLLOW)
 try:
  st=os.fstat(fd);assert [st.st_dev,st.st_ino]==[lock['device'],lock['inode']],'MAIN_LOCK_INODE_DRIFT';fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
  marker=Path(lock['marker']);assert sha(marker)==lock['marker_sha256'],'MAIN_MARKER_DRIFT';m=json.loads(marker.read_text());assert m.get('active') is False and m.get('phase')=='DONE','PRIOR_MAIN_OWNER_ACTIVE'
  source=Path(plan['candidate_root']);target=Path(plan['durable_root']);manifest=E/'durable_release-manifest.json'
  assert sha(manifest)==plan['manifest_sha256'],'MANIFEST_DRIFT'
  for item in json.loads(manifest.read_text())['application_inventory']['entries']:
   f=source/'app'/item['path'];assert item['kind']=='file' and not f.is_symlink() and sha(f)==item['sha256'],('SOURCE_DRIFT',str(f))
  assert sha(Path(plan['operator']))==plan['operator_sha256'],'OPERATOR_DRIFT'
  spec=importlib.util.spec_from_file_location('existing_operator',plan['operator']);op=importlib.util.module_from_spec(spec);spec.loader.exec_module(op)
  row=plan['operation'];assert sha(Path(row['template_path']))==row['template_sha256'],'TEMPLATE_DRIFT'
  if a.action=='stage':
   assert sha(Path(row['plist']))==row['before_sha256'],'ACTIVE_PLIST_CAS_DRIFT'
   assert not target.exists(),'DURABLE_ROOT_ALREADY_EXISTS';tmp=target.with_name('.'+target.name+'.staging-'+str(os.getpid()));assert not tmp.exists();tmp.mkdir()
   subprocess.run(['/bin/cp','-cR',str(source/'app'),str(tmp/'app')],check=True)
   shutil.copy2(manifest,tmp/'release-manifest.json')
   for item in json.loads(manifest.read_text())['application_inventory']['entries']:
    assert sha(tmp/'app'/item['path'])==item['sha256'],'STAGE_DRIFT'
   assert not target.exists();tmp.rename(target);print('STAGED_NOT_ACTIVATED')
  else:
   assert sha(target/'release-manifest.json')==plan['manifest_sha256'],'DURABLE_MANIFEST_DRIFT'
   for item in json.loads(manifest.read_text())['application_inventory']['entries']:
    f=target/'app'/item['path'];assert not f.is_symlink() and sha(f)==item['sha256'],'DURABLE_SOURCE_DRIFT'
   # Original reviewed operator enforces unloaded label and before/after CAS.
   print(op.install_plist(row,rollback=a.action=='rollback'))
 finally:os.close(fd)
if __name__=='__main__':main()
