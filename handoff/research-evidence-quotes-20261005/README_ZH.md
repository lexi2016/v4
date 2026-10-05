# 公司材料正文摘录显示：隔离候选

本轮修复一个已复现的页面缺陷：公司材料已经经过 `sanitize_cards` 和 `build_research_attention`，研究卡片的 `evidence_quote` 仍在 Python 输出及 TypeScript 校验后保留，但 `researchAttention.ts:evidenceDetails()` 只显示时间与链接，展开也看不到正文依据。

运行源码只改一个文件、增加 7 行：在 COMPANY_MATERIAL 的现有证据展开区显示材料标题和原样摘录；无有效字符串摘录时明确缺失，不以标题补正文。使用现有 textContent 安全渲染，保留原链接过滤。提示原文摘录不证明事件发生在当前窗口，不新写事件判断、分数或建议。

**原首选“旧背景句被分类为正向观察”未在本候选修复。** R11 回执明确正文解释仍由原作者处理，因此本轮先告知转为这个独立显示缺陷；未碰正文分类器。该候选也不解决镜像证据与官方首发、既有 US 时钟等其他合同问题。

## 身份与未覆盖的源码

- 基线：`640c77a7f019a1a211faea937b70cc10e4329afc`，分支 `codex/announcement-date-workflow-20261005`。
- 重建：`d57dbb1b0765333f8b176c641a7356ad9744253b` 的 manifest-bound API 快照（不是 canonical），加 R11 `handoff/announcement-date-workflow-20261005/api` 六文件覆盖；六个 SHA 全匹配。
- 上游报告的运行身份：`manager-announcement-r11-20261005-date-catalog-r1/app`。云端仅使用隔离副本 `/workspace/candidate-evidence-quotes/app`，没有连接 Mac 或把 PR25 当活动源码。
- 884 个基线文件核对：883 个逐字不变，唯一变化为该 renderer；详见 `evidence/source-inventory.json`。#22、#24、R10 ledger、R11 目录工作流源码保持原字节，Stage 未改。
- 新独立分支：`codex/research-evidence-quotes-20261005`。本目录交付候选，不覆盖冻结交付目录。
- 目标文件：`apps/web/src/manager-selection/researchAttention.ts`。
- before SHA256：`9b9ea7aef33e504da7d99f2b16b1e632448a63dfe0971ae275730e6311c5ce3a`
- after SHA256：`e4fb78e633fb693a08e0d92a518377f78a6c7ff95c8f430d0d7e0ad25916c4d2`
- **canonical 同名文件为不同版本**：`b42816d5fe43adcd59bdd14823341a8005455543a949cd1dc5d83d8ab0bb4817`；本包不授权直接覆盖它。

已读最新 Issue8/21/23/24 评论以及 R11 receipt。Issue8 最新可见为 R10 验收 comment5976190559，Issue23 最新为 R3 发布 comment5969739769，Issue24 最新为 R9 大计划读回 comment5967029030。未发现本显示缺陷的新修复交付；发布前 R11 远端头仍为上述基线。

## 云端验证

环境：Linux / Python 3.12.14 / Node 24.19.0 / Vitest 4.1.10 / TypeScript 5.9.3 / jsdom 28.1.0；Python 回归使用隔离 venv 的 pytest 9.1.1。项目声明 Python >=3.14，因此云结果不替代 Mac 原生 3.14 验收。

| 检查 | 结果 | 证据 |
|---|---|---|
| 新增测试，同一最终 fixture 对原文件 | 9 FAIL、2 PASS；缺失摘录的断言真实失败 | logs/red-final-fixture.log |
| 新增合成测试 + 既有观察/ledger/attention 四套 | 103 PASS（其中新增 11） | logs/green-final.log |
| 五套扩展前端回归 | 112 PASS、1 FAIL/BLOCKED：旧测试硬编码 Mac 文件缺失 | logs/green-regression.log |
| R11 目录 + R10 ledger Python 回归 | 20 PASS、1 SKIP（实际 Oct2 projection 未提供）；1 既有 Starlette warning | logs/python-regression-final.log |
| renderer + 新测试依赖链严格 TS 检查 | exit 0 | logs/typecheck-scoped.log |
| 补丁正向、反向 | 精确 after/before 字节一致 | logs/patch-verification.log |

新增测试使用明确合成的公司、正文、日期、source_refs 与 workspace 外壳。每次运行调用真实 Python `temporal_role → sanitize_cards → build_research_attention`产生研究卡，再经过真实 `validateManagerWorkspace`。面板用 fetch fixture 响应，经真实 request decoder、`mountCatalystObservations` 和 jsdom DOM；展开原有 details 并核对准确摘录、标题与 READY。并测截止后排除、只有标题不造正文、空/非法摘录、负面/历史措辞原样显示、XSS 字符串和不安全链接、输入不变。负面/历史显示边界用明确的测试端变体，不冒充分类器已经识别这些语义。

