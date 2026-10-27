"""Manual-request isolated source preparation; not original daily run or a release."""
from pathlib import Path
import importlib.util,json,datetime,shutil,hashlib
O=Path(__file__).resolve().parent; B=O.parent; R=B.parent.parent; src=B/'daily_entry/acquire.py'
assert hashlib.sha256(src.read_bytes()).hexdigest()=='f437f554a80fd360277779796628da91e4da76a98b49c73ce13e33da81ffbfbc'
s=importlib.util.spec_from_file_location('manual_source_acquire',src);A=importlib.util.module_from_spec(s);s.loader.exec_module(A);P=A.P
receipt={'started_utc':A.now(),'purpose':'new user manual webpage display research request; source preparation only','published':False,'formula_calls':0,'fit_calls':0}
try:
 assert shutil.disk_usage(O).free-128*1024**2>=3*1024**3
 objs=O/'source_objects';objs.mkdir(exist_ok=True)
 priorfile=O/'GBBQ_SOURCE_RECORD.json'
 prior=P.load(priorfile) if priorfile.exists() else P.load(B/'daily_entry/acquired/GBBQ_SOURCE_STATE.json')
 rights=A.acquire_url('https://www.tdx.com.cn/products/data/data/dbf/gbbq.zip',objs,prior)
 P.save(priorfile,rights)
 constants=B.parent/'data/gbbq_public_format_constants.bin';assert P.sha(constants)=='2cdbe88a76fd70bdb3338d1cf5e2400e16412994c8cf5e1eafbefe2dcabd2e45'
 engine=P.engines()[0];decoder=B.parent/'data/data_engine.py'
 events_path,events,reused=A.cached_events(Path(rights['path']).read_bytes(),rights['sha256'],objs,engine,constants,P.sha(decoder))
 d26=P.load(B/'daily_entry/acquired/20261026/CANDIDATE_CONFIG.json')['events'];old=P.load(P.pinned(d26));changed=A.changed_symbols(old,events)
 receipt.update(status='EVENT_SOURCE_CANDIDATE_NOT_ADMITTED',source=rights,events=P.file_record(O,events_path),decoder_sha256=P.sha(decoder),constants_sha256=P.sha(constants),decode_cache_reused=reused,D26_events=d26,changed_symbols_all_events=changed,changed_count=len(changed),D27_events_count=len(events),free_after=shutil.disk_usage(O).free)
except Exception as e:receipt.update(status='PREPARATION_BLOCKED',error=type(e).__name__+': '+str(e))
receipt['finished_utc']=A.now();P.save(O/'EVENTS_SOURCE_PREPARATION.json',receipt);print(json.dumps(receipt,ensure_ascii=False,indent=2))
