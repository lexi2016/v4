"""Only filesystem contract tests; all network connections are prohibited."""
import socket
import pytest

@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def deny(*a, **k):
        raise AssertionError('NETWORK_FORBIDDEN_IN_OFFLINE_TEST')
    monkeypatch.setattr(socket, 'create_connection', deny)
    monkeypatch.setattr(socket.socket, 'connect', deny)
    monkeypatch.setattr(socket.socket, 'connect_ex', deny)
    for key in ('V4_MANAGER_UNIVERSE_ROOT', 'V4_MANAGER_UNIVERSE_OWNER_ROOT',
                'V4_MANAGER_UNIVERSE_OWNER_SHA256'):
        monkeypatch.delenv(key, raising=False)
