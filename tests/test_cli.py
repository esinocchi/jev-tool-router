import json

import pytest
from typer.testing import CliRunner

from jev_router.cli import app

runner = CliRunner()


def test_route_without_key_json(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    result = runner.invoke(app, ["route", "A private request", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert data["decision"]["fallback_reason"] == "missing_typesafe_api_key"
    assert data["execution"] is None
    assert "A private request" not in result.output


def test_compare_without_baseline_configuration(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    for key in ("TYPESAFE_API_KEY", "OPENAI_API_KEY", "BASELINE_MODEL"):
        monkeypatch.delenv(key, raising=False)
    result = runner.invoke(app, ["compare", "Check calendar", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert data["baseline"]["fallback_reason"] == "missing_baseline_configuration"
    assert data["agreement"] is None


def test_invalid_config_does_not_echo_value(monkeypatch):
    monkeypatch.setenv("JEV_TOOL_CONFIDENCE_THRESHOLD", "SECRET-invalid-value")
    result = runner.invoke(app, ["route", "test"])
    assert result.exit_code != 0
    assert "SECRET-invalid-value" not in result.output


def test_eval_report_without_credentials(monkeypatch, tmp_path):
    from pathlib import Path

    dataset = Path("evals/routing_cases.json").resolve()
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    result = runner.invoke(app, ["eval", "--dataset", str(dataset), "--routers", "jev", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert Path(data["report_path"]).exists()
    assert data["report"]["routers"]["jev"]["metrics"]["case_count"] >= 60


def test_oversized_eval_input_rejected_without_leaking_text(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    private = "PRIVATE_EVALUATION_TEXT" * 1000
    path = tmp_path / "cases.json"
    path.write_text(
        json.dumps(
            [
                {
                    "id": "oversized",
                    "request": private,
                    "expected_domain": "none",
                    "expected_tools": [],
                    "expected_outcome": "no_tool",
                    "requires_approval": False,
                    "expected_mutation": False,
                    "expected_high_consequence": False,
                }
            ]
        )
    )
    result = runner.invoke(app, ["eval", "--dataset", str(path)])
    assert result.exit_code == 2
    assert "PRIVATE_EVALUATION_TEXT" not in result.output
    assert "PRIVATE_EVALUATION_TEXT" not in str(result.exception)


@pytest.mark.parametrize(
    "arguments,status",
    [([], "not_requested"), (["--execute"], "approval_required"), (["--approve"], "simulated")],
)
def test_cli_mock_execution_approval(monkeypatch, tmp_path, arguments, status):
    from jev_router.models import RoutingDecision

    monkeypatch.chdir(tmp_path)

    async def fake_route(self, request):
        return RoutingDecision(
            router="jev",
            model="mock",
            outcome="route",
            selected_domain="files",
            selected_tool="files_delete",
            requires_approval=False,
        )

    monkeypatch.setattr("jev_router.cli.JevRouter.route", fake_route)
    result = runner.invoke(app, ["route", "Delete /tmp/a", "--json", *arguments])
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert data["execution_status"] == status
    if status == "simulated":
        assert data["execution"]["simulated"] is True
        assert data["execution"]["arguments"]["target"] == "mock://files_delete"
    else:
        assert data["execution"] is None
