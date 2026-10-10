# M11固定来源

原总计划24c6d60d524f43fcf4209ec8b078ec02cb34417e：V5/docs/superpowers/plans/2026-10-09-v5-master-delivery.md，M11/P4。
迁移计划d1bf034640ca2e5957423de2745a98e159b69af2：V5/docs/superpowers/plans/2026-10-10-v5-migration-execution.md，M11。
代码固定f7cb731c384ee6890a87d16c19a5b5a621779477。下列完整文件已读取；Git blob是文件身份，不是部署/测试证明。

## Donor → 目标

- ops/run_intraday_research.py及domains/intraday_research.py → 拟新增V5/vendor/research_review_baseline相同相对路径，V5/src/v5_shadow/research_review_daily.py调用原capture_intraday/read_intraday_day；完整导入闭包由Chat补manifest，不能只拷两文件。
- ops/run_research_review_generation.py及domains/research_review_generation/assembly.py → 同M11私有baseline，调用原assemble_runtime/run_generation，保留exact-date lock及懒装配。
- domains/daily_research_review.py → 本模块只读日总结adapter，原V4_DAILY_REVIEW_ROOT只能作为合同参考，不令V5读取未核V4活动根。
- 原/API/v3/review相关字段与DailyResearchCommandView为共享consumer，单独接口请求，Chat不写共享路径。

拟新增research_review_daily.py在固定完整树不存在，未见独立V5接管证据；不能写成“已有服务”。原测试中的临时配置与transport不代表真实provider绑定可用。原state结构为state_root/intraday下inputs/artifacts/manifests/receipts/attempts，日总结state_root/reviews；新V5必须自有不重叠根。

## 已读文件

- [handoff/v4-running-source-20261005/canonical/ops/run_intraday_research.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/handoff/v4-running-source-20261005/canonical/ops/run_intraday_research.py)
  - Git blob SHA：cf83780ef2a67a3706aa16a66c54eca4677b96ab
- [handoff/v4-running-source-20261005/canonical/domains/intraday_research.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/handoff/v4-running-source-20261005/canonical/domains/intraday_research.py)
  - Git blob SHA：551dcbfb598ee4c2c07ff41740899be2e1ccc606
- [handoff/v4-running-source-20261005/canonical/ops/run_research_review_generation.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/handoff/v4-running-source-20261005/canonical/ops/run_research_review_generation.py)
  - Git blob SHA：6bbccf14a7f202c0b5df910743e7e3e3646f04f0
- [handoff/v4-running-source-20261005/canonical/domains/research_review_generation/assembly.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/handoff/v4-running-source-20261005/canonical/domains/research_review_generation/assembly.py)
  - Git blob SHA：31e34483ba7a5b025225c33bb3090b6a5b38c8d4
- [handoff/v4-running-source-20261005/canonical/domains/daily_research_review.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/handoff/v4-running-source-20261005/canonical/domains/daily_research_review.py)
  - Git blob SHA：1bcf1132e83e65f8e1b41aeb1b2767d864436761
- [handoff/v4-running-source-20261005/canonical/tests/test_v4_intraday_research.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/handoff/v4-running-source-20261005/canonical/tests/test_v4_intraday_research.py)
  - Git blob SHA：467b2df216c1a31a427494f6c0a026a8e3cbfa0c
- [handoff/v4-running-source-20261005/canonical/tests/test_research_review_generation.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/handoff/v4-running-source-20261005/canonical/tests/test_research_review_generation.py)
  - Git blob SHA：f640d83fdc9033f6b57431832956047709c41405
- [handoff/v4-running-source-20261005/canonical/tests/test_daily_research_review.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/handoff/v4-running-source-20261005/canonical/tests/test_daily_research_review.py)
  - Git blob SHA：3f2bab372318a2597ae4d8838414c1cb3994850d

原CLI要求date、slot（盘中）、config、config-sha256、source-manifest-sha256；日总结review-root必须等于配置state_root/reviews。配置含既有credential_db/profile定位是原owner接口事实，不授权Chat读取、复制或扩大秘密范围。当前活动owner、全闭包manifest、全部API挂载和真实任务状态仍由Mac核实。
