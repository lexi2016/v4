"""Static graph evidence integrity, distinct source roles, and data exclusion."""
import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]/'research-panel/code-map'

def test_source_graph_digests_coverage_and_roles():
    data=json.loads((ROOT/'graph.json').read_text());assert not data['missing']
    assert len(data['records'])>=37
    roles={r['source_role'] for r in data['records']}
    assert {'TASK_SOURCE_DIRTY_AT_CAPTURE','API_CANDIDATE_NOT_RUNTIME_PROOF','MAIN_C8_INSTALLED_SOURCE_AT_CAPTURE'}<=roles
    for record in data['records']:
        value=dict(record);digest=value.pop('packaged_metadata_sha256')
        assert hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()==digest
        assert not record['parse_status'].startswith('CANNOT_CONFIRM')
    assert json.loads((ROOT/'SNAPSHOT_DRIFT.json').read_text())['status']=='NO_DRIFT_DURING_CAPTURE'

def test_each_overview_node_and_edge_links_to_exact_source_evidence():
    spec=json.loads((ROOT/'overview.json').read_text());mapping=json.loads((ROOT/'MODULES.json').read_text());records={r['source']:r for r in json.loads((ROOT/'graph.json').read_text())['records']}
    assert 8<=len(spec['components'])<=12
    for n in spec['components']:
        refs=mapping['archify_node_sources'][n['id']];assert refs
        for ref in refs:assert ref['path'] in records and ref['line']>0
    assert set(mapping['archify_edge_sources'])=={e['from']+'->'+e['to'] for e in spec['connections']}
    for filename in ['SOURCE_MANIFEST.json','MODULES.json','EXCLUSIONS.json','SANITIZATION.json','SNAPSHOT_DRIFT.json','graph.json','index.html']:
        raw=(ROOT/filename).read_text();assert '/Users/' not in raw and 'Authorization: Bearer' not in raw
    page=(ROOT/'index.html').read_text();assert 'id="search"' in page and 'node-sources' in page and '运行源码' in page
