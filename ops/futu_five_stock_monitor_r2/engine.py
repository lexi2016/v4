"""In-memory alert state and exact event-time gates; no market/account writes."""
from dataclasses import dataclass, field
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo

from .config import BASE_DATE, STOCKS
from .formulas import number

TZ = ZoneInfo("Asia/Shanghai")
REALTIME_RIGHTS = {"LV1", "LV2", "LV3", "SF"}
DENIED_RIGHTS = {"BMP", "NO", "DELAYED"}


def local_time(value):
    text = str(value)
    # SDK also documents yyyy-MM-dd HH:mm:ss:SSS (not ISO's .SSS).
    if len(text)>19 and text[19]==":":
        text = text[:19]+"."+text[20:]
    stamp = datetime.fromisoformat(text)
    return stamp.replace(tzinfo=TZ) if stamp.tzinfo is None else stamp.astimezone(TZ)


def session(code, now, market_state):
    """Exchange state AND market-specific local window, excluding auctions/lunch."""
    now = now.astimezone(TZ)
    if now.weekday()>=5:
        return None
    end_am = time(12) if code.startswith("HK.") else time(11,30)
    end_pm = time(16) if code.startswith("HK.") else time(15)
    t = now.time().replace(tzinfo=None)
    if market_state == "MORNING" and time(9,30)<=t<end_am:
        return (now.date().isoformat(), "AM")
    if market_state == "AFTERNOON" and time(13)<=t<end_pm:
        return (now.date().isoformat(), "PM")
    return None


def fresh(stamp, now, seconds=15):
    return stamp.date()==now.date() and 0<=(now-stamp).total_seconds()<=seconds


def daily_closed(code, now, state, quote_stamp):
    """Conservative: HK CAS must have ended, not merely the 16:00 session."""
    if now.weekday()>=5 or quote_stamp.date()!=now.date():
        return False
    if code.startswith("HK."):
        return state == "CLOSED" and now.time()>=time(16,11) and quote_stamp.time()>=time(16)
    return state in {"CLOSED", "STIB_AFTER_HOURS_END"} and now.time()>=time(15,1) and quote_stamp.time()>=time(14,59)


@dataclass
class Path:
    broken_at: datetime
    broken_price: float
    minimum: float
    broken_sequence: int
    recovered_at: datetime | None = None
    repeated: bool = False
    checked_bar: str | None = None


@dataclass
class State:
    date: str = ""
    segment: tuple | None = None
    previous: float | None = None
    sequence: int | None = None
    ticker_time: datetime | None = None
    paths: dict[float, Path] = field(default_factory=dict)
    seen: set = field(default_factory=set)
    key_invalidated: bool = False


