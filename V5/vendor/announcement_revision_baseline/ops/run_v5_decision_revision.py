#!/usr/bin/env python3
"""Immutable offline decision revisions of an already imported recovery owner."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from types import SimpleNamespace

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))
from infrastructure.owned_io import SafeRoot
from ops.run_v5_offline_analysis import OfflineAnalysisOwner, sha, verify_recovery
from ops.run_v5_private_announcement import _absolute, _no_symlink, _raw, _verify_app

SCHEMA = 'v5.announcement_decision_revision.v1'
INPUTS = ('semantic_catalog.json', 'reviewer_output.json', 'article_decisions.json')


def _parent(root, recovery_sha, product_sha, receipt_sha):
    from v4.manager_research.announcement_analysis import product_path, validate_product
    from v4.manager_research.workspace_announcements import (
        validate_owner_analysis_import_receipt, validate_registered_handoff)
    root, io, recovery, capture, catalog, terminal = verify_recovery(root, recovery_sha)
    store = SimpleNamespace(root=root)
    path = product_path(store, capture['target_trade_date'], capture['publication_date'])
    product_raw = io.read_bytes(str(path.relative_to(root)))
    product = json.loads(product_raw)
    receipt_raw = io.read_bytes(str(path.with_name('owner_import_receipt.v1.json').relative_to(root)))
    if product.get('sha256') != product_sha or sha(receipt_raw) != receipt_sha:
        raise ValueError('REVISION_PARENT_PIN_MISMATCH')
    validate_product(product, target_trade_date=capture['target_trade_date'],
                     publication_date=capture['publication_date'], catalog=catalog['catalog'])
    validate_owner_analysis_import_receipt(json.loads(receipt_raw), product)
    prefix = 'announcement_agent_runs/' + recovery['source_run_id'] + '/evidence/'
    handoff = json.loads(io.read_bytes(prefix + 'handoff_manifest.v1.json'))
    validate_registered_handoff(store, recovery['source_run_id'], handoff['sha256'], product_sha, product)
    return root, io, recovery, capture, catalog, terminal, product_raw, receipt_raw


def _input(io, root, path, expected):
    path = _absolute(path)
    _no_symlink(path)
    if not path.is_relative_to(root):
        raise ValueError('REVISION_INPUT_OUTSIDE_PARENT_ROOT')
    raw = io.read_bytes(str(path.relative_to(root)))
    if sha(raw) != expected:
        raise ValueError('REVISION_INPUT_SHA_MISMATCH')
    json.loads(raw)
    return raw


def _review_binding(revision_id, product_sha, receipt_sha, recovery_sha, run):
    return dict(revision_id=revision_id, parent_product_sha256=product_sha,
                parent_owner_receipt_file_sha256=receipt_sha,
                source_recovery_receipt_sha256=recovery_sha, source_run_id=run)


def create_revision(*, parent_root, recovery_sha256, revision_id,
                    parent_product_sha256, parent_receipt_sha256,
                    semantic_catalog, semantic_sha256, reviewer_output, reviewer_sha256,
                    decisions, decisions_sha256):
    if not isinstance(revision_id, str) or not re.fullmatch('[a-z0-9][a-z0-9_-]{0,63}', revision_id):
        raise ValueError('REVISION_ID_INVALID')
    parent = _parent(parent_root, recovery_sha256, parent_product_sha256, parent_receipt_sha256)
    root, io, recovery, capture, catalog, terminal, product_raw, receipt_raw = parent
    inputs = dict(zip(INPUTS, (
        _input(io, root, semantic_catalog, semantic_sha256),
        _input(io, root, reviewer_output, reviewer_sha256),
        _input(io, root, decisions, decisions_sha256))))
    binding = _review_binding(revision_id, parent_product_sha256, parent_receipt_sha256,
                              recovery_sha256, recovery['source_run_id'])
    reviewer = json.loads(inputs['reviewer_output.json'])
    if reviewer.get('decision_revision') != binding:
        raise ValueError('REVISION_REVIEW_BINDING_INVALID')
    from v4.manager_research.workspace_projection import digest
    document = json.loads(inputs['article_decisions.json'])
    decisions_value = document.get('article_decisions') if isinstance(document, dict) and set(document) == {'article_decisions'} else document
    if (not isinstance(decisions_value, list) or not decisions_value
            or reviewer.get('decision_status') != 'EXPLICIT_DISPOSITIONS'
            or reviewer.get('decision_payload_sha256') != digest(decisions_value)):
        raise ValueError('REVISION_EXPLICIT_DECISIONS_REVIEW_REQUIRED')
    relative = 'decision_revisions/' + revision_id
    revision_root = root / relative
    manifest = dict(schema=SCHEMA, revision_id=revision_id, parent_root=str(root),
        revision_root=str(revision_root), decision_revision=binding,
        app_manifest_sha256=_verify_app(), network_allowed=False, capture_allowed=False,
        source_files=recovery['recovered_files'],
        input_files={name: sha(raw) for name, raw in inputs.items()},
        parent_product_file_sha256=sha(product_raw))
    with io.kernel_lock('.locks/decision-revision-create.mutex', timeout=0):
        if revision_root.exists() or revision_root.is_symlink():
            raise ValueError('REVISION_ALREADY_EXISTS')
        io.ensure_directory(relative)
        target = SafeRoot(revision_root)
        # A failed initialization remains visible and cannot be silently reused.
        target.write_bytes('decision_revision.pending.json', _raw(manifest), require_absent=True)
        for name, expected in recovery['recovered_files'].items():
            raw = io.read_bytes(name)
            if sha(raw) != expected:
                raise ValueError('REVISION_SOURCE_CHANGED')
            target.write_bytes(name, raw, require_absent=True)
        for name, raw in inputs.items():
            target.write_bytes('inputs/' + name, raw, require_absent=True)
        target.write_bytes('source_recovery_receipt.json', io.read_bytes('recovery_receipt.json'), require_absent=True)
        target.write_bytes('parent_analysis.v1.json', product_raw, require_absent=True)
        target.write_bytes('parent_owner_import_receipt.v1.json', receipt_raw, require_absent=True)
        target.write_bytes('decision_revision.json', _raw(manifest), require_absent=True)
    return DecisionRevisionOwner(revision_root, sha(_raw(manifest)))


class DecisionRevisionOwner(OfflineAnalysisOwner):
    def __init__(self, root, revision_sha256):
        from v4.manager_research.store import ManagerResearchStore
        self.root = _absolute(root)
        _no_symlink(self.root)
        self.io = SafeRoot(self.root)
        self.revision_sha256 = revision_sha256
        raw = self.io.read_bytes('decision_revision.json')
        if not isinstance(revision_sha256, str) or not re.fullmatch('[0-9a-f]{64}', revision_sha256) or sha(raw) != revision_sha256:
            raise ValueError('REVISION_MANIFEST_SHA_MISMATCH')
        self.revision = json.loads(raw)
        binding = self.revision['decision_revision']
        self.recovery_sha256 = binding['source_recovery_receipt_sha256']
        self._verify_evidence()
        self.identity = dict(schema='v5.announcement_decision_revision_owner.v1', private_root=str(self.root),
            source_run_id=self.recovery['source_run_id'], revision_manifest_sha256=revision_sha256,
            app_manifest_sha256=_verify_app(), decision_revision=binding, network_allowed=False, capture_allowed=False)
        self._check_state_tree()
        self._write_once('decision_revision_owner_identity.json', _raw(self.identity))
        self.store = ManagerResearchStore(self.root)
        self.capture_enabled = False
        self.gate = self.factory = self._material_store = None

    def _verify_evidence(self):
        raw = self.io.read_bytes('decision_revision.json')
        if sha(raw) != self.revision_sha256:
            raise ValueError('REVISION_MANIFEST_SHA_MISMATCH')
        revision = json.loads(raw)
        binding = revision['decision_revision']
        parent_root = _absolute(revision['parent_root'])
        if (revision.get('schema') != SCHEMA or revision.get('revision_root') != str(self.root)
                or self.root != parent_root / 'decision_revisions' / revision['revision_id']
                or not re.fullmatch('[a-z0-9][a-z0-9_-]{0,63}', revision['revision_id'])
                or revision.get('network_allowed') is not False or revision.get('capture_allowed') is not False
                or revision.get('app_manifest_sha256') != _verify_app()):
            raise ValueError('REVISION_IDENTITY_INVALID')
        parent = _parent(parent_root, binding['source_recovery_receipt_sha256'],
                         binding['parent_product_sha256'], binding['parent_owner_receipt_file_sha256'])
        _, _, self.recovery, self.capture, self.catalog, self.terminal, product_raw, receipt_raw = parent
        expected_binding = _review_binding(revision['revision_id'], binding['parent_product_sha256'],
            binding['parent_owner_receipt_file_sha256'], binding['source_recovery_receipt_sha256'], self.recovery['source_run_id'])
        if binding != expected_binding or revision['source_files'] != self.recovery['recovered_files']:
            raise ValueError('REVISION_SOURCE_BINDING_INVALID')
        if (self.io.read_bytes('parent_analysis.v1.json') != product_raw
                or sha(product_raw) != revision['parent_product_file_sha256']
                or self.io.read_bytes('parent_owner_import_receipt.v1.json') != receipt_raw
                or sha(self.io.read_bytes('source_recovery_receipt.json')) != self.recovery_sha256):
            raise ValueError('REVISION_PARENT_ARCHIVE_CHANGED')
        for name, expected in revision['source_files'].items():
            if sha(self.io.read_bytes(name)) != expected:
                raise ValueError('REVISION_SOURCE_CHANGED')
        if set(revision['input_files']) != set(INPUTS):
            raise ValueError('REVISION_INPUT_SET_INVALID')
        for name, expected in revision['input_files'].items():
            if sha(self.io.read_bytes('inputs/' + name)) != expected:
                raise ValueError('REVISION_INPUT_CHANGED')
        reviewer = json.loads(self.io.read_bytes('inputs/reviewer_output.json'))
        if reviewer.get('decision_revision') != expected_binding:
            raise ValueError('REVISION_REVIEW_BINDING_INVALID')

    def _binding_provenance(self):
        return dict(decision_revision=self.revision['decision_revision'],
                    revision_manifest_sha256=self.revision_sha256,
                    revision_manifest_path='decision_revision.json')

    def execute(self, argv):
        forbidden = {'--semantic-catalog', '--reviewer-output', '--decisions', '--review-receipt'}
        if any(token.split('=', 1)[0] in forbidden for token in argv):
            raise ValueError('REVISION_INPUT_OVERRIDE_FORBIDDEN')
        if not argv or argv[0] not in {'prepare', 'register-handoff', 'verify', 'import', 'readback'}:
            raise ValueError('REVISION_COMMAND_FORBIDDEN')
        tokens = list(argv)
        if argv[0] in {'prepare', 'register-handoff'}:
            tokens += ['--semantic-catalog', str(self.root / 'inputs/semantic_catalog.json')]
        if argv[0] == 'register-handoff':
            tokens += ['--reviewer-output', str(self.root / 'inputs/reviewer_output.json'),
                       '--decisions', str(self.root / 'inputs/article_decisions.json')]
        return super().execute(tokens)


def main():
    def deny(event, args):
        if event in {'socket.connect', 'socket.connect_ex', 'socket.getaddrinfo', 'socket.bind',
                     'socket.sendto', 'subprocess.Popen', 'os.system'}:
            raise RuntimeError('REVISION_NETWORK_OR_PROCESS_FORBIDDEN')
    sys.addaudithook(deny)
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='mode', required=True)
    create = sub.add_parser('create')
    for flag in ('parent-root', 'recovery-sha256', 'revision-id', 'parent-product-sha256',
                 'parent-receipt-sha256', 'semantic-catalog', 'semantic-sha256', 'reviewer-output',
                 'reviewer-sha256', 'decisions', 'decisions-sha256'):
        create.add_argument('--' + flag, required=True)
    run = sub.add_parser('run')
    run.add_argument('--revision-root', required=True)
    run.add_argument('--revision-sha256', required=True)
    run.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.mode == 'create':
        values = vars(args).copy()
        values.pop('mode')
        owner = create_revision(**values)
        result = dict(status='DECISION_REVISION_CREATED', revision_root=str(owner.root),
                      revision_sha256=owner.revision_sha256, decision_revision=owner.revision['decision_revision'])
    else:
        owner = DecisionRevisionOwner(args.revision_root, args.revision_sha256)
        command = args.command[1:] if args.command[:1] == ['--'] else args.command
        result = owner.execute(command)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    main()
