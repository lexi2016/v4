# 离线使用、模块候选与回滚步骤

本页分开描述已验证的隔离操作和待现场确认的运行接线。不要执行历史 reference 的 switch；其旧现场 pins 故意保留，当前绑定不成立。

## 1. 离线复现测试

在本包根目录先核验全部字节及正反向补丁：

```bash
python3 tools/verify_delivery.py
```

使用 Python 3.14.6（至少满足输入 pyproject 的 >=3.14）及隔离 venv。下面以已安装的 uv 为例，输出目录由操作者选择，避免落入任何工作/数据/发布目录：

```bash
uv venv --python 3.14.6 /tmp/v4-issue30-review-env
uv pip install --python /tmp/v4-issue30-review-env/bin/python -r review/test-locked-requirements.txt
uv pip check --python /tmp/v4-issue30-review-env/bin/python
cd full-after
/tmp/v4-issue30-review-env/bin/python -m pytest -q -p no:cacheprovider
```

这个闭包提供可用的 20 个原有测试和本轮 86 个新增测试。它不含全部 V4 上游依赖，不作为一个可直接启动的服务 app。

重新生成候选/回滚证据时，在包根目录调用：

```bash
/tmp/v4-issue30-review-env/bin/python tools/generate_synthetic_evidence.py \
  --code-root full-after \
  --fixture-root /tmp/v4-issue30-new-fixtures \
  --evidence-root /tmp/v4-issue30-new-evidence
```

两个输出根必须尚不存在。生成器仅使用自身合成临时 plist，不能接收/操作 live plist。它会记录新运行的真实路径和 SHA；交付 evidence 是原始那次运行的证据，不能通过文本替换路径后继续声称其原 SHA 有效。

## 2. 真实 owner 契约的批准前提

`examples/api-business-module-owners.PROPOSED.json` 故意不可发布。不得把 status 改成 APPROVED 就当作审核完成。必须由当前源码/构建/运行证据确认模块及其全部消费者、state 兼容性和共享边界，并在独立审核中绑定契约实际 bytes SHA。

契约 schema 为 `v4.api_business_module_owners.v1`。每个模块必有 `module_id`、`source_owner`、精确 `paths`、精确 `routes`（method/path）、`depends_on` 和 `state_compatibility: UNCHANGED`。全局还必须有 `shared_paths`（精确 path/source_owner）和 `protected_external_roots`（已存在、无 alias 的绝对目录列表）。不支持 glob 或目录所有权，不支持未经审核的 state migration。

批准后的契约须位于 candidate app 之外，并由当前 active LaunchAgent 的 `V35_API_MODULE_OWNERSHIP_PATH` 和 `V35_API_MODULE_OWNERSHIP_SHA256` 固定。修改真实 plist 本身属于另行现场变更，不在本交付中执行。首次接线必须一并确认全部现用发布者使用同一个锁和校验链，不能留下并行旧入口绕过新规则。

## 3. 业务模块前向候选

既有 delta receipt 增加以下业务绑定，保留原 schema/base/entries：

```json
{
  "business_module": {
    "module_id": "approved-module-id",
    "owner_contract_sha256": "exact-approved-contract-sha256",
    "base_generation": 7,
    "operation": "forward"
  }
}
```

以上是字段说明，不是可执行审批或有效 SHA。base 必须来自届时完整 active identity，entries 必须含每个目标文件的 before/after SHA 和原有 unified diff proof；新增路径同时列入既有显式 untracked approval。调用现有入口：

```text
python -m ops.build_release_candidate
  --source-root <仅包含经审核 delta source 的独立目录>
  --candidate-root <全新、隔离、与 release-id 同名的目录>
  --api-plist <届时确认的 active api-only plist>
  --release-id <candidate 目录名>
  --api-module-id <已批准的 module_id>
  --api-integration-delta-receipt <届时精确 receipt>
  --formal-release-root <届时真实正式 release 根>
```

这是参数清单；实际值必须来自现场确认，不能使用历史参考脚本的旧 pins。构建只产生 inactive app/manifest/delta/staged plist/plan/build receipt；`launchctl_called=false` 必须保留。candidate-root 的父目录、显式 receipt 的父目录要事先存在且不与任何保留 release、数据根、LaunchAgents 或 source 重叠。

若 stale base/generation/manifest 被拒绝，重新读取当前 active，重新审核 before/diff proof，生成新 receipt，再构建。不要修改旧 receipt 的 base 字段来跳过审批，也不要继续提交旧 B。

最终 immutable staging 和真实 switch 必须复用届时核对的当前原生链：锁内重新核验完整 candidate、owner authority、active 前像；bootout 前和原子替换前再次校验；替换后检查 candidate identity/route/static/health；将构建、plan、真实服务动作和 readback 分别记账。当前这一步仍 CANNOT_CONFIRM。

## 4. 只回滚一个模块

保留原目标发布、父版本、完整中间链及各自 manifest/delta receipts。将下面 API 用于隔离或已批准的候选 preparation；它不会安装 plist 或调用 launchctl：

```python
from pathlib import Path
from ops.api_release_integration import prepare_module_rollback

prepared = prepare_module_rollback(
    active_api_plist_path=Path(active_plist_parameter),
    target_release_root=Path(target_release_parameter),
    expected_manifest_sha256=target_manifest_sha_parameter,
    output_root=Path(new_isolated_reverse_source_parameter),
)
```

这四个参数必须由调用者明确绑定。输出 `source_root`、`delta_receipt_path`、`module_id`、`include_untracked_paths`、当前 base 和 `rollback_of`。把它们传给同一个 `build_module_candidate`，role 固定 gateway，然后经同一真实 publisher 重新 CAS 提交新候选。不要调用旧整包 rollback，不回切 target 的父 plist。

若后续有同模块/依赖模块更新、目标非祖先、目标 bytes/mode 已改变、保留链缺失、契约变动或当前 base 过期，必须拒绝。源码 reverse delta 不撤销任何真实 state 写入，也不代表旧代码必然兼容现在的 state；后者需 owner 证明。

## 5. 撤销本轮源码改动

`reverse.patch` 用于撤销本轮交付的源代码变更，与上面的业务模块回滚不同。在独立副本完成前向两组补丁后，它会逐文件恢复 `before/`；`tools/verify_delivery.py` 已验证。生产环境如需撤销发布框架，必须另做当前代码/服务/候选兼容审核，不能把这个源码补丁当作 live rollback。
