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
# Keep immutable preimages verified above; exercise the explicitly manifested fix.
CANDIDATE = ROOT / 'candidate'
if CANDIDATE.exists():
    for entry in json.loads((ROOT / 'CANDIDATE_MANIFEST.json').read_text())['entries']:
        if hashlib.sha256((ROOT / entry['candidate_path']).read_bytes()).hexdigest() != entry['sha256']:
            raise RuntimeError('CANDIDATE_SOURCE_SHA_MISMATCH: ' + entry['candidate_path'])
    import v4.manager_research
    provider_candidate = CANDIDATE / 'v4/manager_research/hkex_provider.py'
    if provider_candidate.exists():
        provider_spec = importlib.util.spec_from_file_location('v4.manager_research.hkex_provider', provider_candidate)
        provider_module = importlib.util.module_from_spec(provider_spec)
        sys.modules[provider_spec.name] = provider_module
        provider_spec.loader.exec_module(provider_module)
        v4.manager_research.hkex_provider = provider_module
    source_spec = importlib.util.spec_from_file_location('v4.manager_research.announcement_source',
        CANDIDATE / 'v4/manager_research/announcement_source.py')
    source = importlib.util.module_from_spec(source_spec)
    sys.modules[source_spec.name] = source
    source_spec.loader.exec_module(source)
else:
    from v4.manager_research import announcement_source as source
