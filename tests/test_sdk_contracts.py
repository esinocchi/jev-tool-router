"""Exercise real SDK serialization/deserialization with mocked HTTP transports."""

import json

import httpx
import httpx2
from openai import AsyncOpenAI
from typesafe_sdk import AsyncTypeSafeClient, RetryPolicy

from jev_router.config import Settings
from jev_router.jev_router import JevRouter
from jev_router.lab.baseline_router import BaselineRouter
from jev_router.lab.tool_catalog import CATALOG
from jev_router.lab.tool_preparation import prepare_tool_call
from jev_router.models import RoutingRequest


async def test_typesafe_wire_contract_and_no_retry():
    payloads = []

    def handler(request):
        assert request.url.path == "/v1/systemone"
        body = json.loads(request.content)
        payloads.append(body)
        if len(payloads) == 2:
            return httpx2.Response(429, json={"error": "rate limited"})
        return httpx2.Response(
            200,
            json={
                "model": "jev-wire-test",
                "usage": {"input_tokens": 18, "output_tokens": 4},
                "answers": {
                    "tool_domain": {
                        "type": "choice",
                        "choice": "files",
                        "confidence": 0.91,
                        "probabilities": {
                            "github": 0,
                            "browser": 0,
                            "files": 1,
                            "calendar": 0,
                            "none": 0,
                            "other": 0,
                        },
                    },
                    "needs_clarification": {"type": "noul", "noul": 0.01},
                    "likely_mutation": {"type": "noul", "noul": 0.02},
                    "high_consequence": {"type": "noul", "noul": 0.03},
                },
            },
        )

    async with AsyncTypeSafeClient(
        api_key="fake-key",
        retry=RetryPolicy(max_retries=0),
        transport=httpx2.MockTransport(handler),
    ) as client:
        result = await JevRouter(
            Settings(_env_file=None),
            client,
            tools=list(CATALOG.values()),
            prepare_call=prepare_tool_call,
        ).route(RoutingRequest(user_request="Read /tmp/a.txt"))
    assert result.outcome == "fallback"
    assert result.usage.input_tokens == 18
    assert not result.usage.complete
    assert len(payloads) == 2
    assert payloads[0]["questions"]["likely_mutation"]["type"] == "noul"
    assert set(payloads[1]["questions"]["tool"]["criteria"]) == {
        "files_search",
        "files_read",
        "files_write",
        "files_delete",
        "none_of_the_above",
    }


async def test_openrouter_wire_structured_output_contract():
    def handler(request):
        assert request.url.host == "openrouter.ai"
        assert request.url.path == "/api/v1/chat/completions"
        body = json.loads(request.content)
        assert body["model"] == "provider/configured-test"
        assert body["response_format"]["type"] == "json_schema"
        assert body["response_format"]["json_schema"]["strict"] is True
        assert body["provider"] == {"require_parameters": True, "allow_fallbacks": False}
        output = {
            "selected": "none",
            "confidence": 0.95,
            "probabilities": {
                label: int(label == "none")
                for label in ("github", "browser", "files", "calendar", "none", "other")
            },
            "needs_clarification": 0,
            "likely_mutation": 0,
            "high_consequence": 0,
        }
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl_mock",
                "object": "chat.completion",
                "created": 1,
                "model": "provider/configured-test",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(output),
                            "refusal": None,
                        },
                    }
                ],
                "usage": {"prompt_tokens": 27, "completion_tokens": 12, "total_tokens": 39},
            },
        )

    async with AsyncOpenAI(
        api_key="fake-key",
        base_url="https://openrouter.ai/api/v1",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        max_retries=0,
    ) as client:
        result = await BaselineRouter(
            Settings(_env_file=None, baseline_model="provider/configured-test"),
            client,
        ).route(RoutingRequest(user_request="What is 2+2?"))
    assert result.outcome == "no_tool"
    assert result.domain_confidence == 0.95
    assert result.usage.input_tokens == 27
    assert result.usage.output_tokens == 12
