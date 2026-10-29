from pathlib import Path
from copy import deepcopy
import importlib.util,json,sys
import pytest
HERE=Path(__file__).resolve().parent
s=importlib.util.spec_from_file_location('metadata_fix_control',HERE/'control.py');M=importlib.util.module_from_spec(s);s.loader.exec_module(M)

def test_original_fd_cas_forward_inverse_and_metadata(tmp_path,monkeypatch):
 rows=[]
 for source in M.P['files']:
  row=deepcopy(source);dest=tmp_path/source['role'];dest.write_bytes(M.C.read(source['before_file']));row['plist']=str(dest);row['plist_metadata']=M.C.metadata.snapshot(dest);row['plist_metadata_sha256']=M.C.metadata.digest(row['plist_metadata']);rows.append(row)
 ops=M.Ops();ops.p={'operations':rows};monkeypatch.setattr(ops,'state',lambda role:{'loaded':False,'pid':None})
 for r in rows:ops.cas(r['role']);assert M.C.read(r['plist'])==M.C.read(r['after_file']);M.C.metadata.require(r['plist'],r['plist_metadata'])
 for r in reversed(rows):ops.cas(r['role'],reverse=True);assert M.C.read(r['plist'])==M.C.read(r['before_file']);M.C.metadata.require(r['plist'],r['plist_metadata'])

def test_no_other_actor_and_strict_expiry(monkeypatch):
 ops=M.Ops()
 for role in ['main','api','collector']:
  with pytest.raises(M.C.Stop):ops.action('bootout',role)
 monkeypatch.setattr(M.C,'handoff',lambda *a:True)
 h={'observed_epoch':M.datetime.fromisoformat('2026-10-29T14:50:00+08:00').timestamp(),'expires_epoch':M.datetime.fromisoformat('2026-10-29T14:51:00+08:00').timestamp(),'data_pins':[]}
 monkeypatch.setattr(M.time,'time',lambda:h['observed_epoch']);M.fresh(h)
 h['observed_epoch']=M.datetime.fromisoformat('2026-10-29T14:53:00+08:00').timestamp();h['expires_epoch']=M.datetime.fromisoformat('2026-10-29T14:54:00+08:00').timestamp()
 with pytest.raises(M.C.Stop,match='1454'):M.fresh(h)
