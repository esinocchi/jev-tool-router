import pytest

from jev_router.config import Settings
from jev_router.lab.tool_catalog import CATALOG, execute_mock
from jev_router.lab.tool_preparation import prepare_tool_call
from jev_router.models import (
    ChoiceJudgment,
    DomainJudgment,
    RoutingDecision,
    RoutingRequest,
    ToolCallPreparation,
)
from jev_router.routing_service import HierarchicalRouter as CoreHierarchicalRouter


class HierarchicalRouter(CoreHierarchicalRouter):
    def __init__(self, provider, settings):
        super().__init__(provider, settings, CATALOG, prepare_call=prepare_tool_call)


def choice(label, options, confidence=0.95):
    return ChoiceJudgment(
        selected=label, probabilities={x: float(x == label) for x in options}, confidence=confidence
    )


class Provider:
    name = "fake"
    model = "fake-model"
    confidence_source = "test"
    configuration_error = None

    def __init__(
        self,
        domain="github",
        dc=0.95,
        tc=0.95,
        clarification=0,
        mutation=0,
        consequence=0,
        tool="github_search_issues",
    ):
        self.domain = domain
        self.dc = dc
        self.tc = tc
        self.clarification = clarification
        self.mutation = mutation
        self.consequence = consequence
        self.tool = tool
        self.calls = []

    async def judge_domain(self, request, usage):
        from jev_router.questions import DOMAIN_OPTIONS

        self.calls.append("domain")
        return DomainJudgment(
            choice=choice(self.domain, DOMAIN_OPTIONS, self.dc),
            needs_clarification=self.clarification,
            likely_mutation=self.mutation,
            high_consequence=self.consequence,
        )

    async def judge_tool(self, request, domain, usage):
        from jev_router.questions import tool_options

        self.calls.append(domain)
        return choice(self.tool, tool_options(domain, CATALOG), self.tc)


@pytest.mark.parametrize(
    "kwargs,outcome,reason,calls",
    [
        ({}, "route", None, 2),
        ({"dc": 0.64}, "fallback", "low_domain_confidence", 1),
        ({"tc": 0.69}, "fallback", "low_tool_confidence", 2),
        ({"domain": "none"}, "no_tool", None, 1),
        ({"domain": "other"}, "fallback", "unsupported_domain", 1),
        ({"clarification": 0.76}, "clarify", None, 1),
        ({"tool": "none_of_the_above"}, "fallback", "no_matching_tool", 2),
        ({"dc": 0.65, "tc": 0.70, "clarification": 0.75}, "route", None, 2),
    ],
)
async def test_policy(kwargs, outcome, reason, calls):
    provider = Provider(**kwargs)
    result = await HierarchicalRouter(provider, Settings(_env_file=None)).route(
        RoutingRequest(user_request="Find issues")
    )
    assert result.outcome == outcome
    assert result.fallback_reason == reason
    assert len(provider.calls) == calls


@pytest.mark.parametrize(
    "kwargs", [{"mutation": 0.60}, {"consequence": 0.50}, {"tool": "github_create_issue"}]
)
async def test_approval_signals(kwargs):
    result = await HierarchicalRouter(Provider(**kwargs), Settings(_env_file=None)).route(
        RoutingRequest(user_request="Example")
    )
    assert result.requires_approval


@pytest.mark.parametrize("tool", list(CATALOG))
def test_executor_uses_catalog_even_with_forged_decision(tool):
    definition = CATALOG[tool]
    decision = RoutingDecision(
        router="fake",
        model="fake",
        outcome="route",
        selected_domain=definition.domain,
        selected_tool=tool,
        requires_approval=False,
    )
    prepared = ToolCallPreparation(
        tool=tool,
        status="ready",
        arguments={
            field: (
                "https://example.test"
                if field == "url"
                else "/tmp/value"
                if field == "path"
                else "value"
            )
            for field in definition.required_arguments
        },
    )
    if not definition.read_only:
        with pytest.raises(PermissionError):
            execute_mock(decision, prepared=prepared)
    else:
        assert execute_mock(decision, prepared=prepared).tool == tool
    assert execute_mock(decision, prepared=prepared, approved=True).tool == tool


def test_catalog():
    assert len(CATALOG) == 16
    assert len({t.name for t in CATALOG.values()}) == 16
    assert {t.domain for t in CATALOG.values()} == {"github", "browser", "files", "calendar"}
    for tool in CATALOG.values():
        assert tool.input_schema["type"] == "object"
        assert tool.output_schema["type"] == "object"


@pytest.mark.parametrize("outcome", ["fallback", "clarify", "no_tool"])
def test_non_routes_never_execute_even_with_approval(outcome):
    decision = RoutingDecision(
        router="fake",
        model="fake",
        outcome=outcome,
        selected_domain="files",
        selected_tool="files_delete",
    )
    with pytest.raises(ValueError):
        execute_mock(decision, approved=True)


def test_model_risk_can_block_read_only_execution():
    decision = RoutingDecision(
        router="fake",
        model="fake",
        outcome="route",
        selected_domain="files",
        selected_tool="files_read",
        requires_approval=True,
    )
    prepared = ToolCallPreparation(tool="files_read", status="ready", arguments={"path": "/tmp/a"})
    with pytest.raises(PermissionError):
        execute_mock(decision, prepared=prepared)


def test_mismatched_domain_is_not_executable():
    decision = RoutingDecision(
        router="fake",
        model="fake",
        outcome="route",
        selected_domain="github",
        selected_tool="files_read",
    )
    with pytest.raises(ValueError):
        execute_mock(decision, approved=True)


async def test_routed_tool_has_a_ready_prepared_call():
    result = await HierarchicalRouter(Provider(), Settings(_env_file=None)).route(
        RoutingRequest(user_request="Find issues mentioning authentication")
    )

    assert result.outcome == "route"
    assert result.tool_call is not None
    assert result.tool_call.status == "ready"
    assert result.tool_call.arguments == {"query": "Find issues mentioning authentication"}


async def test_missing_arguments_turn_an_otherwise_routed_tool_into_clarification():
    result = await HierarchicalRouter(
        Provider(domain="browser", tool="browser_open_page"), Settings(_env_file=None)
    ).route(RoutingRequest(user_request="Open that website"))

    assert result.outcome == "clarify"
    assert result.tool_call is not None
    assert result.tool_call.missing_fields == ["url"]
