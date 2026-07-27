<p align="center">
  <img src="docs/cognios-wordmark.png" alt="CogniOS" width="280">
</p>

<h3 align="center">Your Private AI Workforce</h3>

<p align="center">
  A self-hosted AI workspace for chat, agents, deep research, documents, email, notes, calendar, and local model workflows.<br>
  Offline-first · Plugin-based · Full data sovereignty.
</p>

<p align="center">
  <a href="#-quickstart"><strong>Quickstart</strong></a> ·
  <a href="#-features"><strong>Features</strong></a> ·
  <a href="#-architecture"><strong>Architecture</strong></a> ·
  <a href="#-agent-tools"><strong>Agent Tools</strong></a> ·
  <a href="#-model-support"><strong>Models</strong></a> ·
  <a href="docs/setup.md"><strong>Full Setup Guide</strong></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/license-AGPL--3.0-blue" alt="License">
  <img src="https://img.shields.io/badge/python-3.11+-green" alt="Python">
  <img src="https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey" alt="Platform">
  <img src="https://img.shields.io/badge/offline-capable-emerald" alt="Offline Capable">
</p>

---

## What is CogniOS?

CogniOS is a **self-hosted AI operating system** that replaces scattered tools with a single unified workspace. Chat with AI agents backed by 40+ tools, manage email, edit documents, run multi-step research, serve local models — all from one interface, all on your own hardware.

No cloud dependency. No telemetry. Your data never leaves your machine.

---

## ⚡ Quickstart

### Windows

```bash
# 1. Clone the repo
git clone https://github.com/your-username/cognios.git
cd cognios

# 2. Create a virtual environment
python -m venv .venv
.venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run setup (creates directories, database, and admin user)
python setup.py

# 5. Start the server
python -m uvicorn app:app --host 127.0.0.1 --port 7000
```

Or just double-click **`run.bat`** — it handles everything automatically.

### macOS (Apple Silicon)

```bash
./start-macos.sh
```

One command. Installs Homebrew dependencies, sets up a Python venv, runs setup, and launches the server. Safe to re-run.

### Manual Launch

```bash
python -m uvicorn app:app --host 127.0.0.1 --port 7000
```

Then open **http://localhost:7000**.

---

## 🧩 Features

### Workspace Modules

| Module | Description |
|--------|-------------|
| 💬 **Chat + Agents** | Full agent mode with 40+ tools — shell, Python, file ops, web search, email, calendar, memory, skills, and MCP |
| 📖 **Cookbook** | Hardware-aware model recommendations, one-click HuggingFace downloads, serving via vLLM / SGLang / llama.cpp / Ollama |
| 🔬 **Deep Research** | Multi-step research engine: Think → Search → Extract → Synthesize. The LLM drives every decision |
| 📧 **Email** | Full IMAP/SMTP client with AI triage, tags, summaries, reply drafts, reminders, and multi-account support |
| 📝 **Documents** | Writing editor with AI suggestions, Markdown, HTML, CSV, and syntax highlighting |
| 📋 **Notes** | Google Keep-style notes with checklists, reminders, labels, and pinning |
| 📅 **Calendar** | CalDAV sync, recurrence rules, event types, and AI-scheduled automated tasks |
| ⚖️ **Compare** | Blind side-by-side model comparison on the same prompt |
| 🖼️ **Gallery** | AI image generation with Stable Diffusion, upscale, background removal, inpainting |
| 🧠 **Memory + RAG** | Persistent memory across sessions with ChromaDB-powered vector search |

### Agent Capabilities

The agent has access to **40+ built-in tools** organized by category:

- **Execution** — Shell commands, Python REPL, background jobs
- **File System** — Read, write, list, search, move, delete files
- **Web** — Search (SearXNG, DuckDuckGo, Brave, etc.), fetch pages, extract content
- **Email** — Read inbox, search, compose, reply, manage accounts
- **Calendar** — Create events, query schedule, manage tasks
- **Memory** — Store/recall facts, contacts, preferences, events
- **Documents** — Create, edit, export documents and notes
- **RAG** — Index files, semantic search over your knowledge base
- **MCP** — Connect to any Model Context Protocol server
- **Skills** — Reusable multi-step workflows the agent can learn and replay

