from pathlib import Path
from datetime import datetime,timezone
import futu,json,logging,hashlib
r=Path("/Users/lexi/Desktop/学习/agents调试/v4_stage_root_hk_fix_20260928/line_fix_r1/runtime_recovery_20261001/coordinator/hk_r4_acceptance_20261002/history")
requested=datetime.now(timezone.utc).isoformat()
ctx=futu.OpenQuoteContext(host="127.0.0.1",port=11111)
try:
 ret,data,key=ctx.request_history_kline("HK.00005",start="2026-09-29",end="2026-09-29",ktype=futu.KLType.K_DAY,autype=futu.AuType.NONE,max_count=1)
 result={"schema":"v4.hk_history_quote_canary.v1","provider":"FUTU_OPEND","host":"127.0.0.1","port":11111,"sdk":futu.__version__,"requested_at":requested,"received_at":datetime.now(timezone.utc).isoformat(),"code":"HK.00005","start":"2026-09-29","end":"2026-09-29","adjustment":"NONE","return_code":ret,"production_allowed":False,"orders_sent":False,"buy_gate_updated":False,"authoritative_writes":False,"membership_proven":False}
 if ret==futu.RET_OK:
  raw=data.to_json(orient="records",force_ascii=False);p=r/"futu_00005_20260929.raw.json";p.write_text(raw);result.update(rows=len(data),exact_date_all=bool(data.time_key.astype(str).str.startswith("2026-09-29").all()),raw_sha256=hashlib.sha256(p.read_bytes()).hexdigest(),status="HISTORICAL_PRICE_SAMPLE_AVAILABLE")
 else:result.update(error=str(data),status="CANNOT_CONFIRM")
 (r/"FUTU_HISTORY_CANARY.json").write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps(result,ensure_ascii=False))
finally:ctx.close()
