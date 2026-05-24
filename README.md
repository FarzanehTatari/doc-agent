# doc-agent

AI-powered documentation for Simulink control models.

**Status**: Phase 2 (Slice 1) + Phase 3 complete. `.slx` → canonical JSON works end-to-end with a toy fixture. See [`../ROADMAP.md`](../ROADMAP.md) for the full plan and [`../DOC_AGENT_BLUEPRINT.md`](../DOC_AGENT_BLUEPRINT.md) for the original v1 specification this rebuild is derived from.

---

## Quick start

Requires **Python 3.11+**.

```bash
cd doc-agent
make dev                       # creates .venv and installs everything

# Get a key at https://console.anthropic.com/settings/keys
cp .env.example .env
# Edit .env, paste your key after ANTHROPIC_API_KEY=

source .venv/bin/activate
doc-agent ping                 # connectivity check
doc-agent chat                 # interactive chat with persistent memory
```

---

## Commands

### Top-level

| Command | Purpose |
|---|---|
| `doc-agent version` | Print version. |
| `doc-agent ping` | Verify Anthropic connectivity. Exit 0 = success. |
| `doc-agent chat` | Interactive chat loop with persistent history and facts-aware system prompt. |

Chat flags: `--new` (start fresh, keep pinned), `--no-facts` (skip the facts block), `--no-stream`, `--max-tokens N`.

Inside the chat loop, type `/help` for in-session commands (`/clear`, `/pin <id>`, `/unpin <id>`, `/history`, `/facts`, `/stats`, `/exit`).

### Memory subcommands

| Command | Purpose |
|---|---|
| `doc-agent memory show [-n N]` | Show stats + last N messages with their ids. |
| `doc-agent memory clear` | Drop non-pinned messages. `--all` drops pinned too. |
| `doc-agent memory pin <id>` | Pin a message so it always stays in context. |
| `doc-agent memory unpin <id>` | Unpin a message. |

### Facts subcommands

| Command | Purpose |
|---|---|
| `doc-agent facts list` | List facts grouped by category. |
| `doc-agent facts add "<text>" [-c category] [-p priority] [-k tag]` | Add a fact. |
| `doc-agent facts remove <id>` | Remove a fact by its 10-char id. |
| `doc-agent facts reload` | Re-read `facts.md` after editing it by hand. |

Categories: `naming`, `domain`, `policy`, `other`. Priorities: `critical`, `high`, `normal`, `low`. Facts are stored in `project_lib/facts.md` — human-editable.

### MATLAB extraction (Phase 2)

| Command | Purpose |
|---|---|
| `doc-agent build-test-model [-d <dir>]` | Generate the toy `VSEModel.slx + .sldd` fixture (needs MATLAB). |
| `doc-agent extract <slx_path> [-o <json>]` | Run `matlab/extract_slx.m` and validate the canonical JSON. |

Both shell out to a headless `matlab -batch ...` call. MATLAB is auto-detected on `PATH` or in `/Applications/MATLAB_R*.app/bin/`; override with `MATLAB_EXECUTABLE` in `.env`.

End-to-end check:

```bash
doc-agent build-test-model               # writes examples/test_model/VSEModel.{slx,sldd}
doc-agent extract examples/test_model/VSEModel.slx
# Output:
#   Model        VSEModel
#   Schema       1
#   Subsystems   3
#   Signals      5
#   Block types  Gain, Saturate, Sum, TransferFcn
#   Data dict    VSEModel.sldd
#   Output       project_lib/extracted/VSEModel.json
```

The resulting JSON validates against `src/doc_agent/extract/schema.py:CanonicalModel`. Phase 4 will feed it to the LLM via tools.

### RAG subcommands

| Command | Purpose |
|---|---|
| `doc-agent rag add <file>` | Index a PDF, DOCX, Markdown, text, or code file. Re-adding replaces prior chunks. |
| `doc-agent rag list` | Show all indexed sources with their chunk counts. |
| `doc-agent rag remove <name>` | Delete every chunk for one source. |
| `doc-agent rag search "<query>" [-k 5]` | Preview retrieval — no LLM call. |
| `doc-agent rag stats` | Quick counts and storage path. |
| `doc-agent rag clear` | Wipe the entire library (originals untouched). |

Supported file types: `.pdf`, `.docx`, `.md`, `.txt`, `.rst`, `.py`, `.m`, `.c`, `.cpp`, `.h`, `.json`, `.xml`, `.yml`, `.yaml`, `.toml`, `.html`.

Once you've indexed at least one document, `doc-agent chat` automatically retrieves the top-k most relevant chunks per turn and includes them in the system prompt with citations. Disable with `doc-agent chat --no-rag` or `RAG_ENABLED=0` in `.env`.

Try it out:

```bash
doc-agent rag add examples/sample_signals_spec.md
doc-agent rag search "What calibration controls the low-pass filter?"
doc-agent chat
# In chat: "Write a brief description of the VSE subsystem."
```

