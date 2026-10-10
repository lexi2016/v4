"""Existing publication CLI: pin the consumed run before publishing once."""
import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from v5_shadow import manager_plan
from v5_shadow.digests import canonical_bytes
from v5_shadow.module_api import _config, read_response

BASE = Path(__file__).resolve().parents[1]


class Module01SavedPublicationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='module01-publish-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        inputs = {}
        for name in ('manager', 'materials', 'us'):
            path = self.root / name
            path.mkdir()
            inputs[name] = dict(root=str(path), files={})
        output = self.root / 'plans'
        output.mkdir()
        (output / '.v5-manager-plan-root').write_text('v5.manager-plan-root.v1\n')
        self.request = dict(target_date='20261009', now='2026-10-10T10:00:00+08:00',
            action='refresh', view='dynamic', selection_date=None, announcement_date=None,
            inputs=inputs, rebound=None, manager_output_root=str(output))
        self.original_run = manager_plan.run_manager_plan
        self.saved = self.original_run(copy.deepcopy(self.request))
        self.read = dict(self.request, action='read', view='auto')
        self.request_path = self.root / 'read-request.json'
        self.request_path.write_bytes(canonical_bytes(self.read))
        self.frontend = self.root / 'built-test-frontend'
        self.frontend.mkdir()
        (self.frontend / 'index.html').write_bytes(b'<p>SYNTHETIC_PUBLISH_CLI_STATIC_INPUT</p>')
        self.publication_root = self.root / 'publication'
        spec = importlib.util.spec_from_file_location('module01_existing_publish_tool', BASE / 'tools/cloud_preview/publish_read.py')
        self.tool = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.tool)

    def argv(self, run):
        return ['publish_read.py', '--request', str(self.request_path), '--expected-run', run,
                '--out', str(self.publication_root), '--frontend-root', str(self.frontend),
                '--release-id', 'module01-synthetic']

    def test_another_real_save_after_verified_read_does_not_change_publication(self):
        calls = []
        second = []

        def read_then_advance(request):
            result = self.original_run(request)
            calls.append(copy.deepcopy(request))
            if len(calls) == 1:
                second.append(self.original_run(copy.deepcopy(self.request)))
            return result

        with patch.object(self.tool, 'run_manager_plan', read_then_advance, create=True), \
             patch.object(manager_plan, 'run_manager_plan', read_then_advance), \
             patch.object(sys, 'argv', self.argv(self.saved['readback']['run_id'])), \
             contextlib.redirect_stdout(io.StringIO()):
            try:
                self.tool.main()
            except ValueError as error:
                self.fail('The already verified saved run was not published: ' + str(error))
        self.assertEqual(len(calls), 1, 'Publishing one verified read must not read latest again')
        self.assertNotEqual(second[0]['readback']['run_id'], self.saved['readback']['run_id'])
        config = json.loads((self.publication_root / 'manager.json').read_bytes())
        config, fd = _config(config)
        try:
            record, _ = read_response(config, fd, manager_plan.ROUTE,
                                      {'date': self.read['target_date'], 'view': 'auto'})
        finally:
            import os
            os.close(fd)
        self.assertEqual(record['payload']['plan_product']['run_id'], self.saved['readback']['run_id'])
        self.assertEqual(record['payload']['plan_product']['sha256'], self.saved['readback']['plan_sha256'])
        self.assertEqual(record['payload']['workspace_plan_attempt']['run_id'], self.saved['readback']['run_id'])

    def test_wrong_expected_run_cannot_create_a_published_generation(self):
        with patch.object(sys, 'argv', self.argv('f' * 32)), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(ValueError, 'SAVED_RUN_NOT_CONSUMED'):
                self.tool.main()
        self.assertEqual(list(self.publication_root.rglob('active.json')), [])
        self.assertEqual(list(self.publication_root.rglob('generations/*.json')), [])


if __name__ == '__main__':
    unittest.main()
