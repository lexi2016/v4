# M05 R8：回复与ZIP实物不符

2026-10-11 03:26 UTC 冻结。**REQUEST_CHANGES，且可并行独立云做精确失败复现。** 不因作者自测薄阻止测试；本件问题是真实入口错误尚未进入ZIP，无法做成功正控，不能用monkeypatch修候选后称原件通过。

回复：https://chatgpt.com/c/6aca4eef-525c-83e8-abb9-d8423024bf90?messageId=7427255e-2244-423b-91da-7f0934e84242

ZIP实测 11491 B，SHA256 `61164b69960de0741dbaa157e4704cff431538a00eadf99550b0eaa934edfab2`；5唯一entry、CRC正常。路径 `/workspace/shared/m05_r5_root_canonical_review_20261011/r8_downloads/V5_M05_R8_STRICT_STORE_BINDING_CANDIDATE_20261011.zip`。

## 1. 最先修打包实物，别继续只写回复

回复声称改为 `_require_write_gate_context`、核 `_write_gate_context is write_gate_context` 并 import/isinstance 原 StoreGateContext，但包内 daily:99–102 实际仍是：

```
if not hasattr(write_gate_context, "control_dir"):
    raise ValueError("M05_WRITE_GATE_CONTEXT_TYPE_REQUIRED")
if not getattr(store, "require_write_gate_context", False):
    raise ValueError("M05_STORE_STRICT_GATE_REQUIRED")
```

全文没有私有两字段、StoreGateContext import/isinstance 或真实factory。daily SHA确为回复/manifest中的 `485950f042ee2e0b0c9e01a9fcdb686d355b7bdfcffffe2985012b85b1da7669`，不是下载旧包。R7→R8 daily 唯一差分在 root helper:41–49；gate片段完全没有变。

因此 R7已证明的真store接口错误原封不动：原 PreselectionPoolStore 只存 `_require_write_gate_context`，合法strict实例仍被错拒。要求作者修改真实after文件后，重新创建ZIP，再重新打开ZIP提取daily，与工作after逐字/hash核对并确认上述代码确实进入包。不得给原类添加假公有属性来通过。

## 2. 已修保留；补丁出现覆盖范围回退

逐lane/空串/default helpers/raw键/窄fatal等已修保留，本轮root helper额外收紧可认可。runtime/reverse各1029B，两者 `git apply --check` 对真实R7/R8目录均exit0，但**只包含daily**，遗漏本轮确实改变的测试。必须用准确R7前像自动生成包括tests/factory在内的全文件正反patch，并核apply后全集SHA、reverse恢复全集。

## 3. 仍非真实fixture；其中一例还会因错误前置而失败

tests 842B，SHA `347bfd706c79b46fed9f7c33b6fb0cf8e5ccf5905ec28921f7c273802a4f2cb1`，仍只有root/conflict/allowlist，没有daily/真实store装配。test_all_roots_required直接用 `/tmp/out`，未生成marker；正常干净环境先在shadow_root抛SHADOW_ROOT_NOT_INITIALIZED，达不到期望M05_OWNER_ROOT_BINDING_REQUIRED。改为TemporaryDirectory、真实marker、合法独立根，再针对单一无效字段断言具体错误。

生产factory、完整diagnostics/聚合冲突/同锁batch依旧未写，应标UNIMPLEMENTED/WAIT INTEGRATION，不能将未写称仅NOT_RUN。独立云可现在运行原SOURCE fixture及本件精确失败复现；成功daily正控必须先拿到包含真实修复的包，不能由测试方暗改产品补过去。

## 4. 独立云最小材料与入口

- 固定SOURCE ZIP `/workspace/shared/V5_M05_SOURCE_REVIEW_20261010.zip`，SHA `241f56dbff2bd91514eaa976239007ca53f73d48cfce20bf173fbfadfd6a4d27`。
- SOURCE已解包根 `/workspace/shared/v5-module05-source-20261010`；保持V5/src、contracts和vendor相对关系。
- R8 ZIP路径/SHA见上；仅在独立临时副本overlay两个Python文件，产品原件不修改。
- publisher合同路径：SOURCE下 `handoff/v4-running-source-20261005/canonical/ops/materialize_scheduled_preselection.py:478–531`。仅阅读合同/私有适配，不盲import缺闭包的旧V4 publisher。
- 原真实fixture路径：SOURCE下 `V5/tests/test_a_preselection.py` 的 make_lane:10、publish_frozen_hourly_fixture:77，以及原 `test_a_preselection*.py`。
- 运行owner可用已批准解释器，以临时副本 `PYTHONPATH=<副本>/V5/src` 执行 `python -B -m unittest discover -s <副本>/V5/tests -p test_a_preselection*.py -v`；原29+1通过不等于daily通过。
- 精确gate错误复现脚本另见 `/workspace/shared/M05_R8_STRICT_GATE_REPRO_20261011.py`，参数为独立临时副本绝对根；只加载真class、生成临时离线lane/marker/合成context，断言在writer前错误拒绝，**不生成生产permit，不做交易**。运行命令：`PYTHONPATH=<副本>/V5/src python -B /workspace/shared/M05_R8_STRICT_GATE_REPRO_20261011.py <副本>`。此探针预期验证一个BUG，不能计为产品PASS；脚本当前NOT_RUN。

本轮只读实物、AST、差分与patch check，未运行产品/fixture或apply。冻结后不改。
