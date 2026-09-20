"""Safe error categories; never serialize provider messages or validation input."""

from pydantic import ValidationError


class RoutingFailure(ValueError):
    """An application-defined reason, never constructed from provider error text."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def validation_reason(error: ValidationError) -> str:
    allowed = {
        "json_invalid": "invalid_json",
        "invalid_probability_sum": "invalid_probability_sum",
        "selected_label_missing": "selected_label_missing",
        "selected_label_not_maximum": "selected_label_not_maximum",
    }
    for issue in error.errors(include_input=False, include_context=False, include_url=False):
        if issue["type"] in allowed:
            return allowed[issue["type"]]
    return "invalid_output_schema"
