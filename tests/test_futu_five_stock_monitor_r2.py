"""SIMULATION only. No live quotes, notification, or account APIs are used."""
from copy import deepcopy
from datetime import datetime, timedelta
import inspect
import unittest
from unittest.mock import patch

import pandas as pd

from ops.futu_five_stock_monitor_r2.config import STOCKS, STREAMS
from ops.futu_five_stock_monitor_r2.engine import Engine, TZ, daily_closed, local_time, session
from ops.futu_five_stock_monitor_r2.formulas import calculate, indicators, recursive, rules
from ops.futu_five_stock_monitor_r2 import runtime


def stamp(h=9,m=30,s=0,day=23):
    return datetime(2026,11,day,h,m,s,tzinfo=TZ)


def feature_rows():
    return [dict(close=100.,open=99.,low=99.,high=101.,volume=100.,
                 white=102.,yellow=101.,bbi=103.,j=10.) for _ in range(8)]


def daily_rows():
    base = datetime(2026,1,1)
    return [dict(code="SZ.300893",time_key=str((base+timedelta(days=i)).date())+" 00:00:00",
                 open=10.,close=10.,high=11.,low=9.,volume=100.) for i in range(116)]


class FormulaTests(unittest.TestCase):
    def test_b1_all_three_and_inclusive_j(self):
        f=feature_rows()
        f[-1]["j"]=13
        self.assertTrue(rules(f)["B1买点候选"])
        for field,value in (("j",13.0001),("bbi",102),("white",101)):
            g=deepcopy(f);g[-1][field]=value
            self.assertFalse(rules(g)["B1买点候选"])

    def test_b2_independent_contexts_and_exact_boundaries(self):
        f=feature_rows()
        self.assertTrue(rules(f)["B2_1006_ORAL_CONTEXT"])
        self.assertFalse(rules(f)["B2_151_VOLUME_CONTEXT"])
        f[-1]["volume"]=120
        self.assertFalse(rules(f)["B2_151_VOLUME_CONTEXT"])
        f[-1]["volume"]=126;f[-1]["close"]=104
        self.assertFalse(rules(f)["B2_USER_EXACT_CANDIDATE"])  # exactly 4%
        f[-1]["close"]=104.01;f[-1]["bbi"]=0;f[-1]["j"]=69
        self.assertTrue(rules(f)["B2_USER_EXACT_CANDIDATE"])  # No B1 gate.
        for field,value in (("volume",125),("j",70),("white",101)):
            g=deepcopy(f);g[-1][field]=value
            self.assertFalse(rules(g)["B2_USER_EXACT_CANDIDATE"])
        for lag in range(3): f[-1-lag]["j"]=13
        self.assertFalse(rules(f)["B2_USER_EXACT_CANDIDATE"])  # strict COUNT J<13

    def test_b3_original_no_new_high_gate(self):
        f=feature_rows();f[-2]["close"]=104;f[-2]["volume"]=116
        f[-1]["close"]=104;f[-1]["volume"]=104.4  # exactly 0.9 -> false
        f[-2]["high"]=200  # no yesterday breakout requirement
        self.assertFalse(rules(f)["B3买点候选"])
        f[-1]["volume"]=104.5
        self.assertTrue(rules(f)["B3买点候选"])
        f[-1]["volume"]=69.6  # exactly .6 -> false
        self.assertFalse(rules(f)["B3买点候选"])
        f[-1]["volume"]=69.5
        self.assertTrue(rules(f)["B3买点候选"])
        f[-2]["volume"]=115  # exactly 1.15 -> false
        self.assertFalse(rules(f)["B3买点候选"])
        f[-2]["volume"]=116;f[-1]["close"]=100.88 # exactly -3%
        self.assertFalse(rules(f)["B3买点候选"])
        f[-1]["close"]=105;f[-2]["close"]=103 # exactly yesterday 3%
        self.assertFalse(rules(f)["B3买点候选"])

    def test_sell_guard_cross_and_ratio(self):
        f=feature_rows();f[-1]["close"]=98
        r=rules(f)
        self.assertTrue(r["守线失守风险"]);self.assertTrue(r["破前低风险"])
        self.assertTrue(r["卖点公式完整命中"])
        f[-1]["close"]=98.01 # .99 of prior low99, equality false
        self.assertFalse(rules(f)["破前低风险"])
        f[-1]["white"]=100
        self.assertTrue(rules(f)["白黄线死叉"])
        f[-2]["white"]=101
        self.assertFalse(rules(f)["白黄线死叉"])  # yesterday strict >
        f=feature_rows();f[-3]["high"]=90;f[-2]["low"]=95;f[-1]["close"]=92
        self.assertFalse(rules(f)["守线失守风险"]) # gap uses previous HIGH90

    def test_warmup_missing_zero_denominator_and_seed(self):
        rows=daily_rows()
        self.assertEqual(calculate(rows[:113])["status"],"UNKNOWN")
        self.assertEqual(calculate(rows)["last"]["ma60"],10)
        self.assertEqual(calculate(rows)["last"]["yellow"],10)
        self.assertEqual(calculate(rows)["last"]["j"],50)
        self.assertEqual(recursive([None,10,20],1/3),[None,10,40/3])
        rows[-1]["close"]=None
        self.assertEqual(calculate(rows)["status"],"UNKNOWN")
        rows=daily_rows()
        for r in rows:r.update(low=10,high=10)
        self.assertIsNone(calculate(rows)["rules"]["B1买点候选"])
        f=feature_rows();f[-2]["volume"]=0;f[-1]["close"]=99
        self.assertIsNone(rules(f)["B3买点候选"])
        f[-1]["volume"]=0
        self.assertIsNone(rules(f)["B3买点候选"])  # Decimal 0/0, no exception.


