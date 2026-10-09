from __future__ import annotations
import hashlib,json,os,tempfile
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parents[1]

def sha(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()

def clean(x):
    if isinstance(x,dict):return {str(k):clean(v) for k,v in x.items()}
    if isinstance(x,(list,tuple)):return [clean(v) for v in x]
    if isinstance(x,np.ndarray):return clean(x.tolist())
    if isinstance(x,(np.integer,)):return int(x)
    if isinstance(x,(float,np.floating)):return float(x) if np.isfinite(x) else None
    if isinstance(x,np.bool_):return bool(x)
    if isinstance(x,Path):return str(x)
    return x

def canonical(x):return json.dumps(clean(x),ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def digest(x):return hashlib.sha256(canonical(x)).hexdigest()
def read_json(path):return json.loads(Path(path).read_text())

def write_json(path,value,exclusive=False):
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
    if exclusive:
        with p.open('x',encoding='utf-8') as f:json.dump(clean(value),f,ensure_ascii=False,indent=2,allow_nan=False);f.write('\n')
    else:
        tmp=p.with_name(p.name+'.tmp')
        with tmp.open('w',encoding='utf-8') as f:json.dump(clean(value),f,ensure_ascii=False,indent=2,allow_nan=False);f.write('\n')
        os.replace(tmp,p)

def source_identity():
    return {str(p.relative_to(ROOT)):sha(p) for p in sorted((ROOT/'spike5').glob('*.py'))}

def safe_child(root,relative):
    r=Path(root).resolve();p=(r/relative).resolve()
    if not p.is_relative_to(r):raise ValueError('path escapes bundle')
    return p

def csv_write(df,path):
    import gzip
    with open(path,'wb') as raw:
        with gzip.GzipFile(filename='',mode='wb',fileobj=raw,mtime=0) as zipped:
            import io
            with io.TextIOWrapper(zipped,encoding='utf-8',newline='') as text:
                df.to_csv(text,index=False,float_format='%.17g')
