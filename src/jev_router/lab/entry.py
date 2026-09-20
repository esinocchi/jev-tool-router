"""Optional CLI entry point with a useful install hint for SDK-only users."""


def main() -> None:
    try:
        from jev_router.lab.cli import app
    except ModuleNotFoundError as error:
        if error.name in {"openai", "typer"}:
            raise SystemExit('Install the experiment CLI with "jev-tool-router[lab]"') from None
        raise
    app()
