# 复现与修复验收（命令仅提供，打包时未执行）

## 固定输入

- 经理：3d9541aca3e5d28e94109609940503cca239b9fe。
- 公告修订：e06d143e881c66c22053a5c594b9c0be21d5be34。
- 超跌：ebe5944ecfbec2f6a161793d7c11946dea063e57。
- decision文件SHA：37607c65e2d822298fe321f8c3278acaf0e33d56f3261fa48b098b6ef2e5a10f；逻辑SHA：e0094a54b123050c11870b8f1ed4a71bf768afd87ccb221605b135f846d468c8。
- reviewer原文件SHA：981f89ebbcee269701ad69e4c346944f9da37cfcb1693032ca11de65c3e4eb29。
- semantic原文件SHA：ec315a9470b92869dc5db928a29e52a7d83a67fd7b53925d65e36e83bcaaf8ba。

## 1. 跨日

在包根设定绝对测试fixture路径，然后切入经理源目录，使用独立CPython3.14.6环境：

```sh
V5_ANNOUNCEMENT_REVISION_TEST_BUNDLE="$PWD/sources/e06d/bundle"
export V5_ANNOUNCEMENT_REVISION_TEST_BUNDLE
cd sources/3d9541ac/V5
PYTHONPATH=src:tests python3.14 -B -m unittest test_daily_revision_chain -v
```

原失败依赖真实当前时钟晚于20261009，fixture本身固定旧目标；修复需覆盖当天、跨日、缺历史资格、输入变化及重复读回，而不是改成当天fixture来隐藏跨日错误。代码定位：vendor/manager_plan_baseline/v4/manager_research/workspace.py:462的auto历史分流、workspace_history.py:287的历史门禁；src/v5_shadow/manager_plan.py保存和读回分支；tests/test_daily_revision_chain.py:75断言。

43项原命令：

```sh
PYTHONPATH=src:tests python3.14 -B -m unittest test_us_mapping_scope test_run_ledger test_daily_dispatch test_daily_us_owner test_daily_owner_adapters test_daily_manager_assembly -v
```

验收：当前恢复身份清楚且非虚假CURRENT/历史可用；实际now不倒填；原owner新版本导入、经理保存与普通页面读回同run/SHA；旧计划字节不变。API/Chrome页面需真实接线后另验，单元PASS不能替代。

## 2. reviewer修订绑定

e06d/bundle/ops/run_v5_decision_revision.py的create_revision在任何新revision写入前验证reviewer.decision_revision。现文件缺失，无真实create trace，因为前置核对已发现缺字段，未制造失败目录。预期拒绝码REVISION_REVIEW_BINDING_INVALID属于源码推导，不冒称已执行异常。

由原独审补充的新字段须绑定：revision_id（新唯一值）、parent_product_sha256=e724d07b39e5b4fb3ccbb0b4536f4519b4badbfd3783cad7ee6506a7af242ad6、parent_owner_receipt_file_sha256=6b5907c556b35b4e4a2c8a9928889b33d314369de31a7c6a12058f352c0525d0、source_recovery_receipt_sha256=b7b37e5385cdb7f14edc711af3b9d4bfd708441ac1de290a24a2b086b0f37b0f、source_run_id=16cc60afcb089f11690430b05853114c。

原流程create→prepare→register-handoff→verify→import→readback详见sources/e06d/bundle/DECISION_REVISION.md。真实输入放原恢复root独立inputs；本包脱敏reviewer仅诊断参考，不可冒用原SHA导入。实际available_at用新导入时间，既有91门禁保留；文章392=2事件/0业绩/26观察/270不选/94未评估，发行人281=2/26/182/71。

## 3. marshal身份

来源与runtime证据见evidence/rebound，完整失败栈private-repair.traceback.txt。code-object-diagnostic是在展开属性后生成，不能覆盖marshal-versions-before-inspection的干净失败证据。docstring引用实验不修改函数、code或global，不代表产品修复已完成。补充说明称19属性，实际JSON列出18个命名属性；以JSON具体字段为准。

既有命令（在sources/ebe5944e/V5）：

```sh
PYTHONPATH=src:tests python3.14 -B -m unittest test_rebound_panel_repair test_rebound_raw_repair test_rebound_admission test_rebound_observation -v
```

原skip条件：V5_REBOUND_REPAIR_ORIGINAL_TESTS及V5_REBOUND_OBSERVATION_ORIGINAL_TESTS未设为1。需Mac具备原模型/locked依赖及独立私有资产后，显式启用对应原owner验收；不要仅去掉skip装饰器。打包未运行这些命令。

验收：正确冻结loader通过；持有/释放docstring引用不改变身份判断；替换函数、嵌套code、导入helper、globals、常量及native布局仍被拒绝；私有真实repair发布child并反读，原panel/pointer不变。保留scale1、价格/量单位与正式admission限制；禁止放开694批量或把数值满足两门等同正式准入。
