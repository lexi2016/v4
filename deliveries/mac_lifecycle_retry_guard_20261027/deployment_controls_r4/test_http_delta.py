from types import SimpleNamespace
import pytest
import controller as c

def build(tmp_path):
 x=c.Capsule.__new__(c.Capsule);p=tmp_path/'saved.json';p.write_text('{"rows":[{"close":1.0}]}')
 x.p={'saved_000523_envelope':str(p)};x.baseline_http={k:{'cannot_confirm':['ORIGINAL_QUARANTINE:old-timeout']} for k in ('601198.SH','601059.SH')}
 x.j=SimpleNamespace(record=lambda *a,**kw:None)
 def response(code,phase):
  if code=='000523.SZ':return {'rows':[{'close':1.0}]}
  return {'status':'CANNOT_CONFIRM','rows':[],'cannot_confirm':['ORIGINAL_QUARANTINE:old-timeout','官方摘牌日期：2026-10-19；原状态保留']}
 x.history_http=response;return x

def test_new_root_three_http_oracle_passes_without_formula_or_provider(tmp_path):build(tmp_path).bounded_http()

def test_new_root_http_rejects_erased_old_error(tmp_path):
 x=build(tmp_path);original=x.history_http
 x.history_http=lambda code,phase:{**original(code,phase),'cannot_confirm':['官方摘牌日期：2026-10-19']} if code!='000523.SZ' else original(code,phase)
 with pytest.raises(c.Stop,match='OLD_ERROR'):x.bounded_http()

def test_new_root_http_rejects_synthesized_bar(tmp_path):
 x=build(tmp_path);original=x.history_http
 x.history_http=lambda code,phase:{**original(code,phase),'rows':[{'close':0}]} if code!='000523.SZ' else original(code,phase)
 with pytest.raises(c.Stop,match='SYNTHESIZE'):x.bounded_http()

def test_new_root_http_rejects_changed_accepted_76_envelope(tmp_path):
 x=build(tmp_path);original=x.history_http
 x.history_http=lambda code,phase:{'rows':[{'close':9.0}]} if code=='000523.SZ' else original(code,phase)
 with pytest.raises(c.Stop,match='ENVELOPE_MISMATCH'):x.bounded_http()
