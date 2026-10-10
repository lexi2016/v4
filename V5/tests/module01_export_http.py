"""Export actual HTTP DTO bytes from the explicitly synthetic original owner.

This driver reuses an already saved synthetic run, publishes one ordinary auto
read into a fresh private root, and closes its ephemeral loopback servers.
It never accepts the real Mac 392 fixture as synthetic evidence.
"""
import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import threading
from urllib.parse import urlencode
from urllib.request import urlopen

from v5_shadow.api_gateway import create_gateway
from v5_shadow.digests import canonical_bytes
from v5_shadow.manager_plan import ROUTE, publish_workspace_read
from v5_shadow.module_api import create_module_server


def snapshot(roots):
    return {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
            for root in roots for path in root.rglob('*') if path.is_file()}


def export_http(fixture_path, expected_run, output):
    fixture = json.loads(Path(fixture_path).read_bytes())
    provenance = fixture['provenance']
    if (provenance.get('fixture_kind') != 'SYNTHETIC_ORIGINAL_OWNER_INPUTS'
            or provenance.get('real_392_reused') is not False
            or sum(provenance.get('decisions', {}).values()) != 4):
        raise ValueError('MODULE01_EXPLICIT_SYNTHETIC_FIXTURE_REQUIRED')
    output = Path(output).absolute()
    output.mkdir(parents=True, exist_ok=False)
    request = copy.deepcopy(fixture['request'])
    request.update(action='read', view='auto', now=datetime.now(timezone.utc).isoformat())
    module_root = output / 'module'
    module_root.mkdir()
    (module_root / '.v5-module-root').write_text('v5.module-root.v1:manager\n')
    config = dict(schema_version='v5.module_api.v1', module_id='manager', release_id='module01-synthetic-http',
                  data_root=str(module_root), routes=[ROUTE])
    published = publish_workspace_read(request, config, expected_generation=None, expected_run_id=expected_run)
    module = create_module_server(config)
    gateway_config = dict(schema_version='v5.api_gateway.v1',
        modules={'manager': dict(port=module.server_port, timeout_seconds=5,
                                 max_inflight=2, release_id=config['release_id'])},
        routes=[dict(path=ROUTE, module_id='manager', methods=['GET'])])
    gateway = create_gateway(gateway_config)
    servers = [module, gateway]
    for server in servers:
        threading.Thread(target=server.serve_forever, daemon=True).start()
    roots = [Path(binding['root']) for binding in request['inputs'].values()]
    roots += [Path(request['manager_output_root']), module_root]
    before = snapshot(roots)
    responses = []
    try:
        query = urlencode({'date': request['target_date'], 'view': request['view']})
        for name, server in zip(('module', 'gateway'), servers, strict=True):
            url = 'http://127.0.0.1:' + str(server.server_port) + ROUTE + '?' + query
            with urlopen(url, timeout=10) as response:
                raw = response.read()
                body = json.loads(raw)
                headers = dict(response.headers)
                if (response.status != 200 or headers.get('X-V5-Workspace-Access') != 'READ_ONLY'
                        or body != published['result']['payload']):
                    raise AssertionError('MODULE01_HTTP_RESPONSE_MISMATCH')
                responses.append(dict(surface=name, method='GET', url=url, status=response.status,
                    headers=headers, body=body, body_sha256=hashlib.sha256(raw).hexdigest()))
        if snapshot(roots) != before:
            raise AssertionError('MODULE01_HTTP_GET_CHANGED_SOURCE_OR_PRODUCT_BYTES')
    finally:
        for server in reversed(servers):
            server.shutdown()
            server.server_close()
    receipt = dict(schema_version='v5.module01.synthetic_http_receipt.v1',
        fixture_kind=provenance['fixture_kind'], real_392_reused=False, provenance=provenance,
        request={'target_date': request['target_date'], 'view': request['view']},
        manager_run=published['result']['payload']['plan_product']['run_id'],
        manager_plan_sha256=published['result']['payload']['plan_product']['sha256'],
        manager_readback=published['result']['readback'],
        implementation_identity=published['result']['implementation_identity'],
        publication=published['publication'], responses=responses,
        http_get_before_after_bytes_equal=True, local_servers_closed=True,
        natural_verified=False, mac_business_acceptance='NOT_RUN')
    (output / 'http-receipt.json').write_bytes(canonical_bytes(receipt))
    print(json.dumps(dict(receipt=str(output / 'http-receipt.json'), run_id=receipt['manager_run'],
        plan_sha256=receipt['manager_plan_sha256'], http_surfaces=[r['surface'] for r in responses],
        http_get_before_after_bytes_equal=True, real_392_reused=False)))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture', required=True, type=Path)
    parser.add_argument('--expected-run', required=True)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    export_http(args.fixture, args.expected_run, args.out)
