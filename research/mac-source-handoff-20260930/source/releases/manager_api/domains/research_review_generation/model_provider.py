"""Explicit read-only CC-Switch DeepSeek factory, extracted from the original.

The caller pins the non-secret profile and supplies the DB path. No selector
fallback, HOME default, .env loading, subprocess or alternative model is used.
The credential row is queried in an in-memory SQLite snapshot: the original DB
is not opened by SQLite, so it cannot create a journal/shm file. A nonempty WAL
is refused rather than silently reading a stale checkpoint.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import json
from pathlib import Path
import sqlite3
from typing import Any

from infrastructure.owned_io import SafeRoot
from ._cache import digest, explicit_root
from ._owned_io import BoundaryError
from .owned_runtime import LlmIdentity
from .vibe_core.llm_errors import (raise_if_config_error, raise_if_transport_error,
                                    raise_if_transport_error_text)

_EXPECTED = {
    'schema':'v4.vibe_runtime_profile.v1','selector':'cc-switch-deepseek',
    'provider_id':'deepseek-claude-code','app_type':'claude','provider_name':'DeepSeek 1M',
    'source_base_url':'https://api.deepseek.com/anthropic','base_url':'https://api.deepseek.com',
    'quick_model':'deepseek-flash','deep_model':'deepseek-flash',
    'temperature':0.6,'timeout':180,'max_retries':2,'prompt_pack':'research',
}
_MODEL_FIELDS=('ANTHROPIC_DEFAULT_HAIKU_MODEL','ANTHROPIC_DEFAULT_OPUS_MODEL')
_OPTIONAL_FIELDS=('ANTHROPIC_MODEL','ANTHROPIC_DEFAULT_SONNET_MODEL','CLAUDE_CODE_SUBAGENT_MODEL')
_CREDENTIAL_DB_MAX_BYTES = 256 * 1024 * 1024


def read_profile(path: Path, expected_sha: str) -> dict:
    path=explicit_root(path)
    raw=SafeRoot(path.parent).read_bytes(path.name,max_bytes=65536)
    if digest(raw)!=expected_sha:
        raise BoundaryError('approved LLM profile SHA drift')
    value=json.loads(raw)
    if value!=_EXPECTED:
        raise BoundaryError('selected profile changed; no provider or prompt fallback')
    return value


def _token(db_path: Path, profile: dict) -> str:
    path=explicit_root(db_path);io=SafeRoot(path.parent)
    try:
        try:
            wal=io.read_bytes(path.name+'-wal',max_bytes=_CREDENTIAL_DB_MAX_BYTES)
        except FileNotFoundError:
            wal=b''
        if wal:
            raise BoundaryError('credential DB has pending WAL; obtain a consistent read-only snapshot from its owner')
        before=io.read_bytes(path.name,max_bytes=_CREDENTIAL_DB_MAX_BYTES)
        c = sqlite3.connect(':memory:')
        try:
            c.deserialize(before)
            c.execute('PRAGMA query_only=ON')
            rows=c.execute('SELECT id, app_type, settings_config FROM providers WHERE id=? AND app_type=?',
                           (profile['provider_id'],profile['app_type'])).fetchall()
        finally:
            c.close()
        after=io.read_bytes(path.name,max_bytes=_CREDENTIAL_DB_MAX_BYTES)
        try:
            after_wal=io.read_bytes(path.name+'-wal',max_bytes=_CREDENTIAL_DB_MAX_BYTES)
        except FileNotFoundError:
            after_wal=b''
        if before!=after or after_wal or len(rows)!=1:
            raise BoundaryError('credential snapshot changed or exact provider is not unique')
        pid,app,settings=rows[0]
        if pid!=profile['provider_id'] or app!=profile['app_type']:
            raise BoundaryError('credential row identity mismatch')
        value=json.loads(settings)
        env=value['env']
        if env.get('ANTHROPIC_BASE_URL')!=profile['source_base_url']:
            raise BoundaryError('credential provider endpoint differs from approved route')
        for field_name in _MODEL_FIELDS:
            if not isinstance(env.get(field_name),str) or env[field_name].strip()!='deepseek-flash':
                raise BoundaryError('credential model differs from approved flash slots')
        for field_name in _OPTIONAL_FIELDS:
            if field_name in env and (not isinstance(env[field_name],str) or env[field_name].strip()!='deepseek-flash'):
                raise BoundaryError('credential optional model would change routing')
        secret=env.get('ANTHROPIC_AUTH_TOKEN')
        if not isinstance(secret,str) or not secret.strip():
            raise BoundaryError('selected provider credential is not configured')
        return secret.strip()
    except BoundaryError:
        raise
    except (OSError,ValueError,KeyError,TypeError,sqlite3.Error) as exc:
        raise BoundaryError('selected provider could not be read; no fallback') from None


@dataclass(frozen=True)
class BoundLlm:
    """A constructor-validated real client and its non-secret identity."""
    _client: Any = field(repr=False)
    identity: LlmIdentity
    profile: dict

    def validate(self) -> None:
        if (self.profile != _EXPECTED or self.identity.provider_id != _EXPECTED['provider_id'] or
            self.identity.model_id != _EXPECTED['quick_model']):
            raise BoundaryError('bound client is not the approved selected profile')
        model=getattr(self._client,'model_name',getattr(self._client,'model',None))
        base=getattr(self._client,'openai_api_base',None)
        if model!=self.identity.model_id or str(base)!=self.profile['base_url']:
            raise BoundaryError('constructed LLM route differs from approved profile')
        if (getattr(self._client,'temperature',None)!=self.profile['temperature'] or
            getattr(self._client,'request_timeout',None)!=self.profile['timeout'] or
            getattr(self._client,'max_retries',None)!=self.profile['max_retries']):
            raise BoundaryError('constructed LLM execution settings drift')

    def public(self) -> dict:
        self.validate()
        return {**self.identity.public(),'app_type':self.profile['app_type'],
                'base_url':self.profile['base_url'],'temperature':self.profile['temperature'],
                'timeout':self.profile['timeout'],'max_retries':self.profile['max_retries'],
                'credential_configured':True,'identity_binding':'FACTORY_AND_CLIENT_VALIDATED'}

    def invoke(self,*args,**kwargs):
        self.validate()
        try:
            result=self._client.invoke(*args,**kwargs)
        except Exception as exc:
            # Preserve original error categories, but never return a raw SDK error.
            try:
                raise_if_config_error(exc,'DeepSeek 复盘')
                raise_if_transport_error(exc,'DeepSeek 复盘')
            except Exception as classified:
                raise type(classified)('DeepSeek selected-provider request failed') from None
            raise RuntimeError('DeepSeek selected-provider request failed') from None
        try:
            raise_if_transport_error_text(getattr(result,'content',None),'DeepSeek 复盘')
        except Exception as classified:
            raise type(classified)('DeepSeek selected-provider returned transport error') from None
        return result


@dataclass(frozen=True)
class Clients:
    quick: BoundLlm
    deep: BoundLlm
    profile_sha256: str


def create_clients(*, profile_path: Path, profile_sha256: str, credential_db: Path,
                   client_factory=None) -> Clients:
    profile=read_profile(profile_path,profile_sha256)
    token=_token(credential_db,profile)
    if client_factory is None:
        from langchain_openai import ChatOpenAI
        client_factory=ChatOpenAI
    clients=[]
    try:
        for slot in ('quick','deep'):
            client=client_factory(model=profile[slot+'_model'],base_url=profile['base_url'],api_key=token,
                                  temperature=profile['temperature'],timeout=profile['timeout'],
                                  max_retries=profile['max_retries'])
            bound=BoundLlm(client,LlmIdentity(profile['provider_id'],profile[slot+'_model'],profile_sha256),dict(profile))
            bound.validate();clients.append(bound)
    except BoundaryError:
        raise
    except Exception:
        raise BoundaryError('selected provider construction failed; no fallback') from None
    finally:
        token=''  # no credential retained in runtime metadata; SDK owns in-memory auth.
    return Clients(clients[0],clients[1],profile_sha256)
