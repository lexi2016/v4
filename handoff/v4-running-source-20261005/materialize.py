"""Reconstruct one exact source variant into a new review directory. No runtime data."""
from pathlib import Path
import argparse, hashlib, json, shutil

p=argparse.ArgumentParser()
p.add_argument('variant',choices=['canonical','api','stage'])
p.add_argument('destination')
a=p.parse_args()
root=Path(__file__).resolve().parent
repo=root.parents[1]
dest=Path(a.destination).resolve()
if dest.exists():raise SystemExit('Destination must not exist; no overwrite')
manifest=json.loads((root/'MANIFEST.json').read_text())
entries=[]
for shard in manifest['file_shards']:
 if shard['variant']!=a.variant:continue
 data=(root/shard['path']).read_bytes()
 if hashlib.sha256(data).hexdigest()!=shard['sha256']:raise SystemExit('Manifest shard SHA mismatch')
 entries.extend(json.loads(data)['files'])
for e in entries:
 source=repo/e['snapshot_path']
 data=source.read_bytes()
 if hashlib.sha256(data).hexdigest()!=e['sha256']:raise SystemExit('Source SHA mismatch: '+e['path'])
 rel=Path(e['path'])
 if rel.is_absolute() or '..' in rel.parts:raise SystemExit('Unsafe source path')
dest.mkdir(parents=True)
for e in entries:
 source=repo/e['snapshot_path'];target=dest/e['path']
 target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
 target.chmod(0o755 if e['mode']=='100755' else 0o644)
print(json.dumps({'variant':a.variant,'files':len(entries),'destination':str(dest),'runtime_data_present':False}))
