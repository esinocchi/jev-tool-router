# Contributing

Keep the router provider-neutral and execution-free. Changes to routing behavior need
hand-authored evaluation cases and tests that cover both the model judgment boundary and
deterministic policy boundary.

The public SDK lives in `src/jev_router/`; baseline routing, mocks, metrics, and the
CLI live in `src/jev_router/lab/`. The hand-authored dataset and detailed benchmark
instructions live in `experiments/`. A contribution to policy should add a focused
unit test. A change to measured behavior should also update the relevant cases or
metric definition and explain the expected effect in the pull request.

Before opening a pull request, run:

```bash
uv sync --locked
uv run ruff format --check .
uv run ruff check .
uv run mypy src
uv run pytest
uv build
```

Do not commit API keys, evaluation reports containing user data, or real integration
credentials. Default tests must mock providers and never make network requests. Live
tests remain opt-in with `RUN_LIVE_TESTS=1`.
