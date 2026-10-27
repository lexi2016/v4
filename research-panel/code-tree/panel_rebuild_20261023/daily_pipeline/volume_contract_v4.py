"""Explicit, exact-once volume normalization. No vendor/PIT/training certification.

RAW32 input is decoded only for exact C364 reserved marker. Existing corrected
partitions and V4 mixed raw/G4 output carry separate schemas and are never decoded
again. G4 is uint64 inferred at offset 56; it NEVER goes through raw32 decoding.
"""
import hashlib,importlib.util,re
from pathlib import Path
from decimal import Decimal,InvalidOperation
PROJECT=Path(__file__).resolve().parent.parent
DECODER_PATH=PROJECT/'volume_correction_v1/volume_decode.py'
DECODER_SHA='2c7ffaec6c0bafbd25335c0cd08b32fe72d868c7a8e6abf34083180d376a6582'
REVIEW_PATH=PROJECT/'review/VOLUME_INDEPENDENT_AUDIT.json'
REVIEW_SHA='e7876710e9099d12275d2fac65b8d7747ee8d82cc72f3690a7842e6feda3ca24'
RAW_ENCODING='TDX_DAY_RAW_UINT32_C364_ENCODED_V1'
DECODED_ENCODING='DECODED_C364_BASE100_V1_DO_NOT_DECODE_AGAIN'
OUTPUT_ENCODING='NUMERIC_VOLUME_V4_DO_NOT_DECODE'
UINT32=(1<<32)-1
UINT64=(1<<64)-1

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def helper():
 if sha(DECODER_PATH)!=DECODER_SHA or sha(REVIEW_PATH)!=REVIEW_SHA:raise ValueError('VOLUME_HELPER_OR_REVIEW_HASH_MISMATCH')
 spec=importlib.util.spec_from_file_location('accepted_c364_v1',DECODER_PATH);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def uint(value,maximum,name):
 if type(value)is int:n=value
 elif type(value)is str and re.fullmatch(r'[0-9]+',value):n=int(value)
 else:raise ValueError('UNSIGNED_INTEGER_REQUIRED:'+name)
 if not 0<=n<=maximum:raise ValueError('UNSIGNED_INTEGER_RANGE:'+name)
 return n

def number(value):
 if type(value)is bool:raise ValueError('NONNUMERIC_BOOLEAN')
 try:d=Decimal(str(value))
 except (ValueError,InvalidOperation) as e:raise ValueError('INVALID_NUMERIC') from e
 if not d.is_finite():raise ValueError('NONFINITE_NUMERIC')
 return d

def normalize_pair(raw,qfq,encoding,decoder_sha=None):
 if encoding not in (RAW_ENCODING,DECODED_ENCODING,OUTPUT_ENCODING):raise ValueError('VOLUME_SCHEMA_UNKNOWN_OR_MISSING')
 if encoding!=RAW_ENCODING and decoder_sha!=DECODER_SHA:raise ValueError('VOLUME_DECODER_VERSION_REQUIRED')
 if len(raw)!=len(qfq):raise ValueError('VOLUME_RAW_QFQ_LENGTH_MISMATCH')
 decode=helper();newraw=[];newq=[];changed=0;marked=0
 for r,q in zip(raw,qfq):
  if r['trade_date']!=q['trade_date']:raise ValueError('VOLUME_RAW_QFQ_DATE_MISMATCH')
  limit=UINT32 if encoding==RAW_ENCODING else UINT64
  vol=uint(r['vol'],limit,'raw.vol');qv=uint(q['vol'],limit,'qfq.vol')
  reserved=uint(r['reserved'],UINT32,'raw.reserved');qr=uint(q['reserved'],UINT32,'qfq.reserved')
  if vol!=qv or reserved!=qr or number(r['amount'])!=number(q['amount']):raise ValueError('VOLUME_RAW_QFQ_FIELDS_MISMATCH')
  ismarker=reserved & 0xffffff00==0xc3640000
  decoded=decode.decode_volume(vol,reserved) if encoding==RAW_ENCODING else vol
  if ismarker:
   marked+=1
   # A decoded tag cannot legitimise still-encoded, truncated, or wrong-remainder values.
   if decoded<=UINT32 or reserved&0xff>99 or decoded%100!=reserved&0xff:raise ValueError('DECODED_MARKER_INCONSISTENT')
   decode.validate_marker_envelope(decoded,r['amount'],r['low'],r['high'])
  a=dict(r);b=dict(q)
  if decoded!=vol:a['vol']=b['vol']=str(decoded);changed+=1
  newraw.append(a);newq.append(b)
 return newraw,newq,{'input_encoding':encoding,'output_encoding':OUTPUT_ENCODING,'decoder_sha256':DECODER_SHA,'decoder_independent_review_sha256':REVIEW_SHA,'decoded_rows':changed,'marker_rows_checked':marked,'status':'NUMERICALLY_VALIDATED_MARKERS_ONLY','official_format_certified':False,'training_eligible':False}

def validate_g4(row):
 vol=uint(row['vol'],UINT64,'G4.vol')
 if vol==0:raise ValueError('G4_ZERO_VOLUME_REQUIRES_NO_TRADE_REVIEW')
 helper().validate_marker_envelope(vol,row['amount'],row['low'],row['high'])
 return {'encoding':'G4_UINT64_OFFSET56_INFERRED_V1','status':'NUMERICALLY_VALIDATED','envelope':'RAW_AMOUNT_DIV_VOLUME_WITHIN_RAW_LOW_HIGH','raw32_decoder_applied':False,'official_format_certified':False,'training_eligible':False}

def contract():
 helper()
 return {'schema':'DAILY_VOLUME_CONTRACT_V4','volume_encoding':OUTPUT_ENCODING,'decoder_sha256':DECODER_SHA,'decoder_independent_review_sha256':REVIEW_SHA,'g4_encoding':'G4_UINT64_OFFSET56_INFERRED_V1','status':'NUMERIC_VALIDATION_NOT_VENDOR_FORMAT_CERTIFICATION','training_eligible':False,'absolute_liquidity_eligible':False,'official_format_certified':False}
