"""Restore the exact CPU archive without executing or deserializing its contents."""
from pathlib import Path, PurePosixPath
import hashlib,json,stat,zipfile

SOURCE=Path('/Users/lexi/Downloads/P5_9_CPU_RETRAINING_PACKAGE.zip')
EXPECTED='fdd02f34f49625df4266d98ca71af97588584533d847255b79b81657a764347f'
OUT=Path('/Users/lexi/Desktop/学习/agents调试/Z哥方法论/phase59_mac_continue_20261105')
DEST=OUT/'cpu_original'
data=SOURCE.read_bytes();actual=hashlib.sha256(data).hexdigest()
assert actual==EXPECTED and len(data)==6235626, 'CPU_ARCHIVE_IDENTITY_MISMATCH'
assert not DEST.exists(), 'ORIGINAL_RESTORE_ALREADY_EXISTS_DO_NOT_OVERWRITE'
DEST.mkdir(parents=True);files=[]
with zipfile.ZipFile(SOURCE) as z:
    assert len(z.infolist())==16 and sum(i.file_size for i in z.infolist())<100_000_000
    for info in z.infolist():
        name=PurePosixPath(info.filename);mode=(info.external_attr>>16)&0xffff
        assert not name.is_absolute() and '..' not in name.parts and not stat.S_ISLNK(mode) and not info.is_dir(), 'UNSAFE_ARCHIVE_MEMBER'
        b=z.read(info);assert len(b)==info.file_size
        target=DEST.joinpath(*name.parts);target.parent.mkdir(parents=True,exist_ok=True)
        with target.open('xb') as f:f.write(b)
        files.append({'member':str(name),'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()})
receipt={'source':str(SOURCE),'archive_sha256':actual,'archive_bytes':len(data),'restored_root':str(DEST),
    'entry_count':len(files),'members':files,'zip_read_and_crc':'PASS','pickle_deserialization':'NOT_RUN','archive_code_execution':'NOT_RUN'}
(OUT/'RESTORE_RECEIPT.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'archive_sha256':actual,'members':len(files),'restored_root':str(DEST)},ensure_ascii=False))
