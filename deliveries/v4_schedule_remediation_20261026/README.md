# V4 调度整改源码胶囊 · 2026-10-26

这里只交付本轮必要源码差异和既有测试，**不是完整可运行项目**，也不代表全链路或自然时段已经完成。旧 worktree/repo 与现役代码基线不同，不能把这些目录整体覆盖到源码根。

- `api/`：最终 combined API R4；保留 router 与 task_status 的增量来源。
- `web/`：已验 R3 前端源文件及原测试；不含 dist。
- `graph/`：独立 graph 基线差异，以及必要的原 gate/完整 plan 操作源码与 identity/full_context 等测试。
- `daily/core/` 与 `daily/a_share/`：复盘日调度 wrapper、A 日线/池修复分别保留。
- `stage/a925/`：独立 PASS 的 A09:25 R2 九文件。
- `main/`：已审 A3+C6 组合中的六个 C 差异文件及当前有效测试；A clean 外部绑定不在本胶囊里伪装为自包含代码。

同名 `infrastructure/runtime_graph/service.py` 等文件在 API 和 graph 中属于不同基线，必须分别核对，不能互相替代。每项 before/after SHA、原基线、实际来源及 scoped PASS 收据路径/SHA 均在 `MANIFEST.json`；实际部署收据留在 case，没有上传。

原 case 测试/操作文件逐字保留，仍依赖原 scope、基线或测试上下文；没有为本次交付重写测试或制造可直接运行的整包。已知有问题的 `activate_graph_only.py` CLI 明确排除，保留完整 plan 的原做法和对应测试供审查，不在本交付执行。

胶囊复制阶段逐项校验 SHA，未改原 source、candidate、active 或 canonical dirty 树，也未重跑测试或业务。源码同步与实际部署分别记录；未来 A09:25 时效/full621仍待自然验证。

`COMMIT_PATHS.txt` 是交给主控的完整、逐项可提交路径清单。主控在 ownership 释放后按此清单做 Git 提交和远端读回。

当前交付边界：A-only 恢复后次日主池80行已实际/API核对；视频复盘仍被 selector metadata/PIT 合同阻断。运行图虽已完成本胶囊内的读写根与降频修复，但发现旧证据绑定和模板目录问题，用户已要求暂停自动采集，正在独立修复；本胶囊不代表运行图已恢复可用。