---

## Where data lives

By default everything persists under `project_lib/` at the repo root (gitignored):

```
project_lib/
├── conversation.json   # chat history (JSON)
├── facts.md            # authoritative project facts (Markdown — edit by hand if you like)
└── session.json        # lightweight key/value state
```

Override via the `DATA_DIR` environment variable in `.env`.

A starter facts file is available at [`examples/facts.example.md`](examples/facts.example.md) — copy it to `project_lib/facts.md` to seed.

---

## Project layout

```
doc-agent/
├── src/doc_agent/
│   ├── __init__.py        # version
│   ├── __main__.py        # `python -m doc_agent`
│   ├── cli.py             # Typer commands (version, ping, chat, memory, facts)
│   ├── config.py          # Settings (pydantic-settings)
│   ├── ai/
│   │   ├── client.py      # AIClient: ping, chat, chat_stream — retry + backoff
│   │   └── tokens.py      # Token estimator
│   ├── memory/
│   │   ├── conversation.py  # ConversationMemory (rolling window, pinning, JSON persist)
│   │   ├── facts.py         # FactsMemory (markdown-backed, priority-ranked)
│   │   └── session.py       # SessionStore (key/value JSON)
│   └── utils/logger.py
├── matlab/                # Phase 2 — extraction scripts (.slx → JSON)
├── tests/                 # pytest, no API key required
├── examples/              # facts.example.md, sample inputs
├── docs/                  # design notes
├── .env.example           # template — copy to .env
├── Makefile               # install / dev / lint / test / ping / clean
├── pyproject.toml         # deps + entry point (PEP 621)
└── README.md
```

---

## Make targets

```bash
make help       # list targets
make dev        # create .venv and install with dev deps
make test       # run pytest (no API key required)
make lint       # run ruff
make ping       # alias for `doc-agent ping`
make clean      # remove caches and the .venv
```

---

## Configuration (`.env`)

| Variable | Default | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | *(required)* | Anthropic API key. |
| `ANTHROPIC_BASE_URL` | `https://api.anthropic.com` | Only change for proxies. |
| `AI_MODEL` | `claude-opus-4-7` | Default model. |
| `LOG_LEVEL` | `INFO` | DEBUG / INFO / WARNING / ERROR. |
| `DATA_DIR` | `project_lib` | Where memory/facts/session live. |
| `MAX_HISTORY` | `12` | Max user+assistant messages kept in context. |
| `MAX_TOKEN_BUDGET` | `40000` | Total input-side token budget. |
| `RESPONSE_TOKEN_BUDGET` | `8000` | Tokens reserved for the model's reply. |
| `FACTS_TOKEN_BUDGET` | `2000` | Tokens reserved for the facts system block. |
| `RAG_ENABLED` | `1` | Set `0` to disable retrieval globally. |
| `RAG_CHUNK_SIZE` | `800` | Target tokens per chunk. |
| `RAG_CHUNK_OVERLAP` | `100` | Overlap between adjacent chunks (tokens). |
| `RAG_TOP_K` | `5` | Chunks to retrieve per chat turn. |
| `RAG_TOKEN_BUDGET` | `4000` | Max tokens of retrieved context injected. |
| `RAG_MIN_SCORE` | `0.0` | Minimum cosine similarity to keep a chunk (0–1). |

---

## What's next (Phase 2 — MATLAB Bridge, 6–8 days)

- `extract_slx.m` + `extract_sldd.m` → canonical JSON
- Stateflow walker, library-link resolution
- A2L / ARXML parsers on the Python side
- Stable `id` + provenance on every entity (hedge for Phase 7 KG)

Exit criterion: a real `.slx` + `.sldd` parsed into a fully validated canonical JSON.

See [`../ROADMAP.md`](../ROADMAP.md) for the full multi-phase plan.

---

## Troubleshooting

**`doc-agent: command not found`** — your virtual environment isn't activated, or `pip install -e .` was run outside it. Re-activate (`source .venv/bin/activate`) and re-install.

**`ANTHROPIC_API_KEY is not set`** — `.env` doesn't exist or doesn't contain a key.

**`Connection error` / `Timeout`** — check internet access; if behind a corporate proxy, set `HTTPS_PROXY` in your shell or `ANTHROPIC_BASE_URL` in `.env`.

**`AuthenticationError`** — the key is set but wrong / revoked. Generate a new one in the Anthropic console.

**Memory file got corrupted** — delete `project_lib/conversation.json`; the next `doc-agent chat` will start fresh.

**Facts not appearing in chat** — run `doc-agent facts reload` after editing `project_lib/facts.md` by hand, or check that `FACTS_TOKEN_BUDGET` isn't 0.

**Python version mismatch** — `python3 --version` must be 3.11+. The Makefile auto-detects 3.13 / 3.12 / 3.11 / `python3`.
