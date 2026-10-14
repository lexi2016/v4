from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import batch_runner as runner
import build_length_canary as canary


def sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def article_record(number: int, tokens: int) -> canary.ArticleRecord:
    body = f"  frozen body {number}\nwith exact spacing  "
    article_id = f"TEST:ARTICLE:{number:03d}"
    products = (str(number + 1).zfill(64), str(number + 1001).zfill(64))
    metadata = {
        "publication_date": "2026-10-13",
        "title": f"Synthetic title {number}",
        "issuer_name": f"Synthetic issuer {number}",
        "symbol": f"HK.{number:05d}",
        "observed_at": "2026-10-14T00:00:00+08:00",
        "available_at": "2026-10-14T00:00:00+08:00",
        "pit_status": "CANNOT_CONFIRM",
        "source_origins": [
            {
                "source_product_sha256": products[0],
                "source_row_index": number,
                "row_fingerprint_sha256": str(number + 2001).zfill(64),
                "source_ref": f"synthetic://listing/{number}#rows/{number}",
            },
            {
                "source_product_sha256": products[1],
                "source_row_index": 0,
                "row_fingerprint_sha256": str(number + 3001).zfill(64),
                "source_ref": f"synthetic://body/{number}#notice",
            },
        ],
        "source_issuer_codes": [],
    }
    article = {
        "article_id": article_id,
        "source_sha256": str(number + 4001).zfill(64),
        "body_sha256": sha(body),
        "article_body": body,
        "article_metadata": metadata,
    }
    return canary.ArticleRecord(article, tokens, 1)


