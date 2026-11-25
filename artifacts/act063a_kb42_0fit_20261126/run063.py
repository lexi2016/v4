"""Run ACT-063A against existing frozen evidence, strictly 0 FIT."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from io import BytesIO
import os
import resource
import subprocess
import sys
from time import perf_counter, process_time

import pandas as pd
import pyarrow as pa
from threadpoolctl import threadpool_limits

from inputs063 import BASE, HOLD, RELAPSE, ROOT, Usage, bind_reader, csv_payload, verified_sources
from common062 import GOV, digest
from run062 import json_payload
import dq063
import exit063
import trace063

LIMIT = 2_000_000
ARROW_CPU, ARROW_IO, BLAS = 4, 2, 1
FILES = {
    "report": "ACT063A_ROUTE_A_C_REPORT.md",
    "trace": "ACT063A_KB42_162EVENTS_ELIMINATION_TRACE.csv",
    "dq": "ACT063A_DQ01_DQ03_RECONCILIATION_PATCH.csv",
    "exit": "ACT063A_EXIT_AXIS_562WAVES_BASELINE.csv",
}


def count_by(mapping):
    names = {
        trace063.L50_ABSENT:"原 L50M 门禁",
        trace063.READY_ABSENT:"原 L50M 有键，FULL 就绪未过",
        trace063.FULL_RANK:"FULL 腿未进 Top-5，CORE 门禁未过",
        trace063.CORE_RANK:"CORE 有资格，双腿排序均未进 Top-5",
        "LEFT_TRUNCATED_FRONT_WINDOW":"左截断，已见槽另列",
    }
    return "，".join(f"{names[k]} {v}" for k,v in sorted(mapping.items()))


def report(trace, wick, states, exit_info):
    d0 = count_by(trace["d0_primary"])
    slots = count_by(trace["day_primary"])
    events = count_by(trace["event_primary"])
    observed = count_by(trace["event_observed_primary"])
    sorted_core = sorted(trace["core_failed_predicate_day_flags"].items(),key=lambda x:(-x[1],x[0]))
    core = "，".join(f"`{key}` {values}" for key,values in sorted_core)
    raw = "，".join(f"`{key}` {values}" for key,values in sorted(trace["raw_gate_day_flags"].items()))
    by_rule = {(x["cohort"],x["rule"]):x for x in exit_info["group_rule_stats"]}
    all_rules = {x["rule"]:x for x in exit_info["all_rule_stats"]}
    nice = {
        exit063.BASELINE:"固定 D+20",
        exit063.WHITE:"首次收盘下穿白线",
        exit063.YELLOW:"首次收盘下穿黄线",
        exit063.DOUBLE:"连续 2 栏收盘低于双线",
        exit063.WARNING:"首次可证警示后 2 栏未修复",
    }
    rows = []
    for rule in exit063.RULES:
        w, h, x = by_rule[(RELAPSE,rule)],by_rule[(HOLD,rule)],all_rules[rule]
        delay = x["trigger_offset_median"]
        delay_text = "—" if pd.isna(delay) else f"{delay:g}"
        rows.append(f"|{nice[rule]}|{x['triggered_n']}/562|{x['unknown_outcome_n']}|{delay_text}|"
                    f"{w['relapse_protected_n']}/151|{w['mark_minus_D20_mean_pp']:+.2f}|"
                    f"{h['hold_forfeited_n']}/411|{h['mark_minus_D20_mean_pp']:+.2f}|"
                    f"{x['paired_mark_minus_D20_max_close_dd_mean_pp']:+.2f}|")
    table = "\n".join(rows)
    state_counts = "，".join(f"`{k}` {v}" for k,v in sorted(states.items()))
    low_names = "、".join(wick["low_wick_stock_names"])
    return f"""# ACT-063A 路线 A／C 冻结研究回执

0 FIT。本轮累计研究 FIT 保持 291，研究、资格和交易边界沿用 ACT-062A。旧原件未覆写。所有结果为固定人群的历史观察。路线 C 独立于旗舰、买门禁和实盘动作。

## 路线 A｜162 事件为什么没有进入 DUAL

