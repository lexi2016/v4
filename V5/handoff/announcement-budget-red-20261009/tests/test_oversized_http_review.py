"""Returned oversized 429 regression; no real network or product execution here."""
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('http_review_support',Path(__file__).with_name('test_http_policy_red.py'))
support=importlib.util.module_from_spec(spec);sys.modules[spec.name]=support;spec.loader.exec_module(support)

class OversizedHttpReview(unittest.TestCase):
    setUp=support.HttpPolicyRed.setUp
    gate=support.HttpPolicyRed.gate
    capture_on_gate=support.HttpPolicyRed.capture_on_gate
    assert_policy=support.HttpPolicyRed.assert_policy

    def test_returned_oversized_429_records_policy_and_exact_bytes_before_size_rejection(self):
        gate=self.gate();opened=[];raw=b'x'*(8*1024*1024+1)
        def transport(url,**kwargs):
            opened.append(url)
            return support.provider_module.SourceResponse(url=url,final_url=url,status_code=429,
                body=raw,headers={'Retry-After':'120'},retrieved_at=support.NOW)
        with patch.object(support.provider_module,'_now',return_value=support.NOW):
            first,_=self.capture_on_gate(491,gate,transport)
        second,_=self.capture_on_gate(492,gate,transport)
        policy=self.assert_policy(first,429,'STOP_AND_COOLDOWN')
        self.assertEqual(policy['retry_after_seconds'],120)
        self.assertEqual(policy['cooldown_until_utc'],'2026-10-09T12:02:00+00:00')
        self.assertEqual(gate.response_bytes,len(raw))
        self.assertEqual(gate.requests,1)
        self.assertEqual(len(opened),1)
        self.assertEqual(second['status'],'CAPTURE_FAILED')
        self.assertEqual(gate._leases,{})
        self.assertEqual(list((self.root/'materials'/'index').glob('*.json')),[])

if __name__=='__main__':unittest.main(verbosity=2)
