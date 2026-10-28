"""Real local SQLite query and factory; only the final SDK client is a fixture."""
import gc
import hashlib
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace
import warnings
import pytest


def credential_db(tmp_path, change=None):
    env={'ANTHROPIC_AUTH_TOKEN':'SYNTHETIC_NOT_A_REAL_SECRET',
         'ANTHROPIC_BASE_URL':'https://api.deepseek.com/anthropic',
         'ANTHROPIC_DEFAULT_HAIKU_MODEL':'deepseek-flash',
         'ANTHROPIC_DEFAULT_OPUS_MODEL':'deepseek-flash'}
    if change:change(env)
    path=tmp_path/'provider.db'
    c=sqlite3.connect(path)
    try:
        c.execute('CREATE TABLE providers (id TEXT,app_type TEXT,settings_config TEXT)')
        c.execute('INSERT INTO providers VALUES (?,?,?)',('deepseek-claude-code','claude',json.dumps({'env':env})))
        c.execute('INSERT INTO providers VALUES (?,?,?)',('not-selected','claude','{"token":"DO_NOT_USE"}'))
        c.commit()
    finally:
        c.close()
    return path


class SdkFixture:
    def __init__(self, **kw):
        self.kw=kw;self.model_name=kw['model'];self.openai_api_base=kw['base_url']
        self.temperature=kw['temperature'];self.request_timeout=kw['timeout'];self.max_retries=kw['max_retries']
    def invoke(self,prompt):return SimpleNamespace(content='synthetic content')


def profile():
    p=Path(__file__).resolve().parents[1]/'contracts/vibe_runtime_profile.json'
    return p,hashlib.sha256(p.read_bytes()).hexdigest()


def test_real_provider_row_and_exact_client_settings(tmp_path):
    from domains.research_review_generation.model_provider import _CREDENTIAL_DB_MAX_BYTES, create_clients
    db=credential_db(tmp_path); before=db.read_bytes();p,sha=profile()
    assert len(before) < _CREDENTIAL_DB_MAX_BYTES
    clients=create_clients(profile_path=p,profile_sha256=sha,credential_db=db,client_factory=SdkFixture)
    assert db.read_bytes()==before
    assert clients.quick.identity.model_id==clients.deep.identity.model_id=='deepseek-flash'
    assert clients.quick.invoke('hello').content=='synthetic content'
    assert clients.quick.public()['temperature']==0.6
    assert clients.quick.public()['timeout']==180 and clients.quick.public()['max_retries']==2
    assert 'SYNTHETIC_NOT_A_REAL_SECRET' not in repr(clients)
    assert 'SYNTHETIC_NOT_A_REAL_SECRET' not in json.dumps(clients.quick.public())


@pytest.mark.parametrize('change',[
    lambda e:e.update(ANTHROPIC_DEFAULT_OPUS_MODEL='deepseek-pro'),
    lambda e:e.update(ANTHROPIC_BASE_URL='https://not-selected.invalid'),
    lambda e:e.update(ANTHROPIC_DEFAULT_SONNET_MODEL='different'),
    lambda e:e.update(ANTHROPIC_AUTH_TOKEN='')])
def test_wrong_identity_or_credential_refuses_without_fallback(tmp_path,change):
    from domains.research_review_generation.model_provider import create_clients
    db=credential_db(tmp_path,change);p,sha=profile();calls=[]
    def factory(**kw):calls.append(kw);return SdkFixture(**kw)
    with pytest.raises(ValueError):create_clients(profile_path=p,profile_sha256=sha,credential_db=db,client_factory=factory)
    assert not calls


def test_wrong_profile_pin_refuses_before_reading_credential(tmp_path):
    from domains.research_review_generation.model_provider import create_clients
    p,_=profile()
    with pytest.raises(ValueError):create_clients(profile_path=p,profile_sha256='0'*64,credential_db=tmp_path/'MISSING',client_factory=SdkFixture)


def test_factory_client_identity_drift_refused(tmp_path):
    from domains.research_review_generation.model_provider import create_clients
    db=credential_db(tmp_path);p,sha=profile()
    def different(**kw):
        obj=SdkFixture(**kw);obj.model_name='wrong-model';return obj
    with pytest.raises(ValueError):create_clients(profile_path=p,profile_sha256=sha,credential_db=db,client_factory=different)


def test_token_closes_snapshot_connection_on_success(tmp_path):
    from domains.research_review_generation.model_provider import _EXPECTED, _token
    db=credential_db(tmp_path)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always', ResourceWarning)
        assert _token(db, _EXPECTED) == 'SYNTHETIC_NOT_A_REAL_SECRET'
        gc.collect()
    assert not [item for item in caught if issubclass(item.category, ResourceWarning)]


def test_token_closes_snapshot_connection_on_deserialize_error(tmp_path):
    from domains.research_review_generation.model_provider import _EXPECTED, _token
    db=tmp_path/'malformed.db'
    db.write_bytes(b'not a sqlite snapshot')
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always', ResourceWarning)
        with pytest.raises(ValueError):
            _token(db, _EXPECTED)
        gc.collect()
    assert not [item for item in caught if issubclass(item.category, ResourceWarning)]


def test_oversized_credential_db_refuses_before_sqlite(tmp_path,monkeypatch):
    from domains.research_review_generation.model_provider import _CREDENTIAL_DB_MAX_BYTES, _EXPECTED, _token
    db=tmp_path/'oversized.db'
    with db.open('wb') as handle:
        handle.truncate(_CREDENTIAL_DB_MAX_BYTES+1)
    calls=[]
    def connect(*args,**kwargs):
        calls.append((args,kwargs))
        raise AssertionError('sqlite must not receive an oversized snapshot')
    monkeypatch.setattr(sqlite3,'connect',connect)
    with pytest.raises(ValueError,match='selected provider could not be read'):
        _token(db,_EXPECTED)
    assert not calls
