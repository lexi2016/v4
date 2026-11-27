"""Fault regressions and byte-level checks for the two real isolated runs."""

import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from local_state import Board, UploadLedger, artifact, digest, read_pin, writer_lock
import route2
from route2 import INPUTS, OUT, evening


BANNER = re.compile(rb'<aside id="route2-state"[^>]*>.*?</aside>')


def current(name):
    root = OUT / name
    return root, Board(root, writable=False).current()


class RealRuns(unittest.TestCase):
    def test_verified_d26_and_missing_d27_preserve_dates_and_bytes(self):
        replay, succeeded = current("replay")
        self.assertFalse(succeeded["stale"])
        self.assertEqual(succeeded["data_date"], "2026-11-26")
        self.assertEqual(succeeded["last_success"]["origin"], "FROZEN_W11C_RENDERED_D26_CLOSE_REPLAY")
        refs = succeeded["last_success"]["proof"]
        frozen = json.loads(read_pin(replay, refs["original_runtime"]))
        self.assertEqual((frozen["manifest_files"], len(frozen["vendor"])), (113, 32))
        proof = json.loads(read_pin(replay, refs["evening_inputs"]))
        self.assertEqual(proof["archived_close_assembly"]["par"]["counts"], {"COMPUTED": 5502, "ISOLATED": 73})
        self.assertEqual(proof["archived_close_assembly"]["prior_shards"]["count"], 8)
        self.assertEqual(proof["original_evening_inputs"]["business_date"], "20261126")
        self.assertEqual(set(proof["pinned_phase_observations"]), {"premarket", "intraday"})
        self.assertEqual(
            {phase: observation["status"] for phase, observation in proof["pinned_phase_observations"].items()},
            {"premarket": "UNKNOWN", "intraday": "UNKNOWN"},
        )
        self.assertEqual(
            {"COMPUTED", "MISSING_UPSTREAM"},
            {obj["status"] for obj in proof["original_evening_inputs"]["inputs"].values()},
        )
        original = (INPUTS / "V5_ORIGINAL_BOARD.html").read_bytes()
        observed, failed = current("observed")
        self.assertEqual((failed["data_date"], failed["attempted_date"], failed["stale"]),
                         ("2026-11-26", "2026-11-27", True))
        self.assertIn("D27_SAME_DATE_DAILY_PAR_109", failed["reason"])
        self.assertEqual(read_pin(observed, failed["last_success"]["raw"]), original)
        seen = read_pin(observed, failed["view"])
        self.assertIn("旧数据 · STALE　数据日期 2026-11-26　尝试日期 2026-11-27".encode(), seen)
        self.assertEqual(BANNER.sub(b"", seen, count=1), original)
        close = json.loads((observed / "CLOSE.json").read_bytes())
        top = json.loads(read_pin(observed, close["objects"]["TOP200.json"]))
        self.assertEqual((top["business_date"], close["top200"]["count"], close["status"]),
                         ("20261127", 200, "MISSING_UPSTREAM"))
        self.assertEqual(top["source_sha256"], close["g4"]["sha256"])

    def test_real_renderer_fallback_after_success_and_atomic_pointer_fault(self):
        replay, actual = current("replay")
        rendered = read_pin(replay, actual["last_success"]["raw"])
        original = (INPUTS / "V5_ORIGINAL_BOARD.html").read_bytes()
        with tempfile.TemporaryDirectory(dir=OUT) as scratch:
            root = Path(scratch)
            board = Board(root)
            pin = {"bytes": len(original), "sha256": digest(original)}
            seeded = board.seed("2026-11-26", pin, "original", lambda: original)
            candidate = artifact(root, "BOARD.html", rendered)
            evidence = artifact(root, "INPUT.json", b"{}")
            original_replace = os.replace

            def broken_pointer(src, dst):
                if dst == board.pointer:
                    raise OSError("simulated pointer replacement failure")
                return original_replace(src, dst)

            with patch("local_state.os.replace", side_effect=broken_pointer), self.assertRaises(OSError):
                board.publish("2026-11-26", candidate, "frozen_renderer", {"inputs": evidence})
            self.assertEqual(board.current()["last_success"], seeded)
            self.assertEqual(read_pin(root, seeded["raw"]), original)
            committed = board.publish("2026-11-26", candidate, "frozen_renderer", {"inputs": evidence})
            reason = "MISSING_UPSTREAM <img src=a onerror='test'>"
            stale = board.fail("2026-11-27", reason)
            self.assertEqual(stale["last_success"], committed["last_success"])
            self.assertEqual(read_pin(root, stale["last_success"]["raw"]), rendered)
            self.assertEqual(read_pin(root, seeded["raw"]), original)
            seen = read_pin(root, stale["view"])
            self.assertIn(b"&lt;img src=a onerror=&#x27;test&#x27;&gt;", seen)
            self.assertNotIn(b"<img src=a onerror=", seen)
            self.assertEqual(BANNER.sub(b"", seen, count=1), rendered)


    def test_missing_bootstrap_reuses_preserved_original_after_generated_replay(self):
        replay, previous = current("replay")
        original = (INPUTS / "V5_ORIGINAL_BOARD.html").read_bytes()
        with tempfile.TemporaryDirectory(dir=OUT) as scratch:
            root = Path(scratch)
            fresh_inputs = root / "inputs"
            fresh_out = root / "out"
            fresh_replay = fresh_out / "replay"
            fresh_inputs.mkdir()
            fresh_replay.mkdir(parents=True)
            for name in ("V5_FINAL.zip", "V5_SYSTEM_MAP.json", "V5_D26.zip", "G4_20261126.zip",
                         "D26_premarket_RESULT.json", "D26_intraday_RESULT.json", "V5_ORIGINAL_BOARD.html"):
                shutil.copyfile(INPUTS / name, fresh_inputs / name)
            bootstrap = fresh_inputs / "V5_ORIGINAL_BOARD.html"
            board = Board(fresh_replay)
            pin = {"bytes": len(original), "sha256": digest(original)}
            seeded = board.seed("2026-11-26", pin, "1LsWT2s0j0sg8Jc_-graK9-WIQSbKrFgs", bootstrap.read_bytes)
            got = previous["last_success"]
            rendered = read_pin(replay, got["raw"])
            ref = artifact(fresh_replay, "BOARD.html", rendered)
            support = {k: artifact(fresh_replay, k + ".json", read_pin(replay, v))
                       for k, v in got["proof"].items()}
            board.publish("2026-11-26", ref, got["origin"], support)
            bootstrap.unlink()
            with patch.multiple(route2, OUT=fresh_out, INPUTS=fresh_inputs):
                result = route2.run(SimpleNamespace(action="run", date="20261126"))
            self.assertEqual(result["status"], "ORIGINAL_V5_CLOSE_EVENING_REPLAY_VERIFIED")
            self.assertFalse(bootstrap.exists())
            receipt = json.loads(Path(result["receipt"]).read_bytes())
            self.assertEqual(receipt["original"], seeded)
            self.assertFalse(receipt["current"]["stale"])
            self.assertEqual(read_pin(fresh_replay, seeded["raw"]), original)
            self.assertEqual(read_pin(fresh_replay, receipt["current"]["last_success"]["raw"]), rendered)
            (fresh_replay / seeded["raw"]["path"]).unlink()
            with patch.multiple(route2, OUT=fresh_out, INPUTS=fresh_inputs):
                blocked = route2.run(SimpleNamespace(action="run", date="20261126"))
            self.assertEqual((blocked["status"], blocked["stale"]), ("BLOCKED", True))
            failure = json.loads(Path(blocked["receipt"]).read_bytes())
            self.assertIn("PRESERVED_ORIGINAL_MISSING", failure["current"]["reason"])
            self.assertEqual(read_pin(fresh_replay, failure["current"]["last_success"]["raw"]), rendered)


