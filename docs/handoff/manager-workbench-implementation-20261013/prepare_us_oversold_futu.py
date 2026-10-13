"""Bind an already captured single Futu response to the complete HK master run.
No quote request, model or formal write. The existing runner executes two lanes.
"""
from pathlib import Path
import argparse,hashlib,json
HERE=Path(__file__).resolve().parent
sha=lambda b:hashlib.sha256(b).hexdigest()
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--base-config',required=True,type=Path);p.add_argument('--response-root',required=True,type=Path);p.add_argument('--output',required=True,type=Path);a=p.parse_args()
 root=a.response_root.resolve(strict=True);out=a.output.resolve()
 if not out.is_relative_to((HERE/'.tmp').resolve()) or out.exists():raise ValueError('NEW_HANDOFF_OUTPUT_REQUIRED')
 receipt=json.loads((root/'receipt.json').read_text());raw=root/'raw.json'
 if receipt.get('source')!='FUTU' or receipt.get('code')!='HK.00001' or sha(raw.read_bytes())!=receipt.get('raw_sha256') or receipt.get('row_count')!=61:raise ValueError('EXACT_PROVEN_SINGLE_RESPONSE_REQUIRED')
 cfg=json.loads(a.base_config.read_text());out.mkdir(parents=True)
 binding=dict(source_local_path=str(root),symbol=receipt['code'],raw_relative='raw.json',raw_sha256=sha(raw.read_bytes()),receipt_relative='receipt.json',receipt_sha256=sha((root/'receipt.json').read_bytes()))
 cfg.setdefault('source_bindings',{}).setdefault('hk_panel',{}).setdefault('20261012',{})['futu_history']=[binding]
 cfg.update(capture_enabled=False,capture_lease_token=None,scheduled_lanes=['US_MAPPING','OVERSOLD'])
 path=out/'base-config.json';path.write_text(json.dumps(cfg,indent=2)+'\n')
 result=dict(status='PREPARED_NOT_RUN',base_config=str(path),config_sha256=sha(path.read_bytes()),single_response=binding,
    target_date='20261013',full_security_master_scope_preserved=True,capture_calls=0,model_calls=0,
    run_command="'/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python' '"+str(HERE/'run_us_oversold.py')+"' --base-config '"+str(path)+"' --output '"+str(out/'run')+"'")
 (out/'receipt.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
if __name__=='__main__':main()
