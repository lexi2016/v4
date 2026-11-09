"""Validated readers for materialized V192 extensions, never calculations."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

FLAGS=dict(RESEARCH_ONLY=True,production_allowed=False,buy_gate_updated=False,orders_sent=False)


def checked(ref,root):
    path=Path(ref['path']);root=Path(root).resolve(strict=True)
    if not path.is_absolute() or path.is_symlink() or path.resolve(strict=True)!=path or not path.is_relative_to(root):
        raise ValueError('V192_ASSET_PATH_CONFLICT')
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=ref['sha256']:raise ValueError('V192_ASSET_SHA_CONFLICT')
    return json.loads(raw)


def load(source,product,model_sha256):
    index=json.loads((source._a_product_root()/'index.json').read_bytes())
    descriptor=index.get('v192_assets',{}).get(product['data_date'])
    if not descriptor or not descriptor.get('module'):return None
    if (descriptor.get('numeric_manifest')!=product['manifest'] or descriptor.get('source_generation')!=product['source_generation']
            or descriptor.get('input_sha256')!=product['source_identity']['input_sha256']
            or descriptor.get('model_artifact_sha256')!=model_sha256):return None
    module=source._a_product_reference(descriptor['module'])
    if (module.get('schema')!='V4_WORKBENCH_V192_ASSETS_V1' or module.get('numeric_manifest')!=product['manifest']
            or module.get('source_generation')!=product['source_generation'] or module.get('data_date')!=product['data_date']
            or module.get('input_sha256')!=product['source_identity']['input_sha256']
            or module.get('selector_sha256')!=product['source_identity']['selector_artifact_sha256']
            or module.get('model_source',{}).get('artifact_sha256')!=model_sha256
            or module.get('historical_PIT') is not False or any(module.get(k)!=v for k,v in FLAGS.items())):
        raise ValueError('V192_ASSET_MODULE_IDENTITY_CONFLICT')
    native={row['symbol'] for row in product['rows']}
    digest=hashlib.sha256(json.dumps(sorted(native),sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest()
    scope=set(module.get('scope_symbols',[]));complete=set(module.get('completed_symbols',[]))
    if (module.get('canonical_symbols_sha256')!=digest or scope&native or not complete<=scope
            or not scope<=set(module.get('model_symbols',[]))):raise ValueError('V192_ASSET_SCOPE_CONFLICT')
    root=Path(module['artifact_root'])
    if not root.is_absolute() or root.is_symlink() or root.resolve(strict=True)!=root:raise ValueError('V192_ASSET_ROOT_CONFLICT')
    manifest=checked(module['charts']['manifest'],root)
    receipt=checked(module['charts']['receipt'],root)
    if (not complete<=set(manifest.get('samples',{})) or any(manifest.get(k)!=v or receipt.get(k)!=v for k,v in FLAGS.items())):
        raise ValueError('V192_ASSET_CHART_COMPLETION_CONFLICT')
    return dict(module=module,descriptor=descriptor,manifest=manifest,receipt=receipt)


def chart(source,native,bound,symbol,*,kind=None,digest=None):
    module=bound['module'];root=Path(module['artifact_root'])
    if symbol not in module['completed_symbols']:raise KeyError('V192_SYMBOL_ASSETS_NOT_MATERIALIZED')
    scope_manifest=checked(module['scope_manifest'],root);product=checked(module['scope_product'],root)
    if (scope_manifest.get('artifact')!=module['scope_product'] or product.get('scope_role')!='V192_EXISTING_SYMBOL_DERIVED'
            or product.get('source_numeric_manifest')!=native['manifest']
            or product.get('source_model_artifact_sha256')!=module['model_source']['artifact_sha256']
            or product.get('source_identity')!=native['source_identity']
            or set(product.get('row_refs',{}))!=set(module['scope_symbols'])
            or any(product['row_refs'][s]!=native.get('row_refs',{}).get(s) for s in module['scope_symbols'])
            or {row['symbol'] for row in product['rows']}!=set(module['scope_symbols'])):
        raise ValueError('V192_DERIVED_SCOPE_SOURCE_CONFLICT')
    product={**product,'manifest':module['scope_manifest'],'artifact':module['scope_product']}
    binding=dict(artifact_root=str(root),manifest=module['charts']['manifest'],receipt=module['charts']['receipt'])
    # All 51/22, retained prefix, source, config, byte and renderer checks stay
    # in the already accepted original-chart reader.
    value=source._read_original_chart_product(product,symbol,generation=native['source_generation'],
        input_sha256=native['source_identity']['input_sha256'],asset=kind,asset_sha256=digest,binding_override=binding)
    return {**value,'product_manifest':native['manifest'],'product_artifact':native['artifact'],
        'derived_scope_manifest':module['scope_manifest'],'scope_role':'V192_EXISTING_SYMBOL_DERIVED',
        'model_artifact_sha256':module['model_source']['artifact_sha256'],'selector_sha256':module['selector_sha256']}
