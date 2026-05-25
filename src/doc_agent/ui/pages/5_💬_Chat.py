"""Chat page — ad-hoc questions to the tool-using agent.

The agent sees the same tools the Generate page uses (get_subsystem,
lookup_calibration, search_rag, list_facts, list_stateflow_charts …), so when
a canonical model has been extracted this session you can ask "what does
LowPassFilter do?" or "what's the value of K_VSE_FILT_TC?" without spending
a full generation cycle.

When no model is loaded, the chat still works — it'll just answer general
questions against your project facts + RAG library.
"""

from __future__ import annotations

import streamlit as st

from doc_agent.config import settings
from doc_agent.ui._brand import apply_brand
from doc_agent.ui.state import K
from doc_agent.ui.state import get as get_state

st.set_page_config(page_title="Chat · doc-agent", page_icon="💬", layout="wide")
apply_brand()
st.title("💬 Chat  ·  ask the agent")


# ---- helpers -------------------------------------------------------------
@st.cache_resource
def _client():
    from doc_agent.ai.client import AIClient
    return AIClient()


def _memory():
    """Conversation memory persisted to `project_lib/conversation.json`.

    Cached in session state so we don't reload it on every interaction.
    """
    from doc_agent.memory import ConversationMemory

    if "chat_memory" not in st.session_state:
        settings.ensure_data_dir()
        mem = ConversationMemory.load(settings.conversation_path)
        mem.max_history = settings.max_history
        mem.max_token_budget = settings.max_token_budget
        mem.response_token_budget = settings.response_token_budget
        mem.persist_path = settings.conversation_path
        st.session_state["chat_memory"] = mem
    return st.session_state["chat_memory"]


def _build_tool_context(use_rag: bool, use_facts: bool):
    """Build a ToolContext from the current pipeline state."""
    from doc_agent.extract import CanonicalModel, ModelHeader
    from doc_agent.generate.tools import ToolContext
    from doc_agent.memory import FactsMemory
    from doc_agent.rag import RAGManager

    canonical = get_state(K.CANONICAL)
    has_model = canonical is not None
    if canonical is None:
        # Stub so the model tools can return polite "no model" errors instead
        # of crashing the loop.
        canonical = CanonicalModel(model=ModelHeader(name="(none)"))

    rag = None
    if use_rag and settings.rag_enabled:
        try:
            r = RAGManager(
                store_path=settings.rag_dir,
                collection_name=settings.rag_collection,
            )
            if r.stats()["chunks"] > 0:
                rag = r
        except Exception:  # noqa: BLE001
            rag = None

    facts = FactsMemory(settings.facts_path) if use_facts else None
    return ToolContext(canonical=canonical, rag=rag, facts=facts), has_model


def _system_prompt(has_model: bool, use_facts: bool) -> str:
    """Build the system prompt for the chat agent."""
    from doc_agent.memory import FactsMemory

    parts = [
        "You are doc-agent, helping the user understand a Simulink control "
        "model and answer questions about it. Be concise, technical, and "
        "ground every claim in tool results. Use Markdown for formatting "
        "(lists, code, tables) when it helps clarity.",
    ]
    if has_model:
        parts.append(
            "A canonical model IS loaded in this session. Call "
            "`list_subsystems`, `get_subsystem`, `lookup_calibration`, "
            "`list_stateflow_charts`, `get_stateflow_chart`, `trace_signal`, "
            "and `list_dd_signals` when the question is about the model. "
            "Never invent block, signal, or calibration names."
        )
    else:
        parts.append(
            "NO model is currently extracted in this session. The model "
            "tools will return empty results. If the user asks about a "
            "specific subsystem, calibration, or signal, direct them to "
            "the Extract page first."
        )
    parts.append(
        "If you call `search_rag`, cite the chunks you actually used."
    )

    if use_facts:
        facts = FactsMemory(settings.facts_path)
        block = facts.for_prompt(
            max_facts=50, max_tokens=settings.facts_token_budget
        )
        if block:
            parts.append(block)
    return "\n\n".join(parts)


