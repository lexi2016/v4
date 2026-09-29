from __future__ import annotations
from typing import Any

def evaluate_retirement(e: dict[str,Any]) -> dict[str,Any]:
    blockers=[]
    if e.get('replacement_deployed') is not True: blockers.append('REPLACEMENT_NOT_DEPLOYED')
    if e.get('readback_verified') is not True: blockers.append('READBACK_NOT_VERIFIED')
    if e.get('natural_verified') is not True: blockers.append('NATURAL_ACCEPTANCE_MISSING')
    if e.get('remaining_consumers') != 0: blockers.append('REMAINING_CONSUMERS')
    if e.get('in_flight') != 0: blockers.append('IN_FLIGHT_WRITES')
    if e.get('rollback_window_closed') is not True: blockers.append('ROLLBACK_WINDOW_OPEN')
    return {'schema':'v4_migration.retirement_gate.v1','status':'BLOCKED' if blockers else 'READY_FOR_SEPARATE_RETIREMENT_AUTHORIZATION','blockers':blockers,'service_disabled':False,'old_data_deleted':False}
