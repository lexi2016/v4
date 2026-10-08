# 离线复现说明

本说明用于复现候选的合成测试，不会证明活动 Mac runner、外部 collector、Vision 或 Drive 已运行。原始命令与逐次退出码保存在 `evidence/writer/`；独立探针与日志在 `evidence/reviewer/`。

## 组装隔离源码

检出包含本交付的 GitHub 提交后，在仓库根执行下面的 Python；当前工作目录应同时包含以下三个顶层目录。程序依次复制原快照、R1 和本候选到新的临时目录，并按 source manifest 校验 after 文件。不会覆盖当前业务运行树。

| 仓库根下的输入 | 本轮临时工作区中的对应目录 |
| --- | --- |
| `wechat-workflow-review/source` | `issue31/inputs/wechat-workflow-review/source` |
| `wechat-workflow-fix-r1/source` | `issue31/inputs/wechat-workflow-fix-r1/source` |
| `wechat-workflow-fix-issue31-r2/source` | `issue31/delivery/wechat-workflow-fix-issue31-r2/source` |

以下代码使用左列的仓库布局。若在本轮临时工作区复现，先按右列映射输入路径；`issue31/baseline` 已是原快照加 R1 的组合，`issue31/candidate` 是当前完整候选。

```python
from pathlib import Path
import hashlib
import json
import shutil
import tempfile

repo = Path.cwd()
delivery = repo / "wechat-workflow-fix-issue31-r2"
inputs = json.loads((delivery / "INPUT_FILES.json").read_text())
for entry in inputs:
    if "/source/" in entry["path"]:
        payload = (repo / entry["path"]).read_bytes()
        assert hashlib.sha256(payload).hexdigest() == entry["sha256"]
check_root = Path(tempfile.mkdtemp(prefix="wechat-issue31-check-"))
for relative in (
    "wechat-workflow-review/source",
    "wechat-workflow-fix-r1/source",
    "wechat-workflow-fix-issue31-r2/source",
):
    shutil.copytree(repo / relative, check_root, dirs_exist_ok=True)
manifest = json.loads((delivery / "SOURCE_MANIFEST.json").read_text())
for entry in manifest["files"]:
    payload = (check_root / entry["path"]).read_bytes()
    assert hashlib.sha256(payload).hexdigest() == entry["after"]["sha256"]
print(check_root)
```

将打印的临时路径赋给 `WX_ISSUE31_CHECK_ROOT`。使用已有合适的隔离 Python 环境；不要为测试升级当前业务环境。本轮 Linux 实际测试环境为 Python 3.12.14，pytest 9.1.1，pandas 2.2.3，pyarrow 25.0.1，Pillow 12.3.0。涉及既有 V4 API 的回归另使用 fastapi 0.143.0、httpx 0.28.1、starlette 1.7.0；该组合出现一个 Starlette 弃用 warning，不影响已记录测试结果。

## 运行与留证

从上述隔离目录运行两个直接受影响的文件：

```bash
python -m pytest -q \
  "$WX_ISSUE31_CHECK_ROOT/wechat/tests/test_wechat_article_fetch_recovery.py" \
  "$WX_ISSUE31_CHECK_ROOT/wechat/tests/test_prior_mentions_performance_appendix.py"
```

既有 R1 的关联回归是 `wechat/tests/test_chat_review_regressions.py`。其 v4_app 默认路径为同一隔离目录下的 `v4_app/`；如需要指定，使用 `WECHAT_REVIEW_V4_ROOT`，不要指向活动业务树。最终精确测试集合、测试数与 subtests 数应以执行日志为准，不能把不同轮次或重复收集的数量相加。

独立 Reviewer 探针默认参照其原审查布局：`issue31/candidate/` 与 `issue31/reviewer_evidence/` 为同级。需要重跑时，将已组装的隔离源码放在新的 `issue31/candidate/`，复制对应探针到 `issue31/reviewer_evidence/`，按日志中的命令运行。保留原探针 SHA；只调整所在目录，不通过改期望断言取得绿色结果。

测试会在临时目录生成合成 HTML、PNG、Parquet、receipt 和冻结包。交付保存源代码、探针和日志；这些临时测试运行产物无需当作真实文章或市场数据上传。

`evidence/root/PATCH_ROUNDTRIP.json` 是实际执行的补丁正反向验证：正向结果与完整隔离候选逐文件字节相同，反向结果与组合基线逐文件字节相同。该校验覆盖 LF/CRLF，不依赖仅归一化后文本相同。

实际 Mac 的验收入口、源文件 SHA、调用参数、checkpoint 协议和恢复后 Drive 交付要求见 `MAC_ACCEPTANCE_REQUIRED.md`。
