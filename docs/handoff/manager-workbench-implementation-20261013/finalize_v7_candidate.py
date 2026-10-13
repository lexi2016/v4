"""After independent narrow PASS, update only capture_binding and V7 identities."""
from pathlib import Path
import argparse,hashlib,json,sys
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2];sys.path.insert(0,str(ROOT))
from ops.api_release_integration import inventory_tree,inventory_digest,_diff_proof,shared_api_release_lock
sha=lambda b:hashlib.sha256(b).hexdigest()

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--review-receipt',required=True);p.add_argument('--review-sha256',required=True);a=p.parse_args()
 review=Path(a.review_receipt).read_bytes()
 if sha(review)!=a.review_sha256:raise ValueError('INDEPENDENT_RECEIPT_SHA_MISMATCH')
 # The parent supplies the already independently accepted receipt identity.
 d=HERE/'deployment-deltas';rp=d/'isolated-candidate-build-v7-receipt.json';r=json.loads(rp.read_text())
 before=rp.read_bytes();rel='v4/manager_workbench/inputs/capture_binding.py';raw=(ROOT/rel).read_bytes()
 api=Path(r['candidate_api']);scheduler=Path(r['candidate_scheduler'])
 with shared_api_release_lock(Path('/Users/lexi/Library/LaunchAgents/com.lexi.v35.api-only.plist')):
  for app in (api,scheduler):
   m=json.loads((app.parent/'release-manifest.json').read_text())
   if inventory_tree(app)!=m['application_inventory']['entries']:raise ValueError('CANDIDATE_DRIFT_BEFORE_NARROW_UPDATE')
  for entries,base in [(r['api_delta_entries'],Path(r['base']['api']['app_root'])),(r['scheduler_delta_entries'],Path(r['base']['scheduler']['app_root']))]:
   e=next(e for e in entries if e['path']==rel);e['after_sha256']=sha(raw)
   if 'unified_diff_sha256' in e:
    e['unified_diff_sha256'],e['unified_diff_hunk_count']=_diff_proof((base/rel).read_bytes(),raw) if (base/rel).exists() else (None,None)
  for app in (api,scheduler):(app/rel).write_bytes(raw)
  (d/'api-delta-source-v7-final'/rel).write_bytes(raw)
  delta=d/'api-integration-delta-v7-receipt.json';value=json.loads(delta.read_text());value['entries']=r['api_delta_entries'];delta.write_text(json.dumps(value,indent=2)+'\n')
  (api.parent/'api-integration-delta-receipt.json').write_bytes(delta.read_bytes())
  r['api_build']['delta_entries']=r['api_delta_entries'];r['api_build']['delta_receipt_sha256']=sha(delta.read_bytes())
  for role,app in [('api',api),('scheduler',scheduler)]:
   mp=app.parent/'release-manifest.json';m=json.loads(mp.read_text());items=inventory_tree(app)
   m['application_inventory']=dict(entries=items,aggregate_sha256=inventory_digest(items),entry_count=len(items))
   if role=='api':m['api_integration']=r['api_build']
   else:m['scheduler_integration']['delta_entries']=r['scheduler_delta_entries']
   mp.write_text(json.dumps(m,indent=2)+'\n');r[role+'_manifest_sha256']=sha(mp.read_bytes())
  for item in r['canonical_sync']:
   if item['path']==rel:item['after_sha256']=sha(raw)
  r['narrow_review']=dict(path=a.review_receipt,sha256=a.review_sha256,source_sha256=sha(raw))
  (HERE/'integration-v7-build-before-narrow-update.json').write_bytes(before)
  rp.write_text(json.dumps(r,indent=2)+'\n')
 print(json.dumps(dict(status='V7_NARROW_UPDATE_PREPARED',source_sha256=sha(raw),api_manifest_sha256=r['api_manifest_sha256'],scheduler_manifest_sha256=r['scheduler_manifest_sha256'])))
if __name__=='__main__':main()