class EventTests(unittest.TestCase):
    def setUp(self):
        self.alerts=[];self.e=Engine(self.alerts.append,simulation=True)
    def tick(self,price,seq,second,**kwargs):
        row=dict(code="SZ.300893",price=price,sequence=seq,time=str(stamp(s=second)),
                 push_data_type="REALTIME",type="AUTO_MATCH")
        row.update(kwargs)
        self.e.tick(row,stamp(s=second)+timedelta(seconds=1),"MORNING",subscribed=True)
    def test_true_path_dedupe_and_rebreak(self):
        self.tick(15.1,1,0);self.tick(15.03,2,1);self.tick(15.02,3,2);self.tick(15.05,4,3)
        p=self.e.states["SZ.300893"].paths[15.04]
        self.assertEqual(p.minimum,15.02)
        self.assertEqual(p.broken_price,15.03)
        self.assertEqual(p.recovered_at,stamp(s=3))
        self.tick(15.01,5,4);self.tick(15.0,6,5)
        alerts=[a for a in self.alerts if a["level"]==15.04]
        self.assertEqual(sum(a["type"]=="支撑失守风险" for a in alerts),1)
        self.assertEqual(sum(a["type"]=="收回后再次失守" for a in alerts),1)
        self.assertTrue(all(a["title"].startswith("SIMULATION") for a in alerts))
        self.assertTrue(all(k in alerts[0] for k in ("price","currency","time","reason","key_k","next_step")))
    def test_cached_delayed_reconnect_reset(self):
        self.tick(15.1,1,0);self.tick(15.03,2,1)
        self.tick(15.02,3,2,push_data_type="CACHE")
        self.tick(15.05,4,3)
        self.assertNotIn(15.04,self.e.states["SZ.300893"].paths)
        self.assertFalse(any("后收回" in a["type"] for a in self.alerts))
        self.tick(15.03,5,4);self.e.reset_paths();self.tick(15.05,6,5)
        self.assertFalse(any("后收回" in a["type"] for a in self.alerts))
    def test_stale_wrong_permission_and_market(self):
        row=dict(code="HK.07666",price=6,sequence=1,time=str(stamp()),push_data_type="REALTIME",type="AUTO_MATCH")
        for market,right,now in (("CLOSED","LV2",stamp()),("MORNING","BMP",stamp()),("MORNING","LV2",stamp(s=30))):
            self.e.tick(row,now,market,right,subscribed=True)
        self.assertEqual(self.alerts,[])
        self.assertIsNone(session("HK.07666",stamp(h=12,m=30),"REST"))
        self.assertIsNone(session("SZ.300893",stamp(h=11,m=45),"MORNING"))
    def test_complete_five_minute_only_and_repeat_failure(self):
        self.tick(15.1,1,0);self.tick(15.03,2,1);self.tick(15.05,3,3)
        bars=[dict(time_key="2026-11-23 09:35:00",low=15.05,close=15.06)]
        self.e.five_minute("SZ.300893",bars,stamp(m=36))
        self.assertFalse(any(a["priority"]=="P1" for a in self.alerts))
        bars += [dict(time_key="2026-11-23 09:40:00",low=15.04,close=15.06),
                 dict(time_key="2026-11-23 09:45:00",low=15.06,close=15.08)]
        self.e.five_minute("SZ.300893",bars,stamp(m=41))
        self.assertEqual(sum(a["priority"]=="P1" for a in self.alerts),1)
        self.e.five_minute("SZ.300893",bars,stamp(m=46))
        self.assertEqual(sum(a["priority"]=="P1" for a in self.alerts),1)
    def test_daily_closed_hk_cas_and_today(self):
        self.assertFalse(daily_closed("HK.07666",stamp(h=16,m=1),"HK_CAS",stamp(h=16)))
        self.assertFalse(daily_closed("HK.07666",stamp(h=16,m=11),"CLOSED",stamp(h=16,day=20)))
        self.assertTrue(daily_closed("HK.07666",stamp(h=16,m=11),"CLOSED",stamp(h=16)))
        self.assertTrue(daily_closed("SZ.300893",stamp(h=15,m=1),"STIB_AFTER_HOURS_END",stamp(h=15)))
        result={"status":"READY","rules":{"卖点公式完整命中":True,"B2_151_VOLUME_CONTEXT":True,"B1买点候选":True}}
        self.e.formula("HK.07666",result,stamp(),6.5)
        self.assertTrue(all("HK_REFERENCE_ONLY" in a["reason"] for a in self.alerts))
        self.assertEqual(next(a for a in self.alerts if a["type"].startswith("B2_151"))["priority"],"P2")
        self.assertTrue(all("盘中形成中" in a["type"] for a in self.alerts))
    def test_new_day_resets_but_lunch_preserves_dedupe(self):
        self.tick(15.1,1,0);self.tick(15.03,2,1)
        n=len(self.alerts);self.e.reset_paths()
        self.e.price("SZ.300893",15.02,stamp(h=13,m=1))
        self.assertEqual(len(self.alerts),n)
        self.e.price("SZ.300893",15.02,stamp(day=24))
        self.assertEqual(len(self.alerts),n+1)

    def test_all_five_fixed_risk_and_upward_levels_currency(self):
        self.e.price("SZ.300893",15.30,stamp())
        self.assertTrue(any(a["type"]=="回踩观察" for a in self.alerts))
        for code,stock in STOCKS.items():
            self.e.price(code,stock.risk-0.001,stamp(),stock.risk+0.001)
            for level,_ in stock.rises:
                self.e.price(code,level+0.001,stamp(),level-0.001)
            selected=[a for a in self.alerts if a["code"]==code]
            self.assertTrue(any(a["priority"]=="P0" and a["level"]==stock.risk for a in selected))
            self.assertEqual(sum(a["level"] in {l for l,_ in stock.rises} for a in selected),len(stock.rises))
            self.assertTrue(all(a["currency"]==("HKD" if code.startswith("HK.") else "CNY") for a in selected))

    def test_same_second_sequence_orders_reclaim_and_start_below_unknown(self):
        self.tick(15.1,1,0);self.tick(15.03,2,1);self.tick(15.05,3,1)
        self.assertTrue(any("后收回" in a["type"] for a in self.alerts))
        other=Engine(lambda _:None)
        for seq,price in enumerate((15,15.01,15.1),1):
            other.tick(dict(code="SZ.300893",price=price,sequence=seq,time=str(stamp(s=seq)),
                            push_data_type="REALTIME",type="AUTO_MATCH"),stamp(s=seq+1),"MORNING",subscribed=True)
        self.assertNotIn(15.04,other.states["SZ.300893"].paths)

    def test_a_unknown_types_and_colon_milliseconds_first_risk(self):
        self.assertEqual(local_time("2026-11-23 09:30:00:123").microsecond,123000)
        for code in ("SZ.000610","SZ.002865","SZ.300920","SZ.300893"):
            risk=STOCKS[code].risk
            for seq,(price,ticktype) in enumerate(((risk-0.01,"UNKNOWN"),(risk-0.02,"N/A"),(risk+0.01,"UNKNOWN")),1):
                self.e.tick(dict(code=code,price=price,sequence=seq,time=f"2026-11-23 09:30:0{seq}:123",
                                 push_data_type="REALTIME",type=ticktype),stamp(s=seq+1),"MORNING",subscribed=True)
            self.assertTrue(any(a["code"]==code and "路径UNKNOWN" in a["reason"] for a in self.alerts))
            self.assertFalse(any(a["code"]==code and "后收回" in a["type"] for a in self.alerts))
        before=len(self.alerts)
        self.tick(14,10,10,type="LATE")
        self.tick(14,11,11,type="UNKNOWN",push_data_type="BYDISCONN")
        self.assertEqual(len(self.alerts),before)


