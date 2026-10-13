"""One-call validation reuse retains all unique immutable ref checks."""
import copy
import json
import pytest
from test_capture_wiring import setup,capture_job,research_job,listing
from v4.manager_workbench.contracts import Phase,Lane
from v4.manager_workbench.inputs import capture_binding as binding
from v4.manager_workbench.inputs.capture_store import encoded,sha


def material(tmp_path):
    s,t,m,cache,clock=setup(tmp_path,[listing(1),listing(2,code='00002')])
    for extra in (None,listing(3,code='00003'),listing(4,code='00004')):
        if extra:
            clock.advance();t.rows.append(extra)
        capture_job(s,clock);research_job(s)
    ctx=s.context('20261013',Phase.INTRADAY,trigger='MANUAL',cutoff=clock(),lanes=[Lane.ANNOUNCEMENT])
    pin=binding.resolve(s.config,ctx)
    return s,ctx,pin


def test_distinct_products_validated_once_per_read_not_across_calls(tmp_path,monkeypatch):
    s,ctx,pin=material(tmp_path)
    try:
        actual=binding.validate_product;calls=[]
        def checked(config,ref,context):
            calls.append(encoded(ref));return actual(config,ref,context)
        monkeypatch.setattr(binding,'validate_product',checked)
        manifest,product=binding.read_binding(s.config,pin,ctx)
        refs={encoded(r) for r in manifest['article_material_refs'].values()}
        assert len(refs)==2 and len(manifest['article_material_refs'])==3
        assert len(product['rows'])==4
        assert len(calls)==3 and len(set(calls))==3
        binding.read_binding(s.config,pin,ctx)
        assert len(calls)==6 # No cross-call validation cache.
    finally:s.stop()


def test_bad_unique_ref_and_article_correspondence_still_rejected(tmp_path):
    s,ctx,pin=material(tmp_path)
    try:
        manifest,_=binding.read_binding(s.config,pin,ctx)
        def read_modified(value):
            raw=encoded(value);identity=sha(raw);rel=f'capture_bindings/20261013/{identity}.json'
            s.store.io.write_bytes(rel,raw,require_absent=True)
            return binding.read_binding(s.config,dict(capture_binding_relative=rel,capture_binding_sha256=identity),ctx)
        broken=copy.deepcopy(manifest)
        identity=next(iter(broken['article_material_refs']))
        broken['article_material_refs'][identity]['sha256']='0'*64
        with pytest.raises(ValueError,match='CAPTURE_BOUND_SHA_MISMATCH'):read_modified(broken)
        broken=copy.deepcopy(manifest)
        refs=list(broken['article_material_refs'].values())
        # The first older product lacks the article added in the second.
        second=next(k for k,v in broken['article_material_refs'].items() if v!=refs[0])
        broken['article_material_refs'][second]=refs[0]
        with pytest.raises(ValueError,match='CAPTURE_PRIOR_MATERIAL_IDENTITY_INVALID'):read_modified(broken)
    finally:s.stop()
