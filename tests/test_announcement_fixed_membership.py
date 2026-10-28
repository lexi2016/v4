from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from v4.manager_workbench import announcement_membership as membership


CONFIG_ENV = "V4_ANNOUNCEMENT_MEMBERSHIP_TEST_CONFIG"


def _live_config() -> SimpleNamespace:
    config_path = os.environ.get(CONFIG_ENV)
    if not config_path:
        raise unittest.SkipTest(f"set {CONFIG_ENV} to run read-only authority checks")
    values = json.loads(Path(config_path).read_text(encoding="utf-8"))
    return SimpleNamespace(shared_root=Path(values["shared_root"]))


class FixedMembershipTests(unittest.TestCase):
    def test_policy_pins_six_references_without_copying_member_codes(self) -> None:
        policy = membership._fixed_policy()
        authority = policy["authority"]
        self.assertEqual(policy["decision"], "FIXED_UNTIL_EXPLICIT_USER_UPDATE")
        self.assertEqual(policy["replacement"], "EXPLICIT_USER_REQUEST_ONLY")
        self.assertEqual(
            set(authority["references"]),
            {"artifact", "capture", "current", "manifest", "publication", "receipt"},
        )
        serialized = json.dumps(policy, ensure_ascii=False)
        self.assertNotIn("HK.", serialized)
        self.assertEqual(authority["member_count"], 698)

    def test_missing_fixed_source_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as empty_root:
            gate = membership.resolve_membership_gate(
                SimpleNamespace(shared_root=empty_root),
                "20261020",
                "2026-10-20T23:59:59+08:00",
            )
        self.assertEqual(gate["status"], "CANNOT_CONFIRM")
        self.assertEqual(gate["basis"], "USER_FIXED_UNIVERSE")
        self.assertEqual(gate["codes"], [])

    def test_fixed_authority_resolves_target20_and_later_month(self) -> None:
        config = _live_config()
        target20 = membership.resolve_membership_gate(
            config, "20261020", "2026-10-20T23:59:59+08:00"
        )
        later_month = membership.resolve_membership_gate(
            config, "20261120", "2026-11-20T23:59:59+08:00"
        )
        self.assertEqual(target20["status"], "VERIFIED", target20)
        self.assertEqual(later_month["status"], "VERIFIED", later_month)
        self.assertEqual(target20["basis"], "USER_FIXED_UNIVERSE")
        self.assertEqual(target20["membership_policy"], "FIXED_UNTIL_EXPLICIT_USER_UPDATE")
        self.assertEqual(target20["source_date"], "20261012")
        self.assertEqual(later_month["source_date"], "20261012")
        self.assertEqual(target20["authority_sha256"], later_month["authority_sha256"])
        self.assertEqual(target20["members_sha256"], "ce3c7eb8757c6c4d9dc8540653fb9d355479b5940547a9850147a847963c0446")
        self.assertEqual(target20["member_count"], 698)
        for gate in (target20, later_month):
            self.assertIsNone(gate["effective_from"])
            self.assertIsNone(gate["effective_to"])
            self.assertEqual(len(gate["authority_pin"]["checked_files"]), 6)
            public = membership.public_gate(gate)
            self.assertEqual(public["basis"], "USER_FIXED_UNIVERSE")
            self.assertEqual(public["member_count"], 698)
            self.assertEqual(public["members_sha256"], target20["members_sha256"])
            self.assertIsNone(public["effective_from"])
            self.assertIsNone(public["effective_to"])
        self.assertEqual(
            membership.revalidate_membership_gate(
                config, target20, "20261020", "2026-10-20T23:59:59+08:00"
            )["status"],
            "VERIFIED",
        )
        self.assertEqual(
            membership.revalidate_membership_gate(
                config, later_month, "20261120", "2026-11-20T23:59:59+08:00"
            )["status"],
            "VERIFIED",
        )

    def test_fixed_authority_still_requires_availability_before_cutoff(self) -> None:
        gate = membership.resolve_membership_gate(
            _live_config(), "20261020", "2026-10-12T19:58:59.501064+08:00"
        )
        self.assertEqual(gate["status"], "CANNOT_CONFIRM")
        self.assertEqual(gate["failure_code"], "FIXED_CONNECT_MEMBERSHIP_AFTER_CUTOFF_OR_UNKNOWN")

    def test_corrupt_pinned_sha_fails_closed(self) -> None:
        config = _live_config()
        policy = copy.deepcopy(membership._fixed_policy())
        sha = policy["authority"]["references"]["artifact"]["sha256"]
        policy["authority"]["references"]["artifact"]["sha256"] = ("0" if sha[0] != "0" else "1") + sha[1:]
        with patch.object(membership, "_fixed_policy", return_value=policy):
            gate = membership.resolve_membership_gate(
                config, "20261120", "2026-11-20T23:59:59+08:00"
            )
        self.assertEqual(gate["status"], "CANNOT_CONFIRM")
        self.assertEqual(gate["failure_code"], "FIXED_CONNECT_MEMBERSHIP_SHA_MISMATCH")

    def test_outside_invalid_and_ambiguous_issuers_never_enter_allowed_payloads(self) -> None:
        gate = membership.resolve_membership_gate(
            _live_config(), "20261120", "2026-11-20T23:59:59+08:00"
        )
        self.assertEqual(gate["status"], "VERIFIED", gate)
        outside_code = next(f"HK.{number:05d}" for number in range(1, 10000)
                            if f"HK.{number:05d}" not in gate["codes"])
        payloads = [
            {"article_id": "IN", "article_metadata": {"symbol": gate["codes"][0]}},
            {"article_id": "OUT", "article_metadata": {"symbol": outside_code}},
            {"article_id": "INVALID", "article_metadata": {"symbol": "HK.123456"}},
            {"article_id": "AMBIGUOUS", "article_metadata": {
                "source_issuer_codes": [{"code": gate["codes"][0]}, {"code": gate["codes"][1]}]}},
        ]
        allowed, excluded = membership.filter_payloads(payloads, gate)
        self.assertEqual([item["article_id"] for item in allowed], ["IN"])
        self.assertEqual([item["membership_status"] for item in excluded], ["OUT", "UNKNOWN", "UNKNOWN"])
        self.assertEqual(excluded[0]["membership_reason"], "OUTSIDE_FIXED_HK_CONNECT_UNIVERSE")

    def test_legacy_gate_keeps_its_existing_reason_text(self) -> None:
        legacy_gate = {"status": "VERIFIED", "codes": ["HK.00001"], "authority_sha256": "a" * 64}
        self.assertEqual(
            membership.classify_codes(["HK.00001"], legacy_gate),
            ("IN", "HK_CONNECT_MEMBER_AT_TARGET_DATE"),
        )
        self.assertEqual(
            membership.classify_codes(["HK.00002"], legacy_gate),
            ("OUT", "NOT_IN_HK_CONNECT_UNIVERSE_AT_TARGET_DATE"),
        )

    def test_revalidation_failure_keeps_fixed_basis_and_null_interval(self) -> None:
        gate = membership.revalidate_membership_gate(
            SimpleNamespace(shared_root="/unused"), None, "20261020", "2026-10-20T23:59:59+08:00"
        )
        public = membership.public_gate(gate)
        self.assertEqual(public["status"], "CANNOT_CONFIRM")
        self.assertEqual(public["basis"], "USER_FIXED_UNIVERSE")
        self.assertIsNone(public["effective_from"])
        self.assertIsNone(public["effective_to"])


if __name__ == "__main__":
    unittest.main()
