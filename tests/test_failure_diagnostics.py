import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from openai import APIConnectionError, APIStatusError, APITimeoutError

from jev_router.baseline_router import BaselineRouter, BaselineToolOutput, output_schema
from jev_router.config import Settings
from jev_router.models import RoutingRequest
from jev_router.questions import DOMAIN_OPTIONS


def completion(content, finish="stop", refusal=None):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason=finish, message=SimpleNamespace(content=content, refusal=refusal)
            )
        ],
        usage=SimpleNamespace(prompt_tokens=20, completion_tokens=5),
        model="test",
    )


def valid_domain():
    return dict(
        selected="files",
        probabilities={k: float(k == "files") for k in DOMAIN_OPTIONS},
        confidence=0.9,
        needs_clarification=0,
        likely_mutation=0,
        high_consequence=0,
    )


def test_closed_schema_requires_every_offered_probability():
    schema = output_schema(
        BaselineToolOutput, {"files_read": "read", "none_of_the_above": "reject"}
    )
    probabilities = schema["properties"]["probabilities"]
    assert set(probabilities["required"]) == {"files_read", "none_of_the_above"}
    assert probabilities["additionalProperties"] is False
    assert schema["properties"]["selected"]["enum"] == ["files_read", "none_of_the_above"]


@pytest.mark.parametrize(
    "problem,reason",
    [
        ("json", "invalid_json"),
        ("schema", "invalid_output_schema"),
        ("missing", "missing_probability_labels"),
        ("extra", "unknown_probability_labels"),
        ("sum", "invalid_probability_sum"),
        ("selection", "selected_label_not_maximum"),
        ("refusal", "provider_refusal"),
        ("length", "incomplete_response"),
        ("empty", "empty_response"),
        ("duplicate", "duplicate_json_keys"),
    ],
)
async def test_distinct_safe_validation_reasons(problem, reason):
    payload = valid_domain()
    if problem == "schema":
        payload["confidence"] = "PRIVATE_VALUE"
    if problem == "missing":
        del payload["probabilities"]["other"]
    if problem == "extra":
        payload["probabilities"]["PRIVATE_LABEL"] = 0
    if problem == "sum":
        payload["probabilities"]["files"] = 0.8
    if problem == "selection":
        payload["selected"] = "github"
    content = json.dumps(payload)
    if problem == "json":
        content = "PRIVATE_INVALID_JSON"
    if problem == "empty":
        content = None
    if problem == "duplicate":
        content = '{"PRIVATE_KEY":1,"PRIVATE_KEY":2}'
    client = AsyncMock()
    client.chat.completions.create.return_value = completion(
        content,
        "length" if problem == "length" else "stop",
        "PRIVATE_REFUSAL" if problem == "refusal" else None,
    )
    result = await BaselineRouter(Settings(_env_file=None, baseline_model="test"), client).route(
        RoutingRequest(user_request="PRIVATE_REQUEST")
    )
    assert result.fallback_reason == reason
    assert result.failure_stage == "domain"
    assert result.usage.input_tokens == 20
    assert "PRIVATE" not in result.model_dump_json()


@pytest.mark.parametrize(
    "status,reason",
    [
        (400, "api_bad_request"),
        (401, "api_authentication"),
        (403, "api_permission"),
        (429, "api_rate_limit"),
        (503, "api_server_error"),
    ],
)
async def test_safe_http_error_categories(status, reason):
    client = AsyncMock()
    client.chat.completions.create.side_effect = APIStatusError(
        "PRIVATE_API_ERROR",
        response=httpx.Response(status, request=httpx.Request("POST", "https://example.test")),
        body={"secret": "PRIVATE"},
    )
    result = await BaselineRouter(Settings(_env_file=None, baseline_model="test"), client).route(
        RoutingRequest(user_request="PRIVATE_REQUEST")
    )
    assert result.fallback_reason == reason
    assert not result.usage.complete
    assert "PRIVATE" not in result.model_dump_json()


async def test_stage_two_error_retains_stage_one_usage():
    client = AsyncMock()
    client.chat.completions.create.side_effect = [
        completion(json.dumps(valid_domain())),
        completion("bad JSON"),
    ]
    result = await BaselineRouter(Settings(_env_file=None, baseline_model="test"), client).route(
        RoutingRequest(user_request="test")
    )
    assert result.failure_stage == "tool"
    assert result.fallback_reason == "invalid_json"
    assert result.usage.input_tokens == 40


@pytest.mark.parametrize(
    "error,reason",
    [
        (
            APIConnectionError(request=httpx.Request("POST", "https://example.test")),
            "api_connection",
        ),
        (APITimeoutError(request=httpx.Request("POST", "https://example.test")), "timeout"),
    ],
)
async def test_connection_failures(error, reason):
    client = AsyncMock()
    client.chat.completions.create.side_effect = error
    result = await BaselineRouter(Settings(_env_file=None, baseline_model="test"), client).route(
        RoutingRequest(user_request="test")
    )
    assert result.fallback_reason == reason
