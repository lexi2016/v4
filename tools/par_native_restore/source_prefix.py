"""Read-only SHA-bound Par prefix reconstruction, with cached original archives.

The caller supplies the physical by-SHA index. Linux original paths are identity
metadata, never fabricated local paths. No downloads, repairs or Mac fallback.
"""
import ast,copy,gzip,hashlib,importlib.util,json,sys,zipfile
from collections import OrderedDict
from pathlib import Path
from native_state import digest

CATALOG_SHA='71854c8985db863fc0c4f1c54da8c89a68b1dab1fad0144a72b3477a1648166e'
SOURCE_SHA='5f5932db843a723e976dbea26bd79e05b1a2f494228ed2462fd5403c1d6ffe35'
BASIS_KEYS=('price_coordinate','event_sha256','volume_contract_sha256')


def canonical(v):return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def json_sha(v):return hashlib.sha256(canonical(v)).hexdigest()


class MissingSource(ValueError):pass


class Store:
    def __init__(self,index):
        data=json.loads(Path(index).read_bytes());self.index=data.get('by_sha256',{})
        if not self.index:
            for item in data.get('files',[]):self.index[item['sha256']]=item
        self.zips={};self.verified={};self.cache=OrderedDict();self.cache_size=0;self.used={};self.physical_cache={}
    def path(self,ref):
        item=self.index.get(ref['sha256'])
        if item is None:raise MissingSource('MISSING_SHA:'+ref['sha256']+':'+str(ref.get('path',ref.get('member',''))))
        p=Path(item if isinstance(item,str) else item['path']).resolve()
        if not p.is_file():raise MissingSource('MISSING_PHYSICAL_FILE:'+str(p))
        return p
    def authenticate(self,p,expected):
        st=p.stat();signature=(st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns)
        if self.verified.get((str(p),expected))==signature:return
        h=hashlib.sha256()
        with p.open('rb') as f:
            for block in iter(lambda:f.read(4*1024**2),b''):h.update(block)
        if h.hexdigest()!=expected:raise ValueError('SOURCE_BYTES_SHA:'+str(p))
        after=p.stat()
        if signature!=(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns):raise ValueError('SOURCE_CHANGED:'+str(p))
        self.verified[(str(p),expected)]=signature
    def read(self,ref,archives=None):
        sha=ref['sha256']
        if sha in self.cache:
            data=self.cache.pop(sha);self.cache[sha]=data;self.used[sha]=self.physical_cache[sha]
            if len(data)!=ref.get('bytes',len(data)):raise ValueError('CACHED_MEMBER_SIZE:'+sha)
            return data
        if sha in self.index:
            p=self.path(ref);self.authenticate(p,sha);data=p.read_bytes();physical=dict(path=str(p),sha256=sha)
        elif 'archive_id' in ref or 'archive_path' in ref:
            if 'archive_id' in ref:archive=archives[ref['archive_id']]
            else:
                candidates=[x for x in (archives or {}).values() if x['path']==ref['archive_path'] or ref['archive_path'].endswith('/'+x['path'])]
                if not candidates:
                    for key,item in self.index.items():
                        if isinstance(item,dict) and (item.get('original_path')==ref['archive_path'] or Path(item.get('path','')).name==Path(ref['archive_path']).name):candidates.append({'sha256':key,'path':item['path']})
                if len(candidates)!=1:raise MissingSource('UNBOUND_ARCHIVE_PATH:'+ref['archive_path']+':MEMBER_SHA:'+sha)
                archive=candidates[0]
            p=self.path(archive);self.authenticate(p,archive['sha256']);key=(str(p),archive['sha256'])
            if key not in self.zips:self.zips[key]=zipfile.ZipFile(p)
            data=self.zips[key].read(ref['member']);physical=dict(path=str(p),archive_sha256=archive['sha256'],member=ref['member'],sha256=sha)
        else:raise MissingSource('MISSING_SHA:'+sha+':'+str(ref.get('path','')))
        if hashlib.sha256(data).hexdigest()!=sha or len(data)!=ref.get('bytes',len(data)):raise ValueError('MEMBER_SHA_SIZE:'+sha)
        self.used[sha]=physical;self.physical_cache[sha]=physical
        if len(data)<=16*1024**2:
            self.cache[sha]=data;self.cache_size+=len(data)
            while self.cache_size>64*1024**2:
                _,old=self.cache.popitem(last=False);self.cache_size-=len(old)
        return data
    def document(self,ref,archives=None):
        data=self.read(ref,archives);return json.loads(gzip.decompress(data) if data[:2]==b'\x1f\x8b' else data)
    def close(self):
        for z in self.zips.values():z.close()


