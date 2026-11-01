"""Explicit offline classification import and read-only indexed views."""
from __future__ import annotations
import argparse,hashlib,json,os,re,sqlite3,threading
from pathlib import Path
from infrastructure.research_workbench_host import FLAGS,checked,checked_bytes
KINDS={'A_SHARE':('A_SHARE',r'\d{6}\.(SH|SZ|BJ)'),'HK_CONNECT':('HK_SHARE',r'\d{5}\.HK'),'CDR':('CDR',r'\d{6}\.SH')}
FIELDS=('symbol','name','market','exchange','board','instrument_type','reference_date','main_business','main_industry','main_industry_source','main_industry_system','main_industry_level','main_industry_levels','official_industry','shortline_themes','shortline_subthemes','normalized_themes','external_themes','industry_chain_role','robotics_role','daily_catalyst','external_inference','field_evidence_ids','classification_status','missing_reason','fine_classification_complete','review_status','identity_status','identity_source','evidence_ids','gaps','eligibility_status','eligibility_basis','eligibility_asof','channel_eligibility')
META=('schema_version','asof','knowledge_cutoff_at','generated_at','scope','classification_complete','all_records_have_rows','all_records_rechecked','fine_classification_status','top200_merged','aggregation_note','explicit_buy_stock_count','rule_derived_sell_only_distinct_count','complete_sell_only_universe_certified','ah_links_inferred','excluded_from_A5575')
EXTRAS=('qualification_verification','qualification_unresolved_records','qualification_source_ledger','original_cache_identity_quarantine','official_directory_status')
def canonical(v):return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def digest(v):return hashlib.sha256(canonical(v)).hexdigest()
def evidence_ids(value):
    found=set()
    def walk(item,key=None):
        if isinstance(item,dict):
            for k,v in item.items():walk(v,k)
        elif isinstance(item,list):
            if key=='evidence_ids':found.update(v for v in item if isinstance(v,str))
            else:
                for v in item:walk(v,key)
    walk(value)
    for values in (value.get('field_evidence_ids') or {}).values():
        if isinstance(values,list):found.update(v for v in values if isinstance(v,str))
    return sorted(found)

def import_received(references,destination):
    """Offline conversion only; never called by an API read or timer."""
    from ops.research_panel_daily_product import save
    root=Path(destination).resolve();root.mkdir(parents=True,exist_ok=True)
    adapter_sha=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    version=digest(dict(schema='classification.local_index.v1',adapter_sha256=adapter_sha,sources={k:v['sha256'] for k,v in sorted(references.items())}))
    folder=root/'versions'/version;manifest_path=folder/'manifest.json'
    if manifest_path.exists():
        manifest=json.loads(manifest_path.read_text());checked_bytes(dict(path=str(root/manifest['database']['path']),sha256=manifest['database']['sha256']))
    else:
        folder.mkdir(parents=True,exist_ok=True);db=folder/'classification.sqlite3';temporary=folder/('classification.'+str(os.getpid())+'.pending')
        if temporary.exists():raise ValueError('CLASSIFICATION_IMPORT_PENDING_EXISTS')
        conn=sqlite3.connect(temporary);counts={};previous=None;reuse=[];imported=[]
        try:
            if (root/'current.json').exists():
                old=ReceivedClassificationStore(root)
                try:
                    current=old._database()
                    if current and current[1]['manifest'].get('adapter_sha256')==adapter_sha:
                        previous=current[1]['manifest'];current[1]['connection'].backup(conn);counts=dict(previous['counts'])
                finally:old.close()
            if previous is None:conn.executescript('CREATE TABLE catalogs(kind TEXT PRIMARY KEY,metadata TEXT,source_ref TEXT,extras TEXT);CREATE TABLE securities(kind TEXT,symbol TEXT,name TEXT,payload TEXT,PRIMARY KEY(kind,symbol));CREATE TABLE evidence(kind TEXT,id TEXT,payload TEXT,PRIMARY KEY(kind,id));CREATE TABLE sources(kind TEXT,id TEXT,payload TEXT,PRIMARY KEY(kind,id));CREATE TABLE gaps(kind TEXT,id TEXT,payload TEXT,PRIMARY KEY(kind,id));')
            if previous:
                for removed in set(previous['source_inputs'])-set(references):
                    for table in ('catalogs','securities','evidence','sources','gaps'):conn.execute('DELETE FROM '+table+' WHERE kind=?',(removed,))
                    counts.pop(removed,None)
            for kind,ref in references.items():
                if previous and previous['source_inputs'].get(kind,{}).get('sha256')==ref['sha256']:
                    reuse.append(kind);continue
                imported.append(kind)
                if previous:
                    for table in ('catalogs','securities','evidence','sources','gaps'):conn.execute('DELETE FROM '+table+' WHERE kind=?',(kind,))
                if kind not in KINDS:raise ValueError('CLASSIFICATION_MARKET_UNSUPPORTED')
                raw=checked(ref);rows=raw.get('classifications');expected,pattern=KINDS[kind]
                if raw.get('schema_version')!='market-baseline-v1' or not isinstance(rows,list):raise ValueError('CLASSIFICATION_RECEIVED_SCHEMA_INVALID')
                conn.execute('INSERT INTO catalogs VALUES(?,?,?,?)',(kind,canonical({k:raw[k] for k in META if k in raw}).decode(),canonical(ref).decode(),canonical({k:raw[k] for k in EXTRAS if k in raw}).decode()))
                for row in rows:
                    if not re.fullmatch(pattern,str(row.get('symbol'))) or row.get('instrument_type')!=expected:raise ValueError('CLASSIFICATION_SECURITY_IDENTITY_INVALID')
                    conn.execute('INSERT INTO securities VALUES(?,?,?,?)',(kind,row['symbol'],row.get('name'),canonical({k:row[k] for k in FIELDS if k in row}).decode()))
                for table,key in [('evidence','id'),('sources','source_id'),('gaps','gap_id')]:
                    for item in raw.get(table,[]):
                        conn.execute('INSERT OR IGNORE INTO '+table+' VALUES(?,?,?)',(kind,item.get(key) or digest(item),canonical(item).decode()))
                counts[kind]=dict(classifications=len(rows),evidence=len(raw.get('evidence',[])),gaps=len(raw.get('gaps',[])))
            conn.commit()
        finally:conn.close()
        with temporary.open('rb') as stream:os.fsync(stream.fileno())
        os.replace(temporary,db)
        manifest=dict(schema='V4_RECEIVED_CLASSIFICATION_INDEX_V1',version=version,adapter_sha256=adapter_sha,imported_markets=imported,reused_markets=reuse,database=dict(path=str(db.relative_to(root)),sha256=hashlib.sha256(db.read_bytes()).hexdigest()),source_inputs=references,counts=counts,import_policy='OFFLINE_RECEIVED_FIELDS_ONLY_NO_FETCH_NO_PIT_OR_COMPLETENESS_UPGRADE',**FLAGS)
        save(manifest_path,manifest,immutable=True)
    pointer=dict(schema='V4_RECEIVED_CLASSIFICATION_CURRENT_V1',manifest=dict(path=str(manifest_path.relative_to(root)),sha256=hashlib.sha256(manifest_path.read_bytes()).hexdigest()),version=version,**FLAGS);save(root/'current.json',pointer);return pointer

