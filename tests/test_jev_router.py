import asyncio
from unittest.mock import AsyncMock

import pytest
from pydantic import SecretStr
from typesafe_sdk import Choice, ChoiceAnswer, Noul, NoulAnswer, SystemOneResponse, Usage

from jev_router.config import Settings
from jev_router.jev_router import JevRouter as CoreJevRouter
from jev_router.jev_router import domain_questions, tool_questions
from jev_router.lab.tool_catalog import CATALOG
from jev_router.lab.tool_preparation import prepare_tool_call
from jev_router.models import RoutingRequest
from jev_router.questions import DOMAIN_OPTIONS, tool_options


class JevRouter(CoreJevRouter):
    def __init__(self, settings, client=None):
        super().__init__(
            settings, client=client, tools=list(CATALOG.values()), prepare_call=prepare_tool_call
        )


def response(domain="github", confidence=0.9, tool=None, tokens=10):
    selected = domain if tool is None else tool
    options = DOMAIN_OPTIONS if tool is None else tool_options(domain, CATALOG)
    answers = {
        "tool_domain" if tool is None else "tool": ChoiceAnswer(
            choice=selected,
            confidence=confidence,
            probabilities={x: float(x == selected) for x in options},
        )
    }
    if tool is None:
        answers.update(
            {
                key: NoulAnswer(noul=0.0)
                for key in ("needs_clarification", "likely_mutation", "high_consequence")
            }
        )
    return SystemOneResponse(
        model="jev-test-version", usage=Usage(input_tokens=tokens, output_tokens=2), answers=answers
    )


def test_question_construction():
    questions = domain_questions(CATALOG)
    assert isinstance(questions["tool_domain"], Choice)
    assert set(questions["tool_domain"].criteria) == set(DOMAIN_OPTIONS)
    for key in ("needs_clarification", "likely_mutation", "high_consequence"):
        assert isinstance(questions[key], Noul)
        assert "user_request" in questions[key].instructions
    for domain in ("github", "browser", "files", "calendar"):
        q = tool_questions(domain, CATALOG)["tool"]
        assert set(q.criteria) == set(tool_options(domain, CATALOG))
        assert all(k.startswith(domain + "_") or k == "none_of_the_above" for k in q.criteria)


async def test_real_sdk_response_parsing_and_usage():
    client = AsyncMock()
    client.system_one.side_effect = [response(), response(tool="github_search_issues", tokens=20)]
    router = JevRouter(Settings(_env_file=None), client=client)
    result = await router.route(RoutingRequest(user_request="Find GitHub issues"))
    assert result.outcome == "route"
    assert result.selected_tool == "github_search_issues"
    assert result.usage.input_tokens == 30
    assert result.usage.output_tokens == 4
    assert result.usage.complete
    assert result.usage.response_models == ["jev-test-version", "jev-test-version"]
    assert (
        client.system_one.call_args_list[0].kwargs["state"]
        == client.system_one.call_args_list[1].kwargs["state"]
    )


@pytest.mark.parametrize("error", [RuntimeError("sensitive secret"), TimeoutError()])
async def test_api_failure(error):
    client = AsyncMock()
    client.system_one.side_effect = error
    result = await JevRouter(Settings(_env_file=None), client=client).route(
        RoutingRequest(user_request="test")
    )
    assert result.outcome == "fallback"
    assert "sensitive" not in result.model_dump_json()
    assert not result.usage.complete


async def test_deadline_and_partial_usage():
    async def slow(**kwargs):
        if "tool_domain" in kwargs["questions"]:
            return response()
        await asyncio.sleep(1)

    client = AsyncMock()
    client.system_one.side_effect = slow
    result = await JevRouter(
        Settings(_env_file=None, jev_routing_timeout_ms=20), client=client
    ).route(RoutingRequest(user_request="test"))
    assert result.fallback_reason == "timeout"
    assert result.latency_ms < 300
    assert result.usage.input_tokens == 10
    assert not result.usage.complete
    assert result.estimated_cost_usd is None


async def test_missing_key(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    result = await JevRouter(Settings(_env_file=None)).route(RoutingRequest(user_request="test"))
    assert result.fallback_reason == "missing_typesafe_api_key"
    assert result.usage.attempted_calls == 0


async def test_missing_usage_is_unknown():
    client = AsyncMock()
    client.system_one.return_value = SystemOneResponse(
        model="test", usage=Usage(), answers=response(domain="none").answers
    )
    result = await JevRouter(Settings(_env_file=None), client=client).route(
        RoutingRequest(user_request="test")
    )
    assert result.outcome == "no_tool"
    assert not result.usage.complete


async def test_invalid_answer_keeps_reported_usage():
    client = AsyncMock()
    client.system_one.return_value = SystemOneResponse(
        model="test", usage=Usage(input_tokens=10, output_tokens=1), answers={}
    )
    result = await JevRouter(Settings(_env_file=None), client=client).route(
        RoutingRequest(user_request="test")
    )
    assert result.outcome == "fallback"
    assert result.usage.input_tokens == 10


def test_client_options_disable_retries(monkeypatch):
    from unittest.mock import Mock

    factory = Mock()
    monkeypatch.setattr("jev_router.jev_router.AsyncTypeSafeClient", factory)
    router = JevRouter(Settings(_env_file=None, typesafe_api_key=SecretStr("test")))
    router.provider.get_client()
    assert factory.call_args.kwargs["retry"].max_retries == 0


@pytest.mark.parametrize("input_count,output_count", [(123, None), (None, 7)])
async def test_partial_token_fields_are_preserved(input_count, output_count):
    client = AsyncMock()
    client.system_one.return_value = SystemOneResponse(
        model="test",
        usage=Usage(input_tokens=input_count, output_tokens=output_count),
        answers=response(domain="none").answers,
    )
    result = await JevRouter(Settings(_env_file=None), client=client).route(
        RoutingRequest(user_request="test")
    )
    assert result.usage.input_tokens == (input_count or 0)
    assert result.usage.output_tokens == (output_count or 0)
    assert not result.usage.complete
    assert result.estimated_cost_usd is None
