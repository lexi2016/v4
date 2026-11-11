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
MAX_CACHED_HISTORY_INPUTS = 32


def _sha(raw):return hashlib.sha256(raw).hexdigest()
def _bound(ref):
    p=Path(ref['path'])
    if not p.is_absolute() or p.is_symlink() or p.resolve(strict=True)!=p:raise ValueError('G4DAY_SOURCE_PATH_INVALID')
    raw=p.read_bytes()
    if _sha(raw)!=ref['sha256']:raise ValueError('G4DAY_SOURCE_SHA_MISMATCH')
    return p,raw


def bind_cached_history(ref: dict) -> dict:
    """Bind existing owner-cache descriptors, without fetching or rewriting them.

    The owner stores input.json at <official_daily>/<session>/input.json.
    Stop at the first absent descriptor. Each session is subsequently verified
    against the same calendar, input SHA and package SHA by the adapter.
    """
    path, raw = _bound(ref)
    value = json.loads(raw)
    if path.name != 'input.json' or path.parent.name != str(value['target_date']):
        raise ValueError('G4DAY_CACHE_LAYOUT_INVALID')
    history = []
    previous = int(value['previous_session'])
    for _ in range(MAX_CACHED_HISTORY_INPUTS):
        cached = path.parent.parent / str(previous) / 'input.json'
        if not cached.exists():
            break
        # Do not resolve away a symlink before the bound-path validator sees it.
        entry = {'path': str(cached), 'sha256': _sha(cached.read_bytes()), 'target_date': previous}
        _, payload = _bound(entry)
        descriptor = json.loads(payload)
        if descriptor.get('target_date') != previous:
            raise ValueError('G4DAY_HISTORY_INPUT_DATE_CONFLICT')
        history.append(entry)
        next_previous = int(descriptor['previous_session'])
        if next_previous >= previous:
            raise ValueError('G4DAY_HISTORY_ORDER_INVALID')
        previous = next_previous
    return {**ref, **({'history_inputs': history} if history else {})}

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
        self.input_path,raw=_bound(ref)
        # This is the immutable descriptor identity used by existing progress.
        # Additional cached sessions are individually bound in recovery_chain;
        # discovering them must not invalidate completed same-input progress.
        self.input_ref={name:ref[name] for name in ('path','sha256')};value=json.loads(raw)
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
        self._history_refs = {}
        self._history_packages = {}
        self._lookup_chains = {}
        self._witnesses = {}
        history = ref.get('history_inputs', [])
        if not isinstance(history, list) or len(history) > MAX_CACHED_HISTORY_INPUTS:
            raise ValueError('G4DAY_HISTORY_INPUTS_INVALID')
        for entry in history:
            date = entry.get('target_date')
            if type(date) is not int or date >= target or date in self._history_refs:
                raise ValueError('G4DAY_HISTORY_INPUT_DATE_CONFLICT')
            # Verify descriptors now; defer package parsing until a symbol needs it.
            _, descriptor = _bound(entry)
            if json.loads(descriptor).get('target_date') != date:
                raise ValueError('G4DAY_HISTORY_INPUT_DATE_CONFLICT')
            self._history_refs[date] = dict(entry)

    def _previous_package(self, date):
        if date not in self._history_packages:
            package = OfficialDailyPackage(self._history_refs[date], date)
            if (package.calendar_ref != self.calendar_ref or
                    package.calendar_adapter_ref != self.calendar_adapter_ref):
                raise ValueError('G4DAY_HISTORY_CALENDAR_IDENTITY_CONFLICT')
            self._history_packages[date] = package
        return self._history_packages[date]

    def lineage(self,market,code):
        item=self.rows.get((market,code))
        return {'source_kind':SOURCE_KIND,'source_url':SOURCE_URL.format(date=self.target),
                'package':self.package_ref,'input_ref':self.input_ref,'calendar':self.calendar_ref,
                'calendar_adapter':self.calendar_adapter_ref,'previous_session':self.previous,
                'record':item[1] if item else None,'target_date':self.target,'market':market,'code':code,
                'date_witness': self._witnesses.get((market, code)),
                'recovery_chain': [package.lineage(market, code)
                                   for package in self._lookup_chains.get((market, code), [])
                                   if package is not self]}
    def lookup(self,market,code,last_date):
        self._lookup_chains[(market, code)] = []
        if last_date is None or last_date > self.target:
            return [], 'HISTORICAL_GAP_NOT_COVERED_BY_DAILY_PACKAGE'
        chain = [self]
        package = self
        while last_date < package.previous:
            if package.previous not in self._history_refs:
                return [], 'HISTORICAL_GAP_NOT_COVERED_BY_DAILY_PACKAGE'
            package = self._previous_package(package.previous)
            chain.append(package)
        if last_date not in {package.previous, self.target}:
            return [], 'HISTORICAL_GAP_NOT_COVERED_BY_DAILY_PACKAGE'
        ordered = list(reversed(chain))
        self._lookup_chains[(market, code)] = ordered
        bars = []
        for package in ordered:
            item = package.rows.get((market, code))
            if item is None:
                return [], 'TARGET_DATE_MISSING'
            if item[2] > 0xffffffff:
                return [], 'G4DAY_VOLUME_OUTSIDE_NATIVE_UINT32'
            bars.append(dict(item[0]))
        return bars, 'OK'

    def witnessed_lookup(self, market, code, last_date, rows, witness_ref):
        """G4 values only; an overlapping SDK sequence witnesses absent dates.

        This proves the provider returned no bar in an interval, never an
        exchange/issuer suspension fact. Missing packages still cannot pass.
        """
        from ops.a_share_daily_sync import valid_hq_bar, day_int
        self.lookup(market, code, last_date)
        chain = self._lookup_chains.get((market, code), [])
        if last_date is None or last_date >= self.previous or not chain:
            return [], 'HISTORICAL_GAP_NOT_COVERED_BY_DAILY_PACKAGE'
        if not isinstance(rows, list) or not 2 <= len(rows) <= 32:
            return [], 'G4DAY_WITNESS_INCOMPLETE'
        if any(not valid_hq_bar(b)[0] or
               b.get('market', market) != market or b.get('code', code) != code for b in rows):
            return [], 'G4DAY_WITNESS_BAR_OR_IDENTITY_INVALID'
        dates = [day_int(b) for b in rows]
        if (dates != sorted(set(dates)) or dates[0] >= last_date or dates[-1] != self.target):
            return [], 'G4DAY_WITNESS_DATE_COVERAGE_INVALID'
        later = [b for b in rows if day_int(b) > last_date]
        if any(b['vol'] <= 0 or b['amount'] <= 0 for b in later):
            return [], 'G4DAY_WITNESS_NO_CURRENT_TRADED_BAR'
        expected = {day_int(b) for b in later}
        witnessed = {day_int(b):b for b in later}
        bars, absent = [], []
        for package in chain:
            item = package.rows.get((market, code))
            bar = item[0] if item else None
            valid = bar is not None and valid_hq_bar(bar)[0]
            traded = valid and bar['vol'] > 0 and bar['amount'] > 0
            if traded:
                if package.target not in expected:
                    return [], 'G4DAY_WITNESS_TRADED_DATE_CONFLICT'
                if item[2] > 0xffffffff:
                    return [], 'G4DAY_VOLUME_OUTSIDE_NATIVE_UINT32'
                if any(round(float(bar[k])*100)!=round(float(witnessed[package.target][k])*100)
                       for k in ('open','high','low','close')):
                    return [], 'G4DAY_WITNESS_OHLC_CONFLICT'
                bars.append(dict(bar))
            else:
                placeholder = bar is None or (all(bar[k] == 0 for k in ('open','high','low'))
                                              and bar['vol'] == 0 and bar['amount'] == 0)
                if package.target in dates or not placeholder:
                    return [], 'G4DAY_WITNESS_MISSING_OR_INVALID_TRADED_BAR'
                absent.append(package.target)
        if {day_int(b) for b in bars} != expected or not bars or day_int(bars[-1]) != self.target:
            return [], 'G4DAY_WITNESS_UNCOVERED_DATE'
        self._witnesses[(market,code)] = dict(response=witness_ref, absent_dates=absent,
            first_response_date=dates[0], last_response_date=dates[-1],
            semantics='NO_BAR_IN_OVERLAPPING_PROVIDER_SEQUENCE; LEGAL_SUSPENSION_CANNOT_CONFIRM')
        return bars, 'OK'

    def needs_witness(self, market, code, last_date):
        """Only a complete historical package chain with a traded current day."""
        if last_date is None or last_date >= self.previous:
            return False
        self.lookup(market, code, last_date)
        chain = self._lookup_chains.get((market,code), [])
        if not chain:
            return False
        from ops.a_share_daily_sync import valid_hq_bar
        current = self.rows.get((market,code))
        if not current or not valid_hq_bar(current[0])[0] or current[0]['vol'] <= 0 or current[0]['amount'] <= 0:
            return False
        absent = False
        for package in chain:
            item = package.rows.get((market,code))
            if item is None:
                absent = True
                continue
            bar = item[0]
            if valid_hq_bar(bar)[0] and bar['vol']>0 and bar['amount']>0:
                continue
            if not (all(bar[k]==0 for k in ('open','high','low')) and bar['vol']==0 and bar['amount']==0):
                return False
            absent = True
        return absent
