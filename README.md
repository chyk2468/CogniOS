# CogniOS

**[cognios.com](https://cognios.com)** · [Download](#download) · [Issues](https://github.com/andrewyng/cognios/issues)

> **Beta** — CogniOS is in open beta: fully usable, updates itself, and we are actively polishing rough edges. [Issues](https://github.com/andrewyng/cognios/issues) welcome.

**CogniOS** is a local-first AI operating environment. **CogniWork** is the AI coworker agent that runs inside it — it delivers finished work (documents, replies, calendar updates, triaged inboxes), not just chat.

Everything runs on your machine. You bring your own model API keys (OpenAI, Anthropic, Google, open-weight providers, or local Ollama). Data leaves your computer only through the model and integrations you configure.

---

## Table of contents

- [Key features](#key-features)
- [Architecture](#architecture)
- [Feature status](#feature-status)
- [Repository structure](#repository-structure)
- [Download](#download)
- [Installation and setup](#installation-and-setup)
- [Configuration](#configuration)
- [Usage](#usage)
- [CogniWork workflow](#cogniwork-workflow)
- [Memory and context](#memory-and-context)
- [Tools and integrations](#tools-and-integrations)
- [API reference](#api-reference)
- [Security](#security)
- [Development](#development)
- [Testing](#testing)
- [Deployment](#deployment)
- [Current limitations](#current-limitations)
- [Future improvements](#future-improvements)
- [Built on aisuite](#built-on-aisuite)
- [Contributing](#contributing)
- [License](#license)

---

## Key features

- **Local-first desktop app** — React UI in a Tauri shell; Python agent server on `127.0.0.1`
- **CogniWork agent loop** — multi-iteration tool-calling with approval gates (`TurnEngine`)
- **Bring your own model** — 18 LLM providers via aisuite (OpenAI-compatible and native APIs)
- **34 shippable connectors** — Slack, GitHub, Jira, Notion, Linear, HubSpot, and more; plus MCP servers
- **Persistent memory** — SQLite-backed facts scoped global or per-workspace
- **Session history** — JSONL conversation logs and SQLite session index
- **Permission modes** — discuss, plan, interactive, auto, custom
- **Inbox and unattended runs** — approval prompts park in a cross-session inbox
- **Automations** — scheduled and event-driven runs via self-wake tools
- **Messaging gateway** — inbound Slack/Telegram can open desktop sessions
- **Optional local account** — single-owner signup with TOTP 2FA and password reset
- **Terminal UI** — `cognios` CLI for headless/agent-in-terminal use

---

## Architecture

CogniOS splits into a **frontend surface** (React + Tauri), a **local agent server** (FastAPI), and the **CogniWork engine** (Python). All state lives under a user config directory (SQLite + JSON files).

```text
User
 ↓
CogniOS UI (React + Tauri)          surfaces/gui/
 ↓ HTTP REST + WebSocket
Sidecar token (X-CogniOS-Token)     cogniwork/server/app.py
 ↓
Optional user session (ow_session)    cogniwork/auth/
 ↓
FastAPI SessionManager                cogniwork/server/manager.py
 ↓
CogniWork TurnEngine                cogniwork/engine.py
 ↓                    ↓
PermissionEngine      ToolRegistry    cogniwork/permissions.py, tools/, mcp/, connectors/
 ↓
Memory / context injection            cogniwork/agent.py, memory/, compaction.py
 ↓
LLM provider (aisuite)                cogniwork/providers/
 ↓
Events → WebSocket → UI
```

```mermaid
graph TD
    subgraph Frontend ["CogniOS UI (surfaces/gui/)"]
        UI[React App / Composer / Transcript]
        WSClient[WebSocket + REST client]
        UI --> WSClient
    end

    subgraph Server ["Local agent server (cogniwork/server/)"]
        FastAPI[FastAPI app.py]
        Mgr[SessionManager manager.py]
        Auth[Auth routes /v1/auth]
        FastAPI --> Mgr
        FastAPI --> Auth
    end

    subgraph Engine ["CogniWork (cogniwork/)"]
        Turn[TurnEngine engine.py]
        Perm[PermissionEngine]
        Tools[Tools / MCP / Connectors]
        Mem[Memory + Compaction]
        Turn --> Perm
        Turn --> Tools
        Turn --> Mem
    end

    subgraph LLM ["Model providers"]
        AISuite[aisuite]
        Models[OpenAI / Anthropic / Gemini / Ollama / …]
        Turn --> AISuite --> Models
    end

    WSClient <-->|/ws/session/{id}| FastAPI
    WSClient -->|/v1/* REST| FastAPI
    Mgr --> Turn
```

### Layer reference

| Layer | Purpose | Key files |
|-------|---------|-----------|
| **CogniOS UI** | Chat, settings, connectors, approvals, inbox | `surfaces/gui/src/App.tsx`, `src/api/`, `src/auth/` |
| **Tauri shell** | Desktop window, sidecar supervision, auto-update | `surfaces/gui/src-tauri/` |
| **Agent server** | REST + WebSocket control plane | `cogniwork/server/app.py`, `run.py` |
| **Session manager** | One engine per session; gateway, MCP, personas | `cogniwork/server/manager.py` |
| **CogniWork engine** | Agent loop, approvals, tool execution | `cogniwork/engine.py`, `agent.py` |
| **Agents / personas** | Skill presets (code, chat, cogniwork, ops, …) | `cogniwork/agents/`, `cogniwork/personas/` |
| **Memory** | Persistent facts, user rules | `cogniwork/memory/` |
| **Providers** | LLM routing and keys | `cogniwork/providers/` |
| **Connectors** | External app integrations | `cogniwork/connectors/` |
| **MCP** | Model Context Protocol clients | `cogniwork/mcp/` |
| **Storage** | SQLite + JSONL under state dir | `cogniwork/secrets.py`, `conversations.py`, `auth/store.py` |
| **STT sidecar** | Offline speech-to-text (Rust) | `stt/` |

See also: [`docs/chat_system_architecture.md`](docs/chat_system_architecture.md) for the chat data flow in detail.

---

## Feature status

| Feature | Status | Implementation |
|---------|--------|----------------|
| User signup (single owner) | ✅ Implemented | `cogniwork/auth/routes.py`, `auth/store.py` |
| Sign in / sign out | ✅ Implemented | `/v1/auth/signin`, `/v1/auth/signout` |
| Account username / email / password change | ✅ Implemented | `/v1/auth/account/*` |
| Account deletion | ✅ Implemented | `POST /v1/auth/account/remove` |
| TOTP 2FA setup / verify / disable | ✅ Implemented | `cogniwork/auth/totp.py`, `/v1/auth/totp/*` |
| Password reset (pet answer + optional TOTP) | ✅ Implemented | `cogniwork/auth/reset.py`, `/v1/auth/forgot-password/*` |
| Disable auth entirely | ✅ Implemented | `COGNIWORK_AUTH_DISABLED=1` |
| CogniWork agent (TurnEngine) | ✅ Implemented | `cogniwork/engine.py`, `agent.py` |
| Agent orchestration (sessions, personas) | ✅ Implemented | `cogniwork/server/manager.py`, `personas/` |
| Permission modes + approval gates | ✅ Implemented | `cogniwork/permissions.py`, inbox in `inbox.py` |
| Memory (remember / update / forget) | ✅ Implemented | `cogniwork/memory/` |
| Context compaction | ✅ Implemented | `cogniwork/compaction.py` |
| Tool execution (files, shell, git, web, …) | ✅ Implemented | `cogniwork/tools/`, `catalog.py` |
| MCP tool integration | ✅ Implemented | `cogniwork/mcp/` |
| Connector integrations (34 shippable) | ✅ Implemented | `cogniwork/connectors/descriptors.py` |
| LLM providers (18) | ✅ Implemented | `cogniwork/providers/registry.py` |
| Conversation / session history | ✅ Implemented | `cogniwork/conversations.py`, JSONL files |
| SQLite storage | ✅ Implemented | `{state_dir}/cogniwork.db` |
| Messaging gateway (Slack, Telegram) | ✅ Implemented | `cogniwork/server/manager.py` (requires `[messaging]` extra) |
| Browser automation | 🟡 Partial | `connectors/browser_automation.py` (optional `[browser]` extra, Playwright) |
| CogniOS Cloud managed OAuth | 🟡 Partial | Gmail, Google Calendar, Google Drive managed OAuth paused in UI |
| Placeholder connectors | 🟡 Partial | datadog, salesforce, descript, clay, pagerduty — UI only, no connect path |
| Docker deployment | 🔴 Not implemented | No Dockerfile or docker-compose in repo |
| Multi-user / cloud backend | 🔴 Not implemented | Single-owner local account only |
| Clerk auth (frontend dep) | 🔴 Not implemented | `@clerk/clerk-react` in package.json but unused in source |
| Postgres / remote database | 🔴 Not implemented | SQLite + local files only |

---

## Repository structure

```text
cognios/                          # repository root (this checkout may be named openworker/)
├── cogniwork/                      # Python backend — CogniWork runtime
│   ├── server/                     # FastAPI app, session manager, run launcher
│   ├── auth/                       # Local account, TOTP, password reset
│   ├── agents/                     # Agent builders (code, chat, cogniwork, …)
│   ├── personas/                   # Persona registry and builtin markdown personas
│   ├── providers/                  # LLM provider registry and clients
│   ├── connectors/                 # External integrations (Slack, GitHub, …)
│   ├── mcp/                        # MCP client, OAuth, dynamic tools
│   ├── memory/                     # SQLite memory store and agent tools
│   ├── tools/                      # Built-in tools (files, shell, git, plan, …)
│   ├── web/                        # web_search, web_fetch
│   ├── engine.py                   # TurnEngine — core agent loop
│   ├── agent.py                    # build_engine() wiring
│   └── cli.py                      # Terminal UI entry (cognios)
├── surfaces/gui/                   # CogniOS desktop / browser UI
│   ├── src/                        # React app, API client, auth pages
│   ├── src-tauri/                  # Tauri shell, sidecar binary
│   ├── e2e/                        # Playwright hermetic tests
│   └── e2e-live/                   # Playwright live-server tests
├── stt/                            # Rust speech-to-text sidecar (ocw-stt)
├── packaging/                      # PyInstaller + Tauri build scripts
├── tests/                          # Python pytest suite (~87 files)
├── docs/                           # config.example.toml, architecture doc
├── alembic/                        # Auth schema migration (documentation)
├── pyproject.toml                  # Python package (name: cogniwork)
├── start_cognios.bat               # Windows dev launcher
└── LICENSE                         # MIT
```

---

## Download

[**macOS (Apple Silicon)**](https://download.cognios.com/mac)
<sub>macOS 12+ · signed and notarized · auto-updates</sub>

[**Windows 10/11 (x64)**](https://download.cognios.com/windows)
<sub>builds are not yet code-signed; SmartScreen will warn</sub>

Open the app, add a model key (or point at Ollama), and ask for something real.

---

## Installation and setup

### Requirements

| Component | Version |
|-----------|---------|
| Python | 3.10+ (`requires-python` in `pyproject.toml`) |
| Node.js | 20+ (used by `start_cognios.bat` and frontend) |
| Rust | Latest stable via [rustup](https://rustup.rs/) (for Tauri desktop shell) |
| Git Bash or WSL | Windows only — for `packaging/setup_dev_env.sh` |

### Clone and bootstrap

```bash
git clone https://github.com/andrewyng/cognios
cd cognios

# One-time Python venv bootstrap (creates .venv)
bash packaging/setup_dev_env.sh
```

On Windows you can also double-click `start_cognios.bat` after bootstrap — it starts the server and Vite dev UI in separate windows.

### Start the agent server

```bash
.venv/bin/cognios-server --cwd ~/some/project --port 8765
# Windows: .venv\Scripts\cognios-server.exe --cwd . --port 8765
```

The server writes a per-launch sidecar token to `{state_dir}/sidecar-8765.token`. Vite reads this file automatically in dev mode.

### Start the UI

```bash
cd surfaces/gui
npm install
npm run dev          # browser UI at http://localhost:1420
```

Vite proxies `/v1` and `/ws` to `http://127.0.0.1:8765`.

### Full desktop app (Tauri)

From `surfaces/gui/`:

```bash
npm run tauri dev    # Tauri launches the window and supervises the server
```

### Terminal UI (no GUI)

```bash
.venv/bin/cognios --cwd ~/some/project
```

### Optional Python extras

```bash
.venv/bin/pip install -e ".[messaging,dev]"   # Slack/Telegram gateway + pytest
.venv/bin/pip install -e ".[browser]"          # Playwright browser automation
.venv/bin/pip install -e ".[bedrock]"          # AWS Bedrock provider
```

---

## Configuration

### State directory

Default locations (see `cogniwork/secrets.py`):

| OS | Path |
|----|------|
| Windows | `%APPDATA%\cogniwork` (falls back to `%APPDATA%\coworker` if legacy exists) |
| macOS / Linux | `~/.config/cogniwork` (falls back to `~/.config/coworker`) |

Override with `COGNIWORK_STATE_DIR`.

### TOML config

Copy [`docs/config.example.toml`](docs/config.example.toml) to:

- `{state_dir}/config.toml` — global
- `{workspace}/.cogniwork/config.toml` — per-workspace override

Key options: `model`, `mode` (`plan` | `interactive` | `auto` | `custom`), `max_iterations`, `allowed_commands`, `auto_allow`, `host`, `port`.

### Environment variables

Variables verified in source. Never commit real secrets.

#### Runtime

| Variable | Purpose |
|----------|---------|
| `COGNIWORK_STATE_DIR` | Override state directory (legacy: `COWORKER_STATE_DIR`) |
| `COGNIWORK_API_TOKEN` | Sidecar API token (legacy: `COWORKER_API_TOKEN`) |
| `COGNIWORK_PORT` | Server port (set by `run.py`) |
| `COGNIWORK_EXIT_WITH_PARENT` | Exit when parent process dies (legacy: `COWORKER_EXIT_WITH_PARENT`) |
| `COGNIWORK_PARENT_PID` | Parent PID for sidecar watchdog (legacy: `COWORKER_PARENT_PID`) |
| `COGNIWORK_AUTH_DISABLED` | Skip user account auth (legacy: `COWORKER_AUTH_DISABLED`) |
| `COGNIWORK_DEBUG_INJECT` | Enable `POST /v1/_debug/inject_inbound` |
| `COGNIWORK_EXPERIMENTAL` | Include experimental connectors in PyInstaller build |
| `COGNIWORK_LIVE_VISION` | Enable live vision tests |
| `SSL_CERT_FILE` | SSL certificate path (defaults to certifi if unset) |

Secrets can also be loaded from `{state_dir}/.env` (see `cogniwork/secrets.py`).

#### Frontend (Vite)

| Variable | Purpose |
|----------|---------|
| `VITE_COGNIWORK_HTTP` | Backend HTTP URL override |
| `VITE_COGNIWORK_WS` | Backend WebSocket URL override |
| `VITE_COGNIWORK_API_TOKEN` | API token override |
| `CI` | Playwright retry/reporter behavior |

#### Tauri / sidecar

| Variable | Purpose |
|----------|---------|
| `COGNIWORK_SERVER_BIN` | Path to server binary (legacy: `COWORKER_SERVER_BIN`) |

#### LLM provider API keys

`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `GOOGLE_API_KEY`, `ZAI_API_KEY`, `DEEPSEEK_API_KEY`, `MOONSHOT_API_KEY`, `MINIMAX_API_KEY`, `DASHSCOPE_API_KEY`, `XAI_API_KEY`, `MISTRAL_API_KEY`, `META_API_KEY`, `TOGETHER_API_KEY`, `FIREWORKS_API_KEY`, `OPENROUTER_API_KEY`, `AWS_BEARER_TOKEN_BEDROCK`

#### Web search

| Variable | Purpose |
|----------|---------|
| `TAVILY_API_KEY` | Tavily search provider |
| `BRAVE_API_KEY` | Brave search provider |

DuckDuckGo is the default keyless provider.

#### Connector testing overrides

`SLACK_API_URL`, `GITHUB_API_URL`, `GITHUB_GIT_URL`, `{PLATFORM}_ALLOWED_USERS`, `{PLATFORM}_ALLOW_ALL_USERS`

#### macOS build / notarization

`APPLE_SIGNING_IDENTITY`, `NOTARYTOOL_API_KEY_PATH`, `NOTARYTOOL_API_KEY_ID`, `NOTARYTOOL_API_ISSUER_ID`, `OCW_SKIP_NOTARIZE`, `OCW_NOTARY_ENV`

---

## Usage

1. **Install** — download the desktop app or run from source (above).
2. **Create or sign in** — on first launch, sign up (single local owner account) or sign in. Auth can be disabled with `COGNIWORK_AUTH_DISABLED=1`.
3. **Configure 2FA (optional)** — Settings → TOTP setup with QR code; required at sign-in when enabled.
4. **Add a model** — Settings → Providers → paste an API key or configure Ollama.
5. **Open CogniOS** — main chat at `/chat` (desktop app or `http://localhost:1420/chat` in dev).
6. **Use CogniWork** — describe an outcome; pick a persona/skill if needed.
7. **Approve actions** — writes, sends, and shell commands show approval cards; unattended runs park prompts in the Inbox.
8. **View results** — transcript, artifacts, and generated files in the session.
9. **Manage account** — change username/email/password, enable/disable TOTP, or delete account from auth settings; sign out clears the session cookie.

---

## CogniWork workflow

When you send a message, the server runs this loop (verified in `engine.py`, `server/manager.py`, `docs/chat_system_architecture.md`):

```text
User message (WebSocket user_message)
 → Session lock (claim_turn)
 → TurnEngine.run()
 → Inject memory + workspace context (agent.py context_provider)
 → LLM call (provider.chat with tools)
 → Tool calls requested?
     → PermissionEngine decision
         → needs_user → PERMISSION_REQUIRED event → user approves/denies
         → allowed → execute tool (concurrent reads, ordered writes)
     → Tool results appended to messages
 → Repeat until model stops, max_iterations, or cancel
 → Context compaction if window exceeded (compaction.py)
 → TURN_END event → UI transcript update
```

Permission modes (`permissions.py`):

| Mode | Behavior |
|------|----------|
| `discuss` | Read-only conversation |
| `plan` | Read-only + `propose_plan` workflow |
| `interactive` | Auto-allow reads; ask on writes/shell (default) |
| `auto` | Full access |
| `custom` | Interactive + `auto_allow` list from config |

---

## Memory and context

| Store | Location | Purpose |
|-------|----------|---------|
| Memory items | `cogniwork.db` → `memories` table | Durable facts (`remember`, `memory_update`, `memory_forget`) |
| Memory settings | `memory-settings.json` | On/off toggle, user rules |
| Conversations | `conversations/{session_id}.jsonl` | Full message history |
| Session index | `cogniwork.db` → `sessions`, `workspaces` | Session metadata |
| Secrets | `secrets.json` (mode 0600) | API keys, connector tokens |
| Workspace trust | JSON store | Trusted workspace directories |

Memory scopes: `global` (user-wide), `workspace` (project-wide). Session scope writes are deprecated.

Agent tools: `remember`, `memory_read`, `memory_update`, `memory_forget` in `cogniwork/memory/tools.py`.

---

## Tools and integrations

### Built-in agent tools

| Category | Tools | Module |
|----------|-------|--------|
| Files | `read_file`, `write_file`, `replace_in_file`, `apply_patch`, `grep` | `tools/files.py`, `tools/search.py` |
| Git | `git_status`, `git_diff`, `git_log` | `tools/git.py` |
| Shell | `run_shell`, background tasks | `tools/shell.py` |
| Planning | `propose_plan`, `ask_user`, `request_directory` | `tools/plan.py`, `tools/ask.py`, `tools/directories.py` |
| Web | `web_search`, `web_fetch` | `web/tool.py`, `web/fetch.py` |
| Memory | `remember`, `memory_*` | `memory/tools.py` |
| Skills | `load_skill`, `save_skill` | `skills/` |
| Subagent | `explore` | `tools/subagent.py` |
| Todo | `todo_write` | `tools/todo.py` |
| Self-wake | `sleep_for`, `sleep_until`, `wake_on` | `selfwake.py` |
| Messaging | `send_message`, `send_file` | `connectors/integration_tools.py` |
| MCP | `mcp__{server}__{tool}` (dynamic) | `mcp/tools.py` |
| Browser | Playwright automation | `connectors/browser_automation.py` (optional) |

### LLM providers

Registered in `cogniwork/providers/registry.py`:

| Provider | Auth | Env key |
|----------|------|---------|
| OpenAI | API key | `OPENAI_API_KEY` |
| Anthropic | API key | `ANTHROPIC_API_KEY` |
| Gemini | API key | `GEMINI_API_KEY`, `GOOGLE_API_KEY` |
| AWS Bedrock | API key / IAM / profile | `AWS_BEARER_TOKEN_BEDROCK` |
| Google Vertex | ADC / service account / API key | GCP credentials |
| Z AI (GLM) | API key | `ZAI_API_KEY` |
| DeepSeek | API key | `DEEPSEEK_API_KEY` |
| Kimi (Moonshot) | API key | `MOONSHOT_API_KEY` |
| MiniMax | API key | `MINIMAX_API_KEY` |
| Qwen (Alibaba) | API key | `DASHSCOPE_API_KEY` |
| xAI (Grok) | API key | `XAI_API_KEY` |
| Mistral | API key | `MISTRAL_API_KEY` |
| Meta (Muse Spark) | API key | `META_API_KEY` |
| Together AI | API key | `TOGETHER_API_KEY` |
| Fireworks AI | API key | `FIREWORKS_API_KEY` |
| OpenRouter | API key | `OPENROUTER_API_KEY` |
| Ollama | None (local) | — |

Model strings use `provider:model-id` prefix (e.g. `openai:gpt-5.6-sol`). Curated list in `providers/matrix.py`.

### Web search providers

| Provider | Key required | Module |
|----------|--------------|--------|
| DuckDuckGo | No (default) | `web/providers.py` |
| Tavily | `TAVILY_API_KEY` | `web/providers.py` |
| Brave | `BRAVE_API_KEY` | `web/providers.py` |

### Connectors (34 shippable)

Defined in `cogniwork/connectors/descriptors.py`. Each connector declares auth method, setup fields, and validation.

| Connector | Auth | Notes |
|-----------|------|-------|
| telegram | bot token | Two-way messaging |
| slack | socket app / managed OAuth | Channels, gateway |
| email | SMTP/IMAP config | Outbound |
| gmail | OAuth / manual token | Managed OAuth paused in UI |
| google_calendar | OAuth / manual token | Managed OAuth paused in UI |
| google_drive | OAuth / manual token | Managed OAuth paused in UI |
| browser | none | Requires `[browser]` extra |
| github | OAuth / PAT | Managed OAuth available |
| outlook | OAuth / manual token | Managed OAuth available |
| jira | API token / MCP | |
| monday | API token | |
| confluence | API token | |
| zendesk | API token | |
| linear | API token / MCP | |
| gitlab | PAT | |
| discord | bot token | |
| stripe | API key | |
| asana | PAT | |
| hubspot | OAuth / PAT | Managed OAuth available |
| dropbox | OAuth / token | |
| box | OAuth / token | |
| whatsapp | Meta API | |
| quickbooks | OAuth | |
| docusign | OAuth token | |
| clickup | API token | |
| canva | OAuth / token | |
| figma | PAT | |
| notion | OAuth / token | Managed OAuth available |
| attio | API token | |
| posthog | OAuth / token | Managed OAuth available |
| mixpanel | service account | |
| amplitude | API key | |
| apollo | API key | |
| hunter | API key | |
| close | API key | |

**Placeholder only** (no connect path): datadog, salesforce, descript, clay, pagerduty.

**MCP servers** — add via Settings; stdio and streamable-http transports; local OAuth at `/mcp/oauth/callback`.

**Messaging gateway** — Slack (Socket Mode + optional cloud relay) and Telegram require the `[messaging]` Python extra.

---

## API reference

Base URL: `http://127.0.0.1:8765`

**Authentication layers:**

1. **Sidecar token** — `X-CogniOS-Token` header (legacy alias: `x-openworker-token`); WebSocket via `Sec-WebSocket-Protocol`
2. **User session** — `ow_session` cookie (when auth enabled)

### WebSocket

| Method | Endpoint | Purpose | Auth |
|--------|----------|---------|------|
| WS | `/ws/session/{session_id}` | Real-time chat, approvals, engine events | Sidecar token + user session |
| WS | `/ws/events` | Global event stream | Sidecar token + user session |

### Auth (`/v1/auth`)

| Method | Endpoint | Purpose | Auth |
|--------|----------|---------|------|
| GET | `/v1/auth/status` | Auth enabled / owner exists | Public |
| GET | `/v1/auth/me` | Current user (401 if none) | Sidecar token |
| GET | `/v1/auth/account` | Account details | User session |
| POST | `/v1/auth/signup` | Create owner account | Public |
| POST | `/v1/auth/signin` | Sign in | Public |
| POST | `/v1/auth/signin/totp` | Complete TOTP challenge | Public |
| POST | `/v1/auth/signout` | Sign out | User session |
| PATCH | `/v1/auth/account/username` | Change username | User session |
| PATCH | `/v1/auth/account/email` | Change email | User session |
| POST | `/v1/auth/account/password` | Change password | User session |
| POST | `/v1/auth/totp/setup` | Start TOTP setup | User session |
| POST | `/v1/auth/totp/verify-setup` | Confirm TOTP | User session |
| POST | `/v1/auth/totp/disable` | Disable TOTP | User session |
| POST | `/v1/auth/account/remove` | Delete account | User session |
| POST | `/v1/auth/forgot-password/start` | Start reset | Public |
| POST | `/v1/auth/forgot-password/verify-pet` | Verify security answer | Public |
| POST | `/v1/auth/forgot-password/verify-totp` | Verify TOTP in reset | Public |
| POST | `/v1/auth/forgot-password/reset` | Set new password | Public |

### Core REST

| Method | Endpoint | Purpose | Auth |
|--------|----------|---------|------|
| GET | `/v1/health` | Health check | Sidecar token (optional) |
| GET | `/v1/agents` | List agent types | Both |
| GET/POST | `/v1/sessions` | List / create sessions | Both |
| GET | `/v1/sessions/{id}/messages` | Session transcript | Both |
| PATCH/DELETE | `/v1/sessions/{id}` | Update / delete session | Both |
| GET/POST/DELETE | `/v1/sessions/{id}/roots` | Workspace roots | Both |
| GET/POST | `/v1/sessions/{id}/unattended` | Unattended mode | Both |
| GET/POST | `/v1/sessions/{id}/skills` | Session skills | Both |
| GET/POST | `/v1/sessions/{id}/connections` | Session connectors | Both |
| GET/POST/PATCH/DELETE | `/v1/memory` | Memory CRUD | Both |
| GET/PUT | `/v1/memory/settings` | Memory settings | Both |
| POST | `/v1/chat/completions` | OpenAI-compatible proxy | Both |
| GET/POST/PATCH/DELETE | `/v1/mcp` | MCP server config | Both |
| GET | `/v1/mcp/{name}/tools` | List MCP tools | Both |
| POST | `/v1/mcp/{name}/connect` | Connect MCP server | Both |
| GET | `/mcp/oauth/callback` | MCP OAuth callback | Public |
| GET | `/v1/connectors` | List connectors | Both |
| POST | `/v1/connectors/{name}/connect` | Connect connector | Both |
| POST | `/v1/connectors/{name}/disconnect` | Disconnect | Both |
| GET/POST | `/v1/providers` | LLM provider config | Both |
| POST | `/v1/providers/verify` | Verify provider key | Both |
| GET/POST | `/v1/settings/*` | App settings | Both |
| GET | `/v1/inbox` | Approval inbox | Both |
| POST | `/v1/inbox/{id}/resolve` | Resolve inbox item | Both |
| GET/POST | `/v1/subscriptions` | Channel subscriptions | Both |
| GET/POST | `/v1/web-search` | Web search config | Both |
| GET/POST | `/v1/browser/*` | Browser automation | Both |
| GET | `/v1/audit` | Audit log | Both |
| GET/POST | `/v1/personas/*` | Persona management | Both |
| GET/POST/PATCH/DELETE | `/v1/skills/*` | Skill management | Both |
| GET/POST | `/v1/workspaces/*` | Workspace trust / open | Both |

Connector-specific routes (Slack workspaces, GitHub installations, Gmail accounts, HubSpot portals, etc.) are under `/v1/connectors/{name}/…` — see `cogniwork/server/app.py`.

Debug route (only when `COGNIWORK_DEBUG_INJECT=1`): `POST /v1/_debug/inject_inbound`.

---

## Security

### Implemented

| Mechanism | Details |
|-----------|---------|
| **Password hashing** | Argon2id (`cogniwork/auth/passwords.py`) |
| **TOTP 2FA** | pyotp + encrypted secrets (`auth/totp.py`, `auth/crypto.py`) |
| **Session cookies** | `ow_session` — local SQLite session store |
| **Sidecar token** | Per-launch random token; `secrets.compare_digest` timing-safe check |
| **Rate limiting** | Auth brute-force protection (`auth/rate_limit.py`) |
| **CORS** | Origin regex pinned to Tauri + localhost only (`app.py`) |
| **Secret storage** | `secrets.json` mode 0600; connector tokens encrypted |
| **Tool permissions** | Risk classification + approval gates; shell operator blocking |
| **Workspace roots** | File tools scoped to granted directories |
| **Account deletion** | `POST /v1/auth/account/remove` |
| **Audit log** | `GET /v1/audit` |

### Not implemented or partial

- No remote/cloud multi-tenant auth
- No Docker/network isolation — server binds to localhost by default
- Windows desktop builds are unsigned (SmartScreen warning)
- CogniOS Cloud managed OAuth partially disabled (Google connectors)
- `@clerk/clerk-react` dependency present but unused

---

## Development

| Area | Location |
|------|----------|
| Frontend UI | `surfaces/gui/src/` |
| Backend server | `cogniwork/server/` |
| CogniWork engine | `cogniwork/engine.py`, `agent.py` |
| Tools | `cogniwork/tools/` |
| Connectors | `cogniwork/connectors/` (add descriptor in `descriptors.py`) |
| MCP | `cogniwork/mcp/` |
| Authentication | `cogniwork/auth/` |
| LLM providers | `cogniwork/providers/` |
| Memory | `cogniwork/memory/` |
| Personas | `cogniwork/personas/` |
| API client (frontend) | `surfaces/gui/src/api/` |

### Dev URLs

| Service | URL |
|---------|-----|
| UI (Vite) | `http://localhost:1420` |
| Agent server | `http://127.0.0.1:8765` |

---

## Testing

### Backend (pytest)

```bash
# From repo root with .venv active
.venv/bin/pytest                    # Linux/macOS
.venv\Scripts\pytest                # Windows
```

Config: `testpaths = ["tests"]` in `pyproject.toml`, `asyncio_mode = auto`.

### Frontend unit tests (Vitest)

```bash
cd surfaces/gui
npm test
npx tsc --noEmit && npx vitest run
```

### Frontend E2E (Playwright)

```bash
cd surfaces/gui
npm run e2e          # hermetic — mocked API, no Python server
npm run e2e:live     # live server (playwright.live.config.ts)
npm run e2e:ui       # Playwright UI mode
```

---

## Deployment

CogniOS ships as a **native desktop app** (Tauri + PyInstaller sidecar). There is **no Docker or cloud server deployment** in this repository.

### Build desktop installers

| Platform | Script | Output |
|----------|--------|--------|
| macOS | `packaging/build_dmg.sh` | `.app` + `.dmg` |
| Windows | `packaging/build_windows.ps1` | NSIS `.exe` + MSI |

PyInstaller spec: `packaging/cognios-server.spec`.

Auto-update endpoints (Tauri): `https://download.cognios.com/latest.json`, GitHub releases.

Tauri app ID: `com.cognios.desktop` (version in `surfaces/gui/src-tauri/tauri.conf.json`).

---

## Current limitations

- **Single local owner account** — no multi-user server deployment
- **SQLite only** — no Postgres or remote database
- **No Docker** — local install or desktop bundle only
- **CogniOS Cloud paused** — managed OAuth for Gmail, Google Calendar, Google Drive disabled in UI
- **5 placeholder connectors** — datadog, salesforce, descript, clay, pagerduty (UI badges only)
- **Windows builds unsigned** — SmartScreen warning on first launch
- **Browser automation optional** — requires separate Playwright install (`[browser]` extra)
- **Messaging gateway optional** — requires `[messaging]` extra for Slack/Telegram inbound
- **Experimental connectors** — `connectors/experimental/` exists but ships empty in release builds

---

## Future improvements

Based on in-repo placeholders and comments (not commitments):

- Code-sign Windows builds
- Re-enable CogniOS Cloud managed OAuth for Google services
- Ship placeholder connectors (datadog, salesforce, descript, clay, pagerduty)
- Groq provider (noted as deferred in `providers/registry.py`)
- Experimental connector pack (opt-in via `COGNIWORK_EXPERIMENTAL=1`)

---

## Built on aisuite

CogniWork's engine is built on [**aisuite**](https://github.com/andrewyng/aisuite) — a unified chat-completions API across LLM providers with tools, toolkits, and MCP support. CogniOS was originally developed inside the aisuite repository before moving here.

---

## Contributing

Contributions and bug reports are welcome — open an [issue](https://github.com/andrewyng/cognios/issues) or pull request. The app auto-updates, so fixes reach installs quickly.

For PRs, attach screenshots of what was broken and how it is fixed. We maintain an internal roadmap; PRs that duplicate in-progress work or diverge from our vision may not be merged.

---

## License

MIT — see [LICENSE](LICENSE).
