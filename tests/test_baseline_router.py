from types import SimpleNamespace
from unittest.mock import AsyncMock

from jev_router.config import Settings
from jev_router.lab.baseline_router import (
    BaselineDomainOutput,
    BaselineRouter,
    BaselineToolOutput,
    output_schema,
)
from jev_router.lab.tool_catalog import CATALOG
from jev_router.models import RoutingRequest
from jev_router.questions import DOMAIN_OPTIONS, tool_options


def output(cls, selected, options, **kwargs):
    return cls(
        selected=selected,
        probabilities={k: float(k == selected) for k in options},
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
    second = output(BaselineToolOutput, "files_read", tool_options("files", CATALOG))
    client.chat.completions.create.side_effect = [
        SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason="stop",
                    message=SimpleNamespace(content=p.model_dump_json(), refusal=None),
                )
            ],
            usage=SimpleNamespace(prompt_tokens=30, completion_tokens=5),
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
    calls = client.chat.completions.create.call_args_list
    assert calls[0].kwargs["response_format"]["json_schema"]["schema"] == output_schema(
        BaselineDomainOutput, DOMAIN_OPTIONS
    )
    assert calls[1].kwargs["response_format"]["json_schema"]["schema"] == output_schema(
        BaselineToolOutput, tool_options("files", CATALOG)
    )
    assert "github_search_code" not in str(calls[1].kwargs["messages"])
    assert calls[0].kwargs["extra_body"]["provider"]["require_parameters"] is True


async def test_refusal_is_fallback_with_usage():
    client = AsyncMock()
    client.chat.completions.create.return_value = SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason="stop", message=SimpleNamespace(content=None, refusal="refused")
            )
        ],
        usage=SimpleNamespace(prompt_tokens=20, completion_tokens=4),
        model="test",
        status="completed",
    )
    result = await BaselineRouter(
        Settings(_env_file=None, baseline_model="test"), client=client
    ).route(RoutingRequest(user_request="test"))
    assert result.outcome == "fallback"
    assert result.usage.input_tokens == 20


async def test_baseline_missing_configuration(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("BASELINE_MODEL", raising=False)
    result = await BaselineRouter(Settings(_env_file=None)).route(
        RoutingRequest(user_request="test")
    )
    assert result.fallback_reason == "missing_baseline_configuration"


def test_openrouter_configuration_from_environment(monkeypatch):
    from unittest.mock import Mock

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")
    monkeypatch.setenv("BASELINE_MODEL", "provider/configured-model")
    factory = Mock()
    monkeypatch.setattr("jev_router.lab.baseline_router.AsyncOpenAI", factory)
    router = BaselineRouter(Settings(_env_file=None))
    assert router.provider.configuration_error is None
    router.provider.get_client()
    assert factory.call_args.kwargs["api_key"] == "test-openrouter-key"
    assert factory.call_args.kwargs["base_url"] == "https://openrouter.ai/api/v1"
    assert router.provider.model == "provider/configured-model"


async def test_invalid_json_keeps_usage():
    client = AsyncMock()
    client.chat.completions.create.return_value = SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason="stop", message=SimpleNamespace(content="not JSON", refusal=None)
            )
        ],
        usage=SimpleNamespace(prompt_tokens=20, completion_tokens=4),
        model="provider/test",
    )
    result = await BaselineRouter(
        Settings(_env_file=None, baseline_model="provider/test"), client
    ).route(RoutingRequest(user_request="test"))
    assert result.outcome == "fallback"
    assert result.usage.input_tokens == 20
    assert result.usage.complete
