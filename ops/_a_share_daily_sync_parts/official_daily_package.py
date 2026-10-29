"""Read-only official G4DAY input adapter inside the original A sync producer.

Binary layout adapted from simonlin1212/a-stock-data (Apache-2.0), pinned
cb57c7aba720380b48a11dd065c6db57a2c39db9, SKILL.md v39-tdx-package.
See docs/handoffs/a_daily_zip_20261029 for upstream attribution/license.
"""
from __future__ import annotations
import hashlib,importlib.util,io,json,math,re,struct,sys,zipfile
from pathlib import Path
from datetime import datetime

SOURCE_KIND = "TDX_OFFICIAL_G4DAY"
SOURCE_URL = "https://www.tdx.com.cn/products/data/data/g4day/{date}.zip"


def _sha(raw):return hashlib.sha256(raw).hexdigest()
def _bound(ref):
    p=Path(ref['path'])
    if not p.is_absolute() or p.is_symlink() or p.resolve(strict=True)!=p:raise ValueError('G4DAY_SOURCE_PATH_INVALID')
    raw=p.read_bytes()
    if _sha(raw)!=ref['sha256']:raise ValueError('G4DAY_SOURCE_SHA_MISMATCH')
    return p,raw

def parse_package(raw: bytes, target: int):
    """Pure parser; preserve native precision and explicit member/index lineage."""
    text=str(target);datetime.strptime(text,'%Y%m%d')
    if len(text)!=8 or len(raw)>32*1024*1024:raise ValueError('G4DAY_DATE_OR_SIZE_INVALID')
    expected={f'{market}{text[2:]}.{ext}' for market in ('sh','sz','bj') for ext in ('cod','md1')}
    rows={};counts={};unpriced={};members={}
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        names=[i.filename for i in z.infolist() if not i.is_dir()]
        if len(names)!=len(set(names)) or not expected.issubset(names):raise ValueError('G4DAY_MEMBER_DATE_OR_DUPLICATE_INVALID')
        if any(n.endswith(('.cod','.md1')) and n not in expected for n in names):raise ValueError('G4DAY_UNEXPECTED_DATED_MEMBER')
        if sum(i.file_size for i in z.infolist())>128*1024*1024:raise ValueError('G4DAY_EXPANSION_LIMIT')
        if z.testzip() is not None:raise ValueError('G4DAY_CRC_INVALID')
        for prefix,market in [('sh',1),('sz',0),('bj',2)]:
            cn,mn=f'{prefix}{text[2:]}.cod',f'{prefix}{text[2:]}.md1'
            cod,md1=z.read(cn),z.read(mn)
            if len(cod)%150 or len(md1)%512 or len(cod)//150!=len(md1)//512:raise ValueError('G4DAY_MEMBER_RECORD_LENGTH_INVALID')
            for name,data in [(cn,cod),(mn,md1)]:members[name]={'name':name,'sha256':_sha(data),'crc32':z.getinfo(name).CRC,'size':len(data)}
            seqs=set();codes=set();counts[prefix]=0;unpriced[prefix]=0
            for index in range(len(cod)//150):
                rec=cod[index*150:(index+1)*150];seq=struct.unpack_from('<H',rec,32)[0]
                if seq in seqs or (seq+1)*512>len(md1):raise ValueError('G4DAY_DUPLICATE_OR_OUTSIDE_SEQ')
                seqs.add(seq);block=md1[seq*512:(seq+1)*512]
                previous=struct.unpack_from('<d',block,4)[0];op,high,low,close=struct.unpack_from('<4d',block,12);amount=struct.unpack_from('<d',block,72)[0]
                if not all(math.isfinite(v) for v in (previous,op,high,low,close,amount)):raise ValueError('G4DAY_NONFINITE_VALUE')
                # Unpriced pseudo-securities can have malformed GBK names; do
                # not decode their names as though they were priced equities.
                if close<=0:unpriced[prefix]+=1;continue
                code=rec[:6].rstrip(b'\0 ').decode('ascii')
                if not re.fullmatch(r'[0-9]{6}',code) or code in codes:raise ValueError('G4DAY_INVALID_OR_DUPLICATE_CODE')
                codes.add(code);name=rec[40:72].split(b'\0')[0].decode('gbk').strip()
                if not name:raise ValueError('G4DAY_EMPTY_PRICED_NAME')
                volume=struct.unpack_from('<Q',block,56)[0]
                lineage={'source_kind':SOURCE_KIND,'code':code,'market':market,'target_date':target,
                         'cod_member':members[cn],'md1_member':members[mn],
                         'cod_record_index':index,'cod_byte_offset':index*150,'seq':seq,'md1_byte_offset':seq*512}
                # Existing pack_hq_bar expects hands, and writes native shares.
                bar={'year':target//10000,'month':target//100%100,'day':target%100,'open':op,'high':high,'low':low,'close':close,'amount':amount,'vol':volume/100.0}
                rows[(market,code)]=(bar,lineage,volume);counts[prefix]+=1
            if not counts[prefix]:raise ValueError('G4DAY_PRICED_MARKET_EMPTY:'+prefix)
    return rows,{'priced_counts':counts,'unpriced_counts':unpriced,'members':members}


class OfficialDailyPackage:
    def __init__(self, ref: dict, target: int):
        self.input_path,raw=_bound(ref);self.input_ref=dict(ref);value=json.loads(raw)
        if value.get('schema_version')!='a_sync_official_daily_input.v1' or value.get('source_kind')!=SOURCE_KIND or value.get('target_date')!=target or value.get('source_url')!=SOURCE_URL.format(date=target):raise ValueError('G4DAY_INPUT_IDENTITY_INVALID')
        self.package_path,payload=_bound(value['package']);self.package_ref=dict(value['package']);self.target=target
        cal_path,_=_bound(value['calendar']);adapter_path,adapter_raw=_bound(value['calendar_adapter'])
        module_name='_g4day_bound_calendar_'+value['calendar_adapter']['sha256']
        spec=importlib.util.spec_from_file_location(module_name,adapter_path);module=importlib.util.module_from_spec(spec);sys.modules[module_name]=module
        exec(compile(adapter_raw,str(adapter_path),'exec'),module.__dict__)
        calendar=module.load_market_calendar(cal_path)
        state=module.resolve_market_states(calendar,str(target))['a_share']
        if state not in {module.TradingDayState.FULL_TRADING_DAY,module.TradingDayState.HALF_TRADING_DAY_AM}:raise ValueError('G4DAY_TARGET_NOT_TRADING_DAY')
        previous=module.previous_session(calendar,str(target),market='a_share')
        if value.get('previous_session')!=previous:raise ValueError('G4DAY_PREVIOUS_SESSION_PROOF_INVALID')
        self.previous=int(previous);self.calendar_ref=dict(value['calendar']);self.calendar_adapter_ref=dict(value['calendar_adapter'])
        self.rows,self.summary=parse_package(payload,target)
    def lineage(self,market,code):
        item=self.rows.get((market,code))
        return {'source_kind':SOURCE_KIND,'source_url':SOURCE_URL.format(date=self.target),
                'package':self.package_ref,'input_ref':self.input_ref,'calendar':self.calendar_ref,
                'calendar_adapter':self.calendar_adapter_ref,'previous_session':self.previous,
                'record':item[1] if item else None,'target_date':self.target,'market':market,'code':code}
    def lookup(self,market,code,last_date):
        if last_date not in {self.previous,self.target}:return [],'HISTORICAL_GAP_NOT_COVERED_BY_DAILY_PACKAGE'
        item=self.rows.get((market,code))
        if item is None:return [],'TARGET_DATE_MISSING'
        if item[2]>0xffffffff:return [],'G4DAY_VOLUME_OUTSIDE_NATIVE_UINT32'
        return [dict(item[0])],'OK'
