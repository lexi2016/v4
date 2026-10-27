#!/usr/bin/env python3
"""Bounded 2026-10-27 HK.00068 quote-only collection; never a trade executor."""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
import sys
import time
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Shanghai")
DAY = "2026-10-27"
CODE = "HK.00068"
ISSUED = 1726199340
DEFAULT_OUT = Path("/Users/lexi/.codex/exports/qunhe_00068_watch_20261027")
BASE = Path("/Users/lexi/.codex/exports/qunhe_00068_ccass_20261026/sources/ccass_20261026.json")
FRIDAY = Path("/Users/lexi/.codex/exports/qunhe_00068_ccass_20261026/sources/brokers_20261023_at160021.csv")
GROUPS = {
    "A": ["高盛", "摩根士丹利", "花旗环球", "汇丰证券(亚洲)", "渣打", "美林", "建银国际", "J.P.摩根"],
    "B": ["巴克莱亚洲", "富瑞", "瑞银", "大和", "BTIG", "荷银", "中信里昂"],
    "C": ["中国投资(沪港通)", "中国创盈(深港通)", "富途证券", "凯基", "耀才", "老虎证券", "盈立"],
}
ALL_NAMES = sorted({name for names in GROUPS.values() for name in names})
NODE_TIMES = {"10:30", "12:00", "14:30", "16:00", "16:10"}
LIMITATIONS = [
    "Gross buy/sell are derived assuming provider total_vol = buy+sell; broker channels do not identify beneficial owners.",
    "Two-sided activity and one_way_ratio do not prove market making, wash trading, manipulation, or original-shareholder selling.",
    "marginal_exec_price is all-side trade VWAP, not separately identifiable selling/buying VWAP.",
    "Group totals cover observed top-10 rows only; missing channels are not zero and group totals are incomplete.",
    "CCASS balance change minus observed net trade is an unattributed residual, not proven SI transfer.",
    "Friday reference is 16:00:21 before CAS; subsequent auction, corrections, outsourced clearing and naming differences remain unobserved.",
]


def now():
    return dt.datetime.now(TZ)


def stamp(value):
    return value.isoformat(timespec="seconds")


def parse(value):
    value = dt.datetime.fromisoformat(str(value))
    return value.replace(tzinfo=TZ) if value.tzinfo is None else value.astimezone(TZ)


def current_brokers(rows):
    return bool(rows) and all(r.get('is_real_time') is True and str(r.get('data_time_str', '')).startswith(DAY) for r in rows)


def clean_quality(frame):
    return not any(any(flag in item for flag in ('STALE', 'MISMATCH', 'REPEATED')) for item in frame.get('quality', []))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    tmp.replace(path)


def table(headers, rows):
    return "\n".join(["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"] + ["| " + " | ".join(map(str, row)) + " |" for row in rows])


def fmt(value, scale=1, digits=3):
    return "NA" if value is None else f"{value / scale:,.{digits}f}"


def decode(row):
    net, total = float(row["net_vol"]), float(row["total_vol"])
    turnover = float(row["total_turnover"])
    if not all(math.isfinite(v) for v in [net, total, turnover]) or total < abs(net) or total < 0 or turnover < 0:
        raise ValueError("INVALID_VOLUME_CONTRACT")
    return dict(row, buy_vol=(total + net) / 2, sell_vol=(total - net) / 2,
                one_way_ratio=abs(net) / total if total else None,
                group=next((g for g, names in GROUPS.items() if row["broker_name"] in names), "OTHER"))