class RuntimeTests(unittest.TestCase):
    def test_notification_argv_silent_and_injection_safe(self):
        with patch.object(runtime.subprocess,"run") as run,patch.object(runtime,"report"):
            runtime.notification(dict(title='SIMULATION " & exit',body='x" & do shell script "bad'))
        args,kwargs=run.call_args
        self.assertEqual(args[0][:2],["/usr/bin/osascript","-"])
        self.assertNotIn("sound",kwargs["input"])
        self.assertNotIn("bad",kwargs["input"])
    def test_qfq_anchor_dates_codes_and_shares(self):
        rows=daily_rows();last=rows[-1]
        quote=dict(code="SZ.300893",data_date=last["time_key"][:10],last_price=10,open_price=10,high_price=11,low_price=9,volume=100)
        self.assertTrue(runtime.aligned_daily("SZ.300893",rows,quote)[0])
        for key,value in (("volume",1),("data_date","2026-11-23"),("code","HK.07666"),("last_price",None)):
            q=quote.copy();q[key]=value
            self.assertFalse(runtime.aligned_daily("SZ.300893",rows,q)[0])
    def test_only_local_quote_context_no_trading_or_user_writes(self):
        source=inspect.getsource(runtime)
        self.assertNotIn("TradeContext",source)
        for bad in ("place_order", "unlock_trade", "modify_user_security", "set_price_reminder", "unsubscribe_all("):
            self.assertNotIn(bad,source)
        self.assertEqual(len(STOCKS),5)
        self.assertEqual(set(STREAMS),{"QUOTE","K_1M","K_5M","K_DAY","TICKER"})
    def test_connect_subscribes_every_stream_and_close_only_owned_context(self):
        import futu as ft
        class Fake:
            def __init__(self):self.calls=[];self.closed=0
            def set_handler(self,h):pass
            def subscribe(self,codes,streams,**kwargs):self.calls.append((codes,streams,kwargs));return 0,None
            def close(self):self.closed+=1
        fake=Fake()
        consumer=runtime.Consumer(ft,Engine(lambda _:None))
        with patch.object(runtime,"_default_context",return_value=fake),patch.object(consumer,"refresh"):
            consumer.connect()
        self.assertEqual(len(fake.calls),10)
        self.assertEqual({s[0] for _,s,_ in fake.calls},set(STREAMS))
        self.assertEqual(sum(len(c)*len(s) for c,s,_ in fake.calls),25)
        self.assertTrue(all(len({x.startswith("HK.") for x in c})==1 and not kw["is_first_push"] for c,_,kw in fake.calls))
        consumer.close();consumer.close();self.assertEqual(fake.closed,1)

    def test_check_never_notifies_even_when_callback_would_trigger(self):
        class FakeConsumer:
            def __init__(self,ft,engine):self.engine=engine;self.market_states={};self.authority_ticks={}
            def connect(self):
                self.engine.emit("SZ.300893",stamp(),15,"SIMULATION","P0",15.04,"fixture","fixture")
            def drain(self):pass
            def refresh(self):pass
            def inspect_daily(self,alerts=True):
                self.assert_silent=not alerts
                return [{"ready":False}]*5
            def close(self):pass
        with patch.object(runtime,"Consumer",FakeConsumer),patch.object(runtime,"notification") as notify,patch.object(runtime,"report"):
            self.assertEqual(runtime.main(["--check"]),2)
        notify.assert_not_called()

    def test_foreground_reconnect_and_keyboard_stop(self):
        constructed=[]
        class FakeConsumer:
            def __init__(self,ft,engine):self.closed=0;constructed.append(self)
            def connect(self):
                if len(constructed)==1:raise ConnectionError("SIMULATION disconnect")
                raise KeyboardInterrupt()
            def close(self):self.closed+=1
        with patch.object(runtime,"Consumer",FakeConsumer),patch.object(runtime.clock,"sleep"),patch.object(runtime,"report"):
            self.assertEqual(runtime.main([]),0)
        self.assertEqual(len(constructed),2)
        self.assertTrue(all(c.closed for c in constructed))

    def test_a_closing_uses_today_connection_authority_after_path_reset(self):
        import futu as ft
        alerts=[];engine=Engine(alerts.append,simulation=True)
        consumer=runtime.Consumer(ft,engine)
        now=stamp(h=15,m=31)
        consumer.health_at=now;consumer.health_ok=True
        consumer.connected_at=stamp(h=9)
        consumer.market_states={c:"STIB_AFTER_HOURS_END" for c in STOCKS}
        consumer.subscriptions={(c,s):True for c in STOCKS for s in STREAMS}
        consumer.authority_ticks["SZ.300893"]=stamp(h=14,m=59)
        engine.reset_paths()
        rows=daily_rows();rows[-1]["time_key"]="2026-11-23 00:00:00"
        quote=dict(code="SZ.300893",data_date="2026-11-23",data_time="15:00:00",last_price=10,
                   open_price=10,high_price=11,low_price=9,volume=100,suspension=False)
        class FakeContext:
            def get_stock_quote(self,codes):return 0,pd.DataFrame([quote])
            def get_cur_kline(self,code,*args):return 0,pd.DataFrame(rows)
        consumer.context=FakeContext()
        consumer.subscriptions={(c,s):True for c in STOCKS for s in STREAMS}
        with patch.object(runtime,"datetime") as dt,patch.object(runtime,"report"):
            dt.now.return_value=now
            evidence=consumer.inspect_daily()
        e=next(r for r in evidence if r["code"]=="SZ.300893")
        self.assertTrue(e["quote_authority_capable"])
        self.assertFalse(e["realtime_confirmed"])
        self.assertTrue(e["ready"])
        self.assertTrue(any(a["type"]=="原锚正式失效｜收盘确认" for a in alerts))
        consumer.authority_ticks.clear()  # New connection or explicit denial.
        with patch.object(runtime,"datetime") as dt,patch.object(runtime,"report"):
            dt.now.return_value=now
            evidence=consumer.inspect_daily()
        self.assertFalse(next(r for r in evidence if r["code"]=="SZ.300893")["ready"])

    def test_idle_monitor_skips_daily_windows(self):
        import futu as ft
        consumer=runtime.Consumer(ft,Engine(lambda _:None))
        class FakeContext:
            def get_stock_quote(self,codes):return 0,pd.DataFrame([{"code":c} for c in codes])
            def get_cur_kline(self,*args):raise AssertionError("Night should not fetch history")
        consumer.context=FakeContext()
        with patch.object(runtime,"datetime") as dt:
            dt.now.return_value=stamp(h=22)
            self.assertEqual(consumer.inspect_daily(),[])


if __name__=="__main__":
    unittest.main()
