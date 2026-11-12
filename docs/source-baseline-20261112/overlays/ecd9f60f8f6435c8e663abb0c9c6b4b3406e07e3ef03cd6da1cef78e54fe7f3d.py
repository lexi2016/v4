from pathlib import Path
from datetime import datetime
import hashlib,io,json,struct,zipfile
import pytest
from ops import a_share_daily_sync as sync
from ops._a_share_daily_sync_parts.official_daily_package import parse_package,OfficialDailyPackage,SOURCE_URL
ROOT=Path(__file__).resolve().parents[1]
CAL=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/a-chain-natural-repair-20261029-r3-main/app/contracts')
TARGET=20261029
SPECS=[('sh',1,'600025'),('sz',0,'000002'),('bj',2,'920005')]
def ref(p):return {'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
def packet(target=TARGET,tweak=None):
    f=io.BytesIO()
    with zipfile.ZipFile(f,'w') as z:
        for prefix,market,code in SPECS:
            cod=bytearray(150);cod[:6]=code.encode();cod[40:44]='样本'.encode('gbk');md=bytearray(512)
            struct.pack_into('<d',md,4,10.0);struct.pack_into('<4d',md,12,10.0,11.0,9.0,10.5);struct.pack_into('<Q',md,56,12345);struct.pack_into('<d',md,72,129622.51357)
            if tweak:cod,md=tweak(prefix,cod,md)
            z.writestr(f'{prefix}{str(target)[2:]}.cod',cod);z.writestr(f'{prefix}{str(target)[2:]}.md1',md)
    return f.getvalue()
def input_ref(tmp_path,payload=None,previous='20261028',target=TARGET):
    tmp_path.mkdir(parents=True,exist_ok=True);p=tmp_path/'package.zip';p.write_bytes(packet(target) if payload is None else payload)
    obj={'schema_version':'a_sync_official_daily_input.v1','source_kind':'TDX_OFFICIAL_G4DAY','target_date':target,'source_url':SOURCE_URL.format(date=target),'package':ref(p),'calendar':ref(CAL/'market_calendar_2026.json'),'calendar_adapter':ref(CAL/'trading_calendar.py'),'previous_session':previous};q=tmp_path/'input.json';q.write_text(json.dumps(obj));return ref(q)
def bar(date=20261028,volume=12345):return {'year':date//10000,'month':date//100%100,'day':date%100,'open':10.,'high':11.,'low':9.,'close':10.5,'amount':129622.51357,'vol':volume/100.}
def run(tmp_path,monkeypatch,*,last_date=20261028,existing_volume=12345):
    inp=input_ref(tmp_path/'input');targets=[]
    for prefix,market,code in SPECS:
        p=tmp_path/prefix/(prefix+code+'.day');p.parent.mkdir();p.write_bytes(sync.pack_hq_bar(bar(last_date,existing_volume)));targets.append(sync.DailyTarget(code=code,market=market,path=p))
    monkeypatch.setattr(sync,'RUN_DIR',tmp_path/'run');calls=[]
    def forbidden(*a,**kw):calls.append('provider');raise AssertionError('TCP must not open')
    result=sync.run_sync(targets,target_date=str(TARGET),api_factory=forbidden,host_candidates=[],official_daily_input=inp,progress_path=tmp_path/'progress.json')
    assert not calls
    return result,targets,inp

def test_parser_preserves_three_market_precision_and_units():
    rows,summary=parse_package(packet(),TARGET)
    assert len(rows)==3 and summary['priced_counts']=={'sh':1,'sz':1,'bj':1}
    value,lineage,shares=rows[(1,'600025')]
    assert shares==12345 and value['vol']==123.45 and value['amount']==129622.51357
    native=sync.pack_hq_bar(value);assert struct.unpack_from('<I',native,24)[0]==12345
    assert struct.unpack_from('<f',native,20)[0]==struct.unpack('<f',struct.pack('<f',129622.51357))[0]
    assert lineage['cod_record_index']==0 and lineage['seq']==0 and lineage['md1_byte_offset']==0

def test_unpriced_invalid_gbk_is_excluded_before_name_decode():
    def tweak(prefix,cod,md):
        extra=bytearray(cod);extra[:6]=b'999999';extra[32:34]=struct.pack('<H',1);extra[40:72]=b'\xff'*32
        return cod+extra,md+bytearray(512)
    rows,summary=parse_package(packet(tweak=tweak),TARGET);assert len(rows)==3 and summary['unpriced_counts']=={'sh':1,'sz':1,'bj':1}

@pytest.mark.parametrize('kind',['date','record_length','seq','code','nan','priced_gbk','zip'])
def test_bad_input_fails_before_any_provider_or_raw_write(tmp_path,kind):
    def tweak(prefix,cod,md):
        if prefix=='sh':
            if kind=='record_length':cod+=b'x'
            if kind=='seq':cod[32:34]=struct.pack('<H',9)
            if kind=='code':cod[:6]=b'INVALID'[:6]
            if kind=='nan':struct.pack_into('<d',md,36,float('nan'))
            if kind=='priced_gbk':cod[40:72]=b'\xff'*32
        return cod,md
    raw=b'not zip' if kind=='zip' else packet(target=20261028 if kind=='date' else TARGET,tweak=tweak)
    with pytest.raises((ValueError,UnicodeError,zipfile.BadZipFile)):parse_package(raw,TARGET)

def test_append_uses_original_validator_and_capture_lineage(tmp_path,monkeypatch):
    calls=[];original=sync._fetch_valid_target_bars
    def observed(*a,**kw):calls.append(kw.get('source_rows'));return original(*a,**kw)
    monkeypatch.setattr(sync,'_fetch_valid_target_bars',observed)
    result,targets,inp=run(tmp_path,monkeypatch)
    assert result['accepted_count']==3 and result['updated_count']==3 and len(calls)==3
    for row in result['symbol_reconciliation']:
        assert row['host']=='TDX_OFFICIAL_G4DAY' and row['source_kind']=='TDX_OFFICIAL_G4DAY'
        receipt=json.loads(Path(row['raw_response_snapshots'][0]['path']).read_text())
        assert receipt['request']['source_kind']=='TDX_OFFICIAL_G4DAY'
        assert receipt['request']['record']['md1_member']['sha256']
    assert all(sync.read_last_date(t.path)==TARGET for t in targets)

def test_daily_package_cannot_fill_multiple_missing_sessions(tmp_path,monkeypatch):
    result,targets,_=run(tmp_path,monkeypatch,last_date=20261027)
    assert result['accepted_count']==0 and result['quarantine_count']==3
    assert all(row['reason_code']=='HISTORICAL_GAP_NOT_COVERED_BY_DAILY_PACKAGE' for row in result['symbol_reconciliation'])
    assert all(sync.read_last_date(t.path)==20261027 for t in targets)

def test_same_date_one_share_difference_is_conflict_not_tolerance(tmp_path,monkeypatch):
    result,targets,_=run(tmp_path,monkeypatch,last_date=TARGET,existing_volume=12346)
    assert result['accepted_count']==0 and result['quarantine_count']==3
    assert all(row['reason_code']==sync.SOURCE_IDENTITY_CHANGED for row in result['symbol_reconciliation'])
    assert all(struct.unpack_from('<I',t.path.read_bytes(),24)[0]==12346 for t in targets)

def test_same_date_identical_native_record_is_reused(tmp_path,monkeypatch):
    result,targets,inp=run(tmp_path,monkeypatch,last_date=TARGET)
    assert result['accepted_count']==3 and result['updated_count']==0
    assert all(row['records_written']==0 for row in result['symbol_reconciliation'])
@pytest.mark.parametrize('previous,target',[('20261027',TARGET),('20260930',20261001)])
def test_calendar_proof_mismatch_or_holiday_rejected(tmp_path,previous,target):
    inp=input_ref(tmp_path,previous=previous,target=target)
    with pytest.raises(ValueError):OfficialDailyPackage(inp,target)
