"""Mac-only offline RED candidate. Real capture/store; fake transport, no sockets.

Mutations caught: replacing provider timeout with batch remainder; retaining a
request-wide gate lock; admitting a fourth concurrent request; dropping request
count/deadline checks; leaking reservations after a failed request.
"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
import hashlib
import importlib.util
import json
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PINNED = ROOT / 'pinned'

def deny_network(event, args):
    if event in {'socket.connect', 'socket.connect_ex', 'socket.getaddrinfo',
                 'socket.bind', 'subprocess.Popen', 'os.system'}:
        raise RuntimeError('OFFLINE_TEST_NETWORK_OR_PROCESS_FORBIDDEN')

sys.addaudithook(deny_network)
# Source checks occur before imports; an incorrect source is ERROR, never RED.
for entry in json.loads((ROOT / 'SOURCE_MANIFEST.json').read_text())['entries']:
    path = ROOT / entry['candidate_path']
    if hashlib.sha256(path.read_bytes()).hexdigest() != entry['sha256']:
        raise RuntimeError('PINNED_SOURCE_SHA_MISMATCH: ' + entry['candidate_path'])
sys.path.insert(0, str(PINNED))
from v4.manager_research import announcement_source as source
from v4.manager_research.materials import MaterialStore
from v4.manager_research.ports import SourceResponse
spec = importlib.util.spec_from_file_location('body_batch_red_subject', PINNED / 'ops/manager_announcement_body_batch.py')
batch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(batch)

API = dict(capture_eastmoney=source.capture_eastmoney,
           read_eastmoney_response=source.read_eastmoney_response,
           safe_reason=source.safe_reason)
BODY = b'{"offline_fixture":true}'

def url_for(index):
    return source.eastmoney_content_url('AN20261009000000%04d' % index)

def response(url):
    return SourceResponse(url=url, status_code=200, body=BODY, headers={},
                          retrieved_at='2026-10-09T00:00:00+00:00', final_url=url)

class CaptureBudgetRed(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='announcement-budget-red-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = MaterialStore(self.root / 'materials')

    def gate(self, *, max_requests=2000, total=64*1024*1024, interval=0):
        gate = batch.SharedCaptureGate(seconds=3600, max_requests=max_requests,
                                       max_bytes=total, interval=interval)
        gate.set_response_limits(per_response=source.MAX_EASTMONEY_RESPONSE_BYTES, total=total)
        return gate

    def capture(self, index, gate, transport):
        # Each worker has an independent provider/transport. No urllib opener.
        provider = SimpleNamespace(_material_store=self.store, _timeout=20.0,
                                   _request_eastmoney_hk=transport)
        return batch._capture_url(API, self.store, provider, gate, url_for(index),
            art_code='AN20261009000000%04d' % index, page_index=1,
            kind='content', out_root=self.root / 'output')

    def test_single_request_timeout_respects_provider_and_remaining_budget(self):
        for index, seconds, expected in [(1, 3600.0, 20.0), (2, 0.25, 0.25), (3, None, 20.0)]:
            with self.subTest(batch_remaining=seconds):
                observed = []
                def transport(url, *, timeout):
                    observed.append(timeout)
                    return response(url)
                provider = SimpleNamespace(_material_store=self.store, _timeout=20.0,
                                           _request_eastmoney_hk=transport)
                budget = None if seconds is None else source.CaptureBudget(seconds=seconds, _start=100.0, interval=0)
                with patch.object(source, 'monotonic', return_value=100.0):
                    ref = source.capture_eastmoney(provider, url_for(index), budget=budget)
                self.assertEqual(source.read_eastmoney_response(self.store, ref), BODY)
                self.assertEqual(observed, [expected], 'HTTP timeout must be min(provider timeout, batch remaining)')

    def test_three_requests_overlap_but_a_fourth_stays_outside_transport(self):
        gate = self.gate()
        release = threading.Event()
        condition = threading.Condition()
        active = 0
        peak = 0
        entered = 0
        entered_times = []
        def transport(url, *, timeout):
            nonlocal active, peak, entered
            with condition:
                active += 1; entered += 1; peak = max(peak, active)
                entered_times.append(time.monotonic())
                condition.notify_all()
            try:
                if not release.wait(10):
                    raise RuntimeError('TEST_RELEASE_WATCHDOG')
                return response(url)
            finally:
                with condition:
                    active -= 1
        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = [pool.submit(self.capture, i, gate, transport) for i in range(10, 16)]
            try:
                with condition:
                    condition.wait_for(lambda: entered >= 3, timeout=3)
                    first_wave = entered
                    fourth_entered = condition.wait_for(lambda: entered > 3, timeout=0.2)
            finally:
                release.set()
            results = [f.result(timeout=15) for f in futures]
        self.assertTrue(all(r[0]['status'] == 'CAPTURED' for r in results), results)
        self.assertEqual(gate.requests, 6)
        self.assertEqual(gate.response_bytes, 6 * len(BODY))
        self.assertEqual(first_wave, 3, 'three distinct URLs must enter HTTP before any read is released')
        self.assertFalse(fourth_entered, 'in-flight cap is independent of caller thread count')
        self.assertEqual(peak, 3)

    def test_failed_transport_releases_reservation_and_preserves_attempt_receipt(self):
        # One response-sized total makes a reservation leak observable on next URL.
        gate = self.gate(total=source.MAX_EASTMONEY_RESPONSE_BYTES)
        def fail(url, *, timeout):
            raise OSError('CONTROLLED_OFFLINE_FAILURE')
        failed, raw = self.capture(21, gate, fail)
        self.assertEqual(failed['status'], 'CAPTURE_FAILED')
        self.assertIsNone(raw)
        good, raw = self.capture(22, gate, lambda url, **kw: response(url))
        self.assertEqual(good['status'], 'CAPTURED')
        self.assertEqual(raw, BODY)
        self.assertEqual(gate.requests, 2)
        self.assertEqual(gate.response_bytes, len(BODY))
        self.assertEqual(len(list((self.root/'output'/'attempts').glob('*.json'))), 2)
        self.assertEqual(len(list((self.root/'output'/'receipts').glob('*.json'))), 2)

    def test_request_and_deadline_limits_prevent_transport_entry(self):
        for index, expired in [(31, False), (32, True)]:
            with self.subTest(expired=expired):
                gate = self.gate(max_requests=0 if not expired else 2000)
                if expired:
                    gate.started = time.monotonic() - 3601
                called = []
                def transport(url, *, timeout):
                    called.append(url)
                    return response(url)
                receipt, raw = self.capture(index, gate, transport)
                self.assertEqual(receipt['status'], 'CAPTURE_FAILED')
                self.assertIsNone(raw)
                self.assertEqual(called, [])
                self.assertEqual(gate.requests, 0)
                self.assertEqual(gate.response_bytes, 0)

    def test_byte_reservations_prevent_two_full_responses_exceeding_total(self):
        # Sequential guard; concurrent reservation ownership requires another RED
        # once the initial overlap regression has been observed on the Mac.
        gate = self.gate(total=source.MAX_EASTMONEY_RESPONSE_BYTES)
        first, _ = self.capture(41, gate, lambda url, **kw: response(url))
        second, _ = self.capture(42, gate, lambda url, **kw: response(url))
        self.assertEqual(first['status'], 'CAPTURED')
        self.assertEqual(second['status'], 'CAPTURE_FAILED')
        self.assertEqual(gate.requests, 1)
        self.assertEqual(gate.response_bytes, len(BODY))

if __name__ == '__main__':
    unittest.main(verbosity=2)
