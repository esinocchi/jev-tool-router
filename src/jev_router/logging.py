"""Allowlisted structured logs. SDK body logging is disabled in the CLI."""

import hashlib
import json
import logging
import sys
from typing import TextIO

from jev_router.config import Settings
from jev_router.models import RoutingDecision, RoutingRequest

LOGGER = logging.getLogger("jev_router")


def configure_logging(stream: TextIO | None = None) -> None:
    LOGGER.handlers.clear()
    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(logging.Formatter("%(message)s"))
    LOGGER.addHandler(handler)
    LOGGER.setLevel(logging.INFO)
    LOGGER.propagate = False
    # Provider debug logs can include full request/response bodies despite header redaction.
    for name in ("typesafe_sdk", "openai", "httpx", "httpx2", "httpcore", "httpcore2"):
        logger = logging.getLogger(name)
        logger.disabled = True
        logger.propagate = False
        logger.handlers.clear()
        logger.addHandler(logging.NullHandler())
        logger.setLevel(logging.CRITICAL + 1)


def request_hash(request: str) -> str:
    return hashlib.sha256(request.encode()).hexdigest()


def log_decision(
    request: RoutingRequest,
    decision: RoutingDecision,
    settings: Settings,
    *,
    mock_execution_attempted: bool = False,
) -> None:
    event = decision.model_dump(mode="json")
    event.update(
        request_id=request.request_id,
        request_sha256=request_hash(request.user_request),
        mock_execution_attempted=mock_execution_attempted,
    )
    if settings.log_full_requests:
        event["request"] = request.user_request
    elif settings.log_request_preview_chars:
        # Even a short request must not be logged in its entirety by the preview option.
        length = min(settings.log_request_preview_chars, max(0, len(request.user_request) - 1))
        event["request_preview"] = request.user_request[:length] + "…"
    LOGGER.info(json.dumps(event, ensure_ascii=False, allow_nan=False))
