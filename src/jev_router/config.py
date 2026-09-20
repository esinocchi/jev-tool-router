"""Validated configuration; secret values never enter reports."""

from typing import Annotated

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from jev_router.models import Probability, TokenUsage

Price = Annotated[float, Field(ge=0, allow_inf_nan=False)]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", env_ignore_empty=True)

    typesafe_api_key: SecretStr | None = None
    openrouter_api_key: SecretStr | None = None
    baseline_model: str = ""
    jev_model: str = "jev-latest"
    jev_domain_confidence_threshold: Probability = 0.65
    jev_tool_confidence_threshold: Probability = 0.70
    jev_clarification_threshold: Probability = 0.75
    jev_mutation_threshold: Probability = 0.60
    jev_high_consequence_threshold: Probability = 0.50
    jev_routing_timeout_ms: int = Field(default=3000, gt=0)
    baseline_routing_timeout_ms: int = Field(default=30000, gt=0)
    log_full_requests: bool = False
    diagnostic_stage_two: bool = False
    log_request_preview_chars: int = Field(default=0, ge=0, le=200)
    jev_input_price_per_million: Price | None = None
    jev_output_price_per_million: Price | None = None
    baseline_input_price_per_million: Price | None = None
    baseline_output_price_per_million: Price | None = None

    def cost(self, router: str, usage: TokenUsage) -> float | None:
        prefix = "jev" if router == "jev" else "baseline"
        input_price: float | None = getattr(self, f"{prefix}_input_price_per_million")
        output_price: float | None = getattr(self, f"{prefix}_output_price_per_million")
        if input_price is None or output_price is None or not usage.complete:
            return None
        return (usage.input_tokens * input_price + usage.output_tokens * output_price) / 1_000_000

    def report_config(self) -> dict[str, bool | str | float | int | None]:
        fields = (
            "jev_model",
            "baseline_model",
            "jev_domain_confidence_threshold",
            "jev_tool_confidence_threshold",
            "jev_clarification_threshold",
            "jev_mutation_threshold",
            "jev_high_consequence_threshold",
            "jev_routing_timeout_ms",
            "baseline_routing_timeout_ms",
            "diagnostic_stage_two",
            "jev_input_price_per_million",
            "jev_output_price_per_million",
            "baseline_input_price_per_million",
            "baseline_output_price_per_million",
        )
        return {name: getattr(self, name) for name in fields}
