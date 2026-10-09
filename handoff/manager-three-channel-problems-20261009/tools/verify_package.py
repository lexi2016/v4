#!/usr/bin/env python3
"""Verify this package directory or ZIP without network access."""
import hashlib,json,sys,zipfile
from pathlib import Path,PurePosixPath
def h(data): return hashlib.sha256(data).hexdigest()
def verify(target):
 target=Path(target)
 if target.is_dir():
  manifest=json.loads((target/'package/manifest.json').read_text(encoding='utf-8'))
  read=lambda rel:(target/('package/PACKAGE_SHA256SUMS.txt' if rel=='PACKAGE_SHA256SUMS.txt' else rel)).read_bytes()
  names=set()
  for p in target.rglob('*'):
   if not p.is_file() or p.name=='SCOPE.md' or p.suffix=='.zip': continue
   rel=p.relative_to(target).as_posix()
   if rel=='package/PACKAGE_SHA256SUMS.txt': rel='PACKAGE_SHA256SUMS.txt'
   names.add(rel)
  archive=None
 else:
  archive=zipfile.ZipFile(target)
  manifest=json.loads(archive.read('package/manifest.json').decode('utf-8'))
  read=archive.read
  names=set(archive.namelist())
 expected={r['path']:r['sha256'] for r in manifest['files']}
 errors=[]
 if names != set(expected)|{'package/manifest.json','PACKAGE_SHA256SUMS.txt'}: errors.append('member inventory differs')
 for rel,digest in expected.items():
  pure=PurePosixPath(rel)
  if pure.is_absolute() or '..' in pure.parts: errors.append('unsafe path '+rel); continue
  try:
   if h(read(rel))!=digest: errors.append('SHA mismatch '+rel)
  except Exception: errors.append('missing '+rel)
 try: sums=read('PACKAGE_SHA256SUMS.txt').decode('utf-8').splitlines()
 except Exception: sums=[]
 listed={}
 for line in sums:
  parts=line.split('  ',1)
  if len(parts)==2: listed[parts[1]]=parts[0]
 if set(listed)!=set(expected)|{'package/manifest.json'}: errors.append('checksum inventory differs')
 for rel,digest in listed.items():
  try:
   if h(read(rel))!=digest: errors.append('checksum mismatch '+rel)
  except Exception: errors.append('missing checksum member '+rel)
 if archive: archive.close()
 print(json.dumps({'status':'FAIL' if errors else 'PASS','package_id':manifest.get('package_id'),'files':len(expected),'errors':errors},ensure_ascii=False,sort_keys=True))
 return 1 if errors else 0
if __name__=='__main__':
 target=sys.argv[1] if len(sys.argv)>1 else Path(__file__).resolve().parents[1]/'three_channel_problem_package_20261009.zip'
 raise SystemExit(verify(target))
