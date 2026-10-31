"""Mac-specific exact non-trade row exclusion, no provider/price collection."""
import hashlib,struct
import pytest
from ops.apply_d30_source_repairs import exclude_no_trade


def test_non_trade_exclusion_is_exact_symbol_date_row_sha_and_keeps_other_bytes():
    first=struct.pack('<8I',20260507,100,100,100,100,0,0,77)
    placeholder=struct.pack('<8I',20260508,100,100,100,100,0x00400000,0,99)
    last=struct.pack('<8I',20260511,100,100,100,100,0,0,88)
    rows=[dict(symbol='002731.SZ',date=20260508,classification='VERIFIED_NO_TRADE_SUSPENSION',original_bad_row_sha256=hashlib.sha256(placeholder).hexdigest())]
    derived,removed=exclude_no_trade(first+placeholder+last,rows,'002731.SZ')
    assert derived==first+last and len(removed)==1 and removed[0]['source_record_hex']==placeholder.hex()
    assert exclude_no_trade(first+placeholder+last,rows,'OTHER.SZ')[0]==first+placeholder+last
    with pytest.raises(ValueError,match='ROW_DRIFT'):exclude_no_trade(first+placeholder[:-1]+b'x'+last,rows,'002731.SZ')
    with pytest.raises(ValueError,match='ROW_MISSING'):exclude_no_trade(first+last,rows,'002731.SZ')


def activation_fixture(tmp_path,monkeypatch):
    import json
    from ops import apply_d30_source_repairs as repair
    from ops.sync_stock_history_completion import DEFAULT_OWNER_LOCK
    rows=[];original=[]
    for i in range(39):
        path=tmp_path/'native'/f'{i}.day';path.parent.mkdir(exist_ok=True);before=struct.pack('<8I',20261029,*([i+1]*7));path.write_bytes(before)
        candidate=tmp_path/f'{i}.candidate';candidate.write_bytes((struct.pack('<8I',20261027,*([i+1]*7))) if i==38 else before+struct.pack('<8I',20261030,*([i+2]*7)))
        rows.append(dict(symbol='301139.SZ' if i==38 else str(i)+'.SZ',historical_only=i==38,original=dict(path=str(path),sha256=hashlib.sha256(before).hexdigest()),candidate=dict(path=str(candidate),sha256=hashlib.sha256(candidate.read_bytes()).hexdigest()),backup=dict(path=str(tmp_path/'backup'/path.name),sha256=hashlib.sha256(before).hexdigest())))
        original.append(before)
    lock=tmp_path/'owner.lock';lock.touch();info=lock.stat()
    plan=dict(canonical_activated=False,code=[],native_replacements=rows,shared_owner_lock=dict(path=str(lock),device=info.st_dev,inode=info.st_ino),receipt_path=str(tmp_path/'activation_receipt.json'))
    planref={'path':'TEST_PLAN','sha256':'a'*64};reviewref={'path':'TEST_REVIEW','sha256':'b'*64}
    frozen=dict(precise_original_files_readonly_until_final_activation=[dict(path=r['original']['path'],expected_sha256=r['original']['sha256'])for r in rows])
    def read(ref):
        if ref==planref:return plan
        if ref==reviewref:return dict(status='PASS',scope_sha256=planref['sha256'])
        if ref['path'].endswith('SOURCE44_ADDENDUM.json'):return frozen
        raise AssertionError(ref)
    monkeypatch.setattr(repair,'read',read)
    monkeypatch.delenv('V4_SCHEDULER_LANE_FD',raising=False)
    return repair,plan,planref,reviewref,original


def test_native_activation_preflight_cas_checks_all_39_before_any_write(tmp_path,monkeypatch):
    repair,plan,p,r,before=activation_fixture(tmp_path,monkeypatch)
    plan['native_replacements'][-1]['original']['sha256']='0'*64
    with pytest.raises(ValueError,match='ALLOWLIST|CAS'):repair.activate_native(p,r)
    assert [__import__('pathlib').Path(x['original']['path']).read_bytes()for x in plan['native_replacements']]==before
    assert not (tmp_path/'backup').exists()


def test_native_activation_mid_write_error_rolls_back_only_applied_originals(tmp_path,monkeypatch):
    import os
    repair,plan,p,r,before=activation_fixture(tmp_path,monkeypatch)
    real=os.replace;calls=[]
    def fail_once(source,target):
        calls.append(str(target))
        if len(calls)==2:raise OSError('SIMULATED_SECOND_WRITE_FAILURE')
        return real(source,target)
    monkeypatch.setattr(os,'replace',fail_once)
    with pytest.raises(OSError,match='SECOND_WRITE'):repair.activate_native(p,r)
    assert [__import__('pathlib').Path(x['original']['path']).read_bytes()for x in plan['native_replacements']]==before
    assert not (tmp_path/'activation_receipt.json').exists()
    assert (tmp_path/'backup'/'0.day').read_bytes()==before[0]


def test_native_activation_includes_the_evidenced_delisted_history_without_current_bar(tmp_path,monkeypatch):
    from pathlib import Path
    repair,plan,p,r,before=activation_fixture(tmp_path,monkeypatch)
    receipt=repair.activate_native(p,r)
    assert receipt['path']==str(tmp_path/'activation_receipt.json')
    for row,original in zip(plan['native_replacements'],before):
        assert Path(row['backup']['path']).read_bytes()==original
        assert Path(row['original']['path']).read_bytes()==Path(row['candidate']['path']).read_bytes()
    historical=plan['native_replacements'][-1]
    assert historical['symbol']=='301139.SZ' and struct.unpack_from('<I',Path(historical['original']['path']).read_bytes())[0]==20261027


def test_native_activation_post_rename_directory_fsync_failure_restores_replaced_file(tmp_path,monkeypatch):
    import os,stat
    from pathlib import Path
    repair,plan,p,r,before=activation_fixture(tmp_path,monkeypatch)
    real=os.fsync;failed=[]
    def fail_directory_once(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode) and not failed:
            failed.append(True);raise OSError('SIMULATED_DIRECTORY_FSYNC_FAILURE_AFTER_RENAME')
        return real(fd)
    monkeypatch.setattr(os,'fsync',fail_directory_once)
    with pytest.raises(OSError,match='AFTER_RENAME'):repair.activate_native(p,r)
    assert [Path(x['original']['path']).read_bytes()for x in plan['native_replacements']]==before
    assert not (tmp_path/'activation_receipt.json').exists()
