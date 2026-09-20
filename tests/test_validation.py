import pytest
from pydantic import ValidationError

from jev_router.baseline_router import BaselineToolOutput
from jev_router.config import Settings
from jev_router.models import ChoiceJudgment, TokenUsage


@pytest.mark.parametrize(
    "probabilities,selected",
    [
        ({"a": 0.2, "b": 0.2}, "a"),
        ({"a": float("nan"), "b": 1}, "a"),
        ({"a": -0.1, "b": 1.1}, "b"),
        ({"a": 0.3, "b": 0.7}, "a"),
        ({"a": 1}, "unoffered"),
    ],
)
def test_invalid_distribution_rejected(probabilities, selected):
    with pytest.raises(ValidationError):
        ChoiceJudgment(selected=selected, probabilities=probabilities, confidence=0.9)


def test_distribution_must_match_all_options():
    judgment = ChoiceJudgment(selected="a", probabilities={"a": 1}, confidence=1)
    with pytest.raises(ValueError):
        judgment.check_options({"a": "A", "b": "B"})


def test_legacy_probability_lists_rejected():
    with pytest.raises(ValidationError):
        BaselineToolOutput(
            selected="a", confidence=1, probabilities=[{"label": "a", "probability": 1}]
        )


def test_cost_uses_both_stages_and_partial_usage_is_unknown():
    settings = Settings(
        _env_file=None, jev_input_price_per_million=2, jev_output_price_per_million=4
    )
    usage = TokenUsage()
    usage.start_call()
    usage.record(100, 10, "test")
    usage.start_call()
    usage.record(200, 20, "test")
    assert settings.cost("jev", usage) == pytest.approx(0.00072)
    usage.start_call()
    assert settings.cost("jev", usage) is None


def test_blank_optional_prices_in_dotenv(tmp_path):
    path = tmp_path / ".env"
    path.write_text("BASELINE_INPUT_PRICE_PER_MILLION=\nBASELINE_OUTPUT_PRICE_PER_MILLION=\n")
    settings = Settings(_env_file=path)
    assert settings.baseline_input_price_per_million is None
    assert settings.cost("baseline", TokenUsage()) is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("jev_domain_confidence_threshold", 1.01),
        ("jev_routing_timeout_ms", 0),
        ("jev_input_price_per_million", -1),
    ],
)
def test_invalid_settings_rejected(field, value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: value})
