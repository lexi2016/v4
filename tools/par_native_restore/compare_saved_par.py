"""Compare candidate109 with actual SHA-bound saved Par109, including UNKNOWNs."""
import hashlib,json
from pathlib import Path
import pyarrow.parquet as pq
from native_state import encode
from environment import observed_environment


def compare(path,expected_sha,candidate):
    path=Path(path)
    if hashlib.sha256(path.read_bytes()).hexdigest()!=expected_sha:raise ValueError('SAVED_PAR109_SHA')
    records=pq.read_table(path).to_pylist();fields={}
    for row in records:
        if row['symbol']!=candidate['symbol'] or row['event_date'].strftime('%Y%m%d')!=candidate['event_date'] or row['field_name'] in fields:raise ValueError('SAVED_PAR109_IDENTITY_DUPLICATE')
        fields[row['field_name']]=json.loads(row['field_object_json'])
    if len(fields)!=109 or fields.keys()!=candidate['fields'].keys():raise ValueError('EXACT109_FIELD_SET')
    differences=[];known_numeric=known_other=both_unknown=0;per_field={}
    for name,expected in fields.items():
        actual=candidate['fields'][name];exact=encode(expected)==encode(actual);per_field[name]=dict(exact_payload=exact)
        if expected.get('value') is None and actual.get('value') is None:both_unknown+=1
        elif type(expected.get('value')) in (float,int):known_numeric+=int(exact)
        else:known_other+=int(exact)
        if not exact:differences.append(dict(field=name,original=expected,candidate=actual,original_value_bits=encode(expected.get('value')).hex(),candidate_value_bits=encode(actual.get('value')).hex()))
    return dict(status='PASS_SAVED_PAR109_SCOPE_ONLY' if not differences else 'DIFFERENT_FROM_SAVED_PAR109',symbol=candidate['symbol'],asof=candidate['event_date'],source=dict(path=str(path),sha256=expected_sha),exact_payloads=109-len(differences),exact_known_numeric=known_numeric,exact_known_other=known_other,both_unknown=both_unknown,differences=differences,per_field=per_field,environment=observed_environment(),cross_machine_generalization='CANNOT_CONFIRM',production_allowed=False)
