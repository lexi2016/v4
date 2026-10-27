from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
import fcntl,json,os
import pytest
import controller as c

def fixture(tmp_path):
 lock=tmp_path/'stable.lock';lock.write_text('original inode');marker=tmp_path/'marker.json';marker.write_text(json.dumps({'active':False,'phase':'DONE'}))
 st=lock.stat();x=c.Capsule.__new__(c.Capsule);x.p={'original_main_control_owner':{'marker':str(marker),'marker_sha256':c.sha(marker),'lock_path':str(lock),'device':st.st_dev,'inode':st.st_ino}}
 x.j=SimpleNamespace(record=lambda *a,**k:None);return x,lock,marker

def test_original_main_owner_busy_wait_does_not_replace_inode(tmp_path,monkeypatch):
 x,lock,marker=fixture(tmp_path);ino=lock.stat().st_ino;raw=marker.read_bytes();fd=os.open(lock,os.O_RDWR);fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
 def stop(_):raise RuntimeError('WAIT')
 monkeypatch.setattr(c.time,'sleep',stop)
 try:
  with pytest.raises(RuntimeError,match='WAIT'):
   with x.original_main_control_owner():pytest.fail('busy cannot yield')
 finally:os.close(fd)
 assert lock.stat().st_ino==ino and marker.read_bytes()==raw

def test_inactive_marker_required_even_if_kernel_lock_free(tmp_path):
 x,lock,marker=fixture(tmp_path);marker.write_text(json.dumps({'active':True,'phase':'DRAINING'}));x.p['original_main_control_owner']['marker_sha256']=c.sha(marker)
 with pytest.raises(c.Stop,match='NOT_CLOSED'):
  with x.original_main_control_owner():pytest.fail('cannot replace prior operation')

def test_wrong_original_lock_inode_rejected(tmp_path):
 x,lock,_=fixture(tmp_path);x.p['original_main_control_owner']['inode']+=1
 with pytest.raises(c.Stop,match='INODE_DRIFT'):
  with x.original_main_control_owner():pytest.fail('cannot use replacement lock')

def test_idle_wait_precedes_api_guard_and_guards_hold_through_body():
 events=[];x=c.Capsule.__new__(c.Capsule);x.p={'workbench_root':'/fixed'};x.j=SimpleNamespace(record=lambda *a,**k:None)
 @contextmanager
 def lanes(old):
  events.append('lane_enter')
  try:yield
  finally:events.append('lane_exit')
 @contextmanager
 def guard(**kw):
  events.append(kw['name']+'_enter')
  try:yield {}
  finally:events.append(kw['name']+'_exit')
 x.natural_idle_lanes=lanes
 def take():events.append('collector_enter');return True
 x.try_graph_collector_lock=take;x.release_graph_collector_lock=lambda:events.append('collector_exit')
 x.idle=lambda old:{'ready':True};x.op=SimpleNamespace(op=lambda p,c:{'plist':'/api.plist'})
 x.a=SimpleNamespace(announcement_flash_cutover_guard=lambda *a,**k:guard(name='announcement'),shared_api_release_lock=lambda *a,**k:guard(name='api'))
 with x.all_original_guards({'pid':1}):events.append('mutations_and_readback')
 assert events==['lane_enter','announcement_enter','api_enter','collector_enter','mutations_and_readback','collector_exit','api_exit','announcement_exit','lane_exit']


def test_original_graph_collector_busy_preserves_lock(tmp_path):
 x=c.Capsule.__new__(c.Capsule);p=tmp_path/'collector.lock';p.write_text('')
 st=p.stat();x.p={'graph_collector_lock':{'path':str(p),'device':st.st_dev,'inode':st.st_ino}};x.graph_fd=None
 fd=os.open(p,os.O_RDWR);fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
 try:assert not x.try_graph_collector_lock()
 finally:os.close(fd)
 assert p.stat().st_ino==st.st_ino and x.graph_fd is None

def test_original_graph_collector_lock_released_before_canonical_bootstrap(tmp_path):
 x=c.Capsule.__new__(c.Capsule);p=tmp_path/'collector.lock';p.write_text('');st=p.stat()
 x.p={'graph_collector_lock':{'path':str(p),'device':st.st_dev,'inode':st.st_ino}};x.graph_fd=None
 assert x.try_graph_collector_lock();fd=x.graph_fd;os.fstat(fd)
 x.release_graph_collector_lock()
 assert x.graph_fd is None and p.stat().st_ino==st.st_ino
 with pytest.raises(OSError):os.fstat(fd)
