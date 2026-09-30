# R1 → R2 最小差异与身份

唯一运行路径：`v4/manager_research/connect_selection.py`。
前像为已验R1后像，不是原r9中的不存在状态。

| 身份 | SHA256 |
|---|---|
| before | `1d5a03958b36b3e430133dec4365ad56b9c244200d28eefdb2f96892ee8f3a0f` |
| after | `b6c5300172f59b6979dbab15927036ff1ab3599a2adae2b4f0e5a1e4868a6248` |
| 原r9 domains reader（未改） | `22ccd133851afa0fd7927ae7c40370ce1130ccd77055b0044e91d863ac1da8d9` |
| 附件Stage原owner规则（未改） | `f527db45d4ec3720845606dd38e76bf6e93e973063b43f1cadb44a8e12407e5c` |

改后27–46行：新增成对显式owner root/SHA接入和拒绝非法/不完整配置。既无root又无SHA时保留R1本release默认行为；没有新的默认数据根。
改后48–51行：只将既有reader已支持的两个参数传入；不调用producer，不注入cutoff作为clock，不修改source采集时间。
改后69–71行：保留原异常diagnostic（code/layer/kind/field/artifact_ref/source code SHA）。
75行后的 `_scope_error`、filter_cards、gate_workspace、evidence_view、selection_diagnostics 函数全部字节不变；资格date/role/codes/digest门槛不动。

工具、测试、配置条件是包级辅助材料；仅runtime.patch可应用到已验R1 app。
`tests.patch`和`tools.patch`只能应用到隔离的空辅助目录，以复原tests/tools/config，不能覆盖活动release。
