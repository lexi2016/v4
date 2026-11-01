#!/usr/bin/env python3
"""Verify prepared API config and its real Stage child transport without collectors.

The child runs a clearly labelled fixture runner after loading the real Stage
configuration builder. It does not tick, collect, import data or acquire a
production lock. It verifies API -> config -> Stage cwd/root/PYTHONPATH and the
unchanged HK-only command. The inherited API manifest env is reported as such:
this fixed HK-only program does not consume the hourly attestation contract.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--candidate',type=Path,required=True)
parser.add_argument('--state',type=Path,required=True)
args=parser.parse_args()
receipt=json.loads((args.candidate/'candidate_receipt.json').read_bytes())
api=Path(receipt['roles']['api']['app_root']);stage=Path(receipt['roles']['stage']['app_root'])
os.environ.update(receipt['proposed_environment']['api']);sys.path.insert(0,str(api))
from infrastructure.scheduling.dispatcher import validate_release_identity
identity=validate_release_identity()
from infrastructure import manual_collection as manual
config_path=Path(os.environ['V4_MANUAL_COLLECTION_STAGE_CONFIG'])
config=json.loads(config_path.read_bytes())
base=json.loads(Path(receipt['manual_source']['path']).read_bytes())
expected=dict(base,stage_owner_root=str(stage))
assert config==expected
service=manual.ManualCollectionService(Path('/nonexistent-fixture-read-root'),stage_selection_root=config['selection_root'],stage_config_path=config_path,state_root=args.state)
assert not service.config_error and service.stage_owner_root==str(stage)
assert service.owner_identity['release_id']==receipt['roles']['stage']['release_id']
assert 'historical_markets=("HK_CONNECT",)' in manual._OWNER_PROGRAM
assert 'read_stage_hourly_attestation' not in manual._OWNER_PROGRAM and 'validate_release_identity' not in manual._OWNER_PROGRAM
shim='''
import os,json
from pathlib import Path
import stage_center.runner as owner_module
class FixtureRunner:
    def __init__(self, config): self.config=config
    def tick(self, date, now, **kwargs):
        assert kwargs['historical_backfill'] is True
        assert tuple(kwargs['historical_markets']) == ('HK_CONNECT',)
        return {'fixture_only': True, 'collector_executed': False, 'cwd': str(Path.cwd()),
            'root': os.environ['V4_APP_ROOT'], 'release_id': os.environ['V4_RELEASE_ID'],
            'pythonpath': os.environ['PYTHONPATH'], 'raw_root':str(self.config.raw_root),
            'receipt_root':str(self.config.receipt_root), 'selection_root':str(self.config.selection_root),
            'inherited_manifest_path':os.environ['V4_RELEASE_MANIFEST_PATH'],
            'inherited_manifest_sha256':os.environ['V4_RELEASE_MANIFEST_SHA256']}
owner_module.StageCenterRunner=FixtureRunner
'''
original_popen=manual.subprocess.Popen
captured={}
def fixture_popen(command,**kwargs):
    assert command==[service.stage_owner_python,'-c',manual._OWNER_PROGRAM]
    captured.update(cwd=kwargs['cwd'],root=kwargs['env']['V4_APP_ROOT'],release_id=kwargs['env']['V4_RELEASE_ID'],pythonpath=kwargs['env']['PYTHONPATH'])
    return original_popen([command[0],'-B','-c',shim+command[2]],**kwargs)
manual.subprocess.Popen=fixture_popen
job={'job_id':'f10-manual-transport-fixture','trade_date':'20261101','phase':'RECOVER'}
result=service._invoke_owner(job)
assert result['fixture_only'] is True and result['collector_executed'] is False
assert captured['root']==result['cwd']==result['root']==str(stage)
assert result['release_id']==stage.parent.name
assert result['pythonpath']==os.pathsep.join((str(stage/'upstreams'),str(stage)))
for name in ('raw_root','receipt_root','selection_root'):assert result[name]==config[name]
assert result['inherited_manifest_path']==str(api.parent/'release-manifest.json')
print(json.dumps({'status':'PASS_CONFIG_AND_REAL_CHILD_TRANSPORT_FIXTURE_ONLY',
    'api_runtime_identity':identity, 'api_manual_config_sha256':hashlib.sha256(config_path.read_bytes()).hexdigest(),
    'manual_config_changed_keys':['stage_owner_root'], 'owner_identity':service.owner_identity,
    'result':result,'no_collectors_or_production_locks':True,
    'inherited_manifest_scope':'API_ENV_UNCONSUMED_BY_FIXED_HK_ONLY_OWNER_PROGRAM',
    'natural_execution_verified':False},ensure_ascii=False,indent=2))
