# 给 Mac 接续执行者

请以本候选包和固定输入 `30ad7bb633f715f30c4e10eb67e9041de92cf036` 为依据，继续**只读身份盘点与隔离测试**。本包不授权部署、源池改写、原回执删除、旧槽重开或计划任务变更。

本次候选仅修 `stage_center/_runner_parts/hk_input_validation.py` 的末尾物理三件套/目录身份复核。canonical 和实际 Stage 的前像均为 `92e8fb2be06e6530c33f3cf2f5b44f29b0bcf7875e6a5902260f8be4c814f735`；共同后像为 `b20baa18d0ee9748971db835f6fb3dd9a0e1d66aabd8da8d450aee3a4a528a8e`。现场缺 provenance、旧行价格日期和真实资格 capture 的问题仍未解决。先读 README、独立 review 和 `acceptance/MAC_READONLY_ACCEPTANCE.md`。

## 顺序

1. 核对 `SOURCE_MANIFEST.json` 及解包文件；保留收到的原 ZIP 和其 SHA。确认两个具体 owner、配置、解释器、前像，以及当前是否已出现并行修改。不要把本包 whole source 切片覆盖任一现役源码树。
2. 使用实际 Stage 配置中的 V4 Python。冻结记录为 `~/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python`；系统 Python 3.9 不满足 `StrEnum`。记录实际 executable、版本、平台和 pytest 版本，不安装新依赖或改变现场解释器来掩盖问题。
3. 设置 `ISSUE28_BUNDLE` 为此交付根，执行 `harness/run_regressions.py --owner both --phase after --suite targeted`。它只使用隔离目录，预期两个 owner 各 15 PASS。保存 stdout 指向的 `RESULTS.json`、JUnit、日志和导入 SHA。可另跑 `--phase before` 复现每 owner 9 PASS / 6 FAIL，保留退出码 1。不要只报告总 PASS 次数。
4. 原交接 19 项测试保持原字节。其 actual 12 PASS / 7 FAIL 与 canonical 17 PASS / 2 FAIL 是已记录基线差异；复跑 `--suite original` 时原样报告，不改 fixture 或加豁免。新增测试里的完整合成 fixture 不代表真实源数据已恢复。
5. 按只读接续说明执行 `audit_runtime_identity.py`，本包 `input/` 为问题目录。工具只盘点冻结允许路径、配置和一个指定槽回执，始终保持 `runtime_recovery_status=CANNOT_CONFIRM`。检查通过不能证明进程已加载后像。
6. 单独盘点已有权威源：10/7 价格的原 artifact / manifest / receipt / run；9/30 Connect 资格的原 artifact / run / capture 及其可核验证据；当前 local pool 的物理三件套与 resolver whole-date owner。不要给当前 9/30 行改日期，不从 `source_sha256` 发明资格哈希，不用本地 manifest/receipt 替代上游身份。任何缺件逐项标 `CANNOT_CONFIRM`，仅提交脱敏身份和必要原始来源源码/合同。
7. 记录当前 Stage receipt、settled/attempt 状态及 API 只读投影的精确身份，保持原数据不变。当前 `SETTLED_PARTIAL` 不能靠替换校验器保证自动重跑。旧槽恢复必须形成独立具体方案；不要删除或重写回执、latest、attempt/rearm，不影响有效 A 股结果。

## Mac 回传记录

回传机器/解释器、实际源码根及前后 SHA、执行命令、输入清单、所有 PASS/FAIL/error/skip、原始日志和 JUnit SHA，以及独立 reviewer 身份。将以下状态分别报告：候选源码测试、完整当前 owner 依赖验证、源码集成、部署、API/UI、自然时段、旧槽恢复。未做的状态写 NOT_RUN。手动复跑或回看不能被记为 09:30–09:35 自然运行。

若要继续集成、部署或旧槽恢复，先形成可审查的具体文件清单、真实来源证据、发布/回滚及旧槽恢复方案，再依据用户届时的明确授权执行。本包没有可一键操作现场服务或数据的入口。
