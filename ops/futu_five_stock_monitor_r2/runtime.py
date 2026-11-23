"""Manual foreground OpenD consumer; only OpenQuoteContext quote endpoints."""
import argparse
from datetime import datetime, time
import json
import queue
import subprocess
import threading
import time as clock

from infrastructure.futu_quote_provider import _default_context, to_futu_symbol
from .config import SAFETY, STOCKS, STREAMS
from .engine import (DENIED_RIGHTS, Engine, REALTIME_RIGHTS, TZ, daily_closed,
                     fresh, local_time, session)
from .formulas import calculate, number

SCRIPT = '''on run argv
display notification (item 2 of argv) with title (item 1 of argv) subtitle (item 3 of argv)
end run
'''


def report(**values):
    print(json.dumps(values, ensure_ascii=False, default=str), flush=True)


def notification(alert):
    subprocess.run(["/usr/bin/osascript", "-", alert["title"], alert["body"],
                    "只读研究提醒｜不自动买卖"], input=SCRIPT, text=True,
                   check=True, capture_output=True, timeout=8)
    report(notification="OS_ACCEPTED_DISPLAY_CANNOT_CONFIRM", **alert)


def aligned_daily(code, rows, quote):
    """Request identity is QFQ; anchor it to same-day raw current OHLC/shares."""
    if len(rows)<116 or quote.get("code")!=code:
        return False, "不足116根同源日线或报价代码不符"
    dates = [str(r.get("time_key",""))[:10] for r in rows]
    if dates != sorted(set(dates)) or any(r.get("code")!=code for r in rows):
        return False,"日线代码、日期顺序或唯一性不符"
    if dates[-1] != quote.get("data_date"):
        return False,"QFQ日线/QUOTE日期不一致"
    for key,qkey in (("close","last_price"),("open","open_price"),
                     ("high","high_price"),("low","low_price"),("volume","volume")):
        a,b = number(rows[-1].get(key)),number(quote.get(qkey))
        if a is None or b is None or abs(a-b)>1e-6:
            return False,"QFQ当前OHLC或股数与QUOTE不一致："+key
    return True,"OpenD get_cur_kline(AuType.QFQ)；当前OHLC/volume与同日报价匹配；volume=shares"