class Engine:
    def __init__(self, notify, simulation=False):
        self.notify = notify
        self.simulation = simulation
        self.states = {c:State() for c in STOCKS}

    def reset_paths(self, code=None):
        for c in ([code] if code else STOCKS):
            s = self.states[c]
            s.segment, s.previous, s.sequence, s.ticker_time = None, None, None, None
            s.paths.clear()

    def current(self, code, now):
        s = self.states[code]
        date = now.date().isoformat()
        if s.date != date:
            self.states[code] = s = State(date=date, key_invalidated=s.key_invalidated)
        return s

    def emit(self, code, now, price, kind, priority, level, reason, next_step):
        s = self.current(code, now)
        key = (kind, str(level))
        if key in s.seen:
            return
        st = STOCKS[code]
        phase = "SIMULATION｜" if self.simulation else ""
        anchor_status = "原锚收盘正式失效" if s.key_invalidated else st.key_k
        payload = dict(code=code, name=st.name, price=price, currency=st.currency,
                       time=now.isoformat(timespec="seconds"), type=kind,
                       priority=priority, level=level, reason=reason,
                       key_k=anchor_status, next_step=next_step)
        payload["title"] = f"{phase}{priority} {st.name} {code}"
        payload["body"] = (f"{price:g} {st.currency}｜{now:%H:%M:%S}｜{kind}\n"
                           f"固定点位 {level}（{BASE_DATE}）｜{reason}\n"
                           f"关键K：{anchor_status}；{st.notes}\n下一步：{next_step}")
        self.notify(payload)  # Failed OS delivery is not silently recorded as success.
        s.seen.add(key)

    def tick(self, row, now, market_state, right="N/A", subscribed=False):
        code = row.get("code")
        if code not in STOCKS:
            return
        s = self.current(code, now)
        try:
            stamp = local_time(row["time"])
            seq = int(row["sequence"])
            price = number(row["price"])
        except (ValueError, KeyError, TypeError):
            self.reset_paths(code)
            return
        segment = session(code, now, market_state)
        valid = (segment and session(code, stamp, market_state)==segment and fresh(stamp, now)
                 and row.get("push_data_type")=="REALTIME" and subscribed
                 and right not in DENIED_RIGHTS and price is not None and price>0
                 and (row.get("type")=="AUTO_MATCH" or
                      (code.startswith("SZ.") and row.get("type") in {"UNKNOWN","N/A"})))
        if not valid:
            self.reset_paths(code)
            return
        if s.segment != segment:
            self.reset_paths(code)
            s.segment = segment
        if s.sequence is not None and seq<=s.sequence:
            return
        if s.ticker_time and stamp<s.ticker_time:
            self.reset_paths(code)
            return
        first = s.sequence is None
        s.sequence, s.ticker_time = seq, stamp
        if first:
            s.previous = price  # Baseline only, never infer an earlier break.
            self.price(code,price,stamp)
            return True
        st = STOCKS[code]
        anchors = {st.risk, *(x for x,_ in st.rises)}
        if st.touch is not None:
            anchors.add(st.touch)
        for low,high,_ in st.zones:
            anchors.update((low,high))
        for level in sorted(anchors):
            path = s.paths.get(level)
            if price<level:
                if path is None and s.previous is not None and s.previous>=level:
                    path = s.paths[level] = Path(stamp,price,price,seq)
                if path is None:
                    continue  # Already below on entry is not an observed break.
                path.minimum = min(price,path.minimum)
                if path.recovered_at is not None and not path.repeated:
                    path.repeated = True
                    self.emit(code,stamp,price,"收回后再次失守", "P0" if level==st.risk else "P2",level,
                              f"真实逐笔再次低于点位；首破{path.broken_at:%H:%M:%S} {path.broken_price:g}；最低{path.minimum:g}；收回{path.recovered_at:%H:%M:%S}",
                              "等新的有效承接；不自动认定买点")
            elif path and path.recovered_at is None and seq>path.broken_sequence and stamp>=path.broken_at:
                path.recovered_at = stamp
                self.emit(code,stamp,price,"盘中破位后收回｜承接观察","P2",level,
                          f"首破{path.broken_at:%H:%M:%S} {path.broken_price:g}；最低{path.minimum:g}；收回{stamp:%H:%M:%S}",
                          "观察收回后完整5分钟K线及是否再次失守")
        self.price(code,price,stamp,s.previous)
        s.previous = price
        return True

    def price(self, code, price, stamp, previous=None):
        st = STOCKS[code]
        for level in {st.risk, *(x for x,_ in st.rises)}:
            if price==level:
                self.emit(code,stamp,price,"触及固定观察点位","P2",level,"真实逐笔价等于固定点位","观察下一笔价格方向与关键K状态")
        if st.touch is not None and price==st.touch:
            self.emit(code,stamp,price,"回踩观察","P2",st.touch,"真实逐笔价等于固定回踩线","观察缩量与关键K底线")
        if price<st.risk:
            self.emit(code,stamp,price,"支撑失守风险","P0",st.risk,
                      f"当前真实逐笔价<{st.risk:g}"+("；进入监控时已在线下，先后路径UNKNOWN" if previous is None else ""),
                      "观察是否收回风险线；不是止损指令")
        if previous is None:
            return
        for level, text in st.rises:
            if previous<=level<price:
                self.emit(code,stamp,price,text,"P2",level,f"真实逐笔由{previous:g}越过{level:g}","观察量价及有效关键K；不是完整买点")
        if st.touch is not None and (previous-st.touch)*(price-st.touch)<=0:
            self.emit(code,stamp,price,"回踩观察","P2",st.touch,"价格触及或跨越固定回踩线","观察缩量与关键K底线")
        for low,high,text in st.zones:
            if low<=price<=high or (previous<low and price>high) or (previous>high and price<low):
                if code=="SZ.000610" and st.risk not in self.states[code].paths:
                    continue
                self.emit(code,stamp,price,text,"P2",f"{low:g}–{high:g}","真实价格进入或跨越固定观察区","观察突破或支撑；不自动操作")

    def five_minute(self, code, bars, now):
        """SDK right labels: require successor (closed), full bar after reclaim."""
        s = self.current(code,now)
        if len(bars)<2:
            return
        labels = [local_time(b["time_key"]) for b in bars]
        if labels != sorted(set(labels)):
            return
        for bar in bars[:-1]:
            end = local_time(bar["time_key"])
            start = end-timedelta(minutes=5)
            if end.date()!=now.date() or end>now or s.segment is None:
                continue
            # All of the confirming bar must lie within the current session.
            if (start.date().isoformat(), "AM" if start.time()<time(13) else "PM") != s.segment:
                continue
            low, close = number(bar.get("low")),number(bar.get("close"))
            if low is None or close is None:
                continue
            for level,path in s.paths.items():
                if path.recovered_at is None or path.repeated or start<path.recovered_at or path.checked_bar:
                    continue
                path.checked_bar = str(bar["time_key"])
                if low>=level and close>=level:
                    self.emit(code,end,close,"破位收回后承接确认候选","P1" if level==STOCKS[code].risk else "P2",level,
                              f"收回{path.recovered_at:%H:%M:%S}后完整5分钟K线{start:%H:%M}–{end:%H:%M}最低{low:g}、收盘{close:g}均守住",
                              "仅承接候选；继续观察再次失守，未认证完整结构买点")
                elif low<level:
                    path.repeated=True
                    self.emit(code,end,close,"收回后5分钟K线再次失守","P0" if level==STOCKS[code].risk else "P2",level,
                              f"已闭合5分钟K最低{low:g}、收盘{close:g}","承接未成立；继续观察")

    def formula(self, code, result, stamp, price, closed=False):
        if closed and code!="SZ.300893" and price<STOCKS[code].risk:
            self.emit(code,stamp,price,"收盘支撑失守风险","P0",STOCKS[code].risk,
                      "SDK确认今日收盘且CLOSE低于固定风险线","等待修复观察；不自动买卖")
        if closed and code=="SZ.300893" and price<STOCKS[code].risk:
            self.current(code,stamp).key_invalidated = True
            self.emit(code,stamp,price,"原锚正式失效｜收盘确认","P0",STOCKS[code].risk,"交易所/SDK确认今日收盘且日线CLOSE<15.04","等待研究负责人更新锚点；固定点位保留")
        if result.get("status")!="READY":
            return
        for rule, hit in result["rules"].items():
            if hit is not True:
                continue
            context = rule in {"B2_1006_ORAL_CONTEXT","B2_151_VOLUME_CONTEXT","缩量回调观察","放量阳包阴观察"}
            risk = rule in {"守线失守风险","白黄线死叉","破前低风险","卖点公式完整命中"}
            priority = "P0" if risk else ("P2" if context else "P1")
            label = rule+("｜日线收盘确认" if closed else "｜盘中形成中")
            reason = result.get("conditions",{}).get(rule,"用户原式独立命中")+"；"+("今日收盘已确认" if closed else "当前日线未收盘，不能当日线收盘确认")
            if code.startswith("HK."):
                reason += "；HK_REFERENCE_ONLY"
            if rule=="B2_1006_ORAL_CONTEXT":
                reason += "；仅较昨日放量/平量语境，非完整B2，J<55不是硬门槛"
            if rule=="B2_151_VOLUME_CONTEXT":
                reason += "；仅VOL>REF(VOL,1)*1.20，非完整B2"
            self.emit(code,stamp,price,label,priority,STOCKS[code].risk,reason,"结合固定关键K状态与有效承接复核；不自动买卖")
