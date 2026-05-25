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
from pathlib import Path as _Path
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
rag_app = typer.Typer(help="Manage the RAG document library.", no_args_is_help=True)
app.add_typer(memory_app, name="memory")
app.add_typer(facts_app, name="facts")
app.add_typer(rag_app, name="rag")

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


def _load_rag():
    """Lazy import so users without chromadb installed can still run other commands."""
    settings.ensure_data_dir()
    from doc_agent.rag import RAGManager

    return RAGManager(
        store_path=settings.rag_dir,
        collection_name=settings.rag_collection,
        chunk_size=settings.rag_chunk_size,
        chunk_overlap=settings.rag_chunk_overlap,
    )


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


def _build_system_prompt(facts: FactsMemory, rag_block: str | None = None) -> Optional[str]:
    """Combine project facts (always) + retrieved RAG chunks (when present)."""
    facts_block = facts.for_prompt(max_facts=50, max_tokens=settings.facts_token_budget)
    pieces: list[str] = []
    preamble = (
        "You are doc-agent, an assistant helping document Simulink control models. "
        "Be precise and concise; when uncertain about model details, say so."
    )
    pieces.append(preamble)
    if facts_block:
        pieces.append(facts_block)
    if rag_block:
        pieces.append(rag_block)
    if len(pieces) == 1:
        return None  # nothing project-specific to inject
    return "\n\n".join(pieces)


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
    no_rag: bool = typer.Option(False, "--no-rag", help="Don't retrieve from the RAG library."),
    no_stream: bool = typer.Option(False, "--no-stream", help="Disable streaming (wait for full reply)."),
    max_tokens: int = typer.Option(
        2048, "--max-tokens", help="Max output tokens per turn.", min=64, max=64000
    ),
) -> None:
    """Interactive chat loop. History persists across runs.

    On each turn, project facts plus relevant RAG chunks are prepended to the
    system prompt. Type `/help` inside the loop for in-session commands.
    Exit with `/exit`, Ctrl-D, or Ctrl-C.
    """
    _ensure_key_or_exit()
    mem = _load_memory()
    facts = _load_facts()

    rag = None
    if settings.rag_enabled and not no_rag:
        try:
            rag = _load_rag()
            rag_stats = rag.stats()
            if rag_stats["chunks"] == 0:
                rag = None  # empty library — skip retrieval calls
        except Exception as e:  # noqa: BLE001
            console.print(f"[dim yellow]RAG disabled: {e}[/dim yellow]")
            rag = None

    if new:
        removed = mem.clear(keep_pinned=True)
        mem.save()
        console.print(f"[dim]Cleared {removed} non-pinned messages.[/dim]")

    client = AIClient()
    _print_chat_header(client.model, mem, facts, rag=rag, facts_enabled=not no_facts)

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

        # Build a fresh system prompt per turn — RAG context is query-specific.
        rag_block = None
        rag_results = []
        if rag is not None:
            try:
                rag_results = rag.search(
                    user_text, top_k=settings.rag_top_k, min_score=settings.rag_min_score
                )
                if rag_results:
                    rag_block = rag.format_for_prompt(
                        user_text,
                        top_k=settings.rag_top_k,
                        min_score=settings.rag_min_score,
                        max_tokens=settings.rag_token_budget,
                    )
            except Exception as e:  # noqa: BLE001
                console.print(f"[dim yellow]RAG search failed: {e}[/dim yellow]")

        system = None if no_facts and not rag_block else _build_system_prompt(
            facts if not no_facts else FactsMemory(settings.facts_path.with_suffix(".empty.md")),
            rag_block=rag_block,
        )

        # Append the user turn
        mem.add("user", user_text)
        recent = mem.recent()
        if not recent or recent[0].get("role") != "user":
            console.print("[red]Internal: nothing to send (memory empty after trim).[/red]")
            continue

        if rag_results:
            cites = ", ".join(r.citation for r in rag_results)
            console.print(f"[dim]retrieved {len(rag_results)} chunk(s): {cites}[/dim]")

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
            console.print()
            if not result.ok:
                console.print(f"[red]Stream error:[/red] {result.error}")
                continue

        mem.add("assistant", result.text)
        mem.save()

        # tiny usage tag
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


