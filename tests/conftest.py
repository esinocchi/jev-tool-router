"""Unit tests are hermetic even when the developer has real credentials configured."""

import socket

import pytest


@pytest.fixture(autouse=True)
def offline_and_clean_environment(request, monkeypatch):
    if request.node.get_closest_marker("live"):
        return
    import os

    for key in list(os.environ):
        if key.startswith(("JEV_", "BASELINE_", "TYPESAFE_", "OPENAI_", "OPENROUTER_", "LOG_")):
            monkeypatch.delenv(key, raising=False)

    # Prevent accidental live API requests by any unit test.
    def blocked(*args, **kwargs):
        raise AssertionError("Network access is forbidden in unit tests")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