def delta_metrics(previous, current, minutes, market_delta=None):
    if minutes <= 0:
        return {"delta_status": "INVALID_TIME"}
    db, ds = current["buy_vol"] - previous["buy_vol"], current["sell_vol"] - previous["sell_vol"]
    dv = float(current["total_vol"]) - float(previous["total_vol"])
    cash = float(current["total_turnover"]) - float(previous["total_turnover"])
    if min(db, ds, dv, cash) < -1e-6:
        return {"delta_status": "SOURCE_REVISION_NON_MONOTONIC"}
    dn = float(current["net_vol"]) - float(previous["net_vol"])
    return {"delta_status": "OK", "delta_minutes": minutes, "delta_buy_vol": db, "delta_sell_vol": ds,
            "delta_net_vol": dn, "gross_sell_per_min": ds / minutes, "net_sell_per_min": -dn / minutes,
            "marginal_exec_price": cash / dv if dv > 0 else None,
            "marginal_price_scope": "ALL_SIDE_TRADE_VWAP", "delta_market_volume": market_delta}


def top10_bounds(rows):
    buys = sorted((float(r["net_vol"]) for r in rows if float(r["net_vol"]) > 0), reverse=True)
    sells = sorted((-float(r["net_vol"]) for r in rows if float(r["net_vol"]) < 0), reverse=True)
    return {"net_lower_bound": -sells[9] if len(sells) >= 10 else None,
            "net_upper_bound": buys[9] if len(buys) >= 10 else None,
            "bound_status": "BOTH_TOP10_COMPLETE" if len(buys) >= 10 and len(sells) >= 10 else "PARTIAL_BOUNDS_ONLY"}


def eligible_minutes():
    start = dt.datetime.fromisoformat(DAY).replace(tzinfo=TZ)
    result = []
    for a, b in [("09:15", "12:01"), ("13:00", "16:10")]:
        begin = parse(DAY + " " + a + ":00")
        end = parse(DAY + " " + b + ":00")
        while begin <= end:
            result.append(begin)
            begin += dt.timedelta(minutes=1)
    result.append(start.replace(hour=16, minute=10, second=30))
    return sorted(result)


def cas_status(captured_at, market, tickers, broker_time):
    auction = [r for r in tickers if str(r.get("type")) == "AUCTION" and str(r.get("time", "")).startswith(DAY + " 16:")]
    after = captured_at >= parse(DAY + " 16:10:00")
    market_updated = str(market.get("update_time", "")).startswith(DAY + " 16:") and str(market.get("update_time"))[11:16] >= "16:08"
    final = after and bool(auction) and market_updated
    return {"market_status": "FINAL_POST_CAS" if final else "POST_CAS_NOT_CONFIRMED",
            "auction_prints": auction, "broker_cas_status": "POST_CAS_TIMESTAMP_PRESENT" if final and str(broker_time)[11:16] >= "16:08" else "CAS_BROKER_COVERAGE_UNVERIFIED"}


