from pathlib import Path
import json,subprocess,sys
HERE=Path(__file__).resolve().parent
PROOF=HERE/'.tmp/us-oversold-futu-prepared-r1/run/proof.json'
V9=HERE/'.tmp/v9-us-futu-r2'
HELPER=HERE/'serve_isolated_candidate_v7.py'

def args():
 plan=json.loads((V9/'operator-plan.json').read_text())
 return [sys.executable,str(HELPER),'--proof',str(PROOF),'--candidate-app-root',plan['candidate_api'],'--candidate-manifest-sha256',plan['api_manifest_sha256'],'--reviewed-source-receipt',str(HERE/'us-oversold-adapter-futu-r1.json'),'--check-only']

def test_exact_saved_product_and_candidate_four_source_check():
 result=subprocess.run(args(),capture_output=True,text=True)
 assert result.returncode==0,result.stderr
 value=json.loads(result.stdout);proof=json.loads(PROOF.read_text())
 assert value['product_sha256']==proof['product_sha256'] and value['run_id']==proof['run_id']
 assert value['model_calls']==0 and value['check_only'] and '/v9-us-futu-r2/' in value['candidate_app_root']

def test_wrong_manifest_and_old_four_source_rejected():
 command=args();command[command.index('--candidate-manifest-sha256')+1]='0'*64
 result=subprocess.run(command,capture_output=True,text=True)
 assert result.returncode!=0 and 'CANDIDATE_MANIFEST_IDENTITY_DRIFT' in result.stderr
 old=HERE/'.tmp/v8-scheduled-pause-r1/manager-workbench-20261013-v8-api/app'
 manifest=json.loads((old.parent/'release-manifest.json').read_text())
 import hashlib
 command=args();command[command.index('--candidate-app-root')+1]=str(old);command[command.index('--candidate-manifest-sha256')+1]=hashlib.sha256((old.parent/'release-manifest.json').read_bytes()).hexdigest()
 result=subprocess.run(command,capture_output=True,text=True)
 assert result.returncode!=0 and 'REVIEWED_CANDIDATE_SOURCE_DRIFT' in result.stderr

def test_formal_port_rejected_without_start():
 result=subprocess.run(args()+['--port','8873'],capture_output=True,text=True)
 assert result.returncode!=0 and 'TEMP_PORT_REQUIRED' in result.stderr
