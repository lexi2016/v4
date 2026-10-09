"""Targeted Mac RED: real provider/default transport, controlled opener only.

No implementation changes. Counters must include bytes returned by response.read
before provider validation or transport failure; header rejection reads zero.
"""
from pathlib import Path
from types import SimpleNamespace
import importlib.util
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('capture_budget_support',
    ROOT / 'tests/test_capture_budget_red.py')
support = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = support
spec.loader.exec_module(support)  # Installs network/process deny hook and verifies source hashes.
from v4.manager_research import hkex_provider as provider_module

CAP = support.source.MAX_EASTMONEY_RESPONSE_BYTES


class ControlledResponse:
    """Return at most read(size) bytes and expose the observed read count."""
    status = 200

    def __init__(self, url, size, *, headers=None, fail_after=None):
        self.url = url
        self.remaining = size
        self.headers = headers or {}
        self.fail_after = fail_after
        self.bytes_read = 0
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True

    def geturl(self):
        return self.url

    def read(self, size):
        if self.fail_after is not None and self.bytes_read >= self.fail_after:
            raise OSError('CONTROLLED_READ_INTERRUPTION')
        count = min(size, self.remaining)
        if self.fail_after is not None:
            count = min(count, self.fail_after - self.bytes_read)
        self.remaining -= count
        self.bytes_read += count
        return b'x' * count

    read1 = read


class RealProviderByteAccountingRed(unittest.TestCase):
    setUp = support.CaptureBudgetRed.setUp
    gate = support.CaptureBudgetRed.gate

    def capture(self, index, transport):
        gate = self.gate()
        # The real provider performs all type/URL/size validation. Supply a
        # forbidden unused official transport so constructor cannot create one.
        def official_forbidden(*args, **kwargs):
            raise AssertionError('official transport must remain unused')
        provider = provider_module.HkexOfficialProvider(
            material_store=self.store, timeout=20.0,
            transport=official_forbidden, eastmoney_transport=transport)
        receipt, raw = support.batch._capture_url(
            support.API, self.store, provider, gate, support.url_for(index),
            art_code='AN20261009000000%04d' % index, page_index=1,
            kind='content', out_root=self.root/'output')
        self.assertEqual(gate.requests, 1)
        return gate, receipt, raw

    def default_transport(self, response):
        # Run the real Request construction and default read loop. Only the
        # opener boundary is replaced; no HTTP server or sockets are involved.
        opened = []
        def open_response(request, *, timeout):
            opened.append((request.full_url, timeout))
            return response
        opener = SimpleNamespace(open=open_response)
        with patch.object(provider_module, 'build_opener', return_value=opener):
            transport = provider_module._default_eastmoney_hk_transport()
        return transport, opened

    def assert_failed_and_charged(self, gate, receipt, raw, expected):
        self.assertEqual(receipt['status'], 'CAPTURE_FAILED')
        self.assertIsNone(raw)
        self.assertEqual(gate.response_bytes, expected,
            'received bytes must remain charged when provider/transport rejects the response')

    def test_default_transport_over_limit_probe_is_charged(self):
        response = ControlledResponse(support.url_for(201), CAP+1)
        transport, opened = self.default_transport(response)
        gate, receipt, raw = self.capture(201, transport)
        self.assertEqual(len(opened), 1)
        self.assertEqual(response.bytes_read, CAP+1)
        self.assertTrue(response.closed)
        self.assert_failed_and_charged(gate, receipt, raw, response.bytes_read)

    def test_default_transport_partial_read_before_exception_is_charged(self):
        response = ControlledResponse(support.url_for(202), 20, fail_after=7)
        transport, opened = self.default_transport(response)
        gate, receipt, raw = self.capture(202, transport)
        self.assertEqual(len(opened), 1)
        self.assertEqual(response.bytes_read, 7)
        self.assertTrue(response.closed)
        self.assert_failed_and_charged(gate, receipt, raw, response.bytes_read)

    def test_real_provider_rejected_oversize_response_is_charged(self):
        body = b'x' * (CAP+1)
        def transport(url, **kwargs):
            return support.SourceResponse(url=url, status_code=200, body=body,
                headers={}, retrieved_at='2026-10-09T00:00:00+00:00', final_url=url)
        gate, receipt, raw = self.capture(203, transport)
        self.assert_failed_and_charged(gate, receipt, raw, len(body))

    def test_real_provider_rejected_final_url_still_charges_returned_body(self):
        body = b'controlled-invalid-final-url'
        def transport(url, **kwargs):
            return support.SourceResponse(url=url, status_code=200, body=body,
                headers={}, retrieved_at='2026-10-09T00:00:00+00:00',
                final_url='https://invalid.example/never-requested')
        gate, receipt, raw = self.capture(204, transport)
        self.assert_failed_and_charged(gate, receipt, raw, len(body))

    def test_header_rejection_before_read_does_not_charge_unread_body(self):
        response = ControlledResponse(support.url_for(205), CAP+1,
            headers={'Content-Length': str(CAP+1)})
        transport, opened = self.default_transport(response)
        gate, receipt, raw = self.capture(205, transport)
        self.assertEqual(len(opened), 1)
        self.assertEqual(response.bytes_read, 0)
        self.assertTrue(response.closed)
        self.assert_failed_and_charged(gate, receipt, raw, 0)

    def test_real_default_transport_success_is_counted_exactly_once(self):
        response = ControlledResponse(support.url_for(206), 23)
        transport, opened = self.default_transport(response)
        gate, receipt, raw = self.capture(206, transport)
        self.assertEqual(len(opened), 1)
        self.assertEqual(receipt['status'], 'CAPTURED')
        self.assertEqual(raw, b'x'*23)
        self.assertEqual(response.bytes_read, 23)
        self.assertEqual(gate.response_bytes, 23)
        self.assertTrue(response.closed)


if __name__ == '__main__':
    unittest.main(verbosity=2)
