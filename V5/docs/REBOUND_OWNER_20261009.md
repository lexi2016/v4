# V5 超跌独立 owner 候选 / Mac 交接

基线 `2719328494a9ec3177a7be56e7348f86dd0137f5`；唯一开发分支
`v5/rebound-owner-20261009`。不改 V4，不修改 manager_plan、legacy_adapter、worker、
shadow_store、UI、archive 或其他并行模块；不合并、不部署、不启停服务、不采集、不交易。
已读根 AGENTS.md，`.agents/skills` 不存在；AGENTS 引用的 Mac 上位文件在云端不可用。

## 本次候选实现

`src/v5_shadow/rebound_owner.py` 提供：

1. `prepare_snapshot(request, destination)`：精确路径/日期/SHA/原主档回执校验，
   descriptor-relative O_NOFOLLOW 读取，单 fd 前后 inode/size/mtime/ctime 一致性；
   仅复制绑定字节，执行文件 0400、目录 0500，独立随机私有目录。
2. 独立新进程运行现有冻结 `read_rebound_screen`；执行前后验证快照完整文件集和 SHA，
   校验算法实际选择的四文件 SHA 等于请求绑定。网络、子进程和写入受 Python guard 阻断。
3. 保留原结果于 `legacy_diagnostic`（`UNTRUSTED_LEGACY_ASSERTIONS`），
   新 `research_observation` 保留所有分组、数值、门槛、缺口，降低无证明的单位/终态/资格标签。
4. 私有输出的 `runs/<run_id>/{artifact,manifest,receipt}.json`，receipt 最后写入，
   三文件逐个 SHA，独立读回并校验语义；没有 mutable latest、没有成功结果缓存或隐式覆盖。
   已通过请求格式验证后的输入/运行失败也保存 CANNOT_CONFIRM 回执。
5. `read_rebound_owner` + `manager_projection` 是父整合的明确接口。
   正式屏幕始终 `eligible_screen=None`；合成数据不得进入经理观察。

没有使用原 `rebound_v3_metrics` 四门函数，没有改选股门槛。
原 screen 保持 close ≤ prior60 high × 0.8、previous5 volume ratio ≥ 1.5；
成交额和低点反弹只作观察。缺日、重复日、pending/excluded/unresolved 均保留。

## 冻结身份与真实性界限

独立 `contracts/rebound_owner_capsule.json` 绑定原有 18 文件 source manifest、
V5 `uv.lock` 和 `pyproject.toml`，复用现有 `vendor/rebound_baseline`，没有再复制一套算法。
descriptor 的规范 JSON SHA：
`0a3f24142b3c63c2e16c08bd44fbac1d9d4909069d42fe3e5fae4c7204c3fb6e`。

- 原 source manifest 源提交 `9dfa50346357b6dc4b2463a30dcbf3718fce2f03`。
- 冻结 `workspace_plan.py` SHA：
  `be0d5e69ff72efd07d2caca4e68948245db4900a8c41f467e9c30f6899c044b1`。
- V5 lock SHA：`7cb690f890cc28b6a79311f07e724f61c3dc4411494d480c0041f075f0825bfd`。
- Python ≥ 3.14；锁包括 numpy 2.5.3、pandas 2.3.3、pyarrow 24.0.0 等。
  子进程会比对实际版本/导入 origin，不匹配则保存精确原因，不自行安装依赖。

这不是历史进程身份。现场提供的历史 release 当前文件 SHA
`96e8e8b7763f932cf353316acbfb45991b79fe00f1a7ca007659ebb76c728f4c`
也不证明当时运行代码。历史 run `ca77f41d26cd4c19b8a64237498f4256`
的 687 输入、657 完整、30 待确认、strict 53/near 317 是交接事实，
不是本候选测试结果。target 20260930、实际生成 2026-09-29T08:00:01.967606Z、
行情 session 20260928 必须分开保留；本次不伪造历史执行时间或自然运行证明。

快照身份仅证明“请求指定的这些字节被复制并用于本次计算”。
`owner_read_lease_verified=false`、`owner_origin_verified=false`；
不宣称 live authority 多文件原子快照、签名鉴真或 OS sandbox。
Python guard 也不能覆盖所有 native syscall 或同 UID 恶意进程。
实际执行的 started_at/finished_at 总是墙钟，不使用 research_cutoff 冒充执行时间。

## 输入合同与已知缺项

请求必须是以下精确键（不接受 `OWNER_VERIFIED` 或 `LIVE`）：

