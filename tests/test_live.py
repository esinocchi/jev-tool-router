"""Paid opt-in contract checks, never selected by the default test command."""

import os

import pytest

from jev_router.config import Settings
from jev_router.jev_router import JevRouter
from jev_router.lab.baseline_router import BaselineRouter
from jev_router.lab.tool_catalog import CATALOG
from jev_router.lab.tool_preparation import prepare_tool_call
from jev_router.models import RoutingRequest

pytestmark = pytest.mark.live


@pytest.mark.parametrize("provider", ["jev", "baseline"])
async def test_live_provider_contract(provider):
    if os.environ.get("RUN_LIVE_TESTS") != "1":
        pytest.skip("Set RUN_LIVE_TESTS=1 and explicitly select -m live")
    settings = Settings()
    router = (
        JevRouter(settings, tools=list(CATALOG.values()), prepare_call=prepare_tool_call)
        if provider == "jev"
        else BaselineRouter(settings)
    )
    if router.provider.configuration_error:
        pytest.skip("Corresponding API key/model is not configured")
    try:
        result = await router.route(
            RoutingRequest(user_request="Read the local file /tmp/demo.txt.")
        )
    finally:
        await router.aclose()
    assert result.failure_stage is None
    assert result.domain_probabilities
    assert result.usage.attempted_calls >= 1
    # Confidence and semantic accuracy are evaluated separately; this test checks the contract.
