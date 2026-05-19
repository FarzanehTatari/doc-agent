# doc-agent

AI-powered documentation for Simulink control models.

**Status**: Phase 0 — project scaffold. See [`../ROADMAP.md`](../ROADMAP.md) for the full plan and [`../DOC_AGENT_BLUEPRINT.md`](../DOC_AGENT_BLUEPRINT.md) for the original v1 specification this rebuild is derived from.

---

## Quick start

Requires **Python 3.11+** and **macOS / Linux / WSL**. (Native Windows works too; substitute the activation command.)

```bash
# 1. Enter the repo
cd doc-agent

# 2. Create a virtual environment
python3.11 -m venv .venv
source .venv/bin/activate          # macOS / Linux / WSL
# .venv\Scripts\activate            # Windows PowerShell

# 3. Install in editable mode (with dev tools)
pip install --upgrade pip
pip install -e ".[dev]"

# 4. Get an Anthropic API key
#    https://console.anthropic.com/settings/keys

# 5. Configure
cp .env.example .env
# Open .env and paste your key after ANTHROPIC_API_KEY=

# 6. Verify connectivity (Phase 0 exit criterion)
doc-agent ping
```

Expected output on success:

```
Pinging claude-opus-4-7 via https://api.anthropic.com …
  Status   ✓ Connected
   Model   claude-opus-4-7
 Latency   ~450 ms
   Reply   'pong'
```

If you see `Setup required`, your API key isn't in `.env` yet.

---

## Commands

| Command | Purpose |
|---|---|
| `doc-agent version` | Print version (no API call). |
| `doc-agent ping` | Verify Anthropic connectivity. Exit 0 = success. |

You can also run as a module: `python -m doc_agent ping`.

---

## Project layout

```
doc-agent/
├── src/doc_agent/         # Python package
│   ├── __init__.py        # version
│   ├── __main__.py        # `python -m doc_agent`
│   ├── cli.py             # Typer commands (version, ping)
│   ├── config.py          # Settings (pydantic-settings)
│   ├── ai/
│   │   └── client.py      # AIClient wrapper around Anthropic SDK
│   └── utils/
│       └── logger.py      # Rich-backed logger
├── matlab/                # Phase 2 — extraction scripts (.slx → JSON)
├── tests/                 # pytest suite — no API calls
├── examples/              # sample inputs (.slx, .sldd, A2L, ARXML)
├── docs/                  # design notes
├── .env.example           # template — copy to .env
├── .gitignore             # excludes .env, .venv, caches
├── Makefile               # install / dev / lint / test / ping / clean
├── pyproject.toml         # deps + entry point (PEP 621)
└── README.md              # this file
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

## Push to a private GitHub repo

After creating an **empty private repo** on github.com (no README, no .gitignore — we already have ours):

```bash
git init
git add .
git commit -m "Phase 0: project scaffold"
git branch -M main
git remote add origin git@github.com:YOUR_USERNAME/doc-agent.git
git push -u origin main
```

The `.gitignore` already excludes `.env`, `.venv/`, build artifacts, and editor / OS junk. **Double-check** that `.env` is not staged before pushing:

```bash
git status              # .env should not appear
git ls-files | grep -i env   # only .env.example should appear
```

---

## What's next (Phase 1 — AI & Memory Core, 3–5 days)

Once `doc-agent ping` is green, the next phase adds:

- `AIClient` extended with retry, streaming, prompt caching, structured outputs
- `ConversationMemory` — rolling chat history with token budgeting and pinning
- `FactsMemory` — authoritative project knowledge, priority-ranked
- `SessionStore` — lightweight key-value persistence
- Token estimation (`tiktoken` for OpenAI parity + Claude estimator)

Exit criterion: a CLI chat loop that respects the token budget, persists across runs, and surfaces pinned facts.

See [`../ROADMAP.md`](../ROADMAP.md) for the full multi-phase plan.

---

## Troubleshooting

**`doc-agent: command not found`** — your virtual environment isn't activated, or `pip install -e .` was run outside it. Re-activate (`source .venv/bin/activate`) and re-install.

**`ANTHROPIC_API_KEY is not set`** — `.env` doesn't exist or doesn't contain a key. `cp .env.example .env`, then paste your key.

**`Connection error` / `Timeout`** — check internet access; if behind a corporate proxy, set `HTTPS_PROXY` in your shell or `ANTHROPIC_BASE_URL` in `.env`.

**`AuthenticationError`** — the key is set but wrong / revoked. Generate a new one in the Anthropic console.

**Python version mismatch** — `python3 --version` must report 3.11 or higher. Use `pyenv` or your system package manager to install 3.11 if needed.
