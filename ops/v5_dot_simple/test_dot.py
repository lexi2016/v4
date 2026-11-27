"""Offline regression suite. The simulated connector never sends a request."""
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, mock
import gzip
import io
import json
import os
import shutil
import zipfile

from dot_connector import PARENT, ROLES, action, check_listing, exact_query, object_name, save_plan
from dot_run import build_prior, initialize, open_live_board, scheduled, validate_stock_member
from dot_runtime import BJT, CONFIG, admit_slot, capture_g4, capture_source, load_runtime, market_day
from dot_state import FLAGS, Board, artifact, digest, json_bytes, read_pin, writer_lock


INTAKE = Path(os.environ["DOT_TEST_INTAKE"]).resolve()
SCRATCH = Path(os.environ["DOT_TEST_SCRATCH"]).resolve()
DAY = "20261130"
NOW = datetime(2026, 11, 30, 9, 0, tzinfo=timezone.utc)


def temp():
    return TemporaryDirectory(prefix="dot-test-", dir=SCRATCH)


def at_bjt(value):
    return datetime.fromisoformat(value).replace(tzinfo=BJT)


def listing(name, rows=(), *, at=NOW):
    return {
        "schema": "V5_DOT_CONNECTOR_LIST_V1", "parent": PARENT, "name": name,
        "query": exact_query(name), "authenticated": True,
        "requested_at": (at - timedelta(seconds=4)).isoformat(), "completed_at": at.isoformat(),
        "pages": [{"request_page_token": None, "next_page_token": None,
                   "status": "OK", "incomplete_search": False, "files": list(rows)}],
    }


def meta(action_value, ident="remote-A"):
    return {"id": ident, "name": action_value["name"], "parent_ids": [PARENT],
            "file_size_bytes": action_value["payload"]["bytes"], "trashed": False}


def json_file(directory, name, value):
    (directory / name).write_bytes(json_bytes(value))


def zip_bytes(files):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        for name, raw in files.items():
            archive.writestr(name, raw)
    return stream.getvalue()


def stock_fixture(runtime, day, symbol, sample=None, *, wrong_state_date=None):
    tail = {"symbol": symbol, "event_date": day, "close": "1", "raw_row_index": 0}
    fields = {"symbol": symbol, "event_date": day, "fields": {f"f{i}": None for i in range(109)}}
    parts = {"STATE51": {"schema": "v5.cloud.exact.daily.state.v1", "symbol": symbol,
                         "last_date": wrong_state_date or int(day), "count": 1},
             "DAY109": sample or fields, "FACTS": {"component_state": {"count": 1}},
             "TAIL": tail, "DAY51": {"trade_date": int(day), "values": {f"v{i}": None for i in range(51)}}}
    return runtime.par.stock_zip(day, {name: json_bytes(value) for name, value in parts.items()}, [tail])


class RuntimeTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.session = temp()
        cls.root = Path(cls.session.name)
        cls.runtime = load_runtime(INTAKE, cls.root)

    @classmethod
    def tearDownClass(cls):
        cls.session.cleanup()

    def test_open_holiday_and_year_crossing_fail_closed(self):
        prior, basis = market_day(DAY, self.runtime, INTAKE)
        self.assertEqual(prior, "20261127")
        self.assertEqual(basis["2026"]["closure_dates"], 33)
        self.assertEqual(market_day("20261008", self.runtime, INTAKE)[0], "20260930")
        for day in ("20261128", "20261001"):
            with self.subTest(day=day), self.assertRaisesRegex(ValueError, "CLOSED_SESSION"):
                market_day(day, self.runtime, INTAKE)
        for day, year in (("20270104", 2027), ("20260105", 2025)):
            with self.subTest(day=day), self.assertRaisesRegex(ValueError, f"CALENDAR_UNAVAILABLE:{year}"):
                market_day(day, self.runtime, INTAKE)

    def test_clock_bjt_and_window_boundaries(self):
        self.assertEqual(admit_slot("close", at_bjt("2026-11-30T16:20"))[0], "16:20")
        utc = datetime(2026, 11, 30, 8, 50, tzinfo=timezone.utc)
        self.assertEqual(admit_slot("close", utc)[0], "16:50")
        self.assertEqual(admit_slot("evening", at_bjt("2026-11-30T18:30"))[0], "18:30")
        for value in ("16:45", "16:55", "17:00"):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "OUTSIDE_DOT_CLOSE"):
                admit_slot("close", at_bjt("2026-11-30T" + value))

    def test_1650_adapter_uses_truthful_timestamp_and_original_archive_gate(self):
        raw = read_pin(INTAKE, CONFIG["canary"]["20261127"])
        start, end = at_bjt("2026-11-27T16:50:12"), at_bjt("2026-11-27T16:50:15")
        _, deadline = admit_slot("close", start)
        url = self.runtime.sources.RAWSOURCE.format(date="20261127")
        class Response(io.BytesIO):
            status = 200
            headers = {}
            def geturl(self):
                return url
        with temp() as output:
            response = Response(raw)
            fake_open = mock.Mock(return_value=response)
            result = capture_g4(Path(output), "20261127", self.runtime, deadline,
                                clock=mock.Mock(side_effect=[start, end]), opener=fake_open)
            self.assertEqual(result["observed_at"], end.isoformat())
            self.assertEqual(result["sha256"], CONFIG["canary"]["20261127"]["sha256"])
            self.assertEqual(fake_open.call_args.args[0].full_url, url)
            with self.assertRaisesRegex(ValueError, "OBSERVED_SLOT"):
                capture_g4(Path(output), "20261127", self.runtime, deadline,
                           clock=mock.Mock(side_effect=[start, deadline]), opener=lambda *_a, **_k: Response(raw))

    def test_113_archive_and_exact_32_vendor_bytes(self):
        self.assertEqual(self.runtime.proof["manifest_files"], 113)
        self.assertEqual(self.runtime.proof["vendor_files"], 32)
        release_root = self.runtime.main.ROOT
        for path, expected in self.runtime.proof["vendor_sha256"].items():
            self.assertEqual(sha256((release_root / path).read_bytes()).hexdigest(), expected)

    def test_future_missing_source_and_evening_retain_byte_exact_seed(self):
        with temp() as output, mock.patch("dot_run.load_runtime", return_value=self.runtime), \
             mock.patch("dot_run.capture_g4", side_effect=ValueError("WAITING_INPUT_G4")):
            state = Path(output)
            initialize(INTAKE, state)
            close = scheduled("close", INTAKE, state, clock=lambda: at_bjt("2026-11-30T16:50"))
            self.assertEqual(close["reason"], "WAITING_INPUT_G4")
            self.assertEqual(close["current"]["data_date"], "20261126")
            result = scheduled("evening", INTAKE, state, clock=lambda: at_bjt("2026-11-30T18:30"))
            self.assertEqual(result["status"], "MISSING_UPSTREAM")
            self.assertEqual(result["current"]["attempted_date"], DAY)
            self.assertTrue(result["current"]["stale"])
            self.assertIn("MISSING_SAME_DAY_VERIFIED_PAR_109", result["reason"])
            value = Board(state, writable=False).current()
            raw = read_pin(state, value["last_success"]["raw"])
            shown = read_pin(state, value["view"])
            self.assertEqual(raw, read_pin(INTAKE, CONFIG["original_board"]))
            self.assertIn(b"20261130", shown)
            self.assertIn(b"20261126", shown)
            self.assertFalse((state / "plans").exists())



    def test_eligible_evening_runs_frozen_dispatch_and_promotes_same_date(self):
        historical = "20261126"
        archive = self.runtime.driveio.manifested(read_pin(INTAKE, CONFIG["accepted_close"]))
        rows = json.loads(gzip.decompress(archive["PAR_LEDGER.json.gz"]))
        parts = {index: {} for index in range(1, 9)}
        samples = json.loads(archive["SAMPLE_109.json"])
        # Structural staging fixture over genuine D26 top, PAR statuses and 109 samples.
        # The fixture connector and mock shard bodies are never live evidence.
        for index, row in enumerate(rows):
            if row["status"] == "COMPUTED":
                part = index % 8 + 1
                stock = stock_fixture(self.runtime, historical, row["symbol"], samples.get(row["symbol"]))
                row.update(part=part, fields=109, bytes=len(stock), sha256=digest(stock))
                parts[part][row["symbol"] + ".zip"] = stock
        g4 = read_pin(INTAKE, CONFIG["canary"][historical])
        observed = "2026-11-26T16:20:10+08:00"
        gbbq = zip_bytes({"gbbq": (1).to_bytes(4, "little") + b"x" * 29})
        rights_ref = {"url": self.runtime.sources.GBBQ, "http_status": 200, "observed_at": observed,
                      "bytes": len(gbbq), "sha256": digest(gbbq)}
        src_top = {"business_date": historical, "g4": CONFIG["canary"][historical]}
        simulated_counts = {0: 1, 1: 1, 2: 1}
        src_daily = src_top | {"gbbq": rights_ref, "right_counts": {str(k): v for k, v in simulated_counts.items()}}
        summary = {"business_date": historical, "scope": 5575, "counts": {"COMPUTED": 5502, "ISOLATED": 73},
                   "status": "COMPUTED_ISOLATED", "parent_date": "20261125"}
        with temp() as output:
            base = Path(output)
            intake, state = base / "intake", base / "state"
            intake.mkdir()
            state.mkdir()
            for key in ("release", "asset_map", "original_board"):
                filename = CONFIG[key]["path"]
                os.link(INTAKE / filename, intake / filename)
            stage = intake / "stage" / historical
            stage.mkdir(parents=True)
            entries = []
            def put(node, role, raw):
                item = {"id": f"fixture-{len(entries)}", "name": object_name(historical, node, role),
                        "parent_ids": [PARENT], "trashed": False, "file_size_bytes": len(raw),
                        "bytes": len(raw), "sha256": digest(raw)}
                entries.append(item)
                (stage / f"remote_{item['id']}.raw").write_bytes(raw)
                return {k: item[k] for k in ("id", "name", "bytes", "sha256")} | {"parent": PARENT}

            def stage_node(node, status, files):
                refs = {role: put(node, role, raw) for role, raw in files.items()}
                put(node, "RECEIPT.json", json_bytes({"schema": "V5_W9D_REMOTE_RECEIPT_V1",
                    "business_date": historical, "node": node, "status": status, "objects": refs, **FLAGS}))

            stage_node("a-top200", "COMPUTED",
                       {"G4.zip": g4, "TOP200.json": archive["TOP200.json"], "SOURCE.json": json_bytes(src_top)})
            stage_node("daily-update", "COMPUTED_ISOLATED", {
                "G4.zip": g4, "GBBQ.zip": gbbq, "SOURCE.json": json_bytes(src_daily),
                "PAR_LEDGER.json": json_bytes({"business_date": historical, "scope": 5575, "rows": rows}),
                "SUMMARY.json": json_bytes(summary), "SAMPLE109.json": archive["SAMPLE_109.json"],
                "FAILED_CLEAN.json": json_bytes({"business_date": historical, "symbols": []}),
                **{f"PAR_STATE_{index:02d}.zip": zip_bytes(members) for index, members in parts.items()},
            })
            json_file(stage, "REMOTE_READBACKS.json", {"date": historical, "entries": entries})
            initialize(intake, state)
            clock = lambda: at_bjt("2026-11-26T18:30")
            with mock.patch("dot_run.load_runtime", return_value=self.runtime), \
                 mock.patch.object(self.runtime.main, "dispatch", wraps=self.runtime.main.dispatch) as dispatch:
                # Real frozen decoder must reject this ZIP, whose raw shape gate passes.
                self.runtime.sources.zip_check(gbbq, historical, "RIGHTS")
                rejected = scheduled("evening", intake, state, clock=clock)
                self.assertEqual(rejected["status"], "BLOCKED")
                self.assertTrue(rejected["reason"].startswith("PAR_GBBQ_DECODE_REJECTED:"), rejected)
                self.assertTrue(rejected["current"]["stale"])
                self.assertFalse((state / "plans").exists())
                dispatch.assert_not_called()
                # Only the positive orchestration seam substitutes decoded data.
                with mock.patch.object(self.runtime.par, "observed_rights",
                                       return_value=(frozenset(), simulated_counts)) as rights:
                    result = scheduled("evening", intake, state, clock=clock)
                self.assertEqual(result["status"], "EVENING_READY", result)
                rights.assert_called_once()
                self.assertEqual(rights.call_args.args[:2], (gbbq, historical))
                dispatch.assert_called_once()
            current = Board(state, writable=False).current()
            self.assertFalse(current["stale"])
            self.assertEqual(current["data_date"], historical)
            self.assertNotEqual(current["last_success"]["raw"]["sha256"], CONFIG["original_board"]["sha256"])
            self.assertIn(b'id="topq"', read_pin(state, current["last_success"]["raw"]))
            assembled = json.loads(read_pin(state, current["last_success"]["proof"]["evening_input"]))
            self.assertTrue(assembled["dot_required_complete"])
            self.assertIn("a-auction", assembled["dot_unscheduled_nodes"])
            self.assertIn("a-auction", assembled["original_assembly_missing"])

    def test_lost_or_damaged_durable_state_cannot_silently_reseed(self):
        with temp() as output:
            path = Path(output)
            check = scheduled("evening", INTAKE, path, clock=lambda: at_bjt("2026-11-30T18:30"))
            self.assertIn("DURABLE_STATE_RESTORE_REQUIRED", check["reason"])
            self.assertIsNone(check["current"]["data_date"])
            initialize(INTAKE, path)
            (path / "CURRENT.json").unlink()
            check = scheduled("evening", INTAKE, path, clock=lambda: at_bjt("2026-11-30T18:30"))
            self.assertIn("DURABLE_STATE_RESTORE_REQUIRED", check["reason"])
            self.assertIsNone(check["current"]["data_date"])
            with self.assertRaisesRegex(ValueError, "DURABLE_STATE_RESTORE_REQUIRED"):
                initialize(INTAKE, path)


    def test_missing_wrong_and_damaged_inner_stock_generation(self):
        day, symbol = "20261126", "000001.SZ"
        with self.assertRaisesRegex(ValueError, "PAR_INNER_STOCK_CONTRACT"):
            validate_stock_member(zip_bytes({"offline-fixture": b"x"}), day, symbol, self.runtime)
        wrong = stock_fixture(self.runtime, day, symbol, wrong_state_date=20261125)
        with self.assertRaisesRegex(ValueError, "PAR_INNER_STOCK_DATE_OR_FIELDS"):
            validate_stock_member(wrong, day, symbol, self.runtime)
        valid = stock_fixture(self.runtime, day, symbol)
        with self.assertRaisesRegex(ValueError, "PAR_INNER_STOCK_CONTRACT"):
            validate_stock_member(valid, "20261127", symbol, self.runtime)

    def test_same_day_rights_observation_at_second_window(self):
        stamp = at_bjt("2026-11-30T16:50:01")
        rights_url = self.runtime.sources.GBBQ
        class Response(io.BytesIO):
            status = 200
            headers = {"Last-Modified": "Fri, 27 Nov 2026 08:10:06 GMT"}
            def geturl(self):
                return rights_url
        structural_zip = zip_bytes({"gbbq": (1).to_bytes(4, "little") + b"x" * 29})
        with temp() as output:
            _, deadline = admit_slot("close", stamp)
            fake_open = mock.Mock(return_value=Response(structural_zip))
            result = capture_source(Path(output), DAY, "RIGHTS", self.runtime, deadline,
                                    clock=lambda: stamp, opener=fake_open)
            self.assertEqual(result["rights_snapshot_finality"], "OBSERVED_NOT_FINAL")
            self.assertEqual(result["observed_at"], stamp.isoformat())
            self.assertEqual(fake_open.call_args.args[0].full_url, rights_url)
            with self.assertRaisesRegex(ValueError, "SOURCE_CAPTURE_CLOCK"):
                capture_source(Path(output), "20261127", "RIGHTS", self.runtime, deadline,
                               clock=lambda: stamp, opener=fake_open)
            self.assertEqual(fake_open.call_count, 1)

    def test_previous_reads_sibling_stage_and_links_exact_pinned_parts(self):
        day, previous = "20261130", "20261127"
        with temp() as output:
            root = Path(output)
            intake, run = root / "intake", root / "run"
            previous_stage = intake / "stage" / previous
            previous_stage.mkdir(parents=True)
            (intake / "stage" / day).mkdir()
            run.mkdir()
            objects = {role: {} for role in ROLES["daily-update"]}
            for index in range(1, 9):
                ident = f"part-{index}"
                raw = f"fixture-{index}".encode()
                (previous_stage / f"remote_{ident}.raw").write_bytes(raw)
                objects[f"PAR_STATE_{index:02d}.zip"] = {"id": ident, "bytes": len(raw), "sha256": digest(raw)}
            remote = {"status": "COMPUTED_ISOLATED", "objects": objects}
            ledger = {"business_date": previous, "scope": 5575,
                      "rows": [{"status": "ISOLATED", "symbol": str(i)} for i in range(5575)]}
            with mock.patch("dot_run.remote_inputs", return_value=object()) as stage, \
                 mock.patch("dot_run.remote_node", return_value=remote), \
                 mock.patch("dot_run.get_remote", return_value=json_bytes(ledger)):
                build_prior(intake, run, day, previous, self.runtime)
            stage.assert_called_once_with(previous_stage, previous, self.runtime)
            manifest = json.loads((run / "VERIFIED_PREVIOUS_PAR_CATALOG.json").read_bytes())
            self.assertEqual(manifest["business_date"], previous)
            self.assertTrue((run / "part-1.zip").samefile(previous_stage / "remote_part-1.raw"))

    def test_changed_board_dates_cannot_relabel_original_raw(self):
        with temp() as output:
            root = Path(output)
            initialize(INTAKE, root)
            current = Board(root, writable=False).current()
            current["last_success"]["data_date"] = DAY
            json_file(root, "CURRENT.json", current)
            result = scheduled("evening", INTAKE, root, clock=lambda: at_bjt("2026-11-30T18:30"))
            self.assertIn("DURABLE_BOARD_POINTER_RESTORE_REQUIRED", result["reason"])
            self.assertIsNone(result["current"]["data_date"])
            with self.assertRaisesRegex(ValueError, "BOARD_POINTER_DATE_OR_FLAGS"):
                Board(root, writable=False).current()
            current.update(data_date=DAY, attempted_date=DAY)
            json_file(root, "CURRENT.json", current)
            with self.assertRaisesRegex(ValueError, "BOARD_RAW_DATE"):
                Board(root, writable=False).current()

    def test_byte_exact_old_current_cannot_replace_newer_bound_pointer(self):
        with temp() as output:
            root = Path(output)
            initialize(INTAKE, root)
            board = open_live_board(root)
            old_pointer = board.pointer.read_bytes()
            html = f"<main><h1>V5 综合静态看板 · {DAY}</h1></main>".encode()
            raw = artifact(root, Path("new.html"), html)
            proof = artifact(root, Path("new-input.json"), json_bytes({
                "business_date": DAY, "slot": "18:30", "dot_required_complete": True,
                "dot_missing_required": [], **FLAGS,
            }))
            board.publish(DAY, raw, "ORIGINAL_V5_W11C_EVENING", {"evening_input": proof})
            self.assertEqual(open_live_board(root).current()["data_date"], DAY)
            board.pointer.write_bytes(old_pointer)
            with self.assertRaisesRegex(ValueError, "DURABLE_BOARD_POINTER_RESTORE_REQUIRED"):
                open_live_board(root)
            result = scheduled("evening", INTAKE, root, clock=lambda: at_bjt("2026-11-30T18:30"))
            self.assertIsNone(result["current"]["data_date"])
            self.assertIsNone(result["current"]["view"])

    def test_wrong_prior_date_cannot_build_catalog(self):
        with temp() as output, mock.patch("dot_run.remote_inputs", return_value=object()), \
             mock.patch("dot_run.remote_node", return_value={"status": "COMPUTED_ISOLATED"}), \
             mock.patch("dot_run.get_remote", return_value=b'{"business_date":"20261126"}'):
            with self.assertRaisesRegex(ValueError, "PREVIOUS_PAR_DATE_OR_SCOPE"):
                build_prior(INTAKE, Path(output), DAY, "20261127", self.runtime)

    def test_writable_state_cannot_be_claimed_concurrently(self):
        with temp() as output, writer_lock(Path(output)):
            with self.assertRaisesRegex(ValueError, "ALREADY_CLAIMED_LOCAL"):
                with writer_lock(Path(output)):
                    self.fail("duplicate local owner entered")


