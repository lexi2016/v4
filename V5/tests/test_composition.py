import copy, tempfile, unittest, json
from pathlib import Path
from dataclasses import asdict
from test_contracts import manifest
from v5_shadow.contracts import parse_manifest
from v5_shadow.digests import canonical_bytes, sha256_json
from v5_shadow.composition import validate_composition, render_effective_config, switch_module

class CompositionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        (self.root/'.v5-shadow-root').write_text('v5.shadow-root.v1\n')
        self.value={'schema_version':'v5.composition.v1','revision':1,'modules':{'rebound_shadow':manifest()},'bindings':{'rebound_shadow':dict(authority_root=None,shadow_root=str(self.root),calendar_sha256='d'*64,source_capsule_sha256='a'*64,input_snapshot_sha256=None)}}
        self.path=self.root/'composition.json';self.path.write_bytes(canonical_bytes(self.value))
    def validate(self,value=None):
        v=value or self.value
        return validate_composition(v,{k:parse_manifest(m) for k,m in v['modules'].items()})
    def test_config_single_source(self):
        composition=self.validate()
        config=render_effective_config(composition,'rebound_shadow')
        self.assertEqual(config['module']['release_id'],'r1')
        self.assertEqual(config['binding']['source_capsule_sha256'],'a'*64)
    def test_source_and_module_identities_are_distinct(self):
        self.value["bindings"]["rebound_shadow"]["source_capsule_sha256"]="e"*64
        self.assertEqual(self.validate().bindings["rebound_shadow"].source_capsule_sha256,"e"*64)
    def test_dependency_missing(self):
        self.value['modules']['rebound_shadow']['requires']=[dict(module_id='pool',input_contract='hk.pool.v1',required_capabilities=['hk_pool.split_price_eligibility.v1'])]
        with self.assertRaisesRegex(ValueError,'INCOMPATIBLE'):self.validate()
    def test_dependency_old_capability(self):
        provider=manifest();provider.update(module_id='pool',entrypoint='unused',output_contract='hk.pool.v1',capabilities=['single_date'])
        self.value['modules']['pool']=provider
        self.value['modules']['rebound_shadow']['requires']=[dict(module_id='pool',input_contract='hk.pool.v1',required_capabilities=['hk_pool.split_price_eligibility.v1'])]
        with self.assertRaisesRegex(ValueError,'INCOMPATIBLE'):self.validate()
    def test_cas_and_rollback(self):
        sibling=manifest();sibling.update(module_id='other',entrypoint='unused',output_contract='other.v1')
        self.value['modules']['other']=sibling;self.path.write_bytes(canonical_bytes(self.value))
        old=sha256_json(self.value)
        new=switch_module(self.path,'rebound_shadow',parse_manifest(manifest('r2')),old)
        with self.assertRaisesRegex(ValueError,'STALE_COMPOSITION'):switch_module(self.path,'rebound_shadow',parse_manifest(manifest()),old)
        latest=json.loads(self.path.read_text());self.assertEqual(latest['modules']['other'],sibling)
        self.assertEqual(latest['modules']['rebound_shadow']['release_id'],'r2')
        switch_module(self.path,'rebound_shadow',parse_manifest(manifest()),new)
        self.assertEqual(json.loads(self.path.read_text())['modules']['rebound_shadow']['release_id'],'r1')
    def test_missing_marker(self):
        (self.root/'.v5-shadow-root').unlink()
        with self.assertRaisesRegex(ValueError,'SHADOW_ROOT'):self.validate()
    def test_symlink_config(self):
        link=self.root/'link.json';link.symlink_to(self.path)
        with self.assertRaises(ValueError):switch_module(link,'rebound_shadow',parse_manifest(manifest('r2')),sha256_json(self.value))
    def test_overlapping_source(self):
        self.value['bindings']['rebound_shadow']['authority_root']=str(self.root)
        with self.assertRaisesRegex(ValueError,'SOURCE_OUTPUT_OVERLAP'):self.validate()
    def test_unknown_switch_not_allowed(self):
        with self.assertRaises(ValueError):switch_module(self.path,'other',parse_manifest(manifest()),sha256_json(self.value))
if __name__=='__main__':unittest.main()
