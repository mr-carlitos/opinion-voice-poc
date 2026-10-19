import socket

import pytest


@pytest.fixture(autouse=True)
def no_external_network(monkeypatch):
    """Keep unit/API tests offline, including when local cloud credentials exist."""
    connect = socket.socket.connect
    connect_ex = socket.socket.connect_ex

    def guarded_connect(self, address):
        if self.family in (socket.AF_INET, socket.AF_INET6):
            pytest.fail(f"Unexpected network connection in offline test: {address!r}")
        return connect(self, address)

    def guarded_connect_ex(self, address):
        if self.family in (socket.AF_INET, socket.AF_INET6):
            pytest.fail(f"Unexpected network connection in offline test: {address!r}")
        return connect_ex(self, address)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", guarded_connect_ex)