class ReceivedClassificationStore:
    def __init__(self,root):self.root=Path(root) if root else None;self._cache={};self._joins={};self._lock=threading.RLock()
    def close(self):
        with self._lock:
            for value in self._cache.values():value['connection'].close()
            self._cache.clear();self._joins.clear()
    def __del__(self):
        try:self.close()
        except Exception:pass
    def _reference(self,ref):
        relative=Path(ref['path'])
        if relative.is_absolute() or any(p in ('.','..') for p in relative.parts):raise ValueError('CLASSIFICATION_RELATIVE_REFERENCE_REQUIRED')
        path=self.root/relative
        if not path.resolve(strict=True).is_relative_to(self.root.resolve(strict=True)):raise ValueError('CLASSIFICATION_REFERENCE_ESCAPE')
        return dict(path=str(path),sha256=ref['sha256'])
    def _current(self):
        if not self.root:return None
        if not self.root.is_absolute() or self.root.is_symlink() or self.root.resolve(strict=True)!=self.root:raise ValueError('CLASSIFICATION_STORE_ROOT_INVALID')
        path=self.root/'current.json'
        if path.is_symlink():raise ValueError('CLASSIFICATION_POINTER_SYMLINK')
        pointer=json.loads(path.read_bytes())
        if pointer.get('schema')!='V4_RECEIVED_CLASSIFICATION_CURRENT_V1' or any(pointer.get(k)!=v for k,v in FLAGS.items()):raise ValueError('CLASSIFICATION_CURRENT_INVALID')
        manifest=checked(self._reference(pointer['manifest']))
        if manifest.get('schema')!='V4_RECEIVED_CLASSIFICATION_INDEX_V1' or manifest.get('version')!=pointer.get('version') or any(manifest.get(k)!=v for k,v in FLAGS.items()):raise ValueError('CLASSIFICATION_MANIFEST_INVALID')
        return pointer,manifest
    def version(self):
        try:
            value=self._current();return value[0]['manifest']['sha256'] if value else 'CANNOT_CONFIRM_SOURCE_NOT_BOUND'
        except (ValueError,OSError,KeyError,TypeError) as e:return 'CANNOT_CONFIRM:'+str(e)
    def _database(self):
        value=self._current()
        if value is None:return None
        pointer,manifest=value;ref=self._reference(manifest['database']);path=Path(ref['path']);stat=path.stat();stamp=(stat.st_ino,stat.st_size,stat.st_mtime_ns);key=pointer['manifest']['sha256']
        if path.is_symlink():raise ValueError('CLASSIFICATION_DATABASE_SYMLINK')
        cached=self._cache.get(key)
        if not cached or cached['stamp']!=stamp:
            checked_bytes(ref);conn=sqlite3.connect(path.as_uri()+'?mode=ro&immutable=1',uri=True,check_same_thread=False);conn.execute('PRAGMA query_only=ON')
            cached=dict(connection=conn,stamp=stamp,manifest=manifest,catalogs={});self._cache[key]=cached
            while len(self._cache)>2:
                old=self._cache.pop(next(iter(self._cache)));old['connection'].close()
        return key,cached
    def _metadata(self,db,kind):
        row=db.execute('SELECT metadata,source_ref,extras FROM catalogs WHERE kind=?',(kind,)).fetchone()
        return dict(metadata=json.loads(row[0]),source_ref=json.loads(row[1]),extras=json.loads(row[2])) if row else None
    def catalog(self,kind):
        if kind not in KINDS:raise ValueError('CLASSIFICATION_MARKET_UNSUPPORTED')
        with self._lock:
            entry=self._database()
            if entry is None:return dict(status='CANNOT_CONFIRM_SOURCE_NOT_BOUND',market=kind,rows=[],**FLAGS)
            version,cached=entry
            if kind not in cached['catalogs']:
                db=cached['connection'];meta=self._metadata(db,kind)
                if meta is None:return dict(status='CANNOT_CONFIRM_MARKET_NOT_IMPORTED',market=kind,rows=[],**FLAGS)
                rows=[json.loads(v[0]) for v in db.execute('SELECT payload FROM securities WHERE kind=? ORDER BY symbol',(kind,))]
                cached['catalogs'][kind]=dict(schema='V4_RECEIVED_CLASSIFICATION_CATALOG_V1',status='PARTIAL_RECEIVED_NOT_DATA_CERTIFIED',market=kind,version=version,count=len(rows),rows=rows,**meta,boundary='历史收到资料；港股资格为来源历史时点，不是今日可买池；不推断A/H身份或交易权限',**FLAGS)
            return cached['catalogs'][kind]
    def join(self,rows):
        with self._lock:
            entry=self._database()
            if entry is None:return dict(status='CANNOT_CONFIRM_SOURCE_NOT_BOUND',rows={},catalogs={},identity_counts={},**FLAGS)
            version,cached=entry;key=(version,digest([(r['symbol'],r.get('display_name') or r.get('enriched_display_name')) for r in rows]))
            if key in self._joins:return self._joins[key]
            db=cached['connection'];symbols=[r['symbol'] for r in rows];marks=','.join('?' for _ in symbols);found={}
            if symbols:
                for kind,symbol,payload in db.execute('SELECT kind,symbol,payload FROM securities WHERE symbol IN ('+marks+')',symbols):found[(kind,symbol)]=json.loads(payload)
            result={};catalogs={};counts={}
            for current in rows:
                symbol=current['symbol'];name=current.get('display_name') or current.get('enriched_display_name');kind='HK_CONNECT' if symbol.endswith('.HK') else 'A_SHARE';source=found.get((kind,symbol))
                if source is None and kind=='A_SHARE' and ('CDR',symbol) in found:kind='CDR';source=found[(kind,symbol)]
                if kind not in catalogs:catalogs[kind]=self._metadata(db,kind) or {}
                status='CANNOT_CONFIRM_CODE_MISSING' if source is None else 'CANNOT_CONFIRM_CURRENT_NAME_MISSING' if not isinstance(name,str) or not name.strip() else 'BOUND_EXACT_CODE_NAME' if source.get('name')==name.strip() else 'IDENTITY_CONFLICT_NAME'
                item=dict(identity_status=status,market_scope=kind,symbol=symbol,current_name=name,received_name=source.get('name') if source else None,classification=None)
                if source and status=='BOUND_EXACT_CODE_NAME':
                    ids=evidence_ids(source);evidence=[]
                    if ids:evidence=[json.loads(v[0]) for v in db.execute('SELECT payload FROM evidence WHERE kind=? AND id IN ('+','.join('?' for _ in ids)+')',[kind,*ids])]
                    source_ids=sorted({r['source_id'] for r in evidence if r.get('source_id')});sources=[]
                    if source_ids:sources=[json.loads(v[0]) for v in db.execute('SELECT payload FROM sources WHERE kind=? AND id IN ('+','.join('?' for _ in source_ids)+')',[kind,*source_ids])]
                    item.update(classification=source,evidence=evidence,sources=sources,missing_evidence_ids=sorted(set(ids)-{r['id'] for r in evidence}))
                elif source:item['missing_reason']='代码相同但名称未精确绑定；原分类已隔离，不用于标签检索或筛选。'
                result[symbol]=item;counts[status]=counts.get(status,0)+1
            answer=dict(schema='V4_WORKBENCH_CLASSIFICATION_JOIN_V1',status='PARTIAL_RECEIVED_NOT_DATA_CERTIFIED',version=version,rows=result,catalogs=catalogs,identity_counts=counts,**FLAGS);self._joins[key]=answer
            while len(self._joins)>8:self._joins.pop(next(iter(self._joins)))
            return answer

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source-refs',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();print(json.dumps(import_received(json.loads(a.source_refs.read_text()),a.output),ensure_ascii=False))
