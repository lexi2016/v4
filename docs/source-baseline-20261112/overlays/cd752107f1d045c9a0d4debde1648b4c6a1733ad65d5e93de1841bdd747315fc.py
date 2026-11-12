"""Loopback-only OpenViking adapter. No cloud fallback, planner or reranker."""
from __future__ import annotations
import importlib.util
import json
import os
import sys
from pathlib import Path
import httpx
from infrastructure.report_evidence_index import NAMESPACE, MODEL_REVISION

_TOKENIZERS = {}

class LocalNative:
    def __init__(self, bridge: str | Path):
        path = Path(bridge) / 'runtime.py'
        spec = importlib.util.spec_from_file_location('_v4_report_local_runtime', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.runtime = module

    def guard(self):
        status = self.runtime.require_local_only()
        if status['revision'] != MODEL_REVISION or self.runtime.URL != 'http://127.0.0.1:1933':
            raise RuntimeError('LOCAL_MODEL_OR_ENDPOINT_MISMATCH')
        return status

    def credentials(self):
        self.guard()
        return json.loads((self.runtime.ART / 'private/client.local.json').read_text())

    async def token_count(self, text: str) -> int:
        """Exact pinned BGE-M3 token count from the same tokenizer used for the acceptance verifier."""
        # Retrieval runs under the bridge venv with the pinned tokenizers package; environments
        # without it fail closed instead of declaring a bound the 1934 HF tokenizer cannot prove.
        try:
            manifest = os.environ.get('V4_REPORT_LOCAL_MODEL_MANIFEST')
            path = Path(manifest) if manifest else self.runtime.ART / 'local_model_manifest.json'
            model_dir = Path(json.loads(path.read_text())['model_dir'])
            tokenizer_path = (model_dir / 'tokenizer.json').resolve()
            if not tokenizer_path.is_file(): raise ValueError('TOKENIZER_MISSING')
            tokenizer = _TOKENIZERS.get(str(tokenizer_path))
            if tokenizer is None:
                from infrastructure.report_evidence_index import BgeTokenizer
                tokenizer = BgeTokenizer(model_dir); _TOKENIZERS[str(tokenizer_path)] = tokenizer
            return tokenizer.count(text)
        except Exception as error:
            raise ValueError('TOKEN_COUNT_UNAVAILABLE') from error

    async def find(self, query: str, target_uris: list[str], limit: int = 50):
        if not target_uris:
            return []
        if any(not u.startswith(NAMESPACE + '/') or '..' in u.split('/') or any(c in u for c in '%?#\\') for u in target_uris):
            raise ValueError('REPORT_NAMESPACE_SCOPE_REQUIRED')
        c = self.credentials()
        # HTTP is the SDK's native find equivalent: options score_threshold/filter
        # map to these actual FindRequest fields. No global top-k/postfilter.
        async with httpx.AsyncClient(trust_env=False, follow_redirects=False, timeout=30) as client:
            response = await client.post(self.runtime.URL + '/api/v1/search/find',
                headers={'X-Api-Key': c['api_key'], 'X-OpenViking-Account': c['account'], 'X-OpenViking-User': c['user']},
                json=dict(query=query, target_uri=target_uris, limit=limit,
                          score_threshold=0.75, filter=None, level=[2], context_type='resource', read_content=False))
            response.raise_for_status()
            result = response.json()
        if result.get('status') != 'ok':
            raise RuntimeError('NATIVE_FIND_FAILED')
        hits = []
        def collect(obj):
            if isinstance(obj, dict):
                if isinstance(obj.get('uri'), str) and any(obj['uri'] == scope or obj['uri'].startswith(scope + '/') for scope in target_uris) and isinstance(obj.get('score'), (int, float)):
                    if obj['uri'] not in {x['uri'] for x in hits}:
                        hits.append({'uri': obj['uri'], 'score': obj['score']})
                for value in obj.values():
                    collect(value)
            elif isinstance(obj, list):
                for value in obj:
                    collect(value)
        collect(result.get('result', {}))
        return sorted(hits, key=lambda h: -h['score'])[:limit]