120 日 FULL 473,307 键、CORE 40,578 键，封存 DUAL 和 BLEND 各 1,200 席全部逐席对回。162 个事件在 D 日及可见的 D−5 至 D 窗口，对 DUAL 都是 **0/162**。洁净锚 Top-10 在 D 日为 {trace['d0_anchor_top10']}/162，在可见窗口为 {trace['observed_window_anchor_top10']}/162。

- D 日 162 个事件互斥归因：{d0}。
- 事件的六栏主归因：{events}。157 个完整观察窗，5 个左截断。先按已见窗最深关口归因，再把左截断单列。若对全部事件只按已见窗统计：{observed}。
- 共 972 个预期槽，实际观察 {trace['observed_slots']}，左截断 {trace['left_truncated_slots']}。重合股票日仍按事件槽计数。已见槽互斥归因：{slots}。
- 原 ACT024 L50M 与 ACT034 FULL OOS 就绪分别来自不同关口。ACT020 直接证据或明确市场规则的非互斥旗标：{raw or '无'}。缺冻结桥键时标 MISSING，缺具体排除证据时标 CANNOT_CONFIRM。
- ACT030 的 7 个主题含 8 个原子谓词，白线和黄线属于双线主题。当 FULL 就绪而 CORE 门禁失败时，各可证阈值失败槽可重叠计数：{core or '无'}。缺值谓词另列在机器回执。
- FULL 腿按冻结 E3HUBER 数值比较。CORE 腿按 ACT046 从两列冻结 E4B、E4C 各自同日平均并列分位后再取均值的排序空间比较。无物化原始 BLEND 分数。CSV 保留 1 起始席序、同日平均并列分位、截断及实选 Top-5 中位比较。差值以事件值减比较值计。历史 Top-50 原名单缺独立封存证据，当前成员是冻结规则重建。

## DQ-01／DQ-03｜增量纠错

ACT-057 的 `_n` 由有效样本长度生成，ACT-062A 将该有效数映为 hits，造成 42 股旧 hits／分母全相等，合计 {wick['old_hits']:,}／{wick['denominator']:,}。从 ACT-056A 全 42 股两份冻结原始指纹，按 ACT-057 的 full20 与峰日有效长上影占振幅 ≥40% 逐事件重算，得到 **{wick['corrected_hits']:,}／{wick['denominator']:,}**。42 股各自的率均精确匹配原表公布精度（%.10g）。原低长上影六股保持原身份，为{low_names}。

冻结生成器定义白线第一位、黄线第二位。D−1 收盘等于线记 1，任意关键值无效时整个状态为 UNKNOWN。前导零是定义的一部分。84 行配对状态从冻结 Reader 逐行回对（{state_counts}）。源码路径、行号及数值读入映射在补丁表。

## 路线 C｜562 条完整波段的独立退出观察轴

观察从事件 D 收盘后的 D+1 起，只读取截至当栏的冻结 Reader 值。首警沿用 ACT-061A 当栏量价与线位定义。预先固定后续 2 栏作为最小双栏确认，未按结果挑选。任一后续栏同时收盘不低于警示栏收盘且位于双线上方即视为修复。先决定观察时点，再联接 D+20 与事后保持／回吐标签。首警只使用第一个可证警示，早栏缺证明确附在规则结果。

|观察规则|触发事件|结果未知|触发栏中位|回吐组改善数|回吐组均值差 pp|保持组踏空数|保持组均值差 pp|配对最大收盘回撤改善 pp|
|---|---:|---:|---:|---:|---:|---:|---:|---:|
{table}

已确认不触发时以 D+20 作为对照时点。未知结果留空，均值按可证行计算。回吐改善和保持踏空分别指早于 D+20 的观察收盘相对固定端点为正或负。最大回撤按 D 收盘至观察时点的同基底收盘序列对先前最高收盘计算，截短窗口会机械改善该指标。观察价是当栏收盘标记，不含成交、滑点或净值模拟。全样本、四原型、两组和交叉组统计在 CSV。四原型代表及已知早栏缺证案共 5 案通过 105 个物理前缀和未来扰动断言。

## 来源与边界