### Deep Research

An IterResearch-style engine that performs autonomous multi-step research:

1. **Think** — Plan what information is needed
2. **Search** — Query the web via SearXNG or other providers
3. **Extract** — Crawl and parse relevant pages
4. **Synthesize** — Compile findings into a structured report
5. **Iterate** — Repeat until the research question is fully answered

Produces visual HTML reports with citations.

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────┐
│              Web UI (localhost:7000)          │
├─────────────────────────────────────────────┤
│       Chat Handler + Action Intent Router    │
├─────────────────────────────────────────────┤
│    Agent Loop (tool parsing · execution      │
│               pipeline · skills)             │
├─────────────────────────────────────────────┤
│       LLM Core + Endpoint Resolver           │
├────────────────────┬────────────────────────┤
│   Local Models     │    API Providers        │
│  vLLM · SGLang     │  OpenAI · Anthropic     │
│  Ollama · llama.cpp│  Gemini · Groq          │
├────────────────────┴────────────────────────┤
│  40+ Tools │ MCP Servers │ Integrations      │
├─────────────────────────────────────────────┤
│  SQLite + ChromaDB │ Filesystem │ SearXNG    │
└─────────────────────────────────────────────┘
```

### Key Components

| Directory | Purpose |
|-----------|---------|
| `app.py` | FastAPI application entry point and middleware |
| `core/` | Auth, database (SQLAlchemy/SQLite), session management, middleware |
| `src/` | Business logic — agent loop, LLM core, tools, research, memory, RAG, embeddings |
| `routes/` | HTTP route handlers for every workspace module |
| `services/` | Background services — search, TTS, STT, memory, shell, YouTube |
| `mcp_servers/` | Built-in MCP servers for email, memory, RAG, and image generation |
| `integrations/` | Third-party integrations (Claude, Codex) |
| `scripts/` | CLI tools (`cognios`, `cognios-mail`, `cognios-cookbook`, etc.) and utilities |
| `static/` | Frontend (HTML/CSS/JS), PWA manifest, service worker |
| `config/` | SearXNG and service configurations |
| `data/` | Runtime data — database, uploads, cache, generated images (gitignored) |
| `companion/` | Companion device pairing module |

---

## 🤖 Model Support

CogniOS works with **any OpenAI-compatible endpoint**. The **Cookbook** module scans your hardware, recommends models, and serves them locally.

### Local Serving

| Backend | Use Case |
|---------|----------|
| **vLLM** | Production GPU serving with continuous batching |
| **SGLang** | High-throughput structured generation |
| **llama.cpp** | CPU/Metal inference, GGUF models |
| **Ollama** | Quick local model management |

### API Providers

| Provider | Notes |
|----------|-------|
| **OpenAI** | GPT-4o, o1, o3, etc. |
| **Anthropic** | Claude 4, Sonnet, Haiku |
| **Google** | Gemini 2.5 Pro/Flash |
| **Groq** | Ultra-fast inference |
| **Any OpenAI-compatible** | LM Studio, Together AI, Fireworks, etc. |

### Cookbook Features

- **GPU auto-detection** — Detects NVIDIA, AMD, and Apple Metal GPUs
- **Hardware-fit recommendations** — Suggests models that fit your VRAM/RAM
- **One-click downloads** — Pull models directly from HuggingFace
- **Serve management** — Start/stop model servers from the UI

---

## 🔌 Integrations

| Integration | Description |
|-------------|-------------|
| **SearXNG** | Self-hosted metasearch engine for web search |
| **ChromaDB** | Vector database for RAG and semantic memory |
| **CalDAV** | Calendar sync (Radicale, Nextcloud, Apple, Fastmail) |
| **IMAP/SMTP** | Email with any provider (Gmail, Outlook, Proton, self-hosted) |
| **Google OAuth** | OAuth2 flow for Google Workspace email accounts |
| **ntfy** | Push notifications |
| **MCP** | Model Context Protocol for extending with external tool servers |
| **Stable Diffusion** | AI image generation |
| **Whisper** | Local speech-to-text |

---

## 🔒 Security

- **Authentication** — Username/password with bcrypt hashing
- **2FA** — TOTP-based two-factor authentication
- **Session management** — Secure cookie-based sessions
- **API tokens** — Scoped tokens for programmatic access
- **RBAC** — Role-based access control (admin/user)
- **CORS** — Configurable allowed origins
- **CSP** — Content Security Policy headers with per-request nonces
- **SSRF protection** — URL validation on outbound requests
- **Secret storage** — Encrypted credential vault
- **Audit logging** — Request/response logging

---

## ⚙️ Configuration

Copy `.env.example` to `.env` and configure:

```bash
cp .env.example .env
```

### Key Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_HOST` | `localhost` | Primary LLM host |
| `SEARXNG_INSTANCE` | `http://localhost:8080` | SearXNG URL |
| `AUTH_ENABLED` | `true` | Enable authentication |
| `APP_PORT` | `7000` | Server port |
| `APP_BIND` | `127.0.0.1` | Bind address |
| `CHROMADB_HOST` | `localhost` | ChromaDB host |
| `CHROMADB_PORT` | `8100` | ChromaDB port |
| `OPENAI_API_KEY` | — | OpenAI API key (if using OpenAI models) |
| `COGNIOS_DATA_DIR` | `./data` | Data directory path |

