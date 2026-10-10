# V4：旧链复用的局部修复

**本包交付同两个文件内三处已复现、已修补的代码错误。20261009 的真实选股恢复仍未完成，现场验收保持 BLOCKED。**

基线为 `lexi2016/v4` 的 `e72607634d46146b0b6c0f4a0396f6b2939589f7`，输入为 R2 问题包。当前目标严格保持 `target_trade_date=20261009`、`publication_date=2026-10-08`。包内历史 `20261008 / 2026-10-07` 的 37 条入选决策、33 个港股代码仅作历史公告证据，本轮没有重新运行或复制这份名单。

## 已修改的内容

| 文件 | 可复现错误 | 最小修复 | 与现场失败的关系 |
|---|---|---|---|
| `ops/run_manager_daily_announcement.py` | `build-reviewed` 先建立选股扩展，再加入审核回执，基础产品 SHA 随后变化，原消费者报 `ANNOUNCEMENT_SELECTION_BASE_PRODUCT_SHA_MISMATCH` | 复用原 `register-handoff` 的身份绑定顺序：审核回执进入基础产品后，使用原验证器把同一组已校验决策重新绑定到最终基础 SHA | 这是辅助构建入口的确定错误；历史成功的 `register-handoff` 本身没有此问题。尚未证明它造成当前 exact-pair 产品缺失 |
| 同一 runner 的 `readback` | 当前原 API 返回有效完整回执时，旧 CLI 用省略字段的临时 product 验证，误报 `ANNOUNCEMENT_OWNER_IMPORT_RECEIPT_HANDOFF_BINDING_INVALID` | 逐字复用固定仓库已有 `_readback` 修法，调用当前既有 `validate_owner_analysis_readback` 校验完整消费链 | 解除已复现的旧 CLI / 当前回执不兼容；不会创建缺失的真实产品 |
| `v4/manager_research/workspace_plan.py` | 二进制浮点乘法会把 `0.28 <= 0.8 × 0.35`、`0.56 <= 0.8 × 0.70` 错判为不满足 | 沿用该模块已有的 Decimal 比较方式处理包含等号的 80% 价格门槛；展示字段仍保持既有 float 类型 | 这是确定的边界计算错误；不能解除成交量单位/尺度未证明导致的 pending |

生产差异只有上述两个文件。日期、来源、审核、SHA、PIT、完整性、成交量证明、原 Stage、BUY 和 Vibe8910 的规则保持原状。研究标志保持 `RESEARCH_ONLY=true`、`production_allowed=false`、`buy_gate_updated=false`、`orders_sent=false`。

## 已取得的验证

| 验证 | 实际结果 | 能证明什么 |
|---|---|---|
| 15 项新增针对性测试，原函数 | 7 failed / 8 passed | 能复现基础 SHA 错误及两组 80% 等号错误 |
| 后补 10 项 CLI 读回测试，旧 readback | 1 failed / 9 passed | 有效当前回执被旧 CLI 错误拒绝 |
| 全部 25 项新增测试 + 问题包原 17 项定向测试 | **42 passed** | 使用原构建器、验证器、存储和 FastAPI 路由的合成数据回归通过 |
| 同基线另取回的 39 项历史参考测试 | 修复前后均 **1 failed / 38 passed** | 有一项既存 fixture 与当前日历校验不匹配，未改测试或放宽生产规则 |
| 独立审查 | 见 `validation/INDEPENDENT_REVIEW.md` | 两文件三项修复、测试边界及诊断工具的复核记录 |
| Mac 部署、真实数据重跑、现场 API、浏览器重载、自然周期 | **NOT_RUN** | 当前会话没有 Mac 执行环境及完整原始 owner 输入 |

新增公告测试覆盖入选、观察、不入选、未评估、无决策、错误日期、回执来源篡改、已存在文件保护；也覆盖当前日期的原 handoff 导入、两次 workspace GET、GET 前后文件 SHA 不变及历史合成 handoff 文件保留。测试中的 `HK.01234`、时钟、正文、reader/reviewer 都是明确标识的合成输入。

新增 CLI 读回测试覆盖完整当前回执、缺失/未验证消费链、六类身份绑定篡改，以及已有 legacy receipt 在当前 handoff 通过验证时的原字节保留。复用的原代码来源与函数 SHA 见 `provenance/READBACK_REUSE_SOURCE.json`。

新增超跌测试直接调用原 `read_rebound_screen`，检验等于、略高于、低于、缺失值；所有成交量证明缺失的行仍保持 pending。它们没有覆盖一个真实 owner 已证明成交量的完整入选分支。

