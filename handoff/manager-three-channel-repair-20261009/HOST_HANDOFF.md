# 给本机验收者：只在新建临时源码副本验证

本任务延续原 [LOCAL_ACCEPTANCE.md](reference/problem/package/LOCAL_ACCEPTANCE.md)：本机负责临时副本落地验证。下面不包含现役服务重启、配置变更、真实行情/公告采集、真实导入或业务状态写入命令。执行前须确认目标目录是新建的临时源码副本。

## 1. 先确认源码组合，不能推定现役已经接入 R3

需要一份**完整的 V4 源码临时副本**，其中前序 `ca01c4d0260fecf7aae3c89e96899f36901bf8f7` 的 R3 API/web 候选已按其清单正确组合，原公告 CLI 和 HK upstream 参考文件也与本包 before SHA 一致。应用的未修改依赖须由本机完整源码提供；本包只有变化文件和 16 份原测试辅助文件，不能单独启动服务。

`api_r3_candidate` 的 6 个路径属于源码组合，不是“这 6 个文件都已存在于现役 API/worker 目录”的证据。原公告 CLI 的来源角色为参考 owner 快照；先确认临时副本用的是该 owner。3 个保留的 Issue32 文件也要匹配。查看 [SOURCE_MAP.md](SOURCE_MAP.md) 和 source_manifest 的每条 before_origin。

不要将真实共享 state、真实 authority root 或现场业务产物复制到测试副本。下面的回归自己创建临时合成 fixture。若 before 校验失败，记录路径、期望/实际 SHA 并停在源码身份定位，不能用覆盖 before、忽略 reject 或修改 manifest 来“通过”。

## 2. 本地变量与只读校验

把下列绝对路径替换为本机实际路径。`V4_REVIEW_ROOT` 必须是已经准备好的新临时源码根。Python/Node/node_modules 指向本机已有测试环境；不用本包安装依赖。

```bash
set -eu
export PYTHONDONTWRITEBYTECODE=1
export V4_HANDOFF="/ABS/PATH/manager-three-channel-repair-20261009"
export V4_REVIEW_ROOT="/ABS/PATH/new-temporary-v4-source"
export V4_REVIEW_PYTHON="/ABS/PATH/test-env/bin/python"
export V4_REVIEW_NODE="/ABS/PATH/node"
export V4_REVIEW_NODE_MODULES="/ABS/PATH/existing-test-node_modules"

"$V4_REVIEW_PYTHON" "$V4_HANDOFF/tools/verify_delivery.py" --package "$V4_HANDOFF"
"$V4_REVIEW_PYTHON" "$V4_HANDOFF/tools/replay_delivery.py" --package "$V4_HANDOFF"

for v4_profile in api_r3_candidate web_r3_candidate test_delta; do
  "$V4_REVIEW_PYTHON" "$V4_HANDOFF/tools/verify_delivery.py" \
    --package "$V4_HANDOFF" --profile "$v4_profile" \
    --source-root "$V4_REVIEW_ROOT" --against before
done
```

第一项检查包内完整源码和补丁，不触碰应用；第二项仅用包中 before/after 在它自己新建的临时目录完成正反应用，结束后移除。第三项才检查指定临时源码副本的 preimage。记录原样输出和退出码。

包总文件另可核对：macOS 在包目录运行 `shasum -a 256 -c PACKAGE_SHA256SUMS`，Linux 可用 `sha256sum -c PACKAGE_SHA256SUMS`。ZIP 顶层 `REMOTE_READBACK.json` 是发布完成后的远端传输证明，不在 commit 内，避免自引用；包目录内部文件应与固定 commit 全部一致。

## 3. 只向临时副本应用三组 patch

```bash
for v4_profile in api_r3_candidate web_r3_candidate test_delta; do
  git -C "$V4_REVIEW_ROOT" apply --check "$V4_HANDOFF/patches/$v4_profile.patch"
  git -C "$V4_REVIEW_ROOT" apply "$V4_HANDOFF/patches/$v4_profile.patch"
done

for v4_profile in api_r3_candidate web_r3_candidate test_delta; do
  "$V4_REVIEW_PYTHON" "$V4_HANDOFF/tools/verify_delivery.py" \
    --package "$V4_HANDOFF" --profile "$v4_profile" \
    --source-root "$V4_REVIEW_ROOT" --against after
done
```

全量 after 可用于人工 diff，不要把 profile 中间目录一并覆盖到源码树。新增 5 个测试路径 before 必须不存在；1 个旧测试 before 必须精确匹配。

## 4. 补齐未变化的测试辅助文件

`test_source_manifest.json` 列出 16 份固定来源辅助文件。下面仅在目标临时副本中补充缺少的文件；现存字节不同时直接失败，不覆盖。先将 `V4_REVIEW_ROOT` 确认为无真实状态的新临时源码副本。

