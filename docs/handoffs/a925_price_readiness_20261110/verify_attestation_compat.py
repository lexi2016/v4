"""Exact 6->7 historical-owner bound, real manifest checks on synthetic fixtures."""
from pathlib import Path
from datetime import datetime
from unittest.mock import patch
import difflib
import hashlib
import json
import os
import subprocess
import sys
import tempfile

from verify_isolated import HERE, STAGE, mount, sha

RELATIVE='infrastructure/manager_input_attestation.py'


def probe(mode):
    import infrastructure.manager_input_attestation as subject
    with tempfile.TemporaryDirectory(prefix='owner-bound-',dir=HERE/'.verification') as tmp:
        root=Path(tmp);current=root/'current/app';current.mkdir(parents=True)
        (current/'ops').mkdir();(current/'ops/run_hourly_research.py').write_bytes(b'current fixture')
        stage=root/'stage/app';stage.mkdir(parents=True)
        data=root/'data';data.mkdir();ledger=root/'ledger';ledger.mkdir()
        bindings=[]
        for n in range(8):
            app=root/f'owner{n}/app';app.mkdir(parents=True)
            entries=[]
            for relative in subject._MAIN_RESEARCH_FILES:
                path=app/relative;path.parent.mkdir(parents=True,exist_ok=True)
                content=f'owner {n} synthetic {relative}'.encode();path.write_bytes(content)
                entries.append(dict(path=relative,kind='file',size=len(content),sha256=subject.digest(content)))
            manifest=dict(schema_version='v4.runtime_graph_repair_release.v1',app_root=str(app),release_id=f'fixture{n}',
                RESEARCH_ONLY=True,production_allowed=False,buy_gate_updated=False,orders_sent=False,
                application_inventory=dict(entries=entries,entry_count=len(entries),
                    aggregate_sha256=subject.digest(json.dumps(entries,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode())))
            raw=subject.encoded(manifest);(app.parent/'release-manifest.json').write_bytes(raw)
            bindings.append(dict(app_root=str(app),release_id=f'fixture{n}',manifest_sha256=subject.digest(raw)))
        def run(count, alteration=None):
            selected=[dict(binding) for binding in bindings[:count]]
            if alteration=='sha':selected[-1]['manifest_sha256']='0'*64
            if alteration=='path':selected[-1]['app_root']='relative/app'
            if alteration=='duplicate':selected[-1]=dict(selected[0])
            (stage/'stage_center_tick_config.json').write_text(json.dumps({'research_historical_owner_bindings':selected}))
            owner=Path(bindings[count-1]['app_root'])
            record=data/'research/hourly/publication/live/20261110/1000.json';record.parent.mkdir(parents=True,exist_ok=True)
            record.write_text(json.dumps({'materializer_sha256':subject.digest((owner/'ops/run_hourly_research.py').read_bytes())}))
            incoming=data/'research/incoming/20261110/1000.json.publication.json';incoming.parent.mkdir(parents=True,exist_ok=True)
            incoming.write_text(json.dumps({'owner_code':{'publication_writer_sha256':subject.digest((owner/RELATIVE).read_bytes())}}))
            with patch.object(subject,'trusted_research_owner',return_value=(current,ledger,('fixture_stage_pin',))), \
                 patch.object(subject,'read_hourly_attestation',return_value={'fixture':'success'}) as witness, \
                 patch.object(subject,'_release_manifest',wraps=subject._release_manifest) as verifier:
                try:
                    publication,evidence=subject.read_stage_hourly_attestation(stage_app=stage,data_root=data,date='20261110',
                        slot='1000',mode='LIVE',as_of=datetime.fromisoformat('2026-11-10T10:00:01+08:00'))
                except subject.PublicationError as error:
                    return dict(status='REJECTED',error=str(error),manifest_checks=verifier.call_count)
                assert publication=={'fixture':'success'} and witness.call_args.kwargs['owner_root']==owner
                assert verifier.call_count==count
                return dict(status='PARSED_AND_SELECTED',manifest_checks=verifier.call_count,
                    selected_owner=f'fixture{count-1}',historical_evidence_present=f'v4_research_historical_owner_release_id=fixture{count-1}' in evidence)
        results={str(count):run(count) for count in (6,7,8)}
        assert results['6']['status']=='PARSED_AND_SELECTED'
        assert results['7']['status']==('REJECTED' if mode=='before' else 'PARSED_AND_SELECTED')
        if mode=='before':assert results['7']['error']=='HOURLY_PROVENANCE_ALLOWLIST_INVALID'
        assert results['8']==dict(status='REJECTED',error='HOURLY_PROVENANCE_ALLOWLIST_INVALID',manifest_checks=0)
        if mode=='after':
            for alteration,error in [('sha','RESEARCH_RELEASE_MANIFEST_SHA_MISMATCH'),('path','RESEARCH_OWNER_ROOT_INVALID'),
                                     ('duplicate','HOURLY_PROVENANCE_ALLOWLIST_INVALID')]:
                result=run(7,alteration);assert result['status']=='REJECTED' and result['error']==error
                results['invalid_'+alteration]=result
        (HERE/f'STAGE_ATTESTATION_{mode.upper()}_RESULT.json').write_text(json.dumps(results,indent=2)+'\n')
        print(json.dumps(results,indent=2))


def main():
    if len(sys.argv)>1:return probe(sys.argv[1])
    source=STAGE/RELATIVE;before=source.read_text();before_sha=sha(source)
    needle='if not isinstance(historical, list) or len(historical) > 6:'
    assert before.count(needle)==1
    after=before.replace(needle,needle.replace('> 6','> 7'))
    (HERE/'stage_attestation_compat.patch').write_text(''.join(difflib.unified_diff(before.splitlines(True),after.splitlines(True),
        fromfile='a/'+RELATIVE,tofile='b/'+RELATIVE)))
    metadata=dict(source=str(source),before_sha256=before_sha,after_sha256=hashlib.sha256(after.encode()).hexdigest(),
                  delta='historical owner maximum 6 to 7 only',repo_sha256=sha(HERE.parents[2]/RELATIVE),
                  fixture_scope='synthetic exact manifests/SHA/path checks; trusted current Stage pin and final publication witness stubbed')
    (HERE/'STAGE_ATTESTATION_COMPAT_SHA.json').write_text(json.dumps(metadata,indent=2)+'\n')
    for mode,content in [('before',before),('after',after)]:
        overlay=HERE/f'.verification/attestation-{mode}'
        mount(STAGE,overlay,{RELATIVE:content.encode()})
        subprocess.run([sys.executable,str(Path(__file__).resolve()),mode],cwd=overlay,
            env=dict(os.environ,PYTHONPATH=str(overlay),PYTHONDONTWRITEBYTECODE='1'),check=True)
    assert sha(source)==before_sha
    print('OWNER_BOUND_PASS: old6 preserved; 7 RED->GREEN; 8 rejected; real manifest SHA/path/duplicate guards intact')


if __name__=='__main__':main()
