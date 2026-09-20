# Jev Tool Router

**Experimental Python SDK and reproducible tool-routing research.** Give the router your agent's tool names and descriptions; it returns a typed `route`, `clarify`, `no_tool`, or `fallback` decision. TypeSafe AI's Jev makes the judgments. Your application remains responsible for arguments, authorization, and execution. This project has not demonstrated an overall performance benefit for a 16-tool agent and is not a production authorization layer.

```text
Your request → Jev: choose a domain → Jev: choose one tool in that domain → typed decision
```

The SDK can be installed without the lab dependencies. The [experiment lab](experiments/README.md) contains an 86-case routing dataset, an OpenRouter comparison, a mock CLI, and a paired agent benchmark.

## What the experiment found

The repo asks **two different questions**. The [86-case routing-only evaluation](experiments/published/routing-2026-09-20.json) gives tool selection to either Jev or a two-stage Luna-based LLM router. There is no agent making a later tool call in this test. Jev found a suitable domain and tool in **64/68 tool-fit cases (94.1%)**, with mean routing latency of **508 ms**; Luna reached **65/68 (95.6%)** at **2,579 ms**. Estimated total API cost was **$0.00365** versus **$0.02920**, using configured prices. Jev selected an acceptable candidate in all **55 cases labeled ready to route**, but returned `clarify` on 24 and `fallback` on one, leaving **30/55** ready-to-use routes versus Luna's **35/55**. See the [metric definitions](experiments/README.md#evaluation).

The separate **10-task agent benchmark** tests what can be built with ordinary provider tool APIs today: Jev filters the tool list, then the same Luna agent still decides whether and how to call a tool. Against a flat 16-tool agent, both arms completed **10/10** clear synthetic tasks. Jev filtering was **19.3% slower** on mean task latency (3.071 s versus 2.575 s) and **6.5% cheaper** by configured price estimates ($0.002786 versus $0.002979 for ten tasks). The two-tool case succeeded only after Jev fell back to the full catalog. Read the [case study](docs/case-study.md), [agent benchmark method](experiments/README.md#agent-task-benchmark), [source tasks](experiments/agent_tasks.json), and [published agent report](experiments/published/agent-bench-2026-09-20.json).

The research hypothesis is that a fast, inexpensive specialist could eventually take more of the routing work away from a general agent model. The routing-only test supports that direction **for this dataset**; the ten-task test does not show an end-to-end speed benefit for the app-level prefilter with 16 tools. Provider APIs let an application control offered tools, but this project does not replace a provider model's internal automatic tool selection. It does not provide a framework-specific adapter or compare provider-native tool search. These small, hand-authored runs do not establish statistical significance or general accuracy parity; costs are estimates, not invoices. See the [integration boundary](docs/usage.md#filter-tools-before-the-model-call). To repeat the paid agent run after configuring both API keys and a baseline model, use `uv run jev-router agent-bench --live --limit 10`.

## Install

Requires Python 3.11+. Install from this Git repository in your Python project:

```bash
uv add "jev-tool-router @ git+https://github.com/esinocchi/jev-tool-router.git"
```

To try a local checkout instead:

```bash
uv add ../jev-tool-router
```

For development in this repository, run `uv sync --locked`. Set `TYPESAFE_API_KEY` in your environment; obtain a key through the [TypeSafe quickstart](https://docs.typesafe.ai/introduction/quickstart). The SDK also reads your project's `.env` file when present. Never commit a real key.

## Route your first request

```python
import asyncio

from jev_router import JevToolRouter, Tool


async def main() -> None:
    tools = [
        Tool(
            name="search_docs",
            domain="knowledge",
            description="Search the company's documentation by topic.",
            read_only=True,
        ),
        Tool(
            name="create_ticket",
            domain="support",
            description="Create a support ticket for a customer issue.",
        ),
    ]
    async with JevToolRouter(tools) as router:
        decision = await router.route("Find the SSO setup guide")

    if decision.outcome == "route":
        print(decision.selected_tool, decision.requires_approval)
    else:
        print(decision.outcome, decision.fallback_reason or decision.clarification_reason)


asyncio.run(main())
```

Copy the runnable version from [examples/basic.py](examples/basic.py). The router sends the request and any supplied context to TypeSafe. It makes up to two API calls and can incur charges.

The `domain` may be any short name you choose, such as `knowledge`, `github`, or `billing`. The first Jev call sees the domains in your catalog; the second sees only the tools in the selected domain. `none` and `other` are reserved. Tool names must be unique. Group closely related tools together and write descriptions that distinguish near misses.

## Use MCP tool metadata

Pass the metadata returned by an MCP `tools/list` call through `Tool.from_mcp_schema`:

```python
tool = Tool.from_mcp_schema(
    {
        "name": "search_docs",
        "description": "Search the company's documentation by topic.",
        "inputSchema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
    domain="knowledge",
    read_only=True,
)
```

`Tool.from_mcp_schema` also accepts the Pydantic tool object returned by the MCP Python SDK, without adding MCP as a dependency. `domain` and `read_only` are trusted application decisions. A tool defaults to **mutating** if `read_only` is omitted. The router does not connect to an MCP server or call this tool. Your agent should generate arguments after the route, validate them against the tool's schema, and enforce its own authorization before any execution.

## Handle decisions

| Outcome | What your application should do |
| --- | --- |
| `route` | Consider the selected tool. Generate and validate arguments separately; require approval when `requires_approval` is true. |
| `clarify` | Ask the user for missing intent or details. |
| `no_tool` | Answer directly without a tool. |
| `fallback` | Use your existing agent/LLM path or ask the user; inspect `fallback_reason`. |

`RoutingDecision` includes domain/tool probabilities, confidence, latency, token usage, and approval signals. Confidence is a model signal, not a guarantee of correctness. The default thresholds and timeout can be changed with `Settings` or the variables in [.env.example](.env.example). A mutating tool always requires approval based on trusted metadata, regardless of the model's prediction. This library never approves or executes tools.

For the full API, outcomes, and integration pattern, see [SDK usage](docs/usage.md). For benchmark commands and interpretation, see [experiments](experiments/README.md).

## Contribute

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup and checks. We keep live provider calls out of the default tests. The [repository research](docs/repository-research.md) explains the packaging and documentation decisions behind this layout. This project is [MIT licensed](LICENSE).
