# Issue #35 · 2026-10-12 三路原 owner 联调验收

本目录**不包含新选股算法或第二 producer**，只调用现役 `8873` 的**原 API owner**，并把实际 HTTP 响应与每路 `run/SHA/gaps/rows` 独立留痕。默认只读，必须在原 Mac 的 V4 本地进程上运行，云端不能代替。

## 已核基线和限制

- GitHub 基线：`codex/three-lane-local-integration-20261011-r1`，提交 `2324ec87daf94802a6d40872f4c0f629a1bb138e`；旧运行版 manifest 为 `f2940d02d408b52bde35258b2366e32a4b7e3ad59193b313b243677d590eae1d`。
- 另一个 US 日常链交付报告指出 10/12 手工计划曾在**不同发布版本**上读回 CURRENT；不得把两个发布版本的结果拼为一次成功，也不能改旧 sealed 产品 SHA。
- 目标 `20261012`，公告日 `20261009`，预期 US session `20261009`；不复用 10/09 计划下的 55 条公告结果。
- 10/11 本地日期时，原 `us_mapping_research._target_bound_cutoff` 禁止创建未来 10/12 正式 daily 产物，脚本 `--refresh-us` 也同步拒绝提前调用。
- 正式产物必须由原 registered announcement owner、rebound screen/research ledger、US daily mapping owner 生成；本脚本只读回，**不补造** `run`、`product_sha256`、`receipt` 或股票。
- `RESEARCH_ONLY=true`、`production_allowed=false`、`buy_gate_updated=false`、`orders_sent=false`。

## Mac 上执行

先核 `launchctl` / 实际 8873 PID、加载模块绝对路径与 SHA、数据根，并对照已部署 release 和 canonical 源。**不要覆盖在运行目录，也不要直接把本仓库 handoff 目录当作启动应用。**以下仅调用原本地 API。

```bash
# 1. 纯 GET，生成新的、此前不存在的证据目录
python3 handoff/issue35-20261012/issue35_canary.py \
  --target 20261012 --announcement-date 20261009 \
  --output-dir "$HOME/issue35-readonly-20261012"

# 2. 明确由原 Owner 保存研究计划（不是正式 BUY / 自然时段）
python3 handoff/issue35-20261012/issue35_canary.py \
  --target 20261012 --announcement-date 20261009 \
  --refresh-plan --output-dir "$HOME/issue35-plan-20261012"
```

其他**显式可选**的原 owner 调用：`--refresh-catalog` 仅运行 Eastmoney 原日期目录 collector；`--import-refs /absolute/path/verified-ref.json` 仅导入注册 handoff 的四字段引用，绝不接收股票名单；**10/12 到来并符合原 owner 准入后**可 `--refresh-us` 运行原日常映射。任何操作前应确认 owner 原始合法输入及渠道依赖已备齐。重复运行须选不同 `--output-dir`，脚本不覆盖已有回执。

验证本目录源码：
```bash
python3 -m unittest discover -s handoff/issue35-20261012 -p 'test_*.py' -v
python3 -m py_compile handoff/issue35-20261012/issue35_canary.py
```

## 输出和验收门槛

`issue35-receipt.json` 逐次保存 HTTP 原始字节 SHA、真实 plan 状态、输入身份、公告/超跌/HK 已有逐股记录、US raw 发现和 US daily owner 分离状态；同时保存 **auto 连续两次**与**dynamic 实时回看**。完整和未完成用 `null`、原 gaps、run、来源 SHA 表示，不能以空数组推断扫描通过。返回码 `0` **仅代表保存计划的两次 auto 读回均为 CURRENT 且身份一致**，不代表三路全部完成；`3` 代表其未稳定；`2` 代表读取/验证错误。

- **A 公告**：10/12 计划、10/09 公告及窗口内合法 owner 产品/注册 handoff/审核回执，合法 cutoff，逐股入选/观察/未评估。
- **O 超跌**：原 60 日及前 5 日完整真实量价、单位、个股缺项、原 screen/ledger 与保存计划 run/product/attempt 同源。
- **U 美股映射**：原 session 10/09、研究评估和关系证据；`us_market_attention=READY` **不等于** `us_mapping_research.daily_run=COMPLETED`。合法空结果也必须有真实 owner 已评估证明。
- **I 计划身份**：新原 owner 计划可反复读回 CURRENT，真实变化会 STALE，日期、payload/receipt SHA 和截止时点不被删除。
- **R 页面**：原 V4 页面重载 `/manager-selection/?date=20261012&plan_date=20261012`，逐路对照真实姓名、代码、理由、run/SHA、资格与待核缺口。脚本不能证明浏览器或 scheduler 已执行。

`owner_receipts_independently_rehashed`、`browser_reload_verified`、`natural_run_verified` 均保持 false，直到原 Mac 主控与不同 Reviewer 取得单独实物证据。不能通过只改页面或放松校验关闭 Issue #35。

**当前交付**：可用于隔离验收的脚本与测试，实际原 owner 输入补采、发布、浏览器验收和自然时段 **NOT_RUN**；问题仍 OPEN。
