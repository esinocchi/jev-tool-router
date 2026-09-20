# Jev Tool Router

**Can a specialist model choose an agent's tools?** This repository contains two small, documented experiments, a runnable benchmark harness, and an experimental Python SDK built around TypeSafe AI's Jev. Start with the [case study](docs/case-study.md) for the story, or use the links below to inspect the evidence behind it.

| Experiment | Question | Published result | Evidence |
| --- | --- | --- | --- |
| **Routing only · 86 requests** | Can Jev make the domain/tool decision instead of a general LLM router? | Similar tool fit; Jev was about 5× faster and cost about one-eighth as much under configured prices. No agent call followed. | [Cases](experiments/routing_cases.json) · [Report](experiments/published/routing-2026-09-20.json) · [Figure](docs/assets/routing-benchmark.svg) · [Method and metrics](experiments/README.md#evaluation) |
| **Agent loop · 10 tasks** | Does a Jev prefilter help when Luna still makes the tool call? | Both arms completed 10/10; prefiltering was slower and slightly cheaper in this small run. | [Tasks](experiments/agent_tasks.json) · [Report](experiments/published/agent-bench-2026-09-20.json) · [Figure](docs/assets/agent-benchmark.svg) · [Method](experiments/README.md#agent-task-benchmark) |

Both comparisons used `openai/gpt-5.6-luna` through OpenRouter as the general-model baseline. They do not compare Jev with every general LLM.

These are **different tests**:

```text
Routing only: request → Jev or Luna router → domain/tool decision → stop
Agent loop:   request → Jev filters tools → Luna chooses a call → mock result
              request → Luna sees all tools → Luna chooses a call → mock result
```

In the first test, Jev picked a suitable domain and tool in **64/68** tool-fit cases versus Luna's **65/68**. Mean routing latency was **508 ms versus 2,579 ms**; estimated total cost was **$0.00365 versus $0.02920**. Jev returned a ready-to-use route in **30/55** cases labeled ready to route versus Luna's **35/55**, mostly because Jev asked for clarification more often. Tool relevance and willingness to proceed are separate measures.

In the second test, both versions of the Luna mock agent completed **10/10** tasks. Adding Jev raised mean task latency from **2.575 to 3.071 seconds** and reduced estimated cost from **$0.002979 to $0.002786**. The two-tool task succeeded only when Jev fell back to the full catalog. With 16 tools, this run did **not** show an end-to-end speed benefit from the extra external routing call.

The promising hypothesis is that specialist routing could help **closer to a provider's tool-selection path**, where the agent would not repeat the selection work. This repo cannot replace a provider model's internal automatic tool selection. It tests the app-level prefilter that today's tool APIs permit, but not provider-native tool search. Both runs are single, synthetic, hand-authored experiments; they do not establish statistical significance, general accuracy parity, or production readiness. Prices are configured estimates, not invoices.

## Inspect the evidence or run the current harness

You can read both datasets and the dated [routing report](experiments/published/routing-2026-09-20.json) and [agent report](experiments/published/agent-bench-2026-09-20.json) **without API keys**. The reports omit complete requests and model answers; the datasets contain the synthetic requests and labels. The [experiment guide](experiments/README.md) explains labeling, metrics, thresholds, mock behavior, and limitations.

To create a new, **paid** run from this checkout:

```bash
uv sync --locked --extra lab
cp -n .env.example .env
# Set TYPESAFE_API_KEY, OPENROUTER_API_KEY, and BASELINE_MODEL in .env
uv run jev-router eval --routers both --diagnostic-stage-two
uv run jev-router agent-bench --live --limit 10
```

`--diagnostic-stage-two` asks for a tool candidate even when the final outcome is `clarify`, giving tool-fit coverage closer to the published routing report. It adds model calls and cost. The published routing report used an earlier schema and domain prompts; the current harness cannot replay it exactly. Compare the two arms **within your new run** rather than expecting the historical numbers. See [protocol details and metric definitions](experiments/README.md#evaluation).

The evaluation writes a timestamped routing report under `experiments/results/`; the agent command writes a separate paired report there. Neither executes real GitHub, browser, file, or calendar tools. `agent-bench` requires `--live` because it calls both model APIs. The CLI also offers `route` and `compare` for individual requests. See [setup and commands](experiments/README.md#installation) before running, especially how to choose a baseline model and price assumptions. Do not overwrite the published reports when making a new run.

## Use the experimental Python SDK

Install it from GitHub in a Python 3.11+ project. The SDK does not require the lab's OpenRouter, Typer, or mock-tool dependencies:

```bash
uv add "jev-tool-router @ git+https://github.com/esinocchi/jev-tool-router.git"
```

Set `TYPESAFE_API_KEY` in your environment or `.env` ([TypeSafe quickstart](https://docs.typesafe.ai/introduction/quickstart)), then describe the tools your application already owns:

```python
import asyncio

from jev_router import JevToolRouter, Tool


async def main() -> None:
    tools = [
        Tool(
            name="search_docs",
            domain="knowledge",
            description="Search documentation by topic.",
            read_only=True,
        ),
        Tool(
            name="create_ticket",
            domain="support",
            description="Create a customer support ticket.",
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

The router chooses a domain, then one tool in that domain, and returns a typed `route`, `clarify`, `no_tool`, or `fallback` decision. It does **not** generate arguments, approve actions, or execute tools. Your application maps the selected name to its trusted registry; its agent generates and validates arguments, and its authorization layer decides whether a call may run. Mutating tools require approval based on trusted metadata regardless of the model's prediction. A routing call may make two TypeSafe API requests and incur charges.

The SDK also accepts tool metadata from an MCP `tools/list` response through `Tool.from_mcp_schema`; this does not connect to an MCP server. See [SDK usage](docs/usage.md) for MCP mapping, outcome handling, confidence, and the current tool-list filtering boundary. [examples/basic.py](examples/basic.py) is runnable. This package is an experimental routing component, not an agent framework or a security boundary.

## Contribute

The most useful next contributions are held-out, realistic routing cases; a larger tool catalog; multi-tool shortlist evaluation; and a comparison with supported provider-native tool search. Keep new runs separate from the dated published reports and explain any changed metric or label. See [CONTRIBUTING.md](CONTRIBUTING.md) for checks and [issues](https://github.com/esinocchi/jev-tool-router/issues) for discussion. Licensed under [MIT](LICENSE).
