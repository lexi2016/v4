from pathlib import Path
import importlib.util,os,sys,json,hashlib
module_path=Path(sys.argv[1]);probe=Path(sys.argv[2])
spec=importlib.util.spec_from_file_location("delivery_review_runner_fixed",module_path)
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
original=probe/"original";execution=probe/"execution";package=probe/"package";work=probe/"work";out=probe/"absolute_out"
for p in (original,execution,package,work,out):p.mkdir(exist_ok=True)
target=original/"sentinel.txt";target.write_bytes(b"original fixture bytes")
fd=os.open(original,os.O_RDONLY|os.O_DIRECTORY)
os.chdir(work);events=[];executed=set();module._install_guard((original,execution,package),events,executed)
checks={}
def rejected(name, operation):
 try:
  operation();checks[name]=False
 except PermissionError:
  checks[name]=True
rejected("absolute_source_write_blocked",lambda:target.write_bytes(b"bad absolute write"))
def relative_write():
 changed=os.open("sentinel.txt",os.O_WRONLY|os.O_TRUNC,dir_fd=fd)
 os.write(changed,b"bad dir_fd write");os.close(changed)
rejected("dir_fd_open_write_blocked",relative_write)
rejected("dir_fd_unlink_blocked",lambda:os.unlink("sentinel.txt",dir_fd=fd))
rejected("dir_fd_rename_blocked",lambda:os.rename("sentinel.txt",str(out/"moved.txt"),src_dir_fd=fd))
rejected("descriptor_chmod_blocked",lambda:os.fchmod(fd,0o700))
absolute_output=out/"allowed_fixture.json";absolute_output.write_text("absolute OUT fixture remains writable")
checks["absolute_output_write_allowed"]=absolute_output.read_text()=="absolute OUT fixture remains writable"
checks["original_fixture_bytes_preserved"]=target.read_bytes()==b"original fixture bytes"
os.close(fd)
print(json.dumps({"checks":checks,"events":events,"scope":"Python audit guard plus source hashes; not a general sandbox"},indent=2))
assert all(checks.values())
