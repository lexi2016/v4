# V4 R9 / R1 → R2：资格原 reader 绑定与只读接入核验候选

**范围：1 个运行文件的最小增量，不是目标日资格供给已修复。**

本轮不改 R1 公告正文分类、US 关系判定、原资格 producer、Stage、A股、BUY、Vibe8910 或暂停的 daily 草稿。
没有执行 Mac、Luna 独立 reviewer、活动 API/UI、部署或真实资格抓取。没有新的真实资格 authority。
总目标状态：`CANNOT_CONFIRM_TARGET_RUNTIME_SUPPLY`。

## 本轮可采用的内容

- `runtime.patch`：只相对**本机已验 R1 app**修改 `v4/manager_research/connect_selection.py`。不是相对原 r9，也不是 9月29日旧 GitHub 交接基线。
- `before/api/` 与 `after/api/`：该文件完整字节。前像 `1d5a03958b36b3e430133dec4365ad56b9c244200d28eefdb2f96892ee8f3a0f`，后像 `b6c5300172f59b6979dbab15927036ff1ab3599a2adae2b4f0e5a1e4868a6248`。
- `tools/audit_connect_authority.py`：用原 SHA 固定 reader 和原 owner，只读最多两个显式数据根的目标日四件套；不完成缺链，不启动采集，不猜默认根。
- `tools/verify_delivery.py`、`tools/run_offline_tests.py`：只在隔离目录验文件与声明范围测试。
- `config/authority_binding_requirements.json`：未授权启用的接入条件；不是活动 binding。
- `OWNER_CLOSURE.md` / `LOCAL_ACCEPTANCE.md` / `UI_ACCEPTANCE_CONTRACT.md`：具体供给判别、Mac 命令、原 API/UI 逐股验收与回退。
- `evidence/input_feedback/`：收到的本机 R1 回执原字节；不能作为 R2 的独立通过回执。

`after/tools`、`after/tests`、`after/config` 是辅助文件的完整后像导出；执行入口在包根的 `tools/`。
`reference_only/` 仅是离线测试依赖，禁止覆盖或部署到任何实际 app。包不是完整 r9 工程。

## 实际验收层次

新声明范围作者测试：27 passed（Linux / Python 3.13.5）；包括两个真实工具 CLI 调用，但数据均为 synthetic，不是 Mac API。
本机 R1 原回执：47 项通过；candidate/base 各132通过6失败，失败集相同。这是复用收到的回执，不是本轮 Mac 复跑。
活动供给 owner、V4 根目标日 authority、R2 Mac独立复验、新 API/UI/部署：仍未确认。
