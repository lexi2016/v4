"""Materialize an isolated app from verified text files; never import/run it."""
from pathlib import Path
import argparse
import hashlib
import json
import shutil

ROOT=Path(__file__).resolve().parents[1]

def assemble(output: Path) -> None:
    if output.exists() or output.is_symlink():
        raise ValueError('OWNER_APP_OUTPUT_MUST_BE_NEW')
    sources={}
    for entry in json.loads((ROOT/'SOURCE_MANIFEST.json').read_text())['entries']:
        sources[entry['candidate_path'].removeprefix('pinned/')]=(ROOT/entry['candidate_path'],entry['sha256'])
    for entry in json.loads((ROOT/'OWNER_DEPENDENCIES.json').read_text())['entries']:
        sources[entry['app_path']]=(ROOT/entry['bundle_path'],entry['sha256'])
    for entry in json.loads((ROOT/'CANDIDATE_MANIFEST.json').read_text())['entries']:
        sources[entry['target_app_path']]=(ROOT/entry['candidate_path'],entry['sha256'])
    for rel,(path,digest) in sources.items():
        if Path(rel).is_absolute() or '..' in Path(rel).parts:
            raise ValueError('OWNER_APP_PATH_INVALID')
        if hashlib.sha256(path.read_bytes()).hexdigest()!=digest:
            raise ValueError('OWNER_APP_SOURCE_SHA_MISMATCH:'+rel)
    output.mkdir(parents=True,exist_ok=False)
    entries=[]
    for rel,(path,digest) in sorted(sources.items()):
        target=output/rel;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(path,target)
        entries.append({'path':rel,'sha256':digest})
    for package in ('ops','v4','v4/manager_research','infrastructure'):
        target=output/package/'__init__.py'
        if not target.exists():
            raw=b'# Isolated owner package namespace; no startup side effects.\n'
            target.write_bytes(raw)
            entries.append({'path':str(target.relative_to(output)),'sha256':hashlib.sha256(raw).hexdigest()})
    (output/'V5_OWNER_APP_MANIFEST.json').write_text(json.dumps({'schema':'v5.announcement_owner_app.v1','files':entries},indent=2)+'\n')

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    assemble(parser.parse_args().out)
