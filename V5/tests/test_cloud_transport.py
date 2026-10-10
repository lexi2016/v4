"""Synthetic openers only: the frozen owner must never bypass a denied CONNECT."""
from pathlib import Path
import importlib.util
import io
import sys
import unittest
from urllib.error import URLError, HTTPError
from unittest.mock import Mock
from types import SimpleNamespace

BASE=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('v5_test_frozen_transport',BASE/'vendor/us_mapping_baseline/infrastructure/http_transport.py')
owner=importlib.util.module_from_spec(spec);sys.modules[spec.name]=owner;spec.loader.exec_module(owner)
from v5_shadow.cloud_transport import guarded_transport_class

class Response(io.BytesIO):
    status=200

class CloudTransportTests(unittest.TestCase):
    def make(self,error):
        proxy=Mock(side_effect=error);direct=Mock(return_value=Response(b'synthetic'))
        transport=guarded_transport_class(owner)(proxy_url='http://proxy.invalid:8080',proxy_opener=SimpleNamespace(open=proxy),direct_opener=SimpleNamespace(open=direct))
        return transport,proxy,direct

    def test_connect_refusals_never_invoke_direct_fallback(self):
        for code in (400,401,403,407,429,451,500,502,503):
            with self.subTest(code=code):
                t,p,d=self.make(URLError(OSError(f'Tunnel connection failed: {code} Synthetic refusal')))
                with self.assertRaises(owner.HTTPContractError) as raised:t.fetch('https://source.invalid/test')
                p.assert_called_once();d.assert_not_called()
                receipt=raised.exception.receipt
                self.assertEqual(receipt['proxy_connect_status'],code)
                self.assertIsNone(receipt['http_status'])
                self.assertFalse(receipt['fallback_used'])
                self.assertTrue(receipt['proxy_used'])
                self.assertEqual(receipt['v5_transport_policy'],'CONNECT_REJECTION_NO_DIRECT_FALLBACK')

    def test_original_upstream_http_denial_remains_no_fallback(self):
        body=io.BytesIO(b'synthetic denial')
        t,p,d=self.make(HTTPError('https://source.invalid',403,'Forbidden',{},body))
        with self.assertRaises(owner.HTTPContractError) as raised:t.fetch('https://source.invalid')
        d.assert_not_called();self.assertEqual(raised.exception.receipt['http_status'],403)
        self.assertTrue(body.closed)

    def test_unrelated_timeout_keeps_original_transport_behavior(self):
        t,p,d=self.make(TimeoutError('synthetic timeout'))
        result=t.fetch('https://source.invalid')
        p.assert_called_once();d.assert_called_once()
        self.assertEqual(result.body,b'synthetic');self.assertTrue(result.receipt['fallback_used'])

    def test_success_preserves_owner_result_and_request_options(self):
        p=Mock(return_value=Response(b'original body'));d=Mock()
        t=guarded_transport_class(owner)(proxy_url='http://proxy.invalid:8080',proxy_opener=SimpleNamespace(open=p),direct_opener=SimpleNamespace(open=d))
        result=t.fetch('https://source.invalid',timeout=7,headers={'X-Synthetic':'1'})
        d.assert_not_called();self.assertIsInstance(result,owner.FetchResult)
        self.assertEqual(result.body,b'original body');self.assertEqual(p.call_args.kwargs['timeout'],7)
        self.assertEqual(p.call_args.args[0].get_header('X-synthetic'),'1')

class CloudCliBindingTests(unittest.TestCase):
    def test_original_cli_receives_guarded_transport_and_preserves_exit(self):
        from types import SimpleNamespace
        from v5_shadow.cloud_transport import run_original_us_cli
        proxy=Mock(side_effect=URLError('Tunnel connection failed: 403 Forbidden'));direct=Mock()
        calls=[]
        def producer(**kwargs):
            calls.append(kwargs)
            with self.assertRaises(owner.HTTPContractError):kwargs['transport'].fetch('https://source.invalid')
            return 2
        module=SimpleNamespace(materialize_us_market_phase=producer,materialize_us_historical_backfill=producer)
        module.main=lambda argv:module.materialize_us_market_phase(data_root='synthetic-only',trade_date='20261009',capture_phase='POST_CLOSE')
        result=run_original_us_cli(module,owner,[],allow_network_capture=True,transport_options=dict(proxy_url='http://proxy.invalid',proxy_opener=SimpleNamespace(open=proxy),direct_opener=SimpleNamespace(open=direct)))
        self.assertEqual(result,2);direct.assert_not_called();proxy.assert_called_once()
        self.assertIs(module.materialize_us_market_phase,producer)
        self.assertIs(module.materialize_us_historical_backfill,producer)
        self.assertEqual(calls[0]['trade_date'],'20261009')

    def test_no_authorization_performs_no_call(self):
        from types import SimpleNamespace
        from v5_shadow.cloud_transport import run_original_us_cli
        module=SimpleNamespace(main=Mock())
        with self.assertRaisesRegex(ValueError,'EXPLICIT_AUTHORIZATION'):
            run_original_us_cli(module,owner,[])
        module.main.assert_not_called()

    def test_cli_failure_restores_original_functions(self):
        from types import SimpleNamespace
        from v5_shadow.cloud_transport import run_original_us_cli
        original=Mock();module=SimpleNamespace(materialize_us_market_phase=original,materialize_us_historical_backfill=original)
        module.main=Mock(side_effect=ValueError('synthetic parser rejection'))
        with self.assertRaisesRegex(ValueError,'synthetic parser'):
            run_original_us_cli(module,owner,[],allow_network_capture=True)
        self.assertIs(module.materialize_us_market_phase,original)
        self.assertIs(module.materialize_us_historical_backfill,original)

class CloudEntryTests(unittest.TestCase):
    def test_missing_explicit_capture_flag_never_loads_owner(self):
        from unittest.mock import patch
        from v5_shadow.cloud_transport import main
        with patch.dict(sys.modules,{'ops':None,'infrastructure':None}):
            with self.assertRaisesRegex(ValueError,'EXPLICIT_AUTHORIZATION'):main([])
