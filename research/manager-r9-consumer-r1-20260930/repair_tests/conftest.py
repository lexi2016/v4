"""All author tests are offline; a network attempt is an error, never a fallback."""
import socket
import pytest

@pytest.fixture(autouse=True)
def deny_network(monkeypatch):
    def blocked(*args,**kwargs):
        raise AssertionError('OFFLINE_TEST_NETWORK_FORBIDDEN')
    monkeypatch.setattr(socket,'create_connection',blocked)
    monkeypatch.setattr(socket.socket,'connect',blocked)
    monkeypatch.setattr(socket.socket,'connect_ex',blocked)
