"""Actual authority/CLI assembly. Raw transport and final LLM SDK only are fixtures."""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import pytest
from test_vibe_data_owner import make_owner,DATE
from test_vibe_model_factory import credential_db,SdkFixture,profile
from vibe_ownership_fixtures import focus


def test_authority_preserves_full_data_functions_and_proof_chain(tmp_path):
    from domains.research_review_generation.owned_runtime import verify_owned_sources
    from domains.research_review_generation._evidence import verify_evidence
    c,tr=make_owner(tmp_path)
    manifest=Path(__import__('domains.research_review_generation.owned_runtime',fromlist=['x']).__file__).parent/'OWNED_SOURCE_MANIFEST.json'
    sha=hashlib.sha256(manifest.read_bytes()).hexdigest()
    c.cache.io.ensure_directory('reflections')
    value,source_sha=c.materialize(implementation_sha256=sha,data_as_of=DATE+'T15:05:00+08:00',assembly_config_sha256='f'*64)
    assert hashlib.sha256((c.state_root/'inputs'/f'{DATE}.json').read_bytes()).hexdigest()==source_sha
    facts=value['functions']['get_market_facts'][1]
    assert {'breadth','stats_context','day_diff','trend','theme_tree','seal_quality','loss_effect','feedback_matrix','theme_structure','event_ledger','by_board'}<=facts.keys()
    proof=verify_evidence(state_root=c.state_root,payload=value,implementation_sha256=sha,reflection_manifest=[])
    assert proof['raw_files_verified']>0 and proof['cache_files_verified']>0
    assert value['sources']['get_capital_data']['status']=='CANNOT_CONFIRM'
    before=dict(tr.calls)
    repeated,_=c.materialize(implementation_sha256=sha,data_as_of=DATE+'T15:05:00+08:00',assembly_config_sha256='f'*64)
    assert tr.calls==before and repeated==value


def config_fixture(tmp_path,*,mode='collect'):
    from test_vibe_data_owner import RawTransport
    root=tmp_path/'state';root.mkdir()
    cache=root/'data';cache.mkdir()
    inv=root/'inventory.json';inv.write_text('{"schema":"v4.vibe_cache_inventory.v1","files":{}}')
    db=credential_db(tmp_path);p,psha=profile()
    body={'schema':'v4.vibe_assembly.v1','state_root':str(root),'cache_root':str(cache),
          'cache_manifest_path':str(inv),'cache_manifest_sha256':hashlib.sha256(inv.read_bytes()).hexdigest(),
          'profile_path':str(p),'profile_sha256':psha,'credential_db':str(db),
          'data_mode':mode,'data_as_of':DATE+'T15:05:00+08:00'}
    path=tmp_path/'assembly.json';path.write_text(json.dumps(body))
    code=Path(__import__('domains.research_review_generation.owned_runtime',fromlist=['x']).__file__).parent/'OWNED_SOURCE_MANIFEST.json'
    return path,hashlib.sha256(path.read_bytes()).hexdigest(),hashlib.sha256(code.read_bytes()).hexdigest(),RawTransport(),body


def test_public_cli_duplicate_refuses_before_factory_and_raw_calls(tmp_path,capsys):
    from ops.run_research_review_generation import main
    path,pin,code,tr,config=config_fixture(tmp_path)
    root=Path(config['state_root']);(root/'reviews').mkdir();(root/'reviews'/f'{DATE}.json').write_text('{}')
    factories=[]
    def factory(**kw):factories.append(kw);return SdkFixture(**kw)
    exit_code=main(['--date',DATE,'--config',str(path),'--config-sha256',pin,'--source-manifest-sha256',code],
                   transport=tr,client_factory=factory)
    assert exit_code==2 and not tr.calls and not factories
    assert json.loads(capsys.readouterr().out)['status']=='CANNOT_CONFIRM'


def test_cli_bad_config_pin_refuses_before_side_effects(tmp_path,capsys):
    from ops.run_research_review_generation import main
    path,pin,code,tr,config=config_fixture(tmp_path)
    exit_code=main(['--date',DATE,'--config',str(path),'--config-sha256','0'*64,'--source-manifest-sha256',code],transport=tr,client_factory=SdkFixture)
    assert exit_code==2 and not tr.calls
    assert not (Path(config['state_root'])/'reviews').exists()


def test_collected_inputs_pass_original_preflight_without_fake_graph(tmp_path):
    from domains.research_review_generation._snapshot import ReviewSnapshot
    from domains.research_review_generation.vibe_core import preflight
    ctx,tr=make_owner(tmp_path)
    code=Path(__import__('domains.research_review_generation.owned_runtime',fromlist=['x']).__file__).parent/'OWNED_SOURCE_MANIFEST.json'
    value,_=ctx.materialize(implementation_sha256=hashlib.sha256(code.read_bytes()).hexdigest(),
        data_as_of=DATE+'T15:05:00+08:00',assembly_config_sha256='f'*64)
    result=preflight.check(DATE,data=ReviewSnapshot(value,DATE))
    assert result['ok'] is True,result
    assert result['missing_core']==[]
    assert '资金面' in result['missing_optional']
    (tmp_path/'authority_preflight_evidence.json').write_text(json.dumps({
        'preflight':result,'provider_counts':ctx.request_counts(),
        'raw_refs':list(ctx.records.values()),'synthetic_only':True},ensure_ascii=False,indent=2))
