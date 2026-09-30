"""No external I/O: fabricated HTTP responses only, real local original stores."""
import socket
import pytest
@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def deny(*a,**kw):
        raise AssertionError('UNEXPECTED_NETWORK_CALL')
    monkeypatch.setattr(socket,'create_connection',deny)
    monkeypatch.setattr(socket.socket,'connect',deny)
    monkeypatch.setattr(socket.socket,'connect_ex',deny)
