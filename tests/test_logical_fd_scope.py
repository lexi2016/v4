import json
from pathlib import Path
import subprocess
import sys
import pyarrow as pa
from ops import research_panel_logical as logical


def test_scoped_files_under_low_limit_and_concurrent_reads(tmp_path):
    schema=pa.schema([('ts_code',pa.string()),('trade_date',pa.int64()),('close',pa.float64())]);blocks=[]
    for n in range(280):
        p=tmp_path/f'b{n}.parquet';logical.physical.write_table(pa.Table.from_pylist([dict(ts_code='000001.SZ',trade_date=n+1,close=float(n))],schema=schema),p)
        blocks.append(logical.descriptor(p,symbols=['000001.SZ'],key_rows={'000001.SZ':[0]}))
    anchor=tmp_path/'current.parquet';anchor.write_bytes(logical.anchor_bytes(schema,blocks,rows=280))
    script=r'''
import resource,sys,os,json
from concurrent.futures import ThreadPoolExecutor
from ops import research_panel_logical as l
hard=resource.getrlimit(resource.RLIMIT_NOFILE)[1];resource.setrlimit(resource.RLIMIT_NOFILE,(64,hard))
f=l.LogicalFile(sys.argv[1]);baseline=len(os.listdir('/dev/fd'))
def read():
 t=f.read();assert len(t)==280 and sum(t['close'].to_pylist())==sum(range(280));return len(os.listdir('/dev/fd'))
read();assert sum(len(b)for b in f.iter_batches())==280
for i in range(280):
 m=f.metadata.row_group(i);assert m.num_rows==1 and m.column(1).statistics.min==i+1
it=f.iter_batches();next(it);it.close()
with ThreadPoolExecutor(max_workers=4)as pool:counts=list(pool.map(lambda _:read(),range(4)))
assert not f._files and len(os.listdir('/dev/fd'))<=baseline+2
print(json.dumps(dict(status='PASS',limit=64,blocks=280,retained_handles=len(f._files),concurrent_readers=4,observed_fd_counts=counts)))
'''
    run=subprocess.run([sys.executable,'-B','-c',script,str(anchor)],text=True,capture_output=True,timeout=40)
    assert run.returncode==0,run.stderr
    assert json.loads(run.stdout)['status']=='PASS'
