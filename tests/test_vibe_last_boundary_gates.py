"""Reject invalid computed data and safety flags before any model invocation."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import pytest
from test_vibe_data_owner import DATE,make_owner
from vibe_ownership_fixtures import make_runtime,reseal_fixture


def test_nonfinite_computed_value_is_not_silently_repaired():
    from domains.research_review_generation.owned_authority import _plain
    from domains.research_review_generation._owned_io import BoundaryError
    with pytest.raises(BoundaryError):_plain({'computed':float('nan')},raw_missing=False)
    assert _plain({'raw_missing':float('nan')})=={'raw_missing':None}


def test_direct_owner_cache_must_stay_inside_owned_state(tmp_path):
    from domains.research_review_generation.owned_authority import VibeDataAuthority
    from domains.research_review_generation._owned_io import BoundaryError
    ctx,_=make_owner(tmp_path)
    sibling=tmp_path/'outside';sibling.mkdir()
    with pytest.raises(BoundaryError):
        VibeDataAuthority(state_root=ctx.state_root,cache_root=sibling,
            cache_manifest_path=ctx.state_root/'cache-inventory.json',
            cache_manifest_sha256=hashlib.sha256((ctx.state_root/'cache-inventory.json').read_bytes()).hexdigest(),
            target_date=DATE)
    assert not list(sibling.iterdir())


def test_nested_unsafe_input_refused_before_llm(tmp_path):
    from domains.research_review_generation._owned_io import BoundaryError
    runtime,raw=make_runtime(tmp_path)
    raw['functions']['get_market_facts'][1]['unexpected']={'orders_sent':True}
    runtime,_=reseal_fixture(runtime,raw)
    with pytest.raises((BoundaryError,ValueError)):
        runtime.prepare(DATE,runtime.state_root/'reviews')
    assert not runtime.quick._client.prompts and not runtime.deep._client.prompts


def test_legitimate_research_order_is_preserved(tmp_path):
    runtime,raw=make_runtime(tmp_path)
    raw['functions']['get_market_facts'][1]['feedback_matrix']['order']=['一字板','连板','首板']
    runtime,raw=reseal_fixture(runtime,raw)
    prepared=runtime.prepare(DATE,runtime.state_root/'reviews')
    assert prepared.snapshot.get_market_facts(DATE)[1]['feedback_matrix']['order']==['一字板','连板','首板']


def test_raw_publication_outside_root_cannot_be_downgraded(tmp_path):
    from domains.research_review_generation._owned_io import BoundaryError
    from domains.research_review_generation.data_core import data
    ctx,tr=make_owner(tmp_path)
    outside=tmp_path/'outside';outside.mkdir()
    (ctx.state_root/'raw').symlink_to(outside,target_is_directory=True)
    assert data.get_sentiment_data(DATE,ctx=ctx).startswith('[⚠️')
    assert not list(outside.iterdir())
    with pytest.raises(BoundaryError):ctx.assert_clean()
    before=dict(tr.calls)
    with pytest.raises(BoundaryError):ctx.ak_call('stock_zt_pool_em',date='20260911')
    assert dict(tr.calls)==before  # a known filesystem violation stops later requests


def test_approved_cache_deleted_after_open_is_fatal_not_live_fallback(tmp_path):
    from domains.research_review_generation._owned_io import BoundaryError
    name=f'cache/zt_summary/{DATE}.json'
    ctx,_=make_owner(tmp_path,prefilled={name:{'date':DATE,'schema':1,'summary':{}}})
    (ctx.cache.root/name).unlink()
    with pytest.raises(BoundaryError):ctx.cache.read_json(name)
    with pytest.raises(BoundaryError):ctx.assert_clean()