def make_source_fixture(directory: Path, batch_number: int = 1) -> tuple[str, str]:
    body = "  exact source body\nwith retained spaces  "
    article_id = f"TEST:ARTICLE:SOURCE:{batch_number:02d}"
    source_hashes = ("a" * 64, "b" * 64)
    origins = [
        {
            "source_product_sha256": source_hashes[0],
            "source_row_index": 7,
            "row_fingerprint_sha256": "c" * 64,
            "source_ref": "synthetic://listing/7#rows/7",
        },
        {
            "source_product_sha256": source_hashes[1],
            "source_row_index": 0,
            "row_fingerprint_sha256": "d" * 64,
            "source_ref": "synthetic://body/notice#notice",
        },
    ]
    article = {
        "article_id": article_id,
        "source_sha256": "e" * 64,
        "body_sha256": sha(body),
        "article_body": body,
        "article_metadata": {
            "publication_date": "2026-10-13",
            "title": "Source fixture",
            "issuer_name": "Issuer",
            "symbol": "HK.00001",
            "observed_at": "2026-10-14T00:00:00+08:00",
            "available_at": "2026-10-14T00:00:00+08:00",
            "pit_status": "CANNOT_CONFIRM",
            "source_origins": origins,
            "source_issuer_codes": [],
        },
    }
    batch_id = f"SOURCE_FIXTURE_{batch_number:02d}"
    source_products = [
        {"source_ref": "synthetic://listing", "sha256": source_hashes[0]},
        {"source_ref": "synthetic://body", "sha256": source_hashes[1]},
    ]
    batch = {
        "schema": runner.INPUT_SCHEMA,
        "batch_id": batch_id,
        "expected_count": 1,
        "source_products": source_products,
        "articles": [article],
    }
    contract = runner.load_active_contract()
    user_content = runner.build_messages(batch, contract, "decision_first")[1]["content"]
    chat = {
        "id": f"pipeline_canary_test_source_fixture_{batch_number:02d}",
        "title": "Fixture",
        "manualTitle": True,
        "messages": [{"id": "msg_test_source_fixture", "role": "user", "content": user_content}],
        "model": runner.MODEL_ID,
        "systemPrompt": runner.build_system_prompt(contract, "decision_first"),
        "updatedAt": "2026-10-14T00:00:00.000Z",
    }
    row = {
        "article_id": article_id,
        "source_sha256": article["source_sha256"],
        "body_sha256": article["body_sha256"],
        "body_link_verified": True,
        "listing_row_link_verified": True,
        "title": article["article_metadata"]["title"],
        "issuer_name": article["article_metadata"]["issuer_name"],
        "symbol": article["article_metadata"]["symbol"],
        "available_at": article["article_metadata"]["available_at"],
        "observed_at": article["article_metadata"]["observed_at"],
        "pit_status": "CANNOT_CONFIRM",
        "source_origins": origins,
        "source_issuer_codes": [],
        "body_artifact_ref": "products/body.json#notice",
        "source_row_index": 7,
    }
    group = {
        "batch_number": batch_number,
        "batch_id": batch_id,
        "article_count": 1,
        "article_ids": [article_id],
        "article_manifest": [row],
        "source_products": source_products,
        "batch_input_sha256": "f" * 64,
        "native_chat_id": chat["id"],
        "native_chat_entry_sha256": hashlib.sha256(canary.canonical_json_bytes(chat)).hexdigest(),
        "system_prompt_sha256": hashlib.sha256(chat["systemPrompt"].encode("utf-8")).hexdigest(),
        "user_message_sha256": hashlib.sha256(user_content.encode("utf-8")).hexdigest(),
    }
    import_path = directory / f"{canary.IMPORT_PREFIX}{batch_number:02d}{canary.IMPORT_SUFFIX}"
    import_path.write_text(json.dumps([chat], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest = {
        "packing": {"total_article_count": 1, "group_count": 1, "groups": [group]}
    }
    (directory / "stress-batch-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )
    return article_id, body


class LengthCanaryTests(unittest.TestCase):
    def test_source_loader_verifies_and_preserves_exact_user_body(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source_dir = Path(temp)
            article_id, original_body = make_source_fixture(source_dir)
            contract = runner.load_active_contract()
            records, source = canary.load_source_population(source_dir, contract, expected_count=1)
            self.assertEqual(source["article_count"], 1)
            self.assertEqual(records[0].article["article_id"], article_id)
            self.assertEqual(records[0].article["article_body"], original_body)
            self.assertEqual(records[0].article["body_sha256"], sha(original_body))
            self.assertEqual(runner.validate_batch(canary.make_batch([records[0].article], "TEST"))[0]["article_body"], original_body)

    def test_source_import_file_hashes_are_bound_to_each_distinct_group(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source_dir = Path(temp)
            make_source_fixture(source_dir, batch_number=1)
            manifest_path = source_dir / "stress-batch-manifest.json"
            first_group = json.loads(manifest_path.read_text(encoding="utf-8"))["packing"]["groups"][0]

            make_source_fixture(source_dir, batch_number=2)
            second_group = json.loads(manifest_path.read_text(encoding="utf-8"))["packing"]["groups"][0]
            manifest_path.write_text(
                json.dumps(
                    {
                        "packing": {
                            "total_article_count": 2,
                            "group_count": 2,
                            "groups": [first_group, second_group],
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            _, source = canary.load_source_population(
                source_dir, runner.load_active_contract(), expected_count=2
            )
            hashes_by_batch = {
                item["batch_number"]: item["native_import_file_sha256"]
                for item in source["source_import_files"]
            }
            expected_hashes = {
                batch_number: hashlib.sha256(
                    (source_dir / f"{canary.IMPORT_PREFIX}{batch_number:02d}{canary.IMPORT_SUFFIX}").read_bytes()
                ).hexdigest()
                for batch_number in (1, 2)
            }
            self.assertEqual(hashes_by_batch, expected_hashes)
            self.assertNotEqual(hashes_by_batch[1], hashes_by_batch[2])

    def test_greedy_packing_covers_each_body_and_isolates_oversize_without_truncation(self) -> None:
        records = [article_record(1, 20), article_record(2, 30), article_record(3, 1000), article_record(4, 10)]

        def prompt_counter(items: list[canary.ArticleRecord], batch_id: str) -> int:
            return 100 + len(batch_id) + sum(item.body_tokens for item in items)

        groups, oversize = canary.pack_length_sorted(
            records, prompt_counter, max_input_tokens=180, max_articles=6
        )
        packed_ids = [article_id for group in groups for article_id in group["article_ids"]]
        oversize_ids = [item["article_id"] for item in oversize]
        self.assertEqual(set(packed_ids + oversize_ids), {item.article["article_id"] for item in records})
        self.assertEqual(len(packed_ids + oversize_ids), len(set(packed_ids + oversize_ids)))
        self.assertEqual(len(oversize), 1)
        self.assertEqual(oversize[0]["status"], "OVERSIZE_PENDING")
        self.assertEqual(oversize[0]["article_id"], "TEST:ARTICLE:003")
        self.assertFalse(oversize[0]["body_truncated"])
        self.assertTrue(all(group["status"] == "PREPARED" for group in groups))
        self.assertTrue(all(group["input_tokens_exact"] <= 180 for group in groups))
        self.assertTrue(all(group["output_reserve_tokens_estimate"] == len(group["article_ids"]) * 2048 for group in groups))
        self.assertTrue(all(item.article["article_body"].startswith("  frozen body") for item in records))

    def test_quantile_canary_selection_uses_nearest_exact_feasible_ranks(self) -> None:
        records = [article_record(index, index * 10) for index in range(1, 10)]

        def prompt_counter(items: list[canary.ArticleRecord], _batch_id: str) -> int:
            return 50 + sum(item.body_tokens for item in items)

        selected, receipt = canary.select_quantile_triplet(
            records, prompt_counter, batch_id="A", max_input_tokens=170
        )
        self.assertEqual([item.body_tokens for item in selected], [10, 40, 70])
        self.assertEqual([item["selected_rank"] for item in receipt["quantile_targets"]], [0, 3, 6])
        self.assertEqual(receipt["combined_input_tokens_exact"], 170)
        self.assertEqual(receipt["fallback_rank_distance_sum"], 2)
        singletons = canary.select_quantile_singletons(
            records, prompt_counter, batch_id_prefix="B", max_input_tokens=180
        )
        self.assertEqual([item["label"] for item in singletons], ["short", "medium", "long"])
        self.assertEqual([item["record"].body_tokens for item in singletons], [10, 50, 80])
        self.assertEqual(len({item["record"].article["article_id"] for item in singletons}), 3)
        self.assertTrue(all(item["input_tokens_exact"] <= 180 for item in singletons))


if __name__ == "__main__":
    unittest.main()
