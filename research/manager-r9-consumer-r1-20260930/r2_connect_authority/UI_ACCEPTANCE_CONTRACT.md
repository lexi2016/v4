# 原工作台最小前端冻结与逐股验收

本轮未附实际r9前端源文件；反馈指出多余字段不hard-fail，但未明确展示selection_diagnostics、mirror_observed_at/time_basis，主文案仍为发布时间。
因此本包**无前端diff**。不能把GitHub另一快照组件当作活动前像。下一次前端freeze仅允许：实际经理工作台卡片/诊断组件、它引用的字段类型/schema，以及针对该字段显示的测试；具体路径必须从实际render/import链记录及逐个SHA冻结后填写，不猜文件名，不改全局状态或其他页面。

数据到页面的必验合同：

1. `selection_diagnostics.membership`：显示目标日、读回状态、资格源date/SHA、缺件或owner SHA拒因；缺资格显示“目标日港股通资格未确认”，不能显示“扫描全部港股通后无机会”。
2. 公告材料 `mirror_observed_at` / `display_time_iso` / `time_basis`：明确“东方财富镜像显示时间”；`available_at` / `retrieved_at`展示原取得时钟；`published_at=null`、`hkex_first_publication_verified=false`时显示“HKEX首次发布时间未知”，不能用镜像时间替代。
3. 资格source的`available_at`另标“本次原reader读回见证时间”，不能与公告网络取得时钟同义展示。
4. `selection_diagnostics.candidates` 每只显示代码、名称、目标日Connect资格及来源、选入原因、逐条原文引用、实际时间字段。US业务关系显示两侧原文和PIT、长期关系有效期与“非今日新催化”。
5. `selection_diagnostics.rejections`和`us_relation_audit`逐项显示真实拒因；保持raw US movers可查看，0映射不删除原上涨输入。
6. `membership.authority_diagnostic`由本次1文件增量保留原code/layer/field/ref/source SHA。展示原code，中文说明不能把MISSING说成“非港股通”。

验收证据：同一目标日/同一候选版本的原API完整响应SHA、实际工作台URL与选定日期、逐股页面与详情截图、可点击来源、控制台schema错误情况和独立Reviewer结论。不能用静态HTML、离线render、旧公告正文面板或HTTP200充当此证据。
