from unittest.mock import AsyncMock

import pytest
from pydantic import BaseModel, Field
from typesafe_sdk import ChoiceAnswer, NoulAnswer, SystemOneResponse, Usage

from jev_router import JevToolRouter, Settings, Tool
from jev_router.questions import domain_options


def test_tool_from_mcp_schema_preserves_required_arguments():
    tool = Tool.from_mcp_schema(
        {
            "name": "search_company_docs",
            "description": "Search company documentation by query.",
            "inputSchema": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
        domain="files",
        read_only=True,
    )

    assert tool.name == "search_company_docs"
    assert tool.required_arguments == ("query",)
    assert tool.read_only


def test_public_router_accepts_application_tools():
    tool = Tool.from_mcp_schema(
        {
            "name": "search_company_docs",
            "description": "Search company documentation by query.",
            "inputSchema": {"type": "object", "required": ["query"]},
        },
        domain="files",
        read_only=True,
    )

    router = JevToolRouter([tool], Settings(_env_file=None))

    assert router.catalog[tool.name] == tool


def test_mcp_metadata_is_conservatively_mutating_without_a_trusted_annotation():
    tool = Tool.from_mcp_schema(
        {
            "name": "send_message",
            "description": "Send a message.",
            "inputSchema": {"type": "object"},
        },
        domain="messaging",
    )
    assert not tool.read_only


def _sdk_answer(questions, selected):
    key = "tool_domain" if "tool_domain" in questions else "tool"
    options = questions[key].criteria
    answers = {
        key: ChoiceAnswer(
            choice=selected,
            confidence=0.99,
            probabilities={name: float(name == selected) for name in options},
        )
    }
    if key == "tool_domain":
        answers.update(
            {
                signal: NoulAnswer(noul=0.0)
                for signal in ("needs_clarification", "likely_mutation", "high_consequence")
            }
        )
    return SystemOneResponse(
        model="jev-test", usage=Usage(input_tokens=5, output_tokens=2), answers=answers
    )


async def test_custom_domain_routes_without_guessing_arguments():
    tool = Tool.from_mcp_schema(
        {
            "name": "search_company_docs",
            "description": "Search internal documentation.",
            "inputSchema": {"type": "object", "required": ["query"]},
        },
        domain="knowledge",
        read_only=True,
    )
    client = AsyncMock()

    async def answer(**kwargs):
        questions = kwargs["questions"]
        selected = "knowledge" if "tool_domain" in questions else "search_company_docs"
        return _sdk_answer(questions, selected)

    client.system_one.side_effect = answer
    router = JevToolRouter([tool], Settings(_env_file=None), client=client)
    decision = await router.route("Find the onboarding guide")

    assert decision.outcome == "route"
    assert decision.selected_domain == "knowledge"
    assert decision.selected_tool == "search_company_docs"
    assert decision.tool_call is None
    assert set(client.system_one.call_args_list[0].kwargs["questions"]["tool_domain"].criteria) == {
        "knowledge",
        "none",
        "other",
    }
    assert set(client.system_one.call_args_list[1].kwargs["questions"]["tool"].criteria) == {
        "search_company_docs",
        "none_of_the_above",
    }


async def test_custom_mutating_tool_requires_approval():
    tool = Tool(name="send_message", domain="messaging", description="Send a message.")
    client = AsyncMock()

    async def answer(**kwargs):
        questions = kwargs["questions"]
        selected = "messaging" if "tool_domain" in questions else "send_message"
        return _sdk_answer(questions, selected)

    client.system_one.side_effect = answer
    decision = await JevToolRouter([tool], Settings(_env_file=None), client=client).route(
        "Send a message"
    )
    assert decision.outcome == "route"
    assert decision.requires_approval


def test_custom_tool_catalog_rejects_duplicate_names_and_reserved_domains():
    tool = Tool(name="lookup", domain="knowledge", description="Look up a fact.")
    with pytest.raises(ValueError, match="unique"):
        JevToolRouter([tool, tool], Settings(_env_file=None))
    with pytest.raises(ValueError, match="reserved"):
        JevToolRouter(
            [Tool(name="lookup", domain="none", description="Look up a fact.")],
            Settings(_env_file=None),
        )


def test_mcp_style_tool_names_are_preserved():
    for name in ("search-docs", "files.read", "DATA_EXPORT_v2"):
        tool = Tool.from_mcp_schema(
            {"name": name, "description": "Find a record.", "inputSchema": {"type": "object"}},
            domain="records",
        )
        assert tool.name == name


def test_existing_domain_name_uses_callers_actual_tools():
    tools = {
        "drive_search": Tool(
            name="drive_search",
            domain="files",
            description="Search files stored in Google Drive.",
            read_only=True,
        )
    }
    description = domain_options(tools)["files"]
    assert "Google Drive" in description
    assert "local files" not in description


def test_mcp_pydantic_tool_object_can_be_adapted_without_mcp_dependency():
    class McpTool(BaseModel):
        name: str
        description: str
        input_schema: dict[str, object] = Field(alias="inputSchema")

    discovered = McpTool(
        name="docs.search",
        description="Search internal docs.",
        inputSchema={"type": "object", "required": ["query"]},
    )
    tool = Tool.from_mcp_schema(discovered, domain="knowledge", read_only=True)
    assert tool.name == "docs.search"
    assert tool.required_arguments == ("query",)


def test_mcp_tool_needs_a_useful_description():
    with pytest.raises(ValueError, match="description"):
        Tool.from_mcp_schema(
            {"name": "lookup", "inputSchema": {"type": "object"}}, domain="knowledge"
        )
