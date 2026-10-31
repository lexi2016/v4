"""Evidence-bound preparation before original A-Sync; never overwrite raw data.

This one-batch adapter consumes the accepted Dot full-RAW-bar source records,
original affine/IPO evidence, and exactly dated no-trade records. Original
provider, ratio threshold, source files, and old receipts are preserved.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib
import importlib.util
import json
from pathlib import Path
import struct
import sys
import zipfile

FLAGS=dict(RESEARCH_ONLY=True,production_allowed=False,buy_gate_updated=False,orders_sent=False)
BATCH=Path('/Users/lexi/Desktop/学习/因子工厂/research/workbench_daily_chain_completion_20261031_r1')


def sha(raw):return hashlib.sha256(raw).hexdigest()

def read(reference):
    path=Path(reference['path']);raw=path.read_bytes()
    if not path.is_absolute() or path.is_symlink() or sha(raw)!=reference['sha256']:raise ValueError('SOURCE44_REFERENCE_DRIFT:'+str(path))
    return json.loads(raw)


def put(path,value):
    raw=json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()+b'\n'
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists() and path.read_bytes()!=raw:raise ValueError('SOURCE44_IMMUTABLE_OUTPUT_EXISTS:'+str(path))
    if not path.exists():
        with path.open('xb')as stream:stream.write(raw);stream.flush();__import__('os').fsync(stream.fileno())
    return dict(path=str(path.resolve()),sha256=sha(raw))


def exclude_no_trade(raw,rows,symbol):
    """Remove only hash-proven non-trading placeholders from a derived copy."""
    dates={row['date']:row for row in rows if row['symbol']==symbol and row['classification']=='VERIFIED_NO_TRADE_SUSPENSION'}
    if len(raw)%32:raise ValueError('SOURCE44_NATIVE_LENGTH')
    kept=[];removed=[]
    for offset in range(0,len(raw),32):
        record=raw[offset:offset+32];day=struct.unpack_from('<I',record)[0]
        if day in dates:
            if sha(record)!=dates[day]['original_bad_row_sha256'] or struct.unpack_from('<2I',record,20)!=(0x00400000,0):raise ValueError('SOURCE44_NO_TRADE_ROW_DRIFT')
            removed.append(dict(date=day,row_sha256=sha(record),byte_offset=offset,source_record_hex=record.hex(),evidence=dates[day]))
        else:kept.append(record)
    if len(removed)!=len(dates):raise ValueError('SOURCE44_NO_TRADE_ROW_MISSING')
    return b''.join(kept),removed


def original_owner(addendum):
    main=Path(addendum['source_codes'][0]['path']).parents[1]
    for ref in addendum['source_codes']:read_code=Path(ref['path']).read_bytes();assert sha(read_code)==ref['sha256'],'SOURCE44_OWNER_DRIFT'
    sys.path.insert(0,str(main));owner=importlib.import_module('ops.a_share_daily_sync')
    if Path(owner.__file__).resolve()!=main/'ops/a_share_daily_sync.py':raise ValueError('SOURCE44_WRONG_OWNER_IMPORT')
    return owner


def prepare(batch=BATCH):
    addendum=read(dict(path=str(batch/'SOURCE44_ADDENDUM.json'),sha256='2bfcddd60b05ef3fd0fc7b56e12ca54f4a4e7aa81a953aa671978d34f6ba44fe'))
    diagnosis=read(addendum['diagnosis']);owner=original_owner(addendum)
    output=batch/'execution/source44';dot=batch/'dot_inputs/july22_correction/content/handoff/thirteen_stock_repair_20261030'
    package=batch/'dot_inputs/july22_correction/EIGHT_JULY22_CORRECTION_V1_PORTABLE_20261030.zip'
    if sha(package.read_bytes())!=diagnosis['dot_package_integrity']['expected_sha256']:raise ValueError('SOURCE44_PACKAGE_DRIFT')
    with zipfile.ZipFile(package)as archive:
        for member in archive.namelist():
            relative=Path(member)
            if member.endswith('/') or '..' in relative.parts or relative.is_absolute():continue
            path=batch/'dot_inputs/july22_correction/content'/relative
            if path.read_bytes()!=archive.read(member):raise ValueError('SOURCE44_EXTRACTED_MEMBER_DRIFT:'+member)
    sys.path.insert(0,str(dot));patch=importlib.import_module('july22_patch')
    records=read(dict(path=str(dot/'correction_v1/records.json'),sha256='04f0e2df50871a73b2f209ebf571e8ed9a07d01fba6f202a52eeb42c412414ab'))
    classifications=json.loads((dot/'all51_row_classification.json').read_bytes());corrections={row['symbol']:row for row in records}
    expected={row['symbol']:row for row in addendum['precise_original_files_readonly_until_final_activation']}
    seed=addendum['original_seed'];context=dict(path=seed['descriptor_path'],expected_sha256=seed['descriptor_sha256'],records=[])
    results=[];files=[]
    # Known representative first. The original owner verifies all source closure,
    # exact event coefficients/pairs and unchanged ratio thresholds itself.
    ordered=sorted(diagnosis['d30_44']['records'],key=lambda row:(row['symbol']!='603629.SH',row['symbol']!='002731.SZ',row['symbol']))
    for diagnosed in ordered:
        symbol=diagnosed['symbol'];binding=expected[symbol];source=Path(binding['path']);before=source.read_bytes()
        if sha(before)!=binding['expected_sha256']:raise ValueError('SOURCE44_NATIVE_DRIFT:'+symbol)
        result=dict(symbol=symbol,original_error=diagnosed['reason_code'],original_diagnosis=diagnosed['diagnosis'],source=dict(path=str(source),sha256=sha(before)),raw_source_modified=False)
        copy_bytes=before
        if symbol in corrections:
            record=corrections[symbol]
            # The portable patch public API rechecks full raw values, units,
            # symbol/date, neighbors, source SHA and actual native row/file SHA.
            copy_bytes=patch.patch_native_copy(before,record)
            copy_bytes,removed=exclude_no_trade(copy_bytes,classifications,symbol)
            result.update(correction=record,no_trade_rows_removed=removed,corrected_rows=1,source_basis='EXISTING_TDX_RAW_ARCHIVE_PRIMARY',historical_PIT=False)
        destination=output/'native_candidates'/source.parent.parent.name/'lday'/source.name
        destination.parent.mkdir(parents=True,exist_ok=True)
        if destination.exists() and destination.read_bytes()!=copy_bytes:raise ValueError('SOURCE44_COPY_CONFLICT')
        if not destination.exists():
            with destination.open('xb')as stream:stream.write(copy_bytes)
        if source.read_bytes()!=before:raise ValueError('SOURCE44_SOURCE_MOVED_DURING_COPY')
        if diagnosed['reason_code']=='CROSS_DAY_CLOSE_RATIO' or symbol in corrections:
            first=len(context['records']);bars,error=owner._local_history_status(destination,20261030,seed_evidence=context,symbol=symbol)
            violations=owner._local_field_signature_violations(destination,symbol=symbol,market=owner.MARKET_BY_PREFIX[source.name[:2]],run_id='D30_SOURCE44_ISOLATED',recorded_at='2026-10-31')
            result.update(local_history_error=error,remaining_signature_violations=violations,seed_explanations=context['records'][first:],status='ORIGINAL_LOCAL_GATE_ACCEPTED' if error is None and not violations else 'CANNOT_CONFIRM_LOCAL_GATE')
        else:
            result.update(status='EXPECTED_NO_USABLE_DAILY_BAR',usable_daily_bar=False,retry_for_price_completion=False,synthetic_bar_created=False,reason_evidence=str(batch/'source_diagnosis/D30_NO_BAR3_STATUS_EVIDENCE.json') if symbol in {'605258.SH','688121.SH','601326.SH'} else str(batch/'dot_inputs/SOP_D30_ZERO_ROWS_002717_002827_20261030.md'))
        result['candidate']=dict(path=str(destination),sha256=sha(copy_bytes));files.append(result['candidate']);results.append(result)
        put(output/'stocks'/symbol/'RESULT.json',result)
        print(json.dumps(dict(symbol=symbol,status=result['status'],error=result.get('local_history_error')),ensure_ascii=False),flush=True)
    summary=dict(schema='SOURCE44_ISOLATED_PREPARE_V1',status='ISOLATED_COMPLETE',target_date=20261030,items=results,counts={status:sum(row['status']==status for row in results)for status in sorted({row['status']for row in results})},copies=files,seed_descriptor=dict(path=seed['descriptor_path'],sha256=seed['descriptor_sha256']),source_unchanged=True,canonical_activated=False,**FLAGS)
    put(output/'PREPARE_RECEIPT.json',summary)
    return summary


def followup(batch=BATCH):
    """Repair only the newly exposed exact rows; reuse all prior captures."""
    prior=json.loads((batch/'execution/source44/PREPARE_RECEIPT.json').read_bytes())
    addendum=read(dict(path=str(batch/'SOURCE44_ADDENDUM.json'),sha256='2bfcddd60b05ef3fd0fc7b56e12ca54f4a4e7aa81a953aa671978d34f6ba44fe'))
    owner=original_owner(addendum)
    # Execute the candidate gate against the unchanged original owner namespace.
    # Every runtime dependency remains the deployed owner; no parallel producer.
    name='ops._a_share_daily_sync_parts.progress'
    path=Path(__file__).parent/'_a_share_daily_sync_parts/progress.py'
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module)
    output=batch/'execution/source44/followup-r5'
    captured=json.loads((batch/'execution/source44/tdx_pair3/CAPTURE_RECEIPT.json').read_bytes())
    captures={item['symbol']:item for item in captured['items']}
    official={item['key']:item for item in json.loads((batch/'execution/source44/evidence/PRIMARY_REFS.json').read_bytes())}
    files={};changes=[]
    for item in prior['items']:
        symbol=item['symbol'];raw=Path(item['candidate']['path']).read_bytes()
        if sha(raw)!=item['candidate']['sha256']:raise ValueError('SOURCE44_PRIOR_COPY_DRIFT')
        if symbol in ('920003.BJ','920699.BJ'):
            capture=captures[symbol];source=read(capture['capture']);rows=[row for row in source['response_rows'] if owner.day_int(row)==20260618]
            if len(rows)!=1 or source['request']!=capture['request'] or source['response_error'] is not None:raise ValueError('SOURCE44_EXACT_CAPTURE_BINDING')
            bar=rows[0]
            if not owner.valid_hq_bar(bar)[0]:raise ValueError('SOURCE44_ADDITIONAL_BAR_INVALID:'+repr(owner.valid_hq_bar(bar)))
            parts=[raw[i:i+32] for i in range(0,len(raw),32)];hits=[i for i,r in enumerate(parts) if struct.unpack_from('<I',r)[0]==20260618]
            if len(hits)!=1:raise ValueError('SOURCE44_ADDITIONAL_NATIVE_ROW')
            index=hits[0];before=parts[index];parts[index]=owner.pack_hq_bar(bar)[:28]+before[28:]
            changes.append(dict(symbol=symbol,date=20260618,kind='FULL_OHLCVA_BAD_NATIVE_REPLACED',before_row_sha256=sha(before),after_row_sha256=sha(parts[index]),before_hex=before.hex(),after_hex=parts[index].hex(),source=capture['capture'],source_request=capture['request'],source_row=bar,volume_conversion='TDX_HANDS_X_100_SHARES',price_basis='TDX_RAW_UNADJUSTED_CURRENT_CAPTURE',historical_PIT=False))
            raw=b''.join(parts)
        if symbol=='002731.SZ':
            capture=captures[symbol];source=read(capture['capture']);dates={owner.day_int(row) for row in source['response_rows']}
            if len(source['response_rows'])!=160 or min(dates)>20260430 or max(dates)<20261030:raise ValueError('SOURCE44_SUSPENSION_CAPTURE_COVERAGE')
            kept=[]
            for offset in range(0,len(raw),32):
                record=raw[offset:offset+32];day=struct.unpack_from('<I',record)[0]
                interval=next(((a,b,keys) for a,b,keys in [(20260506,20260707,['002731_resume0707']),(20260901,20261023,['002731_pause0901','002731_resume1023'])] if a<=day<b),None)
                if interval:
                    if day in dates:raise ValueError('SOURCE44_SUSPENSION_SOURCE_CONFLICT')
                    changes.append(dict(symbol=symbol,date=day,kind='OFFICIAL_SUSPENSION_NATIVE_PSEUDOBAR_EXCLUDED',before_row_sha256=sha(record),before_hex=record.hex(),source=capture['capture'],official_notices=[official[key] for key in interval[2]],historical_PIT=False,all_day_official_independent_certification=False))
                else:kept.append(record)
            raw=b''.join(kept)
        # A failed first row can mask later corruption. Reuse only the exact
        # source-bound full-field differences already measured for these 7 files.
        diff_path=batch/'execution/source44/LATENT7_FULL_FIELD_DIFF.json'
        diff_item=next((v for v in json.loads(diff_path.read_bytes()) if v['symbol']==symbol),None)
        if diff_item:
            source_ref=diff_item['source'];source_bytes=Path(source_ref['path']).read_bytes()
            if sha(source_bytes)!=source_ref['sha256']:raise ValueError('SOURCE44_FULLDIFF_SOURCE_DRIFT')
            if diff_item['source_kind']=='ORIGINAL_TDX_CURRENT_RAW_CAPTURE':
                source_rows=[dict(trade_date=owner.day_int(r),**{k:r[k] for k in ('open','high','low','close','amount')},vol=round(r['vol']*100))for r in json.loads(source_bytes)['response_rows']]
            else:
                import gzip
                source_rows=json.loads(gzip.decompress(source_bytes))
            source_by_date={r['trade_date']:r for r in source_rows};parts=[raw[i:i+32]for i in range(0,len(raw),32)]
            for difference in diff_item['all_differences']:
                if not (difference['price_change'] or difference['amount_change']):continue
                day=difference['date'];row=source_by_date[day]
                if row!=difference['source_row']:raise ValueError('SOURCE44_FULLDIFF_CAPTURE_ROW_DRIFT')
                indices=[i for i,r in enumerate(parts)if struct.unpack_from('<I',r)[0]==day]
                if len(indices)!=1:raise ValueError('SOURCE44_FULLDIFF_TARGET_ROW')
                index=indices[0];before=parts[index]
                if sha(before)!=difference['before_row_sha256']:raise ValueError('SOURCE44_FULLDIFF_BEFORE_ROW_DRIFT')
                converted=dict(year=day//10000,month=day//100%100,day=day%100,**{k:row[k]for k in ('open','high','low','close','amount')},vol=row['vol']/100)
                if not owner.valid_hq_bar(converted)[0]:raise ValueError('SOURCE44_FULLDIFF_INVALID_SOURCE_BAR')
                replacement=owner.pack_hq_bar(converted)[:28]+before[28:]
                if replacement.hex()!=difference['after_hex']:raise ValueError('SOURCE44_FULLDIFF_UNIT_PARITY')
                parts[index]=replacement
                changes.append(dict(symbol=symbol,date=day,kind='ADDITIONAL_FULL_OHLCVA_BAD_NATIVE_REPLACED',before_row_sha256=sha(before),after_row_sha256=sha(replacement),before_hex=before.hex(),after_hex=replacement.hex(),source=source_ref,source_row=row,source_basis='TDX_RAW_UNADJUSTED',historical_PIT=False,whole_field_diff_manifest=dict(path=str(diff_path),sha256=sha(diff_path.read_bytes()))))
            raw=b''.join(parts)
        if diff_item:
            # The original source files end in August/September. The accepted
            # archive-primary contract lets the original source add missing
            # whole rows; current-day admission stays with the original G4 owner.
            tail_sources=[dict(reference=diff_item['source'],rows=source_rows)]
            tail_capture_path=batch/'execution/source44/tdx_missing_tail4/CAPTURE_RECEIPT.json'
            tail_capture=next((v for v in json.loads(tail_capture_path.read_bytes())['items'] if v['symbol']==symbol),None)
            if tail_capture:
                payload=read(tail_capture['capture'])
                if tail_capture['request'].get('count')!=2 or payload['request']!=tail_capture['request'] or payload['response_error'] is not None:raise ValueError('SOURCE44_TAIL_CAPTURE_BINDING')
                tail_sources.append(dict(reference=tail_capture['capture'],rows=[dict(trade_date=owner.day_int(r),**{k:r[k]for k in ('open','high','low','close','amount')},vol=round(r['vol']*100))for r in payload['response_rows']]))
            last=struct.unpack_from('<I',raw,len(raw)-32)[0]
            for source in tail_sources:
                for row in source['rows']:
                    day=row['trade_date']
                    if not last<day<=20261029:continue
                    converted=dict(year=day//10000,month=day//100%100,day=day%100,**{k:row[k]for k in ('open','high','low','close','amount')},vol=row['vol']/100)
                    if not owner.valid_hq_bar(converted)[0]:raise ValueError('SOURCE44_TAIL_INVALID_SOURCE_BAR')
                    record=owner.pack_hq_bar(converted);raw+=record;last=day
                    changes.append(dict(symbol=symbol,date=day,kind='MISSING_TDX_RAW_HISTORY_TAIL_APPENDED',after_row_sha256=sha(record),after_hex=record.hex(),source=source['reference'],source_row=row,source_basis='TDX_RAW_UNADJUSTED',historical_PIT=False))
            if last!=20261029:raise ValueError('SOURCE44_TAIL_STILL_MISSING_D29')
        dest=output/'native_candidates'/Path(item['candidate']['path']).relative_to(batch/'execution/source44/native_candidates')
        dest.parent.mkdir(parents=True,exist_ok=True)
        if dest.exists() and dest.read_bytes()!=raw:raise ValueError('SOURCE44_FOLLOWUP_COPY_CONFLICT')
        if not dest.exists():dest.write_bytes(raw)
        files[symbol]=dict(path=str(dest),sha256=sha(raw))
    seed=json.loads(Path(addendum['original_seed']['descriptor_path']).read_bytes());seed['supplemental_tdx_seed_pairs']={}
    root=Path('/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/数据/runtime/cache/data_layer_daily_formula_increment_update_v1/official_gbbq')
    ref=lambda p:dict(path=str(p),sha256=sha(Path(p).read_bytes()))
    capture=ref(root/'capture_receipts/12ceb883bd2c4ad486687462bd3272288d49e5244724780c72a6844a45500d12.json')
    policy=ref(Path('/Users/lexi/Desktop/学习/agents调试/日更全市场前复权修复_20261024/inputs/TDX_BJ_CATEGORY_POLICY.json'))
    pair_rows=lambda symbol,pair:{str(struct.unpack_from('<I',r)[0]):sha(r) for i in range(0,len(Path(files[symbol]['path']).read_bytes()),32) for r in [Path(files[symbol]['path']).read_bytes()[i:i+32]] if struct.unpack_from('<I',r)[0] in pair}
    for symbol,pair in [('920029.BJ',[20260528,20260529]),('920100.BJ',[20260526,20260527]),('920187.BJ',[20260526,20260527]),('920208.BJ',[20260612,20260615]),('920003.BJ',[20260707,20260708]),('920699.BJ',[20260709,20260710])]:
        seed['supplemental_tdx_seed_pairs'][symbol]=dict(schema='TDX_CAPTURED_CATEGORY1_EXACT_PAIR_V1',symbol=symbol,pair_dates=pair,capture=capture,policy=policy,parser_cache=ref(root/'d413128d3054489e2a167eec1288ad25f3c92dec468e6b6e83193cebcd274cef.parquet'),parser_receipt=ref(root/'d413128d3054489e2a167eec1288ad25f3c92dec468e6b6e83193cebcd274cef.receipt.json'),raw_source=files[symbol],pair_row_sha256=pair_rows(symbol,pair),historical_PIT=False,futu_equivalence=False)
    seed['delisting_first_session_boundaries']={'002731.SZ':dict(type='SZSE_DELISTING_CONSOLIDATION_FIRST_SESSION_NO_PRICE_LIMIT',session_date=20261023,previous_session_date=20260831,official_notice=official['002731_resume1023'],raw_source=files['002731.SZ'],pair_row_sha256=pair_rows('002731.SZ',[20260831,20261023]),historical_PIT=False)}
    seed_ref=put(output/'seed-evidence-descriptor.json',seed);context=dict(path=seed_ref['path'],expected_sha256=seed_ref['sha256'],records=[]);results=[]
    for item in prior['items']:
        symbol=item['symbol'];row={**item,'candidate':files[symbol],'followup_changes':[v for v in changes if v['symbol']==symbol]}
        if item['status']!='EXPECTED_NO_USABLE_DAILY_BAR':
            first=len(context['records']);bars,error=owner._local_history_status(Path(files[symbol]['path']),20261030,seed_evidence=context,symbol=symbol)
            row.update(local_history_error=error,seed_explanations=context['records'][first:],status='ORIGINAL_LOCAL_GATE_ACCEPTED' if error is None else 'CANNOT_CONFIRM_LOCAL_GATE')
        if symbol=='301139.SZ':row.update(status='VERIFIED_DELISTED_NO_CURRENT_BAR',delisting_effective_date=20261028,official_notice=official['301139_delist1028'],retry_for_price_completion=False)
        results.append(row);print(json.dumps(dict(symbol=symbol,status=row['status'],error=row.get('local_history_error')),ensure_ascii=False),flush=True)
    result=dict(schema='SOURCE44_FOLLOWUP_PREPARE_R2',status='ISOLATED_COMPLETE',target_date=20261030,items=results,changes=changes,seed_descriptor=seed_ref,source_unchanged=True,canonical_activated=False,counts={status:sum(v['status']==status for v in results)for status in sorted({v['status']for v in results})},**FLAGS)
    put(output/'PREPARE_RECEIPT.json',result);return result


def activate_native(plan_reference,review_reference):
    """CAS only the frozen 39 native files (38 current, one historical-only) under the existing original owner."""
    import os,fcntl,stat,tempfile
    plan=read(plan_reference);review=read(review_reference)
    if (review.get('status')!='PASS' or review.get('scope_sha256')!=plan_reference['sha256'] or
            plan.get('canonical_activated') is not False):raise ValueError('SOURCE44_FINAL_REVIEW_REQUIRED')
    for reference in plan['code']:read_bytes=Path(reference['path']).read_bytes();assert sha(read_bytes)==reference['sha256'],'SOURCE44_ACTIVATION_CODE_DRIFT'
    frozen=read(dict(path=str(BATCH/'SOURCE44_ADDENDUM.json'),sha256='2bfcddd60b05ef3fd0fc7b56e12ca54f4a4e7aa81a953aa671978d34f6ba44fe'))
    allowed={row['path']:row['expected_sha256']for row in frozen['precise_original_files_readonly_until_final_activation']}
    rows=plan['native_replacements']
    if len(rows)!=39 or len({row['original']['path']for row in rows})!=39:raise ValueError('SOURCE44_ACTIVATION_EXACT_39_REQUIRED')
    historical=[row for row in rows if row.get('historical_only')]
    if len(historical)!=1 or historical[0]['symbol']!='301139.SZ':raise ValueError('SOURCE44_HISTORY_ONLY_SCOPE')
    history_bytes=Path(historical[0]['candidate']['path']).read_bytes()
    if len(history_bytes)%32 or any(struct.unpack_from('<I',history_bytes,off)[0]>=20261028 for off in range(0,len(history_bytes),32)):raise ValueError('SOURCE44_HISTORY_ONLY_HAS_POST_DELIST_BAR')
    from ops.sync_stock_history_completion import _inherited_owner_duplicate
    shared=plan['shared_owner_lock'];inherited=_inherited_owner_duplicate(shared,'20261030');fd=inherited if inherited is not None else os.open(shared['path'],os.O_RDONLY|os.O_NOFOLLOW)
    applied=[]
    def replace(path,payload,mode):
        temp_fd,temp=tempfile.mkstemp(prefix='.source44-',dir=path.parent)
        try:
            os.fchmod(temp_fd,mode)
            with os.fdopen(temp_fd,'wb')as stream:stream.write(payload);stream.flush();os.fsync(stream.fileno())
            os.replace(temp,path)
            directory=os.open(path.parent,os.O_RDONLY)
            try:os.fsync(directory)
            finally:os.close(directory)
        finally:
            if os.path.exists(temp):os.unlink(temp)
    try:
        fcntl.flock(fd,fcntl.LOCK_EX);current=os.stat(shared['path'],follow_symlinks=False);held=os.fstat(fd)
        if (held.st_dev,held.st_ino)!=(shared['device'],shared['inode']) or (current.st_dev,current.st_ino)!=(held.st_dev,held.st_ino):raise ValueError('SOURCE44_OWNER_INODE_DRIFT')
        for row in rows:
            path=Path(row['original']['path']);candidate=Path(row['candidate']['path'])
            if allowed.get(str(path))!=row['original']['sha256'] or path.is_symlink() or not stat.S_ISREG(path.stat().st_mode):raise ValueError('SOURCE44_ACTIVATION_ALLOWLIST')
            if sha(path.read_bytes())!=row['original']['sha256'] or sha(candidate.read_bytes())!=row['candidate']['sha256']:raise ValueError('SOURCE44_ACTIVATION_CAS_OR_CANDIDATE_DRIFT')
        for row in rows:
            path=Path(row['original']['path']);before=path.read_bytes();payload=Path(row['candidate']['path']).read_bytes();mode=stat.S_IMODE(path.stat().st_mode);backup=Path(row['backup']['path']);backup.parent.mkdir(parents=True,exist_ok=True)
            if backup.exists() and backup.read_bytes()!=before:raise ValueError('SOURCE44_BACKUP_CONFLICT')
            if not backup.exists():
                with backup.open('xb')as stream:stream.write(before);stream.flush();os.fsync(stream.fileno())
            if sha(before)!=row['original']['sha256']:raise ValueError('SOURCE44_IMMEDIATE_CAS_DRIFT')
            applied.append((row,before,mode));replace(path,payload,mode)
            if sha(path.read_bytes())!=row['candidate']['sha256']:raise ValueError('SOURCE44_REPLACEMENT_READBACK')
        return put(Path(plan['receipt_path']),dict(status='ACTIVATED_NATIVE39_38_CURRENT_PLUS_ONE_HISTORY_ONLY',plan=plan_reference,review=review_reference,items=rows,canonical_activated=True,source_pointers_activated=False,**FLAGS))
    except Exception:
        for row,before,mode in reversed(applied):
            path=Path(row['original']['path'])
            current_sha=sha(path.read_bytes())
            if current_sha==row['original']['sha256']:continue
            if current_sha!=row['candidate']['sha256']:raise RuntimeError('SOURCE44_ROLLBACK_CAS_CONFLICT:'+str(path))
            replace(path,before,mode)
        raise
    finally:os.close(fd)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--batch',type=Path,default=BATCH);parser.add_argument('--followup',action='store_true');parser.add_argument('--activate-plan',type=Path);parser.add_argument('--review',type=Path);args=parser.parse_args()
    if args.activate_plan:
        if args.review is None:parser.error('--review is required')
        reference=lambda p:dict(path=str(p.resolve()),sha256=sha(p.read_bytes()))
        print(json.dumps(activate_native(reference(args.activate_plan),reference(args.review)),ensure_ascii=False))
    else:(followup if args.followup else prepare)(args.batch)
