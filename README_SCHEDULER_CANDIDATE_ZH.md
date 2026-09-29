# V4 scheduler / 研究面板最小接管候选 — 2026-09-13

**PARTIAL_CANDIDATE / HOLD：不是完整 v16 接管，不是部署包。不得据此停止旧 scheduler、研究面板 producer 或旧 review generator。**

唯一源码基线是本次 handoff 的 `canonical/` 当前 worktree，非此前 9 月 11 日优化 ZIP，非 v16 整树。输入 ZIP SHA256：
`75c161e48874dc6f973d79c421110f1b7c1d0f9399119db7e670241be3f9013f`。

本候选保留现有单一 daemon/runner/registry/panel/producer。只改 3 个生产源码文件的局部 hunk：动态 authority 导入、精简 stdout 与 exact receipt 绑定、A/HK 配置及 backoff 隔离、HK 原有版本门禁接线、现有到期槽的首次执行优先。`a_share_daily_sync.py`、M3 全部文件、manager、模型、安全门、日期/池合同、launcher/plist 均未修改。

阅读 `docs/scheduler-panel-candidate-20260913.md`，以及 ZIP 根目录 `CANDIDATE_CHANGE_MANIFEST.json`、`BASELINE_FILES.json`。完整树仅用于隔离复测；**不要解压覆盖当前工作树或活动 release**。应用统一补丁之前，先逐字节检查 preimage：

```bash
python3.14 <候选目录>/verification/scheduler_candidate/check_preimage.py \
  --root <目标隔离工作树> --manifest <交付根>/CANDIDATE_CHANGE_MANIFEST.json --mode before
cd <目标隔离工作树>
git apply --check <交付路径>/V4_SCHEDULER_PANEL_20260913.patch
git apply <交付路径>/V4_SCHEDULER_PANEL_20260913.patch
```

任一 SHA 不匹配即停止；禁止自动 `--reject`、强制覆盖、回退用户后续修改。App.vue / App.spec.ts 已相对旧 M3 review 漂移，本候选保留的是当前字节。

在有依赖的 Python 3.14 环境、**新的独立验证目录**中复测：

```bash
cd <候选源码目录>
python3.14 verification/scheduler_candidate/run_checks.py --suite new --output <全新验证目录>
# 另用一个全新目录运行继承回归或 combined；结果不可复用/覆写。
python3.14 verification/scheduler_candidate/run_checks.py --suite combined --output <另一个全新验证目录>
```

测试仅在临时目录生成合成 SDK 响应和合成二进制 fixture；不连接 OpenD/HQ/8910，不读真实资产，不写正式数据。交付不带临时 `.day`、parquet、state 或 marketdata。SDK fixture 不代表已验证真实 SDK，不会替代继承测试的真实 pytdx 依赖。

本轮 Linux/Python 3.13.5：新增 35 passed / exit 0；combined 132 passed、2 failed / exit 1，失败为真实 pytdx 缺失。前端三个命令 exit 127，不能沿用旧 M3 review 的前端通过声明。

完整正向 artifact/manifest 链仍为 CANNOT_CONFIRM：A formula/seed、HK frozen assets 与受信数据未包含；跨 stage/research-day v16 闭包未审；review generation 仍 UNREVIEWED/REFERENCE_ONLY。已有测试证明的完整链是**真实入口和更新器参与的离线失败关闭链**，不是完整面板 READY。
