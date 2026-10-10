"""Test-only clocks inside real child processes; no product flag or source edit.

Each child retains the original request, implementation hash verification and IO
boundaries. Only datetime.now for the explicitly named test seam is replaced.
Never use this harness for a live/replayed business acceptance claim.
"""
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
import subprocess
from unittest.mock import patch

CHILD = r'''
import importlib,json,sys
from datetime import datetime
from pathlib import Path
source=Path(sys.argv[1]);sys.path.insert(0,str(source.parents[1]))
module=importlib.import_module('v5_shadow.'+source.stem)
instant=datetime.fromisoformat(sys.argv[2])
class SyntheticClock(datetime):
 @classmethod
 def now(cls,tz=None):
  return instant.astimezone(tz) if tz is not None else instant.replace(tzinfo=None)
if source.stem=='hk_membership_recovery':module.datetime=SyntheticClock
elif source.stem=='manager_plan':
 import v5_shadow.manager_panel_observation as observation
 observation.datetime=SyntheticClock
else:raise RuntimeError('UNSUPPORTED_SYNTHETIC_WORKER_CLOCK')
from v5_shadow.digests import canonical_bytes
try:
 entry=module.worker if source.stem=='hk_membership_recovery' else module._assemble
 result=entry(json.loads(sys.stdin.buffer.read()))
 print(canonical_bytes(result).decode())
except Exception as error:
 print(canonical_bytes(dict(status='FAILED',reason=type(error).__name__+':'+str(error))).decode())
 raise SystemExit(1)
'''


def clock_at(instant):
    instant=datetime.fromisoformat(instant)
    class SyntheticClock(datetime):
        @classmethod
        def now(cls,tz=None):
            return instant.astimezone(tz) if tz is not None else instant.replace(tzinfo=None)
    return SyntheticClock


@contextmanager
def synthetic_worker_clock(clocks):
    original=subprocess.run
    def run(command,*args,**kwargs):
        if isinstance(command,(list,tuple)) and command:
            path=Path(str(command[-1]))
            if path.suffix=='.py' and path.stem in clocks and path.parent.name=='v5_shadow':
                command=[*command[:-1],'-c',CHILD,str(path),clocks[path.stem]]
        return original(command,*args,**kwargs)
    with patch.object(subprocess,'run',run):
        yield