```json
{
  "schema_version": "v5.rebound_owner_request.v1",
  "target_date": "20261009",
  "signal_date": "20261008",
  "research_cutoff": "<本次真实UTC时刻或有证据的明确回放cutoff>",
  "data_kind": "RECORDED_INPUT_REPLAY",
  "input_root": "<现有Mac权威根绝对路径，解析掉软链>",
  "paths": {
    "panel_manifest": "assets/hk_0_2/panels/<精确日-SHA>/manifest.json",
    "panel": "assets/hk_0_2/panels/<精确日-SHA>/hkconnect_vipdoc_daily_panel.parquet",
    "master_manifest": "assets/hk_security_master/runs/<signal日>/<原run>/manifest.json",
    "master_artifact": "assets/hk_security_master/runs/<signal日>/<原run>/artifact.csv",
    "master_receipt": "assets/hk_security_master/runs/<signal日>/<原run>/receipt.json"
  },
  "files": {"<上面每一相对路径>": "<该原文件raw SHA256>"}
}
```

每个角色一份不同文件；5–32 件、总计 ≤1 GiB；单 parquet ≤512 MiB，其他单文件 ≤8 MiB。
必要的同日历史修复 parent manifest/parquet 也须逐文件绑定；不扫描 live latest 自动补依赖。
目录名、panel 路径等仍由原 reader 完整校验。

**原始 master receipt 必须补齐。** 已交接的历史四文件（panel 两件、master 两件）
不足以满足原 reader。新模块不会自造原 owner receipt。
`panel_latest.json` 和 master `latest.json` 是快照内根据显式角色生成的最小路由，
在 `adapter_generated_routing` 中披露；它们不声称是原 latest 字节，不提供任何额外证明。
原 master manifest/receipt/artifact 的 run_id、规范 manifest SHA、raw artifact SHA 均要一致。
未给足角色/文件 SHA 是请求格式错误；已给角色但缺文件或篡改是持久化失败回执。

`signal_date` 要等于原 HK 证券日历为 target/cutoff 算出的 market_session；
panel prepared_at、master captured_at 必须存在、含时区且不晚于 cutoff。
本模块不回拨执行时钟、不用旧主档冒充新日、不把晚到资料搬到盘前。
回放的实际完成时间仍然是现在，经理不会把这个新结果当成过去已知结果。

原 screen 读取 signal 日 master 仅用于名称，并遍历 signal 日 panel 代码。
它**不提供 target 日正式港股通资格**。今天的 698 成员归另一 owner：
15:00:08 OpenD 原帧不能当盘前；本模块不读取/修复/发布该资格。
今日可用 10/8 panel（457332 行、717 代码、当天 695）只是待 Mac 绑定输入的交接事实，
未在云端读取或验证。需要 Mac 提供 10/8 master 原 manifest/receipt/artifact；缺失则阻断，
不得以 9/30 或 10/9 主档替换原 screen 所需的 signal 日主档。

## 仍阻断正式经理准入

冻结 screen 会无证写入 HKD、FULL_DAY_CLOSE、VERIFIED_TARGET_UNIVERSE；
本模块调用其同文件 `rebound_native_evidence` 并明确保留：

- `REBOUND_HISTORY_VOLUME_UNIT_NOT_PROVEN`
- `REBOUND_HISTORY_PRICE_CURRENCY_NOT_PROVEN`
- `REBOUND_AMOUNT_UNIT_NOT_PROVEN`
- `REBOUND_PROVIDER_FINALITY_NOT_ATTESTED`
- `REBOUND_TARGET_MEMBERSHIP_NOT_BOUND`
- `REBOUND_NATURAL_RUN_NOT_VERIFIED`

安全观察把 `amount_hkd` 改名 `amount_native`，`verified_session` 改为 `observed_session`，
单位为 null、session_kind 为 NOT_ATTESTED_BY_PROVIDER、connect_eligibility 为 UNVERIFIED。
原始不实标签只存在带明确 UNTRUSTED 标记的诊断副本中，禁止作为经理正式输入。
研究投影保留原计算 `READY/READY_WITH_GAPS/CANNOT_CONFIRM` 于 original_computation_status，
自身始终 CANNOT_CONFIRM/main_screen_ready=false，避免把“算完了”当“正式合格”。

若要正式选股，需要父协调落实单位/全历史量纲一致性、provider 终态、target 日资格及 PIT
证明的具体 owner 合同；本候选没有可由请求参数打开的“强制 VERIFIED”开关。

## Mac 独立验收命令（云端全部 NOT_RUN）

先取得最终交付的固定 commit 并核对 readback SHA。只在现有 Mac 的隔离 checkout 和
私有输出运行；`PY314` 指向该 Mac 已有、与 V5 lock 相符的 Python 3.14+。

```sh
cd "$V5_CHECKOUT"
PYTHONPATH="$PWD/V5/src:$PWD/V5/tests" V5_REBOUND_OWNER_ORIGINAL_TESTS=1 \
  "$PY314" -B -m unittest test_rebound_owner -v
```