# ---- rag subcommands --------------------------------------------------------
@rag_app.command("add")
def rag_add(
    path: str = typer.Argument(..., help="Path to a file: PDF, DOCX, Markdown, text, or code."),
) -> None:
    """Chunk a file and index it. Re-adding the same filename replaces prior chunks."""
    rag = _load_rag()
    p = _Path(path)
    if not p.exists():
        console.print(f"[red]No such file:[/red] {path}")
        raise typer.Exit(code=1)
    try:
        out = rag.add_document(p, progress=lambda m: console.print(f"[dim]{m}[/dim]"))
    except Exception as e:  # noqa: BLE001
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(code=1) from e
    verb = "Replaced" if out["replaced"] else "Indexed"
    console.print(f"[green]{verb}[/green] [bold]{out['source']}[/bold] → {out['chunks']} chunks")


@rag_app.command("list")
def rag_list() -> None:
    """List indexed documents with their chunk counts."""
    rag = _load_rag()
    sources = rag.list_documents()
    if not sources:
        console.print("[dim]No documents indexed. Try `doc-agent rag add <file>`.[/dim]")
        return
    table = Table(show_header=True, header_style="bold")
    table.add_column("Source", no_wrap=False)
    table.add_column("Chunks", justify="right")
    for name, n in sorted(sources.items()):
        table.add_row(name, str(n))
    console.print(table)
    s = rag.stats()
    console.print(
        f"[dim]Total:[/dim] {s['sources']} docs · {s['chunks']} chunks  "
        f"[dim]Store:[/dim] {s['path']}"
    )


@rag_app.command("remove")
def rag_remove(source: str = typer.Argument(..., help="Source filename (as shown in `rag list`).")) -> None:
    """Remove every chunk from a given source."""
    rag = _load_rag()
    n = rag.remove_document(source)
    if n == 0:
        console.print(f"[red]No chunks found for source:[/red] {source}")
        raise typer.Exit(code=1)
    console.print(f"Removed [bold]{n}[/bold] chunk(s) for {source}.")


@rag_app.command("search")
def rag_search(
    query: str = typer.Argument(..., help="Search query."),
    top_k: int = typer.Option(5, "--top-k", "-k", min=1, max=50),
    min_score: float = typer.Option(0.0, "--min-score", min=0.0, max=1.0),
) -> None:
    """Retrieve the top-k most similar chunks. No LLM call — pure retrieval."""
    rag = _load_rag()
    results = rag.search(query, top_k=top_k, min_score=min_score)
    if not results:
        console.print("[dim]No matches above the score threshold.[/dim]")
        return
    for i, r in enumerate(results, start=1):
        console.rule(f"#{i}  [yellow]{r.citation}[/yellow]  [dim](score {r.score:.3f})[/dim]")
        preview = r.text if len(r.text) <= 800 else r.text[:800].rstrip() + "…"
        console.print(preview)


@rag_app.command("stats")
def rag_stats() -> None:
    """Show counts and storage path."""
    rag = _load_rag()
    s = rag.stats()
    table = Table.grid(padding=(0, 2))
    table.add_column(style="dim", justify="right")
    table.add_column()
    table.add_row("Sources", str(s["sources"]))
    table.add_row("Chunks", str(s["chunks"]))
    table.add_row("Collection", s["collection"])
    table.add_row("Path", s["path"])
    console.print(table)


