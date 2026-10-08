"""SDK evidence normalization, without collection, publication or membership claims.

The tagged-scalar approach reuses the frozen HK capture contract's raw evidence
separation. Normalized business fields are never fed tagged dictionaries.
stock_owner denotes an option/warrant underlying, not a shareholding relation.
"""
import base64
from collections.abc import Mapping
from datetime import date, datetime, time
from decimal import Decimal
import math
import numbers
import re

from .contracts import aware
from .digests import canonical_bytes, sha256_json

SOURCE_DOC = 'https://openapi.futunn.com/futu-api-doc/quote/get-static-info.html'
FIELDS = ('code','name','outstanding_shares','circular_market_val','listing_date',
          'lot_size','stock_owner','stock_child_type','sec_status')


def encode_sdk_value(value):
    if value is None or isinstance(value,(str,bool,int)):
        return value
    if isinstance(value,numbers.Integral):return int(value)
    if isinstance(value,numbers.Real):
        number=float(value)
        return number if math.isfinite(number) else {'$float':repr(number)}
    if isinstance(value,Decimal):return {'$decimal':str(value)}
    if isinstance(value,(date,datetime,time)):return {'$datetime':value.isoformat()}
    if isinstance(value,bytes):return {'$bytes_base64':base64.b64encode(value).decode()}
    if isinstance(value,Mapping):
        if any(not isinstance(k,str) for k in value):raise ValueError('SDK_NONSTRING_KEY')
        return {k:encode_sdk_value(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [encode_sdk_value(v) for v in value]
    if type(value).__name__ in ('NAType','NaTType'):
        return {'$missing_scalar':type(value).__name__}
    if type(value).__module__.startswith('numpy') and callable(getattr(value,'item',None)):
        scalar=value.item()
        if scalar is not value:return encode_sdk_value(scalar)
    raise ValueError('SDK_VALUE_TYPE_UNSUPPORTED')


def _missing(value):
    return (value is None or (isinstance(value,str) and not value.strip())
            or (isinstance(value,numbers.Real) and not isinstance(value,bool) and math.isnan(float(value)))
            or type(value).__name__ in ('NAType','NaTType'))


def _numeric(value, optional=False, positive_integer=False):
    if _missing(value):return None,'UNKNOWN' if optional else 'INVALID'
    if isinstance(value,bool) or not isinstance(value,numbers.Real):return None,'INVALID'
    number=float(value)
    if not math.isfinite(number) or number<0 or (positive_integer and (number<=0 or not number.is_integer())):
        return None,'INVALID'
    return int(value) if isinstance(value,numbers.Integral) or positive_integer else number,'KNOWN'


def _security_type(source):
    explicit=source.get('stock_type')
    types=set()
    if isinstance(explicit,str) and explicit in ('STOCK','WARRANT','OPTION'):types.add(explicit)
    for field,kind in (('equity_valid','STOCK'),('wrt_valid','WARRANT'),('option_valid','OPTION')):
        if source.get(field) is True:types.add(kind)
    if len(types)>1:return 'UNVERIFIED','SECURITY_TYPE_CONFLICT'
    if not types:return 'UNVERIFIED','SECURITY_TYPE_UNVERIFIED'
    return next(iter(types)),None


def normalize_security_references(records, *, captured_at):
    aware(captured_at)
    if not isinstance(records,list) or not records or len(records)>10000:
        raise ValueError('SDK_RECORDS_INVALID')
    raw={'schema_version':'v5.sdk_tagged_records.v1','captured_at':captured_at,
         'records':[encode_sdk_value(record) for record in records]}
    rows=[];codes=set()
    for source in records:
        if not isinstance(source,Mapping):raise ValueError('SDK_RECORD_INVALID')
        code=source.get('code')
        if not isinstance(code,str) or re.fullmatch(r'HK\.[0-9]{5}',code) is None or code in codes:
            raise ValueError('SDK_CODE_INVALID_OR_DUPLICATE')
        codes.add(code)
        kind,type_issue=_security_type(source)
        issues=[type_issue] if type_issue else []
        row={'code':code,'security_type':kind,'field_status':{},'issues':issues}
        for field in ('name','listing_date','sec_status','stock_child_type'):
            value=source.get(field)
            if _missing(value):
                row[field]=None;row['field_status'][field]='UNKNOWN'
                if field!='stock_child_type':issues.append('MISSING_'+field.upper())
            elif isinstance(value,str) and value.lower().strip() not in ('nan','inf','infinity','none'):
                row[field]=value.strip();row['field_status'][field]='KNOWN'
            else:
                row[field]=None;row['field_status'][field]='INVALID';issues.append('INVALID_'+field.upper())
        if row['name'] in (code,code[3:]):issues.append('PLACEHOLDER_NAME')
        if row['listing_date'] is not None:
            try:date.fromisoformat(row['listing_date'])
            except ValueError:issues.append('INVALID_LISTING_DATE')
        for field in ('outstanding_shares','circular_market_val','lot_size'):
            value,state=_numeric(source.get(field),optional=field!='lot_size',positive_integer=field=='lot_size')
            row[field]=value;row['field_status'][field]=state
            if state=='INVALID':issues.append('INVALID_'+field.upper())
        owner=source.get('stock_owner')
        if _missing(owner):
            row['stock_owner']=None
            row['field_status']['stock_owner']='NOT_APPLICABLE' if kind=='STOCK' else 'UNKNOWN'
            if kind in ('WARRANT','OPTION'):issues.append('STOCK_OWNER_REQUIRED')
        elif isinstance(owner,str) and re.fullmatch(r'(HK|US|SH|SZ)\.[A-Z0-9]+',owner):
            row['stock_owner']=owner;row['field_status']['stock_owner']='KNOWN'
        else:
            row['stock_owner']=None;row['field_status']['stock_owner']='INVALID';issues.append('INVALID_STOCK_OWNER')
        row['issues']=sorted(set(issues))
        row['source_row_index']=len(rows)
        rows.append(row)
    value={'schema_version':'v5.security_reference_normalization.v1','status':'NORMALIZED_ONLY',
           'captured_at':captured_at,'field_semantics_source':SOURCE_DOC,'raw':raw,'raw_sha256':sha256_json(raw),
           'rows':rows,'membership_verified':False,'publication_verified':False,
           'research_only':True,'production_allowed':False,'buy_gate_updated':False,'orders_sent':False}
    value['sha256']=sha256_json(value)
    canonical_bytes(value)
    return value