冻结原件为 ACT-020/024/030/034/037/046、ACT-056A/057/061A/062A/062B。每份读取/哈希边界、快照、字段、样本计数、生成代码和治理字段见机器回执。标的只来自既有 KB42。未产生模型评分输出，未训练、发布或写入生产数据。ACT-063B 待 GEMINI_MASTER 核收放行。
""".encode("utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-name", required=True)
    parser.add_argument("--canary", action="store_true")
    args = parser.parse_args()
    assert args.run_name.isascii() and args.run_name.replace("_","").isalnum()
    started_at = datetime.now(timezone.utc).isoformat()
    usage=Usage()
    current = subprocess.check_output(["git","-C",str(ROOT),"rev-parse","HEAD"],text=True).strip()
    assert subprocess.run(["git","-C",str(ROOT),"merge-base","--is-ancestor",BASE,current]).returncode==0
    for name in ("run063.py","inputs063.py","trace063.py","dq063.py","exit063.py"):
        usage.pin(ROOT/name)
    pa.set_cpu_count(ARROW_CPU)
    pa.set_io_thread_count(ARROW_IO)
    with threadpool_limits(limits=BLAS):
        dictionary,recon,waves,controls = verified_sources(usage)
        _, _, stores, calendar, reader, _ = bind_reader(usage,set(dictionary.ts_code))
        profile,tape = dq063.load(usage)
        deps = exit063.load(usage)
        bundle = trace063.load(usage,recon,waves,calendar) if not args.canary else None
        usage.point("reading")
        wick_rows,wick = dq063.wick_patch(dictionary,profile,tape)
        state_rows,states = dq063.state_patch(dictionary,controls,stores)
        exits,exit_info = exit063.build(waves,stores,deps,canary=args.canary)
        if args.canary:
            usage.point("canary_calculation_and_verify")
            print("CANARY_PASS: 42 wick counts, 84 states, 5 representative causal cases, 105 prefixes",flush=True)
            return
        trace,trace_info = trace063.build(bundle,calendar)
        patch = pd.DataFrame(wick_rows+state_rows)
        payloads = {"report":report(trace_info,wick,states,exit_info),
                    "trace":csv_payload(trace),"dq":csv_payload(patch),"exit":csv_payload(exits)}
        usage.point("calculation")
        for key,frame in {"trace":trace,"dq":patch,"exit":exits}.items():
            assert len(pd.read_csv(BytesIO(payloads[key]),low_memory=False))==len(frame)
        assert all(0<len(payload)<=LIMIT for payload in payloads.values())
        assert len(trace)==1134 and len(patch)==47 and len(exits)==2885
        usage.point("verification")
        destination=ROOT/"results"/args.run_name
        destination.mkdir(parents=True,exist_ok=False,mode=0o700)
        stamps=[]
        for key,payload in payloads.items():
            path = destination/FILES[key]
            usage.write(path,payload)
            stamps.append({"path":str(path),"name":path.name,**digest(payload)})
        usage.point("write")
        evidence=dict(action="ACT-063A",status="LOCAL_WRITER_COMPLETE_PENDING_INDEPENDENT_REVIEW",
                      base_commit=BASE,head_at_runtime=current,governance=GOV,
                      started_at_utc=started_at,finished_at_utc=datetime.now(timezone.utc).isoformat(),
                      wall_s=usage.wall,cpu_s=usage.cpu,total_writer_wall_s=perf_counter()-usage.start,
                      total_writer_cpu_s=process_time()-usage.cpu_start,python=sys.executable,
                      host_logical_cores=os.cpu_count(),resource_peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                      arrow_cpu_threads=ARROW_CPU,arrow_io_threads=ARROW_IO,blas_threads=BLAS,
                      input_direct_minimum_bytes=usage.direct_read_bytes,
                      decoded_arrow_and_zip_projection_bytes=usage.projected_decoded_bytes,
                      output_written_payload_bytes=usage.write_bytes,
                      reader_accounting=usage.reader_accounting,physical_fs_io_bytes=None,process_tree_rss_bytes=None,
                      reader=reader,sources=usage.sources,trace=trace_info,dq01=wick,dq03=states,exit=exit_info,
                      failure_log_retention="Preserved under evidence if applicable",files=stamps)
        evidence_dir=ROOT/"evidence"
        evidence_dir.mkdir(exist_ok=True,mode=0o700)
        usage.write(evidence_dir/f"{args.run_name}_writer_evidence.json",json_payload(evidence))
        print(f"WRITER_PASS: {len(stamps)} files / {sum(x['bytes'] for x in stamps)} B",flush=True)


if __name__=="__main__":
    main()