def report(frame):
    market = frame.get("market", {})
    rows = frame.get("brokers", [])
    text = [f"# 00068.HK｜{frame['captured_at']}｜{frame['status']}",
            "RESEARCH_ONLY=true；orders_sent=false。仅研究观察，无交易接口。",
            f"行情更新时间：{market.get('update_time')}；席位更新时间：{frame.get('broker_time')}；两接口调用耗时：{frame.get('request_span_seconds')}秒。",
            f"现价 {market.get('last_price')}；累计成交 {fmt(market.get('volume'), 10000)}万股；成交额 {fmt(market.get('turnover'), 100000000)}亿港元；VWAP {fmt(frame.get('vwap'))}。",
            f"数据质量：{', '.join(frame.get('quality', [])) or 'OK'}。"]
    group_rows = []
    for key, g in frame.get("groups", {}).items():
        group_rows.append([key, f"{g['observed_count']}/{g['configured_count']}", fmt(g['sum_buy_vol'], 10000),
                           fmt(g['sum_sell_vol'], 10000), fmt(g['sum_net_sell'], 10000),
                           fmt(g.get('gross_sell_share_of_market'), .01), fmt(g.get('inst_participation_rate'), .01),
                           fmt(g.get('all_side_trade_vwap'))])
    text.append(table(["组", "在榜覆盖", "毛买/万股", "毛卖/万股", "净卖/万股", "累计毛卖占比%", "窗口毛卖占比%", "双向成交均价"], group_rows))
    view = sorted(rows, key=lambda r: (-int(float(r['net_vol']) > 0), -float(r['net_vol']) if float(r['net_vol']) > 0 else float(r['net_vol'])))
    text.append(table(["席位", "净买/万股", "总量/万股", "毛买/万股", "毛卖/万股", "单边度", "avg_price", "30分钟双向边际均价", "30分钟毛卖/分钟"],
                      [[r['broker_name'], fmt(r['net_vol'], 10000), fmt(r['total_vol'], 10000), fmt(r['buy_vol'], 10000), fmt(r['sell_vol'], 10000), fmt(r['one_way_ratio']), fmt(r.get('avg_price')), fmt(r.get('window_30m', {}).get('marginal_exec_price')), fmt(r.get('window_30m', {}).get('gross_sell_per_min'))] for r in view]))
    dropped = [r for r in frame.get('tracked', []) if r['status'] != 'OBSERVED']
    text.append(table(["缺席位", "状态", "最后见到", "最后毛买", "最后毛卖", "当前净额下界", "当前净额上界"],
                      [[r['broker_name'], r['status'], r.get('last_known_at'), fmt(r.get('last_known_buy_vol')), fmt(r.get('last_known_sell_vol')), fmt(r.get('net_lower_bound')), fmt(r.get('net_upper_bound'))] for r in dropped]))
    text.append("异动：" + ("；".join(frame.get('alerts', [])) or "本帧无新增阈值事件。"))
    text.append("研究判断：" + frame.get('research_note', '数据不足。'))
    text.append("实际卖出加权均价无法由双向total_turnover单独识别。以上组别统计仅为在榜子集，不能称全体外资总额。")
    if frame.get('cas'):
        text.append("CAS：" + json.dumps(frame['cas'], ensure_ascii=False))
    return "\n\n".join(text) + "\n"


