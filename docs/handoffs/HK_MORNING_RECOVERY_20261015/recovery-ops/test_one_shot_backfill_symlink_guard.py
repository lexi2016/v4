from __future__ import annotations

import hashlib
import importlib.util
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(
    "/Users/lexi/Desktop/学习/agents调试/V4_HK_ACCEPTANCE_RECOVERY_20261015/writer/"
    "run_hk_morning_cached_recovery_once.py"
)
SPEC = importlib.util.spec_from_file_location("hk_morning_recovery_once_test", SCRIPT_PATH)
RECOVERY = importlib.util.module_from_spec(SPEC)
assert SPEC is not None and SPEC.loader is not None
SPEC.loader.exec_module(RECOVERY)


class BackfillSymlinkInventoryTest(unittest.TestCase):
    def test_nested_symlink_parent_cannot_admit_outside_sentinel(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="hk-backfill-symlink-repro-", dir=SCRIPT_PATH.parent
        ) as temporary:
            root = Path(temporary)
            raw_root = root / "stage" / "raw"
            backfill_root = raw_root / "backfill"
            run_root = backfill_root / "run-allowed-1"
            outside = root / "outside"
            sentinel = outside / RECOVERY.TRADE_DATE / "sentinel.json"
            (run_root).mkdir(parents=True)
            sentinel.parent.mkdir(parents=True)
            sentinel.write_text('{"outside": true}\n', encoding="utf-8")
            (run_root / "runs").symlink_to(outside, target_is_directory=True)

            lexical_sentinel = (
                run_root / "runs" / RECOVERY.TRADE_DATE / "sentinel.json"
            )
            after = {
                str(lexical_sentinel): {
                    "kind": "file",
                    "size": sentinel.stat().st_size,
                    "sha256": hashlib.sha256(sentinel.read_bytes()).hexdigest(),
                }
            }

            with self.assertRaisesRegex(RuntimeError, "symlink"):
                RECOVERY._backfill_date_inventory(raw_root, "raw")
            with self.assertRaisesRegex(RuntimeError, "symlink"):
                RECOVERY._compare_inventory(
                    {},
                    after,
                    allowed_backfill_run_ids={"run-allowed-1"},
                    backfill_root=raw_root,
                )

            self.assertEqual(sentinel.read_text(encoding="utf-8"), '{"outside": true}\n')


if __name__ == "__main__":
    unittest.main(verbosity=2)