旧 snapshot 未包含 `issue8R2.ownerObservations.json`。为运行既有两套测试，云端从已交付 `V4_SELECTION_GAPS_R1_20261003/evidence/FROZEN_SELECTED_FIELDS.json` 的 `announcement_review.positive_observations` 精确提取 9 条记录；源 SHA `e1a91587c972b22c7118cc7dec07c9d88c57d090814dab2b15e97fa8e19f73be`，提取 JSON SHA `0a56e12d5a56e7534b9a484e8bc2443677a2abeb5d3a9feea56ac0d641b2dce8`。这不是原缺失文件的字节等价证明；未重新采集、未把其算成当前行情。本候选只上传两份新合成测试，不重复上传这九条原产物。

保留早期失败日志，区分测试准备错误与有效红灯：`preparation-invalid-shell.log` 为缺 US input contract；`preparation-missing-fixture.log` 为旧 JSON 缺失及 synthetic GET shell 尚缺 read_context；两项仅修测试输入。首次 npm 默认 cache 不可写，改用 /tmp 缓存后按原锁文件安装成功；系统缺 pytest，隔离 venv 安装后才执行 Python 回归。无依赖清单或锁文件修改。

未执行：完整前端构建、全量 typecheck/测试、真实浏览器页面、真实 API/行情、Mac 测试、集成、部署、自然时段、333MB 回放、全量采集。没有 PIT/BUY/资格/自然预算/Stage/Vibe/调度器变更，也不自动关闭工单。

## 文件与复现

- `before/`、`after/`：完整目标文件；`runtime.patch`：仅运行源码 7 行增量。
- `tests/`：按内部相对路径复制到候选 app 的两个新测试文件。
- `receipt.json`、`MANIFEST.json`：身份、结果与交付逐文件 SHA；`logs/` 保存通过与失败。

从冻结源码包的 `materialize.py api NEW_APP` 重建后，把 R11 六个 `api/` 文件覆盖到新 app，再按下方 SHA 准入应用本补丁。安装和最小验证（在隔离候选 `apps/web`）：

```sh
npm ci --cache /tmp/v4-evidence-npm-cache --ignore-scripts --no-audit --no-fund
npx vitest run src/manager-selection/__tests__/researchEvidenceQuote.spec.ts
npx tsc --noEmit --strict --skipLibCheck --target ES2022 --module ESNext --moduleResolution Bundler --types node,vitest/globals src/manager-selection/researchAttention.ts src/manager-selection/__tests__/researchEvidenceQuote.spec.ts
```

新测试默认调用 `python3`，可通过 `V4_TEST_PYTHON` 指定原生 Python。完整回归命令与 exit code 见 receipt；硬编码 Mac fixture 的旧测试不能在缺文件时计通过。

## Mac 后续验收与回滚（本轮没有执行）

只让原 owner 在**新的隔离候选副本**操作，不直接修改活动 release、canonical 或服务。先核实际活动身份与目标文件 SHA；任何并行漂移都停下做新 diff，不用本 after 覆盖不同文件。尤其 canonical 已知 SHA 不同。

设置 `V4_PACKET` 为本交付目录绝对路径、`V4_CANDIDATE` 为新候选 app 根。每条命令成功后才执行下一条；`cmp` 即逐字 SHA 准入补充。

```sh
cmp "$V4_CANDIDATE/apps/web/src/manager-selection/researchAttention.ts" "$V4_PACKET/before/apps/web/src/manager-selection/researchAttention.ts"
git -C "$V4_CANDIDATE" apply --check "$V4_PACKET/runtime.patch"
git -C "$V4_CANDIDATE" apply "$V4_PACKET/runtime.patch"
cmp "$V4_CANDIDATE/apps/web/src/manager-selection/researchAttention.ts" "$V4_PACKET/after/apps/web/src/manager-selection/researchAttention.ts"
```

仅复制 `tests/` 下明确列出的两个新文件，若同名已存在先核 SHA、不要覆盖并行工作。原生 Python/Node 重跑新增 11 项、相关既有测试和 TS；Mac 的实际 owner fixture/真实页面后续由 owner 独立核对，仍不能据合成结果声明催化判断或系统恢复。本轮未请求服务切换。

候选回滚同样先要求完整 after 一致，反向只移除 7 行，不碰其他文件：

```sh
cmp "$V4_CANDIDATE/apps/web/src/manager-selection/researchAttention.ts" "$V4_PACKET/after/apps/web/src/manager-selection/researchAttention.ts"
git -C "$V4_CANDIDATE" apply --reverse --check "$V4_PACKET/runtime.patch"
git -C "$V4_CANDIDATE" apply --reverse "$V4_PACKET/runtime.patch"
cmp "$V4_CANDIDATE/apps/web/src/manager-selection/researchAttention.ts" "$V4_PACKET/before/apps/web/src/manager-selection/researchAttention.ts"
```

这是候选源码回滚，不是生产服务回滚。Draft PR 仅供复核；没有 merge、deploy 或 force push。
