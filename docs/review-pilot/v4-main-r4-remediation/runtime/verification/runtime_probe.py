"""Launcher-equivalent import and identity probe without starting the scheduler."""
import hashlib
import json
import os
from pathlib import Path
import sys
import sysconfig
import subprocess

from ops import research_storage_governance as governance
from ops import research_qfq_dependency_identity as identity
from ops import research_panel_qfq as owner
from ops.runtime_bytecode_policy import SOURCE_ONLY_PYCACHE_PREFIX, require_source_only_cache_policy


def main():
    root=Path(__file__).resolve().parent
    release=Path(os.environ["V4_APP_ROOT"]).resolve().parent
    expected_base_prefix=(release/"runtime/python/cpython-3.14.6").resolve()
    expected_stdlib=(expected_base_prefix/"lib/python3.14").resolve()
    assert Path(sys.executable).resolve().is_relative_to(release/"runtime")
    assert Path(sys.base_prefix).resolve()==expected_base_prefix
    assert Path(sysconfig.get_path("stdlib")).resolve()==expected_stdlib
    assert Path(owner.__file__).resolve()==release/"app/ops/research_panel_qfq.py"
    assert sys.flags.no_site==1 and sys.flags.dont_write_bytecode==1
    cache_policy=require_source_only_cache_policy()
    assert cache_policy and cache_policy["source_only_prefix"]==SOURCE_ONLY_PYCACHE_PREFIX
    env=os.environ
    assert env["V4_RUNTIME_ROOT"]==str(release/"runtime")
    site=release/"runtime/venvs/v4-mac/lib/python3.14/site-packages"
    import pytdx
    assert Path(pytdx.__file__).resolve().is_relative_to(site)
    assert governance.configured_policy() is not None
    kwargs=dict(driver_path=release/"app/ops/vendor/data_layer_daily_formula_increment_update_v1.py",
        formula_path=Path(env["V4_RESEARCH_PANEL_A_CANONICAL_FORMULA"]).resolve(),
        contract_csv=Path(env["V4_RESEARCH_PANEL_A_CONTRACT_CSV"]).resolve(),
        tdx_root=Path(env["V4_RESEARCH_PANEL_A_TDX_ROOT"]).resolve(),
        refresh_inputs=True,storage_layout="arrow_blocks_v1")
    data=Path(env["V4_RESEARCH_PANEL_A_DATA_ROOT"])
    manifest=identity.computation_dependencies(owner,kwargs,runtime_root=owner.input_path(data).parent)
    key=governance.qfq_invocation_key(owner,data,20261120,kwargs)
    from ops.research_qfq_task_continuity import qfq_admission_context
    admission=[]
    policy=governance.configured_policy()
    for target in (20261120,20261123):
        target_key=governance.qfq_invocation_key(owner,data,target,kwargs)
        try:
            scope=qfq_admission_context(owner,policy,data,Path(env["V4_RESEARCH_PANEL_A_RETURN_ROOT"]),target,target_key)
            state="PREFLIGHT_PASSED_CLAIM_NOT_ATTEMPTED"
        except governance.RetentionError as error:
            state=str(error)
        admission.append(dict(target=target,key=target_key,status=state,claim_begin_called=False))
    assert all(x["status"]=="QFQ_UNCLASSIFIED_LEGACY_RESERVATION" for x in admission)
    child_code=(
        "import json,os,sys,sysconfig,ops.research_panel_qfq as owner,pytdx;from pathlib import Path;"
        "from ops import research_storage_governance as child_governance;"
        "from ops.research_qfq_dependency_identity import computation_dependencies as child_dependencies;"
        "from ops.runtime_bytecode_policy import require_source_only_cache_policy;"
        "r=Path(sys.argv[1]);assert Path(sys.executable).resolve().is_relative_to(r/'runtime');"
        "assert Path(sys.base_prefix).resolve()==(r/'runtime/python/cpython-3.14.6').resolve();"
        "assert Path(sysconfig.get_path('stdlib')).resolve()==(r/'runtime/python/cpython-3.14.6/lib/python3.14').resolve();"
        "assert Path(owner.__file__).resolve()==r/'app/ops/research_panel_qfq.py';"
        "assert Path(pytdx.__file__).resolve().is_relative_to(r/'runtime/venvs/v4-mac/lib/python3.14/site-packages');"
        "assert sys.flags.no_site==0;assert sys.pycache_prefix=='/dev/null/v4-main-r4-source-only-pycache';"
        "assert sys.dont_write_bytecode;"
        "cache_policy=require_source_only_cache_policy();"
        "kwargs=dict(driver_path=r/'app/ops/vendor/data_layer_daily_formula_increment_update_v1.py',"
        "formula_path=Path(os.environ['V4_RESEARCH_PANEL_A_CANONICAL_FORMULA']).resolve(),"
        "contract_csv=Path(os.environ['V4_RESEARCH_PANEL_A_CONTRACT_CSV']).resolve(),"
        "tdx_root=Path(os.environ['V4_RESEARCH_PANEL_A_TDX_ROOT']).resolve(),"
        "refresh_inputs=True,storage_layout='arrow_blocks_v1');"
        "data=Path(os.environ['V4_RESEARCH_PANEL_A_DATA_ROOT']);"
        "manifest=child_dependencies(owner,kwargs,runtime_root=owner.input_path(data).parent);"
        "keys={str(day):child_governance.qfq_invocation_key(owner,data,day,kwargs) "
        "for day in (20261120,20261123)};"
        "print(json.dumps({'status':'PASS_DAEMON_CHILD_IMPORT_AND_QFQ_IDENTITY','no_site':sys.flags.no_site,"
        "'owner':str(Path(owner.__file__).resolve()),'pytdx':str(Path(pytdx.__file__).resolve()),"
        "'cache_policy':cache_policy,'keys':keys,'computation_manifest_sha256':child_governance.canonical(manifest),"
        "'base_prefix':str(Path(sys.base_prefix).resolve()),"
        "'stdlib':str(Path(sysconfig.get_path('stdlib')).resolve()),"
        "'environment':manifest['environment'],'source_roles':len(manifest['dependencies'])},sort_keys=True))"
    )
    child=subprocess.run([sys.executable,"-X",f"pycache_prefix={SOURCE_ONLY_PYCACHE_PREFIX}","-B","-c",child_code,str(release)],
        env={**os.environ,"PYTHONPYCACHEPREFIX":SOURCE_ONLY_PYCACHE_PREFIX,
             "PYTHONDONTWRITEBYTECODE":"1","V4_SOURCE_ONLY_PYCACHE_REQUIRED":"1"},
        capture_output=True,text=True,check=True)
    child_result=json.loads(child.stdout)
    out=dict(status="PASS_LAUNCHER_EQUIVALENT_NO_SITE_IMPORT",
        python=sys.version,executable=str(Path(sys.executable).resolve()),prefix=sys.prefix,base_prefix=sys.base_prefix,
        stdlib=str(Path(sysconfig.get_path("stdlib")).resolve()),
        pycache_prefix=sys.pycache_prefix,no_site=sys.flags.no_site,write_bytecode=False,
        owner_sha256=hashlib.sha256(Path(owner.__file__).read_bytes()).hexdigest(),
        selected_pytdx_file=str(Path(pytdx.__file__).resolve()),source_roles=len(manifest["dependencies"]),
        computation_manifest_sha256=governance.canonical(manifest),
        environment=manifest["environment"],qfq_operation_key=key,
        live_admission_readonly=admission,child_import=child_result,
        child_qfq_key_manifest=dict(release_root=str(release),no_site=child_result["no_site"],
                                   keys=child_result["keys"]),
        production_owner_called=False,registry_mutated=False)
    (root/"RUNTIME_PROBE_RECEIPT.json").write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n")
    (root/"COMPUTATION_DEPENDENCIES.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n")
    print(out["status"],len(manifest["dependencies"]),key)


if __name__=="__main__":
    main()
