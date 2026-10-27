"""Read-only input sentinel and immutable shadow replay; does not update production."""
import hashlib,json,datetime,os,shutil,argparse
from pathlib import Path

def safe_ancestors(p):
 p=Path(p).absolute()
 if any(q.is_symlink() for q in [p,*p.parents]):raise ValueError('SYMLINK_ANCESTOR')

def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def inputs(root,manifest,expected):
 safe_ancestors(root);safe_ancestors(manifest)
 root=Path(root).resolve();manifest=Path(manifest)
 if digest(manifest)!=expected:raise ValueError('MANIFEST_ANCHOR_MISMATCH')
 m=json.loads(manifest.read_text());found=[];seen=set()
 for rec in m['securities']:
  for kind in ('raw','qfq_candidate'):
   if kind not in rec:continue
   f=rec[kind];rel=Path(f['path']);p=root/rel
   if rel.is_absolute() or '..' in rel.parts or any((root/Path(*rel.parts[:i])).is_symlink() for i in range(1,len(rel.parts)+1)):raise ValueError('UNSAFE_PATH')
   if not p.resolve().is_relative_to(root) or str(rel) in seen:raise ValueError('UNSAFE_OR_DUPLICATE_PATH')
   seen.add(str(rel));found.append((p,rel,f))
 if not found:raise ValueError('EMPTY_INPUTS')
 return found

def check(root,manifest,expected):
 fs=inputs(root,manifest,expected)
 for p,rel,f in fs:
  if not p.is_file() or p.stat().st_size!=f['bytes'] or digest(p)!=f['sha256']:raise ValueError('MISSING_OR_CORRUPT:'+str(rel))
 return {'status':'INPUT_BYTES_VERIFIED_ONLY','files':len(fs),'manifest_sha256':expected,'production_publish':'NOT_ENABLED'}

def save_new(path,obj):
 safe_ancestors(path)
 data=json.dumps(obj,sort_keys=True,ensure_ascii=False,indent=2).encode()
 if path.exists():
  if path.read_bytes()!=data:raise ValueError('RECEIPT_CONFLICT')
  return
 # exclusive creation, never overwrite; incomplete receipt on failure blocks next run
 with path.open('xb') as f:f.write(data);f.flush();os.fsync(f.fileno())

def replay(root,manifest,expected,date,out):
 if len(date)!=8 or not date.isdigit():raise ValueError('INVALID_DATE')
 datetime.datetime.strptime(date,'%Y%m%d')
 result=check(root,manifest,expected);out=Path(out)
 if json.loads(Path(manifest).read_text()).get('source_vintage')!=date:raise ValueError('SOURCE_DATE_MISMATCH')
 safe_ancestors(out)
 for p,_,_ in inputs(root,manifest,expected):
  if p.resolve().is_relative_to(out.resolve()):raise ValueError('OUTPUT_OVERLAPS_INPUTS')
 out.mkdir(parents=True,exist_ok=True);key=date+'_'+expected
 checkpoint={'date':date,'source_manifest_sha256':expected,**result,'mode':'ISOLATED_REPLAY_NOT_MARKET_UPDATE'}
 fs=inputs(root,manifest,expected)
 for start in range(0,len(fs),100):
  entries=[{'path':str(rel),'bytes':f['bytes'],'sha256':f['sha256']} for _,rel,f in fs[start:start+100]]
  save_new(out/(key+'.batch-'+str(start//100).zfill(4)+'.json'),{'date':date,'manifest_sha256':expected,'input_bytes_verified':True,'entries':entries})
 save_new(out/(key+'.json'),checkpoint)
 return checkpoint

def restore(root,manifest,expected,dest):
 check(root,manifest,expected);dest=Path(dest);safe_ancestors(dest)
 if any(str(rel)=='RESTORE_MANIFEST.json' for _,rel,_ in inputs(root,manifest,expected)):raise ValueError('RESERVED_MANIFEST_PATH')
 dest.mkdir(parents=True,exist_ok=False)
 for p,rel,f in inputs(root,manifest,expected):
  target=dest/rel;target.parent.mkdir(parents=True,exist_ok=True)
  with p.open('rb') as src,target.open('xb') as out:shutil.copyfileobj(src,out)
 shutil.copyfile(manifest,dest/'RESTORE_MANIFEST.json')
 return check(dest,dest/'RESTORE_MANIFEST.json',expected)

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('command',choices=['check','replay','restore']);p.add_argument('--root',required=True);p.add_argument('--manifest',required=True);p.add_argument('--sha',required=True);p.add_argument('--date');p.add_argument('--out');a=p.parse_args()
 try:
  if a.command=='check':r=check(a.root,a.manifest,a.sha)
  elif a.command=='replay':r=replay(a.root,a.manifest,a.sha,a.date,a.out)
  else:r=restore(a.root,a.manifest,a.sha,a.out)
  print(json.dumps(r,ensure_ascii=False))
 except Exception as e:print(json.dumps({'status':'BLOCKED','error':type(e).__name__+': '+str(e),'production_publish':'NOT_ENABLED'}));raise SystemExit(2)