@rag_app.command("clear")
def rag_clear(
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    """Wipe the entire RAG library. Irreversible — uploaded files are NOT deleted."""
    rag = _load_rag()
    if not yes:
        confirm = typer.confirm("Drop ALL indexed chunks? Your original files are not touched.")
        if not confirm:
            console.print("[dim]aborted[/dim]")
            raise typer.Exit(code=0)
    rag.clear()
    console.print("[green]Cleared.[/green]")


# ---- extract command (Phase 2 — MATLAB bridge) -----------------------------
@app.command()
def extract(
    slx_path: str = typer.Argument(..., help="Path to a .slx file."),
    out: str = typer.Option(
        None, "--out", "-o",
        help="Output JSON path. Defaults to data_dir/extracted/<modelname>.json.",
    ),
) -> None:
    """Run MATLAB extractor on a .slx and validate the JSON output."""
    p = _Path(slx_path)
    if not p.exists():
        console.print(f"[red]No such file:[/red] {slx_path}")
        raise typer.Exit(code=1)

    settings.ensure_data_dir()
    settings.extracted_dir.mkdir(parents=True, exist_ok=True)
    out_path = _Path(out) if out else settings.extracted_dir / f"{p.stem}.json"

    try:
        from doc_agent.extract import MatlabBridge
    except Exception as e:  # noqa: BLE001
        console.print(f"[red]Cannot import extract module:[/red] {e}")
        raise typer.Exit(code=1) from e

    try:
        bridge = MatlabBridge()
        console.print(f"[dim]MATLAB:[/dim] {bridge.matlab}")
        console.print(f"[dim]Running extract_slx → {out_path}[/dim]")
        model = bridge.extract_slx(p, out_path)
    except Exception as e:  # noqa: BLE001
        console.print(f"[red]Extraction failed:[/red] {e}")
        raise typer.Exit(code=1) from e

    table = Table.grid(padding=(0, 2))
    table.add_column(style="dim", justify="right")
    table.add_column()
    table.add_row("Model", model.model.name)
    table.add_row("Schema", str(model.schema_version))
    table.add_row("Subsystems", str(len(model.subsystems)))
    table.add_row("Signals", str(len(model.signals)))
    table.add_row("Block types", ", ".join(sorted(model.all_block_types())) or "(none)")
    if model.data_dictionary:
        table.add_row("Data dict", model.data_dictionary.name)
    table.add_row("Output", str(out_path))
    console.print(table)


@app.command()
def generate(
    extracted_json: str = typer.Argument(
        ..., help="Path to canonical JSON from `doc-agent extract`."
    ),
    subsystem: str = typer.Option(
        None, "--subsystem", "-s",
        help="Subsystem path. Default: first one in the model.",
    ),
    kind: str = typer.Option("autodoc", "--kind", "-k", help="autodoc | sysreq | unitreq"),
    out: str = typer.Option(None, "--out", "-o", help="Output Markdown path."),
    no_rag: bool = typer.Option(False, "--no-rag"),
    no_facts: bool = typer.Option(False, "--no-facts"),
    verbose: bool = typer.Option(False, "--verbose", "-v",
                                  help="Print tool calls as they happen."),
    max_tokens: int = typer.Option(4096, "--max-tokens", min=256, max=64000),
) -> None:
    """Generate documentation for one subsystem from extracted canonical JSON."""
    _ensure_key_or_exit()

    p = _Path(extracted_json)
    if not p.exists():
        console.print(f"[red]No such file:[/red] {extracted_json}")
        raise typer.Exit(code=1)

    from doc_agent.extract import MatlabBridge
    from doc_agent.generate import generate_for_subsystem
    from doc_agent.generate import get as get_deliverable

    try:
        canonical = MatlabBridge.load_canonical(p)
    except Exception as e:  # noqa: BLE001
        console.print(f"[red]Invalid canonical JSON:[/red] {e}")
        raise typer.Exit(code=1) from e

    if not canonical.subsystems:
        console.print(f"[red]No subsystems in {extracted_json}[/red]")
        raise typer.Exit(code=1)

    if subsystem is None:
        subsystem = canonical.subsystems[0].path
        console.print(
            f"[dim]Target:[/dim] [bold]{subsystem}[/bold] "
            f"[dim](first subsystem; use --subsystem to override)[/dim]"
        )

    try:
        deliverable = get_deliverable(kind)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1) from e

    # RAG is optional — skip if no library indexed
    rag = None
    if not no_rag:
        try:
            r = _load_rag()
            if r.stats()["chunks"] > 0:
                rag = r
        except Exception:  # noqa: BLE001
            rag = None

    facts = None if no_facts else _load_facts()
    client = AIClient()

    console.print(
        f"[dim]Generating[/dim] [bold]{deliverable.title}[/bold] "
        f"[dim]for[/dim] [bold]{subsystem}[/bold] "
        f"[dim]using[/dim] [bold]{client.model}[/bold]"
    )

    on_tool = None
    if verbose:
        def on_tool(name, inp):
            inp_preview = ", ".join(f"{k}={v!r}" for k, v in (inp or {}).items())
            console.print(f"  [dim]→ tool:[/dim] [cyan]{name}[/cyan]({inp_preview})")

    try:
        doc = generate_for_subsystem(
            client=client,
            canonical=canonical,
            subsystem_path=subsystem,
            deliverable=deliverable,
            rag=rag,
            facts=facts,
            max_tokens=max_tokens,
            on_tool=on_tool,
        )
    except Exception as e:  # noqa: BLE001
        console.print(f"[red]Generation failed:[/red] {e}")
        raise typer.Exit(code=1) from e

    if doc.error:
        console.print(f"[yellow]Note:[/yellow] {doc.error}")

    # Same path scheme as `generate-all`:
    #   <data_dir>/generated/<model_name>/<subsystem>_<kind>.md
    # so running either command updates the same file for the same target.
    settings.ensure_data_dir()
    if out:
        out_path = _Path(out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
    else:
        out_dir = settings.data_dir / "generated" / canonical.model.name
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / doc.filename(strip_model_prefix=canonical.model.name)
    out_path.write_text(doc.to_markdown(), encoding="utf-8")

    table = Table.grid(padding=(0, 2))
    table.add_column(style="dim", justify="right")
    table.add_column()
    table.add_row("Subsystem", subsystem)
    table.add_row("Deliverable", deliverable.title)
    table.add_row("Iterations", str(doc.iterations))
    table.add_row("Tool calls", str(doc.tool_calls_made))
    table.add_row("Tokens", f"in {format_tokens(doc.input_tokens)}  out {format_tokens(doc.output_tokens)}")
    if doc.citations:
        table.add_row("Citations", ", ".join(doc.citations))
    table.add_row("Output", str(out_path))
    console.print(table)


@app.command()
def export(
    source: str = typer.Argument(
        ..., help="A generated-docs directory (or a single .md file)."
    ),
    format: str = typer.Option(
        "html", "--format", "-f",
        help="html | docx | pdf | all",
    ),
    out: str = typer.Option(
        None, "--out", "-o",
        help="Output file path (or directory if --format=all). Default: alongside source.",
    ),
) -> None:
    """Consolidate generated Markdown into HTML, DOCX, and/or PDF."""
    from doc_agent.export import (
        Bundle,
        pdf_is_available,
        write_docx,
        write_html,
        write_pdf,
    )

    src = _Path(source)
    if not src.exists():
        console.print(f"[red]No such path:[/red] {source}")
        raise typer.Exit(code=1)

    bundle = (
        Bundle.from_single_file(src) if src.is_file() else Bundle.from_directory(src)
    )
    if bundle.is_empty():
        console.print(f"[red]No .md files found in {source}[/red]")
        raise typer.Exit(code=1)

    fmt = (format or "html").lower()
    valid = {"html", "docx", "pdf", "all"}
    if fmt not in valid:
        console.print(
            f"[red]Unknown format: {format}.[/red] Use one of: {', '.join(sorted(valid))}."
        )
        raise typer.Exit(code=1)

    # Resolve output base
    if out:
        out_path = _Path(out)
    else:
        parent = src.parent if src.is_file() else src
        stem = bundle.model_name if not src.is_file() else src.stem
        out_path = parent / stem  # extension appended per-format below

    table = Table.grid(padding=(0, 2))
    table.add_column(style="dim", justify="right")
    table.add_column()
    table.add_row("Model", bundle.model_name)
    table.add_row("Entries", str(len(bundle)))

    want_html = fmt in ("html", "all")
    want_docx = fmt in ("docx", "all")
    want_pdf  = fmt in ("pdf", "all")

    # If user asked for PDF specifically and weasyprint isn't available,
    # error early with the install hint rather than after writing other files.
    if fmt == "pdf" and not pdf_is_available():
        from doc_agent.export.pdf_writer import _INSTALL_HINT
        console.print(f"[red]{_INSTALL_HINT}[/red]")
        raise typer.Exit(code=1)

    if want_html:
        html_path = out_path.with_suffix(".html") if out_path.suffix != ".html" else out_path
        write_html(bundle, html_path)
        table.add_row("HTML", str(html_path))
    if want_docx:
        docx_path = out_path.with_suffix(".docx") if out_path.suffix != ".docx" else out_path
        write_docx(bundle, docx_path)
        table.add_row("DOCX", str(docx_path))
    if want_pdf:
        if pdf_is_available():
            pdf_path = out_path.with_suffix(".pdf") if out_path.suffix != ".pdf" else out_path
            try:
                write_pdf(bundle, pdf_path)
                table.add_row("PDF", str(pdf_path))
            except Exception as e:  # noqa: BLE001
                table.add_row("PDF", f"[red]failed: {e}[/red]")
        else:
            table.add_row("PDF", "[yellow]skipped (weasyprint not installed)[/yellow]")

    console.print(table)


@app.command("generate-all")
def generate_all_cmd(
    extracted_json: str = typer.Argument(
        ..., help="Path to canonical JSON from `doc-agent extract`."
    ),
    kinds: str = typer.Option(
        "autodoc", "--kinds", "-k",
        help="Comma-separated deliverable kinds: autodoc,sysreq,unitreq",
    ),
    out_dir: str = typer.Option(
        None, "--out-dir", "-d",
        help="Output directory. Default: project_lib/generated/<model_name>/.",
    ),
    no_rag: bool = typer.Option(False, "--no-rag"),
    no_facts: bool = typer.Option(False, "--no-facts"),
    verbose: bool = typer.Option(False, "--verbose", "-v",
                                  help="Print each tool call as it happens."),
    max_iterations: int = typer.Option(12, "--max-iterations", min=1, max=50),
    max_tokens: int = typer.Option(4096, "--max-tokens", min=256, max=64000),
) -> None:
    """Walk every subsystem bottom-up; run every requested deliverable per subsystem."""
    _ensure_key_or_exit()

    p = _Path(extracted_json)
    if not p.exists():
        console.print(f"[red]No such file:[/red] {extracted_json}")
        raise typer.Exit(code=1)

    from doc_agent.extract import MatlabBridge
    from doc_agent.generate import generate_all, write_run_outputs

    try:
        canonical = MatlabBridge.load_canonical(p)
    except Exception as e:  # noqa: BLE001
        console.print(f"[red]Invalid canonical JSON:[/red] {e}")
        raise typer.Exit(code=1) from e

    if not canonical.subsystems:
        console.print(f"[red]No subsystems in {extracted_json}[/red]")
        raise typer.Exit(code=1)

    kind_list = [k.strip().lower() for k in kinds.split(",") if k.strip()]
    if not kind_list:
        console.print("[red]No deliverable kinds given. Use --kinds autodoc,sysreq,unitreq[/red]")
        raise typer.Exit(code=1)

    rag = None
    if not no_rag:
        try:
            r = _load_rag()
            if r.stats()["chunks"] > 0:
                rag = r
        except Exception:  # noqa: BLE001
            rag = None
    facts = None if no_facts else _load_facts()

    client = AIClient()

    target_dir = (
        _Path(out_dir)
        if out_dir
        else settings.data_dir / "generated" / canonical.model.name
    )
    target_dir.mkdir(parents=True, exist_ok=True)

    total_runs = len(canonical.subsystems) * len(kind_list)
    console.print(
        f"[dim]Model:[/dim] [bold]{canonical.model.name}[/bold]  "
        f"[dim]subsystems:[/dim] {len(canonical.subsystems)}  "
        f"[dim]kinds:[/dim] {', '.join(kind_list)}  "
        f"[dim]total runs:[/dim] {total_runs}"
    )
    console.print(f"[dim]Out dir:[/dim] {target_dir}")

    on_tool = None
    if verbose:
        def on_tool(name, inp):
            inp_preview = ", ".join(f"{k}={v!r}" for k, v in (inp or {}).items())
            console.print(f"    [dim]→[/dim] [cyan]{name}[/cyan]({inp_preview})")

    def on_progress(current, total, sub_path, kind, doc):
        if doc is None:
            console.print(f"[red][{current}/{total}][/red] {sub_path} · {kind} — [red]FAILED[/red]")
        else:
            console.print(
                f"[green][{current}/{total}][/green] {sub_path} · {kind}  "
                f"[dim]({doc.iterations} iter, {doc.tool_calls_made} tool, "
                f"{format_tokens(doc.input_tokens)}+{format_tokens(doc.output_tokens)} tok)[/dim]"
            )

    try:
        summary = generate_all(
            client=client,
            canonical=canonical,
            kinds=kind_list,
            rag=rag,
            facts=facts,
            max_tokens=max_tokens,
            max_iterations=max_iterations,
            on_progress=on_progress,
            on_tool=on_tool,
        )
    except Exception as e:  # noqa: BLE001
        console.print(f"[red]generate_all failed:[/red] {e}")
        raise typer.Exit(code=1) from e

    index_path = write_run_outputs(summary, target_dir)

    table = Table.grid(padding=(0, 2))
    table.add_column(style="dim", justify="right")
    table.add_column()
    table.add_row("Model", summary.model)
    table.add_row("Docs", str(len(summary.docs)))
    table.add_row("Tool calls", str(summary.total_tool_calls))
    table.add_row(
        "Tokens",
        f"in {format_tokens(summary.total_input_tokens)}  "
        f"out {format_tokens(summary.total_output_tokens)}",
    )
    table.add_row("Elapsed", f"{summary.elapsed_s:.1f} s")
    if summary.failures:
        table.add_row("Failures", str(len(summary.failures)))
    table.add_row("Index", str(index_path))
    console.print(table)

    if summary.failures:
        console.print("\n[yellow]Failures:[/yellow]")
        for f in summary.failures:
            console.print(f"  • {f}")
        raise typer.Exit(code=1)


@app.command("build-test-model")
def build_test_model(
    out_dir: str = typer.Option(
        None, "--out-dir", "-d",
        help="Where to write VSEModel.slx + .sldd. Default: examples/test_model/",
    ),
) -> None:
    """Generate the toy VSE Simulink model + data dictionary (calls MATLAB)."""
    settings.ensure_data_dir()
    target = _Path(out_dir) if out_dir else _Path.cwd() / "examples" / "test_model"
    target.mkdir(parents=True, exist_ok=True)
    try:
        from doc_agent.extract import MatlabBridge
        bridge = MatlabBridge()
        console.print(f"[dim]MATLAB:[/dim] {bridge.matlab}")
        slx, sldd = bridge.build_test_model(target)
    except Exception as e:  # noqa: BLE001
        console.print(f"[red]Build failed:[/red] {e}")
        raise typer.Exit(code=1) from e
    console.print(f"[green]✓[/green] {slx}")
    console.print(f"[green]✓[/green] {sldd}")
    console.print(f"\nNext: [bold]doc-agent extract {slx}[/bold]")


# ---- chat-loop helpers -------------------------------------------------------
def _prompt_user() -> str:
    console.print("[bold green]you >[/bold green] ", end="")
    return input()


def _print_chat_header(
    model: str,
    mem: ConversationMemory,
    facts: FactsMemory,
    *,
    rag=None,
    facts_enabled: bool = True,
) -> None:
    s = mem.stats()
    facts_count = facts.stats()["enabled"]
    rag_part = ""
    if rag is not None:
        rag_stats = rag.stats()
        rag_part = f", rag: {rag_stats['sources']} docs / {rag_stats['chunks']} chunks"
    else:
        rag_part = ", rag: disabled"
    parts = [
        f"[bold]doc-agent chat[/bold]  [dim]· {model} ·[/dim]",
        f"[dim]history: {s['messages']} msg ({format_tokens(s['tokens_total'])} tok),"
        f" pinned: {s['pinned']}, facts: {facts_count}{' (active)' if facts_enabled else ' (disabled)'}"
        f"{rag_part}.[/dim]",
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
    if cmd == "rag":
        # /rag                — show stats
        # /rag <query>        — preview retrieval (no LLM)
        try:
            rag = _load_rag()
        except Exception as e:  # noqa: BLE001
            console.print(f"[red]RAG unavailable:[/red] {e}")
            return False
        if not arg.strip():
            s = rag.stats()
            console.print(f"[dim]sources: {s['sources']}  chunks: {s['chunks']}[/dim]")
            return False
        results = rag.search(arg, top_k=settings.rag_top_k, min_score=settings.rag_min_score)
        if not results:
            console.print("[dim]no matches[/dim]")
            return False
        for i, r in enumerate(results, start=1):
            console.print(f"[yellow]#{i} {r.citation}[/yellow] [dim](score {r.score:.2f})[/dim]")
            preview = r.text if len(r.text) <= 240 else r.text[:240].rstrip() + "…"
            console.print(f"  {preview}\n")
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
- `/rag [query]` — show RAG stats, or preview retrieval for a query (no LLM call)
- `/stats` — current memory / token stats
"""


if __name__ == "__main__":
    app()
