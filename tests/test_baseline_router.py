from types import SimpleNamespace
from unittest.mock import AsyncMock

from jev_router.baseline_router import BaselineDomainOutput, BaselineRouter, BaselineToolOutput
from jev_router.config import Settings
from jev_router.models import RoutingRequest
from jev_router.questions import DOMAIN_OPTIONS, tool_options


def output(cls, selected, options, **kwargs):
    return cls(
        selected=selected,
        probabilities=[{"label": k, "probability": float(k == selected)} for k in options],
        confidence=0.9,
        **kwargs,
    )


async def test_structured_output_and_shared_state():
    client = AsyncMock()
    first = output(
        BaselineDomainOutput,
        "files",
        DOMAIN_OPTIONS,
        needs_clarification=0,
        likely_mutation=0,
        high_consequence=0,
    )
    second = output(BaselineToolOutput, "files_read", tool_options("files"))
    client.responses.parse.side_effect = [
        SimpleNamespace(
            output_parsed=p,
            usage=SimpleNamespace(input_tokens=30, output_tokens=5),
            model="configured-model",
            status="completed",
        )
        for p in (first, second)
    ]
    result = await BaselineRouter(
        Settings(_env_file=None, baseline_model="configured-model"), client=client
    ).route(RoutingRequest(user_request="Read /tmp/test.txt"))
    assert result.outcome == "route"
    assert result.selected_tool == "files_read"
    assert result.usage.input_tokens == 60
    assert result.confidence_source == "self_reported"
    calls = client.responses.parse.call_args_list
    assert calls[0].kwargs["text_format"] is BaselineDomainOutput
    assert calls[1].kwargs["text_format"] is BaselineToolOutput
    assert "github_search_code" not in str(calls[1].kwargs["input"])
    assert calls[0].kwargs["store"] is False


async def test_refusal_is_fallback_with_usage():
    client = AsyncMock()
    client.responses.parse.return_value = SimpleNamespace(
        output_parsed=None,
        usage=SimpleNamespace(input_tokens=20, output_tokens=4),
        model="test",
        status="completed",
    )
    result = await BaselineRouter(
        Settings(_env_file=None, baseline_model="test"), client=client
    ).route(RoutingRequest(user_request="test"))
    assert result.outcome == "fallback"
    assert result.usage.input_tokens == 20


async def test_baseline_missing_configuration(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("BASELINE_MODEL", raising=False)
    result = await BaselineRouter(Settings(_env_file=None)).route(
        RoutingRequest(user_request="test")
    )
    assert result.fallback_reason == "missing_baseline_configuration"
