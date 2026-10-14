#!/usr/bin/env python3
"""Prepare, but never run, a length-packed Flash Next canary.

This module reads only the frozen stress manifest and its native input imports.
It does not read answer exports, call an API, execute inference, or modify the
runtime. Every article body remains byte-for-byte intact; an input above the
experiment's 12,000-token work-set target is recorded as OVERSIZE_PENDING.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import heapq
import json
import math
import os
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

import batch_runner as runner


PIPELINE_DIR = Path(__file__).resolve().parent
DEFAULT_SOURCE_DIR = PIPELINE_DIR / "evidence" / "decision-first-20261014" / "stress"
DEFAULT_OUTPUT_DIR = PIPELINE_DIR / "evidence" / "length-single-20261014"
DEFAULT_SOURCE_MANIFEST = DEFAULT_SOURCE_DIR / "stress-batch-manifest.json"
BASELINE_INVENTORY = DEFAULT_OUTPUT_DIR / "baseline-files.json"
IMPORT_PREFIX = "native-import-pressure-batch-"
IMPORT_SUFFIX = "-FROZEN.json"
MAX_INPUT_TOKENS = 12_000
MAX_ARTICLES_PER_BATCH = 6
OUTPUT_RESERVE_PER_ARTICLE = 2_048
QUANTILES = (("short", 0.10), ("medium", 0.50), ("long", 0.90))
BASELINE_PROFILE_HASHES = {
    "legacy": "8c4dd30de9df230cfb93278b60b7b99458490d1b06760a00b877fbbed9086638",
    "grounded": "9ca4648a15b33e8dd15eebf5447d1530c98edf6b949f1f20d27fbe18b5a18627",
    "decision_first": "9b32e0b4d7d93384ab14b54a5b2f1a7a504c80baa8e13c319dbe4537f414f395",
}
EXPECTED_DECISION_GROUNDED_SHA256 = "107fb203c20440ed904763d12f90bee4ca6984c43292527dfc61ba6f8384f772"


class CanaryPrepError(ValueError):
    """Frozen source data or a prepared input fails a required invariant."""


@dataclass(frozen=True)
class ArticleRecord:
    article: dict[str, Any]
    body_tokens: int
    source_batch_number: int


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical_json_bytes(value: Any) -> bytes:
    return runner.canonical_json_bytes(value)


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _read_json(path: Path) -> tuple[bytes, Any]:
    try:
        raw = path.read_bytes()
        return raw, json.loads(raw)
    except Exception as exc:
        raise CanaryPrepError(f"FROZEN_JSON_INVALID:{path.name}") from exc


def _native_import_array(entries: list[dict[str, Any]]) -> bytes:
    if len(entries) != 1:
        raise CanaryPrepError("NATIVE_IMPORT_MUST_CONTAIN_ONE_CHAT")
    return (json.dumps(entries, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _read_user_payload(entry: dict[str, Any]) -> tuple[dict[str, Any], str]:
    messages = entry.get("messages")
    if not isinstance(messages, list) or len(messages) != 1:
        raise CanaryPrepError("SOURCE_CHAT_MESSAGE_SHAPE_INVALID")
    message = messages[0]
    if not isinstance(message, dict) or message.get("role") != "user" or not isinstance(message.get("content"), str):
        raise CanaryPrepError("SOURCE_CHAT_USER_MESSAGE_INVALID")
    content = message["content"]
    prefix = "ARTICLE_DATA_BEGIN\n"
    suffix = "\nARTICLE_DATA_END"
    if not content.startswith(prefix) or not content.endswith(suffix):
        raise CanaryPrepError("SOURCE_CHAT_ARTICLE_DATA_WRAPPER_INVALID")
    try:
        payload = json.loads(content[len(prefix) : -len(suffix)])
    except Exception as exc:
        raise CanaryPrepError("SOURCE_CHAT_ARTICLE_DATA_JSON_INVALID") from exc
    if not isinstance(payload, dict):
        raise CanaryPrepError("SOURCE_CHAT_ARTICLE_DATA_NOT_OBJECT")
    return payload, content


def _article_from_frozen_sources(
    frozen: dict[str, Any], manifest_row: dict[str, Any]
) -> dict[str, Any]:
    article_id = frozen.get("article_id")
    if not isinstance(article_id, str) or article_id != manifest_row.get("article_id"):
        raise CanaryPrepError("SOURCE_ARTICLE_ID_MISMATCH")
    body = frozen.get("article_body")
    if not isinstance(body, str) or body == "":
        raise CanaryPrepError(f"SOURCE_BODY_MISSING:{article_id}")
    body_sha = sha256_bytes(body.encode("utf-8"))
    if body_sha != frozen.get("body_sha256") or body_sha != manifest_row.get("body_sha256"):
        raise CanaryPrepError(f"SOURCE_BODY_SHA_MISMATCH:{article_id}")
    source_sha = frozen.get("source_sha256")
    if source_sha != manifest_row.get("source_sha256"):
        raise CanaryPrepError(f"SOURCE_SHA_MISMATCH:{article_id}")
    if manifest_row.get("body_link_verified") is not True or manifest_row.get("listing_row_link_verified") is not True:
        raise CanaryPrepError(f"SOURCE_PROVENANCE_NOT_VERIFIED:{article_id}")
    original_metadata = frozen.get("article_metadata")
    if not isinstance(original_metadata, dict):
        raise CanaryPrepError(f"SOURCE_METADATA_MISSING:{article_id}")
    metadata = {
        key: original_metadata.get(key)
        for key in (
            "publication_date",
            "title",
            "issuer_name",
            "symbol",
            "observed_at",
            "available_at",
            "pit_status",
        )
    }
    for key in ("title", "issuer_name", "symbol", "publication_date", "observed_at", "available_at", "pit_status"):
        if manifest_row.get(key) is not None and metadata.get(key) != manifest_row.get(key):
            raise CanaryPrepError(f"SOURCE_METADATA_MISMATCH:{article_id}:{key}")
    metadata.update(
        {
            "source_origins": manifest_row.get("source_origins"),
            "source_issuer_codes": manifest_row.get("source_issuer_codes"),
            "body_artifact_ref": manifest_row.get("body_artifact_ref"),
            "source_row_index": manifest_row.get("source_row_index"),
        }
    )
    return {
        "article_id": article_id,
        "source_sha256": source_sha,
        "body_sha256": body_sha,
        "article_body": body,
        "article_metadata": metadata,
    }


def make_batch(articles: list[dict[str, Any]], batch_id: str) -> dict[str, Any]:
    """Construct a validated-batch envelope without changing article data."""
    products: dict[str, dict[str, str]] = {}
    for article in articles:
        origins = article["article_metadata"].get("source_origins")
        if not isinstance(origins, list):
            raise CanaryPrepError("ARTICLE_SOURCE_ORIGINS_MISSING")
        for origin in origins:
            products.setdefault(
                origin["source_product_sha256"],
                {"source_ref": origin["source_ref"].split("#", 1)[0], "sha256": origin["source_product_sha256"]},
            )
    batch = {
        "schema": runner.INPUT_SCHEMA,
        "batch_id": batch_id,
        "expected_count": len(articles),
        "source_products": sorted(products.values(), key=lambda item: (item["source_ref"], item["sha256"])),
        "articles": articles,
    }
    runner.validate_batch(batch)
    return batch


def load_source_population(
    source_dir: Path,
    contract: runner.ActiveContract,
    *,
    expected_count: int | None = 277,
) -> tuple[list[ArticleRecord], dict[str, Any]]:
    """Rebuild the exact 277 input bodies from the frozen manifest and imports."""
    manifest_path = source_dir / "stress-batch-manifest.json"
    manifest_raw, manifest = _read_json(manifest_path)
    groups = manifest.get("packing", {}).get("groups") if isinstance(manifest, dict) else None
    if not isinstance(groups, list) or not groups:
        raise CanaryPrepError("SOURCE_MANIFEST_GROUPS_MISSING")
    expected_total = manifest.get("packing", {}).get("total_article_count")
    if expected_count is not None and expected_total != expected_count:
        raise CanaryPrepError("SOURCE_MANIFEST_POPULATION_COUNT_MISMATCH")
    if manifest.get("packing", {}).get("group_count") != len(groups):
        raise CanaryPrepError("SOURCE_MANIFEST_GROUP_COUNT_MISMATCH")

    records: list[ArticleRecord] = []
    observed_ids: set[str] = set()
    import_file_sha_by_batch: dict[int, str] = {}
    ordered_groups = sorted(groups, key=lambda item: item.get("batch_number", -1))
    if [group.get("batch_number") for group in ordered_groups] != list(range(1, len(groups) + 1)):
        raise CanaryPrepError("SOURCE_MANIFEST_BATCH_SEQUENCE_INVALID")
    for group in ordered_groups:
        number = group["batch_number"]
        import_path = source_dir / f"{IMPORT_PREFIX}{number:02d}{IMPORT_SUFFIX}"
        import_raw, import_value = _read_json(import_path)
        import_file_sha_by_batch[number] = sha256_bytes(import_raw)
        if not isinstance(import_value, list) or len(import_value) != 1:
            raise CanaryPrepError(f"SOURCE_IMPORT_ENTRY_COUNT_INVALID:{number}")
        entry = import_value[0]
        if not isinstance(entry, dict):
            raise CanaryPrepError(f"SOURCE_IMPORT_ENTRY_INVALID:{number}")
        entry_sha = sha256_bytes(canonical_json_bytes(entry))
        if entry_sha != group.get("native_chat_entry_sha256"):
            raise CanaryPrepError(f"SOURCE_IMPORT_ENTRY_SHA_MISMATCH:{number}")
        if entry.get("id") != group.get("native_chat_id") or entry.get("model") != runner.MODEL_ID:
            raise CanaryPrepError(f"SOURCE_IMPORT_IDENTITY_MISMATCH:{number}")
        system_prompt = entry.get("systemPrompt")
        if not isinstance(system_prompt, str) or sha256_bytes(system_prompt.encode("utf-8")) != group.get("system_prompt_sha256"):
            raise CanaryPrepError(f"SOURCE_SYSTEM_PROMPT_SHA_MISMATCH:{number}")
        if system_prompt != runner.build_system_prompt(contract, "decision_first"):
            raise CanaryPrepError(f"SOURCE_SYSTEM_PROMPT_PROFILE_MISMATCH:{number}")
        payload, user_content = _read_user_payload(entry)
        if sha256_bytes(user_content.encode("utf-8")) != group.get("user_message_sha256"):
            raise CanaryPrepError(f"SOURCE_USER_MESSAGE_SHA_MISMATCH:{number}")
        if payload.get("schema") != runner.INPUT_SCHEMA or payload.get("batch_id") != group.get("batch_id"):
            raise CanaryPrepError(f"SOURCE_USER_BATCH_IDENTITY_MISMATCH:{number}")
        frozen_articles = payload.get("articles")
        manifest_rows = group.get("article_manifest")
        if not isinstance(frozen_articles, list) or not isinstance(manifest_rows, list):
            raise CanaryPrepError(f"SOURCE_ARTICLE_LIST_MISSING:{number}")
        if len(frozen_articles) != group.get("article_count") or len(frozen_articles) != len(manifest_rows):
            raise CanaryPrepError(f"SOURCE_ARTICLE_COUNT_MISMATCH:{number}")
        if payload.get("article_count") != len(frozen_articles):
            raise CanaryPrepError(f"SOURCE_USER_ARTICLE_COUNT_MISMATCH:{number}")
        if [x.get("article_id") for x in frozen_articles] != group.get("article_ids"):
            raise CanaryPrepError(f"SOURCE_USER_ARTICLE_ORDER_MISMATCH:{number}")
        rows_by_id = {row.get("article_id"): row for row in manifest_rows}
        if len(rows_by_id) != len(manifest_rows):
            raise CanaryPrepError(f"SOURCE_MANIFEST_DUPLICATE_ARTICLE:{number}")
        articles: list[dict[str, Any]] = []
        for frozen in frozen_articles:
            article_id = frozen.get("article_id")
            if article_id in observed_ids:
                raise CanaryPrepError(f"SOURCE_DUPLICATE_ARTICLE_ID:{article_id}")
            observed_ids.add(article_id)
            row = rows_by_id.get(article_id)
            if row is None:
                raise CanaryPrepError(f"SOURCE_MANIFEST_ARTICLE_MISSING:{article_id}")
            articles.append(_article_from_frozen_sources(frozen, row))
        batch = make_batch(articles, str(group["batch_id"]))
        frozen_products = group.get("source_products")
        if not isinstance(frozen_products, list):
            raise CanaryPrepError(f"SOURCE_PRODUCTS_MISSING:{number}")
        batch["source_products"] = frozen_products
        runner.validate_batch(batch)
        if not runner._is_sha(group.get("batch_input_sha256")):
            raise CanaryPrepError(f"SOURCE_BATCH_INPUT_SHA_INVALID:{number}")
        rebuilt_user = runner.build_messages(batch, contract, "decision_first")[1]["content"]
        if rebuilt_user != user_content:
            raise CanaryPrepError(f"SOURCE_USER_MESSAGE_NOT_REPRODUCIBLE:{number}")
        for article in articles:
            records.append(ArticleRecord(article, -1, number))

    if expected_count is not None and len(records) != expected_count:
        raise CanaryPrepError("SOURCE_RECORD_TOTAL_MISMATCH")
    if len(observed_ids) != len(records):
        raise CanaryPrepError("SOURCE_POPULATION_NOT_UNIQUE")
    return records, {
        "manifest_path": "evidence/decision-first-20261014/stress/stress-batch-manifest.json",
        "manifest_sha256": sha256_bytes(manifest_raw),
        "batch_count": len(groups),
        "article_count": len(records),
        "ordered_article_ids_sha256": sha256_bytes("\n".join(x.article["article_id"] for x in records).encode("utf-8")),
        "source_import_files": [
            {
                "path": f"evidence/decision-first-20261014/stress/{IMPORT_PREFIX}{group['batch_number']:02d}{IMPORT_SUFFIX}",
                "batch_number": group["batch_number"],
                "native_import_file_sha256": import_file_sha_by_batch[group["batch_number"]],
                "source_batch_input_sha256": group["batch_input_sha256"],
                "native_chat_entry_sha256": group["native_chat_entry_sha256"],
                "user_message_sha256": group["user_message_sha256"],
            }
            for group in ordered_groups
        ],
        "groups": ordered_groups,
    }


def body_token_count(tokenizer: Any, body: str) -> int:
    tokens = tokenizer.encode(body, add_special_tokens=False)
    return len(tokens)


def _token_ids_from_template(encoded: Any) -> Any:
    try:
        return encoded["input_ids"]
    except (KeyError, TypeError, IndexError):
        return encoded


def exact_prompt_token_counter(
    tokenizer: Any,
    contract: runner.ActiveContract,
    profile: str,
) -> Callable[[list[ArticleRecord], str], int]:
    tools = runner.make_tool_schema()

    def count(records: list[ArticleRecord], batch_id: str) -> int:
        batch = make_batch([record.article for record in records], batch_id)
        messages = runner.build_messages(batch, contract, profile)
        encoded = tokenizer.apply_chat_template(
            messages,
            tools=tools,
            tokenize=True,
            add_generation_prompt=True,
        )
        token_ids = _token_ids_from_template(encoded)
        if not isinstance(token_ids, (list, tuple)):
            raise CanaryPrepError("EXACT_CHAT_TEMPLATE_COUNT_FAILED")
        return len(token_ids)

    return count


def _batch_articles(records: list[ArticleRecord], batch_id: str) -> dict[str, Any]:
    return make_batch([record.article for record in records], batch_id)


def _quantile_bands(records: list[ArticleRecord]) -> list[dict[str, int | str | float]]:
    if len(records) < 3:
        raise CanaryPrepError("QUANTILE_POPULATION_TOO_SMALL")
    ordered = sorted(records, key=lambda item: (item.body_tokens, item.article["article_id"]))
    size = len(ordered)
    boundaries = ((0, size // 3 - 1), (size // 3, (2 * size) // 3 - 1), ((2 * size) // 3, size - 1))
    output: list[dict[str, int | str | float]] = []
    for (label, quantile), (lower, upper) in zip(QUANTILES, boundaries):
        target = math.floor(quantile * (size - 1))
        target = min(upper, max(lower, target))
        output.append({"label": label, "quantile": quantile, "target_rank": target, "lower_rank": lower, "upper_rank": upper})
    return output


def select_quantile_triplet(
    records: list[ArticleRecord],
    prompt_counter: Callable[[list[ArticleRecord], str], int],
    *,
    batch_id: str,
    max_input_tokens: int,
) -> tuple[list[ArticleRecord], dict[str, Any]]:
    """Choose the nearest feasible short/medium/long ranks, with stable ties."""
    ordered = sorted(records, key=lambda item: (item.body_tokens, item.article["article_id"]))
    bands = _quantile_bands(ordered)
    start = tuple(int(band["target_rank"]) for band in bands)
    heap: list[tuple[int, tuple[int, int, int]]] = [(0, start)]
    visited = {start}
    while heap:
        distance, ranks = heapq.heappop(heap)
        selected = [ordered[index] for index in ranks]
        exact_tokens = prompt_counter(selected, batch_id)
        if exact_tokens <= max_input_tokens:
            return selected, {
                "quantile_targets": [
                    {"label": band["label"], "quantile": band["quantile"], "target_rank": band["target_rank"], "selected_rank": rank, "rank_distance": abs(rank - int(band["target_rank"]) )}
                    for band, rank in zip(bands, ranks)
                ],
                "combined_input_tokens_exact": exact_tokens,
                "max_input_tokens": max_input_tokens,
                "fallback_rank_distance_sum": distance,
                "selection_rule": "nearest exact-feasible ranks within fixed short/mid/long terciles; ties lexicographic by rank tuple",
            }
        for dim, band in enumerate(bands):
            for step in (-1, 1):
                candidate = list(ranks)
                candidate[dim] += step
                if candidate[dim] < int(band["lower_rank"]) or candidate[dim] > int(band["upper_rank"]):
                    continue
                triple = tuple(candidate)
                if triple in visited:
                    continue
                visited.add(triple)
                score = sum(abs(rank - int(target["target_rank"])) for rank, target in zip(triple, bands))
                heapq.heappush(heap, (score, triple))
    raise CanaryPrepError("NO_FEASIBLE_A_QUANTILE_TRIPLET")


def select_quantile_singletons(
    records: list[ArticleRecord],
    prompt_counter: Callable[[list[ArticleRecord], str], int],
    *,
    batch_id_prefix: str,
    max_input_tokens: int,
) -> list[dict[str, Any]]:
    ordered = sorted(records, key=lambda item: (item.body_tokens, item.article["article_id"]))
    bands = _quantile_bands(ordered)
    selections: list[dict[str, Any]] = []
    for batch_number, band in enumerate(bands, start=1):
        target = int(band["target_rank"])
        candidates = sorted(
            range(int(band["lower_rank"]), int(band["upper_rank"]) + 1),
            key=lambda rank: (abs(rank - target), rank),
        )
        chosen: tuple[int, int] | None = None
        batch_id = f"{batch_id_prefix}_{str(band['label']).upper()}"
        for rank in candidates:
            item = ordered[rank]
            token_count = prompt_counter([item], batch_id)
            if token_count <= max_input_tokens:
                chosen = (rank, token_count)
                break
        if chosen is None:
            raise CanaryPrepError(f"NO_FEASIBLE_B_QUANTILE_SINGLETON:{band['label']}")
        rank, token_count = chosen
        selections.append(
            {
                "label": band["label"],
                "quantile": band["quantile"],
                "target_rank": target,
                "selected_rank": rank,
                "rank_distance": abs(rank - target),
                "record": ordered[rank],
                "batch_id": batch_id,
                "input_tokens_exact": token_count,
                "max_input_tokens": max_input_tokens,
                "selection_rule": "nearest exact-feasible rank within fixed quantile tercile; tie to lower rank",
            }
        )
    selected_ids = [item["record"].article["article_id"] for item in selections]
    if len(selected_ids) != len(set(selected_ids)):
        raise CanaryPrepError("B_QUANTILE_SELECTION_OVERLAP")
    return selections


def pack_length_sorted(
    records: list[ArticleRecord],
    prompt_counter: Callable[[list[ArticleRecord], str], int],
    *,
    max_input_tokens: int = MAX_INPUT_TOKENS,
    max_articles: int = MAX_ARTICLES_PER_BATCH,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    ordered = sorted(records, key=lambda item: (-item.body_tokens, item.article["article_id"]))
    groups: list[dict[str, Any]] = []
    oversize: list[dict[str, Any]] = []
    pending: list[ArticleRecord] = []
    pending_tokens = 0
    pack_number = 1

    def current_id(number: int) -> str:
        return f"LENGTH_PACK_{number:04d}"

    def finish_pending() -> None:
        nonlocal pending, pending_tokens, pack_number
        if not pending:
            return
        batch_id = current_id(pack_number)
        reserve = len(pending) * OUTPUT_RESERVE_PER_ARTICLE
        groups.append(
            {
                "batch_id": batch_id,
                "status": "PREPARED",
                "article_ids": [item.article["article_id"] for item in pending],
                "records": list(pending),
                "body_token_counts": [item.body_tokens for item in pending],
                "input_tokens_exact": pending_tokens,
                "output_reserve_tokens_estimate": reserve,
                "output_reserve_per_article_tokens_estimate": OUTPUT_RESERVE_PER_ARTICLE,
                "combined_input_plus_reserve_tokens_estimate": pending_tokens + reserve,
                "max_input_tokens": max_input_tokens,
                "max_articles": max_articles,
                "body_truncated": False,
            }
        )
        pending = []
        pending_tokens = 0
        pack_number += 1

    for record in ordered:
        candidate = pending + [record]
        batch_id = current_id(pack_number)
        if len(candidate) <= max_articles:
            candidate_tokens = prompt_counter(candidate, batch_id)
        else:
            candidate_tokens = max_input_tokens + 1
        if candidate_tokens <= max_input_tokens:
            pending = candidate
            pending_tokens = candidate_tokens
            continue

        finish_pending()
        singleton_id = current_id(pack_number)
        singleton_tokens = prompt_counter([record], singleton_id)
        if singleton_tokens <= max_input_tokens:
            pending = [record]
            pending_tokens = singleton_tokens
        else:
            oversize_batch = _batch_articles([record], singleton_id)
            oversize.append(
                {
                    "batch_id": singleton_id,
                    "status": "OVERSIZE_PENDING",
                    "article_id": record.article["article_id"],
                    "record": record,
                    "body_tokens": record.body_tokens,
                    "input_tokens_exact": singleton_tokens,
                    "input_sha256": runner._input_batch_sha(oversize_batch),
                    "max_input_tokens": max_input_tokens,
                    "body_truncated": False,
                    "reason": "complete article exceeds the frozen experiment input work-set target",
                }
            )
            pack_number += 1
    finish_pending()
    packed_ids = [article_id for group in groups for article_id in group["article_ids"]]
    oversize_ids = [item["article_id"] for item in oversize]
    all_ids = [record.article["article_id"] for record in records]
    if len(packed_ids + oversize_ids) != len(all_ids) or set(packed_ids + oversize_ids) != set(all_ids):
        raise CanaryPrepError("LENGTH_PACK_COVERAGE_MISMATCH")
    if len(packed_ids + oversize_ids) != len(set(packed_ids + oversize_ids)):
        raise CanaryPrepError("LENGTH_PACK_DUPLICATE_ARTICLE")
    return groups, oversize


def _make_native_chat(title_base: str, system_prompt: str, user_content: str) -> dict[str, Any]:
    chat_uuid = str(uuid4())
    message_uuid = str(uuid4())
    return {
        "id": f"pipeline_canary_{chat_uuid}",
        "title": f"{title_base} {chat_uuid[:8]}",
        "manualTitle": True,
        "messages": [{"id": f"msg_{message_uuid}", "role": "user", "content": user_content}],
        "model": runner.MODEL_ID,
        "systemPrompt": system_prompt,
        "updatedAt": _now_utc(),
    }


def _record_manifest(record: ArticleRecord, status: str, *, pack_id: str | None = None) -> dict[str, Any]:
    article = record.article
    return {
        "article_id": article["article_id"],
        "source_sha256": article["source_sha256"],
        "body_sha256": article["body_sha256"],
        "body_characters": len(article["article_body"]),
        "body_utf8_bytes": len(article["article_body"].encode("utf-8")),
        "body_tokens_exact_local": record.body_tokens,
        "source_batch_number": record.source_batch_number,
        "status": status,
        "run_id": None,
        "run_status": "NOT_RUN",
        "content_assessment_status": "NOT_ASSESSED",
        "selection_status": "NOT_ASSESSED",
        "pack_id": pack_id,
        "input_sha256": None,
        "configuration_sha256": None,
        "body_truncated": False,
    }


def _tokenizer_identity(tokenizer_path: Path) -> list[dict[str, Any]]:
    relevant = []
    for path in sorted(tokenizer_path.iterdir()):
        if not path.is_file():
            continue
        if path.name.startswith(("tokenizer", "vocab", "merges", "special_tokens", "added_tokens")) or path.name in {"config.json", "generation_config.json"}:
            raw = path.read_bytes()
            relevant.append({"path": f"model/{path.name}", "size_bytes": len(raw), "sha256": sha256_bytes(raw)})
    if not relevant:
        raise CanaryPrepError("TOKENIZER_ASSETS_NOT_FOUND")
    return relevant


def _load_tokenizer(tokenizer_path: Path) -> Any:
    try:
        from transformers import AutoTokenizer
        return AutoTokenizer.from_pretrained(
            str(tokenizer_path), local_files_only=True, trust_remote_code=False, use_fast=True
        )
    except Exception as exc:
        raise CanaryPrepError("LOCAL_TOKENIZER_UNAVAILABLE") from exc


def _exact_equivalence_probe(
    tokenizer: Any,
    counter: Callable[[list[ArticleRecord], str], int],
    record: ArticleRecord,
    contract: runner.ActiveContract,
    profile: str,
    tokenizer_path: Path,
) -> dict[str, int]:
    batch = make_batch([record.article], "LENGTH_COUNTER_PROBE")
    messages = runner.build_messages(batch, contract, profile)
    runner_count = runner.count_prompt_tokens(messages, runner.make_tool_schema(), tokenizer_path)
    cached_count = counter([record], "LENGTH_COUNTER_PROBE")
    if runner_count != cached_count:
        raise CanaryPrepError("CACHED_TOKENIZER_COUNTER_MISMATCH")
    return {"batch_runner_count": runner_count, "cached_tokenizer_count": cached_count}


def prepare_plan(
    *,
    source_dir: Path = DEFAULT_SOURCE_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    expected_population: int | None = 277,
    max_input_tokens: int = MAX_INPUT_TOKENS,
    max_articles: int = MAX_ARTICLES_PER_BATCH,
    output_reserve_per_article: int = OUTPUT_RESERVE_PER_ARTICLE,
    contract: runner.ActiveContract | None = None,
    tokenizer: Any | None = None,
    runtime_limits: dict[str, Any] | None = None,
    tokenizer_path: Path = runner.OMLX_TOKENIZER_PATH,
) -> tuple[dict[str, Any], dict[str, bytes]]:
    if max_input_tokens <= 0 or max_articles <= 0 or output_reserve_per_article <= 0:
        raise CanaryPrepError("PLANNING_LIMIT_INVALID")
    if output_reserve_per_article != OUTPUT_RESERVE_PER_ARTICLE:
        raise CanaryPrepError("OUTPUT_RESERVE_IS_FROZEN_AT_2048")
    if max_articles != MAX_ARTICLES_PER_BATCH:
        raise CanaryPrepError("MAX_ARTICLES_IS_FROZEN_AT_6")
    output_dir = output_dir.resolve()
    baseline_path = output_dir / "baseline-files.json"
    if not baseline_path.is_file():
        raise CanaryPrepError("PRECHANGE_BASELINE_INVENTORY_REQUIRED")
    baseline_raw, baseline = _read_json(baseline_path)
    if baseline.get("schema") != "qwen_flash_next.prechange_file_inventory.v1":
        raise CanaryPrepError("PRECHANGE_BASELINE_INVENTORY_SCHEMA_INVALID")
    if contract is None:
        contract = runner.load_active_contract()
    if tokenizer is None:
        tokenizer = _load_tokenizer(tokenizer_path)
    runtime_limits = runtime_limits or runner.load_runtime_limits()
    if runtime_limits.get("completion_max_tokens") != 32768:
        raise CanaryPrepError("COMPLETION_LIMIT_CHANGED_FROM_FROZEN_BASELINE")
    if runtime_limits.get("context_limit_tokens") != 262144:
        raise CanaryPrepError("MODEL_CONTEXT_CHANGED_FROM_FROZEN_BASELINE")

    older_prompt_hashes = {
        profile: sha256_bytes(runner.build_system_prompt(contract, profile).encode("utf-8"))
        for profile in ("legacy", "grounded", "decision_first")
    }
    if older_prompt_hashes != BASELINE_PROFILE_HASHES:
        raise CanaryPrepError("LEGACY_PROMPT_PROFILE_BYTES_CHANGED")
    prompt_hashes = {
        profile: sha256_bytes(runner.build_system_prompt(contract, profile).encode("utf-8"))
        for profile in runner.PROMPT_PROFILES
    }
    if prompt_hashes.get("decision_grounded") != EXPECTED_DECISION_GROUNDED_SHA256:
        raise CanaryPrepError("DECISION_GROUNDED_PROMPT_NOT_FROZEN")
    if (
        contract.source_sha256 != "c786c837d4e3b8e06da017f3b7615e7561b5cd782c82b313e570b2bb00d09ee9"
        or len(contract.reader_schema.get("properties", {})) != 13
    ):
        raise CanaryPrepError("ACTIVE_READER_CONTRACT_CHANGED")

    records, source = load_source_population(source_dir, contract, expected_count=expected_population)
    measured_records = [
        ArticleRecord(record.article, body_token_count(tokenizer, record.article["article_body"]), record.source_batch_number)
        for record in records
    ]
    profile_counter = exact_prompt_token_counter(tokenizer, contract, "decision_grounded")
    equivalence = _exact_equivalence_probe(
        tokenizer, profile_counter, measured_records[0], contract, "decision_grounded", tokenizer_path
    )
    prior_records = [record for record in measured_records if record.source_batch_number <= 4]
    sealed_records = [record for record in measured_records if record.source_batch_number >= 5]
    if len(prior_records) != 116 or len(sealed_records) != 161:
        raise CanaryPrepError("A_B_SOURCE_FRAME_COUNTS_INVALID")
    a_selected, a_choice = select_quantile_triplet(
        prior_records,
        profile_counter,
        batch_id="LENGTH_A_PAIRED_3_ARTICLE_CANARY",
        max_input_tokens=max_input_tokens,
    )
    a_batch = _batch_articles(a_selected, "LENGTH_A_PAIRED_3_ARTICLE_CANARY")
    a_input_sha = runner._input_batch_sha(a_batch)
    a_control_messages = runner.build_messages(a_batch, contract, "decision_first")
    a_candidate_messages = runner.build_messages(a_batch, contract, "decision_grounded")
    a_control_tokens = runner.count_prompt_tokens(a_control_messages, runner.make_tool_schema(), tokenizer_path)
    a_candidate_tokens = profile_counter(a_selected, "LENGTH_A_PAIRED_3_ARTICLE_CANARY")
    if a_control_messages[1] != a_candidate_messages[1] or a_control_tokens > max_input_tokens or a_candidate_tokens > max_input_tokens:
        raise CanaryPrepError("A_PAIRED_INPUT_MISMATCH_OR_OVER_LIMIT")

    b_selections = select_quantile_singletons(
        sealed_records,
        profile_counter,
        batch_id_prefix="LENGTH_B_SEALED",
        max_input_tokens=max_input_tokens,
    )
    a_ids = {record.article["article_id"] for record in a_selected}
    b_ids = {item["record"].article["article_id"] for item in b_selections}
    if len(a_ids) != 3 or len(b_ids) != 3 or a_ids & b_ids:
        raise CanaryPrepError("A_B_SAMPLE_FRAME_OVERLAP")

    pack_groups, oversize = pack_length_sorted(
        measured_records,
        profile_counter,
        max_input_tokens=max_input_tokens,
        max_articles=max_articles,
    )
    full_ids = [record.article["article_id"] for record in measured_records]
    packed_ids = [article_id for group in pack_groups for article_id in group["article_ids"]]
    oversize_ids = [item["article_id"] for item in oversize]
    if len(full_ids) != len(set(full_ids)) or set(full_ids) != set(packed_ids + oversize_ids):
        raise CanaryPrepError("FULL_POPULATION_COVERAGE_INVALID")

    all_body_counts = sorted(record.body_tokens for record in measured_records)
    p95_index = min(len(all_body_counts) - 1, math.ceil(0.95 * len(all_body_counts)) - 1)
    tokenizer_identity = _tokenizer_identity(tokenizer_path)
    safe_runtime = {
        key: value
        for key, value in runtime_limits.items()
        if key not in {"model_config_ref", "global_settings_ref", "model_settings_ref"}
    }
    config_identity = {
        "model_id": runner.MODEL_ID,
        "active_contract_source_sha256": contract.source_sha256,
        "active_prompt_version": contract.prompt_version,
        "runtime_limits": safe_runtime,
        "experiment_max_input_tokens": max_input_tokens,
        "max_articles_per_batch": max_articles,
        "output_reserve_tokens_per_article_estimate": output_reserve_per_article,
        "prompt_profile_hashes": prompt_hashes,
        "reader_schema_sha256": sha256_bytes(canonical_json_bytes(contract.reader_schema)),
        "tool_schema_sha256": sha256_bytes(canonical_json_bytes(runner.make_tool_schema())),
        "tokenizer_assets": tokenizer_identity,
    }
    config_sha = sha256_bytes(canonical_json_bytes(config_identity))
    implementation_sources = []
    for name in (
        "batch_runner.py",
        "test_batch_runner.py",
        "build_length_canary.py",
        "test_build_length_canary.py",
    ):
        raw = (PIPELINE_DIR / name).read_bytes()
        implementation_sources.append({"path": name, "size_bytes": len(raw), "sha256": sha256_bytes(raw)})

    import_payloads: dict[str, bytes] = {}
    import_manifest: dict[str, Any] = {}
    a_user_content = a_control_messages[1]["content"]
    for role, profile, messages, token_count in (
        ("control", "decision_first", a_control_messages, a_control_tokens),
        ("candidate", "decision_grounded", a_candidate_messages, a_candidate_tokens),
    ):
        if messages[1]["content"] != a_user_content:
            raise CanaryPrepError("A_CONTROL_CANDIDATE_USER_CONTENT_CHANGED")
        filename = f"native-import-A-{role}-FROZEN.json"
        chat = _make_native_chat(
            f"Flash length A {role} {profile} paired canary",
            messages[0]["content"],
            messages[1]["content"],
        )
        payload = _native_import_array([chat])
        import_payloads[filename] = payload
        import_manifest[filename] = {
            "role": role,
            "prompt_profile": profile,
            "file_sha256": sha256_bytes(payload),
            "file_bytes": len(payload),
            "input_sha256": a_input_sha,
            "configuration_sha256": config_sha,
            "run_id": None,
            "native_entry_sha256": sha256_bytes(canonical_json_bytes(chat)),
            "chat_id": chat["id"],
            "title": chat["title"],
            "user_message_sha256": sha256_bytes(chat["messages"][0]["content"].encode("utf-8")),
            "system_prompt_sha256": sha256_bytes(chat["systemPrompt"].encode("utf-8")),
            "article_ids": [record.article["article_id"] for record in a_selected],
            "input_tokens_exact": token_count,
            "output_reserve_tokens_estimate": len(a_selected) * output_reserve_per_article,
            "body_truncated": False,
            "inference_status": "NOT_RUN",
        }
    for item in b_selections:
        record = item["record"]
        batch = _batch_articles([record], item["batch_id"])
        messages = runner.build_messages(batch, contract, "decision_grounded")
        filename = f"native-import-B-{item['label']}-FROZEN.json"
        chat = _make_native_chat(
            f"Flash length B sealed {item['label']} decision_grounded",
            messages[0]["content"],
            messages[1]["content"],
        )
        payload = _native_import_array([chat])
        import_payloads[filename] = payload
        item["import_filename"] = filename
        item["record_manifest"] = _record_manifest(record, "PREPARED")
        item["record_manifest"]["input_sha256"] = runner._input_batch_sha(batch)
        item["record_manifest"]["configuration_sha256"] = config_sha
        import_manifest[filename] = {
            "role": "sealed_unmeasured_sample",
            "prompt_profile": "decision_grounded",
            "file_sha256": sha256_bytes(payload),
            "file_bytes": len(payload),
            "input_sha256": runner._input_batch_sha(batch),
            "configuration_sha256": config_sha,
            "run_id": None,
            "native_entry_sha256": sha256_bytes(canonical_json_bytes(chat)),
            "chat_id": chat["id"],
            "title": chat["title"],
            "user_message_sha256": sha256_bytes(chat["messages"][0]["content"].encode("utf-8")),
            "system_prompt_sha256": sha256_bytes(chat["systemPrompt"].encode("utf-8")),
            "article_ids": [record.article["article_id"]],
            "body_tokens_exact_local": record.body_tokens,
            "input_tokens_exact": item["input_tokens_exact"],
            "output_reserve_tokens_estimate": output_reserve_per_article,
            "body_truncated": False,
            "inference_status": "SEALED_NOT_RUN",
        }

    prepared_article_ids = {article_id for group in pack_groups for article_id in group["article_ids"]}
    pack_by_id = {article_id: group["batch_id"] for group in pack_groups for article_id in group["article_ids"]}
    oversize_by_id = {item["article_id"]: item for item in oversize}
    population_manifest = []
    group_inputs: dict[str, dict[str, str]] = {}
    for group in pack_groups:
        batch = _batch_articles(group["records"], group["batch_id"])
        messages = runner.build_messages(batch, contract, "decision_grounded")
        group_inputs[group["batch_id"]] = {
            "input_sha256": runner._input_batch_sha(batch),
            "user_message_sha256": sha256_bytes(messages[1]["content"].encode("utf-8")),
        }
    oversize_by_id = {item["article_id"]: item for item in oversize}
    for record in sorted(measured_records, key=lambda item: item.article["article_id"]):
        article_id = record.article["article_id"]
        if article_id in prepared_article_ids:
            status = "PREPARED"
            pack_id = pack_by_id[article_id]
        else:
            status = "OVERSIZE_PENDING"
            pack_id = None
        item = _record_manifest(record, status, pack_id=pack_id)
        item["configuration_sha256"] = config_sha
        item["input_sha256"] = (
            group_inputs[pack_id]["input_sha256"]
            if pack_id is not None
            else oversize_by_id[article_id]["input_sha256"]
        )
        if status == "OVERSIZE_PENDING":
            item["single_article_input_tokens_exact"] = oversize_by_id[article_id]["input_tokens_exact"]
            item["pack_id"] = oversize_by_id[article_id]["batch_id"]
            item["max_input_tokens"] = max_input_tokens
            item["reason"] = oversize_by_id[article_id]["reason"]
        population_manifest.append(item)

    serial_groups = []
    for group in pack_groups:
        identifiers = group_inputs[group["batch_id"]]
        serial_groups.append(
            {
                key: value
                for key, value in group.items()
                if key != "records"
            }
            | {
                "input_sha256": identifiers["input_sha256"],
                "user_message_sha256": identifiers["user_message_sha256"],
                "configuration_sha256": config_sha,
                "run_id": None,
                "article_records": [
                    {
                        **_record_manifest(record, "PREPARED", pack_id=group["batch_id"]),
                        "input_sha256": identifiers["input_sha256"],
                        "configuration_sha256": config_sha,
                    }
                    for record in group["records"]
                ]
            }
        )
    serial_oversize = [
        {
            key: value
            for key, value in item.items()
            if key != "record"
        }
        | {
            "configuration_sha256": config_sha,
            "run_id": None,
            "source_sha256": next(r.article["source_sha256"] for r in measured_records if r.article["article_id"] == item["article_id"]),
            "body_sha256": next(r.article["body_sha256"] for r in measured_records if r.article["article_id"] == item["article_id"]),
            "source_batch_number": next(r.source_batch_number for r in measured_records if r.article["article_id"] == item["article_id"]),
            "content_assessment_status": "NOT_ASSESSED",
            "selection_status": "NOT_ASSESSED",
        }
        for item in oversize
    ]

    import_names = list(import_payloads)
    all_ids = [x["article_id"] for x in population_manifest]
    manifest = {
        "schema": "qwen_flash_next.length_canary_manifest.v1",
        "created_at_utc": _now_utc(),
        "status": "PREPARED_PENDING_INDEPENDENT_REVIEW",
        "execution": {"api_calls": 0, "inference_started": False, "ui_imported": False, "services_changed": False, "runtime_configuration_changed": False},
        "implementation_sources": implementation_sources,
        "baseline": {
            "manifest_path": "baseline-files.json",
            "manifest_sha256": sha256_bytes(baseline_raw),
            "old_file_count": baseline.get("file_count"),
            "old_files": baseline.get("files"),
        },
        "source": {
            **{key: value for key, value in source.items() if key != "groups"},
            "population_count": len(measured_records),
            "source_batch_input_sha256_recomputed": False,
            "source_batch_input_sha256_limitation": "the original validated batch object was not persisted in the native import; the frozen manifest SHA is retained, while every full body/source SHA and exact user-message bytes were independently checked",
            "first_116_frame": "stress-batch-manifest groups 1-4, preserving frozen input order; no answer text used for sample selection",
            "sealed_161_frame": "stress-batch-manifest groups 5-10; input-only selection; no answer text used for sample selection",
        },
        "configuration": {
            **config_identity,
            "configuration_sha256": config_sha,
            "old_prompt_profiles_unchanged": older_prompt_hashes == BASELINE_PROFILE_HASHES,
            "prompt_profile_default": "legacy",
            "reader_validator_modified": False,
            "runtime_temperature_changed": False,
            "thinking_expected_for_visible_ui": "OFF; parent UI verification required",
            "web_search_expected_for_visible_ui": "ON; parent UI verification required",
            "visible_run_order": ["A control decision_first", "A candidate decision_grounded"],
        },
        "planning_contract": {
            "body_tokenization": "AutoTokenizer local encode(add_special_tokens=False); body strings preserved",
            "prompt_tokenization": "exact apply_chat_template with the active schema and WEB_TOOLS",
            "counter_equivalence_probe": equivalence,
            "experiment_input_work_set_target_tokens": max_input_tokens,
            "input_target_is_model_context_limit": False,
            "effective_model_context_tokens": runtime_limits["context_limit_tokens"],
            "effective_completion_max_tokens": runtime_limits["completion_max_tokens"],
            "max_articles_per_packed_batch": max_articles,
            "visible_run_concurrency": 1,
            "visible_run_concurrency_enforcement": "controller executes one visible request at a time; no scheduler or service setting changed",
            "output_reserve_estimate_per_article": output_reserve_per_article,
            "output_reserve_is_generation_cap": False,
            "tool_schema_enabled": True,
            "body_truncation_allowed": False,
        },
        "population_statistics": {
            "article_count": len(measured_records),
            "body_tokens_min": min(all_body_counts),
            "body_tokens_median": all_body_counts[len(all_body_counts) // 2],
            "body_tokens_p95": all_body_counts[p95_index],
            "body_tokens_max": max(all_body_counts),
            "body_tokens_total": sum(all_body_counts),
            "body_token_counts_sha256": sha256_bytes(canonical_json_bytes([
                {"article_id": record.article["article_id"], "body_tokens": record.body_tokens}
                for record in sorted(measured_records, key=lambda item: item.article["article_id"])
            ])),
        },
        "full_population_packing": {
            "sort_rule": "body token count descending, then exact article_id ascending; greedy in this order",
            "group_count": len(serial_groups),
            "prepared_count": len(prepared_article_ids),
            "oversize_pending_count": len(serial_oversize),
            "coverage_count": len(all_ids),
            "coverage_unique": len(set(all_ids)) == len(all_ids),
            "all_source_body_sha_verified": True,
            "all_body_text_unchanged": True,
            "groups": serial_groups,
            "oversize_pending": serial_oversize,
        },
        "canary_samples": {
            "A_paired": {
                "frame_article_count": len(prior_records),
                "selection_policy": "fixed short/medium/long 10/50/90% quantile ranks by exact body token count; nearest exact-feasible ranks within each tercile if original ranks exceed 12,000 tokens",
                "selected_article_ids": [record.article["article_id"] for record in a_selected],
                "selected_records": [
                    {
                        **_record_manifest(record, "PREPARED"),
                        "input_sha256": a_input_sha,
                        "configuration_sha256": config_sha,
                    }
                    for record in a_selected
                ],
                "quantile_choice": a_choice,
                "input_sha256": a_input_sha,
                "configuration_sha256": config_sha,
                "same_user_content_exact": a_control_messages[1]["content"] == a_candidate_messages[1]["content"],
                "control_input_tokens_exact": a_control_tokens,
                "candidate_input_tokens_exact": a_candidate_tokens,
                "output_reserve_tokens_estimate_each": len(a_selected) * output_reserve_per_article,
                "one_chat_per_import_file": True,
                "inference_status": "NOT_RUN",
                "imports": ["native-import-A-control-FROZEN.json", "native-import-A-candidate-FROZEN.json"],
            },
            "B_sealed_unmeasured": {
                "frame_article_count": len(sealed_records),
                "selection_policy": "fixed short/medium/long 10/50/90% quantile ranks by exact body token count; nearest exact-feasible singleton within each tercile",
                "selected_article_ids": [item["record"].article["article_id"] for item in b_selections],
                "selected_records": [item["record_manifest"] for item in b_selections],
                "batch_input_tokens_exact": [item["input_tokens_exact"] for item in b_selections],
                "output_reserve_tokens_estimate_each": output_reserve_per_article,
                "one_article_per_small_batch": True,
                "one_chat_per_import_file": True,
                "answer_text_read_for_selection": False,
                "inference_status": "SEALED_NOT_RUN",
                "imports": [item["import_filename"] for item in b_selections],
            },
            "imports": import_manifest,
            "all_import_files": import_names,
        },
        "pre_frozen_evaluation": {
            "A_pair_metrics": ["end_to_end_elapsed_seconds", "prefill_ttft_seconds", "generation_seconds", "tool_calls", "tool_failures", "coverage_per_article"],
            "correctness_gate": ["active_13_field_schema", "exact_quote_validation", "independent_semantic_review", "PIT_review", "zero_major_errors", "no_truncation"],
            "speed_claim_rule": "report paired timings only after correctness gate passes; minimum numeric speedup threshold NOT_SPECIFIED",
            "future_throughput_metric": "independently accepted complete articles per minute; report alongside, not replaced by, tokens per second",
            "canary_scope_only": True,
            "full_population_pass_claim": False,
        },
        "workflow_constraints": {
            "current_authoritative_flow": "existing capture -> length queue -> single concurrency -> per-article validation -> retry failed articles only -> independent summary review",
            "per_article_identity": ["run_id", "input_sha256", "configuration_sha256", "status"],
            "status_semantics": "PREPARED and OVERSIZE_PENDING describe workflow readiness; NOT_ASSESSED is not NOT_SELECTED",
            "web_gap_failure_behavior": "a missing-fact web lookup failure remains localized to that article/field and must not hold up the entire batch",
            "future_workbench_owner": "existing authorized owner; this canary creates no second producer, permanent service, or background executor",
        },
    }
    filenames = list(import_payloads) + ["length-canary-manifest.json"]
    for name in filenames:
        if (output_dir / name).exists():
            raise CanaryPrepError(f"OUTPUT_PATH_ALREADY_EXISTS:{name}")
    chat_ids = [value["chat_id"] for value in import_manifest.values()]
    titles = [value["title"] for value in import_manifest.values()]
    if len(chat_ids) != len(set(chat_ids)) or len(titles) != len(set(titles)):
        raise CanaryPrepError("NATIVE_IMPORT_CHAT_ID_OR_TITLE_NOT_UNIQUE")
    import_payloads["length-canary-manifest.json"] = _json_bytes(manifest)
    return manifest, import_payloads


def write_plan(output_dir: Path, files: dict[str, bytes]) -> None:
    output_dir = output_dir.resolve()
    if not output_dir.is_dir():
        raise CanaryPrepError("OUTPUT_DIRECTORY_MISSING")
    for name, raw in files.items():
        if Path(name).name != name:
            raise CanaryPrepError("OUTPUT_FILENAME_INVALID")
        path = output_dir / name
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(raw)
            os.chmod(path, 0o600)
        except FileExistsError as exc:
            raise CanaryPrepError(f"OUTPUT_PATH_ALREADY_EXISTS:{name}") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare frozen, input-only Flash Next length canary artifacts.")
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--max-input-tokens", type=int, default=MAX_INPUT_TOKENS)
    parser.add_argument("--max-articles", type=int, default=MAX_ARTICLES_PER_BATCH)
    args = parser.parse_args(argv)
    manifest, files = prepare_plan(
        source_dir=args.source_dir,
        output_dir=args.output_dir,
        max_input_tokens=args.max_input_tokens,
        max_articles=args.max_articles,
    )
    write_plan(args.output_dir, files)
    print(json.dumps({
        "status": manifest["status"],
        "population": manifest["population_statistics"]["article_count"],
        "prepared": manifest["full_population_packing"]["prepared_count"],
        "oversize_pending": manifest["full_population_packing"]["oversize_pending_count"],
        "pack_count": manifest["full_population_packing"]["group_count"],
        "A_ids": manifest["canary_samples"]["A_paired"]["selected_article_ids"],
        "B_ids": manifest["canary_samples"]["B_sealed_unmeasured"]["selected_article_ids"],
        "config_sha256": manifest["configuration"]["configuration_sha256"],
        "written_files": sorted(files),
        "inference_started": False,
        "api_calls": 0,
    }, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
