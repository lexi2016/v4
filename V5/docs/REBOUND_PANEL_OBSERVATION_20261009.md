# 当前面板原生数值观察 / Mac 候选交接

本候选在 `v5/rebound-owner-20261009` 延续提交 `e11197d5056af80c6f6a2e80579e2cd2c3910b80`。
保留完整主档 `rebound_owner.py`、冻结 vendor、经理接线及已有测试原样。
本文件描述新增 `rebound_observation.py`；云端产品测试 **NOT_RUN**。
父反馈旧超跌29项、经理接线10项已在Mac通过；该反馈不等于新增观察入口已验收。

## 能提供什么

在实际当前时间读取绑定的原面板，计算原生数值比较。10/9 target 对应10/8 signal：
不是10/8当时已知资料的回测复现，也不是10/9实时行情或盘中成交量计算。

真实请求 `data_kind=RECORDED_INPUT_CURRENT`，target 必须等于进程实际香港日期，signal
还须与冻结 HK 证券日历 `plan_context` 一致。请求不接受 cutoff/observed_at；worker自行取墙钟。
跨午夜导致日期变化时不能强行沿用旧 target。`SYNTHETIC` 只用于明确合成测试，经理拒绝消费。

每股输出 `native_numbers`、两个 `native_comparisons`、具体历史缺日/重复日和输入缺项。
`arithmetic_pattern` 只允许：

- `BOTH_COMPARISONS_TRUE`：两次数值比较均为 true，**不代表正式通过**。
- `ONE_COMPARISON_TRUE`：一次为 true，不是 near 候选。
- `NEITHER_COMPARISON_TRUE`：两次均为 false。
- `INCOMPLETE_INPUT`：原两门必需输入不完整，不填零、不把 unknown 当一次未通过。

不输出 strict/near 列表、classification、排名、HKD或已验证终态/资格标签。
固定 `formal_status=CANNOT_CONFIRM`、`eligible_screen=null`，生产/BUY/订单/自然验收全部 false。
整个选定历史的价格和成交量尺度一致性均 `NOT_PROVEN`，provider终态未 attest，资格未验证。
原生比例可以保留数值，不能据此断言跨来源、修复 parent、复权或单位已经可比。

名称仅来自正在读取的 panel `name`，缺失时显示代码；`name_source=PANEL_LABEL_READ_NOW`
并记录本次 observed_at，不称历史主档。恢复的698名称/今日资格文件不参与本入口。
计算范围是 signal 日 panel 行，不因其他名单有698项就填出额外行情或宣称全市场覆盖。

## 原计算如何保留

新 capsule `contracts/rebound_observation_capsule.json` 固定源文件 SHA：
`be0d5e69ff72efd07d2caca4e68948245db4900a8c41f467e9c30f6899c044b1`。
原文件为 `vendor/rebound_baseline/v4/manager_research/workspace_plan.py`，未修改。

`extract_calculator` 解析已校验源 AST，复制以下原句/表达式，固定行边界和源段 SHA：

| 源行 | 保留内容 |
| --- | --- |
| 874–889 | 列校验、日期/代码处理、空session/重复当日代码早退、历史索引 |
| 893–993 | 原排序循环、60/5窗口、缺失/重复处理、float公式及内部bool |
| 997–1043 | 明确白名单的26项数值/状态及code表达式；排除master、来源、资格打包 |
| 1046–1052 | 原背景收益计算、append |

固定比率仍为0.8和1.5；不替换成同文件另一个四门 Decimal 函数。
原60 session包含半日，5日量窗口只取完整session，严格使用原日历日期集合。
20条背景量和3/5条背景价格仍按原记录窗口，公开名称改为 record，
明确 `ORIGINAL_LAST_AVAILABLE_RECORDS_NOT_CALENDAR_WINDOW_VERIFICATION`，不增加日历保证。
背景缺项不错误升级为两门核心缺项；两门不完整则保留原 `PARTIAL_UNKNOWN`。

