"""Command-line interface for doc-agent.

Top-level commands:
    doc-agent version
    doc-agent ping
    doc-agent chat        — interactive chat loop (Phase 1 exit criterion)

Subcommand groups:
    doc-agent memory show|clear|pin|unpin
    doc-agent facts list|add|remove|enable|disable|reload
"""

from __future__ import annotations

import sys
from typing import Optional

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

from doc_agent import __version__
from doc_agent.ai.client import AIClient
from doc_agent.ai.tokens import estimate_tokens, format_tokens
from doc_agent.config import settings
from doc_agent.memory import ConversationMemory, FactsMemory, SessionStore

app = typer.Typer(
    name="doc-agent",
    help="Documentation Agent v2 — AI-powered Simulink documentation.",
    add_completion=False,
    no_args_is_help=True,
)
memory_app = typer.Typer(help="Inspect and manage conversation memory.", no_args_is_help=True)
facts_app = typer.Typer(help="Inspect and manage authoritative facts.", no_args_is_help=True)
app.add_typer(memory_app, name="memory")
app.add_typer(facts_app, name="facts")

console = Console()


# ---- helpers -----------------------------------------------------------------
def _load_memory() -> ConversationMemory:
    settings.ensure_data_dir()
    mem = ConversationMemory.load(settings.conversation_path)
    mem.max_history = settings.max_history
    mem.max_token_budget = settings.max_token_budget
    mem.response_token_budget = settings.response_token_budget
    mem.persist_path = settings.conversation_path
    return mem


def _load_facts() -> FactsMemory:
    settings.ensure_data_dir()
    return FactsMemory(settings.facts_path)


def _load_session() -> SessionStore:
    settings.ensure_data_dir()
    return SessionStore(settings.session_path)


def _ensure_key_or_exit() -> None:
    if settings.has_api_key:
        return
    console.print(
        Panel.fit(
            "[red]ANTHROPIC_API_KEY is not set.[/red]\n\n"
            "1. Get a key from https://console.anthropic.com/settings/keys\n"
            "2. Copy [bold].env.example[/bold] to [bold].env[/bold]\n"
            "3. Paste the key after [bold]ANTHROPIC_API_KEY=[/bold]\n"
            "4. Retry the command.",
            title="Setup required",
            border_style="red",
        )
    )
    raise typer.Exit(code=1)


def _build_system_prompt(facts: FactsMemory) -> Optional[str]:
    """Combine project facts into a system prompt block. None if no facts."""
    block = facts.for_prompt(
        max_facts=50, max_tokens=settings.facts_token_budget
    )
    if not block:
        return None
    preamble = (
        "You are doc-agent, an assistant helping document Simulink control models. "
        "Be precise and concise; when uncertain about model details, say so."
    )
    return f"{preamble}\n\n{block}"


# ---- top-level commands ------------------------------------------------------
@app.command()
def version() -> None:
    """Print the doc-agent version."""
    console.print(f"doc-agent [bold cyan]{__version__}[/bold cyan]")


@app.command()
def ping() -> None:
    """Verify connectivity to Anthropic (Phase 0 exit criterion)."""
    console.print(
        f"[dim]Pinging[/dim] [bold]{settings.ai_model}[/bold] "
        f"[dim]via[/dim] {settings.anthropic_base_url}[dim] …[/dim]"
    )
    _ensure_key_or_exit()
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


@app.command()
def chat(
    new: bool = typer.Option(False, "--new", help="Start a fresh session (clears non-pinned history)."),
    no_facts: bool = typer.Option(False, "--no-facts", help="Don't include facts in the system prompt."),
    no_stream: bool = typer.Option(False, "--no-stream", help="Disable streaming (wait for full reply)."),
    max_tokens: int = typer.Option(
        2048, "--max-tokens", help="Max output tokens per turn.", min=64, max=64000
    ),
) -> None:
    """Interactive chat loop. History persists across runs.

    Type `/help` inside the loop for in-session commands.
    Exit with `/exit`, Ctrl-D, or Ctrl-C.
    """
    _ensure_key_or_exit()
    mem = _load_memory()
    facts = _load_facts()

    if new:
        removed = mem.clear(keep_pinned=True)
        mem.save()
        console.print(f"[dim]Cleared {removed} non-pinned messages.[/dim]")

    system = None if no_facts else _build_system_prompt(facts)
    client = AIClient()

    _print_chat_header(client.model, mem, facts, system_enabled=system is not None)

    while True:
        try:
            user_text = _prompt_user()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]bye[/dim]")
            mem.save()
            break

        if not user_text.strip():
            continue

        # In-session commands
        if user_text.startswith("/"):
            should_exit = _handle_slash_command(user_text.strip(), mem, facts)
            if should_exit:
                mem.save()
                break
            continue

        # Append the user turn
        mem.add("user", user_text)
        recent = mem.recent()
        # Sanity: the API requires non-empty user-led message arrays
        if not recent or recent[0].get("role") != "user":
            console.print("[red]Internal: nothing to send (memory empty after trim).[/red]")
            continue

        console.print("[bold cyan]assistant >[/bold cyan] ", end="")
        if no_stream:
            result = client.chat(recent, system=system, max_tokens=max_tokens)
            if not result.ok:
                console.print(f"\n[red]Error:[/red] {result.error}")
                continue
            console.print(result.text)
        else:
            def _emit(chunk: str) -> None:
                console.print(chunk, end="", soft_wrap=True, highlight=False)
                sys.stdout.flush()

            result = client.chat_stream(recent, on_text=_emit, system=system, max_tokens=max_tokens)
            console.print()  # newline after the stream
            if not result.ok:
                console.print(f"[red]Stream error:[/red] {result.error}")
                continue

        mem.add("assistant", result.text)
        mem.save()

        # tiny usage tag for the curious
        u = (
            f"[dim](in {format_tokens(result.input_tokens)}  "
            f"out {format_tokens(result.output_tokens)}  "
            f"latency {result.latency_ms:.0f} ms)[/dim]"
        )
        console.print(u)


