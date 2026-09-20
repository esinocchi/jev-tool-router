# Contributing

Keep the router provider-neutral and execution-free. Changes to routing behavior need
hand-authored evaluation cases and tests that cover both the model judgment boundary and
deterministic policy boundary.

Before opening a pull request, run:

```bash
uv sync --locked
uv run ruff format --check .
uv run ruff check .
uv run mypy src
uv run pytest
```

Do not commit API keys, evaluation reports containing user data, or real integration
credentials. Default tests must mock providers and never make network requests. Live
tests remain opt-in with `RUN_LIVE_TESTS=1`.
