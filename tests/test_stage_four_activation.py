"""No launchctl, network or business data: bounded rollback failure regression."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SCRIPT=Path(__file__).resolve().parents[1]/'ops/activate_stage_four_repairs.py'
spec=importlib.util.spec_from_file_location('stage_four_activation',SCRIPT)
activation=importlib.util.module_from_spec(spec);spec.loader.exec_module(activation)


class RollbackContinuationTest(unittest.TestCase):
    def run_case(self, *, conflict=False):
        with tempfile.TemporaryDirectory(prefix='stage4-rollback-test-') as directory:
            records={};raws={};events=[];attempts=[];writes=[]
            for role in ('stage','pre','api'):
                path=Path(directory)/(role+'.plist');old=(role+'-old').encode();new=(role+'-new').encode()
                path.write_bytes(b'external-api' if conflict and role=='api' else new)
                records[role]={'path':str(path)};raws[role]=(old,new)
            def unload(role,*args):
                attempts.append(role)
                if role=='api':raise RuntimeError('original API rollback failure')
            def replace(record,current,previous):
                path=Path(record['path']);self.assertEqual(path.read_bytes(),current)
                writes.append(path.stem);path.write_bytes(previous)
            def event(name,**fields):events.append({'event':name,**fields})
            with patch.object(activation,'unload',side_effect=unload), patch.object(activation,'replace',side_effect=replace), patch.object(activation,'start',return_value={'state':'restored'}):
                restored,failures=activation.restore_touched(['stage','pre','api'],records,raws,{},event)
            self.assertEqual(attempts,['pre','stage'] if conflict else ['api','pre','stage'])
            self.assertEqual(writes,['pre','stage'])
            self.assertEqual([row['role'] for row in restored],['pre','stage'])
            self.assertEqual([row['role'] for row in failures],['api'])
            self.assertIn('ROLLBACK_EXTERNAL_CAS_CONFLICT' if conflict else 'original API rollback failure',failures[0]['error'])
            self.assertEqual([(row['event'],row['role']) for row in events],[('ROLLBACK_TARGET_FAILED','api'),('ROLLBACK_TARGET_VERIFIED','pre'),('ROLLBACK_TARGET_VERIFIED','stage')])
            self.assertEqual(Path(records['api']['path']).read_bytes(),b'external-api' if conflict else raws['api'][1])
            for role in ('pre','stage'):self.assertEqual(Path(records[role]['path']).read_bytes(),raws[role][0])

    def test_api_recovery_failure_still_restores_pre_and_stage(self):self.run_case()
    def test_external_api_conflict_is_preserved_while_other_targets_restore(self):self.run_case(conflict=True)


if __name__=='__main__':unittest.main()
