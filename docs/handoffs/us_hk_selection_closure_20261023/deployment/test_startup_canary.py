"""Isolated constructor-closure and forbidden-side-effect counterexamples."""
from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest

HERE=Path(__file__).resolve().parent
SCRATCH=HERE.parents[3]/'.superpowers/sdd/2026-10-23-us-hk-selection-closure/scratch/deployment'


class StartupCanaryTests(unittest.TestCase):
    def child(self,root,code):
        prefix=f"import sys\nsys.path.insert(0,{str(HERE)!r})\nimport startup_canary as c\nfrom pathlib import Path\nroot=Path({str(root)!r})\n"
        result=subprocess.run([sys.executable,'-I','-S','-B','-c',prefix+code],text=True,capture_output=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        return result.stdout

    def test_real_constructor_path_exposes_missing_lazy_module_before_closure(self):
        with tempfile.TemporaryDirectory(prefix='rehearsal-startup-canary-',dir=SCRATCH) as temp:
            root=Path(temp);package=root/'fixture'
            for relative in ('apps','apps/api','apps/api/v35_api','v4','v4/manager_workbench'):
                path=package/relative;path.mkdir(parents=True,exist_ok=True);(path/'__init__.py').write_text('')
            (package/'v4/manager_workbench/service.py').write_text('''class ManagerService:
 def __init__(self,config):
  from .oversold_daily import OversoldDaily
  self.driver=OversoldDaily();self.config=config;self.capture_jobs=None
 def stop(self):pass
''')
            (package/'apps/api/v35_api/app.py').write_text('''from types import SimpleNamespace
from v4.manager_workbench.service import ManagerService
def create_app(**kwargs):
 return SimpleNamespace(state=SimpleNamespace(manager_workbench_service=ManagerService(kwargs['manager_workbench_config'])),routes=[])
''')
            output=self.child(root,"""
from types import SimpleNamespace
import importlib
sys.path.insert(0,str(root/'fixture'));config=SimpleNamespace(scheduled_lanes=['US_MAPPING','OVERSOLD'])
with c.constructor_boundary(root,None,[]):
 try:c.full_constructor('api',config,root)
 except ModuleNotFoundError as e:assert e.name=='v4.manager_workbench.oversold_daily'
 else:raise AssertionError('missing lazy module was hidden')
(root/'fixture/v4/manager_workbench/oversold_daily.py').write_text('class OversoldDaily:pass\\n')
importlib.invalidate_caches()
with c.constructor_boundary(root,None,[]):result=c.full_constructor('api',config,root)
assert result['constructor']=='create_app' and result['service_type']=='ManagerService'
print('missing lazy dependency RED; exact dependency closure GREEN')
""")
            self.assertIn('RED',output)

    def test_constructor_guards_block_network_jobs_processes_and_external_writes(self):
        with tempfile.TemporaryDirectory(prefix='rehearsal-startup-canary-',dir=SCRATCH) as temp:
            self.child(Path(temp),"""
import socket,threading,concurrent.futures,subprocess
blocked=[]
with c.constructor_boundary(root,None,[]):
 checks=[lambda:socket.getaddrinfo('127.0.0.1',9),lambda:threading.Thread(target=lambda:None).start(),
  lambda:subprocess.run([sys.executable,'-c','print(1)']),lambda:(root.parent/'forbidden-canary-write').write_text('bad')]
 for index,call in enumerate(checks):
  try:call()
  except (RuntimeError,c.require.__globals__['Stop']):blocked.append(index)
  else:raise AssertionError('forbidden effect escaped')
 with concurrent.futures.ThreadPoolExecutor() as pool:
  try:pool.submit(lambda:None)
  except RuntimeError:blocked.append(4)
assert blocked==list(range(5))
assert not (root.parent/'forbidden-canary-write').exists()
(root/'after-boundary').write_text('normal fixture cleanup remains possible')
""")

    def test_only_exact_cli_metadata_commands_are_allowed(self):
        with tempfile.TemporaryDirectory(prefix='rehearsal-startup-canary-',dir=SCRATCH) as temp:
            root=Path(temp);binary=root/'fake-codex';binary.write_text('#!/bin/sh\nexit 0\n');binary.chmod(0o700)
            self.child(root,"""
import subprocess
from types import SimpleNamespace
sys.modules['v4.manager_workbench.executors.local_cli']=SimpleNamespace(DISABLED_FEATURES=('web_search',))
probes=[];binary=root/'fake-codex'
with c.constructor_boundary(root,binary,probes):
 for args in (['--version'],['exec','--help'],['--disable','web_search','features','list']):
  subprocess.run([str(binary),*args],check=True)
 try:subprocess.run([str(binary),'exec','not-authorized'])
 except c.require.__globals__['Stop']:pass
 else:raise AssertionError('model command allowed')
assert len(probes)==3
""")


    def test_outbound_send_and_exec_spawn_audit_families_are_denied_without_syscalls(self):
        with tempfile.TemporaryDirectory(prefix='rehearsal-startup-canary-',dir=SCRATCH) as temp:
            self.child(Path(temp),"""
import socket,_socket
original_sends={name:getattr(socket.socket,name) for name in ('send','sendall','sendto','sendmsg','sendmsg_afalg','sendfile') if hasattr(socket.socket,name)}
# Synthetic events exercise denial before any socket/process syscall.
events=('socket.sendto','socket.sendmsg','socket.send','socket.sendall','socket.__new__',
 'os.exec','os.spawn','os.posix_spawn','os.fork','os.forkpty')
with c.constructor_boundary(root,None,[]):
 for event in events:
  try:sys.audit(event,None,[],{})
  except RuntimeError as error:assert 'STARTUP_CANARY_NETWORK_OR_PROCESS_FORBIDDEN' in str(error)
  else:raise AssertionError('unguarded event: '+event)
 # send/sendall do not emit audit events on CPython; normal socket APIs must also be denied.
 for name in ('send','sendall','sendto','sendmsg','sendmsg_afalg','sendfile'):
  method=getattr(socket.socket,name,None)
  if method is None:continue
  try:method(None,b'no syscall')
  except RuntimeError as error:assert 'STARTUP_CANARY_NETWORK_OR_PROCESS_FORBIDDEN' in str(error)
  else:raise AssertionError('unguarded socket API: '+name)
 # The native constructor emits socket.__new__ before a socket syscall.
 try:_socket.socket()
 except RuntimeError as error:assert 'socket.__new__' in str(error)
 else:raise AssertionError('native socket construction allowed')
assert all(getattr(socket.socket,name) is method for name,method in original_sends.items())
""")


if __name__=='__main__':unittest.main(verbosity=2)
