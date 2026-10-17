"""Lossless, source-bound reader chunk planning for long announcements."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import re
from typing import Any, Callable


PART_PLAN_SCHEMA = "v4.manager_workbench.announcement_chunk_plan.v1"
PART_INPUT_SCHEMA = "v4.manager_workbench.announcement_chunk_part_input.v1"
PART_RESULT_SCHEMA = "v4.manager_workbench.announcement_chunk_part_result.v1"
SYNTHESIS_INPUT_SCHEMA = "v4.manager_workbench.announcement_chunk_synthesis_input.v1"
PART_ADDENDUM = """长正文分片 Reader addendum（保留既有 Reader 全部字段、枚举、标准和最终验证）：
- 本次只收到冻结全文中的一个连续分片，不是完整公告。完整公告共 part_count 个分片；当前 part_index 从 1 开始。
- 先读完本分片的全部 source_units，再在本分片证据范围内独立记录正面、负面、冲突、限定、风险和未知内容。分片没有提到某项，不表示全文没有该事项。
- source_units 的 ID 是完整公告全局 source-unit map 中的 ID。证据必须使用本分片内的 start_source_unit_id/end_source_unit_id，按完整、连续、顺序的全局范围引用；不要自行输出 quote、locator、偏移或哈希。
- fixed_fact_ledger 仅含其全部来源单元均位于本分片的账本记录；它是辅助证据，不替代正文。跨分片的账本关系留待最终综合，不要由局部账本推断。
- 本分片 Reader 输出只是内部证据，不是候选或最终判断；不得把单一分片的正面结果当作选股结论。仍须严格使用原有 13 字段 wire schema，facts 和 changes 均为空数组，source_sha256 和 body_sha256 留空字符串。"""
PART_REPAIR_ADDENDUM = (
    "PART_FIXED_FIELDS_MUST_BE_EMPTY：本分片 reader_output.facts、reader_output.changes 必须为 []，"
    "覆盖前文 changes 指令。仍输出完整 13 字段并遵守其余原字段语义、引证及全部验证。"
)
SYNTHESIS_ADDENDUM = """长正文综合 addendum（保留既有 Reader 全部字段、枚举、选择标准和最终验证）：
- 输入是同一篇冻结公告的全部连续分片的已验证 Reader 报告、精确原文引证和跨分片固定账本记录。确认所有 part_index 从 1 到 part_count 各出现一次，按序综合；这些分片报告是证据，不是候选结果。
- 每个分片的 disposition、direction、selection_basis 和报告数量都只是局部证据，不是投票、计数、加权或多数规则；任何一个正面分片都不能自动使全文成为候选。不得把正面分片数、负面分片数或比例当作选择依据。
- 按本提示前文完整原始 Reader 经营判断规则，逐项评估全部分片提供的正面、负面、冲突、限定、风险和未知证据；包括反面证据和条件语义。分片中的缺席不代表全文缺席；未能协调的结论保留 UNKNOWN/NOT_ASSESSED，不自行消解冲突。最终 disposition 和 direction 必须由综合模型按原标准判断，程序的引用验证和最终投影不替代该判断。
- 每条最终证据只引用输入中给出的全局 source-unit ID，使用 start_source_unit_id/end_source_unit_id 形成完整连续范围。不要输出 quote、locator、偏移或哈希；程序会用原全文 map 验证并投影。不得引用分片输入中没有呈现的单位。
- 最终输出仍是原有单篇文章 13 字段 Reader wire envelope；facts 和 changes 均为空数组，source_sha256 和 body_sha256 留空字符串。程序只在最终投影中确定性注入完整冻结账本与原文来源标记。"""
ORIGINAL_READER_PREAMBLE = (
    "你是公告 Reader。对本次输入的一篇完整公告独立作出研究判断。按 source_units 顺序阅读全文；"
    "它们完整、无损地重建正文。"
)
PART_READER_PREAMBLE = (
    "你是公告 Reader。对冻结公告的当前连续分片作局部证据记录。当前分片不是完整公告；"
    "不得将局部结论当作全文最终判断。"
)
SYNTHESIS_READER_PREAMBLE = (
    "你是公告 Reader。对冻结公告的全部有序分片证据综合作出研究判断。你只收到已验证报告和其中呈现的精确原文引证，"
    "没有收到完整正文；不得声称重新阅读全文或推断未呈现的事实。"
)
PART_ADDENDUM_SHA256 = hashlib.sha256(PART_ADDENDUM.encode("utf-8")).hexdigest()
PART_REPAIR_ADDENDUM_SHA256 = hashlib.sha256(PART_REPAIR_ADDENDUM.encode("utf-8")).hexdigest()
SYNTHESIS_ADDENDUM_SHA256 = hashlib.sha256(SYNTHESIS_ADDENDUM.encode("utf-8")).hexdigest()
SYNTHESIS_TOKEN_CAP = 160_000
PART_TARGET_TOKEN_CAP = 64_000
SYNTHESIS_TARGET_TOKEN_CAP = 64_000
COMPLETION_TOKEN_RESERVE = 32_768
TOKEN_SAFETY_MARGIN = 1_024


def reader_task_system_prompt(original_prompt: str, task: str) -> str:
    """Retain the complete frozen Reader rules while describing the task's evidence surface honestly."""
    if not isinstance(original_prompt, str) or original_prompt.count(ORIGINAL_READER_PREAMBLE) != 1:
        raise ValueError("CHUNK_ORIGINAL_READER_PROMPT_BINDING_INVALID")
    replacement = {"part": PART_READER_PREAMBLE, "synthesis": SYNTHESIS_READER_PREAMBLE}.get(task)
    if replacement is None:
        raise ValueError("CHUNK_READER_TASK_INVALID")
    prompt = original_prompt.replace(ORIGINAL_READER_PREAMBLE, replacement, 1)
    original_reading_step = "先通读完整正文，再结合账本核对固定事实"
    task_reading_step = {
        "part": "先读完本分片正文，再结合本分片账本核对固定事实",
        "synthesis": "先按序综合全部分片报告及其精确引证，再结合跨分片账本核对固定事实",
    }[task]
    if prompt.count(original_reading_step) != 1:
        raise ValueError("CHUNK_ORIGINAL_READER_READING_STEP_BINDING_INVALID")
    return prompt.replace(original_reading_step, task_reading_step, 1)


