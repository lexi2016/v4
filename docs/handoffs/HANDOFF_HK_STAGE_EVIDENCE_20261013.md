# 20261013 七阶段复盘证据修复

## 结果

8873 已部署并完成页面验收。七阶段都有观察选股行（共 70 行、31 只去重股票，观察口径覆盖收盘 Top20 的 6 只），但正式七阶段并集要求七阶段证据完整。现为 1/7 完整，其余六阶段历史缺口保留；未将观察数据升级为当时可用数据。

本轮直接处理，不使用子智能体；独立 Reviewer：NOT_RUN。自然时段：NATURAL_SLOT_UNVERIFIED，不能以本次手动重建代替下一交易日自然验收。

## 定位与修改

- `ops/build_close_review.py:132`：旧运行版本 consumer 投影遗漏来源证据。仅在字段缺失时读取既有已校验 selection envelope，并要求 run_id 一致；恢复七个阶段的来源信息，不新增采集。
- `ops/build_close_review.py:26`：竞价实际输入是二筛 Top20，旧记录却以 Top100 计算缺口。复用原二筛校验器，检查同日、CSV SHA、20 行完整性、时点安全和所选 Top10 顺序。只修正复盘判断为 20/20，保留原阶段 PARTIAL_WITH_ROWS 记录。
- `domains/close_review.py:211`：消费上述专用复盘校正状态，保留历史补采及缺口限制。
- `apps/web/src/components/review/HkCloseReviewPanel.vue:208`：新增七行证据明细，分别显示输入数量、选股行、真实采集时间与缺口。

## 剩余六阶段

| 阶段 | 现有输入/观察结果 | 无法从现有产物恢复的证据 |
|---|---|---|
| 09:30–09:35 | 100/100，10 行 | 12:09:12 补采；缺当时盘口，不能证明时点可用 |
| 09:35–09:40 | 100/100，10 行 | 同上 |
| 09:40–09:45 | 100/100，10 行 | 同上 |
| 09:45–10:30 | 100/100，10 行 | 同上 |
| 13:00–13:15 | 100/100，10 行 | 阶段产物未留存可验证采集时间，缺有效快照及当时盘口 |
| 14:45–15:00 | 100/100，10 行 | 快照查询 15:01:59–15:02:00，69/100 股票报价超过 15:00 截止，缺当时盘口 |

15:45–15:55 是第八阶段，不属于既有七阶段口径，不能替换上述缺口。未再次调用富途，也未改写历史阶段原始数据或选股产物。

## 验收

- 行为复现：旧 builder 对新增回归测试 7 项失败；修复后通过。
- canonical Python 三文件测试：30 passed；最终实际 scheduler 候选两文件测试：27 passed。
- UI 组件：6 passed；实际部署前端来源候选：6 passed；Vite build 成功。
- 全量类型检查仍存在既有错误；实际候选与其未修改基线错误逐行一致，无本次组件错误。不是全量类型检查 PASS。
- API：20261013 复盘状态 MODEL_REVIEW_PARTIAL_STAGE_EVIDENCE，竞价 READY，未核验阶段 6；来源证据七阶段均已读回。
- UI：重新加载真实 8873，点击 16:10 收盘复盘，确认七行明细、1/7、竞价 20/20 及六个具体缺口。正式并集仍显示不可用；观察口径继续可见。
- RESEARCH_ONLY=true；production_allowed=false；buy_gate_updated=false；orders_sent=false。

## 身份与复现证据

源码根 `/Users/lexi/Desktop/学习/v4_app`；Git 基线 `ec31cbc07060e034104f632857bb61a9714f026c`，本轮仅五个源码/测试文件及本文。运行包以并行发布后的 v10 为基底，保留 manager-selection 页面和原有资产；8910 未改。

- scheduler：`/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/hk-stage-evidence-20261013-scheduler/app`，manifest SHA `680f0571f7032072411a6de9f769bb44f8eb3e5f50907ea3f0cf3eae526689fd`。
- API：`/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/hk-stage-evidence-20261013-api/app`，manifest SHA `758efa07955f2c061478c1b4d63fcb0db0972db86fc865996295b557061deb1e`。
- 实际根页面资产 `main-fdvT1d-E.js`；前端构建复用原 R10 根页面源码，仅替换本组件，未覆盖并行 manager-selection 入口。
- 复盘 SHA `030f8809dfd33cd8d91b09a20e490a4e82f972f536551d6d9e6cf0df08e07027`；通过原 ReviewStore supersession 路径替换旧复盘。

本机证据目录 `/Users/lexi/Desktop/学习/agents调试/V4_HK_STAGE_EVIDENCE_20261013`：`source_sha.json` 记录五文件前后 SHA 与 blob；`delta.patch`、`stage_audit.json`、`deployment.json`、`build.json`、`api.json`、`ui.txt`、`ui.png` 和测试日志。原始行情与这些本机运行产物不上传 GitHub。

测试解释器为现役 v3.5-mac Python。复现命令：`python -B -m pytest -q tests/test_close_review_verified_inputs.py tests/test_close_review_producer.py tests/test_close_review_slice.py`；前端在对应源码目录运行 `npm exec vitest run src/components/review/HkCloseReviewPanel.spec.ts`、`npm run build` 和 `npm run typecheck`，具体原始结果见上述日志。

私有同步分支 `codex/hk-stage-evidence-fix-20261013`；成功同步后的 commit、远端 ref 与逐文件 blob 读回记录保存在本机 `github_sync.json`。
