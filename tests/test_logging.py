import io
import json
import logging

from pydantic import SecretStr

from jev_router.config import Settings
from jev_router.logging import configure_logging, log_decision
from jev_router.models import RoutingDecision, RoutingRequest


def test_private_logging():
    stream = io.StringIO()
    configure_logging(stream)
    settings = Settings(_env_file=None, typesafe_api_key=SecretStr("top-secret-key"))
    request = RoutingRequest(user_request="A very private complete user request")
    decision = RoutingDecision(router="jev", model="test")
    log_decision(request, decision, settings)
    raw = stream.getvalue()
    assert request.user_request not in raw
    assert "top-secret-key" not in raw
    log = json.loads(raw)
    assert len(log["request_sha256"]) == 64
    assert log["mock_execution_attempted"] is False
    assert logging.getLogger("typesafe_sdk").disabled


def test_optional_preview_is_truncated():
    stream = io.StringIO()
    configure_logging(stream)
    request = RoutingRequest(user_request="short")
    log_decision(
        request,
        RoutingDecision(router="jev", model="test"),
        Settings(_env_file=None, log_request_preview_chars=20),
    )
    event = json.loads(stream.getvalue())
    assert event["request_preview"] != request.user_request


def test_explicit_development_full_logging():
    stream = io.StringIO()
    configure_logging(stream)
    request = RoutingRequest(user_request="development input")
    log_decision(
        request,
        RoutingDecision(router="jev", model="test"),
        Settings(_env_file=None, log_full_requests=True),
    )
    assert json.loads(stream.getvalue())["request"] == request.user_request
