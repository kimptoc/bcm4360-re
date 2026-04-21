# Partner-LLM MCP server

Lets Claude Code invoke Gemini and DeepSeek directly as tools, replacing
the manual prompt-paste relay workflow.

## Tools exposed

- `ask_gemini(prompt, files?, model?, allow_binary?, max_tokens?)`
- `ask_deepseek(prompt, files?, model?, allow_binary?, max_tokens?)`

Both send `prompt` plus optional inlined file content to the respective
API and return the assistant's response as a string.

## Environment variables required

Before launching Claude Code, export:

```
export GEMINI_API_KEY=...       # from Google AI Studio
export DEEPSEEK_API_KEY=...     # from platform.deepseek.com
```

If a key is missing, the tool call raises a clear runtime error.

## Clean-room guard

`allow_binary=False` (default) rejects any file that either:

- has a suffix in the blocklist: `.ko .bin .fw .img .so .a .o .elf .dll .dylib`
- contains non-UTF-8 bytes

To send `phase6/wl.ko` (or similar proprietary binary), call with
`allow_binary=True` explicitly. Binary content is then transmitted as a
hex dump. Think twice before doing this — clean-room analysis should
usually work from plain-text disassembly notes, not from the blob itself.

## File size limit

2 MB per attached file. Split large logs before sending.

## How Claude Code picks it up

`.mcp.json` at the project root registers this server. Claude Code
launches it via `uv run --script mcp/partner_llm_server.py` on session
start and keeps the process alive for the session. First launch prompts
you to approve the server; subsequent sessions remember the approval.

## Adding a new provider

Add a new `@mcp.tool` decorated function in `partner_llm_server.py`.
For any OpenAI-compatible endpoint, re-use `_openai_compat_chat` with
a different base URL and API-key env var. Qwen via DashScope would
follow this pattern (base URL
`https://dashscope-intl.aliyuncs.com/compatible-mode/v1`).
