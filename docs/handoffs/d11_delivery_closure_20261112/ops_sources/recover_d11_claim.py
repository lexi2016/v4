"""Single frozen DEAD claim recovery through original Claim.begin/finish.

Default is read-only preflight. --execute is for controller after combined review
and installation; it changes registry metadata only, never invokes a producer.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import sys

HERE = Path(__file__).resolve().parent


def read_ref(g, ref):
    path = g.safe_path(ref['path'])
    before = g.stamp(path)
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != ref['sha256'] or g.stamp(path) != before:
        raise g.RetentionError('RECOVERY_EVIDENCE_DRIFT:' + str(path))
    return json.loads(raw)


def validate(g, plan, registry):
    result = read_ref(g, plan['full_result'])
    if result.get('storage_governance') != dict(status='COMMITTED_REGISTRY_RECORDING_BLOCKED',
                                               error='RESULT_METADATA_BUDGET'):
        raise g.RetentionError('RECOVERY_ORIGINAL_FAILURE_REQUIRED')
    summary = g.daily_derivatives_registry_summary(result)
    if summary != plan['summary']:
        raise g.RetentionError('RECOVERY_SUMMARY_DRIFT')
    manifest = read_ref(g, plan['numeric_manifest'])
    product = read_ref(g, plan['numeric_product'])
    if (manifest.get('artifact') != plan['numeric_product']
            or manifest.get('schema_version') != 'v4.a_share.daily_product_manifest.v1'
            or product.get('schema_version') != 'v4.a_share.daily_product.v1'):
        raise g.RetentionError('RECOVERY_FORMAL_MANIFEST_DRIFT')
    for value in (result, manifest, product):
        if (value.get('data_date') != plan['data_date']
                or value.get('source_generation') != plan['source_generation']
                or any(value.get(key) != expected for key, expected in plan['safety'].items())):
            raise g.RetentionError('RECOVERY_DATE_GENERATION_OR_SAFETY_DRIFT')
    if (product.get('unique_count') != 426 or len(product.get('rows', [])) != 426
            or len({row['symbol'] for row in product['rows']}) != 426
            or summary['history']['candidate_count'] != 426
            or summary['complete_owner_receipt'] != plan['attempt']
            or summary['f10']['complete_owner_receipt'] != plan['f10_receipt']
            or summary['top200']['artifact'] != plan['top200_artifact']):
        raise g.RetentionError('RECOVERY_FORMAL_SCOPE_OR_COMPLETION_DRIFT')
    # The numeric product remains the dated formal publication, independent of
    # mutable Top200-before CAS hashes and later F10 index updates.
    index = json.loads(g.safe_path(Path(plan['directory']) / 'index.json').read_bytes())
    if (index['dates'].get(plan['data_date']) != plan['numeric_manifest']
            or index['attempts'].get(plan['data_date']) != plan['attempt']
            or index['top200'].get(plan['data_date']) != plan['top200_artifact']):
        raise g.RetentionError('RECOVERY_CURRENT_COMPLETION_BINDING_DRIFT')
    row = registry.read()['tasks'].get(plan['key'])
    if (not row or g.canonical(row) != plan['old_row_sha256']
            or row.get('state') != 'RUNNING' or row.get('token') != plan['old_token']
            or row.get('owner') != plan['old_owner'] or g.owner_state(row['owner']) != 'DEAD'
            or row.get('directory') != plan['directory']):
        raise g.RetentionError('RECOVERY_CAS_OR_DEAD_OWNER_FAILED')
    return result, summary, row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app-root', required=True)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--expected-main-manifest-sha256')
    args = parser.parse_args()
    plan = json.loads((HERE / 'RECOVERY_PLAN.json').read_bytes())
    app = Path(args.app_root).resolve()
    sys.path.insert(0, str(app))
    from ops import research_storage_governance as g
    if (Path(g.__file__).resolve() != app / 'ops/research_storage_governance.py'
            or g.digest(Path(g.__file__)) != plan['patched_governance_sha256']):
        raise g.RetentionError('RECOVERY_REVIEWED_SOURCE_REQUIRED')
    if args.execute:
        if not args.expected_main_manifest_sha256:
            raise g.RetentionError('RECOVERY_EXPLICIT_REVIEWED_MAIN_MANIFEST_REQUIRED')
        plist = plistlib.loads(Path.home().joinpath('Library/LaunchAgents/com.lexi.v4.scheduler.plist').read_bytes())
        env = plist.get('EnvironmentVariables', {})
        if (env.get('V4_APP_ROOT') != str(app)
                or env.get('V4_RELEASE_MANIFEST_SHA256') != args.expected_main_manifest_sha256):
            raise g.RetentionError('RECOVERY_INSTALLED_MAIN_IDENTITY_DRIFT')
        manifest_path = Path(env['V4_RELEASE_MANIFEST_PATH'])
        if g.digest(manifest_path) != args.expected_main_manifest_sha256:
            raise g.RetentionError('RECOVERY_INSTALLED_MAIN_MANIFEST_DRIFT')
        for key in ('V4_RESEARCH_RETENTION_POLICY', 'V4_RESEARCH_RETENTION_POLICY_SHA256'):
            os.environ[key] = env[key]
        policy = g.configured_policy()
    else:
        # Plan-only source worktree is not a deployed Main. Load the frozen
        # current policy for read checks without pretending app-root acceptance.
        from ops.research_storage_retention import load_policy
        policy = load_policy(Path(plan['preparation_policy']['path']),
                             expected_sha256=plan['preparation_policy']['sha256'])
    config = g.configuration(policy)
    if (policy['data_root'] != plan['policy_data_root']
            or config['registry_root'] != plan['registry_root']
            or any(config.get(key) != value for key, value in plan['unchanged_limits'].items())):
        raise g.RetentionError('RECOVERY_POLICY_OR_LIMIT_DRIFT')
    registry = g.Registry(config, policy['data_root'])
    if not args.execute:
        _, summary, row = validate(g, plan, registry)
        print(json.dumps(dict(status='PREPARED_NOT_EXECUTED', owner_state=g.owner_state(row['owner']),
                              key=plan['key'], summary_bytes=len(json.dumps(summary))), sort_keys=True))
        return
    # Existing pool writer serializes normal owners/control; the original
    # transaction CAS verifies the exact dead row immediately before begin.
    with registry.writer():
        with registry.transaction():
            _, summary, before = validate(g, plan, registry)
            g.atomic_json(HERE / 'RECOVERY_BEFORE.json', before)
        claim = g.Claim(registry, plan['key'], plan['directory'], plan['predicted_bytes'],
                        category=plan['category'], category_used=before['category_baseline_bytes'])
        try:
            claim.begin(reuse_ready=False)  # normal admission, retry/space gates intact
            g.atomic_json(HERE / 'RECOVERY_BEGIN.json', registry.read()['tasks'][plan['key']])
            # Recheck immutable references after normal begin; no computation.
            full = read_ref(g, plan['full_result'])
            if g.daily_derivatives_registry_summary(full) != summary:
                raise g.RetentionError('RECOVERY_COMPLETION_CHANGED_AFTER_BEGIN')
            for key in ('numeric_manifest', 'numeric_product'):
                read_ref(g, plan[key])  # begin may inventory a large existing root
            index = json.loads(g.safe_path(Path(plan['directory']) / 'index.json').read_bytes())
            if (index['dates'].get(plan['data_date']) != plan['numeric_manifest']
                    or index['attempts'].get(plan['data_date']) != plan['attempt']
                    or index['top200'].get(plan['data_date']) != plan['top200_artifact']):
                raise g.RetentionError('RECOVERY_PUBLICATION_CHANGED_AFTER_BEGIN')
            refs = [plan[key]['path'] for key in
                    ('attempt', 'f10_receipt', 'top200_artifact', 'numeric_manifest', 'numeric_product')]
            claim.finish(summary, [Path(plan['directory']) / 'index.json', *refs])
        except Exception as error:
            row = registry.read()['tasks'].get(plan['key'], {})
            if row.get('token') == claim.token and not claim.finalized:
                claim.finish(error=error)
            g.atomic_json(HERE / 'RECOVERY_FAILURE.json', dict(error=str(error),
                          row=registry.read()['tasks'].get(plan['key']),
                          original_error='RESULT_METADATA_BUDGET'))
            raise
        after = registry.read()['tasks'][plan['key']]
        if after['state'] != 'READY' or after['result'] != summary:
            raise g.RetentionError('RECOVERY_FINAL_READBACK_FAILED')
        g.atomic_json(HERE / 'RECOVERY_AFTER.json', after)
        print(json.dumps(dict(status='REGISTRY_RECORDING_RECOVERED', key=plan['key'],
                              original_error='RESULT_METADATA_BUDGET',
                              business_status=summary['status'], history_status=summary['history_status'],
                              f10_status=summary['f10']['status']), sort_keys=True))


if __name__ == '__main__':
    main()