# ---- memory subcommands ------------------------------------------------------
@memory_app.command("show")
def memory_show(
    limit: int = typer.Option(10, "--limit", "-n", help="How many recent messages to show."),
) -> None:
    """Show conversation stats and the last N messages."""
    mem = _load_memory()
    s = mem.stats()
    table = Table.grid(padding=(0, 2))
    table.add_column(style="dim", justify="right")
    table.add_column()
    table.add_row("Messages", str(s["messages"]))
    table.add_row("Pinned", str(s["pinned"]))
    table.add_row("Tokens", f"{format_tokens(s['tokens_total'])} / {format_tokens(s['tokens_budget'])}")
    table.add_row("Max history", str(s["max_history"]))
    console.print(table)

    if not len(mem):
        return
    console.rule("[dim]recent[/dim]")
    msgs = mem.all()[-limit:]
    for m in msgs:
        tag = "[yellow]📌[/yellow] " if m.pinned else ""
        role_color = "cyan" if m.role == "assistant" else "green"
        head = f"{tag}[{role_color}]{m.role}[/{role_color}] [dim]#{m.id} · {m.timestamp} · {m.tokens}t[/dim]"
        preview = m.content if len(m.content) <= 240 else m.content[:240].rstrip() + "…"
        console.print(head)
        console.print(f"  {preview}")
        console.print()


@memory_app.command("clear")
def memory_clear(
    all_: bool = typer.Option(False, "--all", help="Drop pinned messages too."),
) -> None:
    """Drop conversation history (keeps pinned by default)."""
    mem = _load_memory()
    removed = mem.clear(keep_pinned=not all_)
    mem.save()
    console.print(f"Removed [bold]{removed}[/bold] message(s).")


@memory_app.command("pin")
def memory_pin(msg_id: int) -> None:
    """Pin a message by id (use `memory show` to see ids)."""
    mem = _load_memory()
    ok = mem.pin(msg_id)
    if ok:
        mem.save()
        console.print(f"Pinned message [bold]#{msg_id}[/bold].")
    else:
        console.print(f"[red]No message with id {msg_id}.[/red]")
        raise typer.Exit(code=1)


@memory_app.command("unpin")
def memory_unpin(msg_id: int) -> None:
    """Unpin a message by id."""
    mem = _load_memory()
    ok = mem.unpin(msg_id)
    if ok:
        mem.save()
        console.print(f"Unpinned message [bold]#{msg_id}[/bold].")
    else:
        console.print(f"[red]No message with id {msg_id}.[/red]")
        raise typer.Exit(code=1)


# ---- facts subcommands ------------------------------------------------------
@facts_app.command("list")
def facts_list() -> None:
    """List all facts, grouped by category."""
    facts = _load_facts()
    s = facts.stats()
    console.print(
        f"[dim]Facts:[/dim] {s['total']} total, {s['enabled']} enabled  "
        f"[dim]File:[/dim] {settings.facts_path}"
    )
    if not len(facts):
        console.print("[dim]No facts yet. Add one with: doc-agent facts add ...[/dim]")
        return
    for cat in facts.DEFAULT_CATEGORIES:
        cat_facts = facts.by_category(cat)
        if not cat_facts:
            continue
        console.rule(f"[bold]{cat}[/bold]")
        table = Table.grid(padding=(0, 1))
        table.add_column(style="dim", no_wrap=True)
        table.add_column(style="dim", no_wrap=True)
        table.add_column()
        for f in sorted(cat_facts, key=lambda f: f.priority):
            tags = " " + " ".join(f"#{k}" for k in f.keywords) if f.keywords else ""
            table.add_row(f.id, f"[{f.priority}]", f.text + tags)
        console.print(table)


