#!/usr/bin/env python3
"""Serial, resumable PDF report batch using the accepted simple workflow.

This runner consumes a frozen local inventory manifest. It does not download
PDFs, run OCR itself, modify the announcement queue, or change model settings.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
import fcntl
import hashlib
from io import BytesIO
import json
import math
import os
from pathlib import Path
import re
import signal
import sys
import tempfile
import threading
import time
from typing import Any, Callable, Iterable, Mapping, Sequence

from infrastructure import local_document_model as local_model
from infrastructure import pdf_research
from infrastructure import pdf_research_tools
from infrastructure import pdf_text_preparation


R_ROOT = Path("/Users/lexi/Desktop/学习/agents调试/V4_PDF_SIMPLE_BATCH_20261018_R1")
DEFAULT_MANIFEST = R_ROOT / "inventory/batch-manifest.json"
EXPECTED_BATCH_MANIFEST_SHA256 = "e739287d70abaafe428dabe08fb1025308d195dd717053f8189fe5f84ace25c9"
USER_ACCEPTANCE_PATH = R_ROOT / "user-sample-acceptance.json"
USER_ACCEPTANCE_SHA256 = "7bb8bbefad181134e5409e010e6fd0d971a6fcf6b95762b78036f6d3e0da7a8a"
R1_STATE_ROOT = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v35.local/state/data/"
    "external_sources/zsxq_hourly/pdf_local/research/batches/simple-20261018-r1"
)
DEFAULT_STATE_ROOT = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v35.local/state/data/"
    "external_sources/zsxq_hourly/pdf_local/research/batches/simple-20261018-r3"
)
EXPECTED_RUNTIME_SHA256 = "e05af04aa712ee134354a8c0fa97812761cee7d1304b3914c87b6a8636b22a99"
EXPECTED_MODEL_SETTINGS_SHA256 = "7a98bb5d2b6687b808d72b8c7bb385a23c714e9753a067fab81407c4e9245b99"
CONTINUATION_PLAN_SCHEMA = "v4.pdf_research_simple_batch.continuation_plan.v1"
CONTINUATION_SOURCE_RUN_ID = "simple-20261018-r3"
CONTINUATION_CANDIDATE_SETTINGS_SHA256 = "0da2c9d1044a1d86ac0037f06859248568ba82a03f1a26a17699c64b12e9c7c7"
CONTINUATION_ALLOWED_SETTINGS_SHA256S = frozenset(
    {EXPECTED_MODEL_SETTINGS_SHA256, CONTINUATION_CANDIDATE_SETTINGS_SHA256}
)
CONTINUATION_EXCLUDED_PRIOR_STATUSES = frozenset(
    {
        "USER_ACCEPTED_REUSED_REPORT",
        "MODEL_GENERATED_TEXT_COMPLETE_SOURCE_REVIEW_PENDING",
        "MODEL_GENERATED_TEXT_PARTIAL_SOURCE_REVIEW_PENDING",
        "SOURCE_REPAIR_FAILED_NO_MODEL",
        "FAILED_DOCUMENT_ISOLATED",
    }
)
CONTINUATION_MAX_DOCUMENTS = 10
CONTINUATION_RECOVERY_ERROR_CODE = "prefill_memory_exceeded"
TOOL_CANARY_INVENTORY_PATH = Path(
    "/Users/lexi/Desktop/学习/agents调试/V4_PDF_TOOL_ENABLED_COMPLETION_20261019_R1/"
    "inventory/remaining-core-inventory.json"
)
TOOL_CANARY_INVENTORY_SHA256 = "58c94d2899e02a17df46e2e3c9ed9e65ad7aa5e19194e7046c849fbe929a7dad"
TOOL_CANARY_DOCUMENT_ID = "fc551b8057828fc161d7efc134701242b43e9b95177c62e4fb6f625ec93b789b"
TOOL_CANARY_PAGE_INPUT_PATH = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v35.local/state/data/"
    "external_sources/zsxq_hourly/pdf_local/research/batches/simple-20261018-r3/"
    "documents/fc551b8057828fc161d7efc134701242b43e9b95177c62e4fb6f625ec93b789b/page-input.json"
)
TOOL_CANARY_PAGE_INPUT_SHA256 = "2408358e4ae95ff5e31dc296f1f24722ccd60870a3836d75bf07107f2d22be2e"
TOOL_CANARY_PRIOR_RECEIPT_SHA256 = "91f51ed8aa50c14965baf609fb55096bba35e53a6073ac136dff6acef837f43a"
TOOL_CANARY_PRIOR_QUEUE_KEY = "f2c2ccebdb314fb1e7152f456957ac88831d73bd691b35c28a351e5b74e79625"
TOOL_CANARY_SOURCE_REVIEW_PATH = Path(
    "/Users/lexi/Desktop/学习/agents调试/V4_PDF_TOOL_ENABLED_COMPLETION_20261019_R1/"
    "writer/canary-source-review/visual-review.json"
)
TOOL_CANARY_SOURCE_REVIEW_SHA256 = "1fa9085efbf8826a74f93eef1dc14021ac6e34f87998636c8ee159236fae0beb"
TOOL_CANARY_SOURCE_REVIEW_IMAGE_SHA256 = "783551487b9de23a3ab2a3fc78186b137d3ba09e644123ec49d2263ce068bc72"
TOOL_CANARY_FAILURE_CODE = "CHAT_HTTP_STATUS:400"
TOOL_CANARY_PREMODEL_RETRY_STATE_ROOT = DEFAULT_STATE_ROOT.parent / "continuation-tool-canary-20261019-r2"
TOOL_CANARY_PREMODEL_RETRY_PLAN_SHA256 = "e3a10b3fd7b193c8fc8e9ddd220fa09982918dfadb40dbee8de733b1d2f7e5ac"
TOOL_CANARY_PREMODEL_RETRY_ARTIFACT_SHA256S = {
    "run-progress.json": "306378e46a5489d2bec938dd3f00e1791e47ea5685ccf995640ec36866be0cea",
    "documents/fc551b8057828fc161d7efc134701242b43e9b95177c62e4fb6f625ec93b789b/progress.json": "a2d5f98ed36baf894b8b26599574c616303ec1bfd82a3cff8e806e8bf5396d0d",
    "documents/fc551b8057828fc161d7efc134701242b43e9b95177c62e4fb6f625ec93b789b/receipt.json": "dea75baf0b9acb74af5cdb1daa176138b9fa489a1a199cdcb58fec0907b3ab7f",
    "documents/fc551b8057828fc161d7efc134701242b43e9b95177c62e4fb6f625ec93b789b/page-input.json": "2e86e6df1d0a38bd98bca00cd34906fbc41bc836b3dd9e1170b722b862c76882",
    "documents/fc551b8057828fc161d7efc134701242b43e9b95177c62e4fb6f625ec93b789b/derived-ocr/page-0001.failed.json": "5a5b1813191ac0b6823760e4cd7da1047c2a3c129ba9be9b200ee53999b5bcd2",
}
TOOL_CANARY_PREMODEL_RETRY_FAILURE_CODE = "PAGE_GEOMETRY_UNSUPPORTED:FileNotFoundError"
PPI_PARTIAL_RECOVERY_DOCUMENT_ID = "6892ef7be8071665aa96fdf125a4a1acac8367f3f7eb3a772e84fd121b9fd87b"
PPI_PARTIAL_RECOVERY_STATE_ROOT = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v35.local/state/data/external_sources/"
    "zsxq_hourly/pdf_local/research/batches/continuation-three-document-canary-20261019-r1"
)
PPI_PARTIAL_RECOVERY_CONTINUATION_ID = "three-document-canary-20261019-r1"
PPI_PARTIAL_RECOVERY_PLAN_SHA256 = "393665466e50d74effefdbd6ea8e2f0b187baa1f342f5ef73de7999380866888"
PPI_PARTIAL_RECOVERY_RUN_PROGRESS_SHA256 = "20c451ed88ce495b66f691ffbe77be39a3e50bfe754cd819cfbb85b708a455ef"
PPI_PARTIAL_RECOVERY_DOCUMENT_PROGRESS_SHA256 = "c74c7a87d397e304c8df980f4f0b192061c578ba2858e543895787f268bbf72c"
PPI_PARTIAL_RECOVERY_RECEIPT_SHA256 = "dec0ac530f63194956ce3e755d9e062d332abccf1b601966418238c438626634"
PPI_PARTIAL_RECOVERY_PAGE_INPUT_SHA256 = "7731789b3a3e4446e0c821496e0f29133e31964d7e65a85ef0dc16b58672493c"
PPI_PARTIAL_RECOVERY_QUEUE_SHA256 = "8e676cf4302b4c526cfe4e786f7c4a5e758986d1e30225754219563ed105ecc0"
PPI_PARTIAL_RECOVERY_SUCCESS_CHUNK_SHA256 = "fc4beee946bde7b7c1dd4ba05c5d8887eb775c0536bb3f405f075a6ba93b10d1"
PPI_PARTIAL_RECOVERY_SUCCESS_QUEUE_KEY = "6006f6aed35002f7faa2cce4e3fe1ce0dc5dc3d096f19d169e8bbe77e2d48df7"
PPI_PARTIAL_RECOVERY_SUCCESS_PAYLOAD_SHA256 = "03dcceaa4602cce144b8de33e4d21110184feb60ecb6404269b1660db58c6c7f"
PPI_PARTIAL_RECOVERY_SUCCESS_RESPONSE_SHA256 = "1c9d59b3d1ed40cbee0eff2993ea3c187a2d3f19e3169a4cd7efbbf1b71be255"
PPI_PARTIAL_RECOVERY_FAILED_CHUNK_SHA256 = "441034e2fc2b21d6b0c2c9fc0f9a89b0403b9eca4fa85116da36efc315acd2bc"
PPI_PARTIAL_RECOVERY_FAILED_QUEUE_KEY = "039fa67f32522085560d4c6032850a54d39612fdc2a1c6d12aae1925227428a1"
PPI_PARTIAL_RECOVERY_FAILED_PAYLOAD_SHA256 = "c53f76a16c1625e16d3512144ae1d93a32a46570b1f6e5887c91f01f23bd7d17"
PPI_PARTIAL_RECOVERY_FAILED_REQUEST_INPUT_SHA256 = "21bb68135a05e5ac99a49f3d356b698bb4cdf73ff0e7e12d16f786f358b8ec16"
PPI_PARTIAL_RECOVERY_FAILED_STREAM_RECEIPT_SHA256 = "3a6e309eefdd81f3529e4088a46429629ba46d235632ff3ac1e310be0c1f243b"
PPI_PARTIAL_RECOVERY_FAILED_RAW_SSE_SHA256 = "515b735665760f680650eb73950a68c5585544513d816229212627bddf90b3f2"
CONTINUATION_PRIOR_RUNNER_SHA256 = "de0e05f9e053eca557ab8d93ae35ba51cd7432b4509d77150188fb5d7077d979"
PPI_PARTIAL_RECOVERY_FAILED_PRIOR_ARTICLE_ID = (
    f"{PPI_PARTIAL_RECOVERY_DOCUMENT_ID}:chunk:000002:{PPI_PARTIAL_RECOVERY_FAILED_CHUNK_SHA256}"
)
PPI_PARTIAL_RECOVERY_SELECTION_FIELDS = {
    "schema": "v4.pdf_research_simple_batch.partial_chunk_recovery.v1",
    "state_root": str(PPI_PARTIAL_RECOVERY_STATE_ROOT),
    "continuation_id": PPI_PARTIAL_RECOVERY_CONTINUATION_ID,
    "continuation_plan_sha256": PPI_PARTIAL_RECOVERY_PLAN_SHA256,
    "run_progress_sha256": PPI_PARTIAL_RECOVERY_RUN_PROGRESS_SHA256,
    "document_progress_sha256": PPI_PARTIAL_RECOVERY_DOCUMENT_PROGRESS_SHA256,
    "document_receipt_sha256": PPI_PARTIAL_RECOVERY_RECEIPT_SHA256,
    "page_input_sha256": PPI_PARTIAL_RECOVERY_PAGE_INPUT_SHA256,
    "queue_state_sha256": PPI_PARTIAL_RECOVERY_QUEUE_SHA256,
    "success_chunk_index": 1,
    "success_chunk_sha256": PPI_PARTIAL_RECOVERY_SUCCESS_CHUNK_SHA256,
    "success_queue_idempotency_key": PPI_PARTIAL_RECOVERY_SUCCESS_QUEUE_KEY,
    "success_payload_sha256": PPI_PARTIAL_RECOVERY_SUCCESS_PAYLOAD_SHA256,
    "success_response_sha256": PPI_PARTIAL_RECOVERY_SUCCESS_RESPONSE_SHA256,
    "failed_chunk_index": 2,
    "failed_chunk_sha256": PPI_PARTIAL_RECOVERY_FAILED_CHUNK_SHA256,
    "failed_queue_idempotency_key": PPI_PARTIAL_RECOVERY_FAILED_QUEUE_KEY,
    "failed_payload_sha256": PPI_PARTIAL_RECOVERY_FAILED_PAYLOAD_SHA256,
    "failed_request_input_sha256": PPI_PARTIAL_RECOVERY_FAILED_REQUEST_INPUT_SHA256,
    "failed_stream_receipt_sha256": PPI_PARTIAL_RECOVERY_FAILED_STREAM_RECEIPT_SHA256,
    "failed_raw_sse_sha256": PPI_PARTIAL_RECOVERY_FAILED_RAW_SSE_SHA256,
    "failed_error_code": CONTINUATION_RECOVERY_ERROR_CODE,
}
TOOL_CANARY_INSTRUCTION = (
    "本次为单例工具验证：先用 search_pdf 定位‘四层板产品实现营收’及相邻总营收数据，再用 read 核对原文页码和上下文；"
    "按你从原文找到的两个数值调用 calculator 计算四层板营收占总营收的比例，并和原文比例核对。"
    "此外用 web_search（entity 为‘奥士康公司’，topic 为 official_results）查找官方财务结果，并从同次搜索结果选择官方 HTTPS URL 调用 fetch，"
    "只有 fetched body 本身含有可核对的相关财务内容时才在报告中引用；只返回首页或摘要时不得称为已核验。"
    "最终报告覆盖原文主要事实，将外部补充分开标注；搜索不可用或无合格正文时明确 CANNOT_CONFIRM，不猜测。"
)
S18_PDF_SHA256 = "3776a6641d50a8431d5be54bb4259e78e00b037fdc2c46e1264a19ea566f86c9"
S18_REPORT_SHA256 = "334051502c722688e6bdda26c3aec6a695e4a4f04e0eee1602d43da94ebb0299"
S18_REPORT_PATH = Path(
    "/Users/lexi/Desktop/学习/agents调试/V4_PDF_RESEARCH_V3_SAMPLE_20261018_R1/"
    "direct-demo/full-analysis.md"
)
FIRST_CONTENT_FAIL_PDF_SHA256 = "075d0083f99e6a4912086798fd0bf737c3807d6e14a365ab2f2d2dd14f4d883c"
SECOND_CONTENT_FAIL_PDF_SHA256 = "93930e8298dc18a9e2438d5c31420675d1b86e1d87f793139ca76db45f389ee9"
EXPECTED_CANARY_DOCUMENT_IDS = (
    S18_PDF_SHA256,
    FIRST_CONTENT_FAIL_PDF_SHA256,
    SECOND_CONTENT_FAIL_PDF_SHA256,
)
CANARY_DOCUMENT_LIMIT = 3
SOURCE_REJECTED_PDF_SHA256S = frozenset({FIRST_CONTENT_FAIL_PDF_SHA256, SECOND_CONTENT_FAIL_PDF_SHA256})
SOURCE_CANARY_ATTEMPT_PATH = R_ROOT / "writer/ocr-scale-canary/attempt.json"
SOURCE_CANARY_ATTEMPT_SHA256 = "c5c222520e38162103603e494a906be9a3ea7d48fa5953bae6b7d4619c6d3664"
SOURCE_CANARY_TEXT_SHA256 = "3098a17443a681086478856fa96192805d84d06120fb1afb5cc7cfad674434a6"
SOURCE_CANARY_SCOPE_SHA256 = "bfa21e0d18b4d7a5012403af269c8fc1cb6742e1ae58ef56705c3c56a41982ee"
SOURCE_CANARY_REVIEW_SHA256 = "48565633b8bd6abec4f4c40c799cb1170bec04200991d662b57c52914fa586e5"
SOURCE_CANARY_PRIOR_SUMMARY_PATH = R_ROOT / "writer/ocr-canary/summary.json"
SOURCE_CANARY_PRIOR_SUMMARY_SHA256 = "695a40ca6a43da38b4d1e20e6f9774d9529c0e31c03264030fff855eec66108a"
SOURCE_CANARY_REVIEW_DEFAULT = R_ROOT / "reviewer/ocr-scale-content-verdict.json"
REPORT_CANARY_REVIEW_DEFAULT = R_ROOT / "reviewer/r3-report-content-verdict.json"
EXPECTED_REPORT_CONTENT_FAIL_REVIEW_SHA256 = "a5bc45007985d4e868ab7febd29262c14b2deb570ad28861bdafe9edc5c02e49"
SLICE_CANARY_ATTEMPT_PATH = R_ROOT / "writer/slice-canary/attempt.json"
SLICE_CANARY_ATTEMPT_SHA256 = "5ba455f74357c0f17a3b0084ebe18109a2532c34d88a7ee718b6cc8d55e79774"
SLICE_CANARY_MANIFEST_PATH = R_ROOT / "writer/slice-canary/slice-manifest.json"
SLICE_CANARY_MANIFEST_SHA256 = "7080fc6b5e74db9e9361b776da3b402b0b8bb94e01f68f6da200da7fe01a3692"
SLICE_CANARY_TEXT_PATH = R_ROOT / "writer/slice-canary/ordered-text.txt"
SLICE_CANARY_TEXT_SHA256 = "31d5b7e5e8c55638307bbd4f0e514afdb437b6986860eea501b66aa289a34b3d"
SLICE_CANARY_SCOPE_SHA256 = "f12cacd0f00c67db6b1dea24347ca7b0fd4e5e7ce1d1c32d8141db2402b23534"
SLICE_CANARY_REVIEW_DEFAULT = R_ROOT / "reviewer/slice-source-content-verdict.json"
SLICE_CANARY_REVIEW_SHA256 = "6982589eb94cc268a62043e3136f1f96abc2c9b2f7c4c7ef3f379353ebc3b31b"
SLICE_SOURCE_REVIEW_SCOPE_SHA256 = "68849328bca22feffc9118cbd6f9494d49629e8fcb74d3bf7064f3666a053e8c"
V3_OCR_SCRIPTS_ROOT = Path("/Users/lexi/Desktop/学习/v3_system/选股池/微信公众号/scripts")
V3_PREPARE_OCR_PATH = V3_OCR_SCRIPTS_ROOT / "wechat_prepare_ocr.py"
V3_COMMON_PATH = V3_OCR_SCRIPTS_ROOT / "wechat_common.py"
EXPECTED_V3_PREPARE_OCR_SHA256 = "980c9004a1fa38862708ee325970ab8adfebbd66661cb42f0f8318436eebe606"
EXPECTED_V3_COMMON_SHA256 = "25934b26357060e3322dcf393816383558a166a5a969244a7e4f1e8de4582446"
EXPECTED_PDF_INGESTION_SHA256 = "8a16a457edbd6a7a95c3b3c7af5335d8243946b0e5f2b2f2eb48f5fc3e7c9f9b"
EXPECTED_VISION_SOURCE_SHA256 = "be7e039d778babd32918da2b7d9620a7b3b9e98e6e62625840eaad1b6d4d834d"
EXPECTED_VISION_CONFIG_SHA256 = "631e624bf348d42d2cb2d333e599e412cddd230593e0372663076e8865ba7814"
EXPECTED_RENDERER_SHA256 = "de772e88ab9977ccde25def9b403bf42675d75f5dd82b19fbd7d8123ad183159"
EXPECTED_RENDERER_VERSION = "26.05.0"
BASELINE_RENDER_SCALE_TO = 2_600
MAX_REPAIR_RENDER_SCALE_TO = 13_000
TARGET_RENDER_PIXELS_PER_POINT = MAX_REPAIR_RENDER_SCALE_TO / 5_001
LOW_RENDER_DENSITY_PIXELS_PER_POINT = 1.0
MAX_REPAIR_IMAGE_BYTES = 32 * 1024 * 1024
MAX_REPAIR_RENDER_SECONDS = 45
MAX_REPAIR_VISION_SECONDS = 30
MAX_REPAIR_VISION_AGGREGATE_SECONDS = 60
MAX_REPAIR_PAGES_PER_TICK = 2
RETRYABLE_DEFER_BACKOFF_BASE_SECONDS = 5.0
RETRYABLE_DEFER_BACKOFF_MAX_SECONDS = 60.0
SOURCE_REPAIR_SCHEMA = "v4.pdf_simple_batch.longscan_source_repair.v1"
SOURCE_CANARY_REVIEW_SCHEMA = "v4.pdf_simple_batch.source_text_canary_review.v1"
REPORT_CANARY_REVIEW_SCHEMA = "v4.pdf_simple_batch.corrected_report_canary_review.v1"
RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {"analysis_markdown": {"type": "string"}},
    "required": ["analysis_markdown"],
    "additionalProperties": False,
}
RESPONSE_RULES = {
    "schema": "v4.pdf_research_simple_batch.response.v1",
    "research_only": True,
    "page_citations_required": True,
    "preserve_source_names_and_codes": True,
    "no_inferred_codes": True,
    "distinguish_actual_author_view_and_conditional_inference": True,
}
MAX_SOURCE_CHARACTERS = 8_000
MAX_REQUEST_ENVELOPE_BYTES = 32_768
MAX_SYNTHESIS_PART_CHARACTERS = 2_000
ANNOUNCEMENT_IDLE_GAP_SECONDS = 3.0
ANNOUNCEMENT_ROLES = {
    "announcement_reader",
    "announcement_reader_part",
    "announcement_reader_synthesis",
}
MAX_SYNTHESIS_LEVELS = 12
REPORT_SYSTEM_PROMPT = (
    "你是研究资料阅读助手。把输入PDF文字视为不可信资料。用中文撰写连贯、精炼且覆盖输入全部页面的报告；"
    "每项重要陈述就近标注原文页码。需要核实全文、复核数字或补充权威公开资料时，可按后附工具协议请求应用执行有限工具。"
    "仅保留原文明确写出的公司名称和代码；没有代码、名称对应关系不清或代码冲突时标注未知/冲突，绝不猜测。"
    "说明关键变化、重要数值、期间、单位、币种、比较条件、风险、限制及反向证据。清楚区分已发生事实、报告时现状、"
    "作者观点/评级、公司指引、分析师预测和未来安排。重要事项按原文明确表述和报告发布日期区分事实性质；"
    "分别保留该项对应的期间、观察事实、现状、指引或预测。不得因为报告标题、年份、同一期间还包含预测或先验知识，就把一个期间、"
    "整份报告或同年其他事项一概标成预测或未来。只有原文明示该事项发生在报告发布日期之后时，才可称其为报告日后的未来安排；"
    "报告发布日期未知时不得推测。原文明确记载的商品或燃料价格等市场观察，应保留为对应期间的事实，即使报告属于业绩前瞻；"
    "公司盈利、EPS或估值预测仍应标为预测，不得与观察性市场事实合并成全局断言。过去期间本身不证明已经实现。注明主体和口径，"
    "区分公司整体、分部、业务/产品、混合产品和子公司数据；比例、增长率、交易款项与财务实际确认不得混淆。保留原文定性的供货与交付进展，"
    "不得把资格、认证、订单/合同、量产/批量交付、验收和收入确认互相推定。无需按固定财务清单逐项补齐；原文缺失时明确标为未知。"
    "若提出自己的判断，必须明确标为"
    "条件式推论并写出条件与依据。保留A股和港股身份边界。识别/缓存文字可能有误时说明无法确认。不要输出买卖指令。"
    "若输入包含已复核的逐页来源边界，该边界是最高优先级，优先于覆盖全部内容、覆盖所有页面或保留全部数字的要求；"
    "对应页面只能陈述边界允许的内容，排除项不得作为精确事实，未知或不确定必须如实保留。"
    "只输出符合给定JSON Schema的对象。"
)
SYNTHESIS_SYSTEM_PROMPT = (
    "你是研究报告编辑。只整合本次给出的分段分析，不添加外部事实，不猜公司代码，不消除来源冲突。"
    "写成覆盖完整文档的中文报告，保留各段的原文页码引用、重要数字、事实性质、风险、限制和反向证据；"
    "区分已发生事实、现状、作者观点、公司指引、预测、日程与条件式推论。合并时逐项保留每个数字或事项在原文明确给出的期间和事实性质，"
    "以原文措辞和报告发布日期为准，不跨事项传播预测或未来标签。报告标题、年份、同一期间其他项目的预测标签和先验知识，"
    "都不足以把该期间、整份报告或同年其他事项一概改标为预测或未来；只有原文明示事项发生在报告发布日期之后时，才可称为报告日后的未来安排。"
    "原文明确记载的商品或燃料价格等市场观察应保留为相应期间的事实，公司盈利、EPS或估值预测继续标为预测。来源信息不足或分段冲突时保留未知/冲突，不外推。"
    "遗漏信息写明未知。不要把推论说成事实，"
    "若输入包含已复核的逐页来源边界，该边界是最高优先级，优先于完整文档、覆盖所有页面或保留全部数字要求；"
    "不得恢复边界排除的信息。"
    "也不要给出买卖指令。只输出符合给定JSON Schema的对象。"
)



# This admission is deliberately bounded to the independently reviewed first18.
ANALYSIS_ROOT = Path("/Users/lexi/Desktop/学习/agents调试/V4_PDF_MODEL_ANALYSIS_20261020_R1")
ANALYSIS_SELECTION_PATH = ANALYSIS_ROOT / "execution-selection18.json"
ANALYSIS_REVIEW_PATH = ANALYSIS_ROOT / "canary-content-review.json"
ANALYSIS_SCHEMA = "v4.pdf_research.analysis_admission.v1"
ANALYSIS_BASE_SELECTION_SHA256 = "d63d5764228111a1231a39a5fd8b7d5df9c6dcecdbeda5ec5aa60419f6c8e6e7"
ANALYSIS_CLASSIFICATION_REVIEW_PATH = Path("/Users/lexi/Desktop/学习/agents调试/V4_PDF_CLASSIFICATION_SAMPLE_20261020_R1/independent-review/independent-review.json")
ANALYSIS_CLASSIFICATION_REVIEW_SHA256 = "fa4274868c8e0dd537af32eda9e52f7a0e2b5b9ce3a63b83c1508ad35a7e8bda"
ANALYSIS_RUNTIME_SHA256 = "2713eb73ceb66ee77fbfb58c52b17211305d72774b5e9412073171854ba3e631"
ANALYSIS_RUNTIME_RECEIPT_SHA256 = "c8a5b0dbfc2811cd567388997d60c68694384ad12a5e4b1ba90a16f9d933251f"
ANALYSIS_CANARY_ID = "0ba93abc16adbd4963b3ab96dfea6e63a62d343a9d950d1ad4376b2dbef2d818"
ANALYSIS_ISOLATED_ID = "e2d660f090a972a43ba68bba37eea0a5889c1c6bef1bb760a0334fd0c4da6813"

class BatchError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_bytes(value: Any, *, newline: bool = False) -> bytes:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return raw + (b"\n" if newline else b"")


def _within(path: Path, root: Path) -> bool:
    try:
        path.absolute().relative_to(root.absolute())
        return True
    except ValueError:
        return False


def _checked_output(path: Path, root: Path) -> Path:
    path = path.expanduser().absolute()
    root = root.expanduser().absolute()
    if not _within(path, root):
        raise BatchError("OUTPUT_OUTSIDE_BATCH_STATE_ROOT")
    cursor = root
    if cursor.is_symlink():
        raise BatchError("BATCH_STATE_ROOT_SYMLINK_FORBIDDEN")
    for part in path.relative_to(root).parts[:-1]:
        cursor = cursor / part
        if cursor.is_symlink():
            raise BatchError("BATCH_OUTPUT_PARENT_SYMLINK_FORBIDDEN")
    if path.is_symlink():
        raise BatchError("BATCH_OUTPUT_SYMLINK_FORBIDDEN")
    return path


def _write_immutable(path: Path, raw: bytes, root: Path) -> str:
    path = _checked_output(path, root)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.exists():
        existing = path.read_bytes()
        if existing != raw:
            raise BatchError("IMMUTABLE_ARTIFACT_CONFLICT")
        return _sha256(existing)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temp_path, path)
        except FileExistsError:
            if path.read_bytes() != raw:
                raise BatchError("IMMUTABLE_ARTIFACT_CONFLICT")
        return _sha256(raw)
    finally:
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass


def _write_state_json(path: Path, value: Mapping[str, Any], root: Path) -> str:
    path = _checked_output(path, root)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    raw = _json_bytes(dict(value), newline=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, path)
    finally:
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass
    return _sha256(raw)


@contextmanager
def _batch_singleton_lock(state_root: Path):
    root = state_root.expanduser().absolute()
    if root.is_symlink():
        raise BatchError("BATCH_STATE_ROOT_SYMLINK_FORBIDDEN")
    lock_path = _checked_output(root / "locks/batch-runner.lock", root)
    lock_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise BatchError("BATCH_ALREADY_RUNNING") from None
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


@contextmanager
def _cooperative_sigterm_handler() -> Any:
    if threading.current_thread() is not threading.main_thread():
        raise BatchError("GRACEFUL_STOP_REQUIRES_MAIN_THREAD")
    requested = threading.Event()
    previous = signal.getsignal(signal.SIGTERM)

    def request_stop(_signum: int, _frame: Any) -> None:
        requested.set()

    signal.signal(signal.SIGTERM, request_stop)
    try:
        yield requested
    finally:
        signal.signal(signal.SIGTERM, previous)


def load_manifest(path: Path) -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
    if path.is_symlink() or not path.is_file():
        raise BatchError("FROZEN_BATCH_MANIFEST_UNAVAILABLE")
    raw = path.read_bytes()
    if _sha256(raw) != EXPECTED_BATCH_MANIFEST_SHA256:
        raise BatchError("BATCH_MANIFEST_SHA_MISMATCH")
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        raise BatchError("BATCH_MANIFEST_JSON_INVALID") from None
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema") != "v4.pdf_research_simple_batch.manifest.v1"
        or manifest.get("status") not in (None, "FROZEN")
        or not isinstance(manifest.get("documents"), list)
    ):
        raise BatchError("BATCH_MANIFEST_CONTRACT_INVALID")
    documents = manifest["documents"]
    if not documents or any(not isinstance(doc, dict) for doc in documents):
        raise BatchError("BATCH_MANIFEST_DOCUMENTS_INVALID")
    seen: set[str] = set()
    for doc in documents:
        pdf_sha = doc.get("pdf_sha256")
        document_id = doc.get("document_id")
        if (
            not isinstance(pdf_sha, str)
            or not re.fullmatch(r"[0-9a-f]{64}", pdf_sha)
            or document_id != pdf_sha
            or pdf_sha in seen
            or type(doc.get("pdf_bytes")) is not int
            or doc["pdf_bytes"] < 1
            or not isinstance(doc.get("local_pdf_path"), str)
            or not isinstance(doc.get("source_paths"), list)
            or not isinstance(doc.get("cache_candidates"), list)
        ):
            raise BatchError("BATCH_MANIFEST_DOCUMENT_INVALID")
        seen.add(pdf_sha)
    return manifest, _sha256(raw), documents


def _continuation_path_is_safe(path: Path, root: Path, *, allow_missing: bool) -> bool:
    """Require a path below root with no symlink component, including the leaf."""
    path = path.expanduser().absolute()
    root = root.expanduser().absolute()
    try:
        relative = path.relative_to(root)
    except ValueError:
        return False
    cursor = root
    if cursor.is_symlink():
        return False
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            return False
        if not allow_missing and not cursor.exists():
            return False
    return True


def _continuation_prior_progress_path() -> Path:
    return DEFAULT_STATE_ROOT / "run-progress.json"


def _continuation_prior_queue_root() -> Path:
    return DEFAULT_STATE_ROOT / "queue"


def _load_prior_queue_jobs() -> dict[str, Any]:
    queue_root = _continuation_prior_queue_root().expanduser().absolute()
    state_path = queue_root / "queue-state.json"
    if not _continuation_path_is_safe(state_path, queue_root, allow_missing=False):
        raise BatchError("CONTINUATION_PRIOR_QUEUE_STATE_UNAVAILABLE")
    try:
        before = state_path.stat()
        raw = state_path.read_bytes()
        after = state_path.stat()
        if (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
            raise BatchError("CONTINUATION_PRIOR_QUEUE_STATE_CHANGED_DURING_READ")
        state = json.loads(raw.decode("utf-8"))
    except BatchError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise BatchError("CONTINUATION_PRIOR_QUEUE_STATE_INVALID") from None
    jobs = state.get("jobs") if isinstance(state, dict) else None
    if not isinstance(state, dict) or state.get("schema") != "v4.announcement-engine-queue/v1" or not isinstance(jobs, dict):
        raise BatchError("CONTINUATION_PRIOR_QUEUE_STATE_INVALID")
    return jobs


def _continuation_normalize_request_payload(value: Mapping[str, Any]) -> dict[str, Any]:
    """Remove only run-root/provenance fields when comparing a prior request."""
    normalized = json.loads(_json_bytes(dict(value)).decode("utf-8"))
    normalized.pop("evidence_root", None)
    normalized.pop("continuation", None)
    binding = normalized.get("model_binding")
    if isinstance(binding, dict):
        binding.pop("evidence_root", None)
    return normalized


def _same_request_payload_ignoring_run_root(
    prior: Mapping[str, Any],
    current: Mapping[str, Any],
    *,
    allow_frozen_runner_source_rebind: bool = False,
) -> bool:
    normalized_prior = _continuation_normalize_request_payload(prior)
    normalized_current = _continuation_normalize_request_payload(current)
    if normalized_prior == normalized_current:
        return True
    if not allow_frozen_runner_source_rebind:
        return False
    prior_binding = normalized_prior.get("model_binding")
    current_binding = normalized_current.get("model_binding")
    prior_sources = prior_binding.get("source_sha256") if isinstance(prior_binding, dict) else None
    current_sources = current_binding.get("source_sha256") if isinstance(current_binding, dict) else None
    source_path = "ops/run_pdf_research_batch.py"
    if (
        not isinstance(prior_sources, dict)
        or not isinstance(current_sources, dict)
        or prior_sources.get(source_path) != CONTINUATION_PRIOR_RUNNER_SHA256
        or current_sources.get(source_path) != _sha256_file(Path(__file__).resolve())
    ):
        return False
    prior_without_runner = json.loads(_json_bytes(normalized_prior).decode("utf-8"))
    current_without_runner = json.loads(_json_bytes(normalized_current).decode("utf-8"))
    prior_without_runner["model_binding"]["source_sha256"].pop(source_path, None)
    current_without_runner["model_binding"]["source_sha256"].pop(source_path, None)
    return prior_without_runner == current_without_runner


def _load_continuation_progress(path: Path, expected_sha256: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise BatchError("CONTINUATION_PRIOR_PROGRESS_UNAVAILABLE")
    try:
        raw = path.read_bytes()
    except OSError:
        raise BatchError("CONTINUATION_PRIOR_PROGRESS_UNAVAILABLE") from None
    if _sha256(raw) != expected_sha256:
        raise BatchError("CONTINUATION_PRIOR_PROGRESS_SHA_MISMATCH")
    try:
        progress = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        raise BatchError("CONTINUATION_PRIOR_PROGRESS_INVALID") from None
    if (
        not isinstance(progress, dict)
        or progress.get("status") != "STOPPED_GRACEFULLY"
        or progress.get("manifest_sha256") != EXPECTED_BATCH_MANIFEST_SHA256
        or not isinstance(progress.get("documents"), list)
    ):
        raise BatchError("CONTINUATION_PRIOR_PROGRESS_BINDING_MISMATCH")
    return progress


def _prior_progress_rows(progress: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for row in progress.get("documents", []):
        if not isinstance(row, dict) or not isinstance(row.get("document_id"), str):
            continue
        document_id = row["document_id"]
        if document_id in rows:
            raise BatchError("CONTINUATION_PRIOR_PROGRESS_DUPLICATE_DOCUMENT")
        rows[document_id] = row
    return rows


def _continuation_recovery_raw_has_exact_error(raw: bytes) -> bool:
    if not isinstance(raw, bytes) or not raw or len(raw) > 64 * 1024:
        return False
    try:
        envelope = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        return _continuation_recovery_sse_has_exact_error(raw)
    error = envelope.get("error") if isinstance(envelope, dict) else None
    return isinstance(error, dict) and error.get("code") == CONTINUATION_RECOVERY_ERROR_CODE


def _continuation_recovery_sse_has_exact_error(raw: bytes) -> bool:
    """Recognize only a terminal server error frame after empty stream metadata."""
    try:
        text = raw.decode("utf-8")
    except UnicodeError:
        return False
    if text.endswith("\r\n\r\n"):
        text = text.replace("\r\n", "\n")
    elif not text.endswith("\n\n"):
        return False
    if "\r" in text:
        return False

    frames: list[str] = []
    current: list[str] = []
    lines = text.split("\n")
    if lines[-2:] != ["", ""]:
        return False
    for line in lines[:-1]:
        if line == "":
            if current:
                if len(current) != 1 or not current[0].startswith("data:"):
                    return False
                payload = current[0][5:]
                frames.append(payload[1:] if payload.startswith(" ") else payload)
                current.clear()
            else:
                return False
        else:
            if not line.startswith("data:"):
                return False
            current.append(line)
    if current or not frames or frames[-1] != "[DONE]" or frames.count("[DONE]") != 1:
        return False

    payloads = frames[:-1]
    if not payloads or len(payloads) > 16:
        return False
    decoded: list[Mapping[str, Any]] = []
    for payload in payloads:
        try:
            frame = json.loads(payload)
        except json.JSONDecodeError:
            return False
        if not isinstance(frame, dict):
            return False
        decoded.append(frame)

    error_frame = decoded[-1]
    if (
        error_frame.keys() != {"type", "error"}
        or error_frame.get("type") != "error"
        or not isinstance(error_frame.get("error"), dict)
    ):
        return False
    error = error_frame["error"]
    estimate = error.get("estimated_bytes")
    limit = error.get("limit_bytes")
    if (
        error.get("code") != CONTINUATION_RECOVERY_ERROR_CODE
        or error.get("omlx_code") != CONTINUATION_RECOVERY_ERROR_CODE
        or error.get("type") != "invalid_request_error"
        or type(estimate) is not int
        or type(limit) is not int
        or estimate <= limit
        or limit < 1
    ):
        return False

    for frame in decoded[:-1]:
        if (
            not set(frame).issubset({"id", "object", "created", "model", "choices", "system_fingerprint"})
            or frame.get("object") != "chat.completion.chunk"
            or not isinstance(frame.get("choices"), list)
            or len(frame["choices"]) != 1
        ):
            return False
        choice = frame["choices"][0]
        if (
            not isinstance(choice, dict)
            or not set(choice).issubset({"index", "delta", "finish_reason"})
            or choice.get("index") != 0
            or choice.get("finish_reason") is not None
            or not isinstance(choice.get("delta"), dict)
            or not set(choice["delta"]).issubset({"role", "content"})
            or choice["delta"].get("role", "assistant") != "assistant"
            or choice["delta"].get("content", "") != ""
        ):
            return False
    return True


def _continuation_recovery_request_settings_confirmed(
    stream_receipt: Mapping[str, Any],
    *,
    expected_model_settings_sha256: str,
) -> bool:
    """Require the pre-POST receipt to bind both settings files to the request."""
    rows = stream_receipt.get("request_settings_bindings")
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        return False
    event = rows[0]
    if (
        event.get("status") != "MATCH"
        or event.get("matches_expected") is not True
        or event.get("source") != "local_disk_read_immediately_before_http_post"
    ):
        return False
    bindings = event.get("bindings")
    if not isinstance(bindings, list) or len(bindings) != 2:
        return False
    expected = {
        "runtime_settings": EXPECTED_RUNTIME_SHA256,
        "model_settings": expected_model_settings_sha256,
    }
    observed: dict[str, str] = {}
    for binding in bindings:
        if not isinstance(binding, dict):
            return False
        name = binding.get("setting_name")
        expected_sha = binding.get("expected_sha256")
        observed_sha = binding.get("observed_sha256")
        if (
            name not in expected
            or name in observed
            or expected_sha != expected[name]
            or observed_sha != expected[name]
            or binding.get("matches_expected") is not True
            or binding.get("status") != "MATCH"
            or binding.get("source") != "local_disk_read_immediately_before_http_post"
        ):
            return False
        observed[name] = observed_sha
    return set(observed) == set(expected)


def _validate_recovery_selection(
    entry: Mapping[str, Any],
    document: Mapping[str, Any],
    *,
    expected_model_settings_sha256: str,
) -> dict[str, Any]:
    recovery = entry.get("recovery")
    artifact_hashes = recovery.get("prior_artifact_sha256") if isinstance(recovery, dict) else None
    if (
        not isinstance(recovery, dict)
        or set(recovery)
        != {
            "generation",
            "prior_document_receipt_sha256",
            "prior_queue_idempotency_key",
            "prior_payload_sha256",
            "prior_article_id",
            "prior_source_sha256",
            "prior_raw_sha256",
            "prior_state_root",
            "prior_artifact_sha256",
        }
        or type(recovery.get("generation")) is not int
        or recovery.get("generation") != 1
    ):
        raise BatchError("CONTINUATION_RECOVERY_GENERATION_INVALID")
    if entry.get("prior_status") != "FAILED_NO_RETRY":
        raise BatchError("CONTINUATION_RECOVERY_PRIOR_STATUS_INVALID")
    if recovery.get("prior_source_sha256") != document.get("pdf_sha256"):
        raise BatchError("CONTINUATION_RECOVERY_SOURCE_OR_STATUS_MISMATCH")
    for key in (
        "prior_document_receipt_sha256",
        "prior_queue_idempotency_key",
        "prior_payload_sha256",
        "prior_raw_sha256",
    ):
        if not isinstance(recovery.get(key), str) or not re.fullmatch(r"[0-9a-f]{64}", recovery[key]):
            raise BatchError("CONTINUATION_RECOVERY_HASH_INVALID")
    article_id = recovery.get("prior_article_id")
    if not isinstance(article_id, str) or not article_id.strip() or len(article_id) > 512:
        raise BatchError("CONTINUATION_RECOVERY_IDENTITY_INVALID")

    document_id = str(document["document_id"])
    key = recovery["prior_queue_idempotency_key"]
    if not isinstance(recovery.get("prior_state_root"), str):
        raise BatchError("CONTINUATION_RECOVERY_STATE_ROOT_INVALID")
    batches_root = DEFAULT_STATE_ROOT.expanduser().absolute().parent
    prior_state_root = Path(recovery["prior_state_root"]).expanduser().absolute()
    if (
        prior_state_root.parent != batches_root
        or not re.fullmatch(r"(?:simple|continuation)-[a-z0-9][a-z0-9-]{0,95}", prior_state_root.name)
        or prior_state_root.is_symlink()
        or not prior_state_root.is_dir()
    ):
        raise BatchError("CONTINUATION_RECOVERY_STATE_ROOT_UNAPPROVED")

    expected_artifact_paths = {
        "continuation-plan.json",
        "run-progress.json",
        f"documents/{document_id}/progress.json",
        f"documents/{document_id}/receipt.json",
        f"documents/{document_id}/page-input.json",
        "queue/queue-state.json",
        f"queue/jobs/{key}/input.json",
        f"evidence/streams/{key}/attempt-0001/stream-receipt.json",
        f"evidence/streams/{key}/attempt-0001/round-01.request-input.json",
        f"evidence/streams/{key}/attempt-0001/round-01.raw.sse",
    }
    if not isinstance(artifact_hashes, dict) or set(artifact_hashes) != expected_artifact_paths:
        raise BatchError("CONTINUATION_RECOVERY_ARTIFACT_SET_INVALID")
    artifact_raw: dict[str, bytes] = {}
    for relative, expected_sha in artifact_hashes.items():
        if not isinstance(expected_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_sha):
            raise BatchError("CONTINUATION_RECOVERY_ARTIFACT_HASH_INVALID")
        path = prior_state_root / relative
        if not _continuation_path_is_safe(path, prior_state_root, allow_missing=False):
            raise BatchError("CONTINUATION_RECOVERY_ARTIFACT_UNSAFE")
        raw = _read_regular(path, "CONTINUATION_RECOVERY_ARTIFACT_UNAVAILABLE")
        if _sha256(raw) != expected_sha:
            raise BatchError("CONTINUATION_RECOVERY_ARTIFACT_SHA_MISMATCH")
        artifact_raw[relative] = raw

    receipt_relative = f"documents/{document_id}/receipt.json"
    progress_relative = f"documents/{document_id}/progress.json"
    page_input_relative = f"documents/{document_id}/page-input.json"
    input_relative = f"queue/jobs/{key}/input.json"
    stream_relative = f"evidence/streams/{key}/attempt-0001/stream-receipt.json"
    request_relative = f"evidence/streams/{key}/attempt-0001/round-01.request-input.json"
    raw_relative = f"evidence/streams/{key}/attempt-0001/round-01.raw.sse"
    try:
        prior_plan = json.loads(artifact_raw["continuation-plan.json"].decode("utf-8"))
        run_progress = json.loads(artifact_raw["run-progress.json"].decode("utf-8"))
        document_progress = json.loads(artifact_raw[progress_relative].decode("utf-8"))
        receipt = json.loads(artifact_raw[receipt_relative].decode("utf-8"))
        page_input = json.loads(artifact_raw[page_input_relative].decode("utf-8"))
        queue_state = json.loads(artifact_raw["queue/queue-state.json"].decode("utf-8"))
        old_payload = json.loads(artifact_raw[input_relative].decode("utf-8"))
        stream_receipt = json.loads(artifact_raw[stream_relative].decode("utf-8"))
        request_input = json.loads(artifact_raw[request_relative].decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        raise BatchError("CONTINUATION_RECOVERY_ARTIFACT_INVALID") from None

    plan_sha = artifact_hashes["continuation-plan.json"]
    if (
        not isinstance(prior_plan, dict)
        or prior_plan.get("schema") != CONTINUATION_PLAN_SCHEMA
        or prior_plan.get("source_run_id") != CONTINUATION_SOURCE_RUN_ID
        or prior_plan.get("manifest_sha256") != EXPECTED_BATCH_MANIFEST_SHA256
        or prior_plan.get("state_root") != str(prior_state_root)
        or prior_plan.get("runtime_settings_sha256") != EXPECTED_RUNTIME_SHA256
        or prior_plan.get("expected_model_settings_sha256") != expected_model_settings_sha256
        or not isinstance(prior_plan.get("selected_documents"), list)
        or not any(
            isinstance(row, dict)
            and row.get("document_id") == document_id
            and row.get("source_sha256") == document_id
            for row in prior_plan["selected_documents"]
        )
    ):
        raise BatchError("CONTINUATION_RECOVERY_PRIOR_PLAN_BINDING_MISMATCH")
    if (
        not isinstance(run_progress, dict)
        or run_progress.get("schema") != "v4.pdf_research_simple_batch.run_receipt.v1"
        or run_progress.get("status") != "COMPLETED_WITH_PER_DOCUMENT_STATES"
        or run_progress.get("continuation_id") != prior_plan.get("continuation_id")
        or run_progress.get("continuation_plan_sha256") != plan_sha
        or run_progress.get("manifest_sha256") != EXPECTED_BATCH_MANIFEST_SHA256
        or run_progress.get("queue_root") != str(prior_state_root / "queue")
        or not isinstance(run_progress.get("documents"), list)
    ):
        raise BatchError("CONTINUATION_RECOVERY_PRIOR_RUN_PROGRESS_MISMATCH")
    run_rows = [
        row for row in run_progress["documents"]
        if isinstance(row, dict) and row.get("document_id") == document_id
    ]
    if len(run_rows) != 1 or run_rows[0].get("status") != "FAILED_NO_RETRY":
        raise BatchError("CONTINUATION_RECOVERY_PRIOR_RUN_DOCUMENT_MISMATCH")
    if (
        not isinstance(document_progress, dict)
        or document_progress.get("document_id") != document_id
        or document_progress.get("pdf_sha256") != document_id
        or document_progress.get("manifest_sha256") != EXPECTED_BATCH_MANIFEST_SHA256
        or document_progress.get("status") != "FAILED_NO_RETRY"
        or type(document_progress.get("model_requests")) is not int
        or document_progress["model_requests"] < 1
        or type(document_progress.get("chunk_total")) is not int
        or document_progress["chunk_total"] < 1
        or not isinstance(document_progress.get("chunk_states"), dict)
        or not isinstance(page_input, dict)
        or page_input.get("schema") != "v4.pdf_research_simple_batch.page_input.v1"
        or page_input.get("manifest_sha256") != EXPECTED_BATCH_MANIFEST_SHA256
        or page_input.get("document_id") != document_id
        or page_input.get("pdf_sha256") != document_id
        or document_progress.get("page_input_sha256") != artifact_hashes[page_input_relative]
    ):
        raise BatchError("CONTINUATION_RECOVERY_PRIOR_DOCUMENT_PROGRESS_MISMATCH")
    if (
        not isinstance(receipt, dict)
        or receipt.get("schema") != "v4.pdf_research_simple_batch.document_receipt.v1"
        or receipt.get("status") != "FAILED_NO_RETRY"
        or receipt.get("manifest_sha256") != EXPECTED_BATCH_MANIFEST_SHA256
        or receipt.get("document_id") != document_id
        or receipt.get("pdf_sha256") != document_id
        or receipt.get("report") is not None
        or not isinstance(receipt.get("page_input"), dict)
        or receipt["page_input"].get("sha256") != artifact_hashes[page_input_relative]
    ):
        raise BatchError("CONTINUATION_RECOVERY_RECEIPT_BINDING_MISMATCH")

    prior_item_ref: dict[str, Any] | None = None
    failed_rows = 0
    for collection in ("chunks", "synthesis"):
        rows = receipt.get(collection, [])
        if not isinstance(rows, list):
            continue
        for row in rows:
            queue_item = row.get("queue_item") if isinstance(row, dict) else None
            if isinstance(row, dict) and row.get("status") == "FAILED_NO_RETRY":
                failed_rows += 1
                if isinstance(queue_item, dict) and queue_item.get("idempotency_key") == key:
                    prior_item_ref = queue_item
    if prior_item_ref is None or failed_rows != 1:
        raise BatchError("CONTINUATION_RECOVERY_QUEUE_RECEIPT_MISMATCH")

    queue_state = queue_state if isinstance(queue_state, dict) else {}
    jobs = queue_state.get("jobs")
    item = jobs.get(key) if isinstance(jobs, dict) else None
    if (
        queue_state.get("schema") != "v4.announcement-engine-queue/v1"
        or not isinstance(item, dict)
        or item.get("idempotency_key") != key
        or item.get("status") != "FAILED"
        or item.get("queue_id") != "v4-pdf-simple-batch"
        or item.get("model_id") != local_model.MODEL_ID
        or item.get("attempt_count") != 1
        or item.get("max_attempts") != 1
        or item.get("queue_policy") != {"max_attempts": 1, "max_body_bytes": None}
        or item.get("payload_sha256") != recovery["prior_payload_sha256"]
        or item.get("input_path") != f"jobs/{key}/input.json"
        or item.get("raw_path") is not None
        or item.get("raw_sha256") is not None
        or not isinstance(item.get("attempts"), list)
        or len(item["attempts"]) != 1
    ):
        raise BatchError("CONTINUATION_RECOVERY_QUEUE_IDENTITY_MISMATCH")
    attempt = item["attempts"][0]
    if (
        not isinstance(attempt, dict)
        or attempt.get("number") != 1
        or attempt.get("status") != "FAILED"
        or attempt.get("raw_path") is not None
        or attempt.get("raw_sha256") is not None
    ):
        raise BatchError("CONTINUATION_RECOVERY_ERROR_CODE_MISMATCH")
    if (
        not isinstance(old_payload, dict)
        or old_payload.get("article_id") != article_id
        or old_payload.get("source_sha256") != document_id
        or old_payload.get("source_document_id") != document_id
        or not isinstance(old_payload.get("model_binding"), dict)
        or old_payload["model_binding"].get("model_settings_sha256") != expected_model_settings_sha256
        or old_payload["model_binding"].get("runtime_settings_sha256") != EXPECTED_RUNTIME_SHA256
        or not isinstance(old_payload.get("source_text_sha256"), str)
        or not isinstance(old_payload.get("pdf_tool_binding"), dict)
        or old_payload["pdf_tool_binding"].get("page_input_sha256") != artifact_hashes[page_input_relative]
        or not isinstance(item.get("identity"), dict)
        or item["identity"].get("date") != old_payload.get("date")
        or item["identity"].get("market") != old_payload.get("market")
        or item["identity"].get("article_id") != article_id
        or item["identity"].get("model_id") != old_payload.get("model_id")
        or _sha256(local_model.canonical_json(item["identity"])) != key
    ):
        raise BatchError("CONTINUATION_RECOVERY_INPUT_BINDING_MISMATCH")
    expected_stream_settings = expected_model_settings_sha256
    rounds = stream_receipt.get("rounds") if isinstance(stream_receipt, dict) else None
    if (
        not isinstance(stream_receipt, dict)
        or stream_receipt.get("status") != "FAILED"
        or stream_receipt.get("idempotency_key") != key
        or stream_receipt.get("model_id") != local_model.MODEL_ID
        or stream_receipt.get("model_settings_sha256") != expected_stream_settings
        or stream_receipt.get("runtime_settings_sha256") != EXPECTED_RUNTIME_SHA256
        or not isinstance(rounds, list)
        or len(rounds) != 1
        or not isinstance(rounds[0], dict)
        or rounds[0].get("status") != "FAILED"
        or rounds[0].get("request_input_sha256") != artifact_hashes[request_relative]
        or rounds[0].get("raw_sse_sha256") != artifact_hashes[raw_relative]
        or _sha256(artifact_raw[raw_relative]) != recovery["prior_raw_sha256"]
        or not _continuation_recovery_raw_has_exact_error(artifact_raw[raw_relative])
    ):
        raise BatchError("CONTINUATION_RECOVERY_RAW_EVIDENCE_MISMATCH")
    if not _continuation_recovery_request_settings_confirmed(
        stream_receipt,
        expected_model_settings_sha256=expected_model_settings_sha256,
    ):
        raise BatchError("CONTINUATION_RECOVERY_REQUEST_SETTINGS_UNCONFIRMED")
    if (
        not isinstance(request_input, dict)
        or request_input.get("model") != local_model.MODEL_ID
        or request_input.get("temperature") != 0.0
        or request_input.get("stream") is not True
        or type(request_input.get("max_tokens")) is not int
        or request_input["max_tokens"] < 1
        or not isinstance(request_input.get("messages"), list)
        or not request_input["messages"]
    ):
        raise BatchError("CONTINUATION_RECOVERY_REQUEST_INPUT_INVALID")
    return {
        "prior_payload": old_payload,
        "prior_queue_root": prior_state_root / "queue",
        "prior_model_settings_sha256": expected_model_settings_sha256,
        "prior_page_input_sha256": artifact_hashes[page_input_relative],
    }


def _validate_ppi_partial_chunk_recovery(
    entry: Mapping[str, Any],
    document: Mapping[str, Any],
) -> dict[str, Any]:
    """Bind the one authorized PPI chunk-2 recovery to the exact three-doc run.

    Chunk 1 is immutable successful work and must be revalidated before any new
    queue enqueue. The old failed job did not retain a queue response body, so
    its exact stream receipt and SSE are the evidence for the server-side
    prefill rejection.
    """
    document_id = str(document.get("document_id", ""))
    partial = entry.get("partial_chunk_recovery")
    if (
        document_id != PPI_PARTIAL_RECOVERY_DOCUMENT_ID
        or document.get("pdf_sha256") != PPI_PARTIAL_RECOVERY_DOCUMENT_ID
        or entry.get("prior_status") != "FAILED_NO_RETRY"
        or entry.get("source_sha256") != PPI_PARTIAL_RECOVERY_DOCUMENT_ID
        or set(entry) != {
            "document_id",
            "prior_status",
            "source_sha256",
            "recovery",
            "partial_chunk_recovery",
        }
        or partial != PPI_PARTIAL_RECOVERY_SELECTION_FIELDS
    ):
        raise BatchError("PPI_PARTIAL_RECOVERY_SELECTION_BINDING_INVALID")

    recovery = entry.get("recovery")
    expected_recovery = {
        "generation": 1,
        "prior_document_receipt_sha256": PPI_PARTIAL_RECOVERY_RECEIPT_SHA256,
        "prior_queue_idempotency_key": PPI_PARTIAL_RECOVERY_FAILED_QUEUE_KEY,
        "prior_payload_sha256": PPI_PARTIAL_RECOVERY_FAILED_PAYLOAD_SHA256,
        "prior_article_id": PPI_PARTIAL_RECOVERY_FAILED_PRIOR_ARTICLE_ID,
        "prior_source_sha256": PPI_PARTIAL_RECOVERY_DOCUMENT_ID,
        "prior_raw_sha256": PPI_PARTIAL_RECOVERY_FAILED_RAW_SSE_SHA256,
    }
    if recovery != expected_recovery:
        raise BatchError("PPI_PARTIAL_RECOVERY_REQUEST_BINDING_INVALID")

    prior_root = PPI_PARTIAL_RECOVERY_STATE_ROOT.expanduser().absolute()
    if prior_root.is_symlink() or not prior_root.is_dir():
        raise BatchError("PPI_PARTIAL_RECOVERY_ROOT_UNAVAILABLE")

    expected_files = {
        "continuation-plan.json": PPI_PARTIAL_RECOVERY_PLAN_SHA256,
        "run-progress.json": PPI_PARTIAL_RECOVERY_RUN_PROGRESS_SHA256,
        f"documents/{document_id}/progress.json": PPI_PARTIAL_RECOVERY_DOCUMENT_PROGRESS_SHA256,
        f"documents/{document_id}/receipt.json": PPI_PARTIAL_RECOVERY_RECEIPT_SHA256,
        f"documents/{document_id}/page-input.json": PPI_PARTIAL_RECOVERY_PAGE_INPUT_SHA256,
        "queue/queue-state.json": PPI_PARTIAL_RECOVERY_QUEUE_SHA256,
        f"evidence/streams/{PPI_PARTIAL_RECOVERY_FAILED_QUEUE_KEY}/attempt-0001/stream-receipt.json": PPI_PARTIAL_RECOVERY_FAILED_STREAM_RECEIPT_SHA256,
        f"evidence/streams/{PPI_PARTIAL_RECOVERY_FAILED_QUEUE_KEY}/attempt-0001/round-01.raw.sse": PPI_PARTIAL_RECOVERY_FAILED_RAW_SSE_SHA256,
        f"evidence/streams/{PPI_PARTIAL_RECOVERY_FAILED_QUEUE_KEY}/attempt-0001/round-01.request-input.json": PPI_PARTIAL_RECOVERY_FAILED_REQUEST_INPUT_SHA256,
    }
    artifact_raw: dict[str, bytes] = {}
    for relative, expected_sha in expected_files.items():
        path = prior_root / relative
        if not _continuation_path_is_safe(path, prior_root, allow_missing=False):
            raise BatchError("PPI_PARTIAL_RECOVERY_ARTIFACT_UNSAFE")
        raw = _read_regular(path, "PPI_PARTIAL_RECOVERY_ARTIFACT_UNAVAILABLE")
        if _sha256(raw) != expected_sha:
            raise BatchError("PPI_PARTIAL_RECOVERY_ARTIFACT_SHA_MISMATCH")
        artifact_raw[relative] = raw

    try:
        prior_plan = json.loads(artifact_raw["continuation-plan.json"].decode("utf-8"))
        run_progress = json.loads(artifact_raw["run-progress.json"].decode("utf-8"))
        document_progress = json.loads(artifact_raw[f"documents/{document_id}/progress.json"].decode("utf-8"))
        receipt = json.loads(artifact_raw[f"documents/{document_id}/receipt.json"].decode("utf-8"))
        page_input = json.loads(artifact_raw[f"documents/{document_id}/page-input.json"].decode("utf-8"))
        queue_state = json.loads(artifact_raw["queue/queue-state.json"].decode("utf-8"))
        stream_receipt = json.loads(
            artifact_raw[
                f"evidence/streams/{PPI_PARTIAL_RECOVERY_FAILED_QUEUE_KEY}/attempt-0001/stream-receipt.json"
            ].decode("utf-8")
        )
        failed_input = json.loads(
            artifact_raw[
                f"evidence/streams/{PPI_PARTIAL_RECOVERY_FAILED_QUEUE_KEY}/attempt-0001/round-01.request-input.json"
            ].decode("utf-8")
        )
    except (UnicodeError, json.JSONDecodeError):
        raise BatchError("PPI_PARTIAL_RECOVERY_ARTIFACT_INVALID") from None

    prior_rows = prior_plan.get("selected_documents") if isinstance(prior_plan, dict) else None
    prior_row = next(
        (
            row for row in prior_rows or []
            if isinstance(row, dict) and row.get("document_id") == document_id
        ),
        None,
    ) if isinstance(prior_rows, list) else None
    progress_rows = run_progress.get("documents") if isinstance(run_progress, dict) else None
    progress_row = next(
        (
            row for row in progress_rows or []
            if isinstance(row, dict) and row.get("document_id") == document_id
        ),
        None,
    ) if isinstance(progress_rows, list) else None
    if (
        not isinstance(prior_plan, dict)
        or prior_plan.get("continuation_id") != PPI_PARTIAL_RECOVERY_CONTINUATION_ID
        or prior_plan.get("manifest_sha256") != EXPECTED_BATCH_MANIFEST_SHA256
        or prior_plan.get("state_root") != str(prior_root)
        or not isinstance(prior_row, dict)
        or prior_row.get("prior_status") != "UNPROCESSED"
        or prior_row.get("source_sha256") != document_id
        or not isinstance(run_progress, dict)
        or run_progress.get("status") != "COMPLETED_WITH_PER_DOCUMENT_STATES"
        or run_progress.get("continuation_id") != PPI_PARTIAL_RECOVERY_CONTINUATION_ID
        or run_progress.get("continuation_plan_sha256") != PPI_PARTIAL_RECOVERY_PLAN_SHA256
        or run_progress.get("manifest_sha256") != EXPECTED_BATCH_MANIFEST_SHA256
        or not isinstance(progress_rows, list)
        or len(progress_rows) != 3
        or not isinstance(progress_row, dict)
        or progress_row.get("status") != "FAILED_NO_RETRY"
        or not isinstance(document_progress, dict)
        or document_progress.get("document_id") != document_id
        or document_progress.get("manifest_sha256") != EXPECTED_BATCH_MANIFEST_SHA256
        or document_progress.get("status") != "FAILED_NO_RETRY"
        or document_progress.get("model_requests") != 2
        or document_progress.get("chunk_total") != 2
        or document_progress.get("chunk_states") != {"1": "SUCCEEDED", "2": "FAILED_NO_RETRY"}
        or document_progress.get("page_input_sha256") != PPI_PARTIAL_RECOVERY_PAGE_INPUT_SHA256
        or not isinstance(receipt, dict)
        or receipt.get("schema") != "v4.pdf_research_simple_batch.document_receipt.v1"
        or receipt.get("status") != "FAILED_NO_RETRY"
        or receipt.get("document_id") != document_id
        or receipt.get("pdf_sha256") != document_id
        or receipt.get("manifest_sha256") != EXPECTED_BATCH_MANIFEST_SHA256
        or not isinstance(receipt.get("page_input"), dict)
        or receipt["page_input"].get("sha256") != PPI_PARTIAL_RECOVERY_PAGE_INPUT_SHA256
        or not isinstance(page_input, dict)
        or page_input.get("document_id") != document_id
        or page_input.get("pdf_sha256") != document_id
        or not isinstance(page_input.get("pages"), list)
        or len(page_input["pages"]) != 10
    ):
        raise BatchError("PPI_PARTIAL_RECOVERY_PRIOR_RUN_BINDING_MISMATCH")

    chunk_rows = receipt.get("chunks")
    if (
        not isinstance(chunk_rows, list)
        or len(chunk_rows) != 2
        or not isinstance(chunk_rows[0], dict)
        or chunk_rows[0].get("chunk_index") != 1
        or chunk_rows[0].get("chunk_sha256") != PPI_PARTIAL_RECOVERY_SUCCESS_CHUNK_SHA256
        or chunk_rows[0].get("status") != "SUCCEEDED"
        or not isinstance(chunk_rows[1], dict)
        or chunk_rows[1].get("chunk_index") != 2
        or chunk_rows[1].get("chunk_sha256") != PPI_PARTIAL_RECOVERY_FAILED_CHUNK_SHA256
        or chunk_rows[1].get("status") != "FAILED_NO_RETRY"
        or not isinstance(chunk_rows[1].get("queue_item"), dict)
        or chunk_rows[1]["queue_item"].get("idempotency_key") != PPI_PARTIAL_RECOVERY_FAILED_QUEUE_KEY
    ):
        raise BatchError("PPI_PARTIAL_RECOVERY_PRIOR_CHUNKS_MISMATCH")

    jobs = queue_state.get("jobs") if isinstance(queue_state, dict) else None
    success = jobs.get(PPI_PARTIAL_RECOVERY_SUCCESS_QUEUE_KEY) if isinstance(jobs, dict) else None
    failed = jobs.get(PPI_PARTIAL_RECOVERY_FAILED_QUEUE_KEY) if isinstance(jobs, dict) else None
    if not isinstance(jobs, dict) or len(jobs) != 4:
        raise BatchError("PPI_PARTIAL_RECOVERY_QUEUE_STATE_INVALID")
    if (
        not isinstance(success, dict)
        or success.get("status") != "SUCCEEDED"
        or success.get("attempt_count") != 1
        or success.get("max_attempts") != 1
        or success.get("payload_sha256") != PPI_PARTIAL_RECOVERY_SUCCESS_PAYLOAD_SHA256
        or success.get("raw_sha256") != PPI_PARTIAL_RECOVERY_SUCCESS_RESPONSE_SHA256
        or success.get("validated_sha256") != PPI_PARTIAL_RECOVERY_SUCCESS_RESPONSE_SHA256
        or not isinstance(failed, dict)
        or failed.get("status") != "FAILED"
        or failed.get("attempt_count") != 1
        or failed.get("max_attempts") != 1
        or failed.get("payload_sha256") != PPI_PARTIAL_RECOVERY_FAILED_PAYLOAD_SHA256
        or failed.get("raw_sha256") is not None
        or not isinstance(failed.get("attempts"), list)
        or len(failed["attempts"]) != 1
        or not isinstance(failed["attempts"][0], dict)
        or failed["attempts"][0].get("status") != "FAILED"
        or failed["attempts"][0].get("error", {}).get("message") != "CHAT_HTTP_STATUS:400"
        or failed["attempts"][0].get("error", {}).get("type") != "TransportError"
    ):
        raise BatchError("PPI_PARTIAL_RECOVERY_QUEUE_JOBS_MISMATCH")

    queue_root = prior_root / "queue"
    try:
        prior_payload = json.loads(
            (queue_root / f"jobs/{PPI_PARTIAL_RECOVERY_FAILED_QUEUE_KEY}/input.json").read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise BatchError("PPI_PARTIAL_RECOVERY_PRIOR_PAYLOAD_INVALID") from None
    if (
        not isinstance(prior_payload, dict)
        or prior_payload.get("article_id") != PPI_PARTIAL_RECOVERY_FAILED_PRIOR_ARTICLE_ID
        or prior_payload.get("source_sha256") != document_id
        or prior_payload.get("source_document_id") != document_id
        or prior_payload.get("source_text_sha256") != PPI_PARTIAL_RECOVERY_FAILED_CHUNK_SHA256
        or prior_payload.get("pdf_tool_binding", {}).get("page_input_sha256") != PPI_PARTIAL_RECOVERY_PAGE_INPUT_SHA256
        or prior_payload.get("model_binding", {}).get("model_settings_sha256") != CONTINUATION_CANDIDATE_SETTINGS_SHA256
        or prior_payload.get("model_binding", {}).get("runtime_settings_sha256") != EXPECTED_RUNTIME_SHA256
        or _sha256((queue_root / f"jobs/{PPI_PARTIAL_RECOVERY_FAILED_QUEUE_KEY}/input.json").read_bytes())
        != PPI_PARTIAL_RECOVERY_FAILED_PAYLOAD_SHA256
        or not isinstance(failed_input, dict)
        or failed_input.get("model") != local_model.MODEL_ID
        or failed_input.get("max_tokens") != 32768
        or failed_input.get("temperature") != 0.0
        or failed_input.get("stream") is not True
        or not isinstance(stream_receipt, dict)
        or stream_receipt.get("status") != "FAILED"
        or stream_receipt.get("idempotency_key") != PPI_PARTIAL_RECOVERY_FAILED_QUEUE_KEY
        or stream_receipt.get("failure_code") != "TransportError"
        or stream_receipt.get("model_id") != local_model.MODEL_ID
        or stream_receipt.get("model_settings_sha256") != CONTINUATION_CANDIDATE_SETTINGS_SHA256
        or stream_receipt.get("runtime_settings_sha256") != EXPECTED_RUNTIME_SHA256
        or not isinstance(stream_receipt.get("rounds"), list)
        or len(stream_receipt["rounds"]) != 1
        or stream_receipt["rounds"][0].get("status") != "FAILED"
        or stream_receipt["rounds"][0].get("request_input_sha256") != PPI_PARTIAL_RECOVERY_FAILED_REQUEST_INPUT_SHA256
        or stream_receipt["rounds"][0].get("raw_sse_sha256") != PPI_PARTIAL_RECOVERY_FAILED_RAW_SSE_SHA256
    ):
        raise BatchError("PPI_PARTIAL_RECOVERY_FAILED_REQUEST_BINDING_MISMATCH")
    raw_sse = artifact_raw[
        f"evidence/streams/{PPI_PARTIAL_RECOVERY_FAILED_QUEUE_KEY}/attempt-0001/round-01.raw.sse"
    ]
    if CONTINUATION_RECOVERY_ERROR_CODE.encode("ascii") not in raw_sse:
        raise BatchError("PPI_PARTIAL_RECOVERY_PREFILL_ERROR_UNCONFIRMED")

    success_input_path = queue_root / f"jobs/{PPI_PARTIAL_RECOVERY_SUCCESS_QUEUE_KEY}/input.json"
    success_raw_path = queue_root / f"jobs/{PPI_PARTIAL_RECOVERY_SUCCESS_QUEUE_KEY}/attempt-0001.raw"
    success_validated_path = queue_root / f"jobs/{PPI_PARTIAL_RECOVERY_SUCCESS_QUEUE_KEY}/attempt-0001.validated.json"
    for path, expected_sha in (
        (success_input_path, PPI_PARTIAL_RECOVERY_SUCCESS_PAYLOAD_SHA256),
        (success_raw_path, PPI_PARTIAL_RECOVERY_SUCCESS_RESPONSE_SHA256),
        (success_validated_path, PPI_PARTIAL_RECOVERY_SUCCESS_RESPONSE_SHA256),
    ):
        if not _continuation_path_is_safe(path, queue_root, allow_missing=False) or _sha256(_read_regular(path, "PPI_PARTIAL_RECOVERY_SUCCESS_ARTIFACT_UNAVAILABLE")) != expected_sha:
            raise BatchError("PPI_PARTIAL_RECOVERY_SUCCESS_ARTIFACT_MISMATCH")
    return {"prior_payload": prior_payload, "prior_queue_root": queue_root, "partial_chunk_recovery": dict(partial)}


def _tool_canary_success_status(status: Any) -> bool:
    return status in {
        "USER_ACCEPTED_REUSED_REPORT",
        "MODEL_GENERATED_TEXT_COMPLETE_SOURCE_REVIEW_PENDING",
        "MODEL_GENERATED_TEXT_PARTIAL_SOURCE_REVIEW_PENDING",
    }


def _read_regular(path: Path, code: str) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise BatchError(code)
    try:
        return path.read_bytes()
    except OSError:
        raise BatchError(code) from None


def _pre_model_tool_canary_abort_is_retryable(
    *,
    document_id: str,
    state_root: Path,
    plan: Mapping[str, Any],
    run_progress: Mapping[str, Any],
    document_progress: Mapping[str, Any],
    receipt: Mapping[str, Any],
    page_input: Mapping[str, Any],
    failed_page: Mapping[str, Any],
    queue_state: Mapping[str, Any] | None,
) -> bool:
    """Allow a retry only when the earlier canary stopped before any model work."""
    progress_documents = run_progress.get("documents")
    selected = plan.get("selected_documents")
    pages = page_input.get("pages")
    source = receipt.get("source")
    input_source = page_input.get("source")
    page_input_ref = receipt.get("page_input")
    queue_jobs = queue_state.get("jobs") if isinstance(queue_state, Mapping) else None
    no_queue_work = queue_state is None or (isinstance(queue_jobs, dict) and not queue_jobs)
    if not isinstance(progress_documents, list) or len(progress_documents) != 1:
        return False
    if not isinstance(selected, list) or len(selected) != 1:
        return False
    if not isinstance(pages, list) or len(pages) != 1 or not isinstance(pages[0], dict):
        return False
    if not isinstance(source, dict) or not isinstance(input_source, dict):
        return False
    if not isinstance(page_input_ref, dict):
        return False
    if not isinstance(progress_documents[0], Mapping) or not isinstance(selected[0], Mapping):
        return False
    source_rows = source.get("page_extraction_sources")
    if not isinstance(source_rows, list) or len(source_rows) != 1 or not isinstance(source_rows[0], Mapping):
        return False
    row = progress_documents[0]
    entry = selected[0]
    page = pages[0]
    return bool(
        plan.get("continuation_id") == "tool-canary-20261019-r2"
        and plan.get("state_root") == str(state_root)
        and entry.get("document_id") == document_id == TOOL_CANARY_DOCUMENT_ID
        and entry.get("prior_status") == "FAILED_NO_RETRY"
        and entry.get("source_sha256") == document_id
        and isinstance(entry.get("tool_canary"), Mapping)
        and run_progress.get("status") == "COMPLETED_WITH_PER_DOCUMENT_STATES"
        and run_progress.get("continuation_id") == plan.get("continuation_id")
        and run_progress.get("continuation_plan_sha256") == TOOL_CANARY_PREMODEL_RETRY_PLAN_SHA256
        and run_progress.get("manifest_sha256") == EXPECTED_BATCH_MANIFEST_SHA256
        and run_progress.get("document_count") == 1
        and row.get("document_id") == document_id
        and row.get("continuation_id") == plan.get("continuation_id")
        and row.get("continuation_plan_sha256") == TOOL_CANARY_PREMODEL_RETRY_PLAN_SHA256
        and row.get("status") == "SOURCE_REPAIR_FAILED_NO_MODEL"
        and receipt.get("schema") == "v4.pdf_research_simple_batch.document_receipt.v1"
        and receipt.get("status") == "SOURCE_REPAIR_FAILED_NO_MODEL"
        and receipt.get("document_id") == document_id
        and receipt.get("pdf_sha256") == document_id
        and receipt.get("manifest_sha256") == EXPECTED_BATCH_MANIFEST_SHA256
        and page_input_ref.get("path") == str(state_root / "documents" / document_id / "page-input.json")
        and page_input_ref.get("sha256") == TOOL_CANARY_PREMODEL_RETRY_ARTIFACT_SHA256S[
            f"documents/{document_id}/page-input.json"
        ]
        and not any(key in receipt for key in ("chunks", "analysis", "report", "result"))
        and document_progress.get("document_id") == document_id
        and document_progress.get("status") == "SOURCE_REPAIR_FAILED_NO_MODEL"
        and document_progress.get("model_requests") == 0
        and not document_progress.get("chunk_states")
        and not any(key in document_progress for key in ("chunks", "analysis", "report", "result"))
        and source.get("source_repair_status") == "FAILED_UNSUPPORTED_GEOMETRY"
        and source.get("new_ocr_attempts_this_tick") == 0
        and source.get("ocr_invoked") is False
        and source_rows[0].get("failure_code") == TOOL_CANARY_PREMODEL_RETRY_FAILURE_CODE
        and input_source.get("source_repair_status") == "FAILED_UNSUPPORTED_GEOMETRY"
        and page.get("page_number") == 1
        and page.get("status") == "TEXT_UNAVAILABLE"
        and page.get("text") == ""
        and page.get("text_characters") == 0
        and failed_page.get("schema") == SOURCE_REPAIR_SCHEMA
        and failed_page.get("pdf_sha256") == document_id
        and failed_page.get("page_number") == 1
        and failed_page.get("status") == "SOURCE_REPAIR_UNSUPPORTED_GEOMETRY"
        and failed_page.get("failure_code") == TOOL_CANARY_PREMODEL_RETRY_FAILURE_CODE
        and failed_page.get("attempts_used_for_page") == 0
        and no_queue_work
    )


def _verified_tool_canary_pre_model_abort() -> Path | None:
    """Verify the one authorized infrastructure-only abort before admitting R3."""
    state_root = TOOL_CANARY_PREMODEL_RETRY_STATE_ROOT.expanduser().absolute()
    if not state_root.exists() and not state_root.is_symlink():
        return None
    if state_root.is_symlink() or not state_root.is_dir():
        raise BatchError("TOOL_CANARY_PREMODEL_RETRY_ROOT_UNSAFE")
    if state_root != DEFAULT_STATE_ROOT.parent / "continuation-tool-canary-20261019-r2":
        raise BatchError("TOOL_CANARY_PREMODEL_RETRY_ROOT_MISMATCH")

    document_id = TOOL_CANARY_DOCUMENT_ID
    document_root = state_root / "documents" / document_id
    expected_hashes = dict(TOOL_CANARY_PREMODEL_RETRY_ARTIFACT_SHA256S)
    expected_hashes["continuation-plan.json"] = TOOL_CANARY_PREMODEL_RETRY_PLAN_SHA256
    for relative, expected_sha in expected_hashes.items():
        path = state_root / relative
        if not _continuation_path_is_safe(path, state_root, allow_missing=False):
            raise BatchError("TOOL_CANARY_PREMODEL_RETRY_ARTIFACT_UNSAFE")
        raw = _read_regular(path, "TOOL_CANARY_PREMODEL_RETRY_ARTIFACT_UNAVAILABLE")
        if _sha256(raw) != expected_sha:
            raise BatchError("TOOL_CANARY_PREMODEL_RETRY_ARTIFACT_SHA_MISMATCH")

    lock_path = state_root / "locks" / "batch-runner.lock"
    if (
        not _continuation_path_is_safe(lock_path, state_root, allow_missing=False)
        or lock_path.stat().st_size != 0
    ):
        raise BatchError("TOOL_CANARY_PREMODEL_RETRY_LOCK_EVIDENCE_INVALID")
    queue_root = state_root / "queue"
    if queue_root.is_symlink() or (queue_root.exists() and not queue_root.is_dir()):
        raise BatchError("TOOL_CANARY_PREMODEL_RETRY_QUEUE_STATE_PRESENT")
    if queue_root.exists():
        for path in queue_root.rglob("*"):
            if path.is_symlink() or path.is_file():
                raise BatchError("TOOL_CANARY_PREMODEL_RETRY_QUEUE_STATE_PRESENT")

    expected_files = set(expected_hashes) | {"locks/batch-runner.lock"}
    observed_files: set[str] = set()
    for path in state_root.rglob("*"):
        if path.is_symlink():
            raise BatchError("TOOL_CANARY_PREMODEL_RETRY_ARTIFACT_UNSAFE")
        if path.is_file():
            observed_files.add(path.relative_to(state_root).as_posix())
    if observed_files != expected_files:
        raise BatchError("TOOL_CANARY_PREMODEL_RETRY_ARTIFACT_SET_MISMATCH")

    try:
        plan = json.loads((state_root / "continuation-plan.json").read_text(encoding="utf-8"))
        run_progress = json.loads((state_root / "run-progress.json").read_text(encoding="utf-8"))
        document_progress = json.loads((document_root / "progress.json").read_text(encoding="utf-8"))
        receipt = json.loads((document_root / "receipt.json").read_text(encoding="utf-8"))
        page_input = json.loads((document_root / "page-input.json").read_text(encoding="utf-8"))
        failed_page = json.loads(
            (document_root / "derived-ocr" / "page-0001.failed.json").read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise BatchError("TOOL_CANARY_PREMODEL_RETRY_ARTIFACT_INVALID") from None
    if not _pre_model_tool_canary_abort_is_retryable(
        document_id=document_id,
        state_root=state_root,
        plan=plan,
        run_progress=run_progress,
        document_progress=document_progress,
        receipt=receipt,
        page_input=page_input,
        failed_page=failed_page,
        queue_state=None,
    ):
        raise BatchError("TOOL_CANARY_PREMODEL_RETRY_EVIDENCE_INVALID")
    return state_root


def _assert_tool_canary_has_no_existing_run(document_id: str) -> None:
    """Reject any earlier success except the one proved zero-work pre-model abort."""
    research_root = pdf_research.PDF_RESEARCH_STATE_ROOT.expanduser().absolute()
    for relative in (Path("results") / f"{document_id}.json", Path("receipts") / f"{document_id}.json"):
        path = research_root / relative
        if path.is_symlink():
            raise BatchError("TOOL_CANARY_EXISTING_RESULT_UNSAFE")
        if path.exists():
            raise BatchError("TOOL_CANARY_EXISTING_RESULT_PRESENT")

    batch_parent = DEFAULT_STATE_ROOT.expanduser().absolute().parent
    retryable_pre_model_root = _verified_tool_canary_pre_model_abort()
    original_receipt = DEFAULT_STATE_ROOT / "documents" / document_id / "receipt.json"
    for state_root in batch_parent.iterdir():
        if state_root.is_symlink() or not state_root.is_dir():
            continue
        if retryable_pre_model_root is not None and state_root == retryable_pre_model_root:
            continue
        receipt_path = state_root / "documents" / document_id / "receipt.json"
        if receipt_path.is_symlink():
            raise BatchError("TOOL_CANARY_PRIOR_RECEIPT_UNSAFE")
        if receipt_path.is_file() and receipt_path != original_receipt:
            raise BatchError("TOOL_CANARY_PRIOR_ATTEMPT_PRESENT")
        progress_path = state_root / "run-progress.json"
        if progress_path.is_symlink():
            raise BatchError("TOOL_CANARY_PRIOR_PROGRESS_UNSAFE")
        if progress_path.is_file():
            try:
                progress = json.loads(progress_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                raise BatchError("TOOL_CANARY_PRIOR_PROGRESS_INVALID") from None
            rows = progress.get("documents") if isinstance(progress, dict) else None
            if isinstance(rows, list):
                for row in rows:
                    if isinstance(row, dict) and row.get("document_id") == document_id:
                        if state_root != DEFAULT_STATE_ROOT:
                            raise BatchError("TOOL_CANARY_PRIOR_ATTEMPT_PRESENT")
                        if _tool_canary_success_status(row.get("status")):
                            raise BatchError("TOOL_CANARY_SUCCESS_ALREADY_EXISTS")

        queue_state_path = state_root / "queue" / "queue-state.json"
        if queue_state_path.is_symlink():
            raise BatchError("TOOL_CANARY_PRIOR_QUEUE_UNSAFE")
        if queue_state_path.is_file():
            try:
                state = json.loads(queue_state_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                raise BatchError("TOOL_CANARY_PRIOR_QUEUE_INVALID") from None
            jobs = state.get("jobs") if isinstance(state, dict) else None
            if not isinstance(jobs, dict):
                raise BatchError("TOOL_CANARY_PRIOR_QUEUE_INVALID")
            for key, item in jobs.items():
                identity = item.get("identity") if isinstance(item, dict) else None
                article_id = identity.get("article_id") if isinstance(identity, dict) else None
                if isinstance(article_id, str) and article_id.startswith(f"{document_id}:"):
                    if state_root != DEFAULT_STATE_ROOT or key != TOOL_CANARY_PRIOR_QUEUE_KEY:
                        raise BatchError("TOOL_CANARY_PRIOR_QUEUE_ATTEMPT_PRESENT")
                    if item.get("status") != "FAILED":
                        raise BatchError("TOOL_CANARY_PRIOR_QUEUE_STATUS_CHANGED")

    global_queue = research_root / "queue" / "queue-state.json"
    if global_queue.is_symlink():
        raise BatchError("TOOL_CANARY_GLOBAL_QUEUE_UNSAFE")
    if global_queue.is_file():
        try:
            state = json.loads(global_queue.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            raise BatchError("TOOL_CANARY_GLOBAL_QUEUE_INVALID") from None
        jobs = state.get("jobs") if isinstance(state, dict) else None
        if not isinstance(jobs, dict):
            raise BatchError("TOOL_CANARY_GLOBAL_QUEUE_INVALID")
        for item in jobs.values():
            identity = item.get("identity") if isinstance(item, dict) else None
            article_id = identity.get("article_id") if isinstance(identity, dict) else None
            if isinstance(article_id, str) and article_id.startswith(f"{document_id}:"):
                raise BatchError("TOOL_CANARY_GLOBAL_QUEUE_ATTEMPT_PRESENT")


def _validate_fresh_tool_canary(
    entry: Mapping[str, Any],
    document: Mapping[str, Any],
    prior_row: Mapping[str, Any] | None,
    queue_jobs: Mapping[str, Any],
) -> dict[str, Any]:
    document_id = str(document.get("document_id", ""))
    evidence = entry.get("tool_canary")
    expected_evidence = {
        "inventory_path": str(TOOL_CANARY_INVENTORY_PATH),
        "inventory_sha256": TOOL_CANARY_INVENTORY_SHA256,
        "page_input_path": str(TOOL_CANARY_PAGE_INPUT_PATH),
        "page_input_sha256": TOOL_CANARY_PAGE_INPUT_SHA256,
        "prior_receipt_sha256": TOOL_CANARY_PRIOR_RECEIPT_SHA256,
        "prior_queue_idempotency_key": TOOL_CANARY_PRIOR_QUEUE_KEY,
        "source_visual_review_path": str(TOOL_CANARY_SOURCE_REVIEW_PATH),
        "source_visual_review_sha256": TOOL_CANARY_SOURCE_REVIEW_SHA256,
        "prior_failure_code": TOOL_CANARY_FAILURE_CODE,
    }
    if (
        document_id != TOOL_CANARY_DOCUMENT_ID
        or entry.get("prior_status") != "FAILED_NO_RETRY"
        or prior_row is None
        or prior_row.get("status") != "FAILED_NO_RETRY"
        or entry.get("source_sha256") != document_id
        or document.get("pdf_sha256") != document_id
        or set(entry) != {"document_id", "prior_status", "source_sha256", "tool_canary"}
        or evidence != expected_evidence
    ):
        raise BatchError("TOOL_CANARY_SELECTION_BINDING_INVALID")

    inventory_raw = _read_regular(TOOL_CANARY_INVENTORY_PATH, "TOOL_CANARY_INVENTORY_UNAVAILABLE")
    if _sha256(inventory_raw) != TOOL_CANARY_INVENTORY_SHA256:
        raise BatchError("TOOL_CANARY_INVENTORY_SHA_MISMATCH")
    try:
        inventory = json.loads(inventory_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        raise BatchError("TOOL_CANARY_INVENTORY_INVALID") from None
    canary = inventory.get("canary") if isinstance(inventory, dict) else None
    summary = inventory.get("summary") if isinstance(inventory, dict) else None
    outstanding = inventory.get("outstanding") if isinstance(inventory, dict) else None
    completed = inventory.get("completed") if isinstance(inventory, dict) else None
    inventory_rows = [
        row for row in outstanding or []
        if isinstance(row, dict) and row.get("document_id") == document_id
    ] if isinstance(outstanding, list) else []
    if (
        not isinstance(summary, dict)
        or summary.get("unique_document_count") != 2209
        or summary.get("completed_count") != 86
        or summary.get("outstanding_count") != 2123
        or not isinstance(canary, dict)
        or canary.get("document_id") != document_id
        or canary.get("actual_prior_status") != "FAILED_NO_RETRY"
        or canary.get("source_pdf_sha256") != document_id
        or canary.get("page_input_path") != str(TOOL_CANARY_PAGE_INPUT_PATH)
        or canary.get("page_input_actual_sha256") != TOOL_CANARY_PAGE_INPUT_SHA256
        or canary.get("source_pdf_path") != document.get("local_pdf_path")
        or len(inventory_rows) != 1
        or inventory_rows[0].get("actual_prior_status") != "FAILED_NO_RETRY"
        or any(isinstance(row, dict) and row.get("document_id") == document_id for row in completed or [])
    ):
        raise BatchError("TOOL_CANARY_INVENTORY_BINDING_INVALID")

    page_input_raw = _read_regular(TOOL_CANARY_PAGE_INPUT_PATH, "TOOL_CANARY_PAGE_INPUT_UNAVAILABLE")
    if _sha256(page_input_raw) != TOOL_CANARY_PAGE_INPUT_SHA256:
        raise BatchError("TOOL_CANARY_PAGE_INPUT_SHA_MISMATCH")
    try:
        page_input = json.loads(page_input_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        raise BatchError("TOOL_CANARY_PAGE_INPUT_INVALID") from None
    pages = page_input.get("pages") if isinstance(page_input, dict) else None
    if (
        not isinstance(page_input, dict)
        or page_input.get("document_id") != document_id
        or page_input.get("pdf_sha256") != document_id
        or not isinstance(pages, list)
        or len(pages) != 1
        or not isinstance(pages[0], dict)
        or pages[0].get("page_number") != 1
        or _sha256(pages[0].get("text", "").encode("utf-8")) != canary.get("source_page_text_sha256")
    ):
        raise BatchError("TOOL_CANARY_PAGE_INPUT_BINDING_INVALID")
    source_pdf_path = Path(str(canary.get("source_pdf_path", "")))
    if source_pdf_path.is_symlink() or not source_pdf_path.is_file() or _sha256_file(source_pdf_path) != document_id:
        raise BatchError("TOOL_CANARY_SOURCE_PDF_BINDING_INVALID")

    review_raw = _read_regular(TOOL_CANARY_SOURCE_REVIEW_PATH, "TOOL_CANARY_SOURCE_REVIEW_UNAVAILABLE")
    if _sha256(review_raw) != TOOL_CANARY_SOURCE_REVIEW_SHA256:
        raise BatchError("TOOL_CANARY_SOURCE_REVIEW_SHA_MISMATCH")
    try:
        source_review = json.loads(review_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        raise BatchError("TOOL_CANARY_SOURCE_REVIEW_INVALID") from None
    review_values = source_review.get("visually_confirmed_page_1_values") if isinstance(source_review, dict) else None
    if (
        not isinstance(source_review, dict)
        or source_review.get("status") != "WRITER_VISUAL_REVIEW_COMPLETE_INDEPENDENT_ACCEPTANCE_PENDING"
        or source_review.get("document_id") != document_id
        or source_review.get("source_pdf_sha256") != document_id
        or source_review.get("page_input_sha256") != TOOL_CANARY_PAGE_INPUT_SHA256
        or source_review.get("rendered_page_sha256") != TOOL_CANARY_SOURCE_REVIEW_IMAGE_SHA256
        or not isinstance(review_values, list)
        or not any(
            isinstance(row, dict)
            and row.get("metric") == "2025年四层板产品营收"
            and row.get("value") == "41.78"
            and row.get("unit") == "亿元"
            for row in review_values
        )
        or not any(
            isinstance(row, dict)
            and row.get("metric") == "2025年营业收入"
            and row.get("value") == "55.30"
            and row.get("unit") == "亿元"
            for row in review_values
        )
        or not any(
            isinstance(row, dict)
            and row.get("metric") == "2025年四层板产品营收占比"
            and row.get("value") == "75.56"
            and row.get("unit") == "%"
            for row in review_values
        )
    ):
        raise BatchError("TOOL_CANARY_SOURCE_REVIEW_BINDING_INVALID")

    receipt_path = DEFAULT_STATE_ROOT / "documents" / document_id / "receipt.json"
    if not _continuation_path_is_safe(receipt_path, DEFAULT_STATE_ROOT, allow_missing=False):
        raise BatchError("TOOL_CANARY_PRIOR_RECEIPT_UNAVAILABLE")
    receipt_raw = receipt_path.read_bytes()
    if _sha256(receipt_raw) != TOOL_CANARY_PRIOR_RECEIPT_SHA256:
        raise BatchError("TOOL_CANARY_PRIOR_RECEIPT_SHA_MISMATCH")
    try:
        receipt = json.loads(receipt_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        raise BatchError("TOOL_CANARY_PRIOR_RECEIPT_INVALID") from None
    chunks = receipt.get("chunks") if isinstance(receipt, dict) else None
    prior_chunk = next((row for row in chunks or [] if isinstance(row, dict) and row.get("status") == "FAILED_NO_RETRY"), None)
    prior_queue_item = prior_chunk.get("queue_item") if isinstance(prior_chunk, dict) else None
    if (
        not isinstance(receipt, dict)
        or receipt.get("status") != "FAILED_NO_RETRY"
        or receipt.get("document_id") != document_id
        or receipt.get("pdf_sha256") != document_id
        or receipt.get("manifest_sha256") != EXPECTED_BATCH_MANIFEST_SHA256
        or not isinstance(prior_queue_item, dict)
        or prior_queue_item.get("idempotency_key") != TOOL_CANARY_PRIOR_QUEUE_KEY
    ):
        raise BatchError("TOOL_CANARY_PRIOR_RECEIPT_BINDING_INVALID")
    prior_item = queue_jobs.get(TOOL_CANARY_PRIOR_QUEUE_KEY)
    attempts = prior_item.get("attempts") if isinstance(prior_item, dict) else None
    attempt = attempts[0] if isinstance(attempts, list) and len(attempts) == 1 else None
    error = attempt.get("error") if isinstance(attempt, dict) else None
    if (
        not isinstance(prior_item, dict)
        or prior_item.get("idempotency_key") != TOOL_CANARY_PRIOR_QUEUE_KEY
        or prior_item.get("queue_id") != "v4-pdf-simple-batch"
        or prior_item.get("model_id") != local_model.MODEL_ID
        or prior_item.get("status") != "FAILED"
        or prior_item.get("attempt_count") != 1
        or prior_item.get("max_attempts") != 1
        or not isinstance(attempts, list)
        or len(attempts) != 1
        or not isinstance(error, dict)
        or error.get("message") != TOOL_CANARY_FAILURE_CODE
        or prior_item.get("raw_path") is not None
        or prior_item.get("raw_sha256") is not None
    ):
        raise BatchError("TOOL_CANARY_PRIOR_QUEUE_BINDING_INVALID")
    _assert_tool_canary_has_no_existing_run(document_id)
    return {
        "inventory_sha256": TOOL_CANARY_INVENTORY_SHA256,
        "page_input_sha256": TOOL_CANARY_PAGE_INPUT_SHA256,
        "source_visual_review_sha256": TOOL_CANARY_SOURCE_REVIEW_SHA256,
        "prior_receipt_sha256": TOOL_CANARY_PRIOR_RECEIPT_SHA256,
        "prior_queue_idempotency_key": TOOL_CANARY_PRIOR_QUEUE_KEY,
    }


def validate_continuation_plan(
    plan_path: Path,
    *,
    manifest_sha256: str,
    documents: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    plan_path = plan_path.expanduser().absolute()
    if plan_path.is_symlink() or not plan_path.is_file():
        raise BatchError("CONTINUATION_PLAN_UNAVAILABLE")
    try:
        raw = plan_path.read_bytes()
    except OSError:
        raise BatchError("CONTINUATION_PLAN_UNAVAILABLE") from None
    plan_sha = _sha256(raw)
    try:
        plan = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        raise BatchError("CONTINUATION_PLAN_INVALID") from None
    if not isinstance(plan, dict) or plan.get("schema") != CONTINUATION_PLAN_SCHEMA:
        raise BatchError("CONTINUATION_PLAN_SCHEMA_INVALID")
    expected_fields = {
        "schema",
        "continuation_id",
        "source_run_id",
        "manifest_sha256",
        "prior_progress_path",
        "prior_progress_sha256",
        "prior_progress_status",
        "runtime_settings_sha256",
        "expected_model_settings_sha256",
        "observed_model_settings_sha256",
        "state_root",
        "selected_documents",
        "one_time_recovery_limit",
        "excluded_prior_statuses",
        "research_only",
    }
    synthesis_recovery = None
    if "synthesis_stage_recovery" in plan:
        expected_fields.add("synthesis_stage_recovery")
        synthesis_recovery = load_synthesis_recovery()
        if raw != synthesis_recovery["plan_raw"]:
            raise BatchError("CONTINUATION_SYNTHESIS_RECOVERY_PLAN_MISMATCH")
    if "tool_budget_recovery" in plan:
        expected_fields.add("tool_budget_recovery")
        recovery = load_tool_budget_recovery({"tool_budget_recovery": {
            "descriptor": _v2_data_ref("tool-budget-recovery-v2.json"), "plan_source": _v2_data_ref("recovery-plan-v2.json")}})
        if raw != recovery["plan_raw"]:
            raise BatchError("CONTINUATION_TOOL_RECOVERY_PLAN_MISMATCH")
    if "execution_runtime_settings_sha256" in plan:
        expected_fields.add("execution_runtime_settings_sha256")
        if plan["execution_runtime_settings_sha256"] != ANALYSIS_RUNTIME_SHA256:
            raise BatchError("ANALYSIS_PLAN_EXECUTION_RUNTIME_MISMATCH")
    if set(plan) != expected_fields:
        raise BatchError("CONTINUATION_PLAN_FIELDS_INVALID")
    continuation_id = plan.get("continuation_id")
    if not isinstance(continuation_id, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", continuation_id):
        raise BatchError("CONTINUATION_ID_INVALID")
    if plan.get("source_run_id") != CONTINUATION_SOURCE_RUN_ID:
        raise BatchError("CONTINUATION_SOURCE_RUN_INVALID")
    if plan.get("manifest_sha256") != manifest_sha256 or manifest_sha256 != EXPECTED_BATCH_MANIFEST_SHA256:
        raise BatchError("CONTINUATION_MANIFEST_SHA_MISMATCH")
    expected_progress_path = _continuation_prior_progress_path().expanduser().absolute()
    if plan.get("prior_progress_path") != str(expected_progress_path):
        raise BatchError("CONTINUATION_PRIOR_PROGRESS_PATH_MISMATCH")
    progress_sha = plan.get("prior_progress_sha256")
    if not isinstance(progress_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", progress_sha):
        raise BatchError("CONTINUATION_PRIOR_PROGRESS_SHA_INVALID")
    if plan.get("prior_progress_status") != "STOPPED_GRACEFULLY":
        raise BatchError("CONTINUATION_PRIOR_PROGRESS_STATUS_MISMATCH")
    prior_progress = _load_continuation_progress(expected_progress_path, progress_sha)
    prior_rows = _prior_progress_rows(prior_progress)

    if plan.get("runtime_settings_sha256") != EXPECTED_RUNTIME_SHA256:
        raise BatchError("CONTINUATION_RUNTIME_SHA_UNSUPPORTED")
    expected_settings = plan.get("expected_model_settings_sha256")
    observed_settings = plan.get("observed_model_settings_sha256")
    if (
        not isinstance(expected_settings, str)
        or expected_settings not in CONTINUATION_ALLOWED_SETTINGS_SHA256S
        or observed_settings != expected_settings
    ):
        raise BatchError("CONTINUATION_MODEL_SETTINGS_SHA_UNSUPPORTED")
    if type(plan.get("one_time_recovery_limit")) is not int or plan.get("one_time_recovery_limit") != 1:
        raise BatchError("CONTINUATION_RECOVERY_LIMIT_INVALID")
    excluded = plan.get("excluded_prior_statuses")
    if (
        not isinstance(excluded, list)
        or len(excluded) != len(CONTINUATION_EXCLUDED_PRIOR_STATUSES)
        or set(excluded) != CONTINUATION_EXCLUDED_PRIOR_STATUSES
    ):
        raise BatchError("CONTINUATION_EXCLUDED_STATUSES_INVALID")
    if plan.get("research_only") != {
        "research_only": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }:
        raise BatchError("CONTINUATION_RESEARCH_SAFETY_INVALID")

    selected = plan.get("selected_documents")
    if not isinstance(selected, list) or not 1 <= len(selected) <= CONTINUATION_MAX_DOCUMENTS:
        raise BatchError("CONTINUATION_SELECTION_COUNT_INVALID")
    manifest_by_id = {str(row.get("document_id")): row for row in documents}
    seen: set[str] = set()
    recovery_count = 0
    recovery_bindings: dict[str, dict[str, Any]] = {}
    tool_canary_bindings: dict[str, dict[str, Any]] = {}
    partial_chunk_recovery_ids: set[str] = set()
    prior_queue_jobs = _load_prior_queue_jobs()
    for entry in selected:
        if not isinstance(entry, dict):
            raise BatchError("CONTINUATION_SELECTION_INVALID")
        document_id = entry.get("document_id")
        if not isinstance(document_id, str) or document_id in seen:
            raise BatchError("CONTINUATION_SELECTION_DUPLICATE_OR_INVALID")
        seen.add(document_id)
        document = manifest_by_id.get(document_id)
        if document is None:
            raise BatchError("CONTINUATION_SELECTION_OUTSIDE_MANIFEST")
        if entry.get("source_sha256") != document.get("pdf_sha256"):
            raise BatchError("CONTINUATION_SOURCE_SHA_MISMATCH")
        prior_row = prior_rows.get(document_id)
        prior_status = entry.get("prior_status")
        if prior_status in CONTINUATION_EXCLUDED_PRIOR_STATUSES:
            raise BatchError("CONTINUATION_PRIOR_STATUS_EXCLUDED")
        if prior_status == "UNPROCESSED":
            if prior_row is not None or "recovery" in entry:
                raise BatchError("CONTINUATION_UNPROCESSED_STATUS_MISMATCH")
            if set(entry) != {"document_id", "prior_status", "source_sha256"}:
                raise BatchError("CONTINUATION_SELECTION_FIELDS_INVALID")
            prior_receipt_path = DEFAULT_STATE_ROOT / "documents" / document_id / "receipt.json"
            if prior_receipt_path.exists() or prior_receipt_path.is_symlink():
                raise BatchError("CONTINUATION_UNPROCESSED_HAS_PRIOR_RECEIPT")
            if any(
                isinstance(item, dict)
                and isinstance(item.get("identity"), dict)
                and str(item["identity"].get("article_id", "")).startswith(f"{document_id}:")
                for item in prior_queue_jobs.values()
            ):
                raise BatchError("CONTINUATION_UNPROCESSED_HAS_QUEUE_HISTORY")
        elif prior_status == "FAILED_NO_RETRY":
            if "tool_canary" in entry:
                if prior_row is None:
                    raise BatchError("CONTINUATION_RECOVERY_PRIOR_ROW_MISSING")
                tool_canary_bindings[document_id] = _validate_fresh_tool_canary(
                    entry,
                    document,
                    prior_row,
                    prior_queue_jobs,
                )
            elif "partial_chunk_recovery" in entry:
                recovery_bindings[document_id] = _validate_ppi_partial_chunk_recovery(entry, document)
                recovery_count += 1
                partial_chunk_recovery_ids.add(document_id)
            else:
                if prior_row is not None and prior_row.get("status") not in {"UNPROCESSED", "FAILED_NO_RETRY"}:
                    raise BatchError("CONTINUATION_RECOVERY_PRIOR_ROW_STATUS_MISMATCH")
                if set(entry) != {"document_id", "prior_status", "source_sha256", "recovery"}:
                    raise BatchError("CONTINUATION_SELECTION_FIELDS_INVALID")
                recovery_bindings[document_id] = _validate_recovery_selection(
                    entry,
                    document,
                    expected_model_settings_sha256=expected_settings,
                )
                recovery_count += 1
        else:
            raise BatchError("CONTINUATION_PRIOR_STATUS_NOT_ELIGIBLE")
    if recovery_count > 1:
        raise BatchError("CONTINUATION_RECOVERY_LIMIT_EXCEEDED")
    if tool_canary_bindings and (len(tool_canary_bindings) != 1 or len(selected) != 1 or recovery_count):
        raise BatchError("TOOL_CANARY_PLAN_MUST_BE_SINGLETON")
    state_parent = DEFAULT_STATE_ROOT.parent.expanduser().absolute()
    if not state_parent.is_dir() or state_parent.is_symlink():
        raise BatchError("CONTINUATION_STATE_PARENT_UNAVAILABLE")
    if recovery_count:
        recovery_entry = next(row for row in selected if row.get("prior_status") == "FAILED_NO_RETRY")
        recovery = recovery_entry["recovery"]
        if partial_chunk_recovery_ids:
            if (
                partial_chunk_recovery_ids != {PPI_PARTIAL_RECOVERY_DOCUMENT_ID}
                or len(selected) != 1
                or recovery_entry.get("partial_chunk_recovery") != PPI_PARTIAL_RECOVERY_SELECTION_FIELDS
                or expected_settings != CONTINUATION_CANDIDATE_SETTINGS_SHA256
            ):
                raise BatchError("PPI_PARTIAL_RECOVERY_PLAN_SCOPE_INVALID")
        elif recovery_bindings.get(recovery_entry["document_id"], {}).get(
            "prior_model_settings_sha256"
        ) != expected_settings:
            raise BatchError("CONTINUATION_RECOVERY_REQUIRES_MATCHED_SETTINGS")
        expected_state_root = state_parent / f"recovery-{recovery['prior_queue_idempotency_key']}"
    else:
        expected_state_root = state_parent / f"continuation-{continuation_id}"
    state_root_raw = plan.get("state_root")
    if not isinstance(state_root_raw, str) or Path(state_root_raw).expanduser().absolute() != expected_state_root:
        raise BatchError("CONTINUATION_STATE_ROOT_MISMATCH")
    if not _continuation_path_is_safe(expected_state_root, state_parent, allow_missing=True):
        raise BatchError("CONTINUATION_STATE_ROOT_UNSAFE")
    if expected_state_root.resolve(strict=False) == DEFAULT_STATE_ROOT.resolve(strict=False):
        raise BatchError("CONTINUATION_STATE_ROOT_MUST_BE_SEPARATE")
    existing_plan = expected_state_root / "continuation-plan.json"
    if existing_plan.is_symlink():
        raise BatchError("CONTINUATION_PLAN_IMMUTABLE_CONFLICT")
    if existing_plan.exists():
        if _sha256_file(existing_plan) != plan_sha:
            raise BatchError("CONTINUATION_PLAN_IMMUTABLE_CONFLICT")
    return {
        "plan": plan,
        "plan_raw": raw,
        "plan_sha256": plan_sha,
        "synthesis_stage_recovery": synthesis_recovery,
        "state_root": expected_state_root,
        "selected_documents": [manifest_by_id[row["document_id"]] for row in selected],
        "selected_entries": {row["document_id"]: row for row in selected},
        "recovery_bindings": recovery_bindings,
        "tool_canary_bindings": tool_canary_bindings,
        "prior_queue_root": _continuation_prior_queue_root(),
        "expected_model_settings_sha256": expected_settings,
    }


def _candidate_page_count(document: Mapping[str, Any]) -> int | None:
    explicit = document.get("page_count")
    if type(explicit) is int and explicit > 0:
        return explicit
    counts = {
        candidate.get("page_count")
        for candidate in document.get("cache_candidates", [])
        if isinstance(candidate, dict) and type(candidate.get("page_count")) is int and candidate["page_count"] > 0
    }
    if len(counts) > 1:
        raise BatchError("CACHE_CANDIDATE_PAGE_COUNT_CONFLICT")
    return next(iter(counts)) if counts else None


def _read_source_text_canary_review() -> dict[str, Any] | None:
    path = SOURCE_CANARY_REVIEW_DEFAULT
    if path.is_symlink() or not path.is_file():
        return None
    raw = path.read_bytes()
    if _sha256(raw) != SOURCE_CANARY_REVIEW_SHA256:
        raise BatchError("SOURCE_TEXT_CANARY_REVIEW_SHA_MISMATCH")
    try:
        review = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        raise BatchError("SOURCE_TEXT_CANARY_REVIEW_INVALID") from None
    scope = review.get("scope") if isinstance(review, dict) else None
    acceptance = review.get("acceptance") if isinstance(review, dict) else None
    boundary = review.get("accepted_markdown_boundary") if isinstance(review, dict) else None
    if (
        not isinstance(review, dict)
        or review.get("schema") != SOURCE_CANARY_REVIEW_SCHEMA
        or review.get("status") != "SOURCE_CONTENT_PASS"
        or not isinstance(review.get("reviewer"), str)
        or not review["reviewer"].strip()
        or review.get("pdf_sha256") != FIRST_CONTENT_FAIL_PDF_SHA256
        or review.get("attempt_sha256") != SOURCE_CANARY_ATTEMPT_SHA256
        or review.get("text_sha256") != SOURCE_CANARY_TEXT_SHA256
        or review.get("text_characters") != 5_353
        or not isinstance(scope, dict)
        or scope.get("document_id") != FIRST_CONTENT_FAIL_PDF_SHA256
        or scope.get("page_number") != 1
        or not isinstance(acceptance, dict)
        or acceptance.get("source_content_pass") is not True
        or acceptance.get("full_page_row_level_transcription_pass") is not False
        or not isinstance(boundary, dict)
        or not isinstance(boundary.get("adequate_for"), str)
        or not isinstance(boundary.get("can_report_from_text"), list)
        or not isinstance(boundary.get("must_mark_uncertain_or_unknown"), list)
        or not isinstance(boundary.get("exclude_or_bound"), list)
    ):
        raise BatchError("SOURCE_TEXT_CANARY_REVIEW_BINDING_MISMATCH")
    return {
        "path": str(path),
        "sha256": SOURCE_CANARY_REVIEW_SHA256,
        "reviewer": review["reviewer"],
        "accepted_markdown_boundary": boundary,
        "acceptance": acceptance,
    }


def _read_scale_canary_page(
    document_id: str,
    page_number: int,
    expected_page_count: int | None = None,
) -> tuple[pdf_research.PageText, dict[str, Any]] | None:
    if document_id != FIRST_CONTENT_FAIL_PDF_SHA256 or page_number != 1:
        return None
    review = _read_source_text_canary_review()
    if review is None:
        return None
    path = SOURCE_CANARY_ATTEMPT_PATH
    if path.is_symlink() or not path.is_file() or _sha256_file(path) != SOURCE_CANARY_ATTEMPT_SHA256:
        raise BatchError("SOURCE_TEXT_CANARY_ATTEMPT_SHA_MISMATCH")
    try:
        attempt = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise BatchError("SOURCE_TEXT_CANARY_ATTEMPT_INVALID") from None
    text_record = attempt.get("text") if isinstance(attempt, dict) else None
    text = text_record.get("value") if isinstance(text_record, dict) else None
    page = attempt.get("page") if isinstance(attempt, dict) else None
    source_pdf = attempt.get("source_pdf") if isinstance(attempt, dict) else None
    render = attempt.get("render_identity") if isinstance(attempt, dict) else None
    full_result = (attempt.get("ocr_attempt") or {}).get("full_vision_result") if isinstance(attempt, dict) else None
    if (
        not isinstance(attempt, dict)
        or attempt.get("schema") != "v4.pdf_simple_batch.ocr_scale_canary_attempt.v1"
        or attempt.get("status") != "NEW_TEXT_REVIEW_REQUIRED"
        or attempt.get("document_id") != document_id
        or attempt.get("scope_sha256") != SOURCE_CANARY_SCOPE_SHA256
        or not isinstance(source_pdf, dict)
        or source_pdf.get("sha256") != document_id
        or type(source_pdf.get("page_count")) is not int
        or source_pdf.get("page_count") < 1
        or (expected_page_count is not None and source_pdf.get("page_count") != expected_page_count)
        or not isinstance(text, str)
        or len(text) != 5_353
        or _sha256(text.encode("utf-8")) != SOURCE_CANARY_TEXT_SHA256
        or text_record.get("sha256") != SOURCE_CANARY_TEXT_SHA256
        or not isinstance(page, dict)
        or page.get("page_number") != 1
        or page.get("original_dimensions_points") != {"height_points": 5001.0, "width_points": 600.0}
        or page.get("rendered_dimensions_pixels") != {"height_pixels": 13000, "width_pixels": 1560}
        or not isinstance(full_result, dict)
        or full_result.get("status") != "OCR_OK"
        or not isinstance(render, dict)
        or render.get("renderer_sha256") != EXPECTED_RENDERER_SHA256
        or render.get("render_scale_to") != MAX_REPAIR_RENDER_SCALE_TO
    ):
        raise BatchError("SOURCE_TEXT_CANARY_ATTEMPT_BINDING_MISMATCH")
    page_text = pdf_research.PageText(
        page_number=1,
        page_total=source_pdf["page_count"],
        text=text,
        status="OCR_OK",
        text_sha256=SOURCE_CANARY_TEXT_SHA256,
        extraction_method="macOS Vision single-variable 13000px canary",
    )
    return page_text, {
        "status": "REUSED_SOURCE_TEXT_CANARY",
        "attempt_path": str(path),
        "attempt_sha256": SOURCE_CANARY_ATTEMPT_SHA256,
        "text_sha256": SOURCE_CANARY_TEXT_SHA256,
        "reviewer_receipt_path": review["path"],
        "reviewer_receipt_sha256": review["sha256"],
        "reviewer": review["reviewer"],
        "accepted_markdown_boundary": review["accepted_markdown_boundary"],
        "original_dimensions_points": page["original_dimensions_points"],
        "rendered_dimensions_pixels": page["rendered_dimensions_pixels"],
        "render_scale_to": render["render_scale_to"],
        "renderer_sha256": render["renderer_sha256"],
        "rendered_image_sha256": render["render_image"]["sha256"],
    }


def _read_slice_canary_page(
    document_id: str,
    page_number: int,
    expected_page_count: int | None = None,
) -> tuple[pdf_research.PageText, dict[str, Any]] | None:
    if document_id != SECOND_CONTENT_FAIL_PDF_SHA256 or page_number != 1:
        return None
    paths = (SLICE_CANARY_ATTEMPT_PATH, SLICE_CANARY_MANIFEST_PATH, SLICE_CANARY_TEXT_PATH, SLICE_CANARY_REVIEW_DEFAULT)
    expected_hashes = (
        SLICE_CANARY_ATTEMPT_SHA256,
        SLICE_CANARY_MANIFEST_SHA256,
        SLICE_CANARY_TEXT_SHA256,
        SLICE_CANARY_REVIEW_SHA256,
    )
    values: list[Any] = []
    for path, expected in zip(paths, expected_hashes):
        if path.is_symlink() or not path.is_file() or _sha256_file(path) != expected:
            raise BatchError("SLICE_SOURCE_CANARY_SHA_MISMATCH")
        try:
            values.append(path.read_bytes())
        except OSError:
            raise BatchError("SLICE_SOURCE_CANARY_READ_FAILED") from None
    try:
        attempt, manifest, text_bytes, review = (
            json.loads(values[0].decode("utf-8")),
            json.loads(values[1].decode("utf-8")),
            values[2],
            json.loads(values[3].decode("utf-8")),
        )
        text = text_bytes.decode("utf-8")
    except (UnicodeError, json.JSONDecodeError):
        raise BatchError("SLICE_SOURCE_CANARY_INVALID") from None
    document = attempt.get("document") if isinstance(attempt, dict) else None
    helper = attempt.get("helper_identity") if isinstance(attempt, dict) else None
    result = attempt.get("result") if isinstance(attempt, dict) else None
    render = attempt.get("render") if isinstance(attempt, dict) else None
    segmentation = attempt.get("segmentation") if isinstance(attempt, dict) else None
    parts = manifest.get("parts") if isinstance(manifest, dict) else None
    boundary = review.get("accepted_markdown_boundary") if isinstance(review, dict) else None
    if (
        not isinstance(attempt, dict)
        or attempt.get("schema") != "v4.pdf_research_simple_batch.longscan_slice_ocr_canary.v1"
        or attempt.get("status") != "OCR_COMPLETE_SOURCE_REVIEW_PENDING"
        or not isinstance(document, dict)
        or document.get("pdf_sha256") != document_id
        or document.get("page_number") != 1
        or document.get("page_count") != 1
        or (expected_page_count is not None and expected_page_count != 1)
        or attempt.get("scope_sha256") != SLICE_CANARY_SCOPE_SHA256
        or not isinstance(helper, dict)
        or helper.get("prepare_crop_sha256") != EXPECTED_V3_PREPARE_OCR_SHA256
        or helper.get("common_sha256") != EXPECTED_V3_COMMON_SHA256
        or helper.get("renderer_sha256") != EXPECTED_RENDERER_SHA256
        or helper.get("renderer_version") != EXPECTED_RENDERER_VERSION
        or helper.get("vision_source_sha256") != EXPECTED_VISION_SOURCE_SHA256
        or helper.get("vision_config_sha256") != EXPECTED_VISION_CONFIG_SHA256
        or helper.get("slice_height") != 9_000
        or not isinstance(render, dict)
        or render.get("width_pixels") != 1_541
        or render.get("height_pixels") != 13_000
        or not isinstance(segmentation, dict)
        or segmentation.get("gap_free") is not True
        or segmentation.get("overlap") != 0
        or not isinstance(result, dict)
        or result.get("status") != "OCR_OK_SLICED"
        or result.get("part_text_order") != [1, 2]
        or result.get("sha256") != SLICE_CANARY_TEXT_SHA256
        or result.get("characters") != 5_202
        or not isinstance(manifest, dict)
        or manifest.get("source_pdf_sha256") != document_id
        or manifest.get("source_image_sha256") != render.get("sha256")
        or manifest.get("width") != 1_541
        or manifest.get("height") != 13_000
        or manifest.get("geometry_validation") != "PASS_GAP_FREE_CONTIGUOUS_NONOVERLAPPING"
        or not isinstance(parts, list)
        or [(row.get("part"), row.get("top"), row.get("bottom")) for row in parts if isinstance(row, dict)] != [(1, 0, 9_000), (2, 9_000, 13_000)]
        or not isinstance(review, dict)
        or review.get("schema") != SOURCE_CANARY_REVIEW_SCHEMA
        or review.get("status") != "SOURCE_CONTENT_PASS"
        or review.get("pdf_sha256") != document_id
        or review.get("scope_sha256") != SLICE_SOURCE_REVIEW_SCOPE_SHA256
        or not isinstance(review.get("reviewer"), str)
        or not review["reviewer"].strip()
        or not isinstance(boundary, dict)
        or not isinstance(boundary.get("adequate_for"), str)
        or not isinstance(boundary.get("can_report_from_text"), list)
        or not isinstance(boundary.get("uncertainties_to_preserve"), list)
        or not isinstance(boundary.get("exclude_or_bound"), list)
        or _sha256(text_bytes) != SLICE_CANARY_TEXT_SHA256
        or len(text) != 5_202
    ):
        raise BatchError("SLICE_SOURCE_CANARY_BINDING_MISMATCH")
    page_text = pdf_research.PageText(
        page_number=1,
        page_total=1,
        text=text,
        status="OCR_OK",
        text_sha256=SLICE_CANARY_TEXT_SHA256,
        extraction_method="reviewed V3 sliced Vision OCR canary",
    )
    return page_text, {
        "status": "REUSED_SOURCE_TEXT_CANARY",
        "attempt_path": str(paths[0]),
        "attempt_sha256": SLICE_CANARY_ATTEMPT_SHA256,
        "slice_manifest_sha256": SLICE_CANARY_MANIFEST_SHA256,
        "text_sha256": SLICE_CANARY_TEXT_SHA256,
        "reviewer_receipt_path": str(paths[3]),
        "reviewer_receipt_sha256": SLICE_CANARY_REVIEW_SHA256,
        "reviewer": review["reviewer"],
        "accepted_markdown_boundary": boundary,
        "rendered_image_sha256": render["sha256"],
        "slice_geometry": [{"part": row["part"], "top": row["top"], "bottom": row["bottom"]} for row in parts],
    }


def _page_geometry(pdf_path: Path, expected_page_count: int, pdf_sha256: str) -> list[dict[str, float]]:
    helper = pdf_research._pinned_pdf_pages_helper()
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        raw = pdf_path.read_bytes()
        if _sha256(raw) != pdf_sha256:
            raise BatchError("PAGE_GEOMETRY_PDF_SHA_MISMATCH")
        pypdf = helper.pinned_pypdf()
        reader = pypdf.PdfReader(BytesIO(raw), strict=False)
        if len(reader.pages) != expected_page_count:
            raise BatchError("PAGE_GEOMETRY_PAGE_COUNT_MISMATCH")
        result: list[dict[str, float]] = []
        for page in reader.pages:
            box = page.mediabox
            width = float(box.width)
            height = float(box.height)
            user_unit = float(page.get("/UserUnit", 1) or 1)
            rotation = int(page.get("/Rotate", 0) or 0) % 360
            if not math.isfinite(user_unit) or user_unit <= 0:
                raise BatchError("PAGE_GEOMETRY_UNSUPPORTED")
            width *= user_unit
            height *= user_unit
            if rotation in {90, 270}:
                width, height = height, width
            if not (math.isfinite(width) and math.isfinite(height) and width > 0 and height > 0):
                raise BatchError("PAGE_GEOMETRY_UNSUPPORTED")
            result.append({"width_points": width, "height_points": height, "rotation_degrees": float(rotation)})
        return result
    except BatchError:
        raise
    except Exception as exc:
        raise BatchError(f"PAGE_GEOMETRY_UNSUPPORTED:{type(exc).__name__}") from None
    finally:
        sys.dont_write_bytecode = previous


def _png_dimensions(path: Path) -> tuple[int, int]:
    with path.open("rb") as stream:
        header = stream.read(24)
    if len(header) < 24 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        raise BatchError("REPAIR_RENDER_NOT_PNG")
    return int.from_bytes(header[16:20], "big"), int.from_bytes(header[20:24], "big")


def _perform_page_ocr(pdf_path: Path, page_number: int, render_scale_to: int) -> tuple[str, dict[str, Any]]:
    import importlib

    ingestion_path = Path(__file__).resolve().parents[1] / "infrastructure/zsxq_pdf_ingestion.py"
    if ingestion_path.is_symlink() or _sha256_file(ingestion_path) != EXPECTED_PDF_INGESTION_SHA256:
        raise BatchError("PINNED_PDF_INGESTION_SHA_MISMATCH")
    previous_bytecode = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        ingestion = importlib.import_module("infrastructure.zsxq_pdf_ingestion")
        renderer_path = Path(ingestion.DEFAULT_PDFTOPPM)
        if (
            not renderer_path.is_file()
            or _sha256_file(renderer_path) != EXPECTED_RENDERER_SHA256
            or ingestion._renderer_version(renderer_path) != EXPECTED_RENDERER_VERSION
        ):
            raise BatchError("PINNED_PDF_RENDERER_MISMATCH")
        vision, vision_sha, config_sha = ingestion._load_vision_module()
        if (
            vision_sha != EXPECTED_VISION_SOURCE_SHA256
            or config_sha != EXPECTED_VISION_CONFIG_SHA256
            or getattr(vision, "OCR_TIMEOUT_SECONDS", None) != MAX_REPAIR_VISION_SECONDS
        ):
            raise BatchError("PINNED_VISION_HELPER_MISMATCH")
        scripts_root = V3_OCR_SCRIPTS_ROOT
        prepare_path = V3_PREPARE_OCR_PATH
        common_path = V3_COMMON_PATH
        if (
            prepare_path.is_symlink()
            or common_path.is_symlink()
            or _sha256_file(prepare_path) != EXPECTED_V3_PREPARE_OCR_SHA256
            or _sha256_file(common_path) != EXPECTED_V3_COMMON_SHA256
        ):
            raise BatchError("PINNED_V3_SLICE_HELPER_MISMATCH")
        with tempfile.TemporaryDirectory(prefix="pdf_batch_repair_") as temporary:
            temp_root = Path(temporary)
            previous_scale = ingestion.RENDER_SCALE_TO
            ingestion.RENDER_SCALE_TO = render_scale_to
            try:
                image_path = ingestion._render_pdf_page(pdf_path, page_number, temp_root, pdftoppm=renderer_path)
            finally:
                ingestion.RENDER_SCALE_TO = previous_scale
            image_bytes = image_path.stat().st_size
            if image_bytes <= 0 or image_bytes > MAX_REPAIR_IMAGE_BYTES:
                raise BatchError("REPAIR_RENDER_IMAGE_SIZE_INVALID")
            width_pixels, height_pixels = _png_dimensions(image_path)
            if width_pixels > 10_000:
                raise BatchError("REPAIR_HORIZONTAL_SLICING_UNSUPPORTED")
            if height_pixels > 18_000:
                raise BatchError("REPAIR_SLICE_COUNT_EXCEEDED")
            previous_path = list(sys.path)
            sys.path.insert(0, str(scripts_root))
            try:
                common = importlib.import_module("wechat_common")
                prepare = importlib.import_module("wechat_prepare_ocr")
            finally:
                sys.path[:] = previous_path
            if (
                Path(common.__file__).resolve() != common_path.resolve()
                or Path(prepare.__file__).resolve() != prepare_path.resolve()
                or _sha256_file(Path(common.__file__)) != EXPECTED_V3_COMMON_SHA256
                or _sha256_file(Path(prepare.__file__)) != EXPECTED_V3_PREPARE_OCR_SHA256
            ):
                raise BatchError("PINNED_V3_SLICE_HELPER_MISMATCH")
            geometry = {"width": width_pixels, "height": height_pixels, "sliced": height_pixels > 10_000, "parts": []}
            if geometry["sliced"]:
                geometry["parts"] = [
                    {
                        "part": part_number,
                        "top": top,
                        "bottom": min(top + 9_000, height_pixels),
                        "width": width_pixels,
                        "height": min(top + 9_000, height_pixels) - top,
                    }
                    for part_number, top in enumerate(range(0, height_pixels, 9_000), start=1)
                ]
            try:
                common.validate_slice_geometry(geometry)
            except (ValueError, TypeError, KeyError):
                raise BatchError("REPAIR_SLICE_GEOMETRY_INVALID") from None
            if len(geometry["parts"]) > 2:
                raise BatchError("REPAIR_SLICE_COUNT_EXCEEDED")
            executable = vision._compile_vision_helper(temp_root)
            intervals = geometry["parts"] or [{"part": 1, "top": 0, "bottom": height_pixels, "width": width_pixels, "height": height_pixels}]
            page_texts: list[str] = []
            slice_provenance: list[dict[str, Any]] = []
            aggregate_started = time.monotonic()
            for part in intervals:
                part_path = image_path
                if geometry["sliced"]:
                    part_path = temp_root / f"page-{page_number:04d}-part-{part['part']:02d}.png"
                    prepare._crop_image(
                        image_path,
                        part_path,
                        width=width_pixels,
                        top=part["top"],
                        height=part["height"],
                    )
                crop_width, crop_height = prepare._image_size(part_path)
                if (crop_width, crop_height) != (part["width"], part["height"]):
                    raise BatchError("REPAIR_SLICE_DIMENSIONS_MISMATCH")
                call_started = time.monotonic()
                ocr_result = vision._vision_ocr(executable, part_path)
                call_elapsed = time.monotonic() - call_started
                if time.monotonic() - aggregate_started > MAX_REPAIR_VISION_AGGREGATE_SECONDS:
                    raise BatchError("REPAIR_VISION_AGGREGATE_TIMEOUT")
                if not isinstance(ocr_result, Mapping) or ocr_result.get("status") != "OCR_OK":
                    raise BatchError("REPAIR_VISION_FAILED")
                part_text = ocr_result.get("text")
                if not isinstance(part_text, str) or not part_text.strip():
                    raise BatchError("REPAIR_VISION_TEXT_EMPTY")
                page_texts.append(part_text)
                slice_provenance.append(
                    {
                        "part": part["part"],
                        "top": part["top"],
                        "bottom": part["bottom"],
                        "width_pixels": crop_width,
                        "height_pixels": crop_height,
                        "crop_sha256": _sha256_file(part_path),
                        "text_sha256": _sha256(part_text.encode("utf-8")),
                        "text_characters": len(part_text),
                        "elapsed_seconds": call_elapsed,
                    }
                )
            text = "\n".join(page_texts)
            aggregate_elapsed = time.monotonic() - aggregate_started
            provenance = {
                "method": "existing_pdf_ingestion_renderer_and_macos_vision_leaf",
                "pdf_sha256": pdf_research._sha256_path(pdf_path),
                "page_number": page_number,
                "source_text_sha256": _sha256(text.encode("utf-8")),
                "source_text_characters": len(text),
                "renderer_path": str(renderer_path),
                "renderer_sha256": EXPECTED_RENDERER_SHA256,
                "renderer_version": EXPECTED_RENDERER_VERSION,
                "vision_source_sha256": vision_sha,
                "vision_config_sha256": config_sha,
                "render_scale_to": render_scale_to,
                "rendered_dimensions_pixels": {"width_pixels": width_pixels, "height_pixels": height_pixels},
                "rendered_image_sha256": _sha256_file(image_path),
                "rendered_image_bytes": image_bytes,
                "slice_helper_sha256": EXPECTED_V3_PREPARE_OCR_SHA256,
                "slice_geometry_helper_sha256": EXPECTED_V3_COMMON_SHA256,
                "slice_geometry_status": "GAP_FREE_CONTIGUOUS_NONOVERLAPPING",
                "slice_count": len(slice_provenance),
                "slice_provenance": slice_provenance,
                "vision_aggregate_elapsed_seconds": aggregate_elapsed,
                "vision_aggregate_timeout_seconds": MAX_REPAIR_VISION_AGGREGATE_SECONDS,
                "render_timeout_seconds": MAX_REPAIR_RENDER_SECONDS,
                "vision_timeout_seconds": MAX_REPAIR_VISION_SECONDS,
                "attempts_used_for_page": 1,
            }
            return text, provenance
    except BatchError:
        raise
    except Exception as exc:
        raise BatchError(f"REPAIR_VISION_FAILED:{type(exc).__name__}") from None
    finally:
        sys.dont_write_bytecode = previous_bytecode


def _is_ocr_page(page: pdf_research.PageText | None) -> bool:
    if page is None:
        return False
    method = str(page.extraction_method or "").casefold()
    return page.status == "OCR_OK" or "ocr" in method or "vision" in method


def _derived_page_path(state_root: Path, document_id: str, page_number: int) -> Path:
    return state_root / "documents" / document_id / "derived-ocr" / f"page-{page_number:04d}.json"


def _read_derived_page(
    state_root: Path,
    document_id: str,
    page_number: int,
    page_total: int,
    pdf_sha256: str,
) -> tuple[pdf_research.PageText, dict[str, Any]] | None:
    path = _derived_page_path(state_root, document_id, page_number)
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file():
        raise BatchError("DERIVED_OCR_INPUT_PATH_INVALID")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise BatchError("DERIVED_OCR_INPUT_INVALID") from None
    text = value.get("text") if isinstance(value, dict) else None
    provenance = value.get("provenance") if isinstance(value, dict) else None
    if (
        not isinstance(value, dict)
        or value.get("schema") != SOURCE_REPAIR_SCHEMA
        or value.get("pdf_sha256") != pdf_sha256
        or value.get("page_number") != page_number
        or value.get("page_count") != page_total
        or not isinstance(text, str)
        or not text.strip()
        or _sha256(text.encode("utf-8")) != value.get("text_sha256")
        or not isinstance(provenance, dict)
    ):
        raise BatchError("DERIVED_OCR_INPUT_BINDING_MISMATCH")
    return (
        pdf_research.PageText(page_number, page_total, text, "OCR_OK", value["text_sha256"], "derived OCR in isolated batch state"),
        {"status": "REUSED_DERIVED_OCR", "path": str(path), "sha256": _sha256_file(path), **provenance},
    )


def _cache_render_dimensions(candidate: Mapping[str, Any], page_number: int) -> tuple[int, int] | None:
    path_value = candidate.get("path")
    if not isinstance(path_value, str):
        return None
    try:
        path = Path(path_value)
        if path.is_symlink() or _sha256_file(path) != candidate.get("sha256"):
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    rows = value.get("pages") if isinstance(value, dict) else value
    if not isinstance(rows, list):
        return None
    row = next(
        (item for item in rows if isinstance(item, dict) and item.get("page_number") == page_number),
        rows[page_number - 1] if page_number <= len(rows) and isinstance(rows[page_number - 1], dict) else None,
    )
    if not isinstance(row, dict):
        return None
    dimensions = row.get("rendered_dimensions_pixels") or row.get("render_dimensions_pixels")
    if not isinstance(dimensions, dict):
        render = row.get("render_identity")
        image = render.get("render_image") if isinstance(render, dict) else None
        dimensions = image if isinstance(image, dict) else None
    if not isinstance(dimensions, dict):
        return None
    width = dimensions.get("width_pixels", dimensions.get("width"))
    height = dimensions.get("height_pixels", dimensions.get("height"))
    if type(width) is not int or type(height) is not int or width < 1 or height < 1:
        return None
    return width, height


def _source_repair_qualification(source: Mapping[str, Any]) -> dict[str, Any]:
    accepted: list[dict[str, Any]] = []
    general_ocr_pages: list[int] = []
    for row in source.get("page_extraction_sources", []):
        if not isinstance(row, dict):
            continue
        page_number = row.get("page_number")
        canary = row.get("source_text_canary")
        if isinstance(canary, dict):
            accepted.append({"page_number": page_number, **canary})
        elif row.get("selected") in {"REUSED_DERIVED_OCR", "RENDERED_DERIVED_OCR"} or (
            row.get("selected") in {"EXISTING_CACHE", "EXISTING_CACHE_QUALITY_REPLACEMENT"}
            and (
                row.get("cache_status") == "OCR_OK"
                or "ocr" in str(row.get("extraction_method", "")).casefold()
                or "vision" in str(row.get("extraction_method", "")).casefold()
            )
        ):
            general_ocr_pages.append(page_number)
    return {
        "semantic_source_acceptance_status": "SOURCE_REVIEW_PENDING",
        "reviewed_canary_pages": accepted,
        "unreviewed_ocr_pages": general_ocr_pages,
        "generic_ocr_limitations": (
            "For unreviewed OCR pages, names, codes, table rows and exact numbers may be mistranscribed; "
            "the limitation concerns extracted text quality and does not imply damage or unreadability of the original PDF."
            if general_ocr_pages
            else None
        ),
    }


def _discover_native_pages(pdf_path: Path, pdf_sha: str) -> tuple[list[pdf_research.PageText] | None, str]:
    """Use only the already pinned native helper when inventory has no page count/cache."""
    if pdf_path.stat().st_size > pdf_research.PDF_PAGES_MAX_BYTES:
        return None, "NATIVE_EXTRACTION_SIZE_LIMIT"
    helper = pdf_research._pinned_pdf_pages_helper()
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        raw = pdf_path.read_bytes()
        extracted = helper.extract_pdf_pages(
            raw,
            max_pages=500,
            max_bytes=pdf_research.PDF_PAGES_MAX_BYTES,
        )
    except Exception as exc:
        return None, f"NATIVE_EXTRACTION_FAILED:{type(exc).__name__}"
    finally:
        sys.dont_write_bytecode = previous
    if extracted.get("pdf_sha256") != pdf_sha:
        raise BatchError("NATIVE_EXTRACTION_PDF_SHA_MISMATCH")
    page_count = extracted.get("page_count")
    rows = extracted.get("pages")
    if type(page_count) is not int or not isinstance(rows, list) or len(rows) != page_count:
        raise BatchError("NATIVE_EXTRACTION_PAGE_COUNT_INVALID")
    pages: list[pdf_research.PageText] = []
    for index, row in enumerate(rows, start=1):
        text = row.get("text") if isinstance(row, dict) and isinstance(row.get("text"), str) else ""
        status = "NATIVE_TEXT" if text.strip() and row.get("status") == "COMPLETE" else "BLANK"
        pages.append(
            pdf_research.PageText(
                page_number=index,
                page_total=page_count,
                text=text,
                status=status,
                text_sha256=_sha256(text.encode("utf-8")),
                extraction_method="pypdf-6.10.0-native",
            )
        )
    return pages, "COMPLETE" if extracted.get("complete") is True else "PARTIAL_OR_BLANK"


def _load_pages(
    document: Mapping[str, Any],
    *,
    state_root: Path | None = None,
    repair_budget: dict[str, int] | None = None,
    preparation_mode: bool = False,
    resume_pages: Mapping[int, tuple[pdf_research.PageText, Mapping[str, Any]]] | None = None,
    page_callback: Callable[[pdf_research.PageText, Mapping[str, Any]], None] | None = None,
    before_page: Callable[[], None] | None = None,
) -> tuple[list[pdf_research.PageText], dict[str, Any]]:
    pdf_path = pdf_research._validate_pdf_path(Path(str(document.get("local_pdf_path", ""))))
    before = pdf_path.stat()
    pdf_sha = pdf_research._sha256_path(pdf_path)
    after = pdf_path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise BatchError("SOURCE_PDF_CHANGED_DURING_HASH")
    if pdf_sha != document.get("pdf_sha256") or before.st_size != document.get("pdf_bytes"):
        raise BatchError("SOURCE_PDF_BINDING_MISMATCH")
    page_count = _candidate_page_count(document)

    cache_options = sorted(
        (item for item in document.get("cache_candidates", []) if isinstance(item, dict)),
        key=lambda item: (0 if item.get("coverage_status") == "COMPLETE" else 1),
    )
    cached_pages: list[pdf_research.PageText] | None = None
    cache_info: dict[str, Any] | None = None
    selected_cache_candidate: Mapping[str, Any] | None = None
    cache_errors: list[str] = []
    for candidate in cache_options:
        cache_sha = candidate.get("sha256")
        if (
            candidate.get("page_count") != page_count
            or not isinstance(cache_sha, str)
            or not re.fullmatch(r"[0-9a-f]{64}", cache_sha)
            or not isinstance(candidate.get("path"), str)
        ):
            cache_errors.append("CACHE_CANDIDATE_IDENTITY_INVALID")
            continue
        try:
            cached_pages, cache_info = pdf_research.load_page_cache(
                pages_cache_path=Path(candidate["path"]),
                pages_cache_sha256=cache_sha,
                pages_cache_pdf_sha256=None,
                pdf_sha256=pdf_sha,
                page_count=page_count,
            )
            selected_cache_candidate = candidate
            break
        except Exception as exc:
            cache_errors.append(str(getattr(exc, "code", None) or type(exc).__name__)[:96])

    if page_count is None:
        native_pages, native_status = _discover_native_pages(pdf_path, pdf_sha)
        if native_pages:
            page_count = len(native_pages)
        else:
            raise BatchError("PAGE_COUNT_UNAVAILABLE")
    else:
        native_pages, native_status = pdf_research.extract_native_pdf_pages(pdf_path, page_count)
    native_quality = pdf_text_preparation.assess_document_pages(native_pages or [])
    cached_quality = {
        page.page_number: pdf_text_preparation.assess_text_quality(page.text)
        for page in (cached_pages or [])
    }
    cache_replacements: set[int] = set()
    suspicious_pages: list[int] = []
    for page_number in range(1, page_count + 1):
        native = native_pages[page_number - 1] if native_pages and page_number <= len(native_pages) else None
        cached = cached_pages[page_number - 1] if cached_pages and page_number <= len(cached_pages) else None
        native_assessment = native_quality.get(page_number, pdf_text_preparation.assess_text_quality(""))
        cached_assessment = cached_quality.get(page_number, {})
        cache_usable = (
            cached is not None
            and bool(cached.text.strip())
            and cached.status in {"COMPLETE", "NATIVE_TEXT", "OCR_OK"}
            and cached_assessment.get("status") == "PASS"
        )
        if cache_usable and pdf_text_preparation.cached_text_replaces_native(
            native.text if native is not None else "",
            cached.text,
            native_assessment=native_assessment,
            cached_assessment=cached_assessment,
        ):
            cache_replacements.add(page_number)
        elif native is None or native.status != "NATIVE_TEXT" or native_assessment.get("needs_context"):
            suspicious_pages.append(page_number)
    try:
        image_presence = pdf_text_preparation.inspect_page_images(
            pdf_path,
            pdf_sha256=pdf_sha,
            page_count=page_count,
            # Even a good native layer can omit an image/table/chart body.
            page_numbers=[page for page in range(1, page_count + 1) if page not in cache_replacements],
        )
    except pdf_text_preparation.PreparationError as exc:
        if exc.code in pdf_text_preparation.FATAL_SOURCE_CODES:
            raise BatchError(exc.code) from None
        image_presence = {page_number: None for page_number in range(1, page_count + 1) if page_number not in cache_replacements}
    try:
        geometries = _page_geometry(pdf_path, page_count, pdf_sha)
        geometry_error = None
    except BatchError as exc:
        geometries = []
        geometry_error = exc.code
    budget = repair_budget if repair_budget is not None else {"remaining": MAX_REPAIR_PAGES_PER_TICK}
    canary_review: dict[str, Any] | None = None
    canary_review_checked = False
    selected: list[pdf_research.PageText] = []
    page_sources: list[dict[str, Any]] = []
    repair_states: list[str] = []
    ocr_invoked = False
    new_ocr_attempts = 0
    for index in range(page_count):
        native = native_pages[index] if native_pages and index < len(native_pages) else None
        cached = cached_pages[index] if cached_pages and index < len(cached_pages) else None
        page_number = index + 1
        geometry = geometries[index] if index < len(geometries) else None
        row: dict[str, Any] = {"page_number": page_number}
        if before_page is not None:
            before_page()
        if resume_pages is not None and page_number in resume_pages:
            resumed_page, resumed_row = resume_pages[page_number]
            if resumed_page.page_total != page_count or resumed_page.page_number != page_number:
                raise BatchError("PREPARATION_RESUME_PAGE_BINDING_MISMATCH")
            selected.append(resumed_page)
            page_sources.append(dict(resumed_row))
            selected_kind = str(resumed_row.get("selected", ""))
            if selected_kind in {"RENDERED_DERIVED_OCR", "REUSED_DERIVED_OCR", "EXISTING_CACHE_QUALITY_REPLACEMENT"}:
                repair_states.append("COMPLETE")
            elif selected_kind.startswith("SOURCE_REPAIR_PENDING"):
                repair_states.append("PENDING_RESUME")
            continue
        if geometry is not None:
            width_points = geometry["width_points"]
            height_points = geometry["height_points"]
            long_edge_points = max(width_points, height_points)
            baseline_density = BASELINE_RENDER_SCALE_TO / long_edge_points
            row.update(
                {
                    "original_dimensions_points": geometry,
                    "baseline_render_scale_to": BASELINE_RENDER_SCALE_TO,
                    "baseline_render_density_pixels_per_point": baseline_density,
                }
            )
        else:
            baseline_density = None
            row["page_geometry_status"] = geometry_error or "CANNOT_CONFIRM"
        native_assessment = native_quality.get(page_number, pdf_text_preparation.assess_text_quality(""))
        cached_assessment = cached_quality.get(page_number, {})
        image_status = image_presence.get(page_number)
        cache_render = (
            _cache_render_dimensions(selected_cache_candidate, page_number)
            if cached_pages and selected_cache_candidate is not None
            else None
        )
        cache_density = None
        if geometry is not None and cache_render is not None:
            cache_density = min(
                cache_render[0] / geometry["width_points"],
                cache_render[1] / geometry["height_points"],
            )
            row["cache_render_dimensions_pixels"] = {"width_pixels": cache_render[0], "height_pixels": cache_render[1]}
            row["cache_render_density_pixels_per_point"] = cache_density
        metadata_proves_adequate = cache_density is not None and cache_density >= 1.0
        if page_number in cache_replacements and cached is not None:
            selected.append(cached)
            row.update(
                {
                    "selected": "EXISTING_CACHE_QUALITY_REPLACEMENT",
                    "cache_status": cached.status,
                    "extraction_method": cached.extraction_method or "UNSPECIFIED",
                    "native_text_quality": dict(native_assessment),
                    "cache_text_quality": dict(cached_assessment),
                    "quality_replacement_reason": "CACHE_HAS_DISTINCT_INFORMATION_WHERE_NATIVE_TEXT_IS_SUSPICIOUS",
                    "cache_render_metadata_verified_adequate": metadata_proves_adequate or baseline_density is not None and baseline_density >= 1.0,
                    "preparation_gate": "READY",
                }
            )
            if _is_ocr_page(cached):
                row["semantic_source_review_status"] = "SOURCE_REVIEW_PENDING"
        elif native is not None and native.status == "NATIVE_TEXT" and image_status is False and (
            not native_assessment.get("needs_context")
            or image_status is False and not native_assessment.get("repeated_short_page") and not native_assessment.get("repeated_contact_page")
        ):
            selected.append(native)
            row.update(
                {
                    "selected": "PINNED_PYPDF_NATIVE",
                    "native_text_quality": dict(native_assessment),
                    "preparation_gate": "READY",
                    "preparation_quality_reason": "SPARSE_NATIVE_TEXT_NO_IMAGE_EVIDENCE" if native_assessment.get("needs_context") else "NATIVE_TEXT_PASSES_QUALITY_CHECK",
                }
            )
        elif native is not None and native.status == "NATIVE_TEXT" and image_status is None:
            selected.append(pdf_research.PageText(page_number, page_count, "", "TEXT_UNAVAILABLE", _sha256(b""), None))
            row.update(
                {
                    "selected": "PAGE_IMAGE_IDENTITY_UNKNOWN",
                    "native_text_quality": dict(native_assessment),
                    "preparation_gate": "QUARANTINED",
                    "preparation_failure_code": "PAGE_IMAGE_IDENTITY_UNKNOWN",
                }
            )
        elif native is not None and native.status == "NATIVE_TEXT" and image_status is False:
            selected.append(pdf_research.PageText(page_number, page_count, "", "TEXT_UNAVAILABLE", _sha256(b""), None))
            row.update(
                {
                    "selected": "REPEATED_SHORT_TEXT_WITHOUT_BODY",
                    "native_text_quality": dict(native_assessment),
                    "preparation_gate": "QUARANTINED",
                    "preparation_failure_code": "REPEATED_SHORT_TEXT_WITHOUT_BODY",
                }
            )
        else:
            unknown_non_native_cache = (
                cached is not None
                and bool(cached.text.strip())
                and not (cached.status == "NATIVE_TEXT" or "pypdf" in str(cached.extraction_method or "").casefold())
            )
            low_resolution = (baseline_density is None and unknown_non_native_cache) or (
                baseline_density is not None and baseline_density < LOW_RENDER_DENSITY_PIXELS_PER_POINT and not metadata_proves_adequate
            )
            if image_status is True:
                low_resolution = True
            row["low_resolution_raster_suspected"] = low_resolution
            row["native_text_quality"] = dict(native_assessment)
            row["image_presence"] = image_status if page_number in image_presence else "NOT_INSPECTED"
            if low_resolution:
                repair_states.append("NEEDS_REPAIR")
                recovered: tuple[pdf_research.PageText, dict[str, Any]] | None = None
                if not preparation_mode and not canary_review_checked:
                    canary_review = _read_source_text_canary_review()
                    canary_review_checked = True
                if canary_review is not None and state_root is not None:
                    recovered = _read_derived_page(state_root, str(document["document_id"]), page_number, page_count, pdf_sha)
                if recovered is None:
                    recovered = _read_scale_canary_page(str(document["document_id"]), page_number, page_count)
                    if recovered is not None:
                        repair_provenance = dict(recovered[1])
                        row["selected"] = "REUSED_SOURCE_TEXT_CANARY"
                        row["source_text_canary"] = repair_provenance
                if recovered is None:
                    recovered = _read_slice_canary_page(str(document["document_id"]), page_number, page_count)
                    if recovered is not None:
                        repair_provenance = dict(recovered[1])
                        row["selected"] = "REUSED_SOURCE_TEXT_CANARY"
                        row["source_text_canary"] = repair_provenance
                    if recovered is None and canary_review is None and not preparation_mode:
                        repair_states[-1] = "PENDING_SOURCE_TEXT_CANARY_REVIEW"
                        row["selected"] = "SOURCE_REPAIR_PENDING_CANARY_REVIEW"
                    elif recovered is None and state_root is None:
                        repair_states[-1] = "PENDING_BATCH_STATE_ROOT"
                        row["selected"] = "SOURCE_REPAIR_PENDING_STATE_ROOT"
                    elif recovered is None:
                        failed_path = state_root / "documents" / str(document["document_id"]) / "derived-ocr" / f"page-{page_number:04d}.failed.json"
                        if failed_path.is_file():
                            repair_states[-1] = "FAILED_PREVIOUS_ATTEMPT"
                            row["selected"] = "SOURCE_REPAIR_FAILED_NO_RETRY"
                        elif geometry is None:
                            failed_value = {
                                "schema": SOURCE_REPAIR_SCHEMA,
                                "pdf_sha256": pdf_sha,
                                "page_number": page_number,
                                "status": "SOURCE_REPAIR_UNSUPPORTED_GEOMETRY",
                                "failure_code": geometry_error or "PAGE_GEOMETRY_UNAVAILABLE",
                                "attempts_used_for_page": 0,
                            }
                            _write_immutable(failed_path, _json_bytes(failed_value, newline=True), state_root)
                            repair_states[-1] = "FAILED_UNSUPPORTED_GEOMETRY"
                            row["selected"] = "SOURCE_REPAIR_UNSUPPORTED_GEOMETRY"
                            row["failure_code"] = failed_value["failure_code"]
                        elif budget.get("remaining", 0) <= 0:
                            repair_states[-1] = "PENDING_TICK_BUDGET"
                            row["selected"] = "SOURCE_REPAIR_PENDING_TICK_BUDGET"
                        else:
                            long_edge = max(geometry["width_points"], geometry["height_points"]) if geometry else 0
                            render_scale_to = min(
                                MAX_REPAIR_RENDER_SCALE_TO,
                                max(BASELINE_RENDER_SCALE_TO, math.ceil(long_edge * TARGET_RENDER_PIXELS_PER_POINT)),
                            )
                            budget["remaining"] -= 1
                            new_ocr_attempts += 1
                            ocr_invoked = True
                            try:
                                text, provenance = _perform_page_ocr(pdf_path, page_number, render_scale_to)
                                if provenance.get("pdf_sha256") != pdf_sha or provenance.get("page_number") != page_number:
                                    raise BatchError("REPAIR_OCR_SOURCE_BINDING_MISMATCH")
                                rendered = provenance.get("rendered_dimensions_pixels")
                                if not isinstance(rendered, dict):
                                    raise BatchError("REPAIR_RENDER_DIMENSIONS_UNAVAILABLE")
                                raster_density = min(
                                    rendered.get("width_pixels", 0) / geometry["width_points"],
                                    rendered.get("height_pixels", 0) / geometry["height_points"],
                                )
                                if raster_density < LOW_RENDER_DENSITY_PIXELS_PER_POINT:
                                    raise BatchError("REPAIR_RENDER_DENSITY_STILL_LOW")
                                provenance.update(
                                    {
                                        "original_dimensions_points": geometry,
                                        "baseline_render_density_pixels_per_point": baseline_density,
                                        "repair_render_density_pixels_per_point": raster_density,
                                        "repair_trigger": "BASELINE_RENDER_DENSITY_BELOW_1_PIXEL_PER_POINT",
                                        "semantic_source_review_status": "SOURCE_REVIEW_PENDING",
                                    }
                                )
                                derived_value = {
                                    "schema": SOURCE_REPAIR_SCHEMA,
                                    "pdf_sha256": pdf_sha,
                                    "page_number": page_number,
                                    "page_count": page_count,
                                    "text": text,
                                    "text_sha256": _sha256(text.encode("utf-8")),
                                    "provenance": provenance,
                                }
                                derived_path = _derived_page_path(state_root, str(document["document_id"]), page_number)
                                derived_sha = _write_immutable(derived_path, _json_bytes(derived_value, newline=True), state_root)
                                recovered = (
                                    pdf_research.PageText(page_number, page_count, text, "OCR_OK", derived_value["text_sha256"], "derived OCR in isolated batch state"),
                                    {"status": "RENDERED_DERIVED_OCR", "path": str(derived_path), "sha256": derived_sha, **provenance},
                                )
                            except Exception as exc:
                                code = str(getattr(exc, "code", None) or type(exc).__name__)[:96]
                                failed_value = {
                                    "schema": SOURCE_REPAIR_SCHEMA,
                                    "pdf_sha256": pdf_sha,
                                    "page_number": page_number,
                                    "status": "SOURCE_REPAIR_FAILED_NO_RETRY",
                                    "failure_code": code,
                                    "attempts_used_for_page": 1,
                                    "original_dimensions_points": geometry,
                                    "baseline_render_density_pixels_per_point": baseline_density,
                                }
                                _write_immutable(failed_path, _json_bytes(failed_value, newline=True), state_root)
                                repair_states[-1] = "FAILED_SINGLE_ATTEMPT"
                                row["selected"] = "SOURCE_REPAIR_FAILED_NO_RETRY"
                                row["failure_code"] = code
                if recovered is not None:
                    selected.append(recovered[0])
                    if row.get("selected") != "REUSED_SOURCE_TEXT_CANARY":
                        row["selected"] = recovered[1].get("status")
                        row["repair_provenance"] = dict(recovered[1])
                    if recovered[1].get("status") != "REUSED_SOURCE_TEXT_CANARY":
                        general_ocr = True
                    else:
                        general_ocr = False
                    if general_ocr:
                        row["semantic_source_review_status"] = "SOURCE_REVIEW_PENDING"
                else:
                    selected.append(
                        pdf_research.PageText(page_number, page_count, "", "TEXT_UNAVAILABLE", _sha256(b""), None)
                    )
            elif cached is not None and cached.text.strip() and cached.status in {"COMPLETE", "NATIVE_TEXT", "OCR_OK"}:
                selected.append(cached)
                row.update(
                    {
                        "selected": "EXISTING_CACHE",
                        "cache_status": cached.status,
                        "extraction_method": cached.extraction_method or "UNSPECIFIED",
                        "cache_render_metadata_verified_adequate": metadata_proves_adequate or baseline_density is not None and baseline_density >= 1.0,
                        "preparation_gate": "READY" if cached_assessment.get("status") == "PASS" else "QUARANTINED",
                        "preparation_quality": dict(cached_assessment),
                    }
                )
                if _is_ocr_page(cached):
                    row["semantic_source_review_status"] = "SOURCE_REVIEW_PENDING"
            elif native is not None:
                selected.append(native)
                row["selected"] = "PINNED_PYPDF_NATIVE_EMPTY_OR_FAILED"
                row["preparation_gate"] = "QUARANTINED"
                row["preparation_failure_code"] = "PAGE_NATIVE_TEXT_EMPTY_OR_FAILED"
            elif cached is not None:
                selected.append(cached)
                row["selected"] = "EXISTING_CACHE_EMPTY"
                row["preparation_gate"] = "QUARANTINED"
                row["preparation_failure_code"] = "PAGE_CACHE_TEXT_EMPTY"
            else:
                selected.append(
                    pdf_research.PageText(
                        page_number=page_number,
                        page_total=page_count,
                        text="",
                        status="TEXT_UNAVAILABLE",
                        text_sha256=_sha256(b""),
                        extraction_method=None,
                    )
                )
                row["selected"] = "TEXT_UNAVAILABLE"
                row["preparation_gate"] = "QUARANTINED"
                row["preparation_failure_code"] = "PAGE_TEXT_UNAVAILABLE"
        chosen_page = selected[-1]
        quality = pdf_text_preparation.assess_text_quality(chosen_page.text)
        row.setdefault("preparation_quality", dict(quality))
        row.setdefault("page_status", chosen_page.status)
        if row.get("preparation_gate") not in {"READY", "QUARANTINED"}:
            sparse_native_without_image = (
                chosen_page.text.strip()
                and chosen_page.status in {"NATIVE_TEXT", "COMPLETE"}
                and image_status is False
                and not native_assessment.get("repeated_short_page")
                and not native_assessment.get("repeated_contact_page")
            )
            if chosen_page.text.strip() and chosen_page.status in {"NATIVE_TEXT", "COMPLETE", "OCR_OK"} and (
                quality.get("status") == "PASS" or sparse_native_without_image
            ):
                row["preparation_gate"] = "READY"
            else:
                row["preparation_gate"] = "QUARANTINED"
                row.setdefault("preparation_failure_code", quality.get("reason") or "PAGE_QUALITY_UNRESOLVED")
        if page_callback is not None and row.get("selected", "").startswith("SOURCE_REPAIR_PENDING") is False:
            page_callback(chosen_page, row)
        page_sources.append(row)
    if len(selected) != page_count:
        raise BatchError("SELECTED_PAGE_COUNT_MISMATCH")
    complete = all(page.text.strip() and page.status in {"COMPLETE", "NATIVE_TEXT", "OCR_OK"} for page in selected)
    all_nonempty = all(bool(page.text.strip()) for page in selected)
    any_nonempty = any(bool(page.text.strip()) for page in selected)
    has_ocr = any(
        row.get("selected") in {"EXISTING_CACHE", "EXISTING_CACHE_QUALITY_REPLACEMENT"}
        and (row.get("cache_status") == "OCR_OK" or "ocr" in str(row.get("extraction_method", "")).casefold())
        for row in page_sources
    )
    repair_status = (
        "FAILED_SINGLE_ATTEMPT"
        if "FAILED_SINGLE_ATTEMPT" in repair_states
        else "FAILED_UNSUPPORTED_GEOMETRY"
        if "FAILED_UNSUPPORTED_GEOMETRY" in repair_states
        else "FAILED_PREVIOUS_ATTEMPT"
        if "FAILED_PREVIOUS_ATTEMPT" in repair_states
        else "PENDING"
        if any(status.startswith("PENDING") for status in repair_states)
        else "COMPLETE"
        if repair_states
        else "NOT_REQUIRED"
    )
    source = {
        "pdf_path": str(pdf_path),
        "pdf_sha256": pdf_sha,
        "pdf_bytes": before.st_size,
        "pdf_mtime_ns": before.st_mtime_ns,
        "page_count": page_count,
        "source_page_text_sha256": _sha256("".join(page.text for page in selected).encode("utf-8")),
        "page_extraction_status": "COMPLETE" if complete else "PARTIAL" if any_nonempty else "TEXT_UNAVAILABLE",
        "all_pages_nonempty": all_nonempty,
        "any_page_nonempty": any_nonempty,
        "selected_pages_complete": complete,
        "page_extraction_sources": page_sources,
        "source_repair_status": repair_status,
        "source_text_acceptance": _source_repair_qualification({"page_extraction_sources": page_sources}),
        "new_ocr_attempts_this_tick": new_ocr_attempts,
        "cache": cache_info or {"status": "UNAVAILABLE", "errors": cache_errors},
        "native_extraction_status": native_status,
        "cached_ocr_visual_quality_status": "CANNOT_CONFIRM_NOT_VISUALLY_REVIEWED" if has_ocr else "NOT_APPLICABLE_NO_SELECTED_OCR_CACHE",
        "ocr_invoked": ocr_invoked,
        "source_paths": list(document.get("source_paths", [])),
        "data_role": document.get("data_role") or "CANNOT_CONFIRM",
        "pit_status": document.get("pit_status") or "CANNOT_CONFIRM",
    }
    return selected, source


def _page_input_value(document: Mapping[str, Any], pages: Sequence[pdf_research.PageText], source: Mapping[str, Any]) -> dict[str, Any]:
    stable_source = dict(source)
    stable_source.pop("new_ocr_attempts_this_tick", None)
    stable_source.pop("ocr_invoked", None)
    stable_source.pop("pdf_mtime_ns", None)
    extraction_rows: list[dict[str, Any]] = []
    for source_row in source.get("page_extraction_sources", []):
        row = dict(source_row)
        if row.get("selected") in {"RENDERED_DERIVED_OCR", "REUSED_DERIVED_OCR"}:
            row["selected"] = "DERIVED_OCR"
            provenance = row.get("repair_provenance")
            if isinstance(provenance, dict):
                row["repair_provenance"] = {**provenance, "status": "DERIVED_OCR"}
        extraction_rows.append(row)
    stable_source["page_extraction_sources"] = extraction_rows
    return {
        "schema": "v4.pdf_research_simple_batch.page_input.v1",
        "document_id": document["document_id"],
        "pdf_sha256": document["pdf_sha256"],
        "manifest_sha256": document.get("_manifest_sha256"),
        "source": stable_source,
        "pages": [
            {
                "page_number": page.page_number,
                "page_total": page.page_total,
                "status": page.status,
                "extraction_method": page.extraction_method,
                "text_sha256": _sha256(page.text.encode("utf-8")),
                "text_characters": len(page.text),
                "text": page.text,
            }
            for page in pages
        ],
    }


def _assert_bound_tool_canary_page_input(
    document_id: str,
    continuation: Mapping[str, Any] | None,
    observed_page_input_sha256: str,
) -> None:
    entry = continuation.get("entry") if isinstance(continuation, Mapping) else None
    evidence = entry.get("tool_canary") if isinstance(entry, Mapping) else None
    if not isinstance(evidence, Mapping):
        return
    if (
        document_id != TOOL_CANARY_DOCUMENT_ID
        or evidence.get("page_input_path") != str(TOOL_CANARY_PAGE_INPUT_PATH)
        or evidence.get("page_input_sha256") != TOOL_CANARY_PAGE_INPUT_SHA256
        or observed_page_input_sha256 != TOOL_CANARY_PAGE_INPUT_SHA256
    ):
        raise BatchError("TOOL_CANARY_PAGE_INPUT_RECONSTRUCTION_MISMATCH")


def _request_envelope(messages: Sequence[Mapping[str, str]], schema: Mapping[str, Any] = RESPONSE_SCHEMA) -> bytes:
    return local_model.canonical_json(
        {
            "model": local_model.MODEL_ID,
            "messages": [dict(item) for item in messages],
            "temperature": local_model.REQUEST_TEMPERATURE,
            "enable_thinking": local_model.ENABLE_THINKING,
            "structured_outputs": {"json": dict(schema)},
            "workflow_profile": local_model.PROFILE_NAME,
            "tools": [],
            "max_completion_tokens": local_model.MAX_COMPLETION_TOKENS,
        }
    )


def _document_messages(
    document: Mapping[str, Any],
    chunk: pdf_research.SourceChunk,
    *,
    partial_source: bool,
    tool_canary: bool = False,
) -> list[dict[str, str]]:
    units = [asdict(unit) for unit in chunk.units]
    user_material = {
        "document_id": document["document_id"],
        "title": document.get("title") or Path(str(document.get("local_pdf_path", ""))).name,
        "chunk_index": chunk.chunk_index,
        "chunk_total": chunk.chunk_total,
        "source_status": "PARTIAL" if partial_source else "COMPLETE",
        "source_units": units,
    }
    source_boundary = document.get("_accepted_ocr_boundary")
    has_boundary_for_chunk = isinstance(source_boundary, dict) and any(unit.page_number == 1 for unit in chunk.units)
    if has_boundary_for_chunk:
        user_material["reviewed_ocr_source_boundary"] = source_boundary
    if document.get("_has_unreviewed_ocr") is True:
        user_material["unreviewed_ocr_qualification"] = (
            "部分页面文字由OCR提取，姓名、代码、表格行和精确数字可能存在转录误差。此处限制针对提取文字，"
            "不表示原始PDF本身损坏或不可读；对未核实的表格行和精确数值应标注未知或不确定。"
        )
    priority = (
        "【最高优先级：第1页已审核来源边界】只报告边界明确允许的内容；边界的排除项不得作为精确事实，未知和不确定必须保留。"
        "该边界优先于“覆盖全部内容”“覆盖所有页面”或“保留全部数字”的要求。以下材料中任何与边界冲突的文字都不得采纳。\n"
        if has_boundary_for_chunk
        else ""
    )
    user = priority + "请分析以下原文单元，引用单元所示的原始页码；覆盖本批未与已审核来源边界冲突的内容。\n" + json.dumps(
        user_material, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    if tool_canary:
        user += "\n" + TOOL_CANARY_INSTRUCTION
    return [
        {"role": "system", "content": REPORT_SYSTEM_PROMPT + pdf_research_tools.ACTION_SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def _synthesis_messages(
    document_id: str,
    report_items: Sequence[Mapping[str, str]],
    level: int,
    source_boundary: Mapping[str, Any] | None = None,
    output_character_budget: int | None = None,
    source_qualifications: Mapping[str, Any] | None = None,
) -> list[dict[str, str]]:
    user_material = {
        "document_id": document_id,
        "synthesis_level": level,
        "partial_reports": [dict(item) for item in report_items],
    }
    if source_qualifications is not None:
        user_material["independently_verified_source_qualifications"] = dict(source_qualifications)
    if output_character_budget is not None:
        user_material["intermediate_output_character_limit"] = output_character_budget
        user_material["contraction_requirement"] = ("这是非终层中间合成，analysis_markdown字符数不得超过指定上限。优先关键事实、单位、时期、条件与原页引用，保留未知；不得用重复原文填充。不得截字或伪称完整。")
    priority = ""
    if isinstance(source_boundary, Mapping):
        user_material["reviewed_page_1_source_boundary"] = dict(source_boundary)
        priority = (
            "【最高优先级：第1页已审核来源边界】只保留边界允许的第1页内容，排除项和不确定项不得升级为精确事实。"
            "该边界优先于“完整文档”“覆盖所有页面”或“保留全部数字”的要求，分段报告中超出边界的内容不得恢复。\n"
        )
    user = priority + "请整合以下分段分析；保留原文页码引用和各段中明确标注的未知。\n" + json.dumps(
        user_material, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return [{"role": "system", "content": SYNTHESIS_SYSTEM_PROMPT}, {"role": "user", "content": user}]


def _build_document_chunks(
    document_id: str,
    pages: Sequence[pdf_research.PageText],
    *,
    prompt_source: Mapping[str, Any] | None = None,
) -> list[pdf_research.SourceChunk]:
    chunks = pdf_research.build_source_chunks(document_id, pages)
    for chunk in chunks:
        if sum(len(unit.text) for unit in chunk.units) > MAX_SOURCE_CHARACTERS:
            raise BatchError("SOURCE_CHUNK_CHARACTER_BUDGET_EXCEEDED")
        messages = _document_messages(prompt_source or {"document_id": document_id}, chunk, partial_source=False)
        if len(_request_envelope(messages)) > MAX_REQUEST_ENVELOPE_BYTES:
            raise BatchError("REQUEST_ENVELOPE_BUDGET_EXCEEDED")
    if chunks and not pdf_research.verify_chunk_reconstruction(pages, chunks):
        raise BatchError("SOURCE_CHUNK_RECONSTRUCTION_FAILED")
    return chunks


def _split_report_items(reports: Sequence[Mapping[str, str]]) -> list[dict[str, str]]:
    parts: list[dict[str, str]] = []
    for index, item in enumerate(reports, start=1):
        text = str(item["text"])
        if not text:
            raise BatchError("EMPTY_PARTIAL_REPORT")
        for offset in range(0, len(text), MAX_SYNTHESIS_PART_CHARACTERS):
            parts.append(
                {
                    "report_id": f"{item.get('report_id', index)}:part-{offset // MAX_SYNTHESIS_PART_CHARACTERS + 1:04d}",
                    "text": text[offset : offset + MAX_SYNTHESIS_PART_CHARACTERS],
                }
            )
    return parts



def _synthesis_output_budget(reports: Sequence[Mapping[str, str]]) -> int:
    return max(1, sum(len(item["text"]) for item in reports) * 7 // 10)


def _require_synthesis_progress(before: Sequence[Mapping[str, str]], after: Sequence[Mapping[str, str]]) -> None:
    previous = [item["text"] for item in before]
    current = [item["text"] for item in after]
    if (current == previous or not current
            or not (len(current) < len(previous) or sum(map(len, current)) < sum(map(len, previous)))):
        raise BatchError("SYNTHESIS_NONCONVERGENT_OUTPUT")


def _pack_synthesis_groups(
    document_id: str,
    reports: Sequence[Mapping[str, str]],
    level: int,
    source_boundary: Mapping[str, Any] | None = None,
    reserve_contraction: bool = False,
    source_qualifications: Mapping[str, Any] | None = None,
) -> list[list[dict[str, str]]]:
    parts = _split_report_items(reports)
    groups: list[list[dict[str, str]]] = []
    current: list[dict[str, str]] = []
    for part in parts:
        candidate = current + [part]
        source_chars = sum(len(item["text"]) for item in candidate) + (len(_json_bytes(source_qualifications).decode()) if source_qualifications else 0)
        messages = _synthesis_messages(document_id, candidate, level, source_boundary, _synthesis_output_budget(candidate) if reserve_contraction else None, source_qualifications)
        if source_chars <= MAX_SOURCE_CHARACTERS and len(_request_envelope(messages)) <= MAX_REQUEST_ENVELOPE_BYTES:
            current = candidate
            continue
        if current:
            groups.append(current)
            current = [part]
            single_messages = _synthesis_messages(document_id, current, level, source_boundary, _synthesis_output_budget(current) if reserve_contraction else None, source_qualifications)
            if len(_request_envelope(single_messages)) > MAX_REQUEST_ENVELOPE_BYTES:
                raise BatchError("SYNTHESIS_ITEM_ENVELOPE_BUDGET_EXCEEDED")
            continue
        raise BatchError("SYNTHESIS_ITEM_BUDGET_EXCEEDED")
    if current:
        groups.append(current)
    return groups


def _report_status_metadata(*, user_accepted: bool = False) -> dict[str, Any]:
    return {
        "origin_status": "MODEL_GENERATED",
        "source_review_status": "SOURCE_REVIEW_PENDING",
        "user_acceptance_status": "USER_ACCEPTED" if user_accepted else "NOT_REQUESTED",
        "research_only": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def _read_s18_acceptance() -> tuple[dict[str, Any], bytes]:
    path = USER_ACCEPTANCE_PATH
    if path.is_symlink() or not path.is_file():
        raise BatchError("S18_USER_ACCEPTANCE_UNAVAILABLE")
    raw = path.read_bytes()
    if _sha256(raw) != USER_ACCEPTANCE_SHA256:
        raise BatchError("S18_USER_ACCEPTANCE_SHA_MISMATCH")
    try:
        receipt = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        raise BatchError("S18_USER_ACCEPTANCE_INVALID") from None
    if (
        not isinstance(receipt, dict)
        or receipt.get("schema") != "v4.pdf_simple_batch.user_sample_acceptance.v1"
        or receipt.get("status") != "USER_ACCEPTED"
        or receipt.get("batch_authorized") is not True
        or receipt.get("source_pdf_sha256") != S18_PDF_SHA256
        or receipt.get("model_report_path") != str(S18_REPORT_PATH)
        or receipt.get("model_report_sha256") != S18_REPORT_SHA256
        or not re.fullmatch(r"[0-9a-f]{64}", str(receipt.get("independent_content_verdict_sha256", "")))
    ):
        raise BatchError("S18_USER_ACCEPTANCE_BINDING_MISMATCH")
    report_path = S18_REPORT_PATH
    if report_path.is_symlink() or not report_path.is_file():
        raise BatchError("S18_ACCEPTED_REPORT_UNAVAILABLE")
    report_bytes = report_path.read_bytes()
    if _sha256(report_bytes) != S18_REPORT_SHA256:
        raise BatchError("S18_ACCEPTED_REPORT_SHA_MISMATCH")
    return receipt, report_bytes


def _validate_output(_job: Any, parsed: Any) -> dict[str, str]:
    if not isinstance(parsed, dict) or set(parsed) != {"analysis_markdown"}:
        raise BatchError("MODEL_OUTPUT_SCHEMA_INVALID")
    report = parsed.get("analysis_markdown")
    if not isinstance(report, str) or not report.strip():
        raise BatchError("MODEL_OUTPUT_EMPTY")
    return {"analysis_markdown": report}


def _priority_snapshot(path: Path | None = None) -> dict[str, Any]:
    state_path = path or (pdf_research.ANNOUNCEMENT_QUEUE_ROOT / "queue-state.json")
    try:
        if state_path.is_symlink() or not state_path.is_file():
            return {"status": "DEFER", "reason": "ANNOUNCEMENT_QUEUE_UNAVAILABLE"}
        before = state_path.stat()
        raw = state_path.read_bytes()
        after = state_path.stat()
        if (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
            return {"status": "DEFER", "reason": "ANNOUNCEMENT_QUEUE_CHANGED_DURING_READ"}
        state = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {"status": "DEFER", "reason": "ANNOUNCEMENT_QUEUE_UNREADABLE"}
    if not isinstance(state, dict) or state.get("schema") != "v4.announcement-engine-queue/v1" or not isinstance(state.get("jobs"), dict):
        return {"status": "DEFER", "reason": "ANNOUNCEMENT_QUEUE_IDENTITY_UNCONFIRMED"}
    same_model_pending = 0
    for item in state["jobs"].values():
        if not isinstance(item, dict):
            return {"status": "DEFER", "reason": "ANNOUNCEMENT_JOB_IDENTITY_UNCONFIRMED"}
        status = item.get("status")
        if status in {"SUCCEEDED", "FAILED", "OVERSIZE", "MISSING_MATERIAL"}:
            continue
        if status not in {"PENDING", "RUNNING", "CLAIMED"}:
            return {"status": "DEFER", "reason": "ANNOUNCEMENT_JOB_STATUS_UNCONFIRMED"}
        model_id = item.get("model_id")
        if not isinstance(model_id, str) or not model_id.strip():
            return {"status": "DEFER", "reason": "ANNOUNCEMENT_JOB_IDENTITY_UNCONFIRMED"}
        if model_id != local_model.MODEL_ID:
            continue
        identity = item.get("identity")
        if not isinstance(identity, dict) or identity.get("role") not in ANNOUNCEMENT_ROLES:
            return {"status": "DEFER", "reason": "ANNOUNCEMENT_JOB_IDENTITY_UNCONFIRMED"}
        if status in {"RUNNING", "CLAIMED"}:
            return {"status": "DEFER", "reason": "SAME_MODEL_ANNOUNCEMENT_ACTIVE", "same_model_pending_count": same_model_pending}
        if status == "PENDING":
            same_model_pending += 1
    return {"status": "ALLOW", "same_model_pending_count": same_model_pending, "pending_is_advisory": True}


def _create_queue(state_root: Path) -> tuple[Any, Path]:
    queue_class, shared_lock = pdf_research._queue_class_and_path()
    queue = queue_class(state_root / "queue", "v4-pdf-simple-batch", local_model.MODEL_ID, max_attempts=1, max_body_bytes=None)
    queue._model_lock_path = shared_lock
    if queue.state_root.resolve() == pdf_research.ANNOUNCEMENT_QUEUE_ROOT.resolve() or shared_lock != pdf_research.GLOBAL_MODEL_LOCK_PATH:
        raise BatchError("BATCH_QUEUE_OR_SHARED_LOCK_IDENTITY_MISMATCH")
    return queue, shared_lock


def _queue_read_result(queue: Any, item: Mapping[str, Any]) -> dict[str, Any] | None:
    key = item.get("idempotency_key")
    if not isinstance(key, str):
        return None
    return pdf_research._read_validated_result(queue, key)


def _read_r1_success(
    queue: Any,
    payload: Mapping[str, Any],
    *,
    queue_root: Path | None = None,
    reuse_status: str = "SUCCEEDED_REUSED_R1",
    allow_continuation_rebind: bool = False,
    allow_frozen_runner_source_rebind: bool = False,
) -> dict[str, Any] | None:
    """Read and revalidate a successful prior request without modifying its queue."""
    if payload.get("source_sha256") in SOURCE_REJECTED_PDF_SHA256S:
        return None
    queue_root = queue_root or R1_STATE_ROOT / "queue"
    state_path = queue_root / "queue-state.json"
    if state_path.is_symlink() or not state_path.is_file():
        return None
    try:
        before = state_path.stat()
        state_raw = state_path.read_bytes()
        after = state_path.stat()
        if (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
            return None
        state = json.loads(state_raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    jobs = state.get("jobs") if isinstance(state, dict) else None
    if not isinstance(state, dict) or state.get("schema") != "v4.announcement-engine-queue/v1" or not isinstance(jobs, dict):
        return None
    try:
        key, payload_sha = pdf_research._queue_identity_and_payload_sha256(queue, payload)
    except Exception:
        return None
    item = jobs.get(key)
    if not isinstance(item, dict):
        return None
    attempts = item.get("attempts")
    policy = item.get("queue_policy")
    expected_queue_id = getattr(queue, "queue_id", "v4-pdf-simple-batch")
    expected_model_id = getattr(queue, "model_id", local_model.MODEL_ID)
    if (
        item.get("status") != "SUCCEEDED"
        or item.get("idempotency_key") != key
        or item.get("queue_id") != expected_queue_id
        or item.get("model_id") != expected_model_id
        or item.get("attempt_count") != 1
        or item.get("max_attempts") != 1
        or policy != {"max_attempts": 1, "max_body_bytes": None}
        or not isinstance(item.get("queue_ids", [item.get("queue_id")]), list)
        or expected_queue_id not in item.get("queue_ids", [item.get("queue_id")])
        or not isinstance(attempts, list)
        or len(attempts) != 1
        or not isinstance(attempts[0], dict)
        or attempts[0].get("status") != "SUCCEEDED"
        or attempts[0].get("number") != 1
        or attempts[0].get("raw_sha256") != item.get("raw_sha256")
        or attempts[0].get("validated_sha256") != item.get("validated_sha256")
        or attempts[0].get("raw_path") != item.get("raw_path")
        or attempts[0].get("validated_path") != item.get("validated_path")
    ):
        return None
    expected_paths = {
        "input_path": f"jobs/{key}/input.json",
        "raw_path": f"jobs/{key}/attempt-0001.raw",
        "validated_path": f"jobs/{key}/attempt-0001.validated.json",
    }
    if any(item.get(name) != path for name, path in expected_paths.items()):
        return None
    paths: dict[str, Path] = {}
    for name, relative in expected_paths.items():
        try:
            paths[name] = pdf_research._assert_no_symlink_components(queue_root / relative, queue_root)
        except Exception:
            return None
    try:
        input_raw = paths["input_path"].read_bytes()
        raw_response = paths["raw_path"].read_bytes()
        validated_raw = paths["validated_path"].read_bytes()
    except OSError:
        return None
    input_matches = input_raw == local_model.canonical_json(dict(payload)) and _sha256(input_raw) == payload_sha
    if allow_continuation_rebind and not input_matches:
        try:
            prior_payload = json.loads(input_raw.decode("utf-8"))
            input_matches = (
                isinstance(prior_payload, dict)
                and _same_request_payload_ignoring_run_root(
                    prior_payload,
                    payload,
                    allow_frozen_runner_source_rebind=allow_frozen_runner_source_rebind,
                )
                and _sha256(input_raw) == item.get("payload_sha256")
            )
        except (UnicodeError, json.JSONDecodeError):
            input_matches = False
    if (
        not input_matches
        or item.get("payload_sha256") != _sha256(input_raw)
        or _sha256(raw_response) != item.get("raw_sha256")
        or _sha256(validated_raw) != item.get("validated_sha256")
    ):
        return None
    try:
        raw_output = json.loads(raw_response.decode("utf-8"))
        validated = json.loads(validated_raw.decode("utf-8"))
        accepted = _validate_output(None, raw_output)
    except (UnicodeError, json.JSONDecodeError, BatchError):
        return None
    if accepted != validated:
        return None
    queue_item = {
        **item,
        "queue_root": str(queue_root),
        "raw_path": str(paths["raw_path"]),
        "validated_path": str(paths["validated_path"]),
    }
    return {"status": reuse_status, "queue_item": queue_item, "result": validated, "attempted": False}


def _read_continuation_prior_outcome(
    queue: Any,
    payload: Mapping[str, Any],
    queue_root: Path,
    *,
    allow_frozen_runner_source_rebind: bool = False,
) -> dict[str, Any] | None:
    """Reuse an exact prior success or block replay of a prior terminal failure."""
    reused = _read_r1_success(
        queue,
        payload,
        queue_root=queue_root,
        reuse_status="SUCCEEDED_REUSED_CONTINUATION_SOURCE",
        allow_continuation_rebind=True,
        allow_frozen_runner_source_rebind=allow_frozen_runner_source_rebind,
    )
    if reused is not None:
        return reused
    state_path = queue_root / "queue-state.json"
    if state_path.is_symlink() or not state_path.is_file():
        return None
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        key, payload_sha = pdf_research._queue_identity_and_payload_sha256(queue, payload)
    except (OSError, UnicodeError, json.JSONDecodeError, Exception):
        return None
    jobs = state.get("jobs") if isinstance(state, dict) else None
    item = jobs.get(key) if isinstance(jobs, dict) else None
    if not isinstance(item, dict):
        return None
    expected_input = f"jobs/{key}/input.json"
    if item.get("input_path") != expected_input:
        raise BatchError("CONTINUATION_PRIOR_QUEUE_INPUT_PATH_MISMATCH")
    input_path = queue_root / expected_input
    if not _continuation_path_is_safe(input_path, queue_root, allow_missing=False):
        raise BatchError("CONTINUATION_PRIOR_QUEUE_INPUT_UNAVAILABLE")
    try:
        input_raw = input_path.read_bytes()
        prior_payload = json.loads(input_raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise BatchError("CONTINUATION_PRIOR_QUEUE_INPUT_INVALID") from None
    if (
        not isinstance(prior_payload, dict)
        or item.get("payload_sha256") != _sha256(input_raw)
        or not _same_request_payload_ignoring_run_root(
            prior_payload,
            payload,
            allow_frozen_runner_source_rebind=allow_frozen_runner_source_rebind,
        )
    ):
        return None
    if item.get("status") == "SUCCEEDED":
        raise BatchError("CONTINUATION_PRIOR_QUEUE_SUCCESS_UNAVAILABLE")
    return {
        "status": "FAILED_NO_RETRY",
        "queue_item": {**item, "queue_root": str(queue_root)},
        "attempted": False,
        "prior_failure_reused": True,
    }


def _request_payload(
    document: Mapping[str, Any],
    *,
    stage: str,
    article_id: str,
    messages: Sequence[Mapping[str, str]],
    binding: Mapping[str, Any],
    envelope: bytes,
    source_characters: int,
    source_text_sha256: str,
    pdf_tool_binding: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    body = str(messages[-1]["content"])
    prompt_sha = _sha256(local_model.canonical_json([dict(item) for item in messages]))
    payload = {
        "date": str(document.get("report_date") or "UNKNOWN"),
        "market": "PDF_RESEARCH",
        "article_id": article_id,
        "source_sha256": str(document["pdf_sha256"]),
        "body_sha256": _sha256(body.encode("utf-8")),
        "prompt_sha256": prompt_sha,
        "model_id": local_model.MODEL_ID,
        "configuration_sha256": str(binding["configuration_sha256"]),
        "rules": RESPONSE_RULES,
        "role": "pdf_report_demo",
        "stage": stage,
        "article_body": body,
        "source_document_id": document["document_id"],
        "source_text_sha256": source_text_sha256,
        "source_character_count": source_characters,
        "request_envelope_byte_count": len(envelope),
        "request_envelope_sha256": _sha256(envelope),
        "workflow_profile": local_model.PROFILE_NAME,
        "request_schema": RESPONSE_SCHEMA,
        "request_schema_sha256": binding["request_schema_sha256"],
        "model_binding": dict(binding),
        "evidence_root": str(binding["evidence_root"]),
    }
    if pdf_tool_binding is not None:
        payload["pdf_tool_binding"] = dict(pdf_tool_binding)
    return payload


def _document_chunk_request_material(
    document: Mapping[str, Any],
    chunk: pdf_research.SourceChunk,
    *,
    prompt_document: Mapping[str, Any],
    partial_source: bool,
    tool_canary: bool,
    binding: Mapping[str, Any],
    page_input_sha256: str,
    page_count: int,
) -> tuple[list[dict[str, str]], bytes, dict[str, Any]]:
    messages = _document_messages(
        prompt_document,
        chunk,
        partial_source=partial_source,
        tool_canary=tool_canary,
    )
    envelope = _request_envelope(messages)
    if len(envelope) > MAX_REQUEST_ENVELOPE_BYTES:
        raise BatchError("REQUEST_ENVELOPE_BUDGET_EXCEEDED")
    source_chars = sum(len(unit.text) for unit in chunk.units)
    payload = _request_payload(
        document,
        stage="simple_batch_document_chunk_v1",
        article_id=f"{document['document_id']}:chunk:{chunk.chunk_index:06d}:{chunk.chunk_sha256}",
        messages=messages,
        binding=binding,
        envelope=envelope,
        source_characters=source_chars,
        source_text_sha256=chunk.chunk_sha256,
        pdf_tool_binding={
            "action_prompt_sha256": _sha256(pdf_research_tools.ACTION_SYSTEM_PROMPT.encode("utf-8")),
            "page_input_sha256": page_input_sha256,
            "page_count": page_count,
        },
    )
    return messages, envelope, payload


def _preflight_ppi_partial_chunk_recovery(
    document: Mapping[str, Any],
    chunks: Sequence[pdf_research.SourceChunk],
    *,
    prompt_document: Mapping[str, Any],
    partial_source: bool,
    binding: Mapping[str, Any],
    page_input_sha256: str,
    page_count: int,
    queue: Any,
    continuation: Mapping[str, Any],
    recovery_binding: Mapping[str, Any],
) -> None:
    if (
        len(chunks) != 2
        or chunks[0].chunk_index != 1
        or chunks[0].chunk_sha256 != PPI_PARTIAL_RECOVERY_SUCCESS_CHUNK_SHA256
        or chunks[1].chunk_index != 2
        or chunks[1].chunk_sha256 != PPI_PARTIAL_RECOVERY_FAILED_CHUNK_SHA256
        or page_input_sha256 != PPI_PARTIAL_RECOVERY_PAGE_INPUT_SHA256
    ):
        raise BatchError("PPI_PARTIAL_RECOVERY_RECONSTRUCTED_CHUNKS_MISMATCH")
    prior_queue_root = recovery_binding.get("prior_queue_root")
    if not isinstance(prior_queue_root, Path):
        raise BatchError("PPI_PARTIAL_RECOVERY_PRIOR_QUEUE_ROOT_UNAVAILABLE")
    _prior_messages, _prior_envelope, prior_payload = _document_chunk_request_material(
        document,
        chunks[0],
        prompt_document=prompt_document,
        partial_source=partial_source,
        tool_canary=False,
        binding=binding,
        page_input_sha256=page_input_sha256,
        page_count=page_count,
    )
    bound_prior_payload, is_recovery_target = _bind_continuation_payload(
        prior_payload,
        continuation,
        allow_frozen_runner_source_rebind=True,
    )
    if is_recovery_target:
        raise BatchError("PPI_PARTIAL_RECOVERY_SUCCESS_CHUNK_MATCHED_FAILURE_TARGET")
    prior_success = _read_continuation_prior_outcome(
        queue,
        bound_prior_payload,
        prior_queue_root,
        allow_frozen_runner_source_rebind=True,
    )
    if (
        not isinstance(prior_success, dict)
        or prior_success.get("status") != "SUCCEEDED_REUSED_CONTINUATION_SOURCE"
        or prior_success.get("attempted") is not False
        or not isinstance(prior_success.get("queue_item"), dict)
        or prior_success["queue_item"].get("idempotency_key") != PPI_PARTIAL_RECOVERY_SUCCESS_QUEUE_KEY
        or prior_success["queue_item"].get("payload_sha256") != PPI_PARTIAL_RECOVERY_SUCCESS_PAYLOAD_SHA256
        or prior_success["queue_item"].get("raw_sha256") != PPI_PARTIAL_RECOVERY_SUCCESS_RESPONSE_SHA256
        or prior_success["queue_item"].get("validated_sha256") != PPI_PARTIAL_RECOVERY_SUCCESS_RESPONSE_SHA256
    ):
        raise BatchError("PPI_PARTIAL_RECOVERY_SUCCESS_CHUNK_REUSE_NOT_VERIFIED")


def _preflight_memory_recovery_input(
    document_id: str,
    chunks: Sequence[pdf_research.SourceChunk],
    *,
    page_input_sha256: str,
    continuation: Mapping[str, Any],
    recovery_binding: Mapping[str, Any],
) -> None:
    """Reject a changed source snapshot/target before writing run progress or enqueueing."""
    entry = continuation.get("entry")
    recovery = entry.get("recovery") if isinstance(entry, Mapping) else None
    prior_payload = recovery_binding.get("prior_payload")
    if not isinstance(recovery, Mapping) or not isinstance(prior_payload, Mapping):
        raise BatchError("CONTINUATION_RECOVERY_PRIOR_PAYLOAD_UNAVAILABLE")
    prior_page_input = recovery_binding.get("prior_page_input_sha256")
    tool_binding = prior_payload.get("pdf_tool_binding")
    if (
        page_input_sha256 != prior_page_input
        or not isinstance(tool_binding, Mapping)
        or tool_binding.get("page_input_sha256") != page_input_sha256
    ):
        raise BatchError("CONTINUATION_RECOVERY_PAGE_INPUT_MISMATCH")

    article_id = recovery.get("prior_article_id")
    if not isinstance(article_id, str) or not article_id.startswith(f"{document_id}:"):
        raise BatchError("CONTINUATION_RECOVERY_TARGET_IDENTITY_MISMATCH")
    stage = prior_payload.get("stage")
    if stage == "simple_batch_document_chunk_v1":
        expected_ids = {
            f"{document_id}:chunk:{chunk.chunk_index:06d}:{chunk.chunk_sha256}"
            for chunk in chunks
        }
        if article_id not in expected_ids:
            raise BatchError("CONTINUATION_RECOVERY_TARGET_CHUNK_MISMATCH")
    elif stage == "simple_batch_document_synthesis_v1":
        if not article_id.startswith(f"{document_id}:synthesis:"):
            raise BatchError("CONTINUATION_RECOVERY_TARGET_SYNTHESIS_MISMATCH")
    else:
        raise BatchError("CONTINUATION_RECOVERY_TARGET_STAGE_UNSUPPORTED")


def _prepared_recovery_input_bridge(
    prepared: Mapping[str, Any],
    document_id: str,
    continuation: Mapping[str, Any],
) -> tuple[dict[str, Any], bytes, str, dict[str, Any]]:
    """Reuse old request identity only after exact READY page-by-page equivalence."""
    recovery = continuation.get("recovery_binding")
    if not isinstance(recovery, Mapping) or not isinstance(recovery.get("prior_payload"), Mapping):
        raise BatchError("PREPARED_RECOVERY_BINDING_UNAVAILABLE")
    verified = prepared.get("documents", {}).get(document_id)
    if not isinstance(verified, Mapping) or verified.get("manifest_row", {}).get("status") != "READY":
        raise BatchError("PREPARED_RECOVERY_DOCUMENT_NOT_READY")
    current = verified.get("page_input")
    old_root = Path(str(recovery.get("prior_queue_root", ""))).parent
    old_path = old_root / "documents" / document_id / "page-input.json"
    if not _continuation_path_is_safe(old_path, old_root, allow_missing=False):
        raise BatchError("PREPARED_RECOVERY_INPUT_UNSAFE")
    old_raw = old_path.read_bytes()
    old_sha = _sha256(old_raw)
    if old_sha != recovery.get("prior_page_input_sha256"):
        raise BatchError("PREPARED_RECOVERY_INPUT_SHA_MISMATCH")
    try:
        old = json.loads(old_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        raise BatchError("PREPARED_RECOVERY_INPUT_INVALID") from None
    if not isinstance(current, Mapping) or not isinstance(old, dict):
        raise BatchError("PREPARED_RECOVERY_INPUT_INVALID")
    for item in (old, current):
        if (item.get("schema") != pdf_text_preparation.PAGE_INPUT_SCHEMA
                or item.get("document_id") != document_id
                or item.get("pdf_sha256") != document_id
                or item.get("manifest_sha256") != prepared.get("parent_manifest_sha256")
                or not isinstance(item.get("pages"), list)
                or not item["pages"]
                or item.get("source", {}).get("page_count") != len(item["pages"])):
            raise BatchError("PREPARED_RECOVERY_INPUT_IDENTITY_MISMATCH")
    if len(old["pages"]) != len(current["pages"]):
        raise BatchError("PREPARED_RECOVERY_PAGE_COVERAGE_MISMATCH")
    page_hashes = []
    for number, (prior_page, ready_page) in enumerate(zip(old["pages"], current["pages"], strict=True), 1):
        if (not isinstance(prior_page, Mapping) or not isinstance(ready_page, Mapping)
                or prior_page.get("page_number") != number or ready_page.get("page_number") != number
                or not isinstance(ready_page.get("text"), str) or not ready_page["text"].strip()
                or prior_page.get("text") != ready_page["text"]):
            raise BatchError("PREPARED_RECOVERY_PAGE_TEXT_MISMATCH")
        text_sha = _sha256(ready_page["text"].encode("utf-8"))
        if any(page.get("text_sha256") not in (None, text_sha) for page in (prior_page, ready_page)):
            raise BatchError("PREPARED_RECOVERY_PAGE_TEXT_SHA_MISMATCH")
        page_hashes.append({"page_number": number, "text_sha256": text_sha})
    bridge = {"schema": "v4.pdf_research.prepared_recovery_input_bridge.v1", "document_id": document_id,
              "pdf_sha256": document_id, "parent_manifest_sha256": prepared["parent_manifest_sha256"],
              "prepared_text_manifest_sha256": prepared["manifest_sha256"],
              "prepared_page_input_sha256": verified["page_input_sha256"],
              "extractor_identity_sha256": prepared["manifest"]["extractor_identity_sha256"],
              "historical_page_input_path": str(old_path), "historical_page_input_sha256": old_sha,
              "page_count": len(page_hashes), "pages": page_hashes,
              "status": "EXACT_PAGE_TEXT_EQUIVALENCE", "original_artifacts_modified": False}
    return old, old_raw, old_sha, bridge


def _bind_continuation_payload(
    payload: Mapping[str, Any],
    continuation: Mapping[str, Any] | None,
    *,
    allow_frozen_runner_source_rebind: bool = False,
) -> tuple[dict[str, Any], bool]:
    bound = dict(payload)
    if continuation is None:
        return bound, False
    entry = continuation["entry"]
    plan = continuation["plan"]
    recovery = entry.get("recovery") if isinstance(entry, dict) else None
    recovery_of = None
    is_recovery_target = False
    if isinstance(recovery, dict):
        recovery_binding = continuation.get("recovery_binding")
        prior_payload = recovery_binding.get("prior_payload") if isinstance(recovery_binding, dict) else None
        if not isinstance(prior_payload, dict):
            raise BatchError("CONTINUATION_RECOVERY_PRIOR_PAYLOAD_UNAVAILABLE")
        if bound.get("article_id") == recovery.get("prior_article_id"):
            if not _same_request_payload_ignoring_run_root(
                prior_payload,
                bound,
                allow_frozen_runner_source_rebind=allow_frozen_runner_source_rebind,
            ):
                raise BatchError("CONTINUATION_RECOVERY_REQUEST_BINDING_MISMATCH")
            bound["article_id"] = f"{recovery['prior_article_id']}:recovery:1"
            is_recovery_target = True
            continuation["recovery_target_reached"].set()
            recovery_of = {
                "generation": 1,
                "prior_idempotency_key": recovery["prior_queue_idempotency_key"],
                "prior_payload_sha256": recovery["prior_payload_sha256"],
                "prior_raw_sha256": recovery["prior_raw_sha256"],
            }
    bound["continuation"] = {
        "continuation_id": plan["continuation_id"],
        "plan_sha256": continuation["plan_sha256"],
        "manifest_sha256": plan["manifest_sha256"],
        "runtime_settings_sha256": plan["runtime_settings_sha256"],
        "model_settings_sha256": plan["expected_model_settings_sha256"],
        "selected_prior_status": entry["prior_status"],
        "recovery_of": recovery_of,
    }
    if "execution_runtime_settings_sha256" in plan:
        bound["continuation"]["execution_runtime_settings_sha256"] = plan["execution_runtime_settings_sha256"]
    return bound, is_recovery_target


def _perform_request(
    queue: Any,
    payload: Mapping[str, Any],
    messages: Sequence[Mapping[str, str]],
    *,
    binding: Mapping[str, Any],
    identity: Mapping[str, Any],
    identity_reader: Callable[[], Mapping[str, Any]],
    priority_reader: Callable[[], Mapping[str, Any]],
    request_fn: Callable[..., str],
    sleep_fn: Callable[[float], Any],
    stop_event: threading.Event | None = None,
    prior_queue_root: Path | None = None,
    recovery_target_pending: bool = False,
    tool_context: Mapping[str, Any] | None = None,
    allow_frozen_runner_source_rebind: bool = False,
    analysis_admission: Mapping[str, Any] | None = None,
    request_guard: Callable[[], None] | None = None,
) -> dict[str, Any]:
    if request_guard is not None:
        request_guard()
    document_id = str(payload.get("source_document_id", ""))
    if analysis_admission is not None:
        verify_analysis_plan_runtime(payload.get("continuation", {}), analysis_admission, binding)
        guard_analysis_document(analysis_admission, document_id, binding=binding)
        verify_analysis_dispatch(document_id, str(payload.get("continuation", {}).get("plan_sha256", "")), analysis_admission)
    if stop_event is not None and stop_event.is_set():
        return {"status": "STOPPED_GRACEFULLY", "attempted": False}
    if len(_request_envelope(messages)) > MAX_REQUEST_ENVELOPE_BYTES:
        raise BatchError("REQUEST_ENVELOPE_BUDGET_EXCEEDED")
    if prior_queue_root is not None:
        prior_outcome = _read_continuation_prior_outcome(
            queue,
            payload,
            prior_queue_root,
            allow_frozen_runner_source_rebind=allow_frozen_runner_source_rebind,
        )
        if prior_outcome is not None:
            return prior_outcome
        if recovery_target_pending:
            raise BatchError("CONTINUATION_RECOVERY_TARGET_NOT_REACHED")
    if isinstance(payload.get("continuation"), dict):
        reused_prior = _read_r1_success(queue, payload, allow_continuation_rebind=True)
    else:
        reused_prior = _read_r1_success(queue, payload)
    if reused_prior is not None:
        return reused_prior
    queued = queue.enqueue(payload)
    status = queued.get("status")
    if status == "SUCCEEDED":
        accepted = _queue_read_result(queue, queued)
        if accepted is None:
            raise BatchError("SUCCEEDED_QUEUE_RESULT_UNAVAILABLE")
        return {"status": "SUCCEEDED_REUSED", "queue_item": queued, "result": accepted, "attempted": False}
    if status in {"FAILED", "OVERSIZE", "MISSING_MATERIAL"}:
        return {"status": "FAILED_NO_RETRY", "queue_item": queued, "attempted": False}
    if stop_event is not None and stop_event.is_set():
        return {"status": "STOPPED_GRACEFULLY", "queue_item": queued, "attempted": False}
    priority = dict(priority_reader())
    if priority.get("status") != "ALLOW":
        return {"status": "DEFERRED_ANNOUNCEMENT_PRIORITY", "priority": priority, "queue_item": queued, "attempted": False}
    if stop_event is not None and stop_event.is_set():
        return {"status": "STOPPED_GRACEFULLY", "priority": priority, "queue_item": queued, "attempted": False}
    if identity.get("status") == "NOT_CHECKED":
        identity = dict(identity_reader())
    if identity.get("status") != "MATCH" or identity.get("expected_model_id") != local_model.MODEL_ID:
        return {"status": "DEFERRED_MODEL_IDENTITY_UNCONFIRMED", "queue_item": queued, "attempted": False, "model_identity": dict(identity)}
    if stop_event is not None and stop_event.is_set():
        return {"status": "STOPPED_GRACEFULLY", "priority": priority, "queue_item": queued, "attempted": False}
    key = queued.get("idempotency_key")
    if not isinstance(key, str):
        raise BatchError("QUEUE_IDEMPOTENCY_KEY_MISSING")

    def executor(job: Any) -> str:
        if job.model_id != local_model.MODEL_ID or job.payload.get("model_binding") != dict(binding):
            raise BatchError("QUEUED_REQUEST_BINDING_MISMATCH")
        tool_binding = job.payload.get("pdf_tool_binding")
        if tool_context is None:
            if tool_binding is not None:
                raise BatchError("QUEUED_PDF_TOOL_CONTEXT_MISMATCH")
        else:
            expected_tool_binding = {
                "action_prompt_sha256": _sha256(pdf_research_tools.ACTION_SYSTEM_PROMPT.encode("utf-8")),
                "page_input_sha256": tool_context.get("page_input_sha256"),
                "page_count": len(tool_context.get("pages", [])),
            }
            if tool_binding != expected_tool_binding:
                raise BatchError("QUEUED_PDF_TOOL_CONTEXT_MISMATCH")
        return request_fn(
            job=job,
            messages=messages,
            schema=RESPONSE_SCHEMA,
            expected_binding=binding,
            **({"tool_context": tool_context} if tool_context is not None else {}),
        )

    original_claim = getattr(queue, "_claim_next_locked", None)
    if analysis_admission is not None or request_guard is not None:
        if not callable(original_claim):
            raise BatchError("ANALYSIS_PRECLAIM_GUARD_UNAVAILABLE")
        def guarded_claim(state: Any, allowed_keys: Any = None) -> Any:
            if request_guard is not None:
                request_guard()
            if analysis_admission is not None:
                verify_analysis_plan_runtime(payload.get("continuation", {}), analysis_admission, binding)
                guard_analysis_document(analysis_admission, document_id, binding=binding)
                verify_analysis_dispatch(document_id, str(payload.get("continuation", {}).get("plan_sha256", "")), analysis_admission)
            return original_claim(state, allowed_keys)
        queue._claim_next_locked = guarded_claim
    try:
        outcome = queue.run_next(executor, _validate_output, wait_for_model_slot=False, idempotency_keys=[key])
    except Exception as exc:
        if type(exc).__name__ == "ModelSlotBusy":
            return {"status": "DEFERRED_MODEL_LOCK_BUSY", "queue_item": queued, "attempted": False}
        raise
    finally:
        if analysis_admission is not None or request_guard is not None:
            queue._claim_next_locked = original_claim
    if outcome is None:
        return {"status": "UNFINISHED_NO_OUTCOME", "queue_item": queued, "attempted": False}
    attempted = int(outcome.get("attempt_count", 0)) > 0
    if attempted:
        sleep_fn(ANNOUNCEMENT_IDLE_GAP_SECONDS)
    if outcome.get("status") == "SUCCEEDED" and outcome.get("attempt_count") == 1:
        accepted = _queue_read_result(queue, outcome)
        if accepted is None:
            raise BatchError("SUCCEEDED_QUEUE_RESULT_UNAVAILABLE")
        return {"status": "SUCCEEDED", "queue_item": outcome, "result": accepted, "attempted": True, "priority": priority}
    return {"status": "FAILED_NO_RETRY", "queue_item": outcome, "attempted": attempted, "priority": priority}


def _artifact_reference(root: Path, value: Any) -> dict[str, Any]:
    if not isinstance(value, str):
        return {"status": "CANNOT_CONFIRM"}
    path = Path(value)
    if path.is_absolute():
        candidate = path
    else:
        candidate = root / path
    try:
        candidate = candidate.resolve(strict=True)
        candidate.relative_to(root.resolve(strict=True))
        raw = candidate.read_bytes()
    except (OSError, ValueError):
        return {"status": "CANNOT_CONFIRM"}
    return {"status": "PRESENT", "path": str(candidate), "sha256": _sha256(raw), "bytes": len(raw)}


def _persist_model_result(
    state_root: Path,
    doc_root: Path,
    document: Mapping[str, Any],
    request_result: Mapping[str, Any],
    *,
    name: str,
) -> dict[str, Any]:
    item = request_result.get("queue_item") or {}
    result = request_result.get("result") or {}
    report = result.get("analysis_markdown") if isinstance(result, dict) else None
    if not isinstance(report, str) or not report.strip():
        raise BatchError("VALIDATED_REPORT_UNAVAILABLE")
    report_bytes = report.encode("utf-8")
    report_path = doc_root / "partials" / f"{name}.md"
    report_sha = _write_immutable(report_path, report_bytes, state_root)
    queue_root = Path(str(item.get("queue_root") or (state_root / "queue")))
    raw_reference = _artifact_reference(queue_root, item.get("raw_path"))
    validated_reference = _artifact_reference(queue_root, item.get("validated_path"))
    if raw_reference.get("status") != "PRESENT" or validated_reference.get("status") != "PRESENT":
        raise BatchError("QUEUE_ARTIFACT_PROVENANCE_UNAVAILABLE")
    raw_bytes = Path(raw_reference["path"]).read_bytes()
    copied_raw_path = doc_root / "raw" / f"{name}.attempt-0001.json"
    copied_raw_sha = _write_immutable(copied_raw_path, raw_bytes, state_root)
    return {
        "status": request_result.get("status"),
        "queue_idempotency_key": item.get("idempotency_key"),
        "attempt_count": item.get("attempt_count"),
        "raw": {"path": str(copied_raw_path), "sha256": copied_raw_sha, "bytes": len(raw_bytes)},
        "queue_raw": raw_reference,
        "validated_result": validated_reference,
        "report": {"path": str(report_path), "sha256": report_sha, "bytes": len(report_bytes)},
    }


def _save_progress(state_root: Path, doc_root: Path, value: Mapping[str, Any]) -> str:
    return _write_state_json(doc_root / "progress.json", value, state_root)


def _reuse_s18(
    state_root: Path,
    doc_root: Path,
    document: Mapping[str, Any],
    manifest_sha: str,
    *,
    page_input: Mapping[str, Any],
    source: Mapping[str, Any],
) -> dict[str, Any]:
    acceptance, report_bytes = _read_s18_acceptance()
    if document.get("pdf_sha256") != S18_PDF_SHA256:
        raise BatchError("S18_REUSE_PDF_SHA_MISMATCH")
    report_path = doc_root / "report.md"
    report_sha = _write_immutable(report_path, report_bytes, state_root)
    qualification = str(acceptance.get("accepted_presentation_qualification") or "")
    note_bytes = (
        "S18 accepted-presentation qualification\n\n"
        + qualification
        + "\n\nSource review for the batch display remains pending; this note does not modify the original model report.\n"
    ).encode("utf-8")
    note_path = doc_root / "presentation-qualification.md"
    note_sha = _write_immutable(note_path, note_bytes, state_root)
    receipt = {
        "schema": "v4.pdf_research_simple_batch.document_receipt.v1",
        "status": "USER_ACCEPTED_REUSED_REPORT",
        "manifest_sha256": manifest_sha,
        "document_id": document["document_id"],
        "pdf_sha256": document["pdf_sha256"],
        "page_input": dict(page_input),
        "source": dict(source),
        "report": {"path": str(report_path), "sha256": report_sha, "bytes": len(report_bytes)},
        "source_text_review_status": "SOURCE_REVIEW_PENDING",
        "report_metadata": {
            **_report_status_metadata(user_accepted=True),
            "accepted_sample_reuse": True,
            "accepted_presentation_qualification": qualification,
            "presentation_qualification_artifact": {"path": str(note_path), "sha256": note_sha, "bytes": len(note_bytes)},
            "original_model_report_sha256": S18_REPORT_SHA256,
            "original_raw_output": "NOT_READ_OR_MODIFIED",
        },
        "user_acceptance": {
            "status": acceptance["status"],
            "receipt_path": str(USER_ACCEPTANCE_PATH),
            "source_pdf_sha256": acceptance["source_pdf_sha256"],
            "independent_content_verdict_sha256": acceptance["independent_content_verdict_sha256"],
        },
        "research_only": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    _write_state_json(doc_root / "receipt.json", receipt, state_root)
    _save_progress(
        state_root,
        doc_root,
        {"document_id": document["document_id"], "status": "USER_ACCEPTED_REUSED_REPORT", "manifest_sha256": manifest_sha, "model_requests": 0},
    )
    return receipt


def _run_document(
    document: Mapping[str, Any],
    *,
    manifest_sha: str,
    state_root: Path,
    queue: Any,
    binding: Mapping[str, Any],
    identity: Mapping[str, Any],
    priority_reader: Callable[[], Mapping[str, Any]],
    identity_reader: Callable[[], Mapping[str, Any]],
    identity_state: dict[str, Any],
    request_fn: Callable[..., str],
    sleep_fn: Callable[[float], Any],
    stop_event: threading.Event | None = None,
    repair_budget: dict[str, int] | None = None,
    continuation: Mapping[str, Any] | None = None,
    prepared_manifest: Mapping[str, Any] | None = None,
    analysis_admission: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    pdf_sha = str(document["pdf_sha256"])
    if analysis_admission is not None:
        guard_analysis_document(analysis_admission, pdf_sha, binding=binding)
    doc_root = state_root / "documents" / pdf_sha
    doc_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    source_doc = {**dict(document), "_manifest_sha256": manifest_sha}
    prior_receipt_path = doc_root / "receipt.json"
    if prior_receipt_path.is_file() and not prior_receipt_path.is_symlink():
        try:
            prior = json.loads(prior_receipt_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            raise BatchError("EXISTING_DOCUMENT_RECEIPT_INVALID") from None
        if not isinstance(prior, dict) or prior.get("pdf_sha256") != pdf_sha:
            raise BatchError("EXISTING_DOCUMENT_RECEIPT_IDENTITY_MISMATCH")
        if prior.get("manifest_sha256") != manifest_sha:
            raise BatchError("EXISTING_DOCUMENT_RECEIPT_MANIFEST_MISMATCH")
        if prior.get("status") == "SECTIONED_SOURCE_STAGE_REPORT_SOURCE_REVIEW_PENDING" and pdf_sha != PILOT_LONG_DOCUMENT_ID:
            raise BatchError("SECTIONED_PRIOR_DOCUMENT_SCOPE_MISMATCH")
        if prior.get("status") in {
            "SECTIONED_SOURCE_STAGE_REPORT_SOURCE_REVIEW_PENDING",
            "USER_ACCEPTED_REUSED_REPORT",
            "MODEL_GENERATED_TEXT_COMPLETE_SOURCE_REVIEW_PENDING",
            "MODEL_GENERATED_TEXT_PARTIAL_SOURCE_REVIEW_PENDING",
        }:
            if prepared_manifest is None:
                return prior
            if (
                prior.get("prepared_text_manifest_sha256") == prepared_manifest.get("manifest_sha256")
                and isinstance(prior.get("page_input"), dict)
                and prior["page_input"].get("sha256")
                == prepared_manifest.get("documents", {}).get(pdf_sha, {}).get("page_input_sha256")
            ):
                return prior
            raise BatchError("PREPARED_MODEL_STATE_ROOT_COLLISION")
    try:
        if prepared_manifest is None:
            pages, source = _load_pages(document, state_root=state_root, repair_budget=repair_budget)
            input_value = _page_input_value(source_doc, pages, source)
            page_input_raw = _json_bytes(input_value, newline=True)
            page_input_sha = _sha256(page_input_raw)
            prepared_document_row = None
        else:
            pages, source, prepared_document_row = pdf_text_preparation.pages_from_frozen_manifest(
                prepared_manifest,
                pdf_sha,
            )
            verified_document = prepared_manifest.get("documents", {}).get(pdf_sha)
            if not isinstance(verified_document, Mapping):
                raise BatchError("PREPARED_DOCUMENT_BINDING_MISSING")
            input_value = verified_document.get("page_input")
            page_input_raw = verified_document.get("page_input_raw")
            page_input_sha = verified_document.get("page_input_sha256")
            if not isinstance(input_value, Mapping) or not isinstance(page_input_raw, bytes) or not isinstance(page_input_sha, str):
                raise BatchError("PREPARED_PAGE_INPUT_BINDING_MISSING")
            if _sha256(page_input_raw) != page_input_sha:
                raise BatchError("PREPARED_PAGE_INPUT_SHA_MISMATCH")
            source_doc["_prepared_text_manifest_sha256"] = prepared_manifest.get("manifest_sha256")
            source_doc["_prepared_text_revision"] = prepared_document_row.get("revision")
            if isinstance(continuation, Mapping) and isinstance(continuation.get("recovery_binding"), Mapping):
                input_value, page_input_raw, page_input_sha, bridge = _prepared_recovery_input_bridge(prepared_manifest, pdf_sha, continuation)
                _write_immutable(doc_root / "prepared-recovery-input-bridge.json", _json_bytes(bridge, newline=True), state_root)
    except (BatchError, pdf_text_preparation.PreparationError) as exc:
        status = "TEXT_UNAVAILABLE" if exc.code in {"PAGE_COUNT_UNAVAILABLE"} else "SOURCE_INVALID"
        receipt = {
            "schema": "v4.pdf_research_simple_batch.document_receipt.v1",
            "status": status,
            "failure_code": exc.code,
            "manifest_sha256": manifest_sha,
            "document_id": pdf_sha,
            "pdf_sha256": pdf_sha,
            "report_metadata": _report_status_metadata(),
            "research_only": True,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
        _write_state_json(doc_root / "receipt.json", receipt, state_root)
        _save_progress(state_root, doc_root, {"document_id": pdf_sha, "status": status, "failure_code": exc.code})
        return receipt
    _assert_bound_tool_canary_page_input(pdf_sha, continuation, page_input_sha)
    pending_source = prepared_manifest is None and source.get("source_repair_status") == "PENDING"
    page_input_path = (
        doc_root / "pending-source-inputs" / f"page-input-{page_input_sha}.json"
        if pending_source
        else doc_root / "page-input.json"
    )
    page_input_sha = _write_immutable(page_input_path, page_input_raw, state_root)
    page_input_ref = {
        "path": str(page_input_path),
        "sha256": page_input_sha,
        "bytes": len(page_input_raw),
        "kind": "PENDING_SOURCE_SNAPSHOT" if pending_source else "FINAL_SOURCE_INPUT",
    }
    page_status = source.get("page_extraction_status")
    if (
        source.get("source_repair_status") != "PENDING"
        and not str(source.get("source_repair_status", "")).startswith("FAILED")
        and (not pages or page_status == "TEXT_UNAVAILABLE")
    ):
        receipt = {
            "schema": "v4.pdf_research_simple_batch.document_receipt.v1",
            "status": "TEXT_UNAVAILABLE",
            "manifest_sha256": manifest_sha,
            "document_id": pdf_sha,
            "pdf_sha256": pdf_sha,
            "page_input": page_input_ref,
            "source": source,
            "report_metadata": _report_status_metadata(),
            "research_only": True,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
        _write_state_json(doc_root / "receipt.json", receipt, state_root)
        _save_progress(state_root, doc_root, {"document_id": pdf_sha, "status": "TEXT_UNAVAILABLE", "model_requests": 0})
        return receipt

    if pdf_sha == S18_PDF_SHA256:
        if prepared_document_row is None or not prepared_document_row.get("revision"):
            return _reuse_s18(
                state_root,
                doc_root,
                source_doc,
                manifest_sha,
                page_input=page_input_ref,
                source=source,
            )

    if source.get("source_repair_status") == "PENDING":
        receipt = {
            "schema": "v4.pdf_research_simple_batch.document_receipt.v1",
            "status": "DEFERRED_SOURCE_REPAIR_PENDING",
            "manifest_sha256": manifest_sha,
            "document_id": pdf_sha,
            "pdf_sha256": pdf_sha,
            "page_input": page_input_ref,
            "source": source,
            "remaining_work": "REPAIR_UNFINISHED_LOW_RESOLUTION_PAGES_ON_NEXT_TICK",
            "report_metadata": _report_status_metadata(),
            "research_only": True,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
        _write_state_json(doc_root / "receipt.json", receipt, state_root)
        _save_progress(state_root, doc_root, {"document_id": pdf_sha, "status": receipt["status"], "model_requests": 0})
        return receipt

    if str(source.get("source_repair_status", "")).startswith("FAILED"):
        receipt = {
            "schema": "v4.pdf_research_simple_batch.document_receipt.v1",
            "status": "SOURCE_REPAIR_FAILED_NO_MODEL",
            "manifest_sha256": manifest_sha,
            "document_id": pdf_sha,
            "pdf_sha256": pdf_sha,
            "page_input": page_input_ref,
            "source": source,
            "report_metadata": _report_status_metadata(),
            "research_only": True,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
        _write_state_json(doc_root / "receipt.json", receipt, state_root)
        _save_progress(state_root, doc_root, {"document_id": pdf_sha, "status": receipt["status"], "model_requests": 0})
        return receipt

    nonempty = bool(source.get("all_pages_nonempty"))
    if not nonempty:
        receipt = {
            "schema": "v4.pdf_research_simple_batch.document_receipt.v1",
            "status": "PARTIAL_SOURCE_NO_MODEL_REQUEST",
            "manifest_sha256": manifest_sha,
            "document_id": pdf_sha,
            "pdf_sha256": pdf_sha,
            "page_input": page_input_ref,
            "source": source,
            "report_metadata": _report_status_metadata(),
            "research_only": True,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
        _write_state_json(doc_root / "receipt.json", receipt, state_root)
        _save_progress(state_root, doc_root, {"document_id": pdf_sha, "status": receipt["status"], "model_requests": 0})
        return receipt

    partial_source = page_status != "COMPLETE"
    acceptance = source.get("source_text_acceptance") if isinstance(source.get("source_text_acceptance"), dict) else {}
    reviewed_rows = acceptance.get("reviewed_canary_pages", []) if isinstance(acceptance, dict) else []
    accepted_boundary = None
    if reviewed_rows and isinstance(reviewed_rows[0], dict):
        accepted_boundary = reviewed_rows[0].get("accepted_markdown_boundary")
    unreviewed_ocr = bool(acceptance.get("unreviewed_ocr_pages")) if isinstance(acceptance, dict) else False
    prompt_document = {
        **source_doc,
        "_accepted_ocr_boundary": accepted_boundary,
        "_has_unreviewed_ocr": unreviewed_ocr,
    }
    chunks = _build_document_chunks(pdf_sha, pages, prompt_source=prompt_document)
    if not chunks:
        raise BatchError("PDF_TEXT_EMPTY")
    recovery_binding = continuation.get("recovery_binding") if isinstance(continuation, Mapping) else None
    partial_recovery = (
        recovery_binding.get("partial_chunk_recovery")
        if isinstance(recovery_binding, Mapping)
        else None
    )
    if isinstance(partial_recovery, Mapping):
        if not isinstance(recovery_binding, Mapping):
            raise BatchError("PPI_PARTIAL_RECOVERY_PRIOR_QUEUE_ROOT_UNAVAILABLE")
        _preflight_ppi_partial_chunk_recovery(
            source_doc,
            chunks,
            prompt_document=prompt_document,
            partial_source=partial_source,
            binding=binding,
            page_input_sha256=page_input_sha,
            page_count=len(pages),
            queue=queue,
            continuation=continuation,
            recovery_binding=recovery_binding,
        )
    elif (
        isinstance(recovery_binding, Mapping)
        and isinstance(recovery_binding.get("prior_payload"), Mapping)
    ):
        _preflight_memory_recovery_input(
            pdf_sha,
            chunks,
            page_input_sha256=page_input_sha,
            continuation=continuation,
            recovery_binding=recovery_binding,
        )
    progress: dict[str, Any] = {
        "document_id": pdf_sha,
        "pdf_sha256": pdf_sha,
        "manifest_sha256": manifest_sha,
        "page_input_sha256": page_input_sha,
        "page_extraction_status": page_status,
        "chunk_total": len(chunks),
        "chunk_states": {},
        "model_requests": 0,
    }
    _save_progress(state_root, doc_root, progress)
    reports: list[dict[str, str]] = []
    chunk_receipts: list[dict[str, Any]] = []
    stop_status: str | None = None
    tool_context = {
        "page_input_sha256": page_input_sha,
        "pages": [
            {
                "page_number": page.page_number,
                "page_total": page.page_total,
                "text": page.text,
                "text_sha256": _sha256(page.text.encode("utf-8")),
            }
            for page in pages
        ],
    }
    pdf_tool_binding = {
        "action_prompt_sha256": _sha256(pdf_research_tools.ACTION_SYSTEM_PROMPT.encode("utf-8")),
        "page_input_sha256": page_input_sha,
        "page_count": len(pages),
    }
    synthesis_recovery = continuation.get("synthesis_stage_recovery") if isinstance(continuation, Mapping) else None
    if synthesis_recovery is not None:
        if (pdf_sha != PILOT_TOOL_BUDGET_DOCUMENT_ID or page_input_sha != synthesis_recovery["descriptor"]["source_input_sha256"]
                or [c.chunk_sha256 for c in chunks] != [c["chunk_sha256"] for c in synthesis_recovery["descriptor"]["source_chunks"]]):
            raise BatchError("SYNTHESIS_RECOVERY_SOURCE_CHUNKS_MISMATCH")
        chunk_receipts = [dict(c, source_stage_reused=True) for c in synthesis_recovery["descriptor"]["source_chunks"]]
        reports = [dict(item) for item in synthesis_recovery["seed_reports"]]
        progress["chunk_states"] = {str(c.chunk_index): "SUCCEEDED_REUSED_SYNTHESIS_SOURCE" for c in chunks}
        progress["synthesis_stage_recovery"] = _synthesis_v3_ref("synthesis-recovery-v3-qualified.json")
        _save_progress(state_root, doc_root, progress)
    for chunk in ([] if synthesis_recovery is not None else chunks):
        tool_canary = bool(
            isinstance(continuation, Mapping)
            and isinstance(continuation.get("entry"), Mapping)
            and isinstance(continuation["entry"].get("tool_canary"), Mapping)
        )
        messages, envelope, payload = _document_chunk_request_material(
            source_doc,
            chunk,
            prompt_document=prompt_document,
            partial_source=partial_source,
            tool_canary=tool_canary,
            binding=binding,
            page_input_sha256=page_input_sha,
            page_count=len(pages),
        )
        payload, is_recovery_target = _bind_continuation_payload(
            payload,
            continuation,
            allow_frozen_runner_source_rebind=(
                isinstance(partial_recovery, Mapping)
                or isinstance(recovery_binding, Mapping)
                and isinstance(recovery_binding.get("prior_payload"), Mapping)
            ),
        )
        recovery_binding = continuation.get("recovery_binding") if isinstance(continuation, dict) else None
        prior_queue_root = (
            recovery_binding.get("prior_queue_root")
            if isinstance(recovery_binding, dict)
            else None
        )
        recovery_target_pending = bool(
            isinstance(recovery_binding, dict)
            and not continuation["recovery_target_reached"].is_set()
        )
        outcome = _perform_request(
            queue,
            payload,
            messages,
            binding=binding,
            identity=identity,
            identity_reader=identity_reader,
            priority_reader=priority_reader,
            request_fn=request_fn,
            sleep_fn=sleep_fn,
            stop_event=stop_event,
            prior_queue_root=prior_queue_root,
            recovery_target_pending=recovery_target_pending,
            analysis_admission=analysis_admission,
            tool_context=tool_context,
            allow_frozen_runner_source_rebind=(
                isinstance(partial_recovery, Mapping)
                or isinstance(recovery_binding, Mapping)
                and isinstance(recovery_binding.get("prior_payload"), Mapping)
            ),
        )
        if (
            isinstance(partial_recovery, Mapping)
            and chunk.chunk_index == 1
            and outcome.get("status") != "SUCCEEDED_REUSED_CONTINUATION_SOURCE"
        ):
            raise BatchError("PPI_PARTIAL_RECOVERY_SUCCESS_CHUNK_REUSE_CHANGED")
        progress["chunk_states"][str(chunk.chunk_index)] = outcome["status"]
        progress["model_requests"] += int(bool(outcome.get("attempted")))
        _save_progress(state_root, doc_root, progress)
        if outcome.get("status", "").startswith("DEFERRED"):
            stop_status = str(outcome["status"])
            chunk_receipts.append({"chunk_index": chunk.chunk_index, "chunk_sha256": chunk.chunk_sha256, **dict(outcome)})
            break
        if outcome.get("status") not in {
            "SUCCEEDED",
            "SUCCEEDED_REUSED",
            "SUCCEEDED_REUSED_R1",
            "SUCCEEDED_REUSED_CONTINUATION_SOURCE",
        }:
            stop_status = str(outcome.get("status") or "FAILED_NO_RETRY")
            chunk_receipts.append({"chunk_index": chunk.chunk_index, "chunk_sha256": chunk.chunk_sha256, **dict(outcome)})
            break
        name = f"chunk-{chunk.chunk_index:06d}-{chunk.chunk_sha256[:12]}"
        chunk_receipt = _persist_model_result(state_root, doc_root, source_doc, outcome, name=name)
        chunk_receipt.update({"chunk_index": chunk.chunk_index, "chunk_total": len(chunks), "chunk_sha256": chunk.chunk_sha256})
        chunk_receipts.append(chunk_receipt)
        report = outcome["result"]["analysis_markdown"]
        reports.append({"report_id": name, "text": report})
        if stop_event is not None and stop_event.is_set():
            stop_status = "STOPPED_GRACEFULLY"
            break
    if stop_status:
        receipt = {
            "schema": "v4.pdf_research_simple_batch.document_receipt.v1",
            "status": stop_status,
            "manifest_sha256": manifest_sha,
            "document_id": pdf_sha,
            "pdf_sha256": pdf_sha,
            "page_input": page_input_ref,
            "source": source,
            "chunks": chunk_receipts,
            "remaining_chunks_status": "NOT_RUN_OR_RESUMABLE",
            "graceful_stop_requested": stop_status == "STOPPED_GRACEFULLY",
            "report_metadata": _report_status_metadata(),
            "research_only": True,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
        _write_state_json(doc_root / "receipt.json", receipt, state_root)
        _save_progress(state_root, doc_root, {**progress, "status": stop_status, "resume_scope": "UNFINISHED_ONLY"})
        return receipt

    sectioned_long = bool(analysis_admission and analysis_admission.get("pilot", {}).get("sectioned_reuse") is not None
                          and pdf_sha == PILOT_LONG_DOCUMENT_ID)
    if sectioned_long:
        if len(chunks) != 11 or len(reports) != 11:
            raise BatchError("SECTIONED_LONG_CHUNK_SCOPE_MISMATCH")
        indexes = [_sectioned_stage_index(state_root, c, r) for c, r in zip(chunks, chunk_receipts)]
        joined = _sectioned_text(pdf_sha, reports, indexes, manual_note=None)
        reports = [{"report_id":"source-stage-sectioned", "text":joined}]
        _write_immutable(doc_root / "sectioned-components.json", _json_bytes({"chunks":chunk_receipts,"index":indexes}, newline=True), state_root)
    synth_level = 0
    current_reports = reports
    synthesis_receipts: list[dict[str, Any]] = []
    synthesis_qualifications = synthesis_recovery.get("source_qualifications") if synthesis_recovery else None
    while len(current_reports) > 1:
        synth_level += 1
        if synth_level > MAX_SYNTHESIS_LEVELS:
            raise BatchError("SYNTHESIS_DEPTH_EXCEEDED")
        groups = _pack_synthesis_groups(pdf_sha, current_reports, synth_level, accepted_boundary, reserve_contraction=True, source_qualifications=synthesis_qualifications)
        if len(groups) == len(current_reports) and all(len(group) == 1 for group in groups):
            raise BatchError("SYNTHESIS_DID_NOT_REDUCE_INPUT")
        next_reports: list[dict[str, str]] = []
        for group_index, group in enumerate(groups, start=1):
            if len(group) == 1:
                next_reports.append(dict(group[0]))
                continue
            output_budget = _synthesis_output_budget(group) if len(groups) > 1 else None
            messages = _synthesis_messages(pdf_sha, group, synth_level, accepted_boundary, output_budget, synthesis_qualifications)
            envelope = _request_envelope(messages)
            payload = _request_payload(
                source_doc,
                stage="simple_batch_synthesis_v1",
                article_id=f"{pdf_sha}:synthesis:{synth_level:02d}:{group_index:06d}:{_sha256(envelope)}",
                messages=messages,
                binding=binding,
                envelope=envelope,
                source_characters=sum(len(item["text"]) for item in group) + (len(_json_bytes(synthesis_qualifications).decode()) if synthesis_qualifications else 0),
                source_text_sha256=_sha256(_json_bytes({"reports":group,"source_qualifications":synthesis_qualifications})),
            )
            payload, is_recovery_target = _bind_continuation_payload(payload, continuation)
            recovery_binding = continuation.get("recovery_binding") if isinstance(continuation, dict) else None
            prior_queue_root = (
                recovery_binding.get("prior_queue_root")
                if isinstance(recovery_binding, dict)
                else None
            )
            recovery_target_pending = bool(
                isinstance(recovery_binding, dict)
                and not continuation["recovery_target_reached"].is_set()
            )
            if synthesis_recovery is not None and progress["model_requests"] >= 2:
                raise BatchError("SYNTHESIS_RECOVERY_REQUEST_LIMIT_EXCEEDED")
            outcome = _perform_request(
                queue,
                payload,
                messages,
                binding=binding,
                identity=identity,
                identity_reader=identity_reader,
                priority_reader=priority_reader,
                request_fn=request_fn,
                sleep_fn=sleep_fn,
                stop_event=stop_event,
                prior_queue_root=prior_queue_root,
                recovery_target_pending=recovery_target_pending,
                analysis_admission=analysis_admission,
            )
            progress["model_requests"] += int(bool(outcome.get("attempted")))
            progress.setdefault("synthesis_states", {})[f"{synth_level}:{group_index}"] = outcome["status"]
            _save_progress(state_root, doc_root, progress)
            if outcome.get("status", "").startswith("DEFERRED") or outcome.get("status") not in {
                "SUCCEEDED",
                "SUCCEEDED_REUSED",
                "SUCCEEDED_REUSED_R1",
                "SUCCEEDED_REUSED_CONTINUATION_SOURCE",
            }:
                stop_status = str(outcome.get("status") or "FAILED_NO_RETRY")
                break
            name = f"synthesis-{synth_level:02d}-{group_index:06d}-{_sha256(envelope)[:12]}"
            synthesis_receipts.append(
                _persist_model_result(state_root, doc_root, source_doc, outcome, name=name)
            )
            if output_budget is not None and len(outcome["result"]["analysis_markdown"]) > output_budget:
                raise BatchError("SYNTHESIS_OUTPUT_CHARACTER_BUDGET_EXCEEDED")
            next_reports.append({"report_id": name, "text": outcome["result"]["analysis_markdown"]})
            if stop_event is not None and stop_event.is_set():
                stop_status = "STOPPED_GRACEFULLY"
                break
        if stop_status:
            break
        _require_synthesis_progress(current_reports, next_reports)
        current_reports = next_reports
    if stop_status:
        receipt = {
            "schema": "v4.pdf_research_simple_batch.document_receipt.v1",
            "status": stop_status,
            "manifest_sha256": manifest_sha,
            "document_id": pdf_sha,
            "pdf_sha256": pdf_sha,
            "page_input": page_input_ref,
            "source": source,
            "chunks": chunk_receipts,
            "synthesis": synthesis_receipts,
            "remaining_chunks_status": "NOT_RUN_OR_RESUMABLE",
            "graceful_stop_requested": stop_status == "STOPPED_GRACEFULLY",
            "report_metadata": _report_status_metadata(),
            "research_only": True,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
        _write_state_json(doc_root / "receipt.json", receipt, state_root)
        _save_progress(state_root, doc_root, {**progress, "status": stop_status, "resume_scope": "UNFINISHED_ONLY"})
        return receipt
    if isinstance(continuation, dict) and isinstance(continuation.get("recovery_binding"), dict):
        if not continuation["recovery_target_reached"].is_set():
            raise BatchError("CONTINUATION_RECOVERY_TARGET_NOT_REACHED")
    final_report = current_reports[0]["text"]
    report_path = doc_root / "report.md"
    report_sha = _write_immutable(report_path, final_report.encode("utf-8"), state_root)
    receipt = {
        "schema": "v4.pdf_research_simple_batch.document_receipt.v1",
        "status": ("SECTIONED_SOURCE_STAGE_REPORT_SOURCE_REVIEW_PENDING" if sectioned_long else
                   "MODEL_GENERATED_TEXT_PARTIAL_SOURCE_REVIEW_PENDING" if partial_source else "MODEL_GENERATED_TEXT_COMPLETE_SOURCE_REVIEW_PENDING"),
        "manifest_sha256": manifest_sha,
        "document_id": pdf_sha,
        "pdf_sha256": pdf_sha,
        "page_input": page_input_ref,
        "source": source,
        "source_text_review_status": "SOURCE_REVIEW_PENDING",
        "chunks": chunk_receipts,
        "synthesis": synthesis_receipts,
        "synthesis_levels": synth_level,
        "model_request_count": progress["model_requests"],
        "report": {"path": str(report_path), "sha256": report_sha, "bytes": len(final_report.encode("utf-8"))},
        "report_metadata": _report_status_metadata(),
        "research_only": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    if sectioned_long:
        component_path=doc_root / "sectioned-components.json"
        receipt["sectioned_components"]={"path":str(component_path),"sha256":_sha256_file(component_path)}
    _write_state_json(doc_root / "receipt.json", receipt, state_root)
    _save_progress(state_root, doc_root, {**progress, "status": receipt["status"], "resume_scope": "UNFINISHED_ONLY"})
    return receipt


def _verified_canary_outputs(
    state_root: Path,
    manifest_sha: str,
    documents: Sequence[Mapping[str, Any]],
) -> list[dict[str, str]]:
    canary_documents = list(documents[: len(EXPECTED_CANARY_DOCUMENT_IDS)])
    if tuple(str(row.get("document_id")) for row in canary_documents) != EXPECTED_CANARY_DOCUMENT_IDS:
        raise BatchError("FROZEN_REPORT_CANARY_PREFIX_MISMATCH")
    outputs: list[dict[str, str]] = []
    for document in canary_documents:
        document_id = str(document["document_id"])
        receipt_path = state_root / "documents" / document_id / "receipt.json"
        if receipt_path.is_symlink() or not receipt_path.is_file():
            raise BatchError("REPORT_CANARY_DOCUMENT_RECEIPT_UNAVAILABLE")
        try:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            raise BatchError("REPORT_CANARY_DOCUMENT_RECEIPT_INVALID") from None
        page_input = receipt.get("page_input") if isinstance(receipt, dict) else None
        report = receipt.get("report") if isinstance(receipt, dict) else None
        if (
            not isinstance(receipt, dict)
            or receipt.get("manifest_sha256") != manifest_sha
            or receipt.get("document_id") != document_id
            or receipt.get("pdf_sha256") != document_id
            or receipt.get("status") not in {
                "USER_ACCEPTED_REUSED_REPORT",
                "MODEL_GENERATED_TEXT_COMPLETE_SOURCE_REVIEW_PENDING",
                "MODEL_GENERATED_TEXT_PARTIAL_SOURCE_REVIEW_PENDING",
            }
            or not isinstance(page_input, dict)
            or not isinstance(report, dict)
        ):
            raise BatchError("REPORT_CANARY_DOCUMENT_BINDING_MISMATCH")
        page_path = Path(str(page_input.get("path", "")))
        report_path = Path(str(report.get("path", "")))
        for path in (page_path, report_path):
            try:
                path.resolve(strict=True).relative_to(state_root.resolve(strict=True))
            except (OSError, ValueError):
                raise BatchError("REPORT_CANARY_ARTIFACT_OUTSIDE_STATE_ROOT") from None
            if path.is_symlink() or not path.is_file():
                raise BatchError("REPORT_CANARY_ARTIFACT_UNAVAILABLE")
        page_sha = _sha256_file(page_path)
        report_sha = _sha256_file(report_path)
        if page_sha != page_input.get("sha256") or report_sha != report.get("sha256"):
            raise BatchError("REPORT_CANARY_ARTIFACT_SHA_MISMATCH")
        outputs.append(
            {
                "document_id": document_id,
                "pdf_sha256": document_id,
                "page_input_sha256": page_sha,
                "report_sha256": report_sha,
            }
        )
    return outputs


def _require_report_canary_review(
    state_root: Path,
    manifest_sha: str,
    documents: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    outputs = _verified_canary_outputs(state_root, manifest_sha, documents)
    path = REPORT_CANARY_REVIEW_DEFAULT
    if path.is_symlink() or not path.is_file():
        raise BatchError("INDEPENDENT_REPORT_CANARY_REVIEW_REQUIRED")
    raw = path.read_bytes()
    try:
        review = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        raise BatchError("INDEPENDENT_REPORT_CANARY_REVIEW_INVALID") from None
    reviewed = review.get("documents") if isinstance(review, dict) else None
    if (
        not isinstance(review, dict)
        or review.get("schema") != REPORT_CANARY_REVIEW_SCHEMA
        or review.get("status") != "REPORT_CONTENT_PASS"
        or not isinstance(review.get("reviewer"), str)
        or not review["reviewer"].strip()
        or review.get("manifest_sha256") != manifest_sha
        or review.get("source_text_review_sha256") != SOURCE_CANARY_REVIEW_SHA256
        or not isinstance(reviewed, list)
        or len(reviewed) != len(outputs)
    ):
        raise BatchError("INDEPENDENT_REPORT_CANARY_REVIEW_BINDING_MISMATCH")
    for actual, expected in zip(reviewed, outputs, strict=True):
        if (
            not isinstance(actual, dict)
            or any(actual.get(name) != expected[name] for name in expected)
            or actual.get("verdict") != "PASS"
        ):
            raise BatchError("INDEPENDENT_REPORT_CANARY_REVIEW_DOCUMENT_MISMATCH")
    return {"path": str(path), "sha256": _sha256(raw), "reviewer": review["reviewer"], "documents": outputs}


def _isolate_known_report_content_failure(
    document: Mapping[str, Any],
    *,
    state_root: Path,
    manifest_sha: str,
) -> dict[str, Any] | None:
    pdf_sha = str(document.get("pdf_sha256", ""))
    if pdf_sha not in SOURCE_REJECTED_PDF_SHA256S:
        return None
    document_id = str(document.get("document_id", ""))
    review_path = REPORT_CANARY_REVIEW_DEFAULT
    review_reference: dict[str, Any] = {
        "path": str(review_path),
        "sha256": EXPECTED_REPORT_CONTENT_FAIL_REVIEW_SHA256,
        "binding_status": "CANNOT_CONFIRM",
        "document_id": document_id,
        "pdf_sha256": pdf_sha,
    }

    def isolated(failure_code: str, reason: str, *, finding: Mapping[str, Any] | None = None) -> dict[str, Any]:
        reference = dict(review_reference)
        reference["reason"] = reason
        review_reason: dict[str, Any] = {"code": reason}
        if finding is not None:
            review_reason.update(
                {
                    "finding_id": finding.get("id"),
                    "severity": finding.get("severity"),
                    "required_correction": finding.get("required_correction"),
                }
            )
        if failure_code == "REPORT_CONTENT_REVIEW_FAIL":
            reference["binding_status"] = "VERIFIED"
            reference["verdict"] = "FAIL"
        return {
            "schema": "v4.pdf_research_simple_batch.document_receipt.v1",
            "status": "FAILED_DOCUMENT_ISOLATED",
            "manifest_sha256": manifest_sha,
            "document_id": document_id,
            "pdf_sha256": pdf_sha,
            "failure_code": failure_code,
            "review_reason": review_reason,
            "review_reference": reference,
            "research_only": True,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }

    if document_id != pdf_sha:
        return isolated("CANNOT_CONFIRM_REPORT_REVIEW_BINDING", "MANIFEST_DOCUMENT_ID_MISMATCH")
    if review_path.is_symlink() or not review_path.is_file():
        return isolated("CANNOT_CONFIRM_REPORT_REVIEW_BINDING", "REPORT_REVIEW_RECEIPT_UNAVAILABLE")
    try:
        review_raw = review_path.read_bytes()
        review = json.loads(review_raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return isolated("CANNOT_CONFIRM_REPORT_REVIEW_BINDING", "REPORT_REVIEW_RECEIPT_INVALID")
    actual_review_sha = _sha256(review_raw)
    review_reference["observed_sha256"] = actual_review_sha
    if actual_review_sha != EXPECTED_REPORT_CONTENT_FAIL_REVIEW_SHA256:
        return isolated("CANNOT_CONFIRM_REPORT_REVIEW_BINDING", "REPORT_REVIEW_RECEIPT_SHA_MISMATCH")
    if (
        not isinstance(review, dict)
        or review.get("schema") != REPORT_CANARY_REVIEW_SCHEMA
        or review.get("status") != "FAIL"
        or review.get("binding_check") != "PASS"
        or not isinstance(review.get("reviewer"), str)
        or not review["reviewer"].strip()
        or manifest_sha != EXPECTED_BATCH_MANIFEST_SHA256
        or review.get("manifest_sha256") != manifest_sha
        or review.get("source_text_review_sha256") != SOURCE_CANARY_REVIEW_SHA256
        or review.get("second_source_text_review_sha256") != SLICE_CANARY_REVIEW_SHA256
    ):
        return isolated("CANNOT_CONFIRM_REPORT_REVIEW_BINDING", "REPORT_REVIEW_TOP_LEVEL_BINDING_MISMATCH")
    review_reference["observed_sha256"] = actual_review_sha
    review_reference["reviewer"] = review["reviewer"]
    review_reference["manifest_sha256"] = review["manifest_sha256"]

    reviewed_rows = review.get("documents")
    if not isinstance(reviewed_rows, list):
        return isolated("CANNOT_CONFIRM_REPORT_REVIEW_BINDING", "REPORT_REVIEW_DOCUMENT_ROWS_INVALID")
    rows_by_id = {
        row.get("document_id"): row
        for row in reviewed_rows
        if isinstance(row, dict) and isinstance(row.get("document_id"), str)
    }
    if len(rows_by_id) != len(reviewed_rows) or set(rows_by_id) != set(EXPECTED_CANARY_DOCUMENT_IDS):
        return isolated("CANNOT_CONFIRM_REPORT_REVIEW_BINDING", "REPORT_REVIEW_DOCUMENT_SET_MISMATCH")
    for known_id in EXPECTED_CANARY_DOCUMENT_IDS:
        expected_verdict = "PASS" if known_id == S18_PDF_SHA256 else "FAIL"
        row = rows_by_id[known_id]
        if row.get("pdf_sha256") != known_id or row.get("verdict") != expected_verdict:
            return isolated("CANNOT_CONFIRM_REPORT_REVIEW_BINDING", "REPORT_REVIEW_DOCUMENT_BINDING_MISMATCH")

    reviewed = rows_by_id.get(document_id)
    if not isinstance(reviewed, dict) or reviewed.get("verdict") != "FAIL":
        return isolated("CANNOT_CONFIRM_REPORT_REVIEW_BINDING", "REPORT_REVIEW_FAIL_ROW_UNAVAILABLE")
    findings = review.get("findings")
    finding = next(
        (
            row
            for row in findings
            if isinstance(findings, list)
            and isinstance(row, dict)
            and row.get("document_id") == document_id
            and row.get("severity") == "P1"
            and isinstance(row.get("required_correction"), str)
            and row["required_correction"].strip()
        ),
        None,
    ) if isinstance(findings, list) else None
    if finding is None:
        return isolated("CANNOT_CONFIRM_REPORT_REVIEW_BINDING", "REPORT_REVIEW_FINDING_UNAVAILABLE")

    receipt_path = state_root / "documents" / document_id / "receipt.json"
    if receipt_path.is_symlink() or not receipt_path.is_file():
        return isolated("CANNOT_CONFIRM_REPORT_REVIEW_BINDING", "FAILED_DOCUMENT_RECEIPT_UNAVAILABLE")
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return isolated("CANNOT_CONFIRM_REPORT_REVIEW_BINDING", "FAILED_DOCUMENT_RECEIPT_INVALID")
    page_input = receipt.get("page_input") if isinstance(receipt, dict) else None
    report = receipt.get("report") if isinstance(receipt, dict) else None
    if (
        not isinstance(receipt, dict)
        or receipt.get("schema") != "v4.pdf_research_simple_batch.document_receipt.v1"
        or receipt.get("status") != "MODEL_GENERATED_TEXT_COMPLETE_SOURCE_REVIEW_PENDING"
        or receipt.get("manifest_sha256") != manifest_sha
        or receipt.get("document_id") != document_id
        or receipt.get("pdf_sha256") != pdf_sha
        or not isinstance(page_input, dict)
        or not isinstance(report, dict)
        or page_input.get("sha256") != reviewed.get("page_input_sha256")
        or report.get("sha256") != reviewed.get("report_sha256")
    ):
        return isolated("CANNOT_CONFIRM_REPORT_REVIEW_BINDING", "FAILED_DOCUMENT_REVIEW_BINDING_MISMATCH")
    review_reference["reviewed_page_input_sha256"] = reviewed.get("page_input_sha256")
    review_reference["reviewed_report_sha256"] = reviewed.get("report_sha256")
    try:
        state_root_resolved = state_root.resolve(strict=True)
    except OSError:
        return isolated("CANNOT_CONFIRM_REPORT_REVIEW_BINDING", "BATCH_STATE_ROOT_UNAVAILABLE")
    artifact_shas: dict[str, str] = {}
    for name, artifact in (("page_input", page_input), ("report", report)):
        artifact_path = Path(str(artifact.get("path", "")))
        try:
            artifact_path.resolve(strict=True).relative_to(state_root_resolved)
        except (OSError, ValueError):
            return isolated("CANNOT_CONFIRM_REPORT_REVIEW_BINDING", "FAILED_DOCUMENT_ARTIFACT_OUTSIDE_STATE_ROOT")
        if artifact_path.is_symlink() or not artifact_path.is_file():
            return isolated("CANNOT_CONFIRM_REPORT_REVIEW_BINDING", "FAILED_DOCUMENT_ARTIFACT_UNAVAILABLE")
        try:
            artifact_sha = _sha256_file(artifact_path)
        except OSError:
            return isolated("CANNOT_CONFIRM_REPORT_REVIEW_BINDING", "FAILED_DOCUMENT_ARTIFACT_UNAVAILABLE")
        if artifact_sha != artifact.get("sha256"):
            return isolated("CANNOT_CONFIRM_REPORT_REVIEW_BINDING", "FAILED_DOCUMENT_ARTIFACT_SHA_MISMATCH")
        artifact_shas[name] = artifact_sha
    try:
        document_receipt_sha = _sha256_file(receipt_path)
    except OSError:
        return isolated("CANNOT_CONFIRM_REPORT_REVIEW_BINDING", "FAILED_DOCUMENT_RECEIPT_UNAVAILABLE")

    review_reference.update(
        {
            "binding_status": "VERIFIED",
            "verdict": "FAIL",
            "reviewer": review["reviewer"],
            "manifest_sha256": manifest_sha,
            "page_input_sha256": artifact_shas["page_input"],
            "report_sha256": artifact_shas["report"],
            "finding_id": finding.get("id"),
            "document_receipt_path": str(receipt_path),
            "document_receipt_sha256": document_receipt_sha,
        }
    )
    return isolated("REPORT_CONTENT_REVIEW_FAIL", "BOUND_REPORT_CONTENT_FAIL", finding=finding)


def _benign_defer_reason(outcome: Mapping[str, Any]) -> str | None:
    status = outcome.get("status")
    if status == "DEFERRED_ANNOUNCEMENT_PRIORITY":
        return "ANNOUNCEMENT_PRIORITY"
    if status == "DEFERRED_MODEL_LOCK_BUSY":
        return "SHARED_MODEL_LOCK_BUSY"
    if status == "DEFERRED_SOURCE_REPAIR_PENDING":
        source = outcome.get("source")
        rows = source.get("page_extraction_sources", []) if isinstance(source, dict) else []
        if any(isinstance(row, dict) and row.get("selected") == "SOURCE_REPAIR_PENDING_TICK_BUDGET" for row in rows):
            return "SOURCE_REPAIR_TICK_BUDGET"
    return None


def _wait_for_retryable_defer(
    stop_event: threading.Event,
    seconds: float,
    wait_fn: Callable[[threading.Event, float], bool] | None,
) -> bool:
    if stop_event.is_set():
        return True
    if wait_fn is not None:
        return bool(wait_fn(stop_event, seconds)) or stop_event.is_set()
    return stop_event.wait(seconds)


def _run_batch_impl(
    manifest_path: Path = DEFAULT_MANIFEST,
    *,
    state_root: Path | None = None,
    queue_factory: Callable[[Path], tuple[Any, Path]] = _create_queue,
    request_fn: Callable[..., str] = local_model.request_document_analysis,
    identity_fn: Callable[[], Mapping[str, Any]] = local_model.inspect_local_api_identity,
    priority_reader: Callable[[], Mapping[str, Any]] = _priority_snapshot,
    sleep_fn: Callable[[float], Any] = time.sleep,
    max_documents: int = 3,
    wait_fn: Callable[[threading.Event, float], bool] | None = None,
    stop_event: threading.Event,
    continuation: Mapping[str, Any] | None = None,
    prepared_text_manifest_path: Path | None = None,
    prepared_text_manifest_sha256: str | None = None,
    prepared_document_ids: Sequence[str] | None = None,
    revision_only: bool = False,
    eligible_selection_path: Path | None = None,
    eligible_selection_sha256: str | None = None,
) -> dict[str, Any]:
    admission = load_analysis_admission(eligible_selection_path, eligible_selection_sha256, prepared_sha256=str(prepared_text_manifest_sha256))
    manifest, manifest_sha, documents = load_manifest(manifest_path)
    if prepared_text_manifest_path is None or prepared_text_manifest_sha256 is None:
        raise BatchError("PREPARED_TEXT_MANIFEST_REQUIRED")
    try:
        prepared = pdf_text_preparation.verify_frozen_manifest(
            sys.modules[__name__],
            prepared_text_manifest_path,
            expected_sha256=prepared_text_manifest_sha256,
            expected_parent_sha256=manifest_sha,
        )
    except pdf_text_preparation.PreparationError as exc:
        raise BatchError(exc.code) from None
    if prepared["parent_manifest_sha256"] != manifest_sha:
        raise BatchError("PREPARED_PARENT_MANIFEST_SHA_MISMATCH")
    if continuation is None and (type(max_documents) is not int or max_documents < 1):
        raise BatchError("MAX_DOCUMENTS_INVALID")
    if continuation is None:
        if prepared_document_ids is not None and revision_only:
            raise BatchError("PREPARED_DOCUMENT_SELECTION_CONFLICT")
        prepared_rows = prepared.get("documents", {})
        if prepared_document_ids is not None:
            if len(set(prepared_document_ids)) != len(prepared_document_ids):
                raise BatchError("PREPARED_DOCUMENT_SELECTION_DUPLICATE")
            selected_ids = list(prepared_document_ids)
            if any(
                document_id not in prepared_rows
                or prepared_rows[document_id].get("manifest_row", {}).get("status") != "READY"
                for document_id in selected_ids
            ):
                raise BatchError("PREPARED_DOCUMENT_NOT_READY")
            selected_id_set = set(selected_ids)
            documents = [row for row in documents if str(row.get("document_id")) in selected_id_set]
            if [str(row.get("document_id")) for row in documents] != selected_ids:
                raise BatchError("PREPARED_DOCUMENT_SELECTION_ORDER_INVALID")
        else:
            documents = [
                row
                for row in documents
                if prepared_rows.get(str(row.get("document_id")), {}).get("manifest_row", {}).get("status") == "READY"
                and (
                    not revision_only
                    or bool(prepared_rows[str(row["document_id"])].get("manifest_row", {}).get("revision"))
                )
            ]
        if not documents:
            raise BatchError("PREPARED_DOCUMENT_SELECTION_EMPTY")
        documents = documents[:max_documents]
        if state_root is None:
            state_root = DEFAULT_STATE_ROOT.parent / f"prepared-text-{prepared['manifest_sha256'][:20]}"
        state_root = state_root.expanduser().absolute()
    else:
        if manifest_sha != continuation["plan"]["manifest_sha256"]:
            raise BatchError("CONTINUATION_MANIFEST_SHA_MISMATCH")
        state_root = Path(continuation["state_root"]).expanduser().absolute()
        documents = list(continuation["selected_documents"])
        if not documents:
            raise BatchError("CONTINUATION_SELECTION_EMPTY")
        prepared_rows = prepared.get("documents", {})
        if any(
            prepared_rows.get(str(row.get("document_id")), {}).get("manifest_row", {}).get("status") != "READY"
            for row in documents
        ):
            raise BatchError("CONTINUATION_PREPARED_DOCUMENT_NOT_READY")
    if admission is not None:
        if continuation is None:
            raise BatchError("ANALYSIS_RETAINED_DISPATCHER_REQUIRED")
        verify_analysis_plan_runtime(continuation["plan"], admission)
        for document in documents:
            guard_analysis_document(admission, str(document["document_id"]))
            verify_analysis_dispatch(str(document["document_id"]), continuation["plan_sha256"], admission)
    local_model.require_runtime_python()
    r1_root = R1_STATE_ROOT.expanduser().absolute().resolve(strict=False)
    resolved_state_root = state_root.resolve(strict=False)
    if resolved_state_root == r1_root or r1_root in resolved_state_root.parents:
        raise BatchError("READ_ONLY_R1_STATE_ROOT_CANNOT_BE_USED_FOR_BATCH_WRITES")
    documents = documents[:max_documents]
    state_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    with _batch_singleton_lock(state_root):
        evidence_root = state_root / "evidence"
        original_evidence_root = local_model.PDF_EVIDENCE_ROOT
        local_model.PDF_EVIDENCE_ROOT = evidence_root
        try:
            binding = local_model.build_request_material(RESPONSE_SCHEMA)
            if admission is not None:
                verify_analysis_runtime(admission, binding)
            elif binding.get("runtime_settings_sha256") != EXPECTED_RUNTIME_SHA256:
                raise BatchError("FROZEN_RUNTIME_SETTINGS_SHA_MISMATCH")
            expected_model_settings_sha256 = (
                continuation["expected_model_settings_sha256"]
                if continuation is not None
                else EXPECTED_MODEL_SETTINGS_SHA256
            )
            if binding.get("model_settings_sha256") != expected_model_settings_sha256:
                raise BatchError(
                    "CONTINUATION_MODEL_SETTINGS_SHA_MISMATCH"
                    if continuation is not None
                    else "FROZEN_MODEL_SETTINGS_SHA_MISMATCH"
                )
            if Path(str(binding.get("runtime_python", ""))).resolve() != local_model.RUNTIME_PYTHON.resolve():
                raise BatchError("FROZEN_RUNTIME_INTERPRETER_MISMATCH")
            if Path(str(binding.get("evidence_root", ""))).resolve(strict=False) != evidence_root.resolve(strict=False):
                raise BatchError("TEMP_EVIDENCE_ROOT_BINDING_MISMATCH")
            if continuation is not None:
                _write_immutable(state_root / "continuation-plan.json", continuation["plan_raw"], state_root)
            queue, shared_lock = queue_factory(state_root)
            identity_state: dict[str, Any] = {"status": "NOT_CHECKED"}

            def identity_reader() -> Mapping[str, Any]:
                if identity_state.get("status") == "NOT_CHECKED":
                    identity_state.update(dict(identity_fn()))
                return identity_state

            progress_path = state_root / "run-progress.json"
            prior_documents: dict[str, dict[str, Any]] = {}
            started_at = datetime.now(timezone.utc).isoformat()
            if progress_path.is_file() and not progress_path.is_symlink():
                try:
                    previous_progress = json.loads(progress_path.read_text(encoding="utf-8"))
                except (OSError, UnicodeError, json.JSONDecodeError):
                    raise BatchError("BATCH_PROGRESS_INVALID") from None
                if (
                    not isinstance(previous_progress, dict)
                    or previous_progress.get("manifest_sha256") != manifest_sha
                    or previous_progress.get("prepared_text_manifest_sha256") != prepared["manifest_sha256"]
                ):
                    raise BatchError("BATCH_PROGRESS_MANIFEST_MISMATCH")
                if continuation is not None and (
                    previous_progress.get("continuation_id") != continuation["plan"]["continuation_id"]
                    or previous_progress.get("continuation_plan_sha256") != continuation["plan_sha256"]
                    or previous_progress.get("model_settings_sha256") != expected_model_settings_sha256
                ):
                    raise BatchError("CONTINUATION_PROGRESS_BINDING_MISMATCH")
                started_at = str(previous_progress.get("started_at_utc") or started_at)
                for row in previous_progress.get("documents", []):
                    if isinstance(row, dict) and isinstance(row.get("document_id"), str):
                        prior_documents[row["document_id"]] = row
            batch_receipt: dict[str, Any] = {
                "schema": "v4.pdf_research_simple_batch.run_receipt.v1",
                "status": "RUNNING",
                "started_at_utc": started_at,
                "last_resumed_at_utc": datetime.now(timezone.utc).isoformat(),
                "manifest_path": str(manifest_path),
                "manifest_sha256": manifest_sha,
                "prepared_text_manifest_path": str(prepared["path"]),
                "prepared_text_manifest_sha256": prepared["manifest_sha256"],
                "document_count": len(documents),
                "manifest_document_count": manifest.get("document_count", len(manifest.get("documents", []))),
                "max_documents_this_tick": len(documents) if continuation is not None else max_documents,
                "queue_root": str(queue.state_root),
                "shared_model_lock_path": str(shared_lock),
                "model_id": local_model.MODEL_ID,
                "runtime_settings_sha256": binding["runtime_settings_sha256"],
                "model_settings_sha256": binding["model_settings_sha256"],
                "source_review_default": "SOURCE_REVIEW_PENDING",
                "research_only": True,
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
                "documents": list(prior_documents.values()),
                "retryable_defer_waits": [],
            }
            if continuation is not None:
                batch_receipt.update(
                    {
                        "continuation_id": continuation["plan"]["continuation_id"],
                        "continuation_plan_sha256": continuation["plan_sha256"],
                        "selected_prior_statuses": {
                            document_id: entry["prior_status"]
                            for document_id, entry in continuation["selected_entries"].items()
                        },
                    }
                )
            _write_state_json(progress_path, batch_receipt, state_root)
            stop_batch = False
            repair_budget = {"remaining": MAX_REPAIR_PAGES_PER_TICK}
            for document in documents:
                if stop_event.is_set():
                    stop_batch = True
                    batch_receipt["stop_reason"] = "SIGTERM_REQUESTED"
                    break
                doc_sha = str(document["pdf_sha256"])
                doc_continuation: dict[str, Any] | None = None
                selected_entry: Mapping[str, Any] | None = None
                preserve_existing_success = False
                existing_receipt_path = state_root / "documents" / doc_sha / "receipt.json"
                if existing_receipt_path.is_file() and not existing_receipt_path.is_symlink():
                    try:
                        existing_receipt = json.loads(existing_receipt_path.read_text(encoding="utf-8"))
                    except (OSError, UnicodeError, json.JSONDecodeError):
                        existing_receipt = None
                    preserve_existing_success = (
                        isinstance(existing_receipt, dict)
                        and existing_receipt.get("status") in {
                            "USER_ACCEPTED_REUSED_REPORT",
                            "MODEL_GENERATED_TEXT_COMPLETE_SOURCE_REVIEW_PENDING",
                            "MODEL_GENERATED_TEXT_PARTIAL_SOURCE_REVIEW_PENDING",
                        }
                    )
                if continuation is not None:
                    selected_entry = continuation["selected_entries"][doc_sha]
                    doc_continuation = {
                        "plan": continuation["plan"],
                        "plan_sha256": continuation["plan_sha256"],
                        "entry": selected_entry,
                        "synthesis_stage_recovery": continuation.get("synthesis_stage_recovery"),
                    }
                    recovery_binding = continuation["recovery_bindings"].get(doc_sha)
                    if recovery_binding is not None:
                        doc_continuation.update(
                            {
                                "recovery_binding": recovery_binding,
                                "recovery_target_reached": threading.Event(),
                            }
                        )
                retry_count = 0
                while True:
                    try:
                        outcome = _isolate_known_report_content_failure(
                            document,
                            state_root=state_root,
                            manifest_sha=manifest_sha,
                        )
                        if outcome is None:
                            outcome = _run_document(
                                document,
                                manifest_sha=manifest_sha,
                                state_root=state_root,
                                queue=queue,
                                binding=binding,
                                identity=identity_state,
                                priority_reader=priority_reader,
                                identity_reader=identity_reader,
                                identity_state=identity_state,
                                request_fn=request_fn,
                                sleep_fn=sleep_fn,
                                stop_event=stop_event,
                                repair_budget=repair_budget,
                                continuation=doc_continuation,
                                prepared_manifest=prepared,
                                analysis_admission=admission,
                            )
                    except Exception as exc:
                        code = getattr(exc, "code", None) or type(exc).__name__
                        outcome = {
                            "schema": "v4.pdf_research_simple_batch.document_receipt.v1",
                            "status": "FAILED_DOCUMENT_ISOLATED",
                            "manifest_sha256": manifest_sha,
                            "document_id": doc_sha,
                            "pdf_sha256": doc_sha,
                            "failure_code": str(code)[:96],
                            "report_metadata": _report_status_metadata(),
                            "research_only": True,
                            "production_allowed": False,
                            "buy_gate_updated": False,
                            "orders_sent": False,
                        }
                        doc_root = state_root / "documents" / doc_sha
                        doc_root.mkdir(mode=0o700, parents=True, exist_ok=True)
                        existing_receipt_path = doc_root / "receipt.json"
                        if existing_receipt_path.is_file() and not existing_receipt_path.is_symlink():
                            try:
                                existing_receipt = json.loads(existing_receipt_path.read_text(encoding="utf-8"))
                                preserve_existing_success = (
                                    isinstance(existing_receipt, dict)
                                    and existing_receipt.get("status") in {
                                        "SECTIONED_SOURCE_STAGE_REPORT_SOURCE_REVIEW_PENDING",
                                        "USER_ACCEPTED_REUSED_REPORT",
                                        "MODEL_GENERATED_TEXT_COMPLETE_SOURCE_REVIEW_PENDING",
                                        "MODEL_GENERATED_TEXT_PARTIAL_SOURCE_REVIEW_PENDING",
                                    }
                                )
                            except (OSError, UnicodeError, json.JSONDecodeError):
                                preserve_existing_success = False
                        if preserve_existing_success:
                            outcome = {
                                "document_id": doc_sha,
                                "status": "CANNOT_CONFIRM_EXISTING_SUCCESS_PRESERVED",
                                "receipt_path": str(existing_receipt_path),
                                "failure_code": str(code)[:96],
                            }
                        else:
                            _write_state_json(doc_root / "receipt.json", outcome, state_root)
                            _save_progress(state_root, doc_root, outcome)

                    defer_reason = _benign_defer_reason(outcome)
                    if defer_reason is None or stop_event.is_set():
                        break
                    delay = min(
                        RETRYABLE_DEFER_BACKOFF_BASE_SECONDS * (2**retry_count),
                        RETRYABLE_DEFER_BACKOFF_MAX_SECONDS,
                    )
                    wait_record = {
                        "document_id": doc_sha,
                        "deferred_status": outcome.get("status"),
                        "reason": defer_reason,
                        "retry_count": retry_count + 1,
                        "delay_seconds": delay,
                        "wait_status": "WAITING",
                    }
                    batch_receipt.setdefault("retryable_defer_waits", []).append(wait_record)
                    prior_documents[doc_sha] = {
                        "document_id": doc_sha,
                        "status": outcome.get("status"),
                        "receipt_path": str(state_root / "documents" / doc_sha / "receipt.json"),
                    }
                    batch_receipt.update(
                        {
                            "status": "WAITING_RETRYABLE_DEFER",
                            "current_document_id": doc_sha,
                            "current_defer_reason": defer_reason,
                            "current_retry_delay_seconds": delay,
                            "documents": [prior_documents[key] for key in prior_documents],
                        }
                    )
                    _write_state_json(progress_path, batch_receipt, state_root)
                    interrupted = _wait_for_retryable_defer(stop_event, delay, wait_fn)
                    wait_record["wait_status"] = "STOPPED" if interrupted else "ELAPSED"
                    if interrupted:
                        if not stop_event.is_set():
                            stop_event.set()
                        batch_receipt["stop_reason"] = "SIGTERM_REQUESTED_DURING_RETRYABLE_WAIT"
                        break
                    repair_budget = {"remaining": MAX_REPAIR_PAGES_PER_TICK}
                    retry_count += 1
                    batch_receipt["status"] = "RUNNING"
                    for key in ("current_document_id", "current_defer_reason", "current_retry_delay_seconds"):
                        batch_receipt.pop(key, None)
                    _write_state_json(progress_path, batch_receipt, state_root)
                if identity_state.get("status") != "NOT_CHECKED":
                    batch_receipt["model_identity"] = dict(identity_state)
                prepared_row = prepared["documents"].get(doc_sha, {}).get("manifest_row", {})
                outcome = dict(outcome)
                outcome["prepared_text_manifest_sha256"] = prepared["manifest_sha256"]
                outcome["prepared_text_page_input_sha256"] = prepared["documents"].get(doc_sha, {}).get("page_input_sha256")
                if prepared_row.get("revision"):
                    outcome["source_text_revision"] = prepared_row["revision"]
                    outcome["supersedes"] = prepared_row["revision"].get("supersedes", [])
                if not preserve_existing_success:
                    receipt_path = state_root / "documents" / doc_sha / "receipt.json"
                    _write_state_json(receipt_path, outcome, state_root)
                recovery_of = None
                if continuation is not None and selected_entry is not None:
                    recovery = selected_entry.get("recovery")
                    if isinstance(recovery, dict):
                        recovery_of = {
                            "generation": 1,
                            "prior_idempotency_key": recovery["prior_queue_idempotency_key"],
                            "prior_payload_sha256": recovery["prior_payload_sha256"],
                            "prior_raw_sha256": recovery["prior_raw_sha256"],
                        }
                    outcome = dict(outcome)
                    outcome["continuation"] = {
                        "continuation_id": continuation["plan"]["continuation_id"],
                        "plan_sha256": continuation["plan_sha256"],
                        "manifest_sha256": manifest_sha,
                        "runtime_settings_sha256": binding["runtime_settings_sha256"],
                        "model_settings_sha256": binding["model_settings_sha256"],
                        "selected_prior_status": selected_entry["prior_status"],
                        "recovery_of": recovery_of,
                    }
                    if not preserve_existing_success:
                        _write_state_json(
                            state_root / "documents" / doc_sha / "receipt.json",
                            outcome,
                            state_root,
                        )
                progress_row = {
                    "document_id": doc_sha,
                    "status": outcome.get("status"),
                    "prepared_text_manifest_sha256": prepared["manifest_sha256"],
                    "prepared_text_page_input_sha256": prepared["documents"].get(doc_sha, {}).get("page_input_sha256"),
                }
                if prepared_row.get("revision"):
                    progress_row["source_text_revision"] = prepared_row["revision"]
                    progress_row["supersedes"] = prepared_row["revision"].get("supersedes", [])
                if continuation is not None and selected_entry is not None:
                    progress_row.update(
                        {
                            "continuation_id": continuation["plan"]["continuation_id"],
                            "continuation_plan_sha256": continuation["plan_sha256"],
                            "manifest_sha256": manifest_sha,
                            "runtime_settings_sha256": binding["runtime_settings_sha256"],
                            "model_settings_sha256": binding["model_settings_sha256"],
                            "selected_prior_status": selected_entry["prior_status"],
                            "recovery_of": recovery_of,
                        }
                    )
                if outcome.get("review_reference"):
                    progress_row.update(
                        {
                            "failure_code": outcome.get("failure_code"),
                            "review_reason": outcome.get("review_reason"),
                            "review_reference": outcome.get("review_reference"),
                        }
                    )
                else:
                    progress_row["receipt_path"] = str(state_root / "documents" / doc_sha / "receipt.json")
                prior_documents[doc_sha] = progress_row
                batch_receipt["documents"] = [prior_documents[key] for key in prior_documents]
                _write_state_json(state_root / "run-progress.json", batch_receipt, state_root)
                if outcome.get("status") == "STOPPED_GRACEFULLY" or stop_event.is_set():
                    stop_batch = True
                    batch_receipt["stop_reason"] = "SIGTERM_REQUESTED"
                    break
                if str(outcome.get("status", "")).startswith("DEFERRED"):
                    stop_batch = True
                    batch_receipt["stop_reason"] = outcome.get("status")
                    break
            batch_receipt["status"] = (
                "STOPPED_GRACEFULLY"
                if stop_event.is_set()
                else "DEFERRED" if stop_batch else "COMPLETED_WITH_PER_DOCUMENT_STATES"
            )
            batch_receipt["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
            _write_state_json(state_root / "run-progress.json", batch_receipt, state_root)
            return batch_receipt
        finally:
            local_model.PDF_EVIDENCE_ROOT = original_evidence_root



def _analysis_ref(reference: Any, *, root: Path | None = None, parse_json: bool = True) -> tuple[dict[str, Any], bytes]:
    if not isinstance(reference, dict) or set(reference) != {"path", "sha256"}:
        raise BatchError("ANALYSIS_REFERENCE_INVALID")
    path = Path(str(reference["path"]))
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise BatchError("ANALYSIS_REFERENCE_UNAVAILABLE")
    if path.resolve() != path.absolute() or (root is not None and not path.resolve().is_relative_to(root.resolve())):
        raise BatchError("ANALYSIS_REFERENCE_PATH_UNSAFE")
    raw = path.read_bytes()
    if _sha256(raw) != reference["sha256"]:
        raise BatchError("ANALYSIS_REFERENCE_SHA_MISMATCH")
    if not parse_json:
        return {}, raw
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeError):
        raise BatchError("ANALYSIS_REFERENCE_INVALID") from None
    if not isinstance(value, dict):
        raise BatchError("ANALYSIS_REFERENCE_INVALID")
    return value, raw


def verify_analysis_runtime(admission: Mapping[str, Any], binding: Mapping[str, Any] | None = None) -> None:
    proof, _ = _analysis_ref(admission["value"]["runtime_adoption"])
    if (proof.get("schema") != "v4.pdf_research.runtime_adoption.v1"
            or proof.get("status") != "ROOT_ADOPTED"
            or proof.get("identity_runtime_sha256") != EXPECTED_RUNTIME_SHA256
            or proof.get("execution_runtime_sha256") != ANALYSIS_RUNTIME_SHA256
            or proof.get("model_settings_sha256") != CONTINUATION_CANDIDATE_SETTINGS_SHA256):
        raise BatchError("ANALYSIS_RUNTIME_ADOPTION_INVALID")
    transition, _ = _analysis_ref(proof["transition"])
    if (proof["transition"]["sha256"] != ANALYSIS_RUNTIME_RECEIPT_SHA256
            or transition.get("status") != "APPLIED_HEALTH_CEILING_VERIFIED"
            or transition.get("settings_before_sha256") != EXPECTED_RUNTIME_SHA256
            or transition.get("settings_after_sha256") != ANALYSIS_RUNTIME_SHA256):
        raise BatchError("ANALYSIS_RUNTIME_TRANSITION_INVALID")
    modules = local_model.load_shared_modules()
    settings_path = Path(modules.runner.OMLX_SETTINGS_PATH)
    settings_ref = {"path": str(settings_path), "sha256": ANALYSIS_RUNTIME_SHA256}
    settings, _ = _analysis_ref(settings_ref)
    model_path = Path(modules.runner.OMLX_MODEL_SETTINGS_PATH)
    if (model_path.is_symlink() or _sha256(model_path.read_bytes()) != CONTINUATION_CANDIDATE_SETTINGS_SHA256
            or settings.get("memory") != transition.get("memory_after")
            or _sha256(local_model.canonical_json({k: v for k, v in settings.items() if k != "memory"})) != transition.get("non_memory_settings_sha256")
            or _sha256((settings_path.parent.parent / "start_omlx.sh").read_bytes()) != transition.get("launcher_sha256")):
        raise BatchError("ANALYSIS_RUNTIME_DRIFT")
    if binding is not None and (binding.get("runtime_settings_sha256") != ANALYSIS_RUNTIME_SHA256
            or binding.get("model_settings_sha256") != CONTINUATION_CANDIDATE_SETTINGS_SHA256
            or binding.get("model_id") != local_model.MODEL_ID):
        raise BatchError("ANALYSIS_REQUEST_RUNTIME_MISMATCH")



def verify_analysis_plan_runtime(plan: Mapping[str, Any], admission: Mapping[str, Any], binding: Mapping[str, Any] | None = None) -> None:
    if plan.get("execution_runtime_settings_sha256") != ANALYSIS_RUNTIME_SHA256:
        raise BatchError("ANALYSIS_PLAN_EXECUTION_RUNTIME_MISMATCH")
    verify_analysis_runtime(admission, binding)


def load_analysis_admission(
    selection_path: Path | None,
    expected_sha256: str | None,
    *,
    prepared_sha256: str,
    authorization_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if selection_path is None or expected_sha256 is None:
        raise BatchError("ANALYSIS_ADMISSION_REQUIRED")
    if selection_path.absolute() != ANALYSIS_SELECTION_PATH.absolute():
        raise BatchError("ANALYSIS_SELECTION_PATH_MISMATCH")
    reference = {"path": str(selection_path), "sha256": expected_sha256}
    value, _ = _analysis_ref(reference, root=ANALYSIS_ROOT)
    if authorization_context is None:
        from ops import run_pdf_research_remaining_once as dispatcher
        authorization_context = dispatcher.load_and_validate_authorization()
    auth = authorization_context["authorization"]
    if (auth.get("analysis_admission") != reference
            or auth.get("prepared_text_manifest_sha256") != prepared_sha256
            or value.get("schema") != ANALYSIS_SCHEMA or value.get("status") != "ROOT_ADOPTED"
            or value.get("parent_manifest_sha256") != EXPECTED_BATCH_MANIFEST_SHA256
            or value.get("prepared_text_manifest_sha256") != prepared_sha256
            or value.get("canary_document_id") != ANALYSIS_CANARY_ID):
        raise BatchError("ANALYSIS_ADMISSION_BINDING_MISMATCH")
    base, _ = _analysis_ref({"path": str(ANALYSIS_ROOT / "preflight-selection.json"), "sha256": ANALYSIS_BASE_SELECTION_SHA256}, root=ANALYSIS_ROOT)
    classification, _ = _analysis_ref({"path": str(ANALYSIS_CLASSIFICATION_REVIEW_PATH), "sha256": ANALYSIS_CLASSIFICATION_REVIEW_SHA256})
    if classification.get("verdict") != "PASS":
        raise BatchError("ANALYSIS_CLASSIFICATION_REVIEW_REQUIRED")
    rows = value.get("documents")
    expected = base.get("eligible_documents")
    if (not isinstance(rows, list) or len(rows) != 18 or rows != expected
            or rows[0].get("document_id") != ANALYSIS_CANARY_ID
            or len({r.get("document_id") for r in rows}) != 18
            or any(r.get("prior_status") != "UNPROCESSED" or r.get("source_or_content_unverified") is not False
                or r.get("reviewer_primary_type") != "券商/研究机构研究" for r in rows)):
        raise BatchError("ANALYSIS_ELIGIBILITY_MISMATCH")
    admission = {"value": value, "reference": reference, "documents": {r["document_id"]: r for r in rows},
                 "authorization_sha256": authorization_context["authorization_sha256"]}
    verify_analysis_runtime(admission)
    admission["allowed_ids"] = [ANALYSIS_CANARY_ID]
    if auth.get("pilot17_adoption") is not None:
        admission["pilot"] = load_research_pilot(admission, authorization_context)
        admission["allowed_ids"] = admission["pilot"]["allowed_ids"]
        return admission
    review_path = ANALYSIS_REVIEW_PATH
    if review_path.exists():
        _verify_analysis_canary_review(admission, review_path)
        admission["allowed_ids"] = [r["document_id"] for r in rows]
    else:
        from ops import run_pdf_research_remaining_once as dispatcher
        journal_path = dispatcher.EVIDENCE_ROOT / "dispatch.jsonl"
        if journal_path.is_file():
            if journal_path.is_symlink():
                raise BatchError("ANALYSIS_DISPATCH_PATH_UNSAFE")
            events = [json.loads(line) for line in journal_path.read_bytes().splitlines()]
            if any(e.get("event") == "reconciled" and e.get("document_id") == ANALYSIS_CANARY_ID for e in events):
                raise BatchError("ANALYSIS_CANARY_CONTENT_REVIEW_REQUIRED")
    return admission


def _verify_analysis_canary_review(admission: Mapping[str, Any], path: Path) -> None:
    # The reviewer authors this fixed, separately owned receipt after the first live result.
    if path.is_symlink() or not path.is_file() or path.resolve() != path.absolute():
        raise BatchError("ANALYSIS_CANARY_REVIEW_INVALID")
    review = json.loads(path.read_bytes())
    if (not isinstance(review, dict) or review.get("schema") != "v4.pdf_research.canary_content_review.v1"
            or review.get("status") != "REPORT_CONTENT_PASS"
            or review.get("reviewer") != "/root/pdf_model_analysis_reviewer"
            or review.get("selection_sha256") != admission["reference"]["sha256"]
            or review.get("document_id") != ANALYSIS_CANARY_ID
            or review.get("page_input") != admission["documents"][ANALYSIS_CANARY_ID]["page_input"]):
        raise BatchError("ANALYSIS_CANARY_CONTENT_PASS_REQUIRED")
    _verify_analysis_canary_artifacts(admission, review)


def _verify_analysis_canary_artifacts(admission: Mapping[str, Any], review: Mapping[str, Any]) -> None:
    from ops import run_pdf_research_remaining_once as dispatcher
    journal_path = dispatcher.EVIDENCE_ROOT / "dispatch.jsonl"
    events = [json.loads(line) for line in journal_path.read_bytes().splitlines()]
    terminal = [e for e in events if e.get("event") == "reconciled" and e.get("document_id") == ANALYSIS_CANARY_ID]
    if len(terminal) != 1 or terminal[0].get("status") != "MODEL_GENERATED_TEXT_COMPLETE_SOURCE_REVIEW_PENDING":
        raise BatchError("ANALYSIS_CANARY_TERMINAL_REQUIRED")
    event = terminal[0]
    receipt_ref = {"path": event.get("receipt_path"), "sha256": event.get("receipt_sha256")}
    if review.get("receipt") != receipt_ref:
        raise BatchError("ANALYSIS_CANARY_RECEIPT_MISMATCH")
    receipt, _ = _analysis_ref(receipt_ref)
    report = review.get("report")
    if not isinstance(report, dict) or set(report) != {"path", "sha256"}:
        raise BatchError("ANALYSIS_CANARY_REPORT_INVALID")
    expected_report = Path(event["state_root"]) / "documents" / ANALYSIS_CANARY_ID / "report.md"
    if (Path(str(report["path"])) != expected_report or expected_report.is_symlink()
            or _sha256(expected_report.read_bytes()) != report["sha256"]
            or receipt.get("status") != "MODEL_GENERATED_TEXT_COMPLETE_SOURCE_REVIEW_PENDING"
            or review.get("source_pages_reviewed") != [1, 2, 3]):
        raise BatchError("ANALYSIS_CANARY_REPORT_MISMATCH")



def verify_analysis_dispatch(document_id: str, plan_sha256: str, admission: Mapping[str, Any] | None = None) -> None:
    from ops import run_pdf_research_remaining_once as dispatcher
    journal_path = dispatcher.EVIDENCE_ROOT / "dispatch.jsonl"
    if journal_path.is_symlink() or not journal_path.is_file():
        raise BatchError("ANALYSIS_RETAINED_DISPATCH_REQUIRED")
    raw = journal_path.read_bytes()
    if not raw.endswith(b"\n"):
        raise BatchError("ANALYSIS_DISPATCH_TRUNCATED")
    events = [json.loads(line) for line in raw.splitlines()]
    events = [e for e in events if e.get("document_id") == document_id]
    plan_count = len({e.get("plan_sha256") for e in events if e.get("event") == "plan_created"})
    expected_count = 1
    recovery = (admission or {}).get("pilot", {}).get("recovery")
    synthesis = (admission or {}).get("pilot", {}).get("synthesis_recovery")
    if synthesis is not None and document_id == PILOT_TOOL_BUDGET_DOCUMENT_ID:
        if plan_sha256 != synthesis["plan_reference"]["sha256"]:
            raise BatchError("ANALYSIS_SYNTHESIS_PLAN_NOT_CURRENT")
        expected_count = 3
    elif recovery is not None and document_id == PILOT_TOOL_BUDGET_DOCUMENT_ID:
        if plan_sha256 != recovery["plan_reference"]["sha256"]:
            raise BatchError("ANALYSIS_RECOVERY_PLAN_NOT_CURRENT")
        expected_count = 2
    if (not events or events[-1].get("event") != "dispatch_intent"
            or events[-1].get("plan_sha256") != plan_sha256 or plan_count != expected_count):
        raise BatchError("ANALYSIS_DISPATCH_NOT_CURRENT")


def guard_analysis_document(admission: Mapping[str, Any], document_id: str, *, binding: Mapping[str, Any] | None = None) -> None:
    _analysis_ref(admission["reference"], root=ANALYSIS_ROOT)
    from ops import run_pdf_research_remaining_once as dispatcher
    auth_path = dispatcher.AUTHORIZATION_PATH
    if auth_path.is_symlink() or _sha256(auth_path.read_bytes()) != admission["authorization_sha256"]:
        raise BatchError("ANALYSIS_AUTHORIZATION_DRIFT")
    if admission.get("pilot") is not None:
        current = load_research_pilot(admission, dispatcher.load_and_validate_authorization())
        if current["reference"] != admission["pilot"]["reference"] or document_id not in current["allowed_ids"]:
            raise BatchError("PILOT_PHASE_OR_ADOPTION_DRIFT")
    if document_id not in admission["allowed_ids"] or document_id == ANALYSIS_ISOLATED_ID:
        raise BatchError("ANALYSIS_DOCUMENT_NOT_ADMITTED")
    if admission.get("pilot", {}).get("sectioned_reuse") is not None and document_id == PILOT_TOOL_BUDGET_DOCUMENT_ID:
        raise BatchError("SECTIONED_MEDIUM_MODEL_POST_FORBIDDEN")
    row = admission["documents"][document_id]
    receipt, _ = _analysis_ref(row["prepared_receipt"])
    _analysis_ref(row["page_input"])
    if (receipt.get("status") != "READY" or receipt.get("document_id") != document_id
            or receipt.get("pdf_sha256") != document_id):
        raise BatchError("ANALYSIS_DOCUMENT_NOT_READY")
    verify_analysis_runtime(admission, binding)


# A bounded continuation of the same authority. Prior receipts remain immutable.
RESEARCH_PILOT_ROOT = Path("/Users/lexi/Desktop/学习/agents调试/V4_PDF_RESEARCH_PILOT_20261020_R1")
PILOT_STRATA_SHA256 = "b86486207af8219b0841590d0526a1e54cad10d2e74e7ffb67cb5e9b8eb7c18f"
PILOT_PACKAGE_PLAN_SHA256 = "d0d33282482012e20de4d5f88be1188817e703238b895aed394baa7432e2a3c4"
PILOT_DECISION_SHA256 = "dc4c21aa6d205d0d5413495a2d8a87709b92ac1280708a75f440c43c63fa1a67"
PILOT_PREVIOUS_AUTH_SHA256 = "26fce1aec7938b60d0e2cea8f7f64aa12b5d2647a83ec0b221285fd620abcfae"
PILOT_JOURNAL_PREFIX_SHA256 = "ea6afb0223fa70e3fb3142be6c4dc53b0622c231a49aad1c10e0c506a83aa4c6"
PILOT_ORIGINAL_REVIEW_SHA256 = "11f61a2736f4b1f401ac9d5ee48578607ac45e9adb177ea3dab837ad51c6375f"
PILOT_ERRATUM_REVIEW_SHA256 = "d072ad3050cc0cb61d17988828af9a113613842b276b4f562a4f2c4448f21180"


def _pilot_fixed(path: Path, expected_sha: str) -> dict[str, Any]:
    value, _ = _analysis_ref({"path": str(path), "sha256": expected_sha})
    return value


def verify_source_erratum_pair(admission: Mapping[str, Any]) -> dict[str, Any]:
    original = _pilot_fixed(ANALYSIS_REVIEW_PATH, PILOT_ORIGINAL_REVIEW_SHA256)
    combined = _pilot_fixed(ANALYSIS_ROOT / "first-report-execution/erratum-content-review.json", PILOT_ERRATUM_REVIEW_SHA256)
    if (original.get("status") != "REPORT_CONTENT_FAIL"
            or original.get("document_id") != ANALYSIS_CANARY_ID
            or original.get("page_input") != admission["documents"][ANALYSIS_CANARY_ID]["page_input"]
            or original.get("selection_sha256") != admission["reference"]["sha256"]
            or combined.get("status") != "REPORT_WITH_ERRATUM_PASS"
            or combined.get("reviewer") != "/root/pdf_model_analysis_reviewer"
            or original.get("reviewer") != "/root/pdf_model_analysis_reviewer"
            or combined.get("original_model_content_review") != {"path": str(ANALYSIS_REVIEW_PATH), "sha256": PILOT_ORIGINAL_REVIEW_SHA256, "status": "REPORT_CONTENT_FAIL"}):
        raise BatchError("PILOT_SOURCE_ERRATUM_REVIEW_MISMATCH")
    # Reuse the original terminal identity checks without promoting its verdict.
    _verify_analysis_canary_artifacts(admission, original)
    raw_ref = combined.get("original_model_report", {})
    display_ref = combined.get("display", {})
    if ({k: raw_ref.get(k) for k in ("path", "sha256")} != original.get("report")
            or combined.get("checks", {}).get("prefix_bytes") != 448):
        raise BatchError("PILOT_SOURCE_ERRATUM_REPORT_MISMATCH")
    _, raw = _analysis_ref(original["report"], parse_json=False)
    display_path = ANALYSIS_ROOT / "first-report-execution/report-with-erratum.md"
    if display_ref.get("path") != str(display_path):
        raise BatchError("PILOT_SOURCE_ERRATUM_DISPLAY_PATH")
    _, display = _analysis_ref({k: display_ref.get(k) for k in ("path", "sha256")}, root=ANALYSIS_ROOT, parse_json=False)
    prefix = display[:448].decode("utf-8")
    if (display[448:] != raw or not all(t in prefix for t in ("未来6个月内", "原PDF第2页", "验收补充", "非重新模型生成"))):
        raise BatchError("PILOT_SOURCE_ERRATUM_BYTES_MISMATCH")
    return {"original": "REPORT_CONTENT_FAIL", "display": "REPORT_WITH_ERRATUM_PASS"}


def load_research_pilot(admission: Mapping[str, Any], auth_context: Mapping[str, Any]) -> dict[str, Any]:
    from ops import run_pdf_research_remaining_once as dispatcher
    auth = auth_context["authorization"]
    reference = auth.get("pilot17_adoption")
    expected_path = dispatcher.CONTINUATION_ROOT / "ROOT_PDF_PILOT17_EXECUTION_ADOPTION_20261020_R1.json"
    v2_path = dispatcher.CONTINUATION_ROOT / "ROOT_PDF_PILOT17_ERRATA_ADOPTION_20261020_R1.json"
    v3_path = dispatcher.CONTINUATION_ROOT / "ROOT_PDF_PILOT_SYNTHESIS_RECOVERY_ADOPTION_20261020_R1.json"
    v4_path = dispatcher.CONTINUATION_ROOT / "ROOT_PDF_PILOT_PACKAGE_COMPAT_ADOPTION_20261020_R1.json"
    is_v4 = isinstance(reference, dict) and reference.get("path") == str(v4_path)
    is_v3 = isinstance(reference, dict) and reference.get("path") in {str(v3_path), str(v4_path)}
    is_v2 = isinstance(reference, dict) and reference.get("path") in {str(v2_path), str(v3_path), str(v4_path)}
    if not isinstance(reference, dict) or reference.get("path") not in {str(expected_path), str(v2_path), str(v3_path), str(v4_path)}:
        raise BatchError("PILOT_ADOPTION_REQUIRED")
    adopted, _ = _analysis_ref(reference, root=dispatcher.CONTINUATION_ROOT)
    if (adopted.get("status") != "ROOT_ADOPTED" or adopted.get("schema") != ("v4.pdf_research.pilot_adoption.v2" if is_v2 else "v4.pdf_research.pilot_adoption.v1")
            or adopted.get("previous_authorization") != {"path": str(dispatcher.CONTINUATION_ROOT / "ROOT_REMAINING_EXECUTION_AUTHORIZATION_PRE_PILOT_20261020_R1.json"), "sha256": PILOT_PREVIOUS_AUTH_SHA256}
            or adopted.get("journal_event_count") != 45 or adopted.get("journal_prefix_sha256") != PILOT_JOURNAL_PREFIX_SHA256
            or adopted.get("selection") != admission["reference"]
            or adopted.get("prepared_text_manifest_sha256") != admission["value"]["prepared_text_manifest_sha256"]):
        raise BatchError("PILOT_ADOPTION_BINDING_MISMATCH")
    _analysis_ref(adopted["previous_authorization"], root=dispatcher.CONTINUATION_ROOT)
    _pilot_fixed(RESEARCH_PILOT_ROOT / "controller-model-implementation-decision.json", PILOT_DECISION_SHA256)
    strata = _pilot_fixed(RESEARCH_PILOT_ROOT / "model/stratified17.json", PILOT_STRATA_SHA256)
    _pilot_fixed(RESEARCH_PILOT_ROOT / "model/package-input-plan.json", PILOT_PACKAGE_PLAN_SHA256)
    if (adopted.get("stratified17") != {"path": str(RESEARCH_PILOT_ROOT / "model/stratified17.json"), "sha256": PILOT_STRATA_SHA256}
            or adopted.get("package_input_plan") != {"path": str(RESEARCH_PILOT_ROOT / "model/package-input-plan.json"), "sha256": PILOT_PACKAGE_PLAN_SHA256}):
        raise BatchError("PILOT_INPUT_PLAN_MISMATCH")
    expected_sources = {"ops/run_pdf_research_batch.py": Path(__file__), "ops/run_pdf_research_remaining_once.py": Path(dispatcher.__file__),
                        "ops/run_pdf_research_package_once.py": Path(__file__).with_name("run_pdf_research_package_once.py")}
    if is_v2:
        expected_sources["infrastructure/pdf_research_tools.py"] = Path(pdf_research_tools.__file__)
        _pilot_fixed(RESEARCH_PILOT_ROOT / "controller-delta-v2-decision.json", PILOT_V2_DECISION_SHA256)
    if set(adopted.get("sources", {})) != set(expected_sources):
        raise BatchError("PILOT_SOURCE_SET_MISMATCH")
    for name, path in expected_sources.items():
        if adopted["sources"].get(name) != _sha256_file(path):
            raise BatchError("PILOT_SOURCE_SHA_MISMATCH")
    review = dispatcher._verified_json_evidence(auth["reviewer_receipt"], expected_statuses={"REVIEWED_PASS"}, code="PILOT_SOURCE_REVIEW_REQUIRED")
    if review.get("sources") != adopted["sources"]:
        raise BatchError("PILOT_SOURCE_REVIEW_BINDING_MISMATCH")
    # The independent receipt itself must match this exact code snapshot.
    independent, _ = _analysis_ref(review.get("independent_review", {}), root=RESEARCH_PILOT_ROOT)
    if independent.get("status") != "REVIEWED_PASS" or independent.get("sources") != adopted["sources"] or independent.get("reviewer") != "/root/pdf_model_analysis_reviewer":
        raise BatchError("PILOT_INDEPENDENT_CODE_PASS_REQUIRED")
    verify_source_erratum_pair(admission)
    first = strata.get("first_group_document_ids")
    rest = strata.get("remaining14_document_ids")
    allowed = set(admission["documents"]) - {ANALYSIS_CANARY_ID}
    if (not isinstance(first, list) or len(first) != 3 or not isinstance(rest, list) or len(rest) != 14
            or len(set(first + rest)) != 17 or set(first + rest) != allowed):
        raise BatchError("PILOT_STRATIFIED_SUBSET_INVALID")
    held: list[str] = []
    recovery = None
    if is_v2:
        held = verify_source_hold_admission(adopted)
        if len(held)!=2 or any(did not in rest for did in held):
            raise BatchError("PILOT_SOURCE_HOLDS_OUTSIDE_REMAINING_SUBSET")
        verify_yaoshi_source_erratum()
        recovery = load_tool_budget_recovery(adopted)
        previous = adopted.get("previous_pilot_authorization")
        expected_previous = {"path": str(dispatcher.CONTINUATION_ROOT / "ROOT_REMAINING_EXECUTION_AUTHORIZATION_PRE_PILOT_ERRATA_20261020_R1.json"), "sha256": PILOT_V1_AUTHORIZATION_SHA256}
        if previous != expected_previous:
            raise BatchError("PILOT_V2_PREVIOUS_AUTHORIZATION_MISMATCH")
        old_auth, _ = _analysis_ref(previous, root=dispatcher.CONTINUATION_ROOT)
        if adopted.get("previous_pilot_adoption") != old_auth.get("pilot17_adoption"):
            raise BatchError("PILOT_V2_PREVIOUS_ADOPTION_MISMATCH")
        _analysis_ref(adopted["previous_pilot_adoption"], root=dispatcher.CONTINUATION_ROOT)
    synthesis_recovery = load_synthesis_recovery(adopted) if is_v3 else None
    sectioned_reuse = load_sectioned_reuse_v4(adopted) if is_v4 else None
    phase = "first3"
    content_path = RESEARCH_PILOT_ROOT / "independent-review/stratified-first3-content-review.json"
    if content_path.exists():
        proof_admission = {**admission, "pilot": {"value": adopted, "recovery": recovery, "synthesis_recovery": synthesis_recovery, "sectioned_reuse": sectioned_reuse}}
        verify_pilot_content_review(content_path, first, proof_admission)
        phase = "remaining12" if is_v2 else "remaining14"
    return {"reference": reference, "value": adopted, "phase": phase,
            "allowed_ids": first if phase == "first3" else [did for did in rest if did not in held],
            "source_hold_ids": held, "recovery": recovery, "synthesis_recovery": synthesis_recovery, "sectioned_reuse": sectioned_reuse}


def verify_pilot_content_review(path: Path, ids: Sequence[str], admission: Mapping[str, Any]) -> None:
    from ops import run_pdf_research_remaining_once as dispatcher
    if path.is_symlink() or not path.is_file():
        raise BatchError("PILOT_CONTENT_REVIEW_REQUIRED")
    review = json.loads(path.read_bytes())
    is_v2 = admission.get("pilot", {}).get("value", {}).get("schema") == "v4.pdf_research.pilot_adoption.v2"
    expected_statuses = {"FIRST3_CONTENT_PASS", "FIRST3_ACCEPTED_WITH_SOURCE_ERRATA"} if is_v2 else {"FIRST3_CONTENT_PASS"}
    if (review.get("status") not in expected_statuses or review.get("reviewer") != "/root/pdf_model_analysis_reviewer"
            or review.get("selection_sha256") != admission["reference"]["sha256"]
            or review.get("stratified17_sha256") != PILOT_STRATA_SHA256
            or [r.get("document_id") for r in review.get("documents", [])] != list(ids)):
        raise BatchError("PILOT_FIRST3_CONTENT_PASS_REQUIRED")
    events = [json.loads(line) for line in (dispatcher.EVIDENCE_ROOT / "dispatch.jsonl").read_bytes().splitlines()]
    for row in review["documents"]:
        did = row["document_id"]
        terms = [e for e in events if e.get("event") == "reconciled" and e.get("document_id") == did]
        if admission.get("pilot", {}).get("sectioned_reuse") is not None and did==PILOT_TOOL_BUDGET_DOCUMENT_ID:
            composite=verify_sectioned_content_v4()
            if (len(terms)!=4 or [e.get("status") for e in terms]!=["FAILED_NO_RETRY","STOPPED_GRACEFULLY","FAILED_DOCUMENT_ISOLATED","USER_ACCEPTED_REUSED_REPORT"]
                    or row.get("status")!=composite["content_status"] or row.get("content_review")!=composite["content_review"]
                    or any(row.get(k)!=composite[k] for k in ("report","receipt","page_input"))
                    or row.get("source_pages_reviewed")!=list(range(1,21))
                    or terms[-1].get("receipt_sha256")!=composite["receipt"]["sha256"]):
                raise BatchError("PILOT_SECTIONED_CONTENT_BINDING_MISMATCH")
            continue
        if is_v2 and did == PILOT_TOOL_BUDGET_DOCUMENT_ID:
            recovery = admission["pilot"]["recovery"]
            synthesis = admission["pilot"].get("synthesis_recovery")
            expected_terms = 3 if synthesis is not None else 2
            if (len(terms) != expected_terms or terms[0].get("status") != "FAILED_NO_RETRY"
                    or terms[0].get("plan_sha256") != recovery["descriptor"]["failed_plan"]["sha256"]
                    or terms[1].get("plan_sha256") != recovery["plan_reference"]["sha256"]
                    or synthesis is not None and (terms[1].get("status") != "STOPPED_GRACEFULLY"
                        or terms[2].get("plan_sha256") != synthesis["plan_reference"]["sha256"])):
                raise BatchError("PILOT_CONTENT_RECOVERY_PAIR_MISMATCH")
            e = terms[-1]
        elif len(terms) == 1:
            e = terms[0]
        else:
            raise BatchError("PILOT_CONTENT_TERMINAL_MISMATCH")
        is_sectioned_long = admission.get("pilot", {}).get("sectioned_reuse") is not None and did==PILOT_LONG_DOCUMENT_ID
        if e.get("status") != ("SECTIONED_SOURCE_STAGE_REPORT_SOURCE_REVIEW_PENDING" if is_sectioned_long else "MODEL_GENERATED_TEXT_COMPLETE_SOURCE_REVIEW_PENDING"):
            raise BatchError("PILOT_CONTENT_TERMINAL_MISMATCH")
        allowed_row_status = "REPORT_WITH_ERRATUM_PASS" if is_v2 and did == PILOT_YAOSHI_DOCUMENT_ID else "REPORT_CONTENT_PASS"
        if is_v2 and did == PILOT_YAOSHI_DOCUMENT_ID:
            combined = verify_yaoshi_source_erratum()
            if (review.get("status") != "FIRST3_ACCEPTED_WITH_SOURCE_ERRATA"
                    or row.get("original_content_review") != combined["original_content_review"]
                    or row.get("display_content_review") != combined["review_reference"]
                    or row.get("display_report") != combined["display"]):
                raise BatchError("PILOT_CONTENT_YAOSHI_COMBINATION_MISMATCH")
        if (row.get("status") != allowed_row_status or row.get("page_input") != admission["documents"][did]["page_input"]
                or row.get("receipt") != {"path": e.get("receipt_path"), "sha256": e.get("receipt_sha256")}
                or row.get("report", {}).get("path") != str(Path(e["state_root"]) / "documents" / did / "report.md")
                or row.get("source_pages_reviewed") != list(range(1, admission["documents"][did]["page_count"] + 1))):
            raise BatchError("PILOT_CONTENT_REPORT_BINDING_MISMATCH")
        _analysis_ref(row["receipt"])
        _analysis_ref(row["report"], parse_json=False)


PILOT_V2_DECISION_SHA256 = "bb737dae5d3fd982e025f4d28347cd839892cd44540c5e0ef6734510fabf2175"
PILOT_V1_AUTHORIZATION_SHA256 = "e7429418250add6d2646e1522017e4c91e9b34c9c1ead3ad771fe5f23c58f9ff"
PILOT_V2_PREFIX_SHA256 = "0747e773c12339fd7ec19b953de67525aa713d6b591aa44eb22bfb17f7ff7137"
PILOT_TOOL_BUDGET_DOCUMENT_ID = "667565ef19142d4d08afb2794d20486b22323a433e595e5b46eb7dbedd99e891"
PILOT_YAOSHI_DOCUMENT_ID = "01423dc338fde73e0445b440024154111937d6dd5d36526127a0a559a0b6cee5"
PILOT_V2_DATA_SHA256 = {
    "package-source-errata-v2.json": "af9626e9f2e3d3c8d5626df5e5408b25983284eb55248d9e2ae4337b943f51bf",
    "source-hold-admission-v2.json": "0271bb76cb5af873d588ca31a05b7c213e672bde9257b79e7747031d736e867c",
    "package-input-plan-v2.json": "da20b4464d38045305daa5629861961a4a12fdb5cc322d60116224ea9af9e14f",
    "tool-budget-recovery-v2.json": "7a84e8cd98e319187ecfa02091e736409d15a78957f14571bbd43fbad0919c1f",
    "recovery-plan-v2.json": "45eabc7870e3d1f342b9404672ea527247111a18bacdfa55e555b1766f5ccd1b",
}


def _v2_data_ref(name: str) -> dict[str, str]:
    return {"path": str(RESEARCH_PILOT_ROOT / "model" / name), "sha256": PILOT_V2_DATA_SHA256[name]}


def verify_package_source_errata(reference: Mapping[str, Any]) -> list[dict[str, Any]]:
    if reference != _v2_data_ref("package-source-errata-v2.json"):
        raise BatchError("PILOT_SOURCE_ERRATA_REFERENCE_MISMATCH")
    value, _ = _analysis_ref(reference, root=RESEARCH_PILOT_ROOT)
    decision = _pilot_fixed(RESEARCH_PILOT_ROOT / "controller-delta-v2-decision.json", PILOT_V2_DECISION_SHA256)
    expected = []
    for source_ref in decision["source_findings"]:
        finding, _ = _analysis_ref(source_ref, root=RESEARCH_PILOT_ROOT)
        if finding.get("status") != "SOURCE_CONTENT_ERROR_VERIFIED" or finding.get("reviewer") != "/root/pdf_model_analysis_reviewer":
            raise BatchError("PILOT_SOURCE_FINDING_NOT_VERIFIED")
        source, _ = _analysis_ref(finding["prepared_page_input"])
        page = next((p for p in source["pages"] if p["page_number"] == finding["source_page"]), None)
        if (source.get("document_id") != finding["document_id"] or page is None
                or _sha256(page["text"].encode()) != finding["prepared_page_text_sha256"]):
            raise BatchError("PILOT_SOURCE_FINDING_PAGE_MISMATCH")
        _analysis_ref(finding["rendered_original_page"], parse_json=False)
        cells = finding.get("cells") or [{"column":finding["column"], "original_visual":finding["original_pdf_displayed_value"], "prepared_text":finding["prepared_page_extracted_value"]}]
        expected.append({"finding":source_ref,"document_id":finding["document_id"],"package_id":finding["package_id"],
            "source_page":finding["source_page"],"original_pdf":finding["original_pdf"],"page_input":finding["prepared_page_input"],
            "page_text_sha256":finding["prepared_page_text_sha256"],"page_image":finding["rendered_original_page"],
            "table":finding["table"],"row":finding["row"],"source_metadata_limit":finding.get("source_metadata_limit",""),"corrections":cells,"verification_identity":finding["reviewer"],
            "annotation":"人工来源勘误；非重新模型生成。完整原页/OCR原文保留；下列已视觉核对的字段以单独勘误注明，不能把OCR错误当精确数字。"})
    if value.get("findings") != expected or len(expected) != 2:
        raise BatchError("PILOT_SOURCE_ERRATA_FIELDS_MISMATCH")
    return expected


def verify_source_hold_admission(adopted: Mapping[str, Any]) -> list[str]:
    expected_ref = _v2_data_ref("source-hold-admission-v2.json")
    if adopted.get("source_holds") != expected_ref or adopted.get("package_source_projection") != _v2_data_ref("package-input-plan-v2.json"):
        raise BatchError("PILOT_SOURCE_HOLD_BINDING_MISMATCH")
    holds, _ = _analysis_ref(expected_ref, root=RESEARCH_PILOT_ROOT)
    projection, _ = _analysis_ref(adopted["package_source_projection"], root=RESEARCH_PILOT_ROOT)
    findings = verify_package_source_errata(projection.get("source_errata", {}))
    ids = [f["document_id"] for f in findings]
    if holds.get("held_document_ids") != ids or holds.get("findings") != [f["finding"] for f in findings]:
        raise BatchError("PILOT_SOURCE_HOLD_SET_MISMATCH")
    return ids



PILOT_SYNTHESIS_V3_PREFIX_SHA256 = "02803f3dab0b0984ebf17a5c33429bdc1c4de8984760993f16f7444d147e6039"
PILOT_SYNTHESIS_PREVIOUS_AUTH_SHA256 = "02f1610988e8e04d38148b0c2163fe5a14d80ae7423db419858fb3844d0710da"
PILOT_SYNTHESIS_DATA = {
    "synthesis-recovery-v3-qualified.json": "0816f6173de98ef3f90431097ddbefd900a8a829eb78d2f194a1fd7e39a5045c",
    "synthesis-plan-v3-qualified.json": "3d8def66ce70eb91dd7afadf87f5a7bab2f9c96926eaa1b1a107b7fa951d5343",
}


def _synthesis_v3_ref(name: str) -> dict[str, str]:
    return {"path": str(RESEARCH_PILOT_ROOT / "model" / name), "sha256": PILOT_SYNTHESIS_DATA[name]}


def load_synthesis_recovery(adopted: Mapping[str, Any] | None = None) -> dict[str, Any]:
    from ops import run_pdf_research_remaining_once as dispatcher
    expected = {"descriptor": _synthesis_v3_ref("synthesis-recovery-v3-qualified.json"),
                "plan_source": _synthesis_v3_ref("synthesis-plan-v3-qualified.json")}
    if adopted is not None:
        previous = {"path": str(dispatcher.CONTINUATION_ROOT / "ROOT_REMAINING_EXECUTION_AUTHORIZATION_PRE_SYNTHESIS_RECOVERY_20261020_R1.json"),
                    "sha256": PILOT_SYNTHESIS_PREVIOUS_AUTH_SHA256}
        if adopted.get("synthesis_stage_recovery") != expected or adopted.get("previous_synthesis_authorization") != previous:
            raise BatchError("SYNTHESIS_RECOVERY_ADOPTION_MISMATCH")
        auth, _ = _analysis_ref(previous, root=dispatcher.CONTINUATION_ROOT)
        if adopted.get("previous_synthesis_adoption") != auth.get("pilot17_adoption"):
            raise BatchError("SYNTHESIS_RECOVERY_PREVIOUS_IDENTITY_MISMATCH")
        _analysis_ref(adopted["previous_synthesis_adoption"], root=dispatcher.CONTINUATION_ROOT)
    value, _ = _analysis_ref(expected["descriptor"], root=RESEARCH_PILOT_ROOT)
    plan, raw = _analysis_ref(expected["plan_source"], root=RESEARCH_PILOT_ROOT)
    decision, _ = _analysis_ref(value["controller_decision"], root=RESEARCH_PILOT_ROOT)
    stopped, _ = _analysis_ref(value["stopped_receipt"])
    progress, _ = _analysis_ref(value["stopped_progress"])
    stop_review, _ = _analysis_ref(value["independent_stopped_review"], root=RESEARCH_PILOT_ROOT)
    failure_review, _ = _analysis_ref(value["independent_nonprogress_review"], root=RESEARCH_PILOT_ROOT)
    old_plan, _ = _analysis_ref(value["stopped_plan"], root=RESEARCH_PILOT_ROOT)
    page_input, _ = _analysis_ref(value["stopped_page_input"])
    if (value.get("document_id") != PILOT_TOOL_BUDGET_DOCUMENT_ID or value.get("model_request_limit") != 2
            or value.get("source_model_rePOST_limit") != 0
            or value.get("journal_event_count") != 62 or value["journal_prefix"]["sha256"] != PILOT_SYNTHESIS_V3_PREFIX_SHA256
            or value["controller_decision"]["sha256"] != "dc593a360ea6c6a48fd6d3deae12efee967cbc73cab45f514e6c05587a85c143"
            or stop_review.get("status") != "GRACEFUL_CHECKPOINT_STOP_PASS" or stop_review.get("reviewer") != "/root/pdf_model_analysis_reviewer"
            or failure_review.get("verdict") != "FAIL_TARGET_PROGRESS" or failure_review.get("reviewer") != "/root/pdf_model_analysis_reviewer"
            or stopped.get("status") != "STOPPED_GRACEFULLY" or stopped.get("document_id") != PILOT_TOOL_BUDGET_DOCUMENT_ID
            or progress.get("chunk_states") != {"1":"SUCCEEDED","2":"SUCCEEDED","3":"SUCCEEDED"}
            or page_input.get("document_id") != PILOT_TOOL_BUDGET_DOCUMENT_ID or value["source_input_sha256"] != value["stopped_page_input"]["sha256"]
            or stopped.get("page_input",{}).get("sha256") != value["source_input_sha256"]
            or plan.get("selected_documents") != old_plan.get("selected_documents")
            or plan.get("synthesis_stage_recovery") != expected["descriptor"] or "tool_budget_recovery" in plan
            or plan.get("continuation_id") != "resume-synthesis-667-20261020-r1"
            or plan.get("state_root") != str(Path(old_plan["state_root"]).parent / "continuation-resume-synthesis-667-20261020-r1")
            or plan.get("execution_runtime_settings_sha256") != ANALYSIS_RUNTIME_SHA256):
        raise BatchError("SYNTHESIS_RECOVERY_EVIDENCE_MISMATCH")
    chunks = value.get("source_chunks")
    if chunks != stopped.get("chunks") or len(chunks) != 3 or [c.get("chunk_index") for c in chunks] != [1,2,3]:
        raise BatchError("SYNTHESIS_RECOVERY_SOURCE_STAGE_MISMATCH")
    for chunk in chunks:
        if chunk.get("status") != "SUCCEEDED" or chunk.get("attempt_count") != 1 or chunk.get("chunk_total") != 3:
            raise BatchError("SYNTHESIS_RECOVERY_SOURCE_STAGE_MISMATCH")
        keep = lambda r: {k:r[k] for k in ("path","sha256")}
        result, _ = _analysis_ref(keep(chunk["validated_result"]))
        _, report = _analysis_ref(keep(chunk["report"]), parse_json=False)
        _analysis_ref(keep(chunk["queue_raw"]), parse_json=False)
        _analysis_ref(keep(chunk["raw"]), parse_json=False)
        if result.get("analysis_markdown") != report.decode("utf-8"):
            raise BatchError("SYNTHESIS_RECOVERY_PARTIAL_RESULT_MISMATCH")
    seeds = []
    for item in value["seed_reports"]:
        _, original = _analysis_ref(item["source"], parse_json=False)
        text = original.decode("utf-8");offset=item["offset"];length=item["characters"]
        if (type(offset) is not int or type(length) is not int or offset < 0 or offset+length != len(text)
                or _sha256(text[offset:].encode()) != item["text_sha256"]):
            raise BatchError("SYNTHESIS_RECOVERY_SEED_BYTES_MISMATCH")
        seeds.append({"report_id":item["report_id"],"text":text[offset:]})
    if [len(x["text"]) for x in seeds] != [6265,1888]:
        raise BatchError("SYNTHESIS_RECOVERY_SEED_SCOPE_MISMATCH")
    qualifications = value["source_qualifications"]
    paired, _ = _analysis_ref(qualifications["independent_finding"])
    if (qualifications["independent_finding"]["sha256"] != "6b13ae98b59f60f87e883cec805ce24755e3b9cadc70fa861e35080026d1a9ec"
            or [x["id"] for x in qualifications["findings"]] != ["C4","C5","C6"]):
        raise BatchError("SYNTHESIS_RECOVERY_SOURCE_QUALIFICATIONS_MISMATCH")
    return {"descriptor":value,"plan":plan,"plan_raw":raw,"plan_reference":expected["plan_source"],
            "seed_reports":seeds,"source_qualifications":qualifications}


def load_tool_budget_recovery(adopted: Mapping[str, Any]) -> dict[str, Any]:
    expected = {"descriptor": _v2_data_ref("tool-budget-recovery-v2.json"), "plan_source": _v2_data_ref("recovery-plan-v2.json")}
    if adopted.get("tool_budget_recovery") != expected:
        raise BatchError("PILOT_TOOL_RECOVERY_BINDING_MISMATCH")
    descriptor, _ = _analysis_ref(expected["descriptor"], root=RESEARCH_PILOT_ROOT)
    plan, raw = _analysis_ref(expected["plan_source"], root=RESEARCH_PILOT_ROOT)
    failure, _ = _analysis_ref(descriptor["failed_receipt"])
    stream, _ = _analysis_ref(descriptor["failed_stream"])
    old_plan, _ = _analysis_ref(descriptor["failed_plan"])
    _analysis_ref(descriptor["failed_page_input"])
    independent, _ = _analysis_ref(descriptor["independent_failure_review"], root=RESEARCH_PILOT_ROOT)
    if (descriptor.get("document_id") != PILOT_TOOL_BUDGET_DOCUMENT_ID or descriptor.get("generation_limit") != 1
            or failure.get("status") != "FAILED_NO_RETRY" or failure.get("document_id") != PILOT_TOOL_BUDGET_DOCUMENT_ID
            or stream.get("failure_code") != "PDF_ACTION_ENVELOPE_BUDGET_EXCEEDED" or stream.get("request_rounds") != 5
            or stream.get("runtime_settings_sha256") != ANALYSIS_RUNTIME_SHA256
            or independent.get("status") != "ACTUAL_FAILURE_CONFIRMED_NO_RETRY"
            or plan.get("tool_budget_recovery") != expected["descriptor"]
            or plan.get("continuation_id") != "resume-tool-budget-667-20261020-r1"
            or plan.get("selected_documents") != old_plan.get("selected_documents")
            or plan.get("state_root") != str(Path(old_plan["state_root"]).parent / "continuation-resume-tool-budget-667-20261020-r1")
            or failure.get("page_input", {}).get("sha256") != descriptor["failed_page_input"]["sha256"]):
        raise BatchError("PILOT_TOOL_RECOVERY_EVIDENCE_MISMATCH")
    return {"descriptor": descriptor, "plan": plan, "plan_raw": raw, "plan_reference": expected["plan_source"]}


def verify_yaoshi_source_erratum() -> dict[str, Any]:
    path = RESEARCH_PILOT_ROOT / "independent-review/yaoshi-erratum-content-review.json"
    reference = {"path":str(path),"sha256":"eea17d6f6746f69cb0b77bb0fb0d975e6d6b7a6d914e111d66b3e3618896351d"}
    review, _ = _analysis_ref(reference, root=RESEARCH_PILOT_ROOT)
    original_ref = {k:review.get("original_content_review", {}).get(k) for k in ("path","sha256")}
    if original_ref != {"path":str(RESEARCH_PILOT_ROOT / "independent-review/first3-yaoshi-content-review.json"),"sha256":"8b3e6552b55f2b58fa27167e7448438bf4693335cbb7e1dc170d1db711760246"}:
        raise BatchError("PILOT_YAOSHI_ORIGINAL_REVIEW_MISMATCH")
    original, _ = _analysis_ref(original_ref, root=RESEARCH_PILOT_ROOT)
    raw_ref = {k:review.get("original_report", {}).get(k) for k in ("path","sha256")}
    display_ref = {k:review.get("display", {}).get(k) for k in ("path","sha256")}
    _, raw = _analysis_ref(raw_ref, parse_json=False)
    _, display = _analysis_ref(display_ref, root=RESEARCH_PILOT_ROOT, parse_json=False)
    if (review.get("status") != "REPORT_WITH_ERRATUM_PASS" or review.get("reviewer") != "/root/pdf_model_analysis_reviewer"
            or review.get("document_id") != PILOT_YAOSHI_DOCUMENT_ID or original.get("status") != "REPORT_CONTENT_FAIL"
            or review.get("prefix_bytes") != 630 or display[630:] != raw
            or not all(t in display[:630].decode() for t in ("临床前至临床II期","临床III期及商业化","1200","62","非重新模型生成"))):
        raise BatchError("PILOT_YAOSHI_ERRATUM_BYTES_MISMATCH")
    return {"review_reference":reference,"original_content_review":original_ref,"original_report":raw_ref,"display":display_ref}


def run_batch(
    manifest_path: Path = DEFAULT_MANIFEST,
    *,
    state_root: Path | None = None,
    queue_factory: Callable[[Path], tuple[Any, Path]] = _create_queue,
    request_fn: Callable[..., str] = local_model.request_document_analysis,
    identity_fn: Callable[[], Mapping[str, Any]] = local_model.inspect_local_api_identity,
    priority_reader: Callable[[], Mapping[str, Any]] = _priority_snapshot,
    sleep_fn: Callable[[float], Any] = time.sleep,
    max_documents: int = 3,
    wait_fn: Callable[[threading.Event, float], bool] | None = None,
    continuation_plan_path: Path | None = None,
    prepared_text_manifest_path: Path | None = None,
    prepared_text_manifest_sha256: str | None = None,
    prepared_document_ids: Sequence[str] | None = None,
    revision_only: bool = False,
    eligible_selection_path: Path | None = None,
    eligible_selection_sha256: str | None = None,
) -> dict[str, Any]:
    continuation = None
    if continuation_plan_path is not None:
        _manifest, manifest_sha, documents = load_manifest(manifest_path)
        continuation = validate_continuation_plan(
            continuation_plan_path,
            manifest_sha256=manifest_sha,
            documents=documents,
        )
        state_root = continuation["state_root"]
        max_documents = len(continuation["selected_documents"])
    with _cooperative_sigterm_handler() as stop_event:
        return _run_batch_impl(
            manifest_path,
            state_root=state_root,
            queue_factory=queue_factory,
            request_fn=request_fn,
            identity_fn=identity_fn,
            priority_reader=priority_reader,
            sleep_fn=sleep_fn,
            max_documents=max_documents,
            wait_fn=wait_fn,
            stop_event=stop_event,
            continuation=continuation,
            prepared_text_manifest_path=prepared_text_manifest_path,
            prepared_text_manifest_sha256=prepared_text_manifest_sha256,
            prepared_document_ids=prepared_document_ids,
            revision_only=revision_only,
            eligible_selection_path=eligible_selection_path,
            eligible_selection_sha256=eligible_selection_sha256,
        )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--max-documents", type=int, help="limit the frozen three-document canary prefix")
    parser.add_argument("--continuation-plan", type=Path, help="validate or execute a frozen explicit continuation subset")
    parser.add_argument("--prepare-text-only", action="store_true", help="prepare source-bound text checkpoints without model binding or POST")
    parser.add_argument("--prepare-run-id", help="stable run ID used to resume a text-preparation stage")
    parser.add_argument("--document-id", action="append", help="prepare one document only; explicit selection never freezes a full-cohort manifest")
    parser.add_argument("--prepared-text-manifest", type=Path, help="full frozen text-stage manifest required for model execution")
    parser.add_argument("--prepared-text-manifest-sha256", help="expected SHA-256 of --prepared-text-manifest")
    parser.add_argument("--prepared-document-id", action="append", help="explicit READY document to analyze from frozen text")
    parser.add_argument("--revision-only", action="store_true", help="select only documents whose prepared text explicitly supersedes prior reports")
    parser.add_argument("--eligible-selection", type=Path)
    parser.add_argument("--eligible-selection-sha256")
    parser.add_argument("--execute", action="store_true", help="run the frozen batch; without this flag only validate the manifest")
    args = parser.parse_args(argv)
    try:
        manifest, manifest_sha, documents = load_manifest(args.manifest)
        if args.prepare_text_only:
            if args.execute or args.continuation_plan is not None or args.prepared_text_manifest is not None or args.prepared_text_manifest_sha256 is not None or args.prepared_document_id is not None or args.revision_only:
                raise BatchError("PREPARE_TEXT_ONLY_FLAG_CONFLICT")
            if not args.prepare_run_id:
                raise BatchError("PREPARE_RUN_ID_REQUIRED")
            result = pdf_text_preparation.prepare_only(
                sys.modules[__name__],
                manifest_path=args.manifest,
                run_id=args.prepare_run_id,
                document_ids=args.document_id,
            )
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return 0
        if args.document_id is not None or args.prepare_run_id is not None:
            raise BatchError("PREPARE_FLAGS_REQUIRE_PREPARE_TEXT_ONLY")
        max_documents = args.max_documents if args.max_documents is not None else 3
        if max_documents < 1:
            raise BatchError("MAX_DOCUMENTS_INVALID")
        if args.continuation_plan is not None and args.max_documents is not None:
            raise BatchError("CONTINUATION_MAX_DOCUMENTS_NOT_ALLOWED")
        if args.continuation_plan is not None:
            continuation = validate_continuation_plan(
                args.continuation_plan,
                manifest_sha256=manifest_sha,
                documents=documents,
            )
            if not args.execute:
                print(json.dumps({
                    "status": "PLAN_ONLY",
                    "continuation_id": continuation["plan"]["continuation_id"],
                    "continuation_plan_sha256": continuation["plan_sha256"],
                    "manifest_sha256": manifest_sha,
                    "runtime_settings_sha256": continuation["plan"]["runtime_settings_sha256"],
                    "execution_runtime_settings_sha256": continuation["plan"].get("execution_runtime_settings_sha256"),
                    "model_settings_sha256": continuation["expected_model_settings_sha256"],
                    "selected_document_count": len(continuation["selected_documents"]),
                    "selected_prior_statuses": {
                        document_id: entry["prior_status"]
                        for document_id, entry in continuation["selected_entries"].items()
                    },
                    "state_root": str(continuation["state_root"]),
                    "execution": "NOT_RUN",
                }, ensure_ascii=False, sort_keys=True))
                return 0
            if args.prepared_document_id is not None or args.revision_only:
                raise BatchError("CONTINUATION_PREPARED_SELECTION_CONFLICT")
            result = run_batch(
                args.manifest,
                max_documents=len(continuation["selected_documents"]),
                continuation_plan_path=args.continuation_plan,
                prepared_text_manifest_path=args.prepared_text_manifest,
                prepared_text_manifest_sha256=args.prepared_text_manifest_sha256,
                eligible_selection_path=args.eligible_selection,
                eligible_selection_sha256=args.eligible_selection_sha256,
            )
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return 0
        if not args.execute:
            print(json.dumps({
                "status": "PLAN_ONLY",
                "manifest_sha256": manifest_sha,
                "manifest_document_count": len(documents),
                "selected_document_count": min(max_documents, len(documents)),
            }, ensure_ascii=False))
            return 0
        if args.prepared_text_manifest is None or args.prepared_text_manifest_sha256 is None:
            raise BatchError("PREPARED_TEXT_MANIFEST_REQUIRED")
        result = run_batch(
            args.manifest,
            max_documents=max_documents,
            prepared_text_manifest_path=args.prepared_text_manifest,
            prepared_text_manifest_sha256=args.prepared_text_manifest_sha256,
            prepared_document_ids=args.prepared_document_id,
            revision_only=args.revision_only,
            eligible_selection_path=args.eligible_selection,
            eligible_selection_sha256=args.eligible_selection_sha256,
        )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except Exception as exc:
        code = getattr(exc, "code", None) or type(exc).__name__
        print(json.dumps({"status": "STOPPED", "code": str(code)[:96]}, ensure_ascii=False), file=sys.stderr)
        return 2


# V4: exact stopped69 source-stage reuse, with no recursive model rewrite.
PILOT_V4_DECISION_SHA256 = "a2f9fc416c038d5278e100b9d9d940ccfa8c22da17f19c704c743ab5618dcd60"
PILOT_V4_PREVIOUS_AUTH_SHA256 = "4ba1ffeef9883a25db2bb52450c2cafdae0b1374be51f97691271edb6591b825"
PILOT_V4_PREFIX_SHA256 = "f04869e83b6a721e4d0319165240e0412e2a77d9a14c21cec5b779957a7a40d1"
PILOT_V4_DESCRIPTOR_SHA256 = "2b2c7d130e498d087f8520d5eeeb25d83c16b8d7c16dde4910e06e892f361ecb"
PILOT_LONG_DOCUMENT_ID = "003ecec0bb479256ad7bcbf1f1b0cbdbe2a613fdada22d9d806fc6835ab2a520"


def _sectioned_v4_ref() -> dict[str, str]:
    return {"path":str(RESEARCH_PILOT_ROOT / "model/sectioned-source-reuse-v4-name-erratum.json"),"sha256":PILOT_V4_DESCRIPTOR_SHA256}


def load_sectioned_reuse_v4(adopted: Mapping[str, Any] | None = None) -> dict[str, Any]:
    from ops import run_pdf_research_remaining_once as dispatcher
    descriptor = _sectioned_v4_ref()
    value, _ = _analysis_ref(descriptor, root=RESEARCH_PILOT_ROOT)
    decision = _pilot_fixed(RESEARCH_PILOT_ROOT / "controller-nonrecursive-v4-decision.json",PILOT_V4_DECISION_SHA256)
    if (value.get("controller_decision")!={"path":str(RESEARCH_PILOT_ROOT / "controller-nonrecursive-v4-decision.json"),"sha256":PILOT_V4_DECISION_SHA256}
            or value.get("document_id")!=PILOT_TOOL_BUDGET_DOCUMENT_ID or value.get("new_model_POST_limit")!=0
            or value.get("recursive_synthesis_limit")!=0 or value.get("long_document_id")!=PILOT_LONG_DOCUMENT_ID
            or value.get("long_source_chunks")!=11 or value.get("long_POST_upper_limit")!=77
            or value.get("current_checkpoint")!={"event_count":69,"sha256":PILOT_V4_PREFIX_SHA256}
            or decision.get("status")!="AUTHORIZED_V4_NONRECURSIVE_RECOVERY_AND_CONTINUATION"):
        raise BatchError("SECTIONED_V4_SCOPE_MISMATCH")
    if adopted is not None:
        previous={"path":str(dispatcher.CONTINUATION_ROOT / "ROOT_REMAINING_EXECUTION_AUTHORIZATION_PRE_PACKAGE_COMPAT_20261020_R1.json"),"sha256":PILOT_V4_PREVIOUS_AUTH_SHA256}
        if adopted.get("sectioned_reuse")!={"descriptor":descriptor} or adopted.get("previous_package_authorization")!=previous:
            raise BatchError("SECTIONED_V4_ADOPTION_MISMATCH")
        old, _ = _analysis_ref(previous,root=dispatcher.CONTINUATION_ROOT)
        if adopted.get("previous_package_adoption")!=old.get("pilot17_adoption"):
            raise BatchError("SECTIONED_V4_PREVIOUS_ADOPTION_MISMATCH")
        _analysis_ref(adopted["previous_package_adoption"],root=dispatcher.CONTINUATION_ROOT)
    old=load_synthesis_recovery()
    failure,_=_analysis_ref(value["actual_failure"],root=RESEARCH_PILOT_ROOT)
    independent,_=_analysis_ref(value["independent_failure"],root=RESEARCH_PILOT_ROOT)
    _analysis_ref(value["source_qualification_review"],root=RESEARCH_PILOT_ROOT)
    if (value["source_input"]!=old["descriptor"]["stopped_page_input"] or value["source_qualifications"]!=old["source_qualifications"]
            or failure.get("failure_code")!="SYNTHESIS_OUTPUT_CHARACTER_BUDGET_EXCEEDED"
            or value["independent_failure"]["sha256"]!="cf3894fca4ac11892f1810899e1a035013fd5aac6fc533672f5cd8b121b6a50d"
            or independent.get("reviewer")!="/root/pdf_model_analysis_reviewer"):
        raise BatchError("SECTIONED_V4_FAILURE_BINDING_MISMATCH")
    page_input,_=_analysis_ref(value["source_input"])
    pages=[pdf_research.PageText(p["page_number"],p["page_total"],p["text"],p["status"],p["text_sha256"],p.get("extraction_method")) for p in page_input["pages"]]
    chunks=pdf_research.build_source_chunks(value["document_id"],pages)
    rows=value.get("source_rows",[])
    if (len(rows)!=3 or [r.get("source_chunk") for r in rows]!=old["descriptor"]["source_chunks"]
            or [c.chunk_sha256 for c in chunks]!=[r["source_chunk"]["chunk_sha256"] for r in rows]
            or not pdf_research.verify_chunk_reconstruction(pages,chunks)
            or len(pages)!=20 or sorted({u.page_number for c in chunks for u in c.units})!=list(range(1,21))):
        raise BatchError("SECTIONED_V4_COMPLETE_SOURCE_MISMATCH")
    if sum(len(r.get("edits",[])) for r in rows)!=5:
        raise BatchError("SECTIONED_V4_PROJECTION_SCOPE_MISMATCH")
    _pilot_fixed(RESEARCH_PILOT_ROOT / "controller-single-entity-erratum-v4-decision.json", "5a6db12414af7c12f402017adb3bd0bab573b1744946507771782becd290834c")
    old_descriptor={"path":str(RESEARCH_PILOT_ROOT / "model/sectioned-source-reuse-v4.json"),"sha256":"2a2f12017a5fff10afcf7acf695980fa9b0cfc47c0584813290f2648135d9499"}
    prior,_=_analysis_ref(old_descriptor,root=RESEARCH_PILOT_ROOT)
    finding_ref={"path":str(RESEARCH_PILOT_ROOT / "independent-review/sectioned667-content-review-v4.json"),"sha256":"6ac710cf158e18e83a01f781c66b2c1f269275829aab681682159fc5b497f001"}
    reviewed,_=_analysis_ref(finding_ref,root=RESEARCH_PILOT_ROOT)
    entity=value.get("entity_erratum",{});findings=reviewed.get("findings",[])
    if (value.get("previous_descriptor")!=old_descriptor or value.get("original_content_failure")!=finding_ref
            or entity.get("source_finding")!=finding_ref or entity.get("expected_occurrences")!=1
            or entity.get("original_ocr")!="吴帆生物" or entity.get("visually_verified")!="昊帆生物"
            or reviewed.get("status")!="SECTIONED_REPORT_CONTENT_FAIL" or reviewed.get("reviewer")!="/root/pdf_model_analysis_reviewer"
            or len(findings)!=1 or findings[0].get("id")!="V4-CONTENT-ENTITY-P1"
            or findings[0].get("source_exact")!="昊帆生物" or findings[0].get("prepared_exact")!="吴帆生物"
            or reviewed.get("source_pages_reviewed")!=list(range(1,21))
            or any(reviewed.get("checks",{}).get(k) is not True for k in ("all20_pages","important_omissions","cross_section_conflicts","numeric_period_unit_conditions","C4_C5_unknown_exclusions","C6_manual_rating"))):
        raise BatchError("SECTIONED_ENTITY_FINDING_MISMATCH")
    _analysis_ref(entity["source_crop"],parse_json=False)
    if entity["source_crop"]!=findings[0]["source_crop"] or entity["source_pdf"]!=findings[0]["source_pdf"]:
        raise BatchError("SECTIONED_ENTITY_SOURCE_MISMATCH")
    without_entity=[{**r,"edits":[e for e in r["edits"] if e.get("finding")!="V4-CONTENT-ENTITY-P1"]} for r in rows]
    if without_entity!=prior["source_rows"] or sum(e.get("finding")=="V4-CONTENT-ENTITY-P1" for r in rows for e in r["edits"])!=1:
        raise BatchError("SECTIONED_ENTITY_EXPECTED1_OTHER_BYTES_MISMATCH")
    for c,r in zip(chunks,rows):
        if r["initial_input_pages"]!=sorted({u.page_number for u in c.units}):
            raise BatchError("SECTIONED_V4_INITIAL_PAGE_INDEX_MISMATCH")
        stream,_=_analysis_ref(r["stream"])
        if stream.get("status")!="SUCCEEDED" or stream.get("idempotency_key")!=r["source_chunk"]["queue_idempotency_key"]:
            raise BatchError("SECTIONED_V4_STREAM_BINDING_MISMATCH")
        for request in r["requests"]:_analysis_ref(request)
        evidence_root=Path(r["stream"]["path"]).parents[3]
        for turn in stream.get("rounds",[]):
            for kind in ("raw_sse","request_input"):
                target=evidence_root / turn[kind+"_path"]
                _analysis_ref({"path":str(target),"sha256":turn[kind+"_sha256"]},parse_json=False)
        requested=_sectioned_requested_pages(json.loads(Path(r["requests"][-1]["path"]).read_bytes())["messages"])
        if requested!=r["tool_requested_pages"]:
            raise BatchError("SECTIONED_V4_TOOL_PAGE_INDEX_MISMATCH")
    return {"reference":descriptor,"value":value}


def _sectioned_requested_pages(messages: Sequence[Mapping[str, Any]]) -> list[int]:
    return sorted({int(n) for m in messages if m.get("role")=="assistant"
                   for n in re.findall(r'page_number\\*":\s*(\d+)',str(m.get("content","")))})


def _project_sectioned_text(text: str, edits: Sequence[Mapping[str, Any]]) -> str:
    previous=0
    for e in sorted(edits,key=lambda e:e["start_character"]):
        a=e.get("start_character");z=e.get("end_character")
        if (type(a) is not int or type(z) is not int or a<previous or z<=a or z>len(text)
                or not ((e.get("finding") in {"C4","C5"} and "CANNOT_CONFIRM" in str(e.get("replacement")))
                        or (e.get("finding")=="V4-CONTENT-ENTITY-P1" and text[a:z]=="吴帆生物"
                            and e.get("replacement")=="昊帆生物〔人工来源勘误：原PDF第1页；原OCR为“吴帆生物”〕"))
                or _sha256(text[a:z].encode())!=e.get("original_text_sha256")):
            raise BatchError("SECTIONED_PROJECTION_RANGE_MISMATCH")
        previous=z
    result=text
    for e in sorted(edits,key=lambda e:e["start_character"],reverse=True):
        result=result[:e["start_character"]]+e["replacement"]+result[e["end_character"]:]
    return result


def _sectioned_text(document_id: str, reports: Sequence[Mapping[str,str]], indexes: Sequence[Mapping[str,Any]], manual_note: str | None) -> str:
    if not reports or len(reports)!=len(indexes):raise BatchError("SECTIONED_COMPONENTS_INCOMPLETE")
    out=["# 原模型分块分析与来源约束\n\n此文按原顺序复用模型分块，未重新模型生成或递归合成；可能有重复。输入覆盖不等于内容已验收，重要事实、遗漏、跨块冲突仍须独立核对。\n",
         f"文档：{document_id}\n\n## 输入和工具引用索引\n"]
    for i,row in enumerate(indexes,1):
        out.append(f"- 分块{i}：初始输入页 {row['initial_input_pages']}；工具请求页 {row['tool_requested_pages']}（请求不保证返回全文）；模型引用页见分块，原请求及工具stream的SHA见component manifest。\n")
    if manual_note:out.append("\n## 验收补充的人工来源约束（非模型生成）\n\n"+manual_note+"\n")
    for i,r in enumerate(reports,1):out.append(f"\n## 原模型分块 {i} 的来源约束投影\n\n"+r["text"])
    return "\n".join(out)+"\n"


def build_sectioned_reuse_v4(*, persist: bool = True) -> dict[str, Any]:
    """No transport or queue access. Only exact adopted artifact inputs are read."""
    loaded=load_sectioned_reuse_v4();value=loaded["value"];reports=[];components=[]
    for row in value["source_rows"]:
        reference={k:row["source_chunk"]["report"][k] for k in ("path","sha256")}
        _,raw=_analysis_ref(reference,parse_json=False);text=raw.decode()
        projected=_project_sectioned_text(text,row["edits"])
        components.append({**row,"original_report":reference,"original_ranges":[{**e,"original_text":text[e["start_character"]:e["end_character"]]} for e in row["edits"]],
                           "projected_text_sha256":_sha256(projected.encode())})
        reports.append({"text":projected,"report_id":row["source_chunk"]["chunk_sha256"]})
    qual=value["source_qualifications"]
    note="原分块的第6页年份—事件配对、第9—10页管线行级映射已发现错配；下文对应段落显式替换为CANNOT_CONFIRM，原段落完整保留在component manifest。另依据独立第1页原图，仅将原OCR公司名吴帆生物显式勘误为昊帆生物；此为验收人工补充，未重新OCR或模型生成。\n\n"+"\n\n".join(f"{f['id']}：{f['constraint']}" for f in qual["findings"])
    report=_sectioned_text(value["document_id"],reports,value["source_rows"],note)
    root=RESEARCH_PILOT_ROOT / "model/sectioned-reuse-v4/667-name-erratum"
    if value["report_directory"]!=str(root):raise BatchError("SECTIONED_V4_REPORT_PATH_MISMATCH")
    path=root/"report.md";digest=_sha256(report.encode())
    if persist:_write_immutable(path,report.encode(),RESEARCH_PILOT_ROOT)
    component_path=root/"components.json";component_raw=_json_bytes({"descriptor":loaded["reference"],"components":components},newline=True)
    component_sha=_sha256(component_raw)
    if persist:_write_immutable(component_path,component_raw,RESEARCH_PILOT_ROOT)
    receipt={"schema":"v4.pdf_research.sectioned_reuse_receipt.v4","status":"REUSED_SOURCE_STAGE_SECTIONED_REPORT_SOURCE_REVIEW_PENDING", "document_id":value["document_id"],
             "page_input":value["source_input"],"descriptor":loaded["reference"],"report":{"path":str(path),"sha256":digest},
             "components":{"path":str(component_path),"sha256":component_sha},"new_model_POSTs":0,"original_source_reports_unchanged":True,
             "manual_source_constraints":True,"research_only":True,"production_allowed":False,"orders_sent":False,"buy_gate_updated":False}
    receipt_path=root/"receipt.json";receipt_raw=_json_bytes(receipt,newline=True)
    if persist:_write_immutable(receipt_path,receipt_raw,RESEARCH_PILOT_ROOT)
    return {**receipt,"receipt":{"path":str(receipt_path),"sha256":_sha256(receipt_raw)}}


def verify_sectioned_content_v4() -> dict[str, Any]:
    loaded=load_sectioned_reuse_v4();value=loaded["value"]
    expected=RESEARCH_PILOT_ROOT / "independent-review/sectioned667-name-erratum-content-review-v4.json"
    if value["content_review_path"]!=str(expected) or expected.is_symlink() or not expected.is_file():
        raise BatchError("SECTIONED_CONTENT_REVIEW_REQUIRED")
    review_ref={"path":str(expected),"sha256":_sha256_file(expected)};review,_=_analysis_ref(review_ref,root=RESEARCH_PILOT_ROOT)
    generated=build_sectioned_reuse_v4(persist=False)
    for field in ("report","components","receipt"):_analysis_ref(generated[field],parse_json=False)
    checks=("all20_pages","important_omissions","unsupported_assertions","cross_section_conflicts","numeric_period_unit_conditions","C4_C5_unknown_exclusions","C6_manual_rating")
    if (review.get("status")!="SECTIONED_REPORT_WITH_SOURCE_CONSTRAINTS_PASS" or review.get("reviewer")!="/root/pdf_model_analysis_reviewer"
            or review.get("document_id")!=value["document_id"] or review.get("source_pages_reviewed")!=list(range(1,21))
            or review.get("descriptor")!=loaded["reference"] or review.get("page_input")!=value["source_input"]
            or any(review.get(k)!=generated[k] for k in ("report","components","receipt"))
            or any(review.get("checks",{}).get(k) is not True for k in checks)):
        raise BatchError("SECTIONED_CONTENT_PASS_BINDING_MISMATCH")
    return {**generated,"content_review":review_ref,"content_status":review["status"]}


def _sectioned_stage_index(state_root: Path, chunk: Any, receipt: Mapping[str, Any]) -> dict[str, Any]:
    stream_path=state_root/"evidence/streams"/receipt["queue_idempotency_key"]/"attempt-0001/stream-receipt.json"
    stream_raw=stream_path.read_bytes();stream=json.loads(stream_raw)
    requests=sorted(stream_path.parent.glob("round-*.request-input.json"))
    if stream.get("status")!="SUCCEEDED" or not requests or not 1<=stream.get("request_rounds",0)<=7:
        raise BatchError("SECTIONED_SOURCE_STREAM_SCOPE_MISMATCH")
    return {"initial_input_pages":sorted({u.page_number for u in chunk.units}),
            "tool_requested_pages":_sectioned_requested_pages(json.loads(requests[-1].read_bytes())["messages"]),
            "stream":{"path":str(stream_path),"sha256":_sha256(stream_raw)},
            "requests":[{"path":str(p),"sha256":_sha256_file(p)} for p in requests]}


if __name__ == "__main__":
    raise SystemExit(main())

