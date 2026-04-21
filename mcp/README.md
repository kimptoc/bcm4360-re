# MCP servers for BCM4360 RE project

Two MCP servers are registered in `../.mcp.json`:

1. **`codex`** — OpenAI Codex CLI's native MCP mode (`codex mcp-server`).
   Exposes `codex` + `codex-reply` tools. No wrapper code — Codex ships
   this itself.

2. **`partner-llm`** — the local Python server in this directory
   (`partner_llm_server.py`). Exposes three tools:
   - `ask_deepseek` — API Q&A (needs `DEEPSEEK_API_KEY`)
   - `dispatch_gemini` — shells to Gemini CLI (sub-auth, no API key)
   - `dispatch_kilocode` — shells to Kilo Code CLI (own auth)

## Authentication (one-time setup per CLI)

Each partner has its own auth. Run each once interactively in a terminal
before relying on the MCP tool:

```sh
codex login          # OAuth to ChatGPT Codex subscription
gemini auth login    # OAuth to your Google account (AI Pro sub works)
kilo auth            # Configure Kilo Code providers
```

For DeepSeek (API key in env):

```sh
export DEEPSEEK_API_KEY=...     # from platform.deepseek.com
```

Put env exports in `~/.zshrc` so they persist across sessions.

## Tool semantics

### `ask_deepseek`

API-based Q&A — pure prompt → response. Supports file attachments
(inlined as UTF-8 text). Clean-room guard rejects binary-suffix files
(`.ko .bin .fw .img .so .a .o .elf .dll .dylib`) and files that fail
UTF-8 decode unless `allow_binary=True`. 2 MB per-file limit.

### `dispatch_gemini`

Runs `gemini -p <prompt> --approval-mode {plan|default}` in a working
directory. `read_only=True` (default) uses `plan` — agent can read files
but cannot write or run commands. Set `read_only=False` only when you
explicitly want the agent to modify the tree.

Agent reads files itself from `cwd`, so there's no `files` parameter
and no clean-room guard in this tool — be deliberate about what you
ask it to read. If you point it at `phase6/wl.ko`, it will read and
transmit it.

### `dispatch_kilocode`

Runs `kilo run <prompt>` in `cwd`. Kilo Code has broad agent
capabilities (file writes, command execution) — no read-only mode
exposed in this wrapper. Scope tasks carefully.

### Codex (via native MCP)

`codex` starts a new Codex session. `codex-reply` continues an existing
one by thread ID. See Codex CLI docs for full parameter set.

## How Claude Code picks it up

`.mcp.json` at the project root registers both servers. Claude Code
launches them on session start and keeps the processes alive for the
session. First launch prompts you to approve each; subsequent sessions
remember approvals.

## Adding a new provider

Edit `partner_llm_server.py`:

- **Another OpenAI-compat API** (Qwen via DashScope, Mistral, etc.):
  add a new `@mcp.tool` that calls `_openai_compat_chat` with a
  different base URL and API-key env var.
- **Another CLI-based agent**: add a new `@mcp.tool` that calls
  `_run_cli([binary, ...args])`.

## Files

- `partner_llm_server.py` — FastMCP server, runs as a `uv` inline-deps
  script.
- `README.md` — this file.