def part_repair_messages(messages: list[dict[str, Any]], failure_code: str) -> list[dict[str, Any]]:
    """Create a versioned, narrowly scoped validator-feedback prompt for one failed part."""
    if failure_code != "PART_FIXED_FIELDS_MUST_BE_EMPTY":
        raise ValueError("PART_REPAIR_FAILURE_CODE_UNSUPPORTED")
    if (not isinstance(messages, list) or not messages or not isinstance(messages[0], dict)
            or messages[0].get("role") != "system" or not isinstance(messages[0].get("content"), str)):
        raise ValueError("PART_REPAIR_SYSTEM_PROMPT_INVALID")
    if PART_REPAIR_ADDENDUM in messages[0]["content"]:
        raise ValueError("PART_REPAIR_PROMPT_ALREADY_VERSIONED")
    repaired = deepcopy(messages)
    repaired[0]["content"] = repaired[0]["content"].rstrip() + "\n\n" + PART_REPAIR_ADDENDUM
    return repaired
_SHA = re.compile(r"^[0-9a-f]{64}$")
_UNIT_ID = re.compile(r"^U[0-9]{6}$")
_CITATION_FIELDS = (
    "facts", "changes", "impact", "confirmation_conditions", "counter_evidence",
)


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _collect_unit_refs(value: Any) -> list[str]:
    refs: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "source_unit_id" and isinstance(child, str):
                refs.append(child)
            elif key == "source_unit_ids" and isinstance(child, list):
                refs.extend(item for item in child if isinstance(item, str))
            else:
                refs.extend(_collect_unit_refs(child))
    elif isinstance(value, list):
        for child in value:
            refs.extend(_collect_unit_refs(child))
    return refs


def project_part_ledger(ledger: dict[str, Any], part_unit_ids: list[str],
                        model_ledger: Callable[[dict[str, Any]], dict[str, Any]]) -> dict[str, Any]:
    """Expose only fixed-ledger facts whose complete support is inside one part."""
    part_ids = set(part_unit_ids)
    if not part_ids or not isinstance(ledger, dict):
        raise ValueError("PART_LEDGER_INPUT_INVALID")
    projected: dict[str, Any] = {
        "protocol": ledger.get("protocol"),
        "source_unit_count": len(part_unit_ids),
        "source_unit_ids": list(part_unit_ids),
    }
    for name in ("records", "daily_trade_rows", "calculations", "reader_facts", "reader_changes"):
        source_rows = ledger.get(name, [])
        if not isinstance(source_rows, list):
            raise ValueError("PART_LEDGER_COLLECTION_INVALID")
        local_rows = []
        for row in source_rows:
            if not isinstance(row, dict):
                continue
            refs = _collect_unit_refs(row)
            if refs and set(refs).issubset(part_ids):
                local_rows.append(deepcopy(row))
        projected[name] = local_rows
    return model_ledger(projected)


