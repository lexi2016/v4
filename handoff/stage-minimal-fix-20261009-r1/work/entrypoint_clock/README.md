# 原节点入口：实际唤醒时钟条件修复

只有 10/5 同 owner 历史 helper 前像可用，本轮未附当前 Mac helper。actual Stage `node_entry.py` 与 canonical 的前像不同，因此给两组精确补丁；两边的 `deadline_supervision.py` 前像相同。完整前后 SHA、路径和回环核验见 `SOURCE_CHANGES.json` / `evidence/PATCH_ROUNDTRIP.json`。前像不匹配时，仅移植这两处最小语义差异并独立复核，不能用旧整文件覆盖现役源码。

## 两处修改

1. 原 `_bounded_wait_until` 在 0–5 秒窗口内 sleep 后返回计划 cutoff，可能抹掉实际唤醒延迟。现在在原 deadline checkpoint 后读取真实 `datetime.now(SHANGHAI)`，返回该时钟。等待上限、未等待分支和 deadline 调用顺序不变。
2. 原 `run_nodes` 只要等待过就固定标 NATURAL。现在对实际唤醒时间重新调用原 `_node_mode`。不调整原模式规则、不扩大 DUE、行情 cutoff 或延迟预算。

本轮实际 Stage 合同中，`STAGE_0940_0945` 的节点分钟是 09:45:00，runner cutoff 是 09:45:05。原 `_node_mode` 对节点分钟起点后至多 5 秒标 NATURAL；原 `evaluate_due` 仅与 cutoff 精确相等才 DUE。测试分别保留这两个时钟：09:45:05.250 按原规则是 RECOVERY / LATE_CATCHUP_REPLAY；它仍可能具有合法截止内行情，不能仅凭晚启动说无行情。若时钟退到 09:45:03，原模式是 NATURAL、due 为 NOT_DUE，这一差异也保留，不把模式当触发证明。

## 证据

真实合同定向测试：前像 16 FAIL / 12 PASS / 1 个仅检查后像的测试跳过；后像 29 PASS、0 FAIL/ERROR/SKIP。测试执行原两个 helper 函数体、原模式和原 scheduler due 函数，使用本轮 actual contracts；时钟、日历和 dispatcher 为显式受控边界，不采行情、不启动服务。先前合成 cutoff 测试日志保留为 `clock_generic_*`，不冒充最终实际合同测试。

在此目录执行 `python -m pytest -q tests` 可复跑。独立结论见 `../hk_entrypoint/clock_review/REVIEW.md`。产品补丁没有改 scheduler、算法、报价时间校验或已部署的 preselection scheduler/shared。该条件修复不会证明过去的 NATURAL 声明属实，也不会把未来 owner 回执升级成独立自然证明。
