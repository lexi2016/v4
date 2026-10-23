"""One bound local code-pair comparison using the unchanged original owner reader."""
from __future__ import annotations
import argparse,csv,hashlib,json,math,os,re,sys
from datetime import datetime
from pathlib import Path
sys.dont_write_bytecode=True

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def load(p):return json.loads(Path(p).read_text())
def stat(p):
    s=Path(p).stat();return dict(inode=s.st_ino,size_bytes=s.st_size,mtime_ns=s.st_mtime_ns,nlink=s.st_nlink)
def main(cp,output_override=None):
    c=load(cp);b=load(c['input_binding_path']);cfg=load(c['config_path']);out=Path(output_override or c['output_directory']);out.mkdir(parents=True,exist_ok=True)
    def deny(event,args):
        if event.startswith(('socket.','sqlite3.connect','subprocess.Popen')):raise RuntimeError('OFFLINE_LOCAL_PAIR_ONLY')
        if event=='open':
            path,mode,flags=args
            if isinstance(path,(str,bytes,os.PathLike)):
                p=Path(os.fsdecode(path)).absolute()
                if p.suffix=='.day' and str(p) not in b['day_files']:raise RuntimeError('UNBOUND_DAY_READ')
                writing=bool((flags or 0)&(os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND))
                if writing and out.resolve() not in p.resolve().parents:raise RuntimeError('SOURCE_WRITE_FORBIDDEN')
    sys.addaudithook(deny)
    assert sha(__file__)==c['code_sha256'] and sha(c['config_path'])==c['config_sha256_expected']
    for p,h in b['source_bindings'].items():assert sha(p)==h,'SOURCE_DRIFT:'+p
    assert sha(b['identity_csv']['path'])==b['identity_csv']['sha256']
    found=[]
    with Path(b['identity_csv']['path']).open(encoding='utf-8-sig',newline='') as f:
        for row in csv.DictReader(f):
            if row['ts_code']==cfg['old_key']:found.append(row)
    assert len(found)==1,'IDENTITY_ROW_MISSING_OR_DUPLICATE';identity=found[0]
    assert identity['identity_classification_cn']=='确认股票'
    assert identity['code_map_old']==cfg['old_code'] and identity['code_map_new']==cfg['new_code'],'OFFICIAL_PAIR_MISMATCH'
    ev=b['official_pair_capture'];assert sha(ev['path'])==ev['sha256']
    text=load(ev['path']);assert isinstance(text,str)
    pair_rows=[]
    for line in text.splitlines():
        cells=[x.strip() for x in line.split('|')]
        if len(cells)>=5 and cells[0].isdigit() and cells[3]==cfg['old_code'] and cells[4]==cfg['new_code']:pair_rows.append(line)
    assert pair_rows and '旧代码' in text and '新代码' in text,'NO_EXACT_OFFICIAL_PAIR_ROW'
    assert identity['evidence_sha256']==ev['sha256'],'INHERITED_PAIR_SOURCE_DRIFT'
    snapshots={};problems=[]
    for p,desc in b['day_files'].items():
        q=Path(p);assert not q.is_symlink() and q.is_file(),'INPUT_PATH_REJECTED'
        assert stat(q)==desc['stat'] and sha(q)==desc['sha256'],'DAY_INPUT_DRIFT'
        snapshots[p]=stat(q)
        if snapshots[p]['size_bytes']%32:problems.append('NON_32_BYTE_ALIGNED:'+q.name)
    # The facade explicitly supports missing pytdx for read-only/tests. Block that
    # optional provider import: no SDK initialization or network client is needed.
    sys.modules['pytdx']=None
    sys.path.insert(0,b['owner_worktree'])
    from ops import a_share_daily_sync as owner
    assert owner.DAY_STRUCT.size==32
    fields=cfg['compare_fields'];info={};parsed={};cutoff=int(cfg['signal_asof'])
    if not problems:
        for label,p in [('old',cfg['old_path']),('new',cfg['new_path'])]:
            rows=owner.read_hq_day_bars(Path(p),tail_records=None)
            dates=[];calendar_valid=True
            for row in rows:
                d=owner.day_int(row);dates.append(d)
                try:datetime.strptime(str(d),'%Y%m%d');calendar_valid &= len(str(d))==8
                except ValueError:calendar_valid=False
            unique=len(dates)==len(set(dates));ascending=all(a<b for a,b in zip(dates,dates[1:]));expected=snapshots[p]['size_bytes']//32
            row_count_matches=len(rows)==expected
            finite=all(isinstance(r[k],(int,float)) and math.isfinite(r[k]) for r,d in zip(rows,dates) if d<=cutoff for k in fields)
            info[label]=dict(total_records=len(rows),expected_records=expected,row_count_matches=row_count_matches,calendar_dates_valid=bool(calendar_valid),dates_unique=unique,dates_strictly_ascending=ascending,max_date_all=max(dates) if dates else None,min_date_all=min(dates) if dates else None,rows_after_signal_cutoff=sum(d>cutoff for d in dates),rows_at_or_before_cutoff=sum(d<=cutoff for d in dates),max_date_at_or_before_cutoff=max((d for d in dates if d<=cutoff),default=None),has_D22=cutoff in dates,finite_compare_fields_through_D22=finite)
            if not (rows and calendar_valid and unique and ascending and row_count_matches and finite):problems.append('INPUT_DATE_OR_VALUE_INVARIANT:'+label)
            parsed[label]={d:r for d,r in zip(dates,rows) if d<=cutoff}
    diffs=None;overlap=None;overlap_bounds=None;unshared=None
    if not problems:
        overlap=sorted(set(parsed['old'])&set(parsed['new']));diffs={k:sum(parsed['old'][d][k]!=parsed['new'][d][k] for d in overlap) for k in fields}
        overlap_bounds=dict(first=min(overlap) if overlap else None,last=max(overlap) if overlap else None)
        unshared=dict(old_only_dates=len(set(parsed['old'])-set(parsed['new'])),new_only_dates=len(set(parsed['new'])-set(parsed['old'])))
        if not overlap:problems.append('NO_NONEMPTY_OVERLAP')
        if not info['new']['has_D22']:problems.append('COUNTERPART_D22_ABSENT')
        if any(diffs.values()):problems.append('STRICT_FIELD_MISMATCH')
    unchanged=True
    for p,desc in b['day_files'].items():unchanged &= stat(p)==snapshots[p] and sha(p)==desc['sha256']
    for p,h in b['source_bindings'].items():unchanged &= sha(p)==h
    unchanged &= sha(b['identity_csv']['path'])==b['identity_csv']['sha256'] and sha(ev['path'])==ev['sha256']
    if not unchanged:problems.append('SOURCE_OR_INPUT_CHANGED_DURING_CANARY')
    receipt=dict(status='LOCAL_PAIRED_DATA_PRESENT_AND_EXACT_OVERLAP_PARITY_ONLY' if not problems else 'CANNOT_CONFIRM_LOCAL_PAIR_PARITY',execution_id=c['execution_id'],old_key=cfg['old_key'],new_key=cfg['new_key'],signal_asof=cfg['signal_asof'],selection_date=cfg['selection_date'],identity_scope='Exact previously accepted official stock pair relation only; canonical side/effective interval/D22 availability not authenticated',owner_reader='ops.a_share_daily_sync.read_hq_day_bars(path,tail_records=None)',owner_day_int='ops.a_share_daily_sync.day_int',units=dict(OHLC='Original owner native integers /100.0; CNY',amount='Original owner float32 amount unchanged',vol='Original owner uint32 /100.0; compare same reader units, no alternate conversion'),alignment32={Path(p).name:v['size_bytes']%32==0 for p,v in snapshots.items()},inputs=info,nonempty_overlap_count=len(overlap) if overlap is not None else None,overlap_date_bounds=overlap_bounds,strict_field_diff_counts=diffs,nonoverlap_counts=unshared,compare_policy='Exact Python numeric equality, zero tolerance; all six fields, dates <=20261022 only. Future rows counted but excluded from numerical comparison.',problems=problems,inputs_and_source_unchanged=bool(unchanged),input_binding_sha256=sha(c['input_binding_path']),source_sha256=sha(__file__),config_sha256=sha(c['config_path']),day_sha256={p:v['sha256'] for p,v in b['day_files'].items()},raw_rows_exported=0,market_data_requests=0,source_writes=0,daily_bars_recovered=0,canonical_or_PIT_certified=False,full05_status='HOLD_CONTRACT_ONLY_NOT_COUNTED',research_only=True,production_allowed=False,buy_gate_updated=False,orders_sent=False)
    p=out/'CANARY_RECEIPT.json';assert not p.exists(),'NO_OUTPUT_OVERWRITE';p.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n');print(json.dumps(receipt,ensure_ascii=False));return 0 if not problems else 2

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--contract',required=True);p.add_argument('--output-directory');a=p.parse_args();raise SystemExit(main(a.contract,a.output_directory))
