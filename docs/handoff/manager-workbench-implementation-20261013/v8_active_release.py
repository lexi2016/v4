"""Narrow compatibility for the exact independently accepted V7 pointer.
All SHA/inventory/manifest checks remain generic; new releases use matching names.
"""
from pathlib import Path
import hashlib,plistlib
import ops.api_release_integration as generic
ORIGINAL=generic.read_active_release
API=Path('/Users/lexi/Library/LaunchAgents/com.lexi.v35.api-only.plist')
PLIST_SHA='522cf4c5c4cfc25a3ef5002de03eb3b74b214e0fa20beddee3901685f3d3dea2'
MANIFEST_SHA='355c38d2933e496c1bfbbb3108a95afb54d87d3bc9066549ca2aa4feaa9de6e1'
ROOT=Path(__file__).resolve().parent/'deployment-deltas/isolated-api-candidate-v7-final'
def read_active(path,*,role='gateway'):
 try:return ORIGINAL(path,role=role)
 except ValueError as exc:
  if str(exc)!='API_RELEASE_ACTIVE_ID_ROOT_MISMATCH' or Path(path)!=API or role!='gateway':raise
 raw=API.read_bytes()
 if hashlib.sha256(raw).hexdigest()!=PLIST_SHA:raise ValueError('EXACT_V7_POINTER_REQUIRED')
 payload=plistlib.loads(raw);values=generic._plist_environment(payload)
 if payload['Label']!='com.lexi.v35.api-only' or values['V35_APP_ROOT']!=str(ROOT/'app') or values['V35_RELEASE_ID']!='manager-workbench-20261013-v7-api' or values['V35_RELEASE_MANIFEST_PATH']!=str(ROOT/'release-manifest.json') or values['V35_RELEASE_MANIFEST_SHA256']!=MANIFEST_SHA:raise ValueError('EXACT_V7_IDENTITY_REQUIRED')
 identity=generic._release_identity(release_root=ROOT,app_root=ROOT/'app',release_id=values['V35_RELEASE_ID'],manifest_path=ROOT/'release-manifest.json',manifest_sha256=MANIFEST_SHA)
 if identity['module_role']!='gateway':raise ValueError('EXACT_V7_GATEWAY_REQUIRED')
 identity.update(api_plist_path=str(API),api_plist_sha256=PLIST_SHA,identity_from_plist={k:values[k] for k in sorted(values)})
 return identity
def install():generic.read_active_release=read_active