class Watch:
    def __init__(self, output):
        self.out = Path(output)
        self.out.mkdir(parents=True, exist_ok=True)
        self.lock = (self.out / "collector.lock").open("a+")
        fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.history = []
        self.known = {}
        self.alert_at = {}
        self.gs_streak = 0
        self.q = None
        self.started = stamp(now())
        self.source_sha = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        self.completed_nodes = set()
        self.errors = 0
        for path in sorted((self.out / 'frames').glob('*.json'))[-45:]:
            self.history.append(json.loads(path.read_text()))
        if (self.out / 'known.json').exists():
            self.known = json.loads((self.out / 'known.json').read_text())
        self.completed_nodes = {p.stem.removeprefix('NODE_') for p in self.out.glob('NODE_*.json')}
        write_json(self.out / 'manifest.json', dict(run_id='qunhe_00068_20261027', scope='BOUNDED_SINGLE_DAY_RESEARCH_EXPORT',
            day=DAY, code=CODE, issued_shares=ISSUED, started_at=self.started,
            source_file=str(Path(__file__).resolve()), source_sha256=self.source_sha, interpreter=sys.executable,
            sources=['Futu OpenD quote API 127.0.0.1:11111', 'HKEX CCASS', 'HKEX DI'],
            broker_parameters={'days_before': 0, 'required_is_real_time': True},
            baseline_inputs=[{'path': str(p), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for p in [BASE, FRIDAY]],
            research_only=True, production_allowed=False, buy_gate_updated=False, orders_sent=False, limitations=LIMITATIONS))
        self.status("STARTING")

    def status(self, value, **extra):
        write_json(self.out / "status.json", dict(day=DAY, code=CODE, pid=os.getpid(), status=value,
                   updated_at=stamp(now()), started_at=self.started, research_only=True, orders_sent=False,
                   production_allowed=False, buy_gate_updated=False,
                   source_file=str(Path(__file__).resolve()), source_sha256=self.source_sha, interpreter=sys.executable,
                   limitations=LIMITATIONS, **extra))

    def connect(self):
        from futu import OpenQuoteContext, SubType
        self.q = OpenQuoteContext(host="127.0.0.1", port=11111)
        ret, data = self.q.subscribe([CODE], [SubType.TICKER], subscribe_push=False)
        if ret != 0:
            raise RuntimeError("TICKER_SUBSCRIPTION_FAILED: " + str(data))

    def capture(self, scheduled=None):
        if self.q is None:
            self.connect()
        began = now()
        ret, snap = self.q.get_market_snapshot([CODE])
        if ret != 0:
            raise RuntimeError("SNAPSHOT_FAILED: " + str(snap))
        ret, brokers = self.q.get_top_ten_buy_sell_brokers(CODE, days_before=0)
        if ret != 0:
            raise RuntimeError("BROKERS_FAILED: " + str(brokers))
        market = json.loads(snap.to_json(orient="records"))[0]
        raw = json.loads(brokers.to_json(orient="records"))
        captured = now()
        bt = raw[0].get('data_time_str') if raw else None
        quality = []
        valid = current_brokers(raw)
        if not valid:
            quality.append("BROKER_DAY_MISMATCH_OR_NOT_REAL_TIME")
        if not str(market.get('update_time', '')).startswith(DAY):
            quality.append("MARKET_DAY_MISMATCH")
        elif (captured - parse(market['update_time'])).total_seconds() > 120:
            quality.append("MARKET_STALE_OVER_120S")
        if bt and str(bt).startswith(DAY) and (captured - parse(bt)).total_seconds() > 120:
            quality.append("BROKER_STALE_OVER_120S")
        if self.history and bt == self.history[-1].get('broker_time'):
            quality.append("BROKER_TIMESTAMP_REPEATED")
        if len({r.get('data_time_str') for r in raw}) > 1:
            quality.append('BROKER_MIXED_TIMESTAMPS')
        if bt and str(bt).startswith(DAY) and str(market.get('update_time', '')).startswith(DAY):
            skew = abs((parse(bt) - parse(market['update_time'])).total_seconds())
            if skew > 120:
                quality.append('SOURCE_TIMESTAMP_MISMATCH_OVER_120S')
        frame = dict(captured_at=stamp(captured), scheduled_at=stamp(scheduled) if scheduled else None,
                     request_span_seconds=round((captured - began).total_seconds(), 4), broker_time=bt,
                     market=market, raw_brokers=raw, brokers=[], tracked=[], groups={}, alerts=[], quality=quality,
                     vwap=market['turnover'] / market['volume'] if market.get('volume', 0) else None,
                     short_data={'status': 'NO_CONFIRMED_INTRADAY_SHORT_VOLUME_SOURCE', 'volume': None},
                     status="OBSERVING" if valid and "MARKET_DAY_MISMATCH" not in quality else "WAITING_TODAY_SOURCE")
        if valid:
            current = {r['broker_name']: decode(r) for r in raw}
            previous = self.history[-1] if self.history else None
            minutes = (captured - parse(previous['captured_at'])).total_seconds() / 60 if previous else None
            market_delta = market['volume'] - previous['market']['volume'] if previous else None
            continuous = previous and previous['status'] == 'OBSERVING' and 0 < minutes <= 3 and clean_quality(frame) and clean_quality(previous) and previous.get('broker_time') != bt
            prev_rows = {r['broker_name']: r for r in previous['brokers']} if previous else {}
            for name, row in current.items():
                row['delta_status'] = 'NO_CONTINUOUS_BASELINE'
                if continuous and name in prev_rows:
                    row.update(delta_metrics(prev_rows[name], row, minutes, market_delta))
                target = captured - dt.timedelta(minutes=30)
                candidates = [(i, f) for i, f in enumerate(self.history) if abs((parse(f['captured_at']) - target).total_seconds()) <= 65]
                if candidates:
                    i, anchor = min(candidates, key=lambda pair: abs((parse(pair[1]['captured_at']) - target).total_seconds()))
                    segment = self.history[i:]
                    same = clean_quality(frame) and all(any(r['broker_name'] == name for r in f['brokers']) and f['status'] == 'OBSERVING' and clean_quality(f) for f in segment)
                    gaps = all((parse(b['captured_at']) - parse(a['captured_at'])).total_seconds() <= 180 for a, b in zip(segment, segment[1:]))
                    if same and gaps and (captured - parse(segment[-1]['captured_at'])).total_seconds() <= 180:
                        old = next(r for r in anchor['brokers'] if r['broker_name'] == name)
                        row['window_30m'] = delta_metrics(old, row, (captured - parse(anchor['captured_at'])).total_seconds() / 60)
                self.known[name] = dict(at=frame['captured_at'], row=row)
            bounds = top10_bounds(raw)
            for name in sorted(set(ALL_NAMES) | set(self.known)):
                last = self.known.get(name)
                entry = dict(broker_name=name, status='OBSERVED' if name in current else ('DROPPED_FROM_TOP10' if last else 'NOT_OBSERVED'),
                             last_known_at=last['at'] if last else None,
                             last_known_buy_vol=last['row']['buy_vol'] if last else None,
                             last_known_sell_vol=last['row']['sell_vol'] if last else None)
                if name not in current:
                    entry.update(bounds)
                frame['tracked'].append(entry)
            frame['brokers'] = list(current.values())
            for key, members in dict(GROUPS, AB=GROUPS['A'] + GROUPS['B']).items():
                subset = [r for r in current.values() if r['broker_name'] in members]
                total = sum(float(r['total_vol']) for r in subset)
                sell = sum(r['sell_vol'] for r in subset)
                eligible = [r for r in subset if r.get('delta_status') == 'OK']
                frame['groups'][key] = dict(observed_count=len(subset), configured_count=len(members),
                    sum_buy_vol=sum(r['buy_vol'] for r in subset), sum_sell_vol=sell,
                    sum_net_sell=-sum(float(r['net_vol']) for r in subset),
                    gross_sell_share_of_market=sell / market['volume'] if market.get('volume', 0) else None,
                    inst_participation_rate=sum(r['delta_sell_vol'] for r in eligible) / market_delta if market_delta and market_delta > 0 and eligible else None,
                    participation_covered_count=len(eligible), coverage='OBSERVED_TOP10_SUBSET',
                    all_side_trade_vwap=sum(float(r['total_turnover']) for r in subset) / total if total else None,
                    actual_weighted_sell_price=None, actual_sell_price_status='NOT_IDENTIFIABLE_FROM_BIDIRECTIONAL_TOTAL')
            gs = current.get('高盛')
            self.gs_streak = self.gs_streak + 1 if gs and gs.get('delta_sell_vol', 0) > 0 and float(gs['net_vol']) < 0 and (gs['one_way_ratio'] or 0) > .5 else 0
            if self.gs_streak >= 2:
                frame['alerts'].append('高盛累计净卖单边度超过50%且连续两帧毛卖增加；不能据此认定原股东或交易策略。')
            citi = current.get('花旗环球')
            if citi and citi.get('delta_sell_vol', 0) > 0:
                frame['alerts'].append('花旗环球本窗口毛卖增加；与花旗银行CCASS客户的映射未确认。')
            for name in ['高盛', '摩根士丹利']:
                row = current.get(name)
                rates = [r.get('gross_sell_per_min') for f in self.history[-5:] for r in f['brokers'] if r['broker_name'] == name and r.get('gross_sell_per_min', 0) > 0]
                if row and rates and 3.25 <= market['last_price'] <= 3.40 and row.get('gross_sell_per_min', 0) >= 2 * statistics.median(rates):
                    frame['alerts'].append(name + '在3.25至3.40观察区毛卖速率达到前五个有效窗口中位数两倍。')
            for name in ['中国投资(沪港通)', '中国创盈(深港通)']:
                row = current.get(name)
                if row and row.get('delta_sell_vol', 0) > row.get('delta_buy_vol', float('inf')):
                    frame['alerts'].append(name + '窗口卖出超过买入；不证明同一投资者日内获利卖出。')
        price, vwap = market.get('last_price'), frame.get('vwap')
        if frame['status'] != 'OBSERVING':
            frame['research_note'] = '尚无今日有效席位/行情，不把昨日日终当作今日盘中。'
        elif not clean_quality(frame):
            frame['research_note'] = '当前时间戳重复、过期或接口不同步，暂停边际卖速判断；仅保留有明确时间的累计观察。'
        elif price < 3.05:
            frame['research_note'] = '跌破26日3.05低点，风险条件恶化；研究上优先降低敞口，不以闭册或大会预期补仓。'
        elif vwap and price < vwap:
            frame['research_note'] = '价格低于当日VWAP，承接尚未确认；观察3.15至3.20及3.30附近修复，反弹受阻时优先控制仓位。'
        else:
            frame['research_note'] = '价格位于当日VWAP上方；结合毛卖速率和回落低点观察修复，单一均线或净额改善不构成确定买入信号。'
        if captured >= parse(DAY + ' 16:00:00'):
            ret, data = self.q.get_rt_ticker(CODE, num=1000)
            ticks = json.loads(data.to_json(orient='records')) if ret == 0 else []
            frame['cas'] = cas_status(captured, market, ticks, bt)
            frame['ticker_query_status'] = 'OK' if ret == 0 else str(data)
            if scheduled and scheduled.hour == 16 and scheduled.minute == 0:
                write_json(self.out / 'CONTINUOUS_CLOSE_BASELINE.json', frame)
            if frame['cas']['market_status'] == 'FINAL_POST_CAS':
                write_json(self.out / 'FINAL_POST_CAS.json', frame)
        ident = captured.strftime('%H%M%S')
        write_json(self.out / 'frames' / (ident + '.json'), frame)
        write_json(self.out / 'latest.json', frame)
        write_json(self.out / 'known.json', self.known)
        (self.out / 'latest.md').write_text(report(frame), encoding='utf-8')
        if scheduled and scheduled.strftime('%H:%M') in NODE_TIMES and scheduled.second == 0:
            node = scheduled.strftime('%H%M')
            (self.out / ('NODE_' + node + '.md')).write_text(report(frame), encoding='utf-8')
            write_json(self.out / ('NODE_' + node + '.json'), frame)
            self.completed_nodes.add(node)
        self.history.append(frame)
        self.history = self.history[-45:]
        self.errors = 0
        self.status('COLLECTING' if scheduled else 'PREFLIGHT_CAPTURED', last_frame=frame['captured_at'], frame_status=frame['status'], completed_nodes=sorted(self.completed_nodes), latest_path=str(self.out / 'latest.json'))
        print(json.dumps(dict(at=frame['captured_at'], status=frame['status'], price=price, brokers=len(frame['brokers']), quality=quality, alerts=frame['alerts']), ensure_ascii=False), flush=True)
        return frame

    def postcheck(self):
        import requests
        from bs4 import BeautifulSoup
        import re
        session = requests.Session()
        url = 'https://www3.hkexnews.hk/sdw/search/searchsdw.aspx'
        r = session.get(url, timeout=20)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, 'html.parser')
        data = {x.get('name'): x.get('value', '') for x in soup.select('input[name]')}
        data.update({'__EVENTTARGET': 'btnSearch', '__EVENTARGUMENT': '', 'txtShareholdingDate': '2026/10/27', 'txtStockCode': '00068', 'txtParticipantID': '', 'txtParticipantName': '', 'txtStockName': ''})
        r = session.post(url, data=data, timeout=25)
        r.raise_for_status()
        body = BeautifulSoup(r.text, 'html.parser')
        text = body.get_text(' ', strip=True)
        actual = re.search(r'Shareholding Date:\s*(\d{4}/\d{2}/\d{2})', text)
        total = re.search(r'Total Shareholding in CCASS\s+([\d,]+)', text)
        current = {}
        for tr in body.select('table.table tr'):
            cells = [td.get_text(' ', strip=True) for td in tr.select('td')]
            if len(cells) == 5:
                current[cells[0].split(': ', 1)[-1]] = dict(name=cells[1].split(': ', 1)[-1], shares=int(cells[3].split(': ', 1)[-1].replace(',', '')))
        receipt = dict(queried_at=stamp(now()), requested_date='2026/10/27', actual_date=actual.group(1) if actual else None,
                       total_shares=int(total.group(1).replace(',', '')) if total else None,
                       status='TARGET_DATE_AVAILABLE' if actual and actual.group(1) == '2026/10/27' and total else 'WAITING_CCASS_TARGET_DATE', limitations=LIMITATIONS)
        if receipt['status'] == 'TARGET_DATE_AVAILABLE' and not current:
            raise ValueError('CCASS_TARGET_TOTAL_WITH_EMPTY_PARTICIPANT_ROWS')
        if receipt['status'] == 'TARGET_DATE_AVAILABLE':
            base = json.loads(BASE.read_text())
            old = {r['participant_id']: r for r in base['rows']}
            with FRIDAY.open(encoding='utf-8-sig') as f:
                friday = {r['broker_name']: int(r['net_vol']) for r in csv.DictReader(f)}
            mapping = {'B01451': '高盛', 'B01274': '摩根士丹利', 'B01161': '瑞银', 'A00003': '中国投资(沪港通)', 'A00004': '中国创盈(深港通)'}
            # Jefferies' participant mapping is intentionally not guessed.
            rows = []
            for pid in sorted(set(old) | set(current)):
                change = current.get(pid, {}).get('shares', 0) - old.get(pid, {}).get('shares', 0)
                broker = mapping.get(pid)
                trade = friday.get(broker) if broker else None
                rows.append(dict(participant_id=pid, name=current.get(pid, old.get(pid))['name'], ccass_change=change,
                                 friday_1600_net_trade=trade, unattributed_residual=change - trade if trade is not None else None,
                                 residual_status='NOT_PROVEN_SI_TRANSFER' if trade is not None else 'BROKER_MAPPING_OR_TRADE_BASELINE_UNAVAILABLE'))
            receipt.update(net_total_change=receipt['total_shares'] - base['official_total_shares'], baseline_total=base['official_total_shares'], rows=rows)
            write_json(self.out / 'CCASS_T2_RECONCILIATION.json', receipt)
            (self.out / 'CCASS_T2_RECONCILIATION.md').write_text('# 10/27 CCASS与周五盘中净额核验\n\n' + table(['参与者', '名称', '存仓变化', '周五16:00净额', '未归因残差'], [[r['participant_id'], r['name'], r['ccass_change'], r['friday_1600_net_trade'], r['unattributed_residual']] for r in rows]) + '\n\n残差不能被直接认定为SI转仓；周五基准缺少CAS，部分执行席位与结算参与者映射未确认。\n', encoding='utf-8')
        params = {'cid': '0', 'cn': '1', 'corpn': 'Manycore Tech Inc.', 'ed': '27/10/2026', 'lang': 'EN', 'sa1': 'cl', 'sa2': 'an', 'sced': '27/10/2026', 'scsd': '20/10/2026', 'sd': '20/10/2026', 'sid': '541814', 'src': 'Main', 'srchCorpName': 'Manycore Tech Inc.'}
        r = session.get('https://di.hkex.com.hk/di/NSAllFormList.aspx', params=params, timeout=25)
        r.raise_for_status()
        di_soup = BeautifulSoup(r.text, 'html.parser')
        di = di_soup.get_text(' ', strip=True)
        (self.out / 'DI_LATEST.txt').write_text(di, encoding='utf-8')
        forms = []
        for link in di_soup.select('a[href]'):
            href = link['href']
            if 'NSForm2.aspx' in href:
                row = link.find_parent('tr')
                forms.append({'url': requests.compat.urljoin(r.url, href), 'text': row.get_text(' ', strip=True) if row else link.get_text(' ', strip=True)})
        receipt['di_form2_rows'] = forms
        receipt['di_new_on_27_candidates'] = [x for x in forms if '27/10/2026' in x['text']]
        receipt['di_status'] = 'FORM2_ROWS_EXTRACTED' if forms else 'NO_FORM2_ROWS_OR_PAGE_NOT_CONFIRMED'
        receipt['di_text_path'] = str(self.out / 'DI_LATEST.txt')
        write_json(self.out / 'postcheck_latest.json', receipt)
        return receipt

    def run(self):
        self.capture()
        for scheduled in eligible_minutes():
            delay = (scheduled - now()).total_seconds()
            if delay < -2:
                with (self.out / 'missed_slots.jsonl').open('a') as f:
                    f.write(json.dumps({'scheduled_at': stamp(scheduled), 'status': 'NOT_CAPTURED_BEFORE_START_OR_DELAY'}) + '\n')
                continue
            if delay > 0:
                self.status('WAITING_NEXT_SLOT', next_slot=stamp(scheduled), completed_nodes=sorted(self.completed_nodes))
                time.sleep(delay)
            try:
                self.capture(scheduled)
            except Exception as exc:
                self.errors += 1
                self.status('CAPTURE_ERROR', consecutive_errors=self.errors, error=repr(exc), failed_slot=stamp(scheduled))
                print('CAPTURE_ERROR', repr(exc), flush=True)
                if self.q:
                    self.q.close()
                self.q = None
                if self.errors >= 3:
                    self.status('STOPPED_REPEATED_SOURCE_ERRORS', consecutive_errors=self.errors, error=repr(exc), failed_slot=stamp(scheduled))
                    raise RuntimeError('Three consecutive source failures; preserve evidence and diagnose before resuming') from exc
        if self.q:
            self.q.close()
            self.q = None
        self.status('MARKET_COLLECTION_FINISHED_WAITING_CCASS', completed_nodes=sorted(self.completed_nodes), final_market_snapshot_present=(self.out / 'FINAL_POST_CAS.json').exists())
        # One executor owns bounded hourly post-close checks; no continuous network polling.
        checks = [parse(DAY + f' {hour:02d}:30:00') for hour in range(18, 24)]
        tomorrow = parse('2026-10-28 00:30:00')
        checks += [tomorrow + dt.timedelta(hours=h) for h in range(8)]
        for scheduled in checks:
            if now() > scheduled + dt.timedelta(minutes=5):
                continue
            time.sleep(max(0, (scheduled - now()).total_seconds()))
            try:
                result = self.postcheck()
                self.status(result['status'], postcheck_path=str(self.out / 'postcheck_latest.json'), completed_nodes=sorted(self.completed_nodes))
                if result['status'] == 'TARGET_DATE_AVAILABLE':
                    self.status('COMPLETE_WITH_LIMITATIONS', postcheck_path=str(self.out / 'postcheck_latest.json'), completed_nodes=sorted(self.completed_nodes), final_market_snapshot_present=(self.out / 'FINAL_POST_CAS.json').exists())
                    return
            except Exception as exc:
                self.status('POSTCHECK_ERROR_WAITING_NEXT_HOURLY_SLOT', error=repr(exc))
        self.status('WAITING_EXTERNAL_DATA_DEADLINE_REACHED', postcheck_path=str(self.out / 'postcheck_latest.json'))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, default=DEFAULT_OUT)
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    if not args.once and now().date().isoformat() != DAY:
        raise SystemExit('This bounded collector runs only on ' + DAY)
    watch = Watch(args.out)
    try:
        if args.once:
            frame = watch.capture()
            print('CAPTURE_PATH', str(args.out / 'latest.json'))
        else:
            watch.run()
    finally:
        if watch.q:
            watch.q.close()


if __name__ == '__main__':
    main()
