from jev_router import JevToolRouter, Tool
from jev_router.config import Settings


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
    )

    router = JevToolRouter([tool], Settings(_env_file=None))

    assert router.catalog[tool.name] == tool
