from pathlib import Path
import importlib.util,os,sys,json
module_path=Path(sys.argv[1]);probe=Path(sys.argv[2])
spec=importlib.util.spec_from_file_location("delivery_finite_contract",module_path)
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
verifier=module._verifier()
original=probe/"original";execution=probe/"execution";package=probe/"package";work=probe/"work";out=probe/"absolute_out"
for p in (original,execution,package,work,out):p.mkdir(exist_ok=True)
target=original/"sentinel.txt";target.write_bytes(b"original fixture bytes")
before=module._snapshot(original,verifier)
fd=os.open(original,os.O_RDONLY|os.O_DIRECTORY)
os.chdir(work);events=[];executed=set();module._install_guard((original,execution,package),events,executed)
try:
 target.write_bytes(b"blocked explicit absolute source write")
 absolute_source_blocked=False
except PermissionError:
 absolute_source_blocked=True
absolute_output=out/"allowed_fixture.json";absolute_output.write_text("absolute OUT writes work")
try:
 changed=os.open("sentinel.txt",os.O_WRONLY|os.O_TRUNC,dir_fd=fd)
 os.write(changed,b"intentionally changed synthetic fixture")
 os.close(changed)
 descriptor_operation_allowed=True
except PermissionError:
 descriptor_operation_allowed=False
os.close(fd)
after=module._snapshot(original,verifier)
differences=module._differences(before,after)
result={"absolute_source_write_blocked":absolute_source_blocked,"absolute_output_write_allowed":absolute_output.read_text()=="absolute OUT writes work","descriptor_operation_allowed_as_declared":descriptor_operation_allowed,"content_drift_detected_by_source_postcheck":module._changed(differences),"differences":differences,"guard_events":events,"meaning":"Intentional synthetic descriptor mutation demonstrates limited prevention and content drift detection; not a general security sandbox."}
print(json.dumps(result,indent=2))
assert absolute_source_blocked and result["absolute_output_write_allowed"] and descriptor_operation_allowed
assert differences=={"missing":[],"added":[],"changed":["sentinel.txt"]}