class DurableState(unittest.TestCase):
    def setUp(self):
        work = tempfile.TemporaryDirectory(dir=OUT)
        self.addCleanup(work.cleanup)
        self.root = Path(work.name)

    def child(self, body):
        return subprocess.run([sys.executable, "-B", "-c", body, str(self.root)],
                              cwd=Path(__file__).resolve().parent, check=False, capture_output=True,
                              text=True, timeout=10)

    def test_exclusive_writer_lock_uses_independent_process(self):
        body = """from pathlib import Path
import sys
from local_state import writer_lock
try:
    with writer_lock(Path(sys.argv[1])):
        print("ACQUIRED")
except ValueError as exc:
    print(exc)
    sys.exit(21)
"""
        with writer_lock(self.root):
            blocked = self.child(body)
        self.assertEqual((blocked.returncode, blocked.stdout.strip()), (21, "ALREADY_CLAIMED_LOCAL"))
        recovered = self.child(body)
        self.assertEqual((recovered.returncode, recovered.stdout.strip()), (0, "ACQUIRED"))

    def test_process_crash_after_request_keeps_unknown_and_blocks_all_payloads(self):
        body = """from pathlib import Path
import os, sqlite3, sys
from local_state import UploadLedger
root = Path(sys.argv[1])
def lose_ack(target, day, sha, payload):
    with sqlite3.connect(root / "upload-ledger.sqlite3") as db:
        assert db.execute("SELECT target, day, sha256, state FROM attempts").fetchone() == (
            target, day, sha, "UNKNOWN_UPLOAD")
    with (root / "fake-request.log").open("ab") as sent:
        sent.write(payload + b"\\n")
        sent.flush()
        os.fsync(sent.fileno())
    os._exit(77)
UploadLedger(root).attempt("fake-board", "20261127", b"one", lose_ack)
"""
        attempt = self.child(body)
        self.assertEqual(attempt.returncode, 77, attempt.stderr)
        candidate = self.root / "fake-request.log"

        def detect_retry(target, day, sha, payload):
            with candidate.open("ab") as sent:
                sent.write(payload + b"\n")
            return {"target": target, "date": day, "sha256": sha, "id": "new-request"}

        for payload in (b"one", b"different"):
            self.assertEqual(UploadLedger(self.root).attempt("fake-board", "20261127", payload, detect_retry),
                             "UNKNOWN_UPLOAD")
        self.assertEqual(candidate.read_bytes(), b"one\n")
        with sqlite3.connect(self.root / "upload-ledger.sqlite3") as db:
            self.assertEqual(db.execute("SELECT state, sha256, readback FROM attempts").fetchall(),
                             [("UNKNOWN_UPLOAD", digest(b"one"), None)])

    def test_evening_cannot_consume_interrupted_close_marker(self):
        board = Board(self.root)
        (self.root / "CLOSE.json").write_text(
            json.dumps({"business_date": "20261126", "status": "CLOSE_IN_PROGRESS"}))
        with self.assertRaisesRegex(ValueError, "MISSING_CLOSE_HANDOFF"):
            evening("20261126", {"mode": "sealed_replay"}, self.root, self.root, None, {}, board, {})

    def test_ack_is_exact_and_deduplicated(self):
        calls = []

        def exact(target, day, sha, payload):
            calls.append(payload)
            return {"target": target, "date": day, "sha256": sha, "id": "fake-exact-readback"}

        def wrong(target, day, sha, payload):
            return dict(exact(target, day, sha, payload), date="20261126")

        ledger = UploadLedger(self.root)
        self.assertEqual(ledger.attempt("fake-board", "20261127", b"one", exact), "ACKNOWLEDGED")
        self.assertEqual(ledger.attempt("fake-board", "20261127", b"one", exact), "ALREADY_ACKNOWLEDGED")
        self.assertEqual(ledger.attempt("fake-board", "20261127", b"two", exact),
                         "DIFFERENT_PAYLOAD_ALREADY_ACKNOWLEDGED")
        self.assertEqual(ledger.attempt("other-fake-board", "20261127", b"three", wrong), "UNKNOWN_UPLOAD")
        self.assertEqual(calls, [b"one", b"three"])


if __name__ == "__main__":
    unittest.main()
