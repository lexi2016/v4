"""One frozen transport equivalence; actual source provenance stays separate."""
import hashlib
import json
from pathlib import Path


def _checked(path, expected):
    path=Path(path)
    if path.is_symlink() or path.resolve(strict=True)!=path or hashlib.sha256(path.read_bytes()).hexdigest()!=expected:
        raise ValueError('READER_TRANSPORT_PROOF_SOURCE_DRIFT')
    return path


def semantic_reader_identity(reader_ref,config_ref,*,proof_path=None):
    proof_path=Path(proof_path) if proof_path else Path(__file__).parent/'vendor/selector_reader_transport_compat.json'
    if not proof_path.exists():return reader_ref,None
    proof=json.loads(proof_path.read_bytes())
    if (proof.get('schema')!='v4.reader.transport_equivalence.v1'
            or proof.get('scope')!='EXACT_ARROW_BLOCK_TRANSPORT_ONLY'
            or proof.get('after_sha256')!=reader_ref['sha256'] or proof.get('config')!=config_ref
            or proof.get('historical_reader',{}).get('path')!=reader_ref['path']
            or proof.get('historical_reader',{}).get('sha256')!=proof.get('before_sha256')):
        raise ValueError('READER_TRANSPORT_PROOF_IDENTITY_CONFLICT')
    before=_checked(proof_path.parent/proof['before_source'],proof['before_sha256'])
    oracle=_checked(proof_path.parent/proof['oracle']['file'],proof['oracle']['sha256'])
    result=json.loads(oracle.read_bytes())
    if result.get('status')!='PASS' or result.get('before_sha256')!=proof['before_sha256'] or result.get('after_sha256')!=proof['after_sha256']:
        raise ValueError('READER_TRANSPORT_ORACLE_NOT_PASS')
    _checked(reader_ref['path'],reader_ref['sha256'])
    return proof['historical_reader'],dict(actual_reader=reader_ref,historical_mathematical_reader=proof['historical_reader'],
        before_source_snapshot=dict(path=str(before),sha256=proof['before_sha256']),
        equivalence_proof=dict(path=str(proof_path),sha256=hashlib.sha256(proof_path.read_bytes()).hexdigest()),
        oracle=dict(path=str(oracle),sha256=proof['oracle']['sha256']))
