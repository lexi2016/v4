"""Publish one real auto read to new private module roots. No refresh or capture."""
import argparse, hashlib, json
from pathlib import Path
from v5_shadow.manager_plan import publish_workspace_read


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request', required=True, type=Path)
    parser.add_argument('--expected-run', required=True)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--frontend-root', required=True, type=Path)
    parser.add_argument('--release-id', required=True)
    args = parser.parse_args()
    root = args.out.absolute()
    if root.exists():
        raise ValueError('NEW_PRIVATE_PUBLICATION_ROOT_REQUIRED')
    request = json.loads(args.request.read_bytes())
    if request['action'] != 'read' or request['view'] != 'auto':
        raise ValueError('ACTUAL_AUTO_READ_REQUIRED')
    frontend = args.frontend_root.resolve(strict=True)
    manifest = {str(p.relative_to(frontend)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in frontend.rglob('*') if p.is_file()}
    if 'index.html' not in manifest:
        raise ValueError('BUILT_FRONTEND_REQUIRED')
    root.mkdir(parents=True)
    configs = {}
    for module, routes in [('manager', ['/api/v4/manager/research/workspace']),
                           ('announcement', ['/api/v4/manager/research/announcements',
                            '/api/v4/manager/research/announcements/analysis',
                            '/api/v4/manager/research/announcements/selection'])]:
        data = root / module
        data.mkdir()
        (data / '.v5-module-root').write_text('v5.module-root.v1:' + module + '\n')
        configs[module] = dict(schema_version='v5.module_api.v1', module_id=module,
                              release_id=args.release_id, data_root=str(data), routes=routes)
        (root / (module + '.json')).write_text(json.dumps(configs[module], indent=2))
    result = publish_workspace_read(request, configs['manager'], expected_generation=None,
                                    expected_run_id=args.expected_run)
    plan = result['result']['payload']['plan_product']
    gateway = dict(schema_version='v5.api_gateway.v1',
                   modules={m: dict(port=18897+i, timeout_seconds=15, max_inflight=4,
                                    release_id=args.release_id) for i, m in enumerate(configs)},
                   routes=[dict(path=p, module_id=m, methods=['GET'])
                           for m, c in configs.items() for p in c['routes']])
    (root/'gateway.json').write_text(json.dumps(gateway, indent=2))
    (root/'frontend.json').write_text(json.dumps(manifest, indent=2))
    (root/'publication.json').write_text(json.dumps(result['publication'], indent=2))
    print(json.dumps(dict(publication=result['publication'], plan_product=plan), indent=2))

if __name__ == '__main__':
    main()
