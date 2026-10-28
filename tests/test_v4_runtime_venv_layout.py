"""Preserve the frozen interpreter link layout; never invoke a real producer."""
import hashlib
from pathlib import Path
import pytest
from ops import install_v4_runtime_closure as runtime


@pytest.mark.parametrize('linked,expected',[(True,'--symlinks'),(False,'--copies')])
def test_install_preserves_source_interpreter_layout(tmp_path,monkeypatch,linked,expected):
    owned=tmp_path/'v4';owned.mkdir();source_base=tmp_path/'original-base';(source_base/'bin').mkdir(parents=True)
    binary=source_base/'bin/python3.13';binary.write_bytes(b'frozen binary fixture')
    source=tmp_path/'original-venv/bin/python';source.parent.mkdir(parents=True)
    if linked:source.symlink_to(binary)
    else:source.write_bytes(binary.read_bytes())
    target=owned/'venv';base=owned/'base';monkeypatch.setattr(runtime,'V4_RUNTIME',owned)
    monkeypatch.setattr(runtime,'_probe',lambda _:dict(version_info=[3,13,12],packages=[],base_prefix=str(source_base)))
    def copy(s,t):
        (t/'bin').mkdir(parents=True);(t/'bin/python3.13').write_bytes(binary.read_bytes())
    monkeypatch.setattr(runtime,'_copy_exact',copy)
    calls=[]
    class StoppedBeforeExecution(Exception):pass
    def capture(command,**kwargs):calls.append(command);raise StoppedBeforeExecution
    monkeypatch.setattr(runtime.subprocess,'run',capture)
    item=dict(source_executable=str(source),target_venv=str(target),target_base=str(base),binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),version_info=[3,13,12],packages=[],component='fixture')
    with pytest.raises(StoppedBeforeExecution):runtime.install(item,apply=True)
    assert len(calls)==1 and expected in calls[0]
    assert calls[0][0]==str(base/'bin/python3.13')
    assert '--without-pip' in calls[0]


def test_link_layout_rejects_legacy_base_before_creation(tmp_path,monkeypatch):
    owned=tmp_path/'v4';owned.mkdir();old=tmp_path/'legacy/python';old.parent.mkdir();old.write_bytes(b'old')
    monkeypatch.setattr(runtime,'V4_RUNTIME',owned)
    monkeypatch.setattr(runtime.subprocess,'run',lambda *a,**k:pytest.fail('must reject before creation'))
    with pytest.raises(ValueError,match='RUNTIME_VENV_BASE_OUTSIDE_V4'):
        runtime._create_venv(old,old,owned/'venv')


def test_generated_alias_cannot_point_to_original_runtime(tmp_path,monkeypatch):
    owned=tmp_path/'v4';owned.mkdir();base=owned/'base/bin/python3.13';base.parent.mkdir(parents=True);base.write_bytes(b'frozen')
    old=tmp_path/'legacy/python';old.parent.mkdir();old.write_bytes(b'frozen');source=tmp_path/'source-python';source.symlink_to(old)
    target=owned/'venv';monkeypatch.setattr(runtime,'V4_RUNTIME',owned)
    def create(*a,**k):
        (target/'bin').mkdir(parents=True);(target/'bin/python').symlink_to(old)
    monkeypatch.setattr(runtime.subprocess,'run',create)
    with pytest.raises(ValueError,match='RUNTIME_VENV_LINK_OUTSIDE_COPIED_BASE'):
        runtime._create_venv(source,base,target)