# ---- sidebar controls ----------------------------------------------------
with st.sidebar:
    st.markdown("### Chat settings")
    if not settings.has_api_key:
        st.error("No `ANTHROPIC_API_KEY`. Set it in `.env` and restart.")
        st.stop()

    use_rag    = st.checkbox("Use RAG library",  value=True, key="chat_use_rag")
    use_facts  = st.checkbox("Use project facts", value=True, key="chat_use_facts")
    show_tools = st.checkbox("Show tool calls",   value=True, key="chat_show_tools")
    stream_text = st.checkbox("Stream reply",     value=True, key="chat_stream",
                              help="Show the assistant's reply token-by-token.")

    st.markdown("---")
    if st.button("🗑  Clear history (keep pinned)", key="chat_clear_btn"):
        m = _memory()
        m.clear(keep_pinned=True)
        m.save()
        st.toast("Cleared.", icon="🗑")
        st.rerun()


# ---- status row ----------------------------------------------------------
mem = _memory()
canonical = get_state(K.CANONICAL)

c1, c2, c3 = st.columns(3)
c1.metric("Messages", len(mem))
c2.metric("Model", canonical.model.name if canonical else "—")
c3.metric("Tokens used", f"{sum(m.tokens for m in mem.all()):,}")

if canonical is None:
    st.info(
        "💡 No model extracted in this session. The chat works for general "
        "questions, but to ask about specific subsystems / calibrations / "
        "signals you need to **Extract** first.",
        icon="ℹ️",
    )

st.markdown("---")


# ---- replay past messages ------------------------------------------------
for m in mem.all():
    avatar = "🧑" if m.role == "user" else "🤖"
    with st.chat_message(m.role, avatar=avatar):
        st.markdown(m.content)


# ---- chat input ----------------------------------------------------------
prompt = st.chat_input(
    "Ask anything — about your model, project conventions, or general doc-writing…"
)

if prompt:
    # Build history BEFORE adding the new user turn, so the agent receives
    # `[history…] + [new user prompt]` cleanly.
    history = mem.recent()

    # Render the user's message immediately
    with st.chat_message("user", avatar="🧑"):
        st.markdown(prompt)

    # Build context, system prompt, run the agent
    ctx, has_model = _build_tool_context(use_rag=use_rag, use_facts=use_facts)
    system = _system_prompt(has_model=has_model, use_facts=use_facts)

    tool_log: list[tuple[str, dict]] = []

    def on_tool(name, inp):
        tool_log.append((name, inp or {}))

    with st.chat_message("assistant", avatar="🤖"):
        from doc_agent.generate.agent import run_agent

        # Live placeholder that fills in as text streams.
        stream_buf = {"text": ""}
        placeholder = st.empty()

        def on_text(delta: str):
            if not stream_text:
                return
            stream_buf["text"] += delta or ""
            placeholder.markdown(stream_buf["text"])

        with st.spinner("Thinking…"):
            result = run_agent(
                client=_client(),
                ctx=ctx,
                user_prompt=prompt,
                messages_history=history,
                system=system,
                on_tool=on_tool,
                on_text=on_text if stream_text else None,
                stream=stream_text,
            )

        if result.error:
            placeholder.empty()
            st.error(f"Agent error: {result.error}")
        else:
            # Replace whatever streamed in with the post-processed final text
            # (preamble stripped, etc.). If they happen to be identical the
            # user just sees the same content.
            placeholder.markdown(result.text)

        if show_tools and tool_log:
            with st.expander(f"🛠  {len(tool_log)} tool call(s)", expanded=False):
                for name, inp in tool_log:
                    inp_repr = ", ".join(f"{k}={v!r}" for k, v in inp.items())
                    st.markdown(f"- `{name}({inp_repr})`")

        # Tiny stats line
        if not result.error:
            st.caption(
                f"_{result.iterations} iter · {len(result.tool_calls)} tool · "
                f"in {result.input_tokens:,} / out {result.output_tokens:,} tokens_"
            )

    # Persist both turns to memory AFTER the agent returns, so a mid-call
    # crash doesn't leave a dangling user message in the history.
    if not result.error:
        mem.add("user", prompt)
        mem.add("assistant", result.text)
        mem.save()
