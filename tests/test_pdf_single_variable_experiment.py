"""Targeted tests for ablation identity and request deltas; no live HTTP."""
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from infrastructure import local_document_model as model, pdf_research_protocol as protocol
from infrastructure.pdf_research_identity import canonical_json
from ops import run_pdf_single_variable_experiment as experiment


class ExperimentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        (self.root/'prompt-baseline.txt').write_text(experiment.BASE_PROMPT)
        (self.root/'prompt-simplified.txt').write_text('one frozen simplified prompt')
        self.original_files = experiment.execution.SOURCE_FILES

    def tearDown(self):
        protocol.PROMPT=experiment.BASE_PROMPT
        protocol.PROTOCOL_SHA256=experiment.BASE_PROTOCOL_SHA
        model.ENABLE_THINKING=experiment.BASE_THINKING
        experiment.execution.SOURCE_FILES=self.original_files
        self.temp.cleanup()

    def envelope(self):
        return protocol.request_envelope([{'role':'system','content':protocol.PROMPT},{'role':'user','content':'same source'}])

    def test_baseline_restores_exact_protocol_and_default_request(self):
        experiment.apply_group('A',self.root)
        baseline=self.envelope()
        experiment.apply_group('D',self.root)
        experiment.apply_group('C',self.root)
        experiment.apply_group('A',self.root)
        self.assertEqual(self.envelope(),baseline)
        self.assertEqual(protocol.PROTOCOL_SHA256,experiment.BASE_PROTOCOL_SHA)

    def test_prompt_only_changes_system_message_and_honest_hash(self):
        experiment.apply_group('A',self.root);baseline=self.envelope()
        experiment.apply_group('C',self.root);candidate=self.envelope()
        self.assertEqual(experiment.changed_paths(baseline,candidate),['/messages/0/content'])
        expected=hashlib.sha256(canonical_json({'schema':protocol.SCHEMA,'prompt':protocol.PROMPT,
            'version':protocol.PROTOCOL_VERSION,'semantic_pipeline':protocol.SEMANTIC_PIPELINE_VERSION})).hexdigest()
        self.assertEqual(protocol.PROTOCOL_SHA256,expected)
        self.assertNotEqual(expected,experiment.BASE_PROTOCOL_SHA)

    def test_thinking_only_changes_switch_and_keeps_schema_decoding(self):
        experiment.apply_group('A',self.root);baseline=self.envelope()
        experiment.apply_group('D',self.root);candidate=self.envelope()
        self.assertEqual(experiment.changed_paths(baseline,candidate),['/enable_thinking'])
        self.assertEqual(candidate['temperature'],0.0)
        self.assertEqual(candidate['max_tokens'],32768)
        self.assertEqual(candidate['structured_outputs'],baseline['structured_outputs'])
        self.assertEqual(protocol.PROTOCOL_SHA256,experiment.BASE_PROTOCOL_SHA)

    def test_input_group_does_not_change_global_protocol(self):
        experiment.apply_group('A',self.root);baseline=self.envelope()
        experiment.apply_group('B',self.root)
        self.assertEqual(self.envelope(),baseline)

    def test_adapter_is_bound_once(self):
        experiment.apply_group('A',self.root)
        experiment.apply_group('D',self.root)
        self.assertEqual(experiment.execution.SOURCE_FILES.count(experiment.WRAPPER_REL),1)

    def test_immutable_artifacts_do_not_overwrite(self):
        p=self.root/'record.json';experiment.write(p,{'a':1})
        experiment.write(p,{'a':1})
        with self.assertRaisesRegex(RuntimeError,'IMMUTABLE'):experiment.write(p,{'a':2})
        self.assertEqual(p.read_bytes(),canonical_json({'a':1}))

    def test_run_stops_on_first_worker_failure_without_retry(self):
        with patch.object(experiment.subprocess,'run') as run:
            run.return_value.returncode=7
            with self.assertRaises(SystemExit) as stopped:
                experiment.run_all(self.root,self.root/'receipt.json','abc')
            self.assertEqual(stopped.exception.code,7)
            self.assertEqual(run.call_count,1)
            self.assertEqual(run.call_args.args[0][0],experiment.sys.executable)
            self.assertFalse((self.root/'run-finished.json').exists())

if __name__=='__main__':unittest.main()
