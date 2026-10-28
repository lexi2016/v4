#!/usr/bin/env python3
"""Fixed-path, GET-only reader for the local V4 API."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


BASE_URL = "http://127.0.0.1:8873"
TIMEOUT_SECONDS = 15
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
FROZEN_STAGE_IDS = frozenset(
    {
        "STAGE_0925",
        "STAGE_0930_0935",
        "STAGE_0935_0940",
        "STAGE_0940_0945",
        "STAGE_0945_1030",
        "STAGE_1300_1315",
        "STAGE_1445_1500",
        "STAGE_1545_1555",
    }
)
OPENING_SAFETY_EXPECTATIONS = {
    "RESEARCH_ONLY": True,
    "write_performed": False,
    "production_allowed": False,
    "buy_gate_updated": False,
    "orders_sent": False,
}


class ReadFailure(Exception):
    def __init__(self, message: str, record: dict[str, Any]):
        super().__init__(message)
        self.record = record


def validate_date(value: str, name: str = "date") -> str:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise argparse.ArgumentTypeError(f"{name} must be YYYY-MM-DD")
    try:
        parsed = dt.date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"{name} must be a real calendar date") from exc
    if parsed.isoformat() != value:
        raise argparse.ArgumentTypeError(f"{name} must be YYYY-MM-DD")
    return value


def validate_symbol(value: str) -> str:
    if not re.fullmatch(r"(?:\d{6}\.(?:SH|SZ|BJ)|\d{5}\.HK)", value):
        raise argparse.ArgumentTypeError(
            "symbol must include a complete suffix: six digits with .SH/.SZ/.BJ or five digits with .HK"
        )
    return value


def validate_stage(value: str) -> str:
    if value not in FROZEN_STAGE_IDS:
        raise argparse.ArgumentTypeError(f"unknown stage; choose one of: {', '.join(sorted(FROZEN_STAGE_IDS))}")
    return value


def positive_limit(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("limit must be an integer") from exc
    if not 1 <= parsed <= 300:
        raise argparse.ArgumentTypeError("limit must be between 1 and 300")
    return parsed


def stage_limit(value: str) -> int:
    parsed = positive_limit(value)
    if parsed > 200:
        raise argparse.ArgumentTypeError("stage limit must be between 1 and 200")
    return parsed


def nonnegative_offset(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("offset must be an integer") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError("offset must be zero or greater")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read existing V4 data from the fixed local API.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_raw_option(subparser: argparse.ArgumentParser) -> None:
        subparser.add_argument("--raw", action="store_true", help="write the original HTTP response bytes to stdout")

    health = subparsers.add_parser("health", help="GET /healthz")
    add_raw_option(health)

    identity = subparsers.add_parser("identity", help="GET the V4 frontend build identity")
    add_raw_option(identity)

    opening = subparsers.add_parser("opening", help="GET one symbol's opening observation")
    opening.add_argument("--date", required=True, type=validate_date)
    opening.add_argument("--symbol", required=True, type=validate_symbol)
    opening.add_argument("--candidate-source-date", type=lambda value: validate_date(value, "candidate-source-date"))
    add_raw_option(opening)

    stage = subparsers.add_parser("stage", help="GET one frozen stage")
    stage.add_argument("--date", required=True, type=validate_date)
    stage.add_argument("--stage", required=True, type=validate_stage)
    stage.add_argument("--limit", type=stage_limit, default=50)
    add_raw_option(stage)

    pools = subparsers.add_parser("pools", help="GET one requested preselection-pool page")
    pools.add_argument("--date", required=True, type=validate_date)
    pools.add_argument("--limit", type=positive_limit, default=200)
    pools.add_argument("--offset", type=nonnegative_offset, default=0)
    add_raw_option(pools)
    return parser


def build_request(args: argparse.Namespace) -> tuple[str, dict[str, Any], str]:
    command = args.command
    params: dict[str, Any] = {}
    if command == "health":
        path = "/healthz"
        coverage = "HEALTH_ENDPOINT"
    elif command == "identity":
        path = "/api/v4/runtime-graph/frontend-build"
        coverage = "BUILD_IDENTITY_ENDPOINT"
    elif command == "opening":
        path = "/api/v4/research/opening-observation"
        params = {"date": args.date, "symbol": args.symbol}
        if args.candidate_source_date is not None:
            candidate_date = dt.date.fromisoformat(args.candidate_source_date)
            if candidate_date >= dt.date.fromisoformat(args.date):
                raise argparse.ArgumentTypeError("candidate-source-date must precede date")
            params["candidate_source_date"] = args.candidate_source_date
        coverage = "ONE_SYMBOL_OPENING_OBSERVATION"
    elif command == "stage":
        path = "/api/v4/stage-center/selection"
        params = {"date": args.date.replace("-", ""), "stage": args.stage, "limit": args.limit}
        coverage = "ONE_REQUESTED_STAGE_AND_LIMIT"
    elif command == "pools":
        path = "/api/v4/preselection-pools"
        params = {"date": args.date.replace("-", ""), "limit": args.limit, "offset": args.offset}
        coverage = "ONE_REQUESTED_PAGE"
    else:  # pragma: no cover - argparse constrains the command set
        raise ValueError(f"unsupported command: {command}")

    query = urllib.parse.urlencode(params)
    url = BASE_URL + path + ("?" + query if query else "")
    return url, params, coverage


def _read_timestamp() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def _base_record(url: str, params: dict[str, Any], coverage: str) -> dict[str, Any]:
    return {
        "url": url,
        "method": "GET",
        "request": params,
        "coverage_scope": coverage,
        "read_at": _read_timestamp(),
        "http_status": None,
        "transport_status": "READ_ERROR",
        "RESEARCH_ONLY": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def _read_body(response: Any) -> tuple[bytes, bool]:
    body = response.read(MAX_RESPONSE_BYTES + 1)
    return body, len(body) > MAX_RESPONSE_BYTES


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        return None


def fetch(url: str, params: dict[str, Any], coverage: str) -> tuple[dict[str, Any], bytes]:
    record = _base_record(url, params, coverage)
    request = urllib.request.Request(url, method="GET", headers={"Accept": "application/json"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirectHandler())
    response_body = b""
    try:
        with opener.open(request, timeout=TIMEOUT_SECONDS) as response:
            record["http_status"] = response.getcode()
            response_body, oversized = _read_body(response)
    except urllib.error.HTTPError as exc:
        record["http_status"] = exc.code
        try:
            response_body, oversized = _read_body(exc)
        except OSError as body_exc:
            oversized = False
            response_body = None
            record["body_read_error"] = str(body_exc)
        finally:
            exc.close()
        record["read_at"] = _read_timestamp()
        if oversized:
            record["response_bytes_observed"] = len(response_body)
            record["observed_prefix_sha256"] = hashlib.sha256(response_body).hexdigest()
            raise ReadFailure("response exceeded the configured size limit", record)
        if response_body is not None:
            record["response_bytes"] = len(response_body)
            record["response_sha256"] = hashlib.sha256(response_body).hexdigest()
        raise ReadFailure(f"HTTP status {exc.code}", record) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        record["read_at"] = _read_timestamp()
        raise ReadFailure(f"request failed: {exc}", record) from exc

    record["read_at"] = _read_timestamp()
    if oversized:
        record["response_bytes_observed"] = len(response_body)
        record["observed_prefix_sha256"] = hashlib.sha256(response_body).hexdigest()
        raise ReadFailure("response exceeded the configured size limit", record)
    record["response_bytes"] = len(response_body)
    record["response_sha256"] = hashlib.sha256(response_body).hexdigest()
    if record["http_status"] != 200:
        raise ReadFailure(f"HTTP status {record['http_status']}", record)
    record["transport_status"] = "READ_OK"
    return record, response_body


def _opening_contract(record: dict[str, Any], payload: Any) -> None:
    missing_or_abnormal = []
    if not isinstance(payload, dict):
        missing_or_abnormal.extend(OPENING_SAFETY_EXPECTATIONS)
    else:
        for key, expected in OPENING_SAFETY_EXPECTATIONS.items():
            if key not in payload or payload[key] is not expected:
                missing_or_abnormal.append(key)
    record["contract_status"] = "CONTRACT_CONFIRMED" if not missing_or_abnormal else "CONTRACT_UNCONFIRMED"
    record["contract_missing_or_abnormal_fields"] = missing_or_abnormal


def make_envelope(record: dict[str, Any], payload: Any, command: str) -> dict[str, Any]:
    if command == "opening":
        _opening_contract(record, payload)
    return {"reader": record, "payload": payload}


def _error_output(error: ReadFailure) -> str:
    record = dict(error.record)
    return json.dumps(
        {"error": str(error), "reader": record},
        ensure_ascii=False,
        separators=(",", ":"),
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        url, params, coverage = build_request(args)
    except argparse.ArgumentTypeError as exc:
        parser.error(str(exc))

    try:
        record, raw = fetch(url, params, coverage)
    except ReadFailure as exc:
        print(_error_output(exc), file=sys.stderr)
        return 2

    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        record["payload_status"] = "INVALID_JSON"
        failure = ReadFailure(f"HTTP body is not valid JSON: {exc}", record)
        if args.raw:
            sys.stdout.buffer.write(raw)
        print(_error_output(failure), file=sys.stderr)
        return 2

    envelope = make_envelope(record, payload, args.command)
    if args.raw:
        sys.stdout.buffer.write(raw)
        print(json.dumps({"reader": record}, ensure_ascii=False, separators=(",", ":")), file=sys.stderr)
    else:
        sys.stdout.write(json.dumps(envelope, ensure_ascii=False, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
