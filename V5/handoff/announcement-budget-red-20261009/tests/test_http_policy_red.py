"""Offline RED for the next HTTP gate, using the real provider/read boundary.

No sockets. Existing 31 methods are not executed by this file.
"""
from pathlib import Path
from types import SimpleNamespace
from email.message import Message
from urllib.error import HTTPError
import importlib.util
import json
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('provider_policy_test_support',
    ROOT/'tests/test_provider_byte_accounting_red.py')
support=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=support
spec.loader.exec_module(support)
base=support.support
provider_module=support.provider_module
NOW='2026-10-09T12:00:00+00:00'
SECRET='DO_NOT_PERSIST_COOKIE_OR_TOKEN'


class PayloadResponse(support.ControlledResponse):
    def __init__(self,url,body,*,status=200,headers=None):
        super().__init__(url,len(body),headers=headers)
        self.payload=body
        self.status=status

    def read(self,size):
        start=self.bytes_read
        count=min(size,self.remaining)
        self.bytes_read+=count
        self.remaining-=count
        return self.payload[start:start+count]

    read1=read


class HttpPolicyRed(unittest.TestCase):
    setUp=base.CaptureBudgetRed.setUp
    gate=base.CaptureBudgetRed.gate
    capture_on_gate=support.RealProviderByteAccountingRed.capture_on_gate
    default_transport=support.RealProviderByteAccountingRed.default_transport

    def http_error_transport(self,status,retry_after=None):
        opened=[]
        headers=Message()
        if retry_after is not None: headers['Retry-After']=retry_after
        headers['Set-Cookie']=SECRET
        headers['Authorization']='Bearer '+SECRET
        def open_response(request,*,timeout):
            opened.append(request.full_url)
            raise HTTPError(request.full_url,status,SECRET,headers,None)
        with patch.object(provider_module,'build_opener',return_value=SimpleNamespace(open=open_response)):
            transport=provider_module._default_eastmoney_hk_transport()
        return transport,opened

    def assert_policy(self,receipt,status,action):
        self.assertEqual(receipt['status'],'CAPTURE_FAILED')
        policy=receipt.get('byte_accounting',{}).get('http_policy',{})
        self.assertEqual(policy.get('status_code'),status,
            'HTTP status must survive provider wrapping in a sanitized policy receipt')
        self.assertEqual(policy.get('action'),action)
        self.assertIs(policy.get('automatic_retry'),False)
        self.assertNotIn(SECRET,json.dumps(receipt))
        return policy

    def test_429_seconds_preserves_cooldown_and_blocks_other_urls(self):
        gate=self.gate()
        transport,opened=self.http_error_transport(429,'120')
        with patch.object(provider_module,'_now',return_value=NOW):
            receipt,_=self.capture_on_gate(401,gate,transport)
        second,_=self.capture_on_gate(402,gate,transport)
        self.assertEqual(len(opened),1)
        self.assertEqual(second['status'],'CAPTURE_FAILED')
        policy=self.assert_policy(receipt,429,'STOP_AND_COOLDOWN')
        self.assertEqual(policy.get('retry_after_seconds'),120)
        self.assertEqual(policy.get('cooldown_until_utc'),'2026-10-09T12:02:00+00:00')
        self.assertEqual(policy.get('retry_after_raw'),'120')
        self.assertEqual(gate.requests,1)

    def test_503_http_date_preserves_cooldown(self):
        gate=self.gate()
        transport,_=self.http_error_transport(503,'Fri, 09 Oct 2026 12:02:00 GMT')
        with patch.object(provider_module,'_now',return_value=NOW):
            receipt,_=self.capture_on_gate(411,gate,transport)
        policy=self.assert_policy(receipt,503,'STOP_AND_COOLDOWN')
        self.assertEqual(policy.get('retry_after_seconds'),120)
        self.assertEqual(policy.get('cooldown_until_utc'),'2026-10-09T12:02:00+00:00')

    def test_403_is_hard_stop_not_a_retry_after_permission(self):
        gate=self.gate()
        transport,opened=self.http_error_transport(403,'1')
        first,_=self.capture_on_gate(421,gate,transport)
        second,_=self.capture_on_gate(422,gate,transport)
        self.assertEqual(len(opened),1)
        self.assertEqual(second['status'],'CAPTURE_FAILED')
        policy=self.assert_policy(first,403,'STOP')
        self.assertIsNone(policy.get('cooldown_until_utc'))
        self.assertEqual(policy.get('reason'),'HTTP_403')

    def test_200_html_captcha_stops_batch_without_caching_challenge(self):
        gate=self.gate()
        body=b'<html><title>Security Verification</title><form><input name="captcha"></form></html>'
        response=PayloadResponse(base.url_for(431),body,headers={'Content-Type':'text/html'})
        transport,opened=self.default_transport(response)
        first,_=self.capture_on_gate(431,gate,transport)
        next_response=PayloadResponse(base.url_for(432),b'{}',headers={'Content-Type':'application/json'})
        next_transport,next_opened=self.default_transport(next_response)
        second,_=self.capture_on_gate(432,gate,next_transport)
        self.assertEqual(first['status'],'CAPTURE_FAILED','challenge HTML is not an announcement body')
        self.assertEqual(second['status'],'CAPTURE_FAILED')
        self.assertEqual((len(opened),len(next_opened)),(1,0))
        policy=self.assert_policy(first,200,'STOP')
        self.assertEqual(policy.get('reason'),'CAPTCHA_CHALLENGE')
        self.assertEqual(gate.response_bytes,len(body))
        self.assertEqual(list((self.root/'materials'/'index').glob('*.json')),[])

    def test_returned_429_response_is_charged_but_not_cached(self):
        gate=self.gate()
        body=b'{"error":"rate limited"}'
        response=PayloadResponse(base.url_for(441),body,status=429,
            headers={'Retry-After':'9','Set-Cookie':SECRET,'Content-Type':'application/json'})
        transport,_=self.default_transport(response)
        with patch.object(provider_module,'_now',return_value=NOW):
            receipt,_=self.capture_on_gate(441,gate,transport)
        policy=self.assert_policy(receipt,429,'STOP_AND_COOLDOWN')
        self.assertEqual(policy.get('retry_after_seconds'),9)
        self.assertEqual(gate.response_bytes,len(body))
        self.assertEqual(list((self.root/'materials'/'index').glob('*.json')),[])

    def test_malformed_retry_after_stops_without_inventing_wait(self):
        gate=self.gate()
        transport,_=self.http_error_transport(429,'not-a-date')
        receipt,_=self.capture_on_gate(451,gate,transport)
        policy=self.assert_policy(receipt,429,'STOP')
        self.assertIsNone(policy.get('retry_after_seconds'))
        self.assertIsNone(policy.get('cooldown_until_utc'))

    def test_announcement_json_mentioning_captcha_is_not_a_challenge(self):
        gate=self.gate()
        body=b'{"notice_content":"The company sells captcha software."}'
        response=PayloadResponse(base.url_for(461),body,headers={'Content-Type':'application/json'})
        transport,_=self.default_transport(response)
        receipt,raw=self.capture_on_gate(461,gate,transport)
        self.assertEqual(receipt['status'],'CAPTURED')
        self.assertEqual(raw,body)
        self.assertIsNone(receipt.get('byte_accounting',{}).get('http_policy'))
        self.assertEqual(gate.response_bytes,len(body))

    def test_provider_bound_policy_covers_catalog_calls_without_explicit_budget(self):
        gate=self.gate()
        transport,opened=self.http_error_transport(429,'30')
        provider=provider_module.HkexOfficialProvider(material_store=self.store,
            transport=lambda *a,**kw:None,eastmoney_transport=transport)
        # Proposed owner binding: the original catalog calls capture_eastmoney
        # without a budget argument. The provider must carry the shared policy.
        provider._capture_policy=gate
        for index in (471,472):
            with self.assertRaises(RuntimeError):
                base.source.capture_eastmoney(provider,base.url_for(index),force=True)
        self.assertEqual(len(opened),1,'date-catalog calls must not bypass the shared HTTP stop')
        self.assertEqual(gate.requests,1)

    def test_implicit_catalog_budget_releases_each_successful_request(self):
        gate=self.gate()
        opened=[]
        def open_response(request,*,timeout):
            opened.append(request.full_url)
            return PayloadResponse(request.full_url,b'{}',headers={'Content-Type':'application/json'})
        with patch.object(provider_module,'build_opener',return_value=SimpleNamespace(open=open_response)):
            transport=provider_module._default_eastmoney_hk_transport()
        provider=provider_module.HkexOfficialProvider(material_store=self.store,
            transport=lambda *a,**kw:None,eastmoney_transport=transport)
        provider._capture_policy=gate
        for index in (481,482):
            ref=base.source.capture_eastmoney(provider,base.url_for(index),force=True)
            self.assertEqual(base.source.read_eastmoney_response(self.store,ref),b'{}')
        self.assertEqual(len(opened),2)
        self.assertEqual((gate.requests,gate.response_bytes),(2,4))


if __name__=='__main__':
    unittest.main(verbosity=2)
