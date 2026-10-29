"""Read-only identity capture using the controller's exact LC_ALL=C policy."""
import json
from pathlib import Path
import four_role_control as C

def capture_main_identity(plan):
    identity=C.Live(plan).identity(plan['main_readonly']['identity']['pid'])
    if identity is None:raise C.Stop('READONLY_MAIN_IDENTITY_UNAVAILABLE')
    return identity

if __name__=='__main__':
    plan=json.loads(C.read(Path(__file__).resolve().with_name('PLAN.json')))
    print(json.dumps(capture_main_identity(plan),ensure_ascii=False))