这是 `FROZEN_NUMERIC_BODY_EXTRACT_NOT_COMPLETE_MASTER_OWNER`，不是完整旧owner的运行证明。
源码里的master名称、master source_refs及原authority打包未执行；没有空master或stub witness。

## 输入和快照合同

```json
{
  "schema_version": "v5.rebound_observation_request.v1",
  "target_date": "20261009",
  "signal_date": "20261008",
  "data_kind": "RECORDED_INPUT_CURRENT",
  "input_root": "<现有Mac原权威根绝对路径，resolve软链>",
  "paths": {
    "panel_manifest": "assets/hk_0_2/panels/<确认目录>/manifest.json",
    "panel": "assets/hk_0_2/panels/<确认目录>/hkconnect_vipdoc_daily_panel.parquet"
  },
  "files": {
    "<panel_manifest路径>": "<原manifest raw SHA256>",
    "<panel路径>": "<原parquet raw SHA256>"
  }
}
```

只接受上述精确键；files仅允许hk_0_2/panels原manifest/parquet，2–32件。
原历史修复路径若需parent，须将已确认parent的manifest/parquet及SHA一并绑定，
缺依赖时返回原witness原因，不另抓、不回退、不重建面板。
不得传master文件、原live latest、其他owner文件。

复用已验收owner的descriptor-relative O_NOFOLLOW流式读取、私有只读copy、
执行前后完整文件集/SHA验证、Python无写入/网络guard。单parquet≤512MiB，其他单件≤8MiB，
总量≤1GiB。快照内仅生成明确标记的panel routing pointer，不生成master或任何owner receipt。

原 `_read_hk02_panel_witness` 仍实际运行，校验源合同、精确日期、路径、SHA、发布时间、
修复依赖和截止时间；并交叉校验最终选择的panel/manifest SHA等于请求绑定。
原native_evidence仍校验原观测结构；master_captured_at保持None。
原witness中无证的HKD/FULL_DAY_CLOSE字段不公开，只公开经过绑定的SHA身份。

实际parquet依然读取原十列：trade_date_compact、code_norm、name、open、high、low、
close、amount、trade、pre_close。核心close/trade及60high/5trade缺失保留未知；
low/amount等数值缺失只影响观察。整个必读列不存在则拒绝，不伪造输入列。

稳定性仍只是“所绑定字节的私有副本前后一致”，不宣称live原子快照、原来源鉴真或OS隔离。

## Mac 精确命令

先checkout交付的固定提交；`PY314` 使用现有Mac与V5 lock完全相符的Python≥3.14。
本候选未安装依赖；运行时版本/origin不匹配会明确拒绝。

```sh
cd "$V5_CHECKOUT"
PYTHONPATH="$PWD/V5/src:$PWD/V5/tests" V5_REBOUND_OBSERVATION_ORIGINAL_TESTS=1 \
  "$PY314" -B -m unittest test_rebound_observation -v
```

Mac差分候选：原完整合成输入由旧factory生成，原reader与提取器逐股比较独立列出的
26个字段和成交额；包含阈值相等/相邻浮点、缺60日、历史/当日重复、当前close/trade缺失、
5日均量零、low/amount缺失、空日、20背景量NaN及窗口外重复。
另有只有panel两件、完全没有master目录的新入口→三件套读回候选。
这些测试在云端没有执行，不能把静态编译成功当差分通过。

真实10/8输入：父先确认 `OBS_AUTHORITY` 和根下相对的 `OBS_PANEL_MANIFEST`；
`OBS_REQUEST_PATH`、`OBS_OUTPUT_ROOT`、`OBS_RUN_SUMMARY`、`OBS_REFERENCE_PATH` 均选
仓库及authority之外的私有路径，不上传原始数据或结果。

