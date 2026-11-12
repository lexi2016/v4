"""Inspect supplied original Par continuations without deriving native state."""
import argparse,gzip,hashlib,json
from pathlib import Path


def audit(root,out):
    records=[]
    for path in sorted(root.rglob('continuation.json.gz')):
        blob=path.read_bytes();doc=json.loads(gzip.decompress(blob));component=doc.get('component109',{})
        native=component.get('native_latest',{});state51=doc.get('state51',{})
        absent=[k for k in ('ema10_layer1','ema10_layer2','k_unrounded','d_unrounded','brick_sma4','brick_sma6_1','brick_sma6_2','raw_prefix','native_intermediate_sequences') if k not in component]
        records.append(dict(path=str(path),sha256=hashlib.sha256(blob).hexdigest(),symbol=doc['symbol'],asof=doc['asof'],
          schema=doc['schema'],component_schema=component.get('schema'),component_keys=sorted(component),
          native_latest_keys=sorted(native),native_prefix_required=component.get('native_prefix_required'),
          source_prefix_copied=component.get('source_prefix_copied'),absent_native_state_keys=absent,
          absence_scope='Explicit component top-level and native_latest keys only; no state inferred from output fields.',
          decimal51_contract=state51.get('decimal_contract'),decimal51_schema=state51.get('schema'),
          history_refs=doc.get('history_refs'),original_pins=component.get('original_pins'),
          production_allowed=doc.get('production_allowed'),historical_PIT=doc.get('historical_PIT'),
          conclusion='ORIGINAL_COMPONENT109_REQUIRES_NATIVE_PREFIX; DECIMAL51_NOT_NATIVE_FLOAT64_STATE'))
    result=dict(status='ORIGINAL_STATE_AUDIT_COMPLETE_SCOPED',count=len(records),records=records,
      limitations=['Original bundles retained verbatim under inputs owned by controller.','Missing native accumulators are not reconstructed from displayed values.','Binary64 primitive diagnostic PASS does not certify all109 recurrence.'])
    out.mkdir(parents=True,exist_ok=True);target=out/'ORIGINAL_PAR_STATE_AUDIT.json';target.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(dict(count=len(records),output=str(target),sha256=hashlib.sha256(target.read_bytes()).hexdigest())))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();audit(a.root,a.output)