class Loader:
    def __init__(self,par,catalog,index):
        self.store=Store(index);path=Path(catalog);raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=CATALOG_SHA:raise ValueError('ORIGINAL_CATALOG_PIN')
        self.catalog=json.loads(raw);source=Path(par)/'handoff/unified_candidate_20261102/source.py'
        if hashlib.sha256(source.read_bytes()).hexdigest()!=SOURCE_SHA:raise ValueError('ORIGINAL_NORMALIZER_PIN')
        sys.path.insert(0,str(source.parent));spec=importlib.util.spec_from_file_location('recovery_prefix_original_source',source);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);self.source=m
    def bundle(self,ref):
        b=self.store.document(ref);s=b['state51'];day=b['daily51'];component=b['component109']
        if s['state_sha256']!=json_sha({k:v for k,v in s.items() if k!='state_sha256'}) or s['last_daily_sha256']!=json_sha(day):raise ValueError('ORIGINAL_BUNDLE_SELF_HASH')
        if not (b['symbol']==s['symbol']==component['symbol'] and b['asof']==str(day['trade_date'])==str(s['last_date'])==component['last_date']):raise ValueError('BUNDLE_IDENTITY')
        if s['count']!=component['count']:raise ValueError('BUNDLE_COUNT')
        if len(day['values'])!=51 or len(day['drawings'])!=22 or day['ohlcv']['trade_date']!=day['trade_date']:raise ValueError('ORIGINAL51_22_SCHEMA_DATE')
        return b
    def append_day(self,rows,day,symbol):
        prior=rows[-1];bridge=dict(trade_date=int(prior['event_date']),ohlcv=dict(trade_date=int(prior['event_date']),**{k:prior[k] for k in ('open','high','low','close')},vol=prior['volume']))
        row=self.source.normalize([bridge,day],symbol)[-1];row['raw_row_index']=len(rows)
        if row['event_date']<=prior['event_date']:raise ValueError('SOURCE_DAY_ORDER')
        rows.append(row);return rows
    def seed(self,bundle):
        symbol=bundle['symbol'];h=bundle['history_refs']
        if 'oct30_catalog_ref' not in h:raise MissingSource('BOOTSTRAP841_ORIGINAL_TDX_SINA_CHAIN_REQUIRED:'+symbol+':'+h.get('kind','UNKNOWN'))
        binding=self.catalog['symbols'][symbol]
        if h['oct30_catalog_ref']['sha256']!=CATALOG_SHA or h['oct30_source_binding']!=binding:raise ValueError('OCT30_SOURCE_BINDING_IDENTITY')
        archives=self.catalog['archives'];docs=[self.store.document(ref,archives) for ref in binding['source_refs']]
        if any(doc.get('symbol',symbol)!=symbol for doc in docs):raise ValueError('ORIGINAL_PREFIX_DOCUMENT_SYMBOL')
        raw=list(docs[0]['rows'])+docs[1:]
        rows=self.source.normalize(raw,symbol)
        if binding.get('original_values_refs'):
            docs=[self.store.document(ref,archives) for ref in binding['original_values_refs']]
            original=self.source.normalize(list(docs[0]['rows'])+docs[1:],symbol);rows=self.source.bind_original_values(rows,original)
        if len(rows)!=binding.get('expected_rows',len(rows)):raise ValueError('ORIGINAL_PREFIX_EXPECTED_ROWS')
        if rows[-1]['event_date']!='20261030':raise ValueError('OCT30_PHYSICAL_DATE')
        for date in ('20261102','20261103'):self.append_day(rows,self.store.document(h['nov2_nov3'][date]),symbol)
        # SHA-authenticated original Parquet supplies original Nov4 daily bytes.
        import io,pyarrow.parquet as pq
        ref=h['nov4_state_asset_ref'];table=pq.read_table(io.BytesIO(self.store.read(ref)),columns=['symbol','event_date','daily','daily_sha256']).to_pylist()
        matches=[r for r in table if r['symbol']==symbol and r['event_date'].strftime('%Y%m%d')=='20261104']
        if len(matches)!=1:raise ValueError('NOV4_STATE_ASSET_ROW')
        record=matches[0];blob=bytes(record['daily'])
        if hashlib.sha256(blob).hexdigest()!=record['daily_sha256']:raise ValueError('NOV4_DAILY_BYTES_SHA')
        self.append_day(rows,json.loads(blob),symbol);self.append_day(rows,bundle['daily51'],symbol)
        # Match the original SeedHistory policy exactly: no invented historic51.
        for row in rows:row.pop('original_values',None)
        rows[-1]['original_values']={k:bundle['daily51']['values'].get(k) for k in ('MA60','白线','黄线','一级买点','二级买点','卖点')}
        return rows,copy.deepcopy(binding['context'])
    def prefix(self,ref,seen=None):
        seen=set() if seen is None else seen
        if ref['sha256'] in seen or len(seen)>366:raise ValueError('PARENT_CHAIN_CYCLE_DEPTH')
        seen.add(ref['sha256']);bundle=self.bundle(ref)
        if bundle['schema']=='NOV5_MINIMUM_CONTINUATION_BUNDLE_V1':rows,context=self.seed(bundle)
        elif bundle['schema']=='SAME_BASIS_CONTINUATION_BUNDLE_V1':
            parent_ref=bundle['history_refs']['parent_continuation_ref'];rows,context,parent=self.prefix(parent_ref,seen)
            if parent['symbol']!=bundle['symbol']:raise ValueError('PARENT_SYMBOL')
            if bundle['state51'].get('parent_state_sha256')!=json_sha(parent['state51']):raise ValueError('ORIGINAL51_PARENT_STATE_SHA')
            for key in BASIS_KEYS:
                if parent['state51']['binding'].get(key)!=bundle['state51']['binding'].get(key):raise ValueError('SOURCE_BASIS_CHANGED:'+key)
            self.append_day(rows,bundle['daily51'],bundle['symbol'])
        else:raise ValueError('ORIGINAL_BUNDLE_SCHEMA')
        if len(rows)!=bundle['state51']['count'] or rows[-1]['event_date']!=bundle['asof']:raise ValueError('PREFIX_COUNT_ASOF')
        context={**context,'symbol':bundle['symbol'],'asof':bundle['asof']}
        return rows,context,bundle
    def load(self,ref,target='20261109'):
        self.store.used={};rows,context,bundle=self.prefix(ref)
        if bundle['asof']!=target:raise ValueError('REQUESTED_TARGET_NOT_PHYSICAL_ASOF:'+bundle['asof'])
        return dict(rows=rows,context=context,bundle=bundle,kind='ACTUAL_PAR_SOURCE',source_binding=dict(source_prefix_sha256=digest(rows),source_reference=ref['sha256'],source_basis=context['basis'],source_catalog_sha256=CATALOG_SHA,source_normalizer_sha256=SOURCE_SHA,normalized_rows_sha256=digest(rows),physical_asof=rows[-1]['event_date'],source_refs=list(self.store.used.values()),original_bundle_ref=ref))
