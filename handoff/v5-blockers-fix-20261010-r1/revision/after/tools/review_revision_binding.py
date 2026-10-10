#!/usr/bin/env python3
"""Emit a review request or inspect returned bytes; never create a reviewer or revision.

This tool checks immutable structure only. Authentic reviewer identity and the
task/transport receipt must be verified through the existing review channel.
It never supplies semantic approval and never authorizes an import.
"""
from __future__ import annotations

import argparse
from decimal import Decimal, DecimalException
import hashlib
import json
import os
from pathlib import Path
import re
import stat

REQUEST_SCHEMA = 'v5.revision_review_binding_request.v1'
REPORT_SCHEMA = 'v5.revision_review_binding_preflight.v1'
BINDING_PINS = dict(
    parent_product_sha256='e724d07b39e5b4fb3ccbb0b4536f4519b4badbfd3783cad7ee6506a7af242ad6',
    parent_owner_receipt_file_sha256='6b5907c556b35b4e4a2c8a9928889b33d314369de31a7c6a12058f352c0525d0',
    source_recovery_receipt_sha256='b7b37e5385cdb7f14edc711af3b9d4bfd708441ac1de290a24a2b086b0f37b0f',
    source_run_id='16cc60afcb089f11690430b05853114c')
FROZEN_INPUTS = dict(
    original_reviewer_file_sha256='981f89ebbcee269701ad69e4c346944f9da37cfcb1693032ca11de65c3e4eb29',
    semantic_catalog_file_sha256='ec315a9470b92869dc5db928a29e52a7d83a67fd7b53925d65e36e83bcaaf8ba',
    article_decisions_file_sha256='37607c65e2d822298fe321f8c3278acaf0e33d56f3261fa48b098b6ef2e5a10f',
    article_decisions_logical_sha256='e0094a54b123050c11870b8f1ed4a71bf768afd87ccb221605b135f846d468c8')


class InputError(ValueError):
    pass


def _hex(value, count=64):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{' + str(count) + '}', value) is not None


def make_request(binding, frozen_inputs):
    """Build a request, not a reviewer. Pins are explicit caller expectations."""
    if (not isinstance(binding, dict) or set(binding) != {'revision_id', *BINDING_PINS}
            or not isinstance(binding.get('revision_id'), str)
            or not re.fullmatch('[a-z0-9][a-z0-9_-]{0,63}', binding['revision_id'])
            or not _hex(binding.get('source_run_id'), 32)
            or any(not _hex(binding.get(key)) for key in BINDING_PINS if key != 'source_run_id')
            or not isinstance(frozen_inputs, dict) or set(frozen_inputs) != set(FROZEN_INPUTS)
            or any(not _hex(value) for value in frozen_inputs.values())):
        raise ValueError('REQUEST_INVALID')
    return dict(
        schema=REQUEST_SCHEMA, status='BLOCKED_AWAITING_ORIGINAL_REVIEWER',
        scope='IMMUTABLE_REVISION_BINDING_ONLY',
        expected_decision_revision=dict(binding), frozen_inputs=dict(frozen_inputs),
        semantic_review_performed=False, authorizes_import=False,
        return_contract=dict(
            required_artifacts=['actual_original_reviewer_output_file',
                'new_reviewer_output_file_sha256', 'actual_review_channel_identity_and_task_receipt'],
            original_fields='Preserve all existing reviewer fields; supplement decision_revision only. '
                'Additional provenance fields may be added without changing original fields.',
            provenance='Verify the actual original reviewer, request identity, channel and returned file SHA '
                'through the existing review channel; JSON fields alone do not prove authorship.',
            original_material='Reuse the frozen semantic catalog and decisions byte for byte. '
                'Do not redo the 392-article semantic review.'))


def _report(status, errors=(), **details):
    return dict(schema=REPORT_SCHEMA, status=status, scope='STRUCTURAL_BINDING_ONLY',
        error_codes=list(errors), authorship_verified=False,
        semantic_review_performed=False, authorizes_import=False,
        business_status='BLOCKED_UNTIL_AUTHENTIC_ORIGINAL_REVIEWER_RETURN_IS_VERIFIED',
        **details)


def _read_pinned(path, expected, mismatch):
    if not _hex(expected):
        raise InputError('EXPECTED_SHA_INVALID')
    path = Path(path).absolute()
    # The importer's SafeRoot remains authoritative. This helper also refuses
    # symlink inputs and non-regular files before consuming any returned bytes.
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise InputError('INPUT_SYMLINK_FORBIDDEN')
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0)
            | getattr(os, 'O_NONBLOCK', 0))
        with os.fdopen(descriptor, 'rb') as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                raise InputError('INPUT_NOT_REGULAR')
            raw = handle.read(64 * 1024 * 1024 + 1)
    except OSError as exc:
        raise InputError('INPUT_READ_FAILED') from exc
    if len(raw) > 64 * 1024 * 1024:
        raise InputError('INPUT_TOO_LARGE')
    if hashlib.sha256(raw).hexdigest() != expected:
        raise InputError(mismatch)
    return raw


def _json_object(raw, code):
    def reject_nonfinite(token):
        raise ValueError('non-standard JSON number: ' + token)

    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError('duplicate JSON key')
            value[key] = item
        return value
    try:
        value = json.loads(raw, object_pairs_hook=unique,
            parse_float=Decimal, parse_constant=reject_nonfinite)
        if not isinstance(value, dict):
            raise ValueError('JSON object required')
        return value
    except (UnicodeError, ValueError, DecimalException) as exc:
        raise InputError(code) from exc


