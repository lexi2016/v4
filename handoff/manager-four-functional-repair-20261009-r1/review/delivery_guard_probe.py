from pathlib import Path
import importlib.util,os,sys,json
module_path=Path(sys.argv[1]);probe=Path(sys.argv[2])
spec=importlib.util.spec_from_file_location("delivery_review_runner",module_path)
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
original=probe/"original";execution=probe/"execution";package=probe/"package";work=probe/"work"
for p in (original,execution,package,work):p.mkdir(exist_ok=True)
target=original/"sentinel.txt";target.write_bytes(b"original fixture bytes")
fd=os.open(original,os.O_RDONLY|os.O_DIRECTORY)
os.chdir(work);events=[];executed=set();module._install_guard((original,execution,package),events,executed)
try:
 target.write_bytes(b"blocked absolute fixture mutation")
 absolute_blocked=False
except PermissionError:
 absolute_blocked=True
try:
 changed=os.open("sentinel.txt",os.O_WRONLY|os.O_TRUNC,dir_fd=fd)
 os.write(changed,b"dir_fd fixture mutation")
 os.close(changed)
 dir_fd_blocked=False
except PermissionError:
 dir_fd_blocked=True
os.close(fd)
print(json.dumps({"absolute_write_blocked":absolute_blocked,"dir_fd_write_blocked":dir_fd_blocked,"final_fixture_bytes":target.read_text(),"events":events},indent=2))
