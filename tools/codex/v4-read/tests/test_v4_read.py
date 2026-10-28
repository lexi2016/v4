from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock
import urllib.parse


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import v4_read


class ResponseState:
    status = 200
    body = b"{}"
    requests: list[tuple[str, str]] = []
    sink_hits = 0


class LocalHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        ResponseState.requests.append((self.command, self.path))
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/sink")
            self.end_headers()
            return
        if self.path == "/sink":
            ResponseState.sink_hits += 1
        self.send_response(ResponseState.status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(ResponseState.body)))
        self.end_headers()
        self.wfile.write(ResponseState.body)

    def log_message(self, _format: str, *_args: object) -> None:
        return


class CapturedStdout:
    def __init__(self) -> None:
        self.buffer = io.BytesIO()
        self.text = io.StringIO()

    def write(self, value: str) -> int:
        self.text.write(value)
        return len(value)


class V4ReadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), LocalHandler)
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.server_thread.join(timeout=2)

    def setUp(self) -> None:
        ResponseState.status = 200
        ResponseState.body = b"{}"
        ResponseState.requests = []
        ResponseState.sink_hits = 0

    def test_date_symbol_and_candidate_source_validation(self) -> None:
        for bad in ("2026-02-29", "2026-13-01", "2026-1-01", "latest"):
            with self.subTest(bad=bad), self.assertRaises(v4_read.argparse.ArgumentTypeError):
                v4_read.validate_date(bad)
        for bad in ("301655", "301655.SHX", "0001.HK", "301655.XX"):
            with self.subTest(bad=bad), self.assertRaises(v4_read.argparse.ArgumentTypeError):
                v4_read.validate_symbol(bad)
        args = v4_read.build_parser().parse_args(
            ["opening", "--date", "2026-10-28", "--symbol", "301655.SZ", "--candidate-source-date", "2026-10-28"]
        )
        with self.assertRaises(v4_read.argparse.ArgumentTypeError):
            v4_read.build_request(args)

    def test_unknown_stage_and_unsupported_transport_options_rejected(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            v4_read.build_parser().parse_args(
                ["stage", "--date", "2026-10-28", "--stage", "NOT_A_STAGE"]
            )
        for option in ("--url", "--path", "--method", "--force", "--retry", "--fallback"):
            with self.subTest(option=option), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                v4_read.build_parser().parse_args(["health", option, "value"])

    def test_stage_and_pool_limits_follow_endpoint_bounds(self) -> None:
        with self.assertRaises(v4_read.argparse.ArgumentTypeError):
            v4_read.stage_limit("201")
        with self.assertRaises(v4_read.argparse.ArgumentTypeError):
            v4_read.positive_limit("301")
        self.assertEqual(v4_read.stage_limit("200"), 200)
        self.assertEqual(v4_read.positive_limit("300"), 300)

    def test_endpoint_date_wire_formats_match_frozen_api_contract(self) -> None:
        commands = (
            (
                ["stage", "--date", "2026-10-28", "--stage", "STAGE_0930_0935", "--limit", "50"],
                "/api/v4/stage-center/selection",
                "20261028",
            ),
            (
                ["pools", "--date", "2026-10-28", "--limit", "200", "--offset", "0"],
                "/api/v4/preselection-pools",
                "20261028",
            ),
            (
                ["opening", "--date", "2026-10-28", "--symbol", "601566.SH"],
                "/api/v4/research/opening-observation",
                "2026-10-28",
            ),
        )
        for argv, expected_path, expected_wire_date in commands:
            with self.subTest(command=argv[0]):
                args = v4_read.build_parser().parse_args(argv)
                url, params, _coverage = v4_read.build_request(args)
                parsed = urllib.parse.urlsplit(url)
                query = urllib.parse.parse_qs(parsed.query)
                self.assertEqual(parsed.path, expected_path)
                self.assertEqual(query["date"], [expected_wire_date])
                self.assertEqual(params["date"], expected_wire_date)
                self.assertEqual(expected_wire_date.replace("-", ""), args.date.replace("-", ""))

    def test_fixed_health_get_ignores_proxy_environment(self) -> None:
        ResponseState.body = b'{"status":"ok"}'
        args = v4_read.build_parser().parse_args(["health"])
        with mock.patch.object(v4_read, "BASE_URL", self.base_url), mock.patch.dict(
            os.environ,
            {
                "HTTP_PROXY": "http://127.0.0.1:1",
                "HTTPS_PROXY": "http://127.0.0.1:1",
                "http_proxy": "http://127.0.0.1:1",
                "https_proxy": "http://127.0.0.1:1",
            },
        ):
            url, params, coverage = v4_read.build_request(args)
            record, body = v4_read.fetch(url, params, coverage)
        self.assertEqual(ResponseState.requests, [("GET", "/healthz")])
        self.assertEqual(body, b'{"status":"ok"}')
        self.assertEqual(record["transport_status"], "READ_OK")
        self.assertEqual(record["url"], self.base_url + "/healthz")

    def test_redirect_is_not_followed(self) -> None:
        with self.assertRaises(v4_read.ReadFailure) as caught:
            v4_read.fetch(self.base_url + "/redirect", {}, "TEST")
        self.assertEqual(caught.exception.record["http_status"], 302)
        self.assertEqual(caught.exception.record["transport_status"], "READ_ERROR")
        self.assertEqual(ResponseState.sink_hits, 0)
        self.assertEqual(ResponseState.requests, [("GET", "/redirect")])

    def test_http_error_fails_without_fake_payload(self) -> None:
        ResponseState.status = 503
        ResponseState.body = b'{"detail":"unavailable"}'
        stdout = CapturedStdout()
        stderr = io.StringIO()
        with mock.patch.object(v4_read, "BASE_URL", self.base_url), mock.patch.object(sys, "stdout", stdout), mock.patch.object(
            sys, "stderr", stderr
        ):
            code = v4_read.main(["health"])
        self.assertEqual(code, 2)
        self.assertEqual(stdout.buffer.getvalue(), b"")
        error = json.loads(stderr.getvalue())
        self.assertEqual(error["reader"]["transport_status"], "READ_ERROR")
        self.assertEqual(error["reader"]["http_status"], 503)
        self.assertNotIn("payload", error)
        self.assertIn("HTTP status 503", error["error"])

    def test_oversized_response_is_an_explicit_error(self) -> None:
        ResponseState.body = b"0123456789"
        with mock.patch.object(v4_read, "MAX_RESPONSE_BYTES", 5):
            with self.assertRaises(v4_read.ReadFailure) as caught:
                v4_read.fetch(self.base_url + "/large", {}, "TEST")
        record = caught.exception.record
        self.assertEqual(record["transport_status"], "READ_ERROR")
        self.assertEqual(record["response_bytes_observed"], 6)
        self.assertIn("observed_prefix_sha256", record)
        self.assertNotIn("response_sha256", record)

    def test_success_preserves_partial_missing_unsafe_null_zero_false_and_provenance(self) -> None:
        payload = {
            "status": "PARTIAL",
            "RESEARCH_ONLY": True,
            "write_performed": False,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
            "stages": [
                {
                    "stage_id": "STAGE_0930_0935",
                    "availability": "MISSING",
                    "temporal_state": "UNSAFE",
                    "selection": None,
                    "rows": [{"turnover": 0, "prev_close_price": None, "selected": False}],
                    "missing_reasons": ["CANNOT_CONFIRM"],
                    "raw": {"run_id": "run-1", "artifact_sha256": "abc", "rows": [{"source": "kept"}]},
                }
            ],
        }
        raw = json.dumps(payload, separators=(",", ":")).encode()
        ResponseState.body = raw
        args = v4_read.build_parser().parse_args(
            ["opening", "--date", "2026-10-28", "--symbol", "301655.SZ"]
        )
        with mock.patch.object(v4_read, "BASE_URL", self.base_url):
            url, params, coverage = v4_read.build_request(args)
            record, response = v4_read.fetch(url, params, coverage)
        envelope = v4_read.make_envelope(record, json.loads(response), "opening")
        self.assertEqual(envelope["reader"]["transport_status"], "READ_OK")
        self.assertEqual(envelope["reader"]["contract_status"], "CONTRACT_CONFIRMED")
        self.assertEqual(envelope["payload"], payload)
        self.assertEqual(envelope["payload"]["stages"][0]["rows"][0], {"turnover": 0, "prev_close_price": None, "selected": False})

    def test_missing_opening_safety_flags_are_unconfirmed_without_dropping_payload(self) -> None:
        payload = {"status": "PARTIAL", "stage": {"availability": "MISSING", "temporal_state": "UNSAFE"}}
        ResponseState.body = json.dumps(payload, separators=(",", ":")).encode()
        stdout = CapturedStdout()
        with mock.patch.object(v4_read, "BASE_URL", self.base_url), mock.patch.object(sys, "stdout", stdout):
            code = v4_read.main(["opening", "--date", "2026-10-28", "--symbol", "301655.SZ"])
        self.assertEqual(code, 0)
        envelope = json.loads(stdout.text.getvalue())
        self.assertEqual(envelope["reader"]["transport_status"], "READ_OK")
        self.assertEqual(envelope["reader"]["contract_status"], "CONTRACT_UNCONFIRMED")
        self.assertEqual(envelope["reader"]["contract_missing_or_abnormal_fields"], list(v4_read.OPENING_SAFETY_EXPECTATIONS))
        self.assertEqual(envelope["payload"], payload)

    def test_empty_body_is_nonzero_but_read_status_remains_transport_read_ok(self) -> None:
        ResponseState.body = b""
        stdout = CapturedStdout()
        stderr = io.StringIO()
        with mock.patch.object(v4_read, "BASE_URL", self.base_url), mock.patch.object(sys, "stdout", stdout), mock.patch.object(
            sys, "stderr", stderr
        ):
            code = v4_read.main(["health"])
        self.assertEqual(code, 2)
        self.assertEqual(stdout.text.getvalue(), "")
        error = json.loads(stderr.getvalue())
        self.assertEqual(error["reader"]["transport_status"], "READ_OK")
        self.assertEqual(error["reader"]["payload_status"], "INVALID_JSON")
        self.assertNotIn("payload", error)

    def test_raw_mode_writes_original_response_bytes_unchanged(self) -> None:
        ResponseState.body = b'{\n  "status" : "ok", "zero": 0 }\n'
        stdout = CapturedStdout()
        stderr = io.StringIO()
        with mock.patch.object(v4_read, "BASE_URL", self.base_url), mock.patch.object(sys, "stdout", stdout), mock.patch.object(
            sys, "stderr", stderr
        ):
            code = v4_read.main(["health", "--raw"])
        self.assertEqual(code, 0)
        self.assertEqual(stdout.buffer.getvalue(), ResponseState.body)
        self.assertIn('"transport_status":"READ_OK"', stderr.getvalue())

    def test_pools_reads_only_one_requested_page_and_does_not_claim_completeness(self) -> None:
        payload = {"status": "PARTIAL", "rows": [{"code": "000001.SZ"}], "page": 1, "total": 12}
        ResponseState.body = json.dumps(payload, separators=(",", ":")).encode()
        stdout = CapturedStdout()
        stderr = io.StringIO()
        with mock.patch.object(v4_read, "BASE_URL", self.base_url), mock.patch.object(sys, "stdout", stdout), mock.patch.object(
            sys, "stderr", stderr
        ):
            code = v4_read.main(["pools", "--date", "2026-10-28", "--limit", "1", "--offset", "0"])
        self.assertEqual(code, 0)
        self.assertEqual(len(ResponseState.requests), 1)
        self.assertEqual(ResponseState.requests[0][0], "GET")
        parsed_url = urllib.parse.urlsplit(self.base_url + ResponseState.requests[0][1])
        self.assertEqual(urllib.parse.parse_qs(parsed_url.query), {"date": ["20261028"], "limit": ["1"], "offset": ["0"]})
        envelope = json.loads(stdout.text.getvalue())
        self.assertEqual(envelope["reader"]["coverage_scope"], "ONE_REQUESTED_PAGE")
        self.assertEqual(envelope["reader"]["request"], {"date": "20261028", "limit": 1, "offset": 0})
        self.assertEqual(envelope["payload"], payload)
        self.assertNotIn("complete", envelope["reader"])


if __name__ == "__main__":
    unittest.main()
