"""V4 volume contract tests. Synthetic rows are engineering fixtures, not market acceptance."""
import importlib.util,tempfile,unittest,json,gzip,csv,copy
from pathlib import Path
HERE=Path(__file__).resolve().parent
SPEC=importlib.util.spec_from_file_location('volume_v4',HERE/'volume_contract_v4.py')
# RED asserts absence rather than treating an import typo as a feature failure.
class VolumeContractTests(unittest.TestCase):
 def setUp(self):
  self.assertTrue((HERE/'volume_contract_v4.py').exists(),'V4 exact-once volume contract is not implemented')
  self.v=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(self.v)
 def row(self,vol=60110591,reserved=0xc3640061):
  return {'trade_date':20260522,'open':'4.7','high':'5.16','low':'4.47','close':'4.9','amount':'29162717184.0','vol':str(vol),'reserved':str(reserved)}
 def test_exact_marker_decode_and_unchanged_other_fields(self):
  r=self.row();q={**r,'close':'4.8'};raw,adj,receipt=self.v.normalize_pair([r],[q],self.v.RAW_ENCODING)
  self.assertEqual(raw[0]['vol'],'6011059197');self.assertEqual(adj[0]['vol'],'6011059197');self.assertEqual(receipt['decoded_rows'],1)
  self.assertEqual({k:v for k,v in raw[0].items() if k!='vol'},{k:v for k,v in r.items() if k!='vol'})
 def test_already_decoded_marker_is_not_decoded_twice(self):
  r=self.row(6011059197);out,_,receipt=self.v.normalize_pair([r],[r],self.v.DECODED_ENCODING,self.v.DECODER_SHA)
  self.assertEqual(out,[r]);self.assertEqual(receipt['decoded_rows'],0)
 def test_nonmarker_reserved_not_multiplied(self):
  r=self.row(100,12345);r['amount']='490';out,_,_=self.v.normalize_pair([r],[r],self.v.RAW_ENCODING)
  self.assertEqual(out,[r])
 def test_schema_and_decoder_version_are_required(self):
  r=self.row()
  for enc,h in [('UNKNOWN',None),(None,None),(self.v.DECODED_ENCODING,'bad')]:
   with self.assertRaises(ValueError):self.v.normalize_pair([r],[r],enc,h)
 def test_mislabeled_decoded_raw_marker_rejected(self):
  r=self.row()
  with self.assertRaisesRegex(ValueError,'DECODED_MARKER'):self.v.normalize_pair([r],[r],self.v.DECODED_ENCODING,self.v.DECODER_SHA)
 def test_bad_marker_remainder_and_bad_envelope_rejected(self):
  for r in [self.row(reserved=0xc3640064),{**self.row(),'amount':'10'}]:
   with self.assertRaises(ValueError):self.v.normalize_pair([r],[r],self.v.RAW_ENCODING)
 def test_qfq_volume_or_reserved_mismatch_rejected(self):
  r=self.row()
  for q in [{**r,'vol':'60110590'},{**r,'reserved':'0'},{**r,'amount':'99'}]:
   with self.assertRaises(ValueError):self.v.normalize_pair([r],[q],self.v.RAW_ENCODING)
 def test_g4_uint64_large_number_is_not_raw32_decoded(self):
  r=self.row(6011059197);r.pop('reserved');receipt=self.v.validate_g4(r)
  self.assertEqual(receipt['status'],'NUMERICALLY_VALIDATED');self.assertFalse(receipt['official_format_certified'])
  self.assertEqual(r['vol'],'6011059197')
 def test_g4_bad_vwap_and_unsafe_units_rejected(self):
  for r in [{**self.row(100),'amount':'1000000'},self.row(-1),self.row(1<<64),{**self.row(100),'vol':True}]:
   with self.assertRaises(ValueError):self.v.validate_g4(r)
 def test_raw_price_envelope_not_qfq_price(self):
  r=self.row();q={**r,'low':'1','high':'2'}
  raw,_,_=self.v.normalize_pair([r],[q],self.v.RAW_ENCODING);self.assertEqual(raw[0]['vol'],'6011059197')
 def test_g4_zero_volume_not_validated_as_liquid(self):
  with self.assertRaisesRegex(ValueError,'ZERO_VOLUME'):self.v.validate_g4(self.row(0))
if __name__=='__main__':unittest.main()
