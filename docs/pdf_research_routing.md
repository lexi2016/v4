# PDF研究分流投影

`ops/build_pdf_research_routing.py`只消费已冻结分类台账、原分页来源、18样本选择和已验收首份展示组合，生成供V4既有资料看板下载/详情补充的JSON、CSV和Markdown。它不改分类builder、原件、OCR、模型或业务状态，不创建服务、计划任务或第二资料底板。

优先次序为：明确的质量/材料形式阻断→REVIEW；输入和独立内容验收绑定的展示组合→REUSE；本轮研究包具体问题及原页证据→DEEP_RESEARCH；原复用候选缺有效结果绑定→REVIEW；会议记录或五页以内资讯→LIGHT_EXTRACTION；其余→SAVE。五类互斥。SAVE表示保留可检索、相关性待任务触发，不表示低价值。READY不是语义验收，未知机构或日期本身不全局阻断；每条保留受限用途。长会议记录也仅分配事实卡任务，不宣称已摘录。

首份REUSE只指人工勘误与原模型报告组成、经独立review的展示结果；单独原模型报告保持`REPORT_CONTENT_FAIL`。严格相同正文只确证正文关系，不证明有效研究结果；相似转载/版本关系仍是候选，保留差异数字与所有原件。A/HK/US只继承原字段，不补股票代码、市场映射、日期、机构或推荐关系。

所有2209身份必须与冻结manifest集合相同且唯一；源码验证BUILD/artifact/manifest SHA以及样本输入绑定。模型授权仅投影原18中除已完成首份外的17个身份；分流脚本执行模型、OCR和下载调用均为0，路由本身不释放全量模型准入。

可选`--packages`文件格式为`{"packages":[{"package_id":"...","kind":"company|industry|event","question":"明确研究问题","documents":[{"document_id":"...","question_link":"此页如何为问题提供新增事实或观点分歧","evidence":{"page_number":1,"page_text_sha256":"...","excerpt":"原页连续短片段"}}]}]}`。问题由研究包owner按实际材料冻结；片段须逐字存在于SHA绑定原页，不允许凭标题把2209文档批量赋为深度研究。问题/原页绑定表示研究用途，未认证作者结论或PIT安全。

复现命令：

```sh
python3 ops/build_pdf_research_routing.py \
  --build-root "$accepted_build" \
  --selection18 "$selection18" \
  --first-handoff "$first_handoff" \
  --expected-build-sha "$frozen_build_sha" \
  --expected-manifest-sha "$frozen_manifest_sha" \
  --packages "$package_bindings" \
  --output "$routing_output"
python3 -m unittest discover -s tests -p test_pdf_research_routing.py -v
```

`routing.json`中`original_metadata`逐字段保留原台账，包括未知值、原路径、页SHA、分类状态与原有候选。`selection_evidence`证明材料形式的出处；`research_questions`才是深度问题出处。两者不混淆。`statistics.json`对账并记录旧路由变化；Markdown说明处置及验收边界。针对性测试验证2209集合/互斥、质量优先、未知不猜、候选不误复用、数字/来源保留、页证据和17个准入边界；不重跑旧分类测试、不估计全量语义准确率。Writer测试只供交接，独立Reviewer验收另留receipt。