```bash
"$V4_REVIEW_PYTHON" - <<'PY'
import hashlib, json, os
from pathlib import Path
package = Path(os.environ['V4_HANDOFF']).resolve()
target = Path(os.environ['V4_REVIEW_ROOT']).resolve()
manifest = json.loads((package / 'test_source_manifest.json').read_text())
pending = []
for row in manifest['unchanged_support']:
    rel = Path(row['path'])
    if rel.is_absolute() or '..' in rel.parts:
        raise SystemExit('Invalid support path')
    src = package / row['archive_path']
    raw = src.read_bytes()
    if len(raw) != row['bytes'] or hashlib.sha256(raw).hexdigest() != row['sha256']:
        raise SystemExit(f'Support payload mismatch: {rel}')
    dst = target / rel
    if dst.is_symlink() or target not in dst.resolve().parents:
        raise SystemExit(f'Unsafe target: {rel}')
    if dst.exists() and dst.read_bytes() != raw:
        raise SystemExit(f'Existing support differs: {rel}')
    if not dst.exists():
        pending.append((dst, raw))
for dst, raw in pending:
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(raw)
print(f'Verified {len(manifest["unchanged_support"])}; added {len(pending)} support files in temporary source only')
PY
```

## 5. 执行三路定向测试与前端消费契约

```bash
"$V4_REVIEW_PYTHON" "$V4_HANDOFF/tools/run_scoped_tests.py" \
  --app-root "$V4_REVIEW_ROOT" \
  --junitxml "$V4_REVIEW_ROOT/three-channel-core-results.xml"

export V4_TEST_SOURCE_ROOT="$V4_REVIEW_ROOT"
export V4_TEST_PYTHON="$V4_REVIEW_PYTHON"

# 仅当新临时副本尚无 node_modules 时，引用已有测试依赖。
if [ ! -e "$V4_REVIEW_ROOT/apps/web/node_modules" ] && \
   [ ! -L "$V4_REVIEW_ROOT/apps/web/node_modules" ]; then
  ln -s "$V4_REVIEW_NODE_MODULES" "$V4_REVIEW_ROOT/apps/web/node_modules"
fi

(
cd "$V4_REVIEW_ROOT/apps/web"
"$V4_REVIEW_NODE" "$V4_REVIEW_NODE_MODULES/vitest/vitest.mjs" run \
  --config "$V4_HANDOFF/tools/vitest.config.mjs" \
  src/api/managerWorkspace.threeChannel.spec.ts \
  src/api/managerWorkspace.dailyAutomation.spec.ts
)
```

预期对应本次云端记录是 Python 43 pass、前端 25 pass；这不是对未运行的本机结果预签通过。保存实际命令、cwd、解释器/依赖版本、退出码和输出。出现不同结果，保留完整日志并核对来源，不能修改阈值或把 unknown 改为 0 来验收。

Python runner 复用范围受限的 namespace loader，调用真实业务函数但不验证完整应用 package initializer。若本机需要原生 import 层面的验收，须在同一隔离且依赖完整的副本中单独记录；云端完整原生 import、Mac 原生 suite 均为 `NOT_RUN`。前端是 Vitest/jsdom 及真实 Python DTO 合成消费检查，不是现役浏览器。

已知兼容失败不在核心 43 中：原 `test_missing_original_archive_is_not_empty_connect_selection` 期望 READY，基线和候选实际均为 PARTIAL。独立扩展检查保留该失败，详见 [TESTING.md](TESTING.md)，不要将其抹去后报告全绿。

## 6. 逐通道验收记录

| 通道 | 至少保存的证据 |
|---|---|
| 公告 | capture 原字节一致；Reader/Reviewer 缺失及相同身份拒绝；真实 import/readback/consumer 链；catalog/run/manifest/judgment 绑定；非原生字符串身份拒绝；跨通道保留公告 |
| 美股 | 原 owner 从合成既有材料得到合法 VALID_EMPTY；计划与 GET 消费精确 run/SHA；GET 不写状态；缺输入/异常/超时/busy 可见且计划继续；同 slot 幂等、下一准入 slot 可更新；未来日期/PREOPEN 保持原规则 |
| HK / 前端 | 缺 exact-date 的 index SHA/条目数/最新日/键存在性；坏证据与缺键不同；有效 exact-date + later index entry 正向计算；snapshot witness 一致；未知计数 null、前端接受且不伪装 READY |

历史 16:01 的 index 原件缺失，不能把当前 reader 读取称为历史重放。17:23 收盘后 StoreError 内因另列 `CANNOT_CONFIRM`。本轮只做合成回归，不向真实 authority root 补写 `20261008`，也不拿 695/Futu 替代 D1 主表。

## 7. 临时副本回滚与结束

补丁逆序回滚，只针对此临时副本；新增的原测试支持、JUnit 文件和测试依赖 symlink 不属于 patch，结束时随整个一次性副本清理，不去操作现役目录。

```bash
for v4_profile in test_delta web_r3_candidate api_r3_candidate; do
  git -C "$V4_REVIEW_ROOT" apply --reverse --check "$V4_HANDOFF/patches/$v4_profile.patch"
  git -C "$V4_REVIEW_ROOT" apply --reverse "$V4_HANDOFF/patches/$v4_profile.patch"
done

for v4_profile in api_r3_candidate web_r3_candidate test_delta; do
  "$V4_REVIEW_PYTHON" "$V4_HANDOFF/tools/verify_delivery.py" \
    --package "$V4_HANDOFF" --profile "$v4_profile" \
    --source-root "$V4_REVIEW_ROOT" --against before
done
```

本机返回实际文件身份、定向测试和限制即可。当前候选验证通过不赋予现役集成/部署、服务/调度变更或真实采集的执行权限；这些仍需相应任务和现场证据。本包未执行它们。