from v4.manager_research.materials import MaterialStore
from v4.manager_research.ports import SourceResponse
spec = importlib.util.spec_from_file_location('body_batch_red_subject', (CANDIDATE if CANDIDATE.exists() else PINNED) / 'ops/manager_announcement_body_batch.py')
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
        # A completed response consumes bytes needed by the next full reservation.
        gate = self.gate(total=source.MAX_EASTMONEY_RESPONSE_BYTES)
        first, _ = self.capture(41, gate, lambda url, **kw: response(url))
        second, _ = self.capture(42, gate, lambda url, **kw: response(url))
        self.assertEqual(first['status'], 'CAPTURED')
        self.assertEqual(second['status'], 'CAPTURE_FAILED')
        self.assertEqual(gate.requests, 1)
        self.assertEqual(gate.response_bytes, len(BODY))

    def test_cached_body_costs_zero_physical_requests_and_bytes(self):
        provider = SimpleNamespace(_material_store=self.store, _timeout=20.0,
            _request_eastmoney_hk=lambda url, **kw: response(url))
        source.capture_eastmoney(provider, url_for(51))
        gate = self.gate()
        def forbidden(url, **kw):
            raise AssertionError('cache hit must not enter transport')
        receipt, raw = self.capture(51, gate, forbidden)
        self.assertEqual(receipt['status'], 'CAPTURED')
        self.assertTrue(receipt['from_cache'])
        self.assertEqual(raw, BODY)
        self.assertEqual((gate.requests, gate.response_bytes), (0, 0))

    def test_same_url_concurrent_capture_has_one_request_and_valid_receipt(self):
        gate = self.gate()
        entered, release = threading.Event(), threading.Event()
        calls = []
        def transport(url, **kw):
            calls.append(url); entered.set()
            if not release.wait(5): raise RuntimeError('TEST_RELEASE_WATCHDOG')
            return response(url)
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(self.capture, 61, gate, transport)
            try:
                self.assertTrue(entered.wait(2))
                second = pool.submit(self.capture, 61, gate, transport)
                with self.assertRaises(TimeoutError):
                    second.result(timeout=0.15)
            finally:
                release.set()
            results = [first.result(timeout=5), second.result(timeout=5)]
        self.assertEqual(len(calls), 1)
        self.assertTrue(all(r[0]['status'] == 'CAPTURED' and r[1] == BODY for r in results), results)
        self.assertEqual((gate.requests, gate.response_bytes), (1, len(BODY)))
        receipts = list((self.root/'output'/'receipts').glob('*.json'))
        self.assertEqual(len(receipts), 1)
        self.assertEqual(json.loads(receipts[0].read_text())['status'], 'CAPTURED')

    def test_reservation_isolation_and_duplicate_release_do_not_admit_extra_bytes(self):
        cap = source.MAX_EASTMONEY_RESPONSE_BYTES
        gate = self.gate(total=2*cap)
        entered = threading.Barrier(3)
        finish = threading.Event()
        def owner(size):
            gate.before_request()
            try:
                entered.wait(timeout=3)
                if not finish.wait(5): raise RuntimeError('TEST_RELEASE_WATCHDOG')
                gate.record_response_bytes(size)
                gate.record_response_bytes(size)  # duplicate settlement must not double-charge
            finally:
                gate.end_request()
                gate.end_request()  # must not release another request's permit/reservation
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(owner, size) for size in (7, 11)]
            try:
                entered.wait(timeout=3)
                with self.assertRaisesRegex(RuntimeError, 'BYTE_BUDGET_EXHAUSTED'):
                    gate.before_request()
                gate.end_request()  # unsuccessful admission must not affect the two owners
            finally:
                finish.set()
            for future in futures: future.result(timeout=5)
        self.assertEqual((gate.requests, gate.response_bytes), (2, 18))
        gate.before_request()
        gate.record_response_bytes(3)
        gate.end_request()
        self.assertEqual((gate.requests, gate.response_bytes), (3, 21))

    def test_settlement_retains_bytes_when_readback_fails(self):
        gate = self.gate()
        with patch.dict(API, read_eastmoney_response=lambda *args: (_ for _ in ()).throw(ValueError('CONTROLLED_HASH_FAILURE'))):
            receipt, raw = self.capture(71, gate, lambda url, **kw: response(url))
        self.assertEqual(receipt['status'], 'CAPTURE_FAILED')
        self.assertIsNone(raw)
        self.assertEqual((gate.requests, gate.response_bytes), (1, len(BODY)))
        self.assertEqual(self.capture(72, gate, lambda url, **kw: response(url))[0]['status'], 'CAPTURED')

    def test_request_budget_race_admits_exactly_two(self):
        gate = self.gate(max_requests=2)
        start = threading.Barrier(7)
        def worker(index):
            start.wait(timeout=3)
            return self.capture(index, gate, lambda url, **kw: response(url))[0]['status']
        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = [pool.submit(worker, i) for i in range(80,86)]
            start.wait(timeout=3)
            results = [f.result(timeout=5) for f in futures]
        self.assertEqual(results.count('CAPTURED'), 2)
        self.assertEqual(gate.requests, 2)
        self.assertEqual(gate.response_bytes, 2*len(BODY))

    def test_throttle_wait_does_not_hold_accounting_lock_or_extend_deadline(self):
        gate = self.gate(interval=2.0)
        gate.seconds = 0.8
        gate.before_request()
        started = threading.Event()
        def contender():
            started.set()
            try: gate.before_request()
            finally: gate.end_request()
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(contender)
            self.assertTrue(started.wait(1))
            gate.record_response_bytes(1)
            gate.end_request()
            with self.assertRaisesRegex(RuntimeError, 'TIME_BUDGET_EXHAUSTED'):
                future.result(timeout=2)
        self.assertEqual((gate.requests, gate.response_bytes), (1,1))

    def test_throttle_separates_starts_without_serializing_reads(self):
        gate = self.gate(interval=0.1)
        release = threading.Event()
        condition = threading.Condition()
        starts=[]
        def transport(url, **kw):
            with condition:
                starts.append(time.monotonic()); condition.notify_all()
            if not release.wait(5): raise RuntimeError('TEST_RELEASE_WATCHDOG')
            return response(url)
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures=[pool.submit(self.capture,i,gate,transport) for i in range(90,93)]
            try:
                with condition: self.assertTrue(condition.wait_for(lambda:len(starts)==3,timeout=2))
            finally: release.set()
            results=[f.result(timeout=5) for f in futures]
        self.assertTrue(all(r[0]['status']=='CAPTURED' for r in results),results)
        self.assertTrue(all(b-a>=0.09 for a,b in zip(starts,starts[1:])),starts)

    def test_atomic_json_same_path_has_unique_temporary_files(self):
        barrier=threading.Barrier(3)
        path=self.root/'shared.json'
        def writer(index):
            barrier.wait(timeout=3)
            for _ in range(10): batch.atomic_json(path,{'writer':index})
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(writer,i) for i in (1,2)]
            barrier.wait(timeout=3)
            for f in futures: f.result(timeout=5)
        self.assertIn(json.loads(path.read_text())['writer'],(1,2))
        self.assertEqual(list(self.root.glob('*.tmp')),[])

    def test_batch_owner_rejects_second_runner_before_any_capture(self):
        entered,release=threading.Event(),threading.Event()
        def owned(*args,**kwargs):
            entered.set()
            if not release.wait(5): raise RuntimeError('TEST_RELEASE_WATCHDOG')
            return {'status':'CONTROLLED'}
        args=({},self.root/'materials',self.root/'batch','20261009','2026-10-08')
        with patch.object(batch,'_run_capture_owned',side_effect=owned):
            with ThreadPoolExecutor(max_workers=1) as pool:
                first=pool.submit(batch.run_capture,*args)
                try:
                    self.assertTrue(entered.wait(2))
                    with self.assertRaises(TimeoutError): batch.run_capture(*args)
                finally: release.set()
                self.assertEqual(first.result(timeout=5),{'status':'CONTROLLED'})

    def test_provider_is_reused_per_worker_but_never_shared_across_workers(self):
        instances=[]
        lock=threading.Lock()
        def factory(**kwargs):
            provider=SimpleNamespace(**kwargs)
            with lock: instances.append(provider)
            return provider
        providers=batch._WorkerProviders({'HkexOfficialProvider':factory},self.store)
        barrier=threading.Barrier(3)
        def worker():
            first=providers.get()
            barrier.wait(timeout=3)
            self.assertIs(first,providers.get())
            return first
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures=[pool.submit(worker) for _ in range(3)]
            result=[f.result(timeout=5) for f in futures]
        self.assertEqual(len({id(p) for p in result}),3)
        self.assertEqual(len(instances),3)
        self.assertTrue(all(p.material_store is self.store and p.timeout==20.0 for p in result))


    def test_batch_owner_lock_does_not_precreate_canary_output(self):
        output=self.root/'new-canary'
        def owned(*args,**kwargs):
            self.assertFalse(output.exists())
            return {'status':'CONTROLLED'}
        with patch.object(batch,'_run_capture_owned',side_effect=owned):
            self.assertEqual(batch.run_capture({},self.root/'materials',output,
                '20261009','2026-10-08',canary_article='CONTROLLED'),{'status':'CONTROLLED'})

    def test_waiting_for_inflight_slot_stops_at_deadline(self):
        gate=self.gate()
        entered=threading.Barrier(4)
        release=threading.Event()
        def owner():
            gate.before_request()
            try:
                entered.wait(timeout=3)
                if not release.wait(5): raise RuntimeError('TEST_RELEASE_WATCHDOG')
            finally: gate.end_request()
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures=[pool.submit(owner) for _ in range(3)]
            try:
                entered.wait(timeout=3)
                gate.seconds=gate.elapsed_seconds+0.2
                with self.assertRaisesRegex(RuntimeError,'TIME_BUDGET_EXHAUSTED'):
                    gate.before_request()
                gate.end_request()
            finally: release.set()
            for future in futures: future.result(timeout=5)
        self.assertEqual((gate.requests,gate.response_bytes),(3,0))

    def test_timeout_never_rounds_tiny_remaining_budget_up(self):
        observed=[]
        def transport(url,*,timeout):
            observed.append(timeout)
            return response(url)
        provider=SimpleNamespace(_material_store=self.store,_timeout=20.0,_request_eastmoney_hk=transport)
        budget=source.CaptureBudget(seconds=0.0001,_start=0,interval=0)
        with patch.object(source,'monotonic',return_value=0):
            source.capture_eastmoney(provider,url_for(101),budget=budget)
        self.assertEqual(observed,[0.0001])

if __name__ == '__main__':
    unittest.main(verbosity=2)