```sh
"$PY314" - <<'PY'
import os,json,hashlib
from pathlib import Path
root=Path(os.environ['OBS_AUTHORITY']).resolve()
relative=os.environ['OBS_PANEL_MANIFEST']
manifest=json.loads((root/relative).read_bytes())
paths=dict(panel_manifest=relative,panel='assets/hk_0_2/'+manifest['panel_relative'])
value=dict(schema_version='v5.rebound_observation_request.v1',target_date='20261009',
    signal_date='20261008',data_kind='RECORDED_INPUT_CURRENT',input_root=str(root),paths=paths,
    files={p:hashlib.sha256((root/p).read_bytes()).hexdigest() for p in paths.values()})
Path(os.environ['OBS_REQUEST_PATH']).write_text(json.dumps(value,ensure_ascii=False,indent=2))
out=Path(os.environ['OBS_OUTPUT_ROOT']).resolve()
out.mkdir(mode=0o700,parents=True,exist_ok=False)
(out/'.v5-rebound-observation-root').write_bytes(b'v5.rebound-observation-root.v1\n')
PY
PYTHONPATH="$PWD/V5/src" "$PY314" -B -m v5_shadow.rebound_observation \
  --request "$OBS_REQUEST_PATH" --output-root "$OBS_OUTPUT_ROOT" > "$OBS_RUN_SUMMARY"
```

脚本为10/9当前任务；以后执行不可把target维持10/9并回拨时钟，需明确新target/signal。
父须把刚读取的原文件SHA与已有witness核对，再运行；必要parent文件显式补入files。
初始化只做一次，后续同一输出根每次产生新run，旧attempt不覆盖。

查看持久化的全部观察：

```sh
"$PY314" - <<'PY'
import os,json
from pathlib import Path
value=json.loads(Path(os.environ['OBS_RUN_SUMMARY']).read_bytes())
Path(os.environ['OBS_REFERENCE_PATH']).write_text(json.dumps(value['reference']))
PY
PYTHONPATH="$PWD/V5/src" "$PY314" -B -m v5_shadow.rebound_observation \
  --reference "$OBS_REFERENCE_PATH" --output-root "$OBS_OUTPUT_ROOT"
```

先检查 `computation_status=NATIVE_VALUES_OBSERVED`，再查看rows/counts/缺项；
`CANNOT_CONFIRM`计算失败时rows和counts为null，不冒称真实空结果。
CLI退出0仅说明尝试已保存，不能当计算成功或正式准入。
存储为 `runs/<run_id>/artifact.json、manifest.json、receipt.json`，receipt最后写，
reference绑定三文件SHA；读回还校验公开字段白名单、布尔/数值类型、数值模式、
尺度状态和panel/manifest/calendar/源码身份。

## 经理最小观察接线（本分支不改经理）

父增加独立 `rebound_observation` 绑定，保留已有完整owner binding：

```python
from v5_shadow.rebound_observation import read_rebound_observation, manager_observation
saved = read_rebound_observation(binding['root'], binding['reference'])
observed = manager_observation(saved, target_date=request['target_date'],
    market_session=context['market_session'], research_cutoff=context['research_cutoff'])
# observed 只进入明确“原生数值观察/缺口”字段。
# 正式screen仍保持原路径；不得把rows转成strict/near或正式候选。
```

经理cutoff必须晚于本次实际finished_at；日期不符、晚于cutoff、合成数据时不给rows。
纯读不重算；绑定根应纳入既有不重叠检查，新adapter SHA纳入经理运行身份。
正式结果始终eligible_screen=None，即使所有原生比较为true。

## 本次验收边界

云端仅代码/AST及提取AST的编译检查、冻结文件哈希、差异范围、git检查。
Mac新测试、真实10/8面板观察、经理观察集成、UI、部署、自然运行均NOT_RUN。
今日资格owner、公告及archive任务未改动。缺少历史主档不会再无依据阻断本观察入口，
但核心行情缺项、PIT、稳定性和原panel witness门禁仍执行。