def _same_json_value(left, right):
    """Compare JSON types and exact values, including nested decimal numbers."""
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(
            _same_json_value(value, right[key]) for key, value in left.items())
    if isinstance(left, list):
        return len(left) == len(right) and all(
            _same_json_value(a, b) for a, b in zip(left, right))
    return left == right


def inspect_review(request, *, original_reviewer, semantic_catalog, decisions,
                   reviewer_output=None, reviewer_sha256=None):
    """Read local inputs and return structural findings; perform no writes."""
    try:
        if not isinstance(request, dict) or request.get('schema') != REQUEST_SCHEMA:
            raise InputError('REQUEST_INVALID')
        binding = request.get('expected_decision_revision')
        pins = request.get('frozen_inputs')
        make_request(binding, pins)
        original = _json_object(_read_pinned(original_reviewer,
            pins['original_reviewer_file_sha256'], 'ORIGINAL_REVIEWER_SHA_MISMATCH'),
            'ORIGINAL_REVIEWER_JSON_INVALID')
        _read_pinned(semantic_catalog, pins['semantic_catalog_file_sha256'],
            'SEMANTIC_CATALOG_SHA_MISMATCH')
        # Byte identity is sufficient here; the original owner still validates
        # the normalized logical digest and all per-article gates during create/register.
        _read_pinned(decisions, pins['article_decisions_file_sha256'],
            'ARTICLE_DECISIONS_SHA_MISMATCH')
        reader = original.get('reader_identity')
        reviewer = original.get('reviewer_identity')
        if (original.get('review_conclusion') != 'PASS'
                or original.get('evidence_run_id') != binding['source_run_id']
                or original.get('decision_status') != 'EXPLICIT_DISPOSITIONS'
                or original.get('decision_payload_sha256') != pins['article_decisions_logical_sha256']
                or original.get('semantic_catalog_sha256') != pins['semantic_catalog_file_sha256']
                or not isinstance(reader, str) or not reader.strip()
                or not isinstance(reviewer, str) or not reviewer.strip() or reader == reviewer
                or 'decision_revision' in original):
            raise InputError('ORIGINAL_REVIEW_CONTRACT_INVALID')
        details = dict(expected_decision_revision=dict(binding), frozen_inputs=dict(pins),
            original_reviewer_identity=reviewer, original_reader_identity=reader,
            frozen_input_bytes_verified=True)
        if reviewer_output is None:
            return _report('BLOCKED_AWAITING_ORIGINAL_REVIEWER', **details)
        if not _hex(reviewer_sha256):
            raise InputError('RETURNED_REVIEWER_SHA_REQUIRED')
        returned = _json_object(_read_pinned(reviewer_output, reviewer_sha256,
            'RETURNED_REVIEWER_SHA_MISMATCH'), 'REVIEWER_JSON_INVALID')
        errors = []
        if not _same_json_value(returned.get('decision_revision'), binding):
            errors.append('REVISION_REVIEW_BINDING_INVALID')
        changed = sorted(key for key, value in original.items()
            if key not in returned or not _same_json_value(returned[key], value))
        if changed:
            errors.append('ORIGINAL_REVIEW_FIELDS_CHANGED')
        if errors:
            return _report('BLOCKED', errors, changed_original_fields=changed, **details)
        return _report('STRUCTURAL_BINDING_VERIFIED', reviewer_file_sha256=reviewer_sha256,
            original_reviewer_fields_unchanged=True, **details)
    except (InputError, ValueError) as exc:
        return _report('BLOCKED', [str(exc)])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    request_parser = commands.add_parser('request', help='Print a BLOCKED request; never print a reviewer')
    request_parser.add_argument('--revision-id', required=True)
    for name, default in {**BINDING_PINS, **FROZEN_INPUTS}.items():
        request_parser.add_argument('--' + name.replace('_', '-'), default=default)
    inspect_parser = commands.add_parser('inspect', help='Read and compare pinned files; never create a revision')
    for name in ('request', 'request-sha256', 'original-reviewer', 'semantic-catalog', 'decisions'):
        inspect_parser.add_argument('--' + name, required=True)
    inspect_parser.add_argument('--reviewer-output')
    inspect_parser.add_argument('--reviewer-sha256')
    args = parser.parse_args(argv)
    try:
        if args.command == 'request':
            result = make_request(dict(revision_id=args.revision_id,
                **{key: getattr(args, key) for key in BINDING_PINS}),
                {key: getattr(args, key) for key in FROZEN_INPUTS})
            code = 0
        else:
            request = _json_object(_read_pinned(args.request, args.request_sha256,
                'REQUEST_SHA_MISMATCH'), 'REQUEST_JSON_INVALID')
            result = inspect_review(request, original_reviewer=args.original_reviewer,
                semantic_catalog=args.semantic_catalog, decisions=args.decisions,
                reviewer_output=args.reviewer_output, reviewer_sha256=args.reviewer_sha256)
            code = 0 if result['status'] == 'STRUCTURAL_BINDING_VERIFIED' else 2
    except (InputError, ValueError) as exc:
        result, code = _report('BLOCKED', [str(exc)]), 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
