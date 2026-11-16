import hashlib, importlib.util, json, sys, tempfile
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
BASELINE=ROOT/"baseline/sandbox/v0_2_impl"
MOD_PATH=HERE/"build_v0_2.py"
spec=importlib.util.spec_from_file_location("p515_candidate_build", MOD_PATH)
b=importlib.util.module_from_spec(spec); sys.modules[spec.name]=b; spec.loader.exec_module(b)
b.ROOT=HERE

def load_rows_for_fixture(cal, ids):
    rows=[]
    for i in ids:
        base=(dict(open=10.,high=10.2,low=9.95,close=10.1,volume=1000.) if i<20 else
              dict(open=10.,high=10.5,low=9.95,close=10.45,volume=2600.) if i==20 else
              dict(open=10.2,high=10.4,low=10.,close=10.3,volume=1050.))
        rows.append(dict(trade_date=cal[i],user_v1_B1=None,**base))
    return rows

def build_fixture(key, ids, mutate=None):
    cal=b.load_calendar()[:35]; rows=load_rows_for_fixture(cal,ids)
    if mutate: mutate(rows,cal)
    with tempfile.TemporaryDirectory() as d:
        res=b.build(rows,cal,"fixture",d,captured_at="2026-11-16T00:00:00+08:00")
    fam=res["events"].query("event_namespace == 'R2_RESEARCH_FAMILY'").iloc[0]
    out=res["outcomes"].loc[res["outcomes"].event_id==fam.event_id].iloc[0]
    return fam,out

# The same open event as the red fixture must build with no terminal date,
# a provisional high based only on dates through its own observed prefix,
# and right censoring at that snapshot.
open_event,open_out=build_fixture("open",range(21))
assert open_event.terminal_rule_outcome=="UNKNOWN_OPEN_AT_SNAPSHOT"
assert open_event.terminal_date is None
assert open_event.reference_lock_status=="PROVISIONAL_RUNNING"
assert open_event.reference_high==10.5
assert open_out.censoring_status=="RIGHT_CENSORED_AT_D"

# A missing exchange session ends the event as UNKNOWN_DATA_GAP.
# A later, unrelated bar has an extreme high; it must not enter this
# old event's provisional reference.
def inject_gap_and_later_extreme(rows,cal):
    rows[:]=load_rows_for_fixture(cal,[*range(24),25])
    rows[22].update(high=10.8)
    rows[-1].update(open=10.2,high=999.,low=10.,close=10.3,volume=1050.)
gap_event,gap_out=build_fixture("gap",[*range(24),25],inject_gap_and_later_extreme)
assert gap_event.terminal_rule_outcome=="UNKNOWN_DATA_GAP"
assert gap_event.terminal_date is None
assert gap_event.reference_lock_status=="PROVISIONAL_RUNNING"
assert gap_event.reference_end_date==b.load_calendar()[22]
assert gap_event.reference_high==10.8
assert gap_out.censoring_status=="UNKNOWN"

# Rebuild unchanged archived 001219.SZ under fixed original capture time and
# require exact bytes for the released three-table contract.
rows=b.load_bars(); cal=b.load_calendar()
source_sha=b.sha256_file(b.BARS_PATH)
with tempfile.TemporaryDirectory() as d:
    b.build(rows,cal,source_sha,d,captured_at="2026-11-15T22:28:09+08:00")
    exact={}
    for name in ("EVENT_LEDGER_V0_2.csv","DAILY_STATE_OBSERVATIONS_V0_2.csv","OUTCOME_LEDGER_V0_2.csv"):
        got=Path(d,name).read_bytes(); original=(BASELINE/name).read_bytes()
        exact[name]={"candidate_sha256":hashlib.sha256(got).hexdigest(),
                     "baseline_sha256":hashlib.sha256(original).hexdigest(),
                     "exact_bytes":got==original}
        assert got==original,name

receipt={
  "status":"PASS",
  "owner":"CODEX_MAC",
  "patch_sha256":hashlib.sha256((HERE/"build_v0_2.patch").read_bytes()).hexdigest(),
  "tests":{
    "OPEN_NULL_END_BUILDER":"PASS",
    "GAP_UNKNOWN_CENSORING":"PASS",
    "LATER_EXTREME_EXCLUDED_FROM_OLD_EVENT_REFERENCE":"PASS",
    "ARCHIVED_001219_THREE_TABLE_BYTE_PARITY":"PASS"
  },
  "baseline_byte_parity":exact,
  "scope":{"fit":0,"preprocessor_fit":0,"predict":0,"new_weights":0,"labels_changed":0,
           "production_changes":0,"frozen_asset_changes":0}
}
(HERE/"CANDIDATE_TEST_RECEIPT.json").write_text(json.dumps(receipt,indent=2)+"\n")
print(json.dumps(receipt,indent=2))