@facts_app.command("add")
def facts_add(
    text: str = typer.Argument(..., help="The fact text."),
    category: str = typer.Option("other", "--category", "-c"),
    priority: str = typer.Option("normal", "--priority", "-p"),
    keywords: list[str] = typer.Option([], "--keyword", "-k", help="Tag (repeatable)."),
) -> None:
    """Add a fact. Example: `doc-agent facts add 'Signals use camelCase' -c naming -p high`."""
    facts = _load_facts()
    try:
        f = facts.add(text, category=category, priority=priority, keywords=keywords)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1) from e
    facts.save()
    console.print(f"[green]Added[/green] [{f.priority}] {f.text}  [dim]id={f.id}[/dim]")


@facts_app.command("remove")
def facts_remove(fact_id: str) -> None:
    """Remove a fact by id (10-char hash shown in `facts list`)."""
    facts = _load_facts()
    ok = facts.remove(fact_id)
    if not ok:
        console.print(f"[red]No fact with id {fact_id}.[/red]")
        raise typer.Exit(code=1)
    facts.save()
    console.print(f"Removed fact [bold]{fact_id}[/bold].")


@facts_app.command("reload")
def facts_reload() -> None:
    """Re-read facts.md (use after editing the file by hand)."""
    facts = _load_facts()
    n = facts.load()
    console.print(f"Reloaded [bold]{n}[/bold] fact(s) from {settings.facts_path}")


# ---- chat-loop helpers -------------------------------------------------------
def _prompt_user() -> str:
    console.print("[bold green]you >[/bold green] ", end="")
    return input()


def _print_chat_header(model: str, mem: ConversationMemory, facts: FactsMemory, *, system_enabled: bool) -> None:
    s = mem.stats()
    facts_count = facts.stats()["enabled"]
    parts = [
        f"[bold]doc-agent chat[/bold]  [dim]· {model} ·[/dim]",
        f"[dim]history: {s['messages']} msg ({format_tokens(s['tokens_total'])} tok),"
        f" pinned: {s['pinned']}, facts: {facts_count}{' (active)' if system_enabled else ' (disabled)'}.[/dim]",
        "[dim]/help for commands · /exit or Ctrl-D to quit[/dim]",
    ]
    console.print(Panel("\n".join(parts), border_style="cyan"))


def _handle_slash_command(line: str, mem: ConversationMemory, facts: FactsMemory) -> bool:
    """Process an in-session `/command`. Return True if the chat loop should exit."""
    cmd, *rest = line[1:].split(maxsplit=1)
    arg = rest[0] if rest else ""

    if cmd in ("exit", "quit", "q"):
        return True
    if cmd in ("help", "h", "?"):
        console.print(Markdown(_HELP_TEXT))
        return False
    if cmd == "clear":
        keep = "all" not in arg
        removed = mem.clear(keep_pinned=keep)
        mem.save()
        console.print(f"[dim]cleared {removed} message(s){' (pinned kept)' if keep else ''}[/dim]")
        return False
    if cmd == "pin":
        if not arg.isdigit():
            console.print("[red]Usage: /pin <id>[/red]")
            return False
        ok = mem.pin(int(arg))
        if ok:
            mem.save()
            console.print(f"[dim]pinned #{arg}[/dim]")
        else:
            console.print(f"[red]no message #{arg}[/red]")
        return False
    if cmd == "unpin":
        if not arg.isdigit():
            console.print("[red]Usage: /unpin <id>[/red]")
            return False
        ok = mem.unpin(int(arg))
        if ok:
            mem.save()
            console.print(f"[dim]unpinned #{arg}[/dim]")
        else:
            console.print(f"[red]no message #{arg}[/red]")
        return False
    if cmd == "history":
        n = int(arg) if arg.isdigit() else 5
        for m in mem.all()[-n:]:
            tag = "📌 " if m.pinned else "  "
            console.print(f"{tag}#{m.id} [{m.role}] {m.content[:120]}")
        return False
    if cmd == "facts":
        facts.load()
        block = facts.for_prompt()
        if not block:
            console.print("[dim]no facts[/dim]")
        else:
            console.print(Markdown(block))
        return False
    if cmd == "stats":
        s = mem.stats()
        console.print(
            f"messages: {s['messages']}  pinned: {s['pinned']}  "
            f"tokens: {format_tokens(s['tokens_total'])} / {format_tokens(s['tokens_budget'])}"
        )
        return False
    console.print(f"[red]unknown command:[/red] /{cmd}  (try /help)")
    return False


_HELP_TEXT = """
**In-session commands** (prefix any input with `/`):

- `/help` — show this list
- `/exit` — leave the chat (also Ctrl-D)
- `/clear` — drop non-pinned history (`/clear all` drops pinned too)
- `/pin <id>` — pin a message by id
- `/unpin <id>` — unpin a message
- `/history [N]` — show the last N messages with their ids (default 5)
- `/facts` — show the active facts block
- `/stats` — current memory / token stats
"""


if __name__ == "__main__":
    app()