class Consumer:
    def __init__(self, ft, engine):
        self.ft,self.engine = ft,engine
        self.context = None
        self.events = queue.Queue(maxsize=1000)
        self.overflow = threading.Event()
        self.subscriptions = {}
        self.rights = {"cn_qot_right":"N/A", "hk_qot_right":"N/A"}
        self.market_states = {}
        self.health_at = None
        self.health_ok = False
        self.observed = {c:{s:0 for s in STREAMS} for c in STOCKS}
        self.connected_at = None
        self.authority_ticks = {}  # Today's REALTIME fact, this connection only.
        self.last_subscribe_at = 0.0

    def enqueue(self, kind, data):
        try:
            self.events.put_nowait((kind,data))
        except queue.Full:
            self.overflow.set()

    def connect(self):
        ft = self.ft
        self.engine.reset_paths()
        self.connected_at = datetime.now(TZ)
        self.context = _default_context()  # Existing V4 read-only local connection.
        owner = self
        def handler(base, kind):
            class Handler(base):
                def on_recv_rsp(self, rsp):
                    ret,data = super().on_recv_rsp(rsp)
                    if ret==ft.RET_OK:
                        owner.enqueue(kind,data)
                    else:
                        owner.enqueue("error",str(data))
                    return ret,data
            return Handler()
        self.context.set_handler(handler(ft.TickerHandlerBase,"ticker"))
        self.context.set_handler(handler(ft.StockQuoteHandlerBase,"quote"))
        self.context.set_handler(handler(ft.CurKlineHandlerBase,"kline"))
        self.context.set_handler(handler(ft.SysNotifyHandlerBase,"system"))
        self.subscribe_missing()
        self.refresh()

    def subscribe_missing(self):
        # Separate A/HK so an unavailable market cannot poison the other four.
        for stream in STREAMS:
            for hk in (False,True):
                codes=[c for c in STOCKS if c.startswith("HK.")==hk and
                       not self.subscriptions.get((c,stream),False) and self.right(c) not in DENIED_RIGHTS]
                if not codes:
                    continue
                ret,message=self.context.subscribe(codes,[getattr(self.ft.SubType,stream)],
                                                    is_first_push=False,subscribe_push=True)
                for code in codes:
                    self.subscriptions[(code,stream)]=ret==self.ft.RET_OK
                report(subscription=stream,codes=codes,ok=ret==self.ft.RET_OK,error=message)
        self.last_subscribe_at=clock.monotonic()

    def right(self,code):
        return self.rights["hk_qot_right" if code.startswith("HK.") else "cn_qot_right"]

    def subscribed(self,code):
        return all(self.subscriptions.get((code,s),False) for s in STREAMS)

    def refresh(self):
        ft = self.ft
        ret,state = self.context.get_global_state()
        now = datetime.now(TZ)
        if ret!=ft.RET_OK:
            raise ConnectionError("get_global_state: "+str(state))
        if str(state.get("qot_logined")) not in {"1","True"}:
            raise ConnectionError("OpenD行情连接未就绪")
        server_time = number(state.get("timestamp"))
        if server_time is None or abs(now.timestamp()-server_time)>15:
            raise ConnectionError("OpenD服务器时钟不新鲜或本机时钟偏差>15s")
        ret, frame = self.context.get_market_state(list(STOCKS))
        if ret!=ft.RET_OK:
            raise ConnectionError("get_market_state: "+str(frame))
        states = {r["code"]:r["market_state"] for r in frame.to_dict("records")}
        if set(states)!=set(STOCKS):
            raise ConnectionError("市场状态缺少指定标的")
        for code in STOCKS:
            old = session(code,now,self.market_states.get(code))
            new = session(code,now,states[code])
            if old!=new:
                self.engine.reset_paths(code)
        self.market_states = states
        # Restricted field request. Never log identity/account fields returned by SDK.
        ret, info = self.context.get_user_info([ft.UserInfoField.QOTRIGHT])
        if ret==ft.RET_OK:
            rights = {k:info.get(k,"N/A") for k in self.rights}
            if rights!=self.rights:
                self.engine.reset_paths()
                self.authority_ticks.clear()
            self.rights = rights
        self.health_at,self.health_ok = now,True
        if clock.monotonic()-self.last_subscribe_at>=30:
            self.subscribe_missing()

    def live_market(self,code,now):
        return (self.health_ok and self.health_at is not None and fresh(self.health_at,now)
                and self.subscribed(code) and self.right(code) not in DENIED_RIGHTS)

    def drain(self):
        if self.overflow.is_set():
            self.engine.reset_paths()
            while not self.events.empty():
                try:
                    self.events.get_nowait()
                except queue.Empty:
                    break
            self.overflow.clear()
            report(status="UNKNOWN",reason="事件队列溢出，路径重置，重新建立逐笔基线")
        for _ in range(1000):
            try:
                kind,data = self.events.get_nowait()
            except queue.Empty:
                break
            now = datetime.now(TZ)
            if kind=="error":
                self.engine.reset_paths()
                report(status="UNKNOWN",reason="行情回调错误",error=data)
            elif kind=="system":
                typ,_,values = data
                if typ=="CONN_STATUS" and not values.get("qot_logined",False):
                    self.engine.reset_paths()
                    self.health_ok = False
                    self.authority_ticks.clear()
                    raise ConnectionError("行情连接中断，丢弃跨断线路径")
                if typ=="QOT_RIGHT":
                    self.rights = {k:values.get(k,"N/A") for k in self.rights}
                    self.engine.reset_paths()
                    self.authority_ticks.clear()
            else:
                for row in data.to_dict("records"):
                    code = row.get("code")
                    if code not in STOCKS:
                        continue
                    stream = "TICKER" if kind=="ticker" else ("QUOTE" if kind=="quote" else row.get("k_type"))
                    if stream in self.observed[code]:
                        self.observed[code][stream] += 1
                    if kind=="ticker":
                        state = self.market_states.get(code) if self.live_market(code,now) else None
                        try:
                            if local_time(row["time"])<self.connected_at:
                                continue
                        except (KeyError,ValueError,TypeError):
                            pass
                        if self.engine.tick(row,now,state,self.right(code),self.subscribed(code)):
                            self.authority_ticks[code] = local_time(row["time"])

    def inspect_daily(self, alerts=True):
        ft = self.ft
        now=datetime.now(TZ)
        def in_window(code):
            end=time(16) if code.startswith("HK.") else time(15)
            closing=now.weekday()<5 and end<=now.time()<time(end.hour+1)
            return session(code,now,self.market_states.get(code)) is not None or closing
        poll_codes=[c for c in STOCKS if not alerts or in_window(c)]
        if not poll_codes:
            return []
        quotes = {}
        for hk in (False,True):
            codes=[c for c in poll_codes if c.startswith("HK.")==hk and self.subscribed(c)]
            if not codes:
                continue
            ret,frame=self.context.get_stock_quote(codes)
            if ret==ft.RET_OK:
                quotes.update({r["code"]:r for r in frame.to_dict("records")})
            else:
                for code in codes:
                    self.engine.reset_paths(code)
                    self.authority_ticks.pop(code,None)
                report(status="UNKNOWN",codes=codes,reason="报价不可用，仅隔离对应市场",error=str(frame))
        evidence = []
        for code,stock in STOCKS.items():
            now = datetime.now(TZ)
            # Outside continuous trading/one-hour closing observation window,
            # stay connected but do not repeatedly fetch five daily windows.
            if code not in poll_codes:
                continue
            quote = quotes.get(code,{})
            ret,frame = self.context.get_cur_kline(code,300,ft.KLType.K_DAY,ft.AuType.QFQ)
            rows = frame.to_dict("records") if ret==ft.RET_OK else []
            aligned,reason = aligned_daily(code,rows,quote)
            stamp = None
            try:
                stamp = local_time(str(quote["data_date"])+" "+str(quote["data_time"]))
            except (ValueError,KeyError):
                pass
            current = (stamp is not None and fresh(stamp,now) and
                       session(code,now,self.market_states.get(code)) is not None)
            tick = self.engine.states[code].ticker_time
            authority_tick = self.authority_ticks.get(code)
            today_authority = authority_tick is not None and authority_tick.date()==now.date()
            quote_authority_capable = self.right(code) in REALTIME_RIGHTS or today_authority
            realtime = quote_authority_capable and current
            gate = self.live_market(code,now) and quote_authority_capable
            closed = (stamp is not None and daily_closed(code,now,self.market_states.get(code),stamp))
            result = calculate(rows) if aligned else {"status":"UNKNOWN","reason":reason}
            ready = (gate and aligned and (current or closed) and
                     result.get("status")=="READY" and not bool(quote.get("suspension",True)))
            row_evidence = dict(code=code,fixed_name=stock.name,source_name=quote.get("name"),
                                mapping_ok=quote.get("code")==code and to_futu_symbol("HK.07666" if code.startswith("HK.") else "A."+code[3:])==code,
                                currency=stock.currency,rights=self.right(code),
                                subscriptions={s:self.subscriptions.get((code,s),False) for s in STREAMS},
                                data_date=quote.get("data_date"),data_time=quote.get("data_time"),
                                qfq_rows=len(rows),source_aligned=aligned,source_reason=reason,
                                market_state=self.market_states.get(code),realtime_confirmed=realtime,
                                quote_authority_capable=quote_authority_capable,
                                today_realtime_tick=authority_tick.isoformat() if today_authority else None,
                                natural_realtime_tick_confirmed=tick is not None and fresh(tick,now),
                                formula_status=result["status"] if ready else "UNKNOWN",
                                formula_rules={k:("UNKNOWN" if v is None else v) for k,v in result.get("rules",{}).items()},
                                ready=ready,closed_confirmed=closed,observed_pushes=self.observed[code].copy())
            evidence.append(row_evidence)
            if alerts and ready:
                self.engine.formula(code,result,now,float(quote["last_price"]),closed)
            elif alerts:
                report(status="UNKNOWN",**row_evidence)
            if alerts and gate and current and aligned:
                # Explicit QFQ 5m read; push K-line autype is not assumed.
                ret,kframe = self.context.get_cur_kline(code,6,ft.KLType.K_5M,ft.AuType.QFQ)
                if ret==ft.RET_OK:
                    bars=kframe.to_dict("records")
                    if all(b.get("code")==code for b in bars):
                        self.engine.five_minute(code,bars,now)
        return evidence

    def close(self):
        self.health_ok = False
        self.authority_ticks.clear()
        self.engine.reset_paths()
        if self.context is not None:
            self.context.close()  # Only this context; never unsubscribe_all or stop OpenD.
            self.context = None