已知历史参考失败为 `test_missing_original_archive_is_not_empty_connect_selection`：旧 mock 的 `read_scope` 没有当前 `calendar_applicability`，实际返回 `HK_CONNECT_CALENDAR_UNVERIFIED`，聚合状态为 `PARTIAL`，而旧断言预期 `READY`。原测试字节保留，前后日志均附在包内。

测试环境是 Linux/Python 3.12.14。ZIP 缺少的导入依赖从同一固定 GitHub commit 补齐，全部作为隔离测试支持源码，来源记录于 `provenance/TEST_ASSEMBLY_SOURCES.json`；这些支持模块没有作为 live 替换文件交付。环境详情及 Starlette/httpx 弃用警告见 `validation/ENVIRONMENT.json`。

## 四条现场链的下一步

| 链 | 当前仍未完成的内容 | 已缩小到的原入口 |
|---|---|---|
| ANNOUNCEMENT | 当前 exact-pair 的真实 catalog、正文、reader/reviewer、decisions、registered handoff、owner receipt 及 cutoff 消费 | 原 runner 的 `capture / register-handoff / import / readback`；优先读取或续接已存在的同日期 run |
| HK_CONNECT | 20261009 V2 authority 的原根目录、六文件及 owner pin/PIT | 比对实际 `V4_MANAGER_UNIVERSE_ROOT` 与原 HK job 的 `--hk-asset-root.resolve().parent.parent`；已有只读元数据检查工具 |
| OVERSOLD | 原 HK02 panel、60/5 session 覆盖、六个比较日的真实 volume unit/scale 证明 | 已找到原 HK02 publisher。已检查的旧导出均声明 `NOT_PROVEN`，当前没有可直接接入的兼容单位证明 |
| Stage | 原目标日指针、artifact/manifest/receipt 及固定输入池 | 原 `SelectionStore` 和 consumer，精确键 `20261009/STAGE_0935_0940/HK_CONNECT`；另行核验同日 A 完整池和 HK canonical D-1 Top100 |

现场记录来自原 [CURRENT_CHAIN.json](https://github.com/lexi2016/v4/blob/e72607634d46146b0b6c0f4a0396f6b2939589f7/handoff/selection-output-reuse-issue-20261010-r2/CURRENT_CHAIN.json)，没有被本轮重新观测覆盖。详细来源和判定规则见 `OWNER_CHAIN_FINDINGS.md` 与 `LOCAL_OWNER_CONTINUATION.md`。

## 应用与复跑

先阅读 `MAC_APPLY_AND_ACCEPTANCE.md`。只对隔离候选中与 `SOURCE_MANIFEST.json` 的 before SHA 完全一致的两个目标文件应用；runner 的来源是 historical-r2，workspace_plan 的来源是 current-live，不能整目录互换。

在本机已有完整 V4 checkout、原项目 Python 依赖及上述候选文件的前提下：

```bash
cd "$V4_PATCH_APP_ROOT"
PYTHONPATH="$V4_PATCH_APP_ROOT" "$V4_PYTHON" -m pytest -q \
  "$V4_REPAIR_PACKAGE/tests/targeted" \
  "$V4_REPAIR_PACKAGE/tests/upstream_reference"
```

39 项扩展历史参考测试单独运行，保留已说明的基线失败：

```bash
PYTHONPATH="$V4_PATCH_APP_ROOT" "$V4_PYTHON" -m pytest -q \
  "$V4_REPAIR_PACKAGE/tests/extended_reference" --tb=short
```

这些命令不会证明真实选股完成。完成验收仍需同一精确日期、原输入和判定记录、产物/run/SHA、原接口与重载页面逐项对上；合法零结果也必须有完整覆盖及逐项拒绝原因。`CURRENT`、HTTP 200、可见页面或测试通过均不能替代这条证据链。

## 包内文件

- `before/`、`after/`：两个目标文件的完整前后版本。
- `runtime.patch`、`SOURCE_MANIFEST.json`：精确差异、来源及前后 SHA。
- `tests/`、`validation/`、`provenance/`：必要测试、真实执行日志、审查与来源记录。
- `tools/inspect_connect_metadata.py`：调用原 reader 的本地只读诊断工具，不产生选股、行情或 authority。
- `MAC_APPLY_AND_ACCEPTANCE.md`：候选应用、回滚、真实验收步骤。
- `LOCAL_OWNER_CONTINUATION.md`：最小现场证据续接说明。
- `HK_CONNECT_LOCAL_REUSE_RECIPE.md`：原 HK root 对照与精确六文件检查。

本包不包含原始行情、完整公告正文、16 MB owner body、账号数据、依赖安装目录或真实新候选名单。