class ConnectorTests(TestCase):
    def setUp(self):
        self.directory = temp()
        self.addCleanup(self.directory.cleanup)
        self.state = Path(self.directory.name)
        initialize(INTAKE, self.state)
        self.evidence = self.state / "fixture-evidence"
        self.evidence.mkdir()
        self.node = "a-top200"
        refs = {role: artifact(self.state, Path(role), role.encode()) for role in ROLES[self.node]}
        save_plan(self.state, DAY, self.node, refs)

    def write_proofs(self, command, rows=(), *, node_rows=(), at=NOW):
        json_file(self.evidence, "LIST.json", listing(command["name"], rows, at=at))
        json_file(self.evidence, "NODE_LIST.json", listing(command["node_receipt_name"], node_rows, at=at))

    def next_action(self, proof=False):
        return action(self.state, DAY, self.node, self.evidence if proof else None, NOW)

    def prove_existing(self, pending, ident):
        metadata = meta(pending, ident)
        self.write_proofs(pending, [metadata])
        json_file(self.evidence, f"metadata_{ident}.json", metadata)
        raw = (self.state / pending["payload"]["path"]).read_bytes()
        (self.evidence / f"remote_{ident}.raw").write_bytes(raw)
        return self.next_action(True)

    def test_paginated_exact_listing_and_failure(self):
        command = self.next_action()
        name = command["name"]
        evidence = listing(name)
        first = evidence["pages"][0]
        first["next_page_token"] = "request-2"
        second = {**first, "request_page_token": "request-2", "next_page_token": None,
                  "files": [meta(command)]}
        evidence["pages"].append(second)
        self.assertEqual(len(check_listing(evidence, name, NOW)[0]), 1)
        for patch, message in [({"request_page_token": "wrong"}, "LIST_INCOMPLETE"),
                               ({"incomplete_search": True}, "LIST_INCOMPLETE"),
                               ({"status": "FAILED"}, "LIST_INCOMPLETE"),
                               ({"next_page_token": "unread"}, "LIST_INCOMPLETE")]:
            with self.subTest(patch=patch), self.assertRaisesRegex(ValueError, message):
                check_listing({**evidence, "pages": [first, {**second, **patch}]}, name, NOW)
        with self.assertRaisesRegex(ValueError, "NOT_FRESH"):
            check_listing(evidence, name, NOW + timedelta(minutes=1))

    def test_different_and_duplicate_same_name_rejected(self):
        pending = self.next_action()
        row = meta(pending)
        for rows, fail in [([row, {**row, "id": "B"}], "DUPLICATE_EXACT_NAME"),
                           ([{**row, "parent_ids": ["other"]}], "CONNECTOR_METADATA")]:
            self.write_proofs(pending, rows)
            with self.subTest(rows=rows), self.assertRaisesRegex(ValueError, fail):
                self.next_action(True)
        self.write_proofs(pending, [row])
        json_file(self.evidence, "metadata_remote-A.json", row)
        (self.evidence / "remote_remote-A.raw").write_bytes(b"x" * row["file_size_bytes"])
        with self.assertRaisesRegex(ValueError, "PIN_SHA"):
            self.next_action(True)

    def test_existing_same_day_node_never_creates_missing_child(self):
        pending = self.next_action()
        node_meta = {**meta(pending), "name": pending["node_receipt_name"]}
        self.write_proofs(pending, node_rows=[node_meta])
        with self.assertRaisesRegex(ValueError, "EXISTING_NODE_RECEIPT_RECONCILE"):
            self.next_action(True)

    def test_unknown_ack_never_retries_and_accepts_later_exact_readback(self):
        pending = self.next_action()
        self.write_proofs(pending)
        permit = self.next_action(True)
        self.assertEqual(permit["status"], "CREATE_ONCE")
        self.assertEqual(self.next_action()["local_claim"], True)
        with self.assertRaisesRegex(ValueError, "ACK_UNKNOWN_NO_RETRY"):
            self.next_action(True)
        self.assertEqual(self.prove_existing(pending, "remote-A")["status"], "READBACK_VERIFIED")


    def test_missing_or_replaced_drive_journal_cannot_duplicate_create(self):
        pending = self.next_action()
        self.write_proofs(pending)
        self.assertEqual(self.next_action(True)["status"], "CREATE_ONCE")
        journal = self.state / "drive" / "JOURNAL.json"
        raw = json.loads(journal.read_bytes())
        shutil.rmtree(journal.parent)
        with self.assertRaisesRegex(ValueError, "DURABLE_DRIVE_JOURNAL_RESTORE_REQUIRED"):
            self.next_action(True)
        journal.parent.mkdir()
        for replacement in ({**raw, "journal_id": "0" * 32}, {**raw, "claims": {}}):
            with self.subTest(replacement=replacement):
                json_file(journal.parent, journal.name, replacement)
                with self.assertRaisesRegex(ValueError, "DURABLE_DRIVE_JOURNAL_RESTORE_REQUIRED"):
                    self.next_action(True)

    def test_existing_identical_objects_and_receipt_need_no_create(self):
        for count in range(4):
            pending = self.next_action()
            if count == 3:
                self.assertEqual(pending["role"], "RECEIPT.json")
                terminal = json.loads((self.state / pending["payload"]["path"]).read_bytes())
                self.assertEqual(set(terminal["objects"]), ROLES[self.node])
                self.assertFalse(terminal["orders_sent"])
            result = self.prove_existing(pending, f"remote-{count}")
            self.assertEqual(result["status"], "READBACK_VERIFIED")
        self.assertEqual(self.next_action()["status"], "REMOTE_VERIFIED")
