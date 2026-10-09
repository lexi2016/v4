"""Lazy assembly for the existing public generation owner, not a second CLI.

Reading/pinning a non-secret config is side-effect-free. Provider construction,
cache/data reads and materialization happen in run(), after the existing public
entry has acquired its same-date task lock and checked exact output absence.
"""
from __future__ import annotations
from dataclasses import dataclass,field
from datetime import datetime
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from infrastructure.owned_io import SafeRoot
from ._cache import digest,explicit_root
from ._owned_io import BoundaryError,directory,read_json,records
from ._snapshot import sha,timestamp
from .owned_runtime import VibeRuntime,verify_owned_sources
from .model_provider import create_clients,read_profile
from .owned_authority import VibeDataAuthority,LiveTransport
from .vibe_core.prompts import RESEARCH_PACK


_REQUIRED={'schema','state_root','cache_root','cache_manifest_path','cache_manifest_sha256',
           'profile_path','profile_sha256','credential_db','data_mode','data_as_of'}
_OPTIONAL={'snapshot_sha256','news_binding','market_proxy','fuyao_credential_file'}


@dataclass(frozen=True)
class RuntimeAssembly:
    state_root: Path
    configuration: dict
    configuration_sha256: str
    implementation_manifest_sha256: str
    _transport: Any = field(default=None,repr=False)
    _client_factory: Any = field(default=None,repr=False)

    def run(self,trade_date: str,review_root: Path):
        c=self.configuration
        if review_root!=self.state_root/'reviews':raise BoundaryError('review root differs from assembly binding')
        verify_owned_sources(self.implementation_manifest_sha256)
        clients=create_clients(profile_path=Path(c['profile_path']),profile_sha256=c['profile_sha256'],
            credential_db=Path(c['credential_db']),client_factory=self._client_factory)
        fuyao_key=None
        if c.get('fuyao_credential_file'):
            p=explicit_root(c['fuyao_credential_file'])
            value=json.loads(SafeRoot(p.parent).read_bytes(p.name,max_bytes=16384))
            if set(value)!={'api_key'} or not isinstance(value['api_key'],str) or not value['api_key'].strip():
                raise BoundaryError('explicit Fuyao credential file is invalid')
            fuyao_key=value['api_key'].strip()
        authority=VibeDataAuthority(state_root=self.state_root,cache_root=Path(c['cache_root']),
            cache_manifest_path=Path(c['cache_manifest_path']),cache_manifest_sha256=c['cache_manifest_sha256'],
            target_date=trade_date,transport=self._transport or LiveTransport(market_proxy=c.get('market_proxy')),
            fuyao_key=fuyao_key,news_binding=c.get('news_binding'))
        if c['data_mode']=='collect':
            _,input_sha=authority.materialize(implementation_sha256=self.implementation_manifest_sha256,
                data_as_of=c['data_as_of'],assembly_config_sha256=self.configuration_sha256)
        else:
            input_sha=sha(c.get('snapshot_sha256'))
            # No implicit raw collection or substitute input in snapshot mode.
        runtime=VibeRuntime(self.state_root,input_sha,self.implementation_manifest_sha256,
            clients.quick,clients.deep,clients.quick.identity,clients.deep.identity,RESEARCH_PACK,
            reflection_root=authority.cache.root/'reflections',authority=authority)
        payload,metadata=runtime.run(trade_date,review_root)
        metadata['assembly']={'schema':'v4.vibe_assembly.v1','configuration_sha256':self.configuration_sha256,
            'data_mode':c['data_mode'],'profile_sha256':clients.profile_sha256,
            'cache_manifest_sha256':c['cache_manifest_sha256'],'cache_inventory_files':len(authority.cache.approved),
            'model_and_data_materialization_under_public_task_lock':True}
        return payload,metadata


def assemble_runtime(*,config_path: Path,config_sha256: str,implementation_manifest_sha256: str,
                     transport=None,client_factory=None) -> RuntimeAssembly:
    path=explicit_root(config_path)
    raw=SafeRoot(path.parent).read_bytes(path.name,max_bytes=128*1024)
    if digest(raw)!=sha(config_sha256):raise BoundaryError('approved assembly configuration SHA drift')
    c=json.loads(raw)
    if (not isinstance(c,dict) or not _REQUIRED<=set(c) or set(c)-_REQUIRED-_OPTIONAL or
        c['schema']!='v4.vibe_assembly.v1' or c['data_mode'] not in {'collect','snapshot'}):
        raise BoundaryError('assembly configuration contract invalid')
    root=explicit_root(c['state_root']);cache=explicit_root(c['cache_root'])
    if cache==root or root not in cache.parents:
        raise BoundaryError('cache must be an explicit child of the V4 state root')
    for name in ('cache_manifest_path','profile_path','credential_db'):
        explicit_root(c[name])
    for name in ('cache_manifest_sha256','profile_sha256'):
        sha(c[name])
    if c['data_mode']=='snapshot':sha(c.get('snapshot_sha256'))
    if c.get('market_proxy'):
        proxy=urlsplit(c['market_proxy'])
        if proxy.scheme not in {'http','https','socks5','socks5h'} or proxy.username or proxy.password or not proxy.hostname:
            raise BoundaryError('market proxy must be an explicit non-secret URL')
    # Pin actual implementation and profile before any owned state creation.
    source=verify_owned_sources(implementation_manifest_sha256)
    code=Path(source['root']).parents[1]
    if root==code or root in code.parents or code in root.parents:
        raise BoundaryError('code and state roots must be disjoint')
    read_profile(Path(c['profile_path']),c['profile_sha256'])
    return RuntimeAssembly(root,c,config_sha256,implementation_manifest_sha256,transport,client_factory)
