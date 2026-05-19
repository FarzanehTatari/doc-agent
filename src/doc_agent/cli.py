"""Command-line interface for doc-agent."""

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from doc_agent import __version__
from doc_agent.ai.client import AIClient
from doc_agent.config import settings

app = typer.Typer(
    name="doc-agent",
    help="Documentation Agent v2 — AI-powered Simulink documentation.",
    add_completion=False,
    no_args_is_help=True,
)
console = Console()


@app.command()
def version() -> None:
    """Print the doc-agent version."""
    console.print(f"doc-agent [bold cyan]{__version__}[/bold cyan]")


@app.command()
def ping() -> None:
    """Verify connectivity to Anthropic.

    Exit code 0 on success, 1 on any failure (missing key, network, auth).
    This is the Phase 0 exit criterion.
    """
    console.print(
        f"[dim]Pinging[/dim] [bold]{settings.ai_model}[/bold] "
        f"[dim]via[/dim] {settings.anthropic_base_url}[dim] …[/dim]"
    )

    if not settings.has_api_key:
        console.print(
            Panel.fit(
                "[red]ANTHROPIC_API_KEY is not set.[/red]\n\n"
                "1. Get a key from https://console.anthropic.com/settings/keys\n"
                "2. Copy [bold].env.example[/bold] to [bold].env[/bold]\n"
                "3. Paste the key after [bold]ANTHROPIC_API_KEY=[/bold]\n"
                "4. Run [bold]doc-agent ping[/bold] again.",
                title="Setup required",
                border_style="red",
            )
        )
        raise typer.Exit(code=1)

    try:
        client = AIClient()
        result = client.ping()
    except Exception as e:  # noqa: BLE001
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(code=1) from e

    table = Table.grid(padding=(0, 2))
    table.add_column(style="dim", justify="right")
    table.add_column()
    table.add_row(
        "Status",
        "[bold green]✓ Connected[/bold green]" if result.ok else "[bold red]✗ Failed[/bold red]",
    )
    table.add_row("Model", result.model)
    table.add_row("Latency", f"{result.latency_ms:.0f} ms")
    if result.reply:
        table.add_row("Reply", f"[italic]{result.reply!r}[/italic]")
    if result.error:
        table.add_row("Error", f"[red]{result.error}[/red]")
    console.print(table)

    raise typer.Exit(code=0 if result.ok else 1)


if __name__ == "__main__":
    app()
