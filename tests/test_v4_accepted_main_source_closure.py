"""Accepted Main body mapping and preserved API facade, without provider calls."""
import ast,hashlib,json
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1]


def _nodes(path):
    out={}
    for n in ast.parse(path.read_text()).body:
        if isinstance(n,(ast.FunctionDef,ast.ClassDef)):out[n.name]=n
        if isinstance(n,ast.ClassDef):
            out.update({n.name+'.'+f.name:f for f in n.body if isinstance(f,ast.FunctionDef)})
    return out


def test_frozen_accepted_main_bodies_and_retained_api_functions():
    contract=json.loads((ROOT/'contracts/v4_accepted_main_source_closure.json').read_text());cache={}
    for row in contract['accepted_body_mappings']+contract['retained_API_function_mappings']:
        if row['path'] not in cache:cache[row['path']]=_nodes(ROOT/row['path'])
        node=cache[row['path']][row['target']]
        # Work on a copy because a private Main helper intentionally shares
        # pure primitives with the unchanged API title projection.
        node=ast.parse(ast.unparse(node)).body[0];rename=row.get('normalize_names',{})
        class Normalize(ast.NodeTransformer):
            def visit_Name(self,n):n.id=rename.get(n.id,n.id);return n
            def visit_FunctionDef(self,n):n.name=rename.get(n.name,n.name);return self.generic_visit(n)
        node=Normalize().visit(node)
        assert hashlib.sha256(ast.dump(node,include_attributes=False).encode()).hexdigest()==row['ast_sha256'],(row['path'],row['target'])


def test_actual_hourly_registry_uses_accepted_heartbeat_without_provider(tmp_path,monkeypatch):
    from infrastructure.scheduling.executor_registry import FixedExecutorRegistry
    from contracts.runtime_tasks import DispatchRequest,DispatchMode
    registry=FixedExecutorRegistry(data_root=tmp_path/'data')
    monkeypatch.setattr(registry,'_run',lambda *a,**k:pytest.fail('no provider/producer before08:30'))
    result=registry._hourly_research(DispatchRequest('20261028','20261028','20261028','0700',DispatchMode.LIVE))
    assert result['status']=='SUCCEEDED' and result['no_op'] is True
    assert result['source_status']=='EXPECTED_EMPTY' and not (tmp_path/'data').exists()


def test_added_recovery_interface_fails_closed_without_writing(tmp_path):
    from infrastructure.research_store import validate_hourly_recovery_provenance,HourlyResearchStore,ResearchArchiveStore
    assert callable(HourlyResearchStore.replace) and callable(ResearchArchiveStore.replace)
    with pytest.raises(ValueError,match='recovery source identity'):
        validate_hourly_recovery_provenance(data_root=tmp_path/'data',archive_date='20261028',slot='2000',recovery_path=tmp_path/'absent.json',recovery_sha256='0'*64,recovery_payload={})
    assert not (tmp_path/'data').exists()