def _validated_units(body: str, body_sha256: str, unit_map: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(body, str) or not body or not _SHA.fullmatch(str(body_sha256)):
        raise ValueError("PART_SOURCE_INVALID")
    if sha256(body.encode("utf-8")) != body_sha256:
        raise ValueError("PART_BODY_SHA_MISMATCH")
    if (not isinstance(unit_map, dict) or unit_map.get("body_sha256") != body_sha256
            or not isinstance(unit_map.get("units"), list) or not unit_map["units"]):
        raise ValueError("PART_UNIT_MAP_INVALID")
    units = unit_map["units"]
    cursor = 0
    material_units = []
    byte_cursor = 0
    for index, unit in enumerate(units, 1):
        if not isinstance(unit, dict):
            raise ValueError("PART_UNIT_INVALID")
        text = unit.get("text")
        unit_id = unit.get("source_unit_id")
        start_cp = unit.get("start_cp")
        end_cp = unit.get("end_cp")
        digest = unit.get("unit_sha256")
        if (unit_id != f"U{index:06d}" or not _UNIT_ID.fullmatch(str(unit_id))
                or type(start_cp) is not int or type(end_cp) is not int
                or start_cp != cursor or end_cp <= start_cp
                or not isinstance(text, str) or body[start_cp:end_cp] != text
                or sha256(text.encode("utf-8")) != digest):
            raise ValueError("PART_UNIT_BINDING_INVALID")
        byte_length = len(text.encode("utf-8"))
        material_units.append({
            "source_unit_id": unit_id,
            "start_cp": start_cp,
            "end_cp": end_cp,
            "start_byte": byte_cursor,
            "end_byte": byte_cursor + byte_length,
            "unit_sha256": digest,
            "text": text,
        })
        cursor = end_cp
        byte_cursor += byte_length
    if cursor != len(body) or byte_cursor != len(body.encode("utf-8")):
        raise ValueError("PART_UNIT_MAP_COVERAGE_INVALID")
    map_material = {
        "protocol": unit_map.get("protocol"),
        "boundary_policy": unit_map.get("boundary_policy"),
        "body_sha256": body_sha256,
        "units": [{key: unit[key] for key in ("source_unit_id", "start_cp", "end_cp", "unit_sha256")}
                  for unit in material_units],
    }
    if sha256(canonical(map_material)) != unit_map.get("source_unit_map_sha256"):
        raise ValueError("PART_UNIT_MAP_SHA_MISMATCH")
    return material_units


def plan_parts(*, article_id: str, source_sha256: str, body: str, body_sha256: str,
               unit_map: dict[str, Any], fixed_fact_ledger: dict[str, Any],
               prompt_sha256: str, synthesis_prompt_sha256: str,
               configuration_sha256: str, batch_binding_sha256: str,
               token_cap: int, render_tokens: Callable[[list[dict[str, Any]], int, int], int],
               token_counter: Callable[[str], int],
               model_ledger: Callable[[dict[str, Any]], dict[str, Any]]) -> dict[str, Any]:
    """Greedily pack complete global units, using exact rendered-message token counts."""
    for value in (source_sha256, body_sha256, prompt_sha256, synthesis_prompt_sha256,
                  configuration_sha256, batch_binding_sha256):
        if not isinstance(value, str) or not _SHA.fullmatch(value):
            raise ValueError("PART_PLAN_SHA_BINDING_INVALID")
    if type(token_cap) is not int or token_cap < 1:
        raise ValueError("PART_TOKEN_CAP_INVALID")
    if token_cap > PART_TARGET_TOKEN_CAP:
        raise ValueError("PART_TOKEN_CAP_EXCEEDS_TARGET")
    units = _validated_units(body, body_sha256, unit_map)
    if (not isinstance(fixed_fact_ledger, dict)
            or fixed_fact_ledger.get("body_sha256") != body_sha256
            or fixed_fact_ledger.get("source_unit_map_sha256") != unit_map.get("source_unit_map_sha256")):
        raise ValueError("PART_LEDGER_SOURCE_BINDING_INVALID")
    raw_estimates = [int(token_counter(unit["text"])) for unit in units]
    if any(value < 0 for value in raw_estimates):
        raise ValueError("PART_UNIT_TOKEN_ESTIMATE_INVALID")
    estimates = [max(1, value) for value in raw_estimates]

    def partition(total_guess: int) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        start = 0
        part_index = 1
        while start < len(units):
            low = start + 1
            high = len(units)
            best = start
            best_tokens = None
            while low <= high:
                middle = (low + high) // 2
                candidate = units[start:middle]
                count = int(render_tokens(candidate, part_index, total_guess))
                if count <= token_cap:
                    best = middle
                    best_tokens = count
                    low = middle + 1
                else:
                    high = middle - 1
            if best == start:
                raise ValueError("PART_SINGLE_SOURCE_UNIT_EXCEEDS_TOKEN_CAP")
            # Tokenizer merges can make counts locally non-monotonic by a few
            # tokens. Check the immediate greedy boundary before committing.
            while best < len(units):
                next_count = int(render_tokens(units[start:best + 1], part_index, total_guess))
                if next_count > token_cap:
                    break
                best += 1
                best_tokens = next_count
            selected = units[start:best]
            first = selected[0]
            last = selected[-1]
            text = "".join(unit["text"] for unit in selected)
            result.append({
                "part_index": part_index,
                "part_count": total_guess,
                "unit_start_index": start,
                "unit_end_index": best,
                "start_source_unit_id": first["source_unit_id"],
                "end_source_unit_id": last["source_unit_id"],
                "source_unit_ids": [unit["source_unit_id"] for unit in selected],
                "start_cp": first["start_cp"],
                "end_cp": last["end_cp"],
                "start_byte": first["start_byte"],
                "end_byte": last["end_byte"],
                "part_sha256": sha256(text.encode("utf-8")),
                "prompt_tokens_exact": best_tokens,
            })
            start = best
            part_index += 1
        return result

    guess = max(1, (sum(estimates) + token_cap - 1) // token_cap)
    parts = []
    for _ in range(8):
        parts = partition(guess)
        actual = len(parts)
        if actual == guess:
            break
        guess = actual
    else:
        raise ValueError("PART_PLAN_COUNT_DID_NOT_CONVERGE")
    # Recount exact prompts with the persisted part_count and verify byte/CP
    # coverage after the final stable partition.
    for part in parts:
        units_for_part = units[int(part["unit_start_index"]):int(part["unit_end_index"])]
        exact = int(render_tokens(units_for_part, part["part_index"], len(parts)))
        if exact > token_cap:
            raise ValueError("PART_RENDERED_PROMPT_EXCEEDS_TOKEN_CAP")
        part["part_count"] = len(parts)
        part["prompt_tokens_exact"] = exact
    plan_material = {
        "schema": PART_PLAN_SCHEMA,
        "article_id": article_id,
        "source_sha256": source_sha256,
        "body_sha256": body_sha256,
        "source_unit_map_sha256": unit_map["source_unit_map_sha256"],
        "fixed_fact_ledger_sha256": fixed_fact_ledger.get("ledger_sha256"),
        "prompt_sha256": prompt_sha256,
        "synthesis_prompt_sha256": synthesis_prompt_sha256,
        "configuration_sha256": configuration_sha256,
        "batch_binding_sha256": batch_binding_sha256,
        "part_addendum_sha256": PART_ADDENDUM_SHA256,
        "synthesis_addendum_sha256": SYNTHESIS_ADDENDUM_SHA256,
        "synthesis_token_cap": SYNTHESIS_TOKEN_CAP,
        "part_target_token_cap": PART_TARGET_TOKEN_CAP,
        "synthesis_target_token_cap": SYNTHESIS_TARGET_TOKEN_CAP,
        "completion_token_reserve": COMPLETION_TOKEN_RESERVE,
        "token_safety_margin": TOKEN_SAFETY_MARGIN,
        "token_cap": token_cap,
        "parts": parts,
    }
    plan_sha256 = sha256(canonical(plan_material))
    return {**plan_material, "plan_sha256": plan_sha256}


def verify_part_coverage(body: str, body_sha256: str, unit_map: dict[str, Any],
                         plan: dict[str, Any]) -> None:
    units = _validated_units(body, body_sha256, unit_map)
    if not isinstance(plan, dict):
        raise ValueError("PART_PLAN_INVALID")
    parts = plan.get("parts")
    if not isinstance(parts, list) or not parts:
        raise ValueError("PART_PLAN_INVALID")
    token_cap = plan.get("token_cap")
    if (plan.get("body_sha256") != body_sha256
            or plan.get("source_unit_map_sha256") != unit_map.get("source_unit_map_sha256")
            or type(token_cap) is not int or not 1 <= token_cap <= PART_TARGET_TOKEN_CAP):
        raise ValueError("PART_PLAN_SOURCE_OR_BUDGET_BINDING_INVALID")
    material = {key: value for key, value in plan.items() if key != "plan_sha256"}
    if (not _SHA.fullmatch(str(plan.get("plan_sha256", "")))
            or sha256(canonical(material)) != plan.get("plan_sha256")):
        raise ValueError("PART_PLAN_SHA_MISMATCH")
    next_index = 0
    pieces: list[bytes] = []
    for expected_index, part in enumerate(parts, 1):
        if (not isinstance(part, dict) or part.get("part_index") != expected_index
                or part.get("part_count") != len(parts)):
            raise ValueError("PART_PLAN_ORDER_INVALID")
        ids = part.get("source_unit_ids")
        if not isinstance(ids, list) or not ids:
            raise ValueError("PART_PLAN_UNIT_IDS_INVALID")
        selected = units[next_index:next_index + len(ids)]
        if [unit["source_unit_id"] for unit in selected] != ids:
            raise ValueError("PART_PLAN_GAP_OR_OVERLAP")
        if (part.get("unit_start_index") != next_index
                or part.get("unit_end_index") != next_index + len(ids)
                or type(part.get("prompt_tokens_exact")) is not int
                or part.get("prompt_tokens_exact") > token_cap):
            raise ValueError("PART_PLAN_TOKEN_OR_INDEX_INVALID")
        text = "".join(unit["text"] for unit in selected)
        raw = text.encode("utf-8")
        first, last = selected[0], selected[-1]
        if (part.get("start_source_unit_id") != first["source_unit_id"]
                or part.get("end_source_unit_id") != last["source_unit_id"]
                or part.get("start_cp") != first["start_cp"]
                or part.get("end_cp") != last["end_cp"]
                or part.get("start_byte") != first["start_byte"]
                or part.get("end_byte") != last["end_byte"]
                or part.get("part_sha256") != sha256(raw)
                or part.get("end_byte") - part.get("start_byte") != len(raw)):
            raise ValueError("PART_PLAN_SOURCE_BINDING_MISMATCH")
        pieces.append(raw)
        next_index += len(ids)
    rebuilt = b"".join(pieces)
    if (next_index != len(units) or rebuilt != body.encode("utf-8")
            or sha256(rebuilt) != body_sha256):
        raise ValueError("PART_PLAN_RECONSTRUCTION_MISMATCH")


def validate_part_envelope(envelope: Any, *, article_id: str, source_sha256: str,
                           body_sha256: str, plan_sha256: str, part: dict[str, Any],
                           unit_map: dict[str, Any], body: str,
                           validate_schema: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
    """Validate one local Reader wire response and project its exact global quotes."""
    if (not isinstance(envelope, dict) or set(envelope) != {"action", "lookup_request", "reader_output"}
            or envelope.get("action") != "complete" or envelope.get("lookup_request") is not None):
        raise ValueError("PART_READER_ENVELOPE_INVALID")
    output = envelope.get("reader_output")
    if not isinstance(output, dict):
        raise ValueError("PART_READER_OUTPUT_INVALID")
    validate_schema(output)
    if output.get("facts") != [] or output.get("changes") != []:
        raise ValueError("PART_FIXED_FIELDS_MUST_BE_EMPTY")
    if output.get("source_sha256") not in ("", source_sha256) or output.get("body_sha256") not in ("", body_sha256):
        raise ValueError("PART_READER_SOURCE_IDENTITY_MISMATCH")
    unit_by_id = {unit["source_unit_id"]: unit for unit in unit_map["units"]}
    allowed = set(part.get("source_unit_ids", []))
    all_unit_ids = [unit["source_unit_id"] for unit in unit_map["units"]]
    order = {unit_id: index for index, unit_id in enumerate(all_unit_ids)}
    projected = deepcopy(output)
    citation_rows = []
    for field_name in _CITATION_FIELDS:
        values = output.get(field_name)
        if not isinstance(values, list):
            raise ValueError("PART_READER_CITATION_COLLECTION_INVALID")
        projected_values = []
        for citation in values:
            if not isinstance(citation, dict):
                raise ValueError("PART_READER_CITATION_INVALID")
            start_wire = citation.get("start_source_unit_id")
            end_wire = citation.get("end_source_unit_id")
            prefix = article_id + "::"
            if (not isinstance(start_wire, str) or not isinstance(end_wire, str)
                    or not start_wire.startswith(prefix) or not end_wire.startswith(prefix)):
                raise ValueError("PART_READER_CITATION_ARTICLE_MISMATCH")
            start_id = start_wire[len(prefix):]
            end_id = end_wire[len(prefix):]
            if start_id not in allowed or end_id not in allowed:
                raise ValueError("PART_READER_CITATION_OUTSIDE_PART")
            if start_id not in unit_by_id or end_id not in unit_by_id or order[start_id] > order[end_id]:
                raise ValueError("PART_READER_CITATION_RANGE_INVALID")
            start_unit = unit_by_id[start_id]
            end_unit = unit_by_id[end_id]
            quote = body[start_unit["start_cp"]:end_unit["end_cp"]]
            expected = "".join(unit["text"] for unit in unit_map["units"][order[start_id]:order[end_id] + 1])
            if quote != expected:
                raise ValueError("PART_READER_CITATION_NOT_CONTIGUOUS")
            projected_values.append({
                "claim": citation["claim"],
                "start_source_unit_id": start_wire,
                "end_source_unit_id": end_wire,
                "quote": quote,
                "locator": f"article_body[codepoint:{start_unit['start_cp']}:{end_unit['end_cp']}]",
            })
            citation_rows.append({
                "field": field_name,
                "start_source_unit_id": start_wire,
                "end_source_unit_id": end_wire,
                "range_sha256": sha256(quote.encode("utf-8")),
            })
        projected[field_name] = projected_values
    return {
        "schema": PART_RESULT_SCHEMA,
        "article_id": article_id,
        "source_sha256": source_sha256,
        "body_sha256": body_sha256,
        "plan_sha256": plan_sha256,
        "part_index": part["part_index"],
        "part_count": part["part_count"],
        "part_sha256": part["part_sha256"],
        "source_unit_map_sha256": unit_map["source_unit_map_sha256"],
        "reader_output": projected,
        "citation_ranges": citation_rows,
    }


def validate_synthesis_citations(envelope: Any, *, article_id: str, unit_map: dict[str, Any],
                                 allowed_intervals: list[tuple[int, int]],
                                 source_sha256: str, body_sha256: str,
                                 validate_schema: Callable[[dict[str, Any]], None]) -> None:
    """Fail closed when final evidence was not shown in any validated part report."""
    if (not isinstance(envelope, dict) or set(envelope) != {"action", "lookup_request", "reader_output"}
            or envelope.get("action") != "complete" or envelope.get("lookup_request") is not None):
        raise ValueError("SYNTHESIS_READER_ENVELOPE_INVALID")
    output = envelope.get("reader_output")
    if not isinstance(output, dict):
        raise ValueError("SYNTHESIS_READER_OUTPUT_INVALID")
    validate_schema(output)
    if output.get("facts") != [] or output.get("changes") != []:
        raise ValueError("SYNTHESIS_FIXED_FIELDS_MUST_BE_EMPTY")
    if output.get("source_sha256") not in ("", source_sha256) or output.get("body_sha256") not in ("", body_sha256):
        raise ValueError("SYNTHESIS_SOURCE_IDENTITY_MISMATCH")
    unit_ids = [unit["source_unit_id"] for unit in unit_map.get("units", []) if isinstance(unit, dict)]
    if not unit_ids:
        raise ValueError("SYNTHESIS_UNIT_MAP_INVALID")
    order = {unit_id: index for index, unit_id in enumerate(unit_ids)}
    allowed: set[int] = set()
    for start, end in allowed_intervals:
        allowed.update(range(start, end + 1))
    for field_name in _CITATION_FIELDS:
        citations = output.get(field_name)
        if not isinstance(citations, list):
            raise ValueError("SYNTHESIS_CITATION_COLLECTION_INVALID")
        for citation in citations:
            if not isinstance(citation, dict):
                raise ValueError("SYNTHESIS_CITATION_INVALID")
            prefix = article_id + "::"
            start_wire = citation.get("start_source_unit_id")
            end_wire = citation.get("end_source_unit_id")
            if (not isinstance(start_wire, str) or not isinstance(end_wire, str)
                    or not start_wire.startswith(prefix) or not end_wire.startswith(prefix)):
                raise ValueError("SYNTHESIS_CITATION_ARTICLE_MISMATCH")
            start_id = start_wire[len(prefix):]
            end_id = end_wire[len(prefix):]
            if start_id not in order or end_id not in order or order[start_id] > order[end_id]:
                raise ValueError("SYNTHESIS_CITATION_RANGE_INVALID")
            cited = set(range(order[start_id], order[end_id] + 1))
            if not cited.issubset(allowed):
                raise ValueError("SYNTHESIS_CITATION_NOT_IN_VALIDATED_PART_EVIDENCE")


def normalize_synthesis_citation_ids(envelope: Any, *, article_id: str, unit_map: dict[str, Any],
                                     part_reports: Any) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Add the article namespace only for an exact, unique validated part citation.

    The returned envelope is detached from the supplied raw response. This deliberately
    recognizes only a pair of bare local unit IDs whose exact article-qualified pair is
    present once in one validated part report and whose units occur in one part only.
    All ordinary synthesis citation validation still runs on the returned envelope.
    """
    if (not isinstance(envelope, dict) or not isinstance(article_id, str) or not article_id
            or not isinstance(unit_map, dict) or not isinstance(unit_map.get("units"), list)
            or not isinstance(part_reports, list) or not part_reports):
        raise ValueError("SYNTHESIS_CITATION_NORMALIZATION_INPUT_INVALID")
    normalized = deepcopy(envelope)
    if any(not isinstance(unit, dict) for unit in unit_map["units"]):
        raise ValueError("SYNTHESIS_CITATION_NORMALIZATION_UNIT_MAP_INVALID")
    unit_ids = [unit.get("source_unit_id") for unit in unit_map["units"]]
    if (not unit_ids or any(not isinstance(unit_id, str) or not _UNIT_ID.fullmatch(unit_id)
                             for unit_id in unit_ids)
            or len(set(unit_ids)) != len(unit_ids)):
        raise ValueError("SYNTHESIS_CITATION_NORMALIZATION_UNIT_MAP_INVALID")
    order = {unit_id: index for index, unit_id in enumerate(unit_ids)}
    prefix = article_id + "::"

    part_occurrences: dict[str, list[int]] = {unit_id: [] for unit_id in unit_ids}
    validated_pairs: dict[tuple[str, str], dict[int, dict[str, Any]]] = {}
    for expected_index, report in enumerate(part_reports, 1):
        descriptor = report.get("part_descriptor") if isinstance(report, dict) else None
        part_ids = descriptor.get("source_unit_ids") if isinstance(descriptor, dict) else None
        ranges = report.get("citation_ranges") if isinstance(report, dict) else None
        if (not isinstance(descriptor, dict) or descriptor.get("part_index") != expected_index
                or descriptor.get("part_count") != len(part_reports)
                or report.get("part_index") != expected_index
                or report.get("part_count") != len(part_reports)
                or not isinstance(part_ids, list) or not part_ids
                or not isinstance(ranges, list)):
            raise ValueError("SYNTHESIS_CITATION_NORMALIZATION_PART_REPORT_INVALID")
        for unit_id in part_ids:
            if unit_id not in part_occurrences:
                raise ValueError("SYNTHESIS_CITATION_NORMALIZATION_PART_UNIT_UNKNOWN")
            part_occurrences[unit_id].append(expected_index)
        for citation in ranges:
            if not isinstance(citation, dict):
                raise ValueError("SYNTHESIS_CITATION_NORMALIZATION_RANGE_INVALID")
            start_wire = citation.get("start_source_unit_id")
            end_wire = citation.get("end_source_unit_id")
            if (not isinstance(start_wire, str) or not isinstance(end_wire, str)
                    or not start_wire.startswith(prefix) or not end_wire.startswith(prefix)):
                raise ValueError("SYNTHESIS_CITATION_NORMALIZATION_RANGE_INVALID")
            start_id, end_id = start_wire[len(prefix):], end_wire[len(prefix):]
            if (start_id not in part_ids or end_id not in part_ids
                    or start_id not in order or end_id not in order or order[start_id] > order[end_id]):
                raise ValueError("SYNTHESIS_CITATION_NORMALIZATION_RANGE_INVALID")
            pair = (start_wire, end_wire)
            part_rows = validated_pairs.setdefault(pair, {})
            saved_row = part_rows.setdefault(expected_index, {
                "part_index": expected_index,
                "part_result_sha256": report.get("part_result_sha256"),
                "part_raw_response_sha256": report.get("part_raw_response_sha256"),
                "validated_range_occurrences": 0,
            })
            saved_row["validated_range_occurrences"] += 1

    edits: list[dict[str, Any]] = []
    output = normalized.get("reader_output") if isinstance(normalized.get("reader_output"), dict) else None
    if output is None:
        return normalized, edits
    for field_name in _CITATION_FIELDS:
        citations = output.get(field_name)
        if not isinstance(citations, list):
            continue
        for citation_index, citation in enumerate(citations):
            if not isinstance(citation, dict):
                continue
            start_wire = citation.get("start_source_unit_id")
            end_wire = citation.get("end_source_unit_id")
            if not isinstance(start_wire, str) or not isinstance(end_wire, str):
                continue
            # Qualified IDs are left untouched for the existing strict validator.
            if start_wire.startswith(prefix) and end_wire.startswith(prefix):
                continue
            if _UNIT_ID.fullmatch(start_wire) and _UNIT_ID.fullmatch(end_wire):
                if (start_wire not in order or end_wire not in order
                        or len(part_occurrences[start_wire]) != 1
                        or len(part_occurrences[end_wire]) != 1
                        or part_occurrences[start_wire] != part_occurrences[end_wire]):
                    raise ValueError("SYNTHESIS_CITATION_NORMALIZATION_UNIQUE_SOURCE_REQUIRED")
                qualified_pair = (prefix + start_wire, prefix + end_wire)
                matches = validated_pairs.get(qualified_pair, {})
                if len(matches) != 1:
                    raise ValueError("SYNTHESIS_CITATION_NORMALIZATION_UNIQUE_VALIDATED_RANGE_REQUIRED")
                citation["start_source_unit_id"], citation["end_source_unit_id"] = qualified_pair
                edits.append({"field": field_name, "citation_index": citation_index,
                              "from_start_source_unit_id": start_wire,
                              "from_end_source_unit_id": end_wire,
                              "to_start_source_unit_id": qualified_pair[0],
                              "to_end_source_unit_id": qualified_pair[1],
                              **next(iter(matches.values()))})
            elif ("::" in start_wire or "::" in end_wire
                  or _UNIT_ID.fullmatch(start_wire) or _UNIT_ID.fullmatch(end_wire)):
                raise ValueError("SYNTHESIS_CITATION_ARTICLE_MISMATCH")
    return normalized, edits


def synthesis_intervals_from_reports(part_reports: Any, *, article_id: str,
                                     unit_map: dict[str, Any]) -> list[list[int]]:
    """Rebuild the exact final-citation allowance from complete validated part receipts."""
    if not isinstance(part_reports, list) or not part_reports:
        raise ValueError("SYNTHESIS_PART_REPORTS_INVALID")
    unit_ids = [unit["source_unit_id"] for unit in unit_map.get("units", []) if isinstance(unit, dict)]
    if not unit_ids:
        raise ValueError("SYNTHESIS_UNIT_MAP_INVALID")
    order = {unit_id: index for index, unit_id in enumerate(unit_ids)}
    count = len(part_reports)
    intervals: list[list[int]] = []
    for expected_index, report in enumerate(part_reports, 1):
        if (not isinstance(report, dict) or report.get("part_index") != expected_index
                or report.get("part_count") != count
                or not _SHA.fullmatch(str(report.get("part_result_sha256", "")))
                or not _SHA.fullmatch(str(report.get("part_raw_response_sha256", "")))):
            raise ValueError("SYNTHESIS_PART_REPORT_ORDER_OR_SHA_INVALID")
        part = report.get("part_descriptor")
        part_ids = part.get("source_unit_ids") if isinstance(part, dict) else None
        citations = report.get("citation_ranges")
        if (not isinstance(part_ids, list) or not part_ids
                or part.get("part_index") != expected_index or part.get("part_count") != count
                or not isinstance(citations, list)):
            raise ValueError("SYNTHESIS_PART_REPORT_DESCRIPTOR_INVALID")
        part_positions = [order.get(unit_id) for unit_id in part_ids]
        if any(position is None for position in part_positions) or part_positions != list(
                range(part_positions[0], part_positions[0] + len(part_positions))):
            raise ValueError("SYNTHESIS_PART_REPORT_UNIT_BINDING_INVALID")
        prefix = article_id + "::"
        for citation in citations:
            if not isinstance(citation, dict):
                raise ValueError("SYNTHESIS_PART_CITATION_INVALID")
            start_wire, end_wire = citation.get("start_source_unit_id"), citation.get("end_source_unit_id")
            if (not isinstance(start_wire, str) or not isinstance(end_wire, str)
                    or not start_wire.startswith(prefix) or not end_wire.startswith(prefix)):
                raise ValueError("SYNTHESIS_PART_CITATION_ARTICLE_MISMATCH")
            start_id, end_id = start_wire[len(prefix):], end_wire[len(prefix):]
            if (start_id not in order or end_id not in order or order[start_id] > order[end_id]
                    or start_id not in part_ids or end_id not in part_ids):
                raise ValueError("SYNTHESIS_PART_CITATION_RANGE_INVALID")
            span = list(range(order[start_id], order[end_id] + 1))
            if not set(span).issubset(set(part_positions)):
                raise ValueError("SYNTHESIS_PART_CITATION_CROSSES_PART")
            intervals.append([span[0], span[-1]])
    return intervals


def cross_part_ledger(ledger: dict[str, Any], unit_map: dict[str, Any], plan: dict[str, Any],
                      model_ledger: Callable[[dict[str, Any]], dict[str, Any]] | None = None) -> dict[str, Any]:
    """Project only fixed-ledger rows whose source units cross part boundaries."""
    part_by_unit = {}
    for part in plan.get("parts", []):
        for unit_id in part.get("source_unit_ids", []):
            part_by_unit[unit_id] = part["part_index"]
    unit_by_id = {unit["source_unit_id"]: unit for unit in unit_map.get("units", [])}
    output: dict[str, Any] = {"schema": "v4.manager_workbench.announcement_cross_part_ledger.v1"}
    for name in ("records", "daily_trade_rows", "calculations", "reader_facts", "reader_changes"):
        values = ledger.get(name, [])
        rows = []
        if isinstance(values, list):
            for value in values:
                if not isinstance(value, dict):
                    continue
                refs = list(dict.fromkeys(_collect_unit_refs(value)))
                if len({part_by_unit.get(ref) for ref in refs if ref in part_by_unit}) < 2:
                    continue
                record = deepcopy(value)
                record["source_unit_quotes"] = [
                    {"source_unit_id": unit_id, "text": unit_by_id[unit_id]["text"]}
                    for unit_id in refs if unit_id in unit_by_id
                ]
                rows.append(record)
        output[name] = rows
    return model_ledger(output) if model_ledger else output

