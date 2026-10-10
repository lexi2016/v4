"""Copy only SHA-pinned original collector source; no collection or credentials."""
import argparse,hashlib,subprocess,sys
from pathlib import Path
BASE=Path(__file__).resolve().parents[2];sys.path.insert(0,str(BASE/'src'))
from v5_shadow.cloud_us_collector import descriptor,verify
parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--out',type=Path,required=True);args=parser.parse_args()
root=args.out.absolute()
if root.exists():raise ValueError('NEW_COLLECTOR_SOURCE_ROOT_REQUIRED')
manifest=descriptor();pending=[]
for row in manifest['entries']:
    raw=subprocess.check_output(['git','-C',str(BASE.parent),'show',manifest['source_commit']+':'+row['git_path']])
    if hashlib.sha256(raw).hexdigest()!=row['sha256'] or len(raw)!=row['bytes']:raise ValueError('ORIGINAL_COLLECTOR_GIT_BYTES:'+row['path'])
    pending.append((row['path'],raw))
root.mkdir(parents=True)
for relative,raw in pending:
    p=root/relative;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
verify(root)
print('SOURCE_ONLY_VERIFIED: '+str(root)+'; no capture; '+str(len(pending))+' original files')
