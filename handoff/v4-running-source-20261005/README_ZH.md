# V4 当前运行源码与问题交接 · 2026-10-05

这是源码审查快照，不是修复、测试或部署。目标仓库仅私有 `lexi2016/v4`，新独立分支；保留原分支与本机脏工作树。远端基线 main commit `615d1ce5417ed65ca2c8b736435c5d4596b79b19`，canonical HEAD `55a5ba0b8aef8e83dfd04fdbabefb8d9baa1d054`。旧8851只作相同blob复用依据，不作为运行身份。

## 当前身份与分层

- canonical：`/Users/lexi/Desktop/学习/v4_app`，含未提交研发改动；本次仅改项目根AGENTS同步段，未改业务文件。
- API/经理：`manager-selection-r10-20261004-business-r1/app`，launchctl running PID72627；入口 `python -B -m apps.api.v35_api.run --host 127.0.0.1 --port 8873`。
- Stage：`V4_HK_STAGE_RECOVERY_20261003/issue23_runner_helper_r3/stage_r1_binding_candidate_r3/app`，主scheduler已登记，核对时 not running、runs=9；入口 `python -B ops/run_stage_center_nodes.py --config stage_center_tick_config.json`。注册、候选身份、实际自然运行分别裁决。

完整根目录与plist SHA见RUNTIME_IDENTITY.json。三层各文件SHA见MANIFEST.json及其分片；相同字节只存一份，由snapshot_path引用。不可整树把canonical覆盖API/Stage，也不可拿旧freeze当现役。

## 获取准确源码

从本仓库根执行：

```sh
python3 handoff/v4-running-source-20261005/materialize.py api /tmp/v4-review-api-new
python3 handoff/v4-running-source-20261005/materialize.py stage /tmp/v4-review-stage-new
python3 handoff/v4-running-source-20261005/materialize.py canonical /tmp/v4-review-canonical-new
```

脚本只允许新目录，按所选层的清单逐文件校验SHA并重建；不会启动应用。pyproject.toml、uv.lock、前端package/package-lock/tsconfig、API和Stage入口、模块与测试已纳入。配置仅提供config_examples的脱敏示例；不带实际state、行情、计划、账户、模型权重或外部数据。upstreams中仅纳入现存源码，包外运行依赖与数据仍须按原合同提供，缺口不能伪造。

启动仅作入口说明：先由云端读依赖清单、使用独立隔离数据和配置；不要运行采集器/节点调度或把API指向本机原state。本次不安装依赖、不运行业务测试、不启动服务。

## 已有成果与剩余边界

- R10研究选股已有独立源码/离线验收及原API/UI回执；回看结果与自然时段证据分开，本次没有重验。
- canonical单日目标公告补丁由原writer完成，原独立57项及局部行为PASS；公开phase2仍记未部署，不能把canonical新增能力当R10已上线。
- 旧公告日期/缓存、Issue22成功原因、A股与R7后续保留项按既有回执复用，不重新派工。
- 公告范围/目录穷尽仍partial；US快照session、完整材料与关系资格缺口保留。事后采集不证明历史PIT或自然选择；历史恢复后续产物不能和旧20-cell快照混成同一验收。
- 最新经理writer台账为completed；HK最新day25 scope仍有writer但没有当前生命周期终态，不能保证全项目无并行任务。本快照各源码SHA在收件后复核一致，不暂停或抢占原任务。

精简证据见evidence/。未上传原始价格/行情、CSV候选清单、长响应、333MB计划、认证/账户文件、venv/node_modules/dist。敏感扫描仅检出明确的负例URL凭证占位夹具，未检出真实令牌或私钥。

## 本轮规则修改与远端验收

项目AGENTS原文保留为前缀，备份与前后SHA见AGENTS_CHANGE_RECEIPT.json。仅追加每轮工作分支同步、测试/运行边界及remote读回要求；未改全局安全/权限/hooks，不授权merge/deploy或扩大数据上传。已启动会话是否自动加载新规则CANNOT_CONFIRM。

本轮新测试/API/UI/natural均NOT_RUN。push后固定commit及关键文件读回结果在本机REMOTE_VERIFICATION.json中记录；该文件是发布后的外部回执，不制造自引用commit。
