from __future__ import annotations
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

E = Path('/Users/lexi/Desktop/\u5b66\u4e60/agents\u8c03\u8bd5/V4_MANAGER_DAILY_FAILURE_R3_20261009')
PACKAGE = E / 'package'
EVIDENCE = E / 'evidence'
RECEIPT = EVIDENCE / 'validation_receipt.json'

SECRET_PATTERNS = {
    'private_key_pem': re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    'aws_access_key': re.compile(r'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b'),
    'github_token': re.compile(r'\bgh[pousr]_[A-Za-z0-9_]{20,}\b'),
    'openai_style_key': re.compile(r'\bsk-[A-Za-z0-9_-]{24,}\b'),
    'bearer_literal': re.compile(r'(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{24,}'),
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def read_json(path: Path):
    with path.open('r', encoding='utf-8') as f:
        return json.load(f)


def main() -> int:
    manifest_path = PACKAGE / 'source_manifest.json'
    manifest = read_json(manifest_path)
    files = manifest['files']
    copied = 0
    missing = []
    sha_unset = []
    problems = []
    for rec in files:
        src = Path(rec['source_root']) / rec['source_relative_path']
        rel = rec.get('package_relative_path')
        if not rec.get('available'):
            missing.append(rec['source_relative_path'])
            if rel is not None or src.exists() or rec.get('identity_status') != 'MISSING_IN_SOURCE_ROOT':
                problems.append('invalid missing record: ' + rec['source_relative_path'])
            continue
        if not rel:
            problems.append('available source has no package path: ' + rec['source_relative_path'])
            continue
        dst = PACKAGE / 'source_snapshot' / Path(rel).relative_to('source_snapshot')
        if not src.is_file() or not dst.is_file():
            problems.append('source or snapshot absent: ' + rec['source_relative_path'])
            continue
        sb, db = src.stat().st_size, dst.stat().st_size
        sh, dh = sha256(src), sha256(dst)
        if (sb, sh) != (rec.get('source_bytes'), rec.get('source_sha256')):
            problems.append('manifest source identity mismatch: ' + rec['source_relative_path'])
        if (db, dh) != (rec.get('package_bytes'), rec.get('package_sha256')):
            problems.append('manifest package identity mismatch: ' + rec['source_relative_path'])
        if (sb, sh) != (db, dh):
            problems.append('source/snapshot differ: ' + rec['source_relative_path'])
        expected = rec.get('expected_source_sha256')
        if expected and sh != expected:
            problems.append('expected source SHA mismatch: ' + rec['source_relative_path'])
        if expected is None:
            sha_unset.append(rec['source_relative_path'])
            if rec.get('identity_status') != 'EXPECTED_SHA_UNSET':
                problems.append('unset expected SHA not labeled: ' + rec['source_relative_path'])
        copied += 1

    protected = [x for x in files if x.get('role') == 'issue32_protected']
    required = {
        'apps/api/v35_api/app.py': '5d344dfe902db37f81e06d1d401e9a7e20ae910d8f7647b732ae2b3ba4f019e5',
        'apps/api/v35_api/preselection_router.py': '718d54a6c6aa8cde2871ce4dc41cbc1d825f199a57b605e4f5ec70d8c4fe19ae',
        'apps/api/v35_api/preselection_service.py': 'cbed3aa4797889051eb7bebe4b8e3240b568d72b4dfb5c20f65e914d39e48044',
    }
    observed = {r['source_relative_path']: r.get('source_sha256') for r in protected}
    if observed != required:
        problems.append('Issue32 protected path/SHA set mismatch')
    for p, digest in required.items():
        matches = [x for x in files if x.get('preserve_issue32') and x.get('source_relative_path') == p]
        if len(matches) != 1 or matches[0].get('source_sha256') != digest or matches[0].get('package_sha256') != digest:
            problems.append('Issue32 protected snapshot mismatch: ' + p)

    json_paths = sorted(list(PACKAGE.rglob('*.json')) + list(EVIDENCE.rglob('*.json')))
    json_errors = []
    for p in json_paths:
        try:
            read_json(p)
        except Exception as exc:
            json_errors.append({'path': str(p.relative_to(E)), 'error': type(exc).__name__})
    if json_errors:
        problems.append('JSON parse failures')

    secret_hits = []
    for base in (PACKAGE, EVIDENCE):
        for p in base.rglob('*'):
            if not p.is_file() or p == RECEIPT:
                continue
            try:
                text = p.read_text(encoding='utf-8')
            except (UnicodeDecodeError, OSError):
                continue
            for lineno, line in enumerate(text.splitlines(), 1):
                for name, pattern in SECRET_PATTERNS.items():
                    if pattern.search(line):
                        secret_hits.append({'path': str(p.relative_to(E)), 'line': lineno, 'rule': name})
    if secret_hits:
        problems.append('high-confidence secret pattern detected')

    acceptance_path = PACKAGE / 'acceptance.json'
    acceptance = read_json(acceptance_path)
    flags = acceptance.get('safety_flags', {})
    expected_flags = {'RESEARCH_ONLY': True, 'production_allowed': False, 'buy_gate_updated': False, 'orders_sent': False}
    if flags != expected_flags:
        problems.append('safety flags differ from required research-only values')
    acceptance['package_state'] = 'READY_FOR_INDEPENDENT_REVIEW' if not problems else 'VALIDATION_FAILED'
    checks = acceptance.setdefault('scope_checks', {})
    checks['source_snapshot_identity'] = f"{'PASS' if not problems else 'FAIL'}; {copied} copied source files checked; {len(missing)} missing source path recorded without stub; {len(sha_unset)} expected SHAs unset; {len(problems)} validation problem(s)."
    checks['machine_json_parse'] = 'PASS' if not json_errors else 'FAIL'
    checks['secret_scan'] = 'PASS' if not secret_hits else 'FAIL'
    checks['independent_package_review'] = 'PENDING'
    checks['github_sync_and_readback'] = 'PENDING_PARENT'
    acceptance_path.write_text(json.dumps(acceptance, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    package_files = []
    for p in sorted(list(PACKAGE.rglob('*')) + list(EVIDENCE.rglob('*'))):
        if p.is_file() and p != RECEIPT:
            package_files.append({'path': str(p.relative_to(E)), 'bytes': p.stat().st_size, 'sha256': sha256(p)})
    receipt = {
        'schema_version': 'v4.manager_daily_failure_r3.validation_receipt.v1',
        'validated_at_local': datetime.now().astimezone().isoformat(timespec='seconds'),
        'validator': {'path': str(Path(__file__).relative_to(E)), 'sha256': sha256(Path(__file__))},
        'result': 'PASS' if not problems else 'FAIL',
        'counts': {'manifest_records': len(files), 'copied_source_files_checked': copied, 'missing_source_paths': missing, 'expected_sha_unset_paths': sha_unset, 'json_files_parsed': len(json_paths), 'secret_matches': len(secret_hits)},
        'checks': {'source_and_snapshot_bytes_sha256': not any(any(token in p for token in ('source', 'snapshot', 'Issue32')) for p in problems), 'json_parse': not json_errors, 'issue32_protected_shas': observed == required, 'research_only_flags': flags == expected_flags, 'high_confidence_secret_scan': not secret_hits},
        'secret_scan_matches': secret_hits,
        'json_parse_errors': json_errors,
        'problems': problems,
        'package_evidence_files': package_files,
        'boundary': 'Read-only validation of package/evidence snapshots; no business code, live configuration, state, service, scheduler, automation, network or Git action.'
    }
    RECEIPT.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'result': receipt['result'], 'counts': receipt['counts'], 'problems': problems, 'receipt': str(RECEIPT)}, ensure_ascii=False))
    return 0 if not problems else 1

if __name__ == '__main__':
    raise SystemExit(main())
