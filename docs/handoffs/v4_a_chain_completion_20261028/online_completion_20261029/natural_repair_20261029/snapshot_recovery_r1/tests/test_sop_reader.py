from pathlib import Path
import hashlib,importlib.util,sys
import pytest
HERE=Path(__file__).resolve().parents[1]
sys.path.insert(0,'/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/v4-daily-numeric283-20261029-r2-api/app')
spec=importlib.util.spec_from_file_location('sop_candidate',HERE/'sources/api/infrastructure/operations_sop_reader.py');R=importlib.util.module_from_spec(spec);spec.loader.exec_module(R)
def test_fixed_documents_realtime_sha_no_path_or_symlink_or_oversize(tmp_path,monkeypatch):
 monkeypatch.setattr(R,'CANONICAL_ROOT',tmp_path)
 for doc,(_,relative) in R.DOCUMENTS.items():
  p=tmp_path/relative;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('# SOP\n<script>readonly</script>\n',encoding='utf8')
  a=R.read_sop(doc);assert a['content']==p.read_text() and a['sha256']==hashlib.sha256(p.read_bytes()).hexdigest() and a['write_performed'] is False
  p.write_text('# updated',encoding='utf8');b=R.read_sop(doc);assert a['sha256']!=b['sha256']
 for unknown in ('../../etc/passwd','file:///etc/passwd','docs/SOP.md','no-such'):
  with pytest.raises(KeyError):R.read_sop(unknown)
 p=tmp_path/'docs/SOP.md';p.unlink();p.symlink_to(tmp_path/'docs/operations/STAGE_SELECTION_SOP.md')
 with pytest.raises(ValueError,match='ALIAS'):R.read_sop('overview')
 p.unlink();p.write_bytes(b'x'*(512*1024+1))
 with pytest.raises((ValueError,OSError)):R.read_sop('overview')
