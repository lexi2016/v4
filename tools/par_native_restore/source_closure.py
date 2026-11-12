"""Authenticate current original Par source closure across supplied read-only roots."""
import argparse,ast,hashlib,json
from pathlib import Path
from recovery import LATEST_SHA,DEPENDENCIES_SHA


def entry(p,expected=None):
    data=p.read_bytes();sha=hashlib.sha256(data).hexdigest()
    if expected and sha!=expected:raise ValueError('SOURCE_PIN:'+str(p))
    return dict(path=str(p),bytes=len(data),sha256=sha)


def main(a):
    latest=entry(a.latest,LATEST_SHA);deps=entry(a.dependencies,DEPENDENCIES_SHA);declared=json.loads(a.dependencies.read_bytes())['dependencies'];verified=[]
    for r in declared:
        x=entry(a.par/r['path'],r['sha256'])
        if x['bytes']!=r['bytes']:raise ValueError('SOURCE_SIZE')
        verified.append(x)
    provider=a.par/'handoff/numeric_research_repair_20261101/src/native_provider.py';tree=ast.parse(provider.read_bytes())
    node=next(n for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='REVIEWED_SOURCE_HASHES' for t in n.targets));pins=ast.literal_eval(node.value)
    native=[entry(a.par/'handoff/mac_native_dependencies_20261101/extracted/skill'/p,sha) for p,sha in pins.items()]
    result=dict(status='PINNED_CURRENT_CODE_CLOSURE_VERIFIED',latest=latest,dependency_manifest=deps,composition_dependencies=verified,native_module_dependencies=native,
      original_daily_path=dict(native_primitives='prefix_math.series(full_prefix) is invoked daily in original latest109; only109finalcomposition is latest-only.',genuine_persisted_native_primitives=False,original_latest_does_not_restore_original_missing_production_entry=True),
      mapping_version_link='All15 dependencies used by latest109 match the supplied unified109/schema/native/foundation/N/KB8 sources. Mapping applies to this pinned composition.',
      input_source_history_closure='CANNOT_CONFIRM_UNTIL_ACTUAL_PREFIX_BOUND',production_allowed=False)
    a.output.mkdir(parents=True,exist_ok=True);p=a.output/'CURRENT_SOURCE_CLOSURE.json';p.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(dict(path=str(p),sha256=hashlib.sha256(p.read_bytes()).hexdigest(),composition_files=len(verified),native_files=len(native))))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--par',type=Path,required=True);p.add_argument('--latest',type=Path,required=True);p.add_argument('--dependencies',type=Path,required=True);p.add_argument('--output',type=Path,required=True);main(p.parse_args())
