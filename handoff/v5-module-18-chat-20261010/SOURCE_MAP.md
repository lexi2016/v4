# M18固定来源与目标映射
F=f7cb731c384ee6890a87d16c19a5b5a621779477。以下“已读”均为本包静态源码阅读，绝不表示当前Mac同字节或已测试。Git blob SHA用于取回核验，不代替候选交付必须提供的SHA256。固定链接可供Chat直接读取，不要求用户搬运Mac原始数据。

## 实际V5路径
- [V5/src/v5_shadow/manager_plan.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/src/v5_shadow/manager_plan.py)
  - Git blob: 5e05f82ec6d2d88f47e79d19e5caf433a0143f2c
  - 已读请求/隔离/存储/恢复/发布核心链。_request 93起；_plan_store_scope 261起；_assemble 292起；同run独立核454—464；观察附加490—539；run_manager_plan 575起、publish_workspace_read 597起。M18主目标，先保留既有实现。
- [V5/src/v5_shadow/manager_plan_io.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/src/v5_shadow/manager_plan_io.py)
  - Git blob: 52ae09344864c9b6a20b57a7fef8a23fb2c595fc
  - 已全文读。install_manager_boundary只容许计划私有写与US私有锁，read_only禁止计划写；Python guards不是OS沙箱，禁止放宽。
- [V5/src/v5_shadow/manager_plan_gate.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/src/v5_shadow/manager_plan_gate.py)
  - Git blob: 314cd6141c7266bad7d66653885a6a8dc8d74687
  - 已全文读；转调原mapping_plan_admission，不能借此跳过M15准入。
- [V5/src/v5_shadow/daily_manager_assembly.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/src/v5_shadow/daily_manager_assembly.py)
  - Git blob: 15163128f101a36b2cbdfe8a9b5b804b82265bd7
  - 已全文读。product_reference只取readback_verified引用；assemble_manager_request封存实际请求，US exact-run+head一致核验；共享日调度接线仅提交集成请求。
- [V5/src/v5_shadow/daily_owner_adapters.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/src/v5_shadow/daily_owner_adapters.py)
  - Git blob: 31f08e44addf677b0eb393a9c87819577234ffa0
  - 已全文读。run_manager_daily 42—76核同attempt，再auto读同产品；结尾仍BLOCKED三lane业务未验，不能换标签造通过。共享文件不得18Chat并改。
- [V5/vendor/manager_plan_baseline/v4/manager_research/workspace.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/vendor/manager_plan_baseline/v4/manager_research/workspace.py)
  - Git blob: 3ad63b1d6ec6b5a57d20ea2b0beb7d42e867ed71
  - 已读核心451—488、770—1006及函数索引。verified_plan_attempt按run读；_read_plan目前按latest读；refresh保存顺序及同run检查需要真实竞态负测。固定原owner，非V4整包替换入口。
- [V5/vendor/manager_plan_baseline/v4/manager_research/workspace_plan_autorun.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/vendor/manager_plan_baseline/v4/manager_research/workspace_plan_autorun.py)
  - Git blob: aeb0bdaa1a335aafe072c278a8059ceca5849b52
  - 已定位owner_plan_readback和preopen/morning窗口；实际V5日期/终态合同依赖，执行者需读完整目标函数后改。
- [V5/contracts/manager_plan_source_manifest.json](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/contracts/manager_plan_source_manifest.json)
  - Git blob: ed8abe0e2286fd3e830ff08d4b3adeb7f48a0ea8
  - 已读取descriptor。与manager_plan.PIN及每个vendor字节绑定。vendor改变必须同步明确新身份，不删pin。
- [V5/src/v5_shadow/module_api.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/src/v5_shadow/module_api.py)
  - Git blob: 3fdea5f256b2dc70df141a0e70dbbc1396abb859
  - 已核read_response与HTTP路由；do_POST 202=405 MODULE_READ_ONLY。共享只读服务；不声称refresh已通。
- [V5/src/v5_shadow/module_artifacts.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/src/v5_shadow/module_artifacts.py)
  - Git blob: acf2195fee3711f594982269f1e6ab81da40a905
  - 已读取并定位publish_generation/activate_generation/expected-generation逻辑；共享发布能力，复用且统一集成。
- [V5/src/v5_shadow/api_gateway.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/src/v5_shadow/api_gateway.py)
  - Git blob: c5677fb59a4847a24f16a12d5412fce293168fc0
  - 已核配置可选GET/POST与按method转发，实际绑定由配置决定。共享平台代码不由M18直接覆盖。
- [V5/ui/manager-workbench/source/apps/web/src/api/managerWorkspace.ts](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/ui/manager-workbench/source/apps/web/src/api/managerWorkspace.ts)
  - Git blob: ce4e697ea0c90cbf25df06b7eab505ce94192e06
  - 已核validateManagerWorkspace与1423—1503请求/响应链。普通GET传bindings，refresh签名当前没有bindings；动态mode检查须对照e0候选。共享UI，交统一集成。
