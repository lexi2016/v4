from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prepare_candidate


class CandidateManifestTests(unittest.TestCase):
    def source_manifest(self) -> dict:
        entries = [
            {"kind": "file", "mode": "0444", "path": "one.py", "sha256": "a", "size": 1},
            {"kind": "file", "mode": "0444", "path": "two.py", "sha256": "b", "size": 2},
        ]
        return {
            "activation_status": "NOT_ACTIVATED",
            "application_inventory": {
                "aggregate_sha256": prepare_candidate.inventory_aggregate(entries),
                "entries": entries,
            },
            "candidate": {
                "app_root": "/old/app",
                "release_id": "old-release",
                "root": "/old",
            },
            "candidate_status": "INDEPENDENT_CANDIDATE_PASS",
        }

    def test_entry_count_is_derived_and_identity_is_rebound(self) -> None:
        source = self.source_manifest()
        original = copy.deepcopy(source)
        result = prepare_candidate._candidate_manifest(
            source, Path("/candidate/app"), Path("/candidate")
        )

        self.assertEqual(result["application_inventory"]["entry_count"], len(source["application_inventory"]["entries"]))
        self.assertEqual(result["application_inventory"]["entries"], original["application_inventory"]["entries"])
        self.assertEqual(result["application_inventory"]["aggregate_sha256"], original["application_inventory"]["aggregate_sha256"])
        self.assertEqual(result["candidate"]["release_id"], prepare_candidate.CANDIDATE_RELEASE_ID)
        self.assertEqual(result["candidate"]["app_root"], "/candidate/app")
        self.assertEqual(result["candidate"]["root"], "/candidate")
        self.assertEqual(result["activation_status"], "NOT_ACTIVATED")
        self.assertEqual(result["candidate_status"], "READY_FOR_INDEPENDENT_REVIEW")
        self.assertNotIn("entry_count", source["application_inventory"])

    def test_existing_count_is_rejected(self) -> None:
        source = self.source_manifest()
        source["application_inventory"]["entry_count"] = 999
        with self.assertRaisesRegex(ValueError, "SOURCE_ENTRY_COUNT_ALREADY_PRESENT_STOP"):
            prepare_candidate._candidate_manifest(
                source, Path("/candidate/app"), Path("/candidate")
            )


if __name__ == "__main__":
    unittest.main()