def main(argv=None):
    parser=argparse.ArgumentParser(description="五股OpenD只读研究监控；默认前台监控，Ctrl-C停止")
    flags=parser.add_mutually_exclusive_group()
    flags.add_argument("--check",action="store_true",help="只读订阅/口径/权限检查，无弹窗；0就绪/2 UNKNOWN/1连接错误")
    flags.add_argument("--test-notification",action="store_true",help="仅发一条SIMULATION静默通知，不连接OpenD")
    args=parser.parse_args(argv)
    if args.test_notification:
        Engine(notification,simulation=True).emit("SZ.300893",datetime.now(TZ),15.04,
            "SIMULATION通知验收","P2",15.04,"模拟测试，不是真实行情触发","确认Mac横幅权限与专注模式")
        return 0
    import futu as ft
    engine=Engine((lambda _: None) if args.check else notification)
    consumer=None
    attempts=0
    report(task="FUTU_FIVE_STOCK_INTRADAY_MONITOR_R2",mode="CHECK" if args.check else "MANUAL_FOREGROUND",**SAFETY)
    try:
        while True:
            consumer=Consumer(ft,engine)
            try:
                consumer.connect()
                consumer.drain()
                if args.check:
                    # Observe only in an actual continuous session. Historic
                    # snapshots/cache cannot establish today's REALTIME fact.
                    deadline=clock.monotonic()+15
                    while (any(session(c,datetime.now(TZ),consumer.market_states.get(c)) and
                               consumer.subscribed(c) and c not in consumer.authority_ticks
                               for c in STOCKS) and clock.monotonic()<deadline):
                        consumer.drain()
                        clock.sleep(0.1)
                    consumer.refresh()
                    consumer.drain()
                    evidence=consumer.inspect_daily(alerts=False)
                    ok=all(e["ready"] for e in evidence)
                    report(status="READY" if ok else "CANNOT_CONFIRM",stocks=evidence,**SAFETY)
                    return 0 if ok else 2
                attempts=0
                last_refresh=clock.monotonic()
                consumer.inspect_daily()
                while True:
                    consumer.drain()
                    if clock.monotonic()-last_refresh>=10:
                        consumer.refresh()
                        consumer.drain()
                        consumer.inspect_daily()
                        last_refresh=clock.monotonic()
                    clock.sleep(0.1)
            except (ConnectionError,OSError,RuntimeError,ValueError) as exc:
                report(status="CANNOT_CONFIRM",error=str(exc),action="断线/错误路径已重置；仅重建本进程只读连接")
                if args.check:
                    return 1
                attempts += 1
            finally:
                consumer.close()
            clock.sleep(min(30,2**min(attempts,5)))
    except KeyboardInterrupt:
        report(status="STOPPED",reason="Ctrl-C；本进程连接已关闭；OpenD及其他服务保持运行",**SAFETY)
        return 0
    finally:
        if consumer:
            consumer.close()
