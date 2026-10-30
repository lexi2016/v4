"""One aligned launchd invocation. Exclusive lock, stored completion, no daemon."""
from datetime import datetime,timedelta
import argparse
import fcntl
import json
from pathlib import Path

from contracts.trading_calendar import load_market_calendar,resolve_market_states,TradingDayState,previous_session
from infrastructure.research_workbench_host import checked,FLAGS,next_workbench_session
from ops.collect_workbench_observations import SH,collect,publish,digest,put

SLOTS=tuple(['0800','0810','0915','0925']+[f'{m//60:02d}{m%60:02d}' for m in range(570,691,10)]+[f'{m//60:02d}{m%60:02d}' for m in range(780,901,10)]+['1540','1610','1640','1700','1900'])


def due(now):
    """Never backfill missed intraday clocks with a later observation."""
    return next((s for s in SLOTS if 0<=now.hour*60+now.minute-(int(s[:2])*60+int(s[2:]))<2),None)


def run(config,*,now=None,collector=collect,manual=False):
    now=now or datetime.now(SH);day=now.date().isoformat();root=Path(config['state_root'])
    try:
        calendar_ref=config.get('calendar')
        if calendar_ref:checked(calendar_ref)
        calendar=load_market_calendar(Path(calendar_ref['path']) if calendar_ref else None)
        state=resolve_market_states(calendar,now.strftime('%Y%m%d')).get('a_share')
        if state==TradingDayState.UNKNOWN:return dict(status='CANNOT_CONFIRM',error='MARKET_CALENDAR_OUT_OF_RANGE',**FLAGS)
    except ValueError as error:return dict(status='CANNOT_CONFIRM',error=str(error),**FLAGS)
    if state not in {TradingDayState.FULL_TRADING_DAY,TradingDayState.HALF_TRADING_DAY_AM}:return dict(status='SKIP_NON_TRADING_DAY',**FLAGS)
    slot=now.strftime('%H%M') if manual else due(now)
    if slot is None:return dict(status='SKIP_OUTSIDE_NODE',**FLAGS)
    root.mkdir(parents=True,exist_ok=True)
    with (root/'.capture.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return dict(status='BUSY',**FLAGS)
        # Resolve actual latest committed source. Never guess source_date+1.
        index=json.loads((Path(config['product_root'])/'index.json').read_text());date=previous_session(calendar,now.strftime('%Y%m%d'),market='a_share')
        if date not in index['dates']:return dict(status='CANNOT_CONFIRM',error='PREVIOUS_SESSION_PRODUCT_MISSING',required_source_date=date,**FLAGS)
        mf=checked(index['dates'][date]);product=checked(mf['artifact'])
        source_date=f'{date[:4]}-{date[4:6]}-{date[6:]}'
        binding=checked(config['host_binding']);entry=binding.get('observation_dates',{}).get(source_date)
        if entry:
            if entry.get('date')!=day:return dict(status='CANNOT_CONFIRM',error='OBSERVATION_DATE_BINDING_CONFLICT',**FLAGS)
            checked(entry['authority'])
        elif not binding.get('calendar') or binding.get('calendar')!=calendar_ref:
            return dict(status='CANNOT_CONFIRM',error='OBSERVATION_CALENDAR_BINDING_MISSING',**FLAGS)
        identity=dict(source_date=source_date,generation=product['source_generation'],input_sha256=product['source_identity']['input_sha256'])
        commit=root/day/slot/'commit.json';attempt_path=root/day/slot/'attempt.json'
        previous=json.loads(commit.read_text()) if commit.exists() else None
        if previous:
            snapshot=checked(previous['snapshot']);kr=checked(previous['korea'])
            if any(snapshot.get(k)!=v for k,v in {'source_generation':identity['generation'],'input_sha256':identity['input_sha256']}.items()):raise ValueError('WORKBENCH_SLOT_SOURCE_CONFLICT')
            if all(not r.get('error') for r in snapshot['rows']) and all(r.get('value') is not None for r in kr['indices']):return dict(status='ALREADY_COMMITTED',pointer=previous,**FLAGS)
        attempts=json.loads(attempt_path.read_text()).get('attempts',0) if attempt_path.exists() else 0
        if attempts>=2:return dict(status='DIAGNOSIS_REQUIRED',error='TWO_SLOT_ATTEMPTS_EXHAUSTED',pointer=previous,**FLAGS)
        put(attempt_path,dict(attempts=attempts+1,started_at=now.isoformat(),status='RUNNING',**FLAGS))
        symbols=[r['symbol'] for r in product['rows']]
        official_input=None
        if config.get('official_input_root'):
            path=Path(config['official_input_root'])/now.strftime('%Y%m%d')/'input.json'
            if path.is_file():
                import hashlib
                official_input=dict(path=str(path.resolve()),sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        kwargs=dict(now=now,official_input=official_input,prior_snapshot=snapshot if previous else None,prior_korea=kr if previous else None)
        saved_kr=config.get('korea_raw',{}).get(day)
        if saved_kr:
            def read_saved(url):
                symbol='^KS11' if 'KS11' in url else '^KQ11'
                return json.dumps(checked(saved_kr[symbol])).encode()
            kwargs['kr_read']=read_saved
        snapshot,kr,raw=collector(day,slot,identity,symbols,**kwargs)
        if saved_kr:kr['saved_source_refs']=saved_kr
        pointer=publish(root,snapshot,kr,raw);put(commit,pointer)
        put(attempt_path,dict(attempts=attempts+1,finished_at=snapshot['recorded_at'],status='COMMITTED',pointer=pointer,**FLAGS))
        future=[datetime.fromisoformat(day+'T'+s[:2]+':'+s[2:]+':00+08:00') for s in SLOTS]
        next_due=next((t.isoformat() for t in future if t>now),None)
        if next_due is None:
            try:
                following=next_workbench_session(calendar,now.strftime('%Y%m%d'))
                next_due=f'{following[:4]}-{following[4:6]}-{following[6:]}T08:00:00+08:00'
            except ValueError:next_due='CANNOT_CONFIRM_NEXT_CALENDAR_YEAR'
        return dict(status='COMMITTED' if all(not r.get('error') for r in snapshot['rows']) else 'PARTIAL_STORED_INTRADAY_SOURCE_BLOCKED',pointer=pointer,valid=sum(not r.get('error') for r in snapshot['rows']),scope=len(symbols),next_slot=next_due,manual=manual,**FLAGS)


def main():
    p=argparse.ArgumentParser();p.add_argument('--config',type=Path,required=True);p.add_argument('--config-sha256',required=True);p.add_argument('--manual-current',action='store_true');a=p.parse_args()
    config=checked(dict(path=str(a.config.resolve()),sha256=a.config_sha256))
    if any(config.get(k)!=v for k,v in FLAGS.items()):raise ValueError('WORKBENCH_COLLECTOR_SAFETY_CONFLICT')
    print(json.dumps(run(config,manual=a.manual_current),ensure_ascii=False))


if __name__=='__main__':main()