- [V5/ui/manager-workbench/source/apps/web/src/manager-selection/dailyChannels.ts](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/ui/manager-workbench/source/apps/web/src/manager-selection/dailyChannels.ts)
  - Git blob: 5f7beb215c71c3c2235902431cc41c9b92ddb8cb
  - 已读并定位日期/同run校验及render；与实际DTO跨语言fixture配对，不放宽validator。
- [V5/ui/manager-workbench/source/apps/web/src/manager-selection/catalystObservationPanel.ts](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/ui/manager-workbench/source/apps/web/src/manager-selection/catalystObservationPanel.ts)
  - Git blob: d1eff24632f71df767742a79c23fa852c571e9c2
  - 已定位mount与加载控制源。先复用e0已交差异，执行者需按实际前像核详细调用。
- [V5/tests/test_manager_plan.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/tests/test_manager_plan.py)
  - Git blob: e2af8ff8c68fcd847f6524c23dc5653265067148
  - 已读测试名/固定源，含保存/同run篡改/普通auto HTTP只读；本轮未运行。
- [V5/tests/test_manager_current_recovery.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/tests/test_manager_current_recovery.py)
  - Git blob: 42d61b7afe8d1a1b0f62a3ac21264cc01e60f9db
  - 已读测试名/固定源，含跨日同run、旧字节保持、显式历史、exact journal、普通auto HTTP；本轮未运行。
- [V5/tests/test_daily_manager_assembly.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/tests/test_daily_manager_assembly.py)
  - Git blob: e36e90527b1014c6b71e9759c288943dda6f5ae5
  - 已读测试名/固定源，含sealed cutoff重用及stale US/observation剔除；本轮未运行。

## V4 donor与既有候选，只供逐函数对照
- 已核进行中：用户已交旧9cac0ff跨13→18任务给原Chat，正修manager same-run/latest及共享UI只读/date/cancel。该Chat继续拥有当前候选，优先收其完整固定交付；本包不授权另一个Chat平行重做。进行中候选尚无本包可记录的新代码commit，不猜SHA或把旧9cac0ff当最终修复提交。
- [V4静态审查包](https://github.com/lexi2016/v4/blob/d3578688995c7cf14edb3b771a36688e0558dc2f/handoff/v4-code-optimization-review-20261010/START_HERE.md)：DELIVERY_PIPELINE_REVIEW/SOURCE_INDEX记录A严格identity、FOUR exact reader及多候选差异。不能把其11条逻辑路径当V5必改清单。
- [A/UI10严格identity donor](https://github.com/lexi2016/v4/blob/8c8e35d9d53431c9082dec49f4976e363c275765/handoff/manager-live-ui-api-repair-20261010-r1/after/v4/manager_research/workspace_identity.py)：逻辑在完整已验证引用上局部去无关registry-wide指纹。F的manager_plan vendor没有同名文件（目录核验及该路径读取404），须映射workspace/原projection，不新增文件后整套覆盖。
- [FOUR donor](https://github.com/lexi2016/v4/blob/74478a0e62be215c8527ccc9a14b89b51042d014/handoff/manager-four-functional-gaps-20261009/package/code/r2_chat_patch_target/apps/api/v35_api/manager_research_router.py)：US owner prepare→exact run回读→当前时钟→plan。V5里US生产由M15/调度负责，M18接提交引用。不能把V4 router覆盖V5 module_api。
- [current_recovery前端候选](https://github.com/lexi2016/v4/blob/e0a6bc36f9563df6a4e0f37d4e16a59e14347227/handoff/v5-current-recovery-frontend-20261010/START_HERE.md)：本轮读了START_HERE，blob b03a8eb2f42a083ae096c1cec370e2f414eb53a5；3个TS与1测试，dailyChannels前像来源单独核，真实fixture缺失，未声称测试可独立通过。候选文件本身由统一集成读MANIFEST后逐份核。
- [两文件三修复候选](https://github.com/lexi2016/v4/blob/d659ff0dbcc00aa1944908cfc8b44443642ea171/handoff/selection-output-reuse-repair-20261010-r1/README.md)：公告base SHA/readback归M13，超跌Decimal归M14；M18不重复修改。其历史runner/current-live workspace_plan前像不同，不是一套可整搬的V5基线。

## 输入与产物边界
M13交公告exact target/publication binding、run/审核/导入/产品SHA与状态；M14交已准入正式screen引用或明确观察/阻断；M15交原daily run/artifact/receipt及实际session/关系可用时点。M18保存workspace_plans及workspace_plan_runs，随后显式发布普通响应generation。V5普通外部URL路径沿用/api/v4/manager/research/workspace并不代表回退V4；响应release与实际进程须验。

## 未核不猜
Mac当前HEAD、实际输出根、解释器、调度安装、HTTP refresh目标服务、浏览器bundle和当前端口均待落地检查。原计划明确04—17最终消费，但F并未全部绑定；不补造API/路径/自然执行结果。