产品测试包括 snapshot/坏证据/不可变三件套/经理拒绝及原算法合成 integration 候选。
测试名称、数量以固定 commit 内测试文件为准；不把语法解析当测试通过。

真实输入由父在 Mac 用已确认的五路径生成请求，以下脚本只读原文件；请先明确
`REBOUND_AUTHORITY`、`REBOUND_PANEL_MANIFEST`、`REBOUND_MASTER_MANIFEST`（后两者是根下相对路径），
以及位于 repo 和 authority **之外**的 `REBOUND_REQUEST_PATH`：

```sh
"$PY314" - <<'PY'
import os,json,hashlib
from pathlib import Path
from datetime import datetime,timezone
root=Path(os.environ['REBOUND_AUTHORITY']).resolve()
pm=os.environ['REBOUND_PANEL_MANIFEST']; mm=os.environ['REBOUND_MASTER_MANIFEST']
panel=json.loads((root/pm).read_bytes()); master=json.loads((root/mm).read_bytes())
paths=dict(panel_manifest=pm,panel='assets/hk_0_2/'+panel['panel_relative'],
    master_manifest=mm,master_artifact='assets/hk_security_master/'+master['artifact_relative'],
    master_receipt=str(Path(mm).with_name('receipt.json')))
value=dict(schema_version='v5.rebound_owner_request.v1',target_date='20261009',
    signal_date='20261008',research_cutoff=datetime.now(timezone.utc).isoformat(),
    data_kind='RECORDED_INPUT_REPLAY',input_root=str(root),paths=paths,
    files={p:hashlib.sha256((root/p).read_bytes()).hexdigest() for p in paths.values()})
Path(os.environ['REBOUND_REQUEST_PATH']).write_text(json.dumps(value,ensure_ascii=False,indent=2))
PY
```

若原 panel 是带 parent 的历史修复版本，应补其已确认 parent 文件的 raw SHA 到 files，
否则保留失败诊断，不改阈值或偷偷回退。五文件原 SHA 要与父已验证 witness 对比。
初始化一次专有输出目录（不要选 V4 根或仓库路径）：

```sh
"$PY314" - <<'PY'
import os
from pathlib import Path
p=Path(os.environ['REBOUND_OUTPUT_ROOT']).resolve()
p.mkdir(mode=0o700,parents=True,exist_ok=False)
(p/'.v5-rebound-owner-root').write_bytes(b'v5.rebound-owner-root.v1\n')
PY
PYTHONPATH="$PWD/V5/src" "$PY314" -B -m v5_shadow.rebound_owner \
  --request "$REBOUND_REQUEST_PATH" --output-root "$REBOUND_OUTPUT_ROOT"
```

CLI 返回 reference/状态/原因；退出 0 仅说明尝试已持久化，必须检查 computation_status。
正式状态本版必定 CANNOT_CONFIRM；不能把退出 0 当正式资格 PASS。
复用同一请求重跑产生新的真实尝试 run_id，失败和 partial 均不被缓存吞掉。

## 经理最小接线方案（本分支未修改经理）

现状不仅 worker/legacy_adapter 拒绝 OWNER_VERIFIED，shadow_store 也拒绝其成功写入；
manager_plan 又读取冻结 screen 不存在的 `data_context.price_signal_date`。
不要通过修改这些旧标签绕门禁。父整合可增加独立可选 `rebound_owner` 绑定，
与已有 rebound shadow 引用分开：

```python
from v5_shadow.rebound_owner import read_rebound_owner, manager_projection
saved = read_rebound_owner(binding['root'], binding['reference'])
observed = manager_projection(saved, target_date=request['target_date'],
    research_cutoff=context['research_cutoff'], market_session=context['market_session'])
# 放在新的、明确未验证的 research diagnostics/observation 字段。
# 原 workspace.read_rebound_screen(None, context) 的正式 CANNOT_CONFIRM 屏幕仍保留。
# 不把 observed 或 saved['legacy_diagnostic']['payload'] 作为原正式 screen。
```

绑定应复用经理已有输入/输出路径不重叠检查，并把新模块文件身份纳入经理 implementation identity。
consumer 检查 target、signal、request cutoff、**实际 finished_at**，拒绝回填过去。
经理开始时间必须晚于 owner finished_at，不能复用生成 owner 之前的 manager now。
纯读回不启动算法、不写产物、不连接数据源。

## 验收分层

- 云端代码、AST 语法、冻结18件源码SHA/descriptor绑定、git diff 检查：见交付 evidence。
- Mac 合成产品测试：NOT_RUN（交父协调）。
- Mac 真实五文件测试和数值/分组差异比较：NOT_RUN。
- 经理集成、API/UI、部署、自然时段：NOT_RUN。
- 正式准入：CANNOT_CONFIRM，缺证明如上；本候选不冒称关闭这些门禁。