See [`.env.example`](.env.example) for the full list of configuration options.

---

## 📁 Project Structure

```
cognios/
├── app.py                  # FastAPI entry point
├── launcher.py             # Development launcher
├── setup.py                # First-time setup script
├── run.bat                 # Windows one-click launcher
├── start-macos.sh          # macOS one-command quick start
├── core/                   # Auth, database, sessions, middleware
├── src/                    # Agent loop, LLM core, tools, research, RAG
│   ├── agent_loop.py       # Main agent execution loop
│   ├── llm_core.py         # LLM abstraction and routing
│   ├── deep_research.py    # Multi-step research engine
│   ├── tool_schemas.py     # 40+ tool definitions
│   ├── tool_execution.py   # Tool dispatch and execution
│   ├── embeddings.py       # Local + API embeddings
│   └── ...                 # 100+ modules
├── routes/                 # HTTP route handlers (54 files)
├── services/               # Background services
├── mcp_servers/            # Built-in MCP servers
├── integrations/           # Third-party integrations
├── scripts/                # CLI tools and utilities
├── static/                 # Frontend (HTML/CSS/JS, PWA)
├── config/                 # Service configurations
├── tests/                  # Test suite (pytest)
├── docs/                   # Documentation and media
├── data/                   # Runtime data (gitignored)
└── requirements.txt        # Python dependencies
```

---

## 🧪 Testing

```bash
# Run all tests
pytest

# Run fast tests only (excludes slow-marked tests)
pytest -m "not slow"

# Run tests for a specific area
pytest -m area_security
pytest -m area_routes
pytest -m area_services
```

Test markers are defined in [`pyproject.toml`](pyproject.toml). See [`tests/README.md`](tests/README.md) for the full test taxonomy.

---

## 🛠️ CLI Tools

CogniOS ships with a suite of CLI scripts in `scripts/`:

| Command | Description |
|---------|-------------|
| `cognios` | Main CLI entry point |
| `cognios-mail` | Email account management |
| `cognios-cookbook` | Model management and serving |
| `cognios-calendar` | Calendar operations |
| `cognios-contacts` | Contact management |
| `cognios-docs` | Document operations |
| `cognios-gallery` | Gallery management |
| `cognios-memory` | Memory management |
| `cognios-notes` | Notes management |
| `cognios-research` | Research operations |
| `cognios-sessions` | Session management |
| `cognios-skills` | Skill management |
| `cognios-tasks` | Task management |
| `cognios-backup` | Backup and restore |
| `cognios-mcp` | MCP server management |
| `cognios-webhook` | Webhook management |

---

## 📜 License

CogniOS is licensed under the [GNU Affero General Public License v3.0](LICENSE) (AGPL-3.0).

Optional dependencies may carry their own licenses — see `licenses/` for details.

---

<p align="center">
  Built for people who want AI that works for them — not the other way around.
</p>
