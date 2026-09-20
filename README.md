# Jev Tool Router

**Can a specialist model choose an agent's tools?** This repository contains two small, documented experiments, a runnable benchmark harness, and an experimental Python SDK built around TypeSafe AI's Jev. Start with the [case study](docs/case-study.md) for the story, or use the links below to inspect the evidence behind it.

| Experiment | Question | Shared 100-prompt result | Evidence |
| --- | --- | --- | --- |
| **Routing only · 100 prompts × 3** | Can Jev make the domain/tool decision instead of a general LLM router? | Median tool fit: 76/81 versus 77/81. Jev mean routing latency: 0.419 s versus 2.459 s; estimated cost: $0.00486 versus $0.03673. | [Cases](experiments/shared_cases.json) · [Runs 1–3](docs/case-study.md#test-1-jev-makes-the-routing-decision) · [Figure](docs/assets/routing-benchmark-100.svg) · [Method](experiments/README.md#evaluation) |
| **Agent loop · same 100 prompts × 3** | Does a Jev prefilter help when Luna still makes the tool call? | Median read-task success: 37/47 versus 35/47. Jev filtering raised mean read-task latency from 3.011 s to 3.737 s but reduced estimated total cost from $0.02847 to $0.02096. | [Runs 1–3](docs/case-study.md#test-2-jev-filters-tools-before-luna) · [Figure](docs/assets/agent-benchmark-100.svg) · [Method](experiments/README.md#agent-task-benchmark) |

Both comparisons used `openai/gpt-5.6-luna` through OpenRouter as the general-model baseline. They do not compare Jev with every general LLM. The older [86-case routing](experiments/published/routing-2026-09-20.json) and [ten-task agent](experiments/published/agent-bench-2026-09-20.json) reports remain archived as historical results.

These are **different tests**:

```text
Routing only: request → Jev or Luna router → domain/tool decision → stop
Agent loop:   request → Jev filters tools → Luna chooses a call → mock result
              request → Luna sees all tools → Luna chooses a call → mock result
```

Across three routing runs, Jev picked a suitable tool in **76/81** tool-fit cases each time; Luna scored **76–77/81**. Median mean routing latency was **419 ms versus 2,459 ms**; median estimated total cost was **$0.00486 versus $0.03673**. Jev returned a ready-to-use correct route in **41** cases versus Luna's **45–46**. Tool relevance and willingness to proceed are separate measures.

Across three agent runs, median read-task success was **37/47 with Jev versus 35/47 with all tools**. Jev filtering raised median mean read-task latency from **3.011 to 3.737 seconds** and reduced median estimated total cost from **$0.02847 to $0.02096**. The read-task slowdown and cost saving appeared in every run. [The case study](docs/case-study.md) shows ranges and the category breakdown.

The promising hypothesis is that specialist routing could help **closer to a provider's tool-selection path**, where the agent would not repeat the selection work. This repo cannot replace a provider model's internal automatic tool selection. It tests the app-level prefilter that today's tool APIs permit, but not provider-native tool search. The runs are synthetic and do not establish statistical significance, general accuracy parity, or production readiness. Prices are configured estimates, not invoices.

## Inspect the evidence or run the current harness

You can read the [shared dataset](experiments/shared_cases.json) and the reports above **without API keys**. The reports omit complete requests and model answers; the dataset contains the synthetic requests and labels. The [experiment guide](experiments/README.md) explains labeling, metrics, thresholds, mock behavior, and limitations.

To create a new, **paid** run from this checkout:

```bash
uv sync --locked --extra lab
cp -n .env.example .env
# Set TYPESAFE_API_KEY, OPENROUTER_API_KEY, and BASELINE_MODEL in .env
uv run jev-router eval --routers both --diagnostic-stage-two
uv run jev-router agent-bench --live
```

`--diagnostic-stage-two` asks for a tool candidate even when the final outcome is `clarify`, giving tool-fit coverage matching the published routing reports. It adds model calls and cost. The older 86-case report used an earlier schema and domain prompts; the current harness cannot replay that historical result exactly. Compare the two arms **within your new run**. See [protocol details and metric definitions](experiments/README.md#evaluation).

The shared set includes reads, no-tool questions, ambiguous requests, approval-gated actions, and unavailable tools. The agent report separates these categories in `by_expectation`. Its overall mean latency includes all categories; use the `complete` category for read-task latency. This category average includes unsuccessful attempts.

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
