"""Only new control differences; no provider, service or business execution."""
from pathlib import Path
from types import SimpleNamespace
import json,os
import pytest
import controller as c

@pytest.mark.parametrize('row',[{}, {'status':'DAEMON_DISPATCH_CYCLE','minute':'old','active_children':0,'queued_slots':0},
 {'status':'DAEMON_DISPATCH_CYCLE','minute':'now','active_children':1,'queued_slots':0},
 {'status':'DAEMON_DISPATCH_CYCLE','minute':'now','active_children':0,'queued_slots':1},
 {'status':'DAEMON_DISPATCH_CYCLE','minute':'now','active_children':False,'queued_slots':0}])
def test_idle_rejects_missing_stale_busy_or_boolean(row):assert not c.cycle_idle([row],'now')

def test_latest_cycle_only():
 idle={'status':'DAEMON_DISPATCH_CYCLE','minute':'now','active_children':0,'queued_slots':0}
 assert c.cycle_idle([idle],'now')
 assert not c.cycle_idle([idle,{**idle,'queued_slots':1}],'now')

def test_descendant_walk_does_not_treat_parent_as_idle():
 rows={10:{'ppid':1},20:{'ppid':10},30:{'ppid':20},40:{'ppid':1}}
 assert c.descendants(10,rows)=={20,30}

def test_lane_busy_closes_only_acquired_fd_and_never_yields(tmp_path,monkeypatch):
 p=tmp_path/'stable.lock';fd=os.open(p,os.O_CREAT|os.O_RDWR,0o600);inode=p.stat().st_ino
 x=c.Capsule.__new__(c.Capsule);x.deployment_boundary=lambda:{'ready':True};x.ledger=SimpleNamespace(try_acquire_scheduler_lane=lambda lane:fd if lane=='A_LONG' else None)
 events=[];x.j=SimpleNamespace(record=lambda *args,**kw:events.append((args,kw)))
 def halt(t):raise RuntimeError('WAIT_CHECKPOINT')
 monkeypatch.setattr(c.time,'sleep',halt)
 with pytest.raises(RuntimeError,match='WAIT_CHECKPOINT'):
  with x.natural_idle_lanes({'pid':10}):pytest.fail('busy cannot yield')
 with pytest.raises(OSError):os.fstat(fd)
 assert p.exists() and p.stat().st_ino==inode and events[0][1]['reason']=='ORIGINAL_STABLE_LANE_BUSY'

def test_lanes_held_through_body_then_close(tmp_path):
 fds=[os.open(tmp_path/str(i),os.O_CREAT|os.O_RDWR,0o600) for i in range(2)];it=iter(fds)
 x=c.Capsule.__new__(c.Capsule);x.deployment_boundary=lambda:{'ready':True};x.ledger=SimpleNamespace(try_acquire_scheduler_lane=lambda lane:next(it));x.idle=lambda old:{'ready':True};x.j=SimpleNamespace(record=lambda *a,**k:None)
 with x.natural_idle_lanes({'pid':10}):
  for fd in fds:os.fstat(fd)
 for fd in fds:
  with pytest.raises(OSError):os.fstat(fd)

def test_busy_graph_never_bootout():
 x=c.Capsule.__new__(c.Capsule);x.p={};x.op=SimpleNamespace(op=lambda p,n:{'label':'graph'},label_state=lambda label:22);x.j=SimpleNamespace(command=lambda *a:pytest.fail('no service action'))
 with pytest.raises(c.Stop,match='BECAME_BUSY'):x.bootout('collector')

def test_unknown_bootstrap_outcome_not_repeated(tmp_path):
 p=tmp_path/'p';p.write_text('same');x=c.Capsule.__new__(c.Capsule);x.p={};x.attempted_service_actions=set()
 x.op=SimpleNamespace(op=lambda p,n:{'label':'fixed','plist':str(pfile)},label_state=lambda label:None);pfile=p
 def fail(args):raise c.Stop('COMMAND_NONZERO_OUTCOME_RECONCILE_NO_RETRY')
 x.j=SimpleNamespace(command=fail,record=lambda *a,**k:None)
 with pytest.raises(c.Stop,match='COMMAND_NONZERO'):x.bootstrap('main')
 with pytest.raises(c.Stop,match='ALREADY_ATTEMPTED'):x.bootstrap('main')

def test_foreign_rollback_plist_not_overwritten(tmp_path):
 p=tmp_path/'foreign';p.write_text('foreign');x=c.Capsule.__new__(c.Capsule);x.p={};x.graph_fd=42
 x.bootout=lambda name:None
 row={'plist':str(p),'before_sha256':'before','after_sha256':'after'}
 x.op=SimpleNamespace(op=lambda p,n:row,install_plist=lambda *a,**k:pytest.fail('no overwrite'))
 with pytest.raises(c.Stop,match='FOREIGN_PLIST'):x.rollback()
 assert p.read_text()=='foreign'

def test_exact_inventory_rejects_extra_file(tmp_path):
 p=tmp_path/'expected';p.write_text('1');expected=[{'path':'expected','bytes':1,'sha256':c.sha(p)}]
 x=c.Capsule.__new__(c.Capsule);x.exact_inventory(tmp_path,expected,[])
 (tmp_path/'extra').write_text('2')
 with pytest.raises(c.Stop,match='INVENTORY_SET'):x.exact_inventory(tmp_path,expected,[])
