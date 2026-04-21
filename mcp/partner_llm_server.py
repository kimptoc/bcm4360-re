# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "fastmcp>=3.0",
#     "httpx>=0.27",
# ]
# ///
"""Partner-LLM MCP server for the BCM4360 RE project.

Exposes three tools to Claude Code:

  - ask_deepseek(prompt, files?, model?, allow_binary?, max_tokens?)
      API-based Q&A via DeepSeek's OpenAI-compat endpoint.
      Text in, text out. Clean-room guard on file attachments.

  - dispatch_gemini(prompt, cwd?, read_only?, timeout_seconds?)
      Shells out to the Gemini CLI in non-interactive mode. The CLI
      authenticates via user's Google account (works with a consumer
      AI Pro subscription — no API key required). Agent can read files
      in cwd directly, so no attachment param is needed.

  - dispatch_kilocode(prompt, cwd?, timeout_seconds?)
      Shells out to the Kilo Code CLI in non-interactive mode. CLI
      handles its own auth via `kilo auth`.

Codex is NOT in this server — register it directly in .mcp.json via
its native `codex mcp-server` mode.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Annotated

import httpx
from fastmcp import FastMCP
from pydantic import Field

BINARY_SUFFIX_BLOCKLIST = {
    ".ko", ".bin", ".fw", ".img", ".so", ".a", ".o",
    ".elf", ".dll", ".dylib",
}
MAX_FILE_BYTES = 2 * 1024 * 1024
API_TIMEOUT_SECONDS = 300.0
CLI_DEFAULT_TIMEOUT_SECONDS = 600

DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"

mcp = FastMCP("partner-llm")


class CleanRoomError(RuntimeError):
    """Raised when a file would be sent that the clean-room guard blocks."""


def _read_file_for_prompt(path: str, allow_binary: bool) -> str:
    p = Path(path)
    if not p.is_absolute():
        raise ValueError(f"File path must be absolute: {path}")
    if not p.exists():
        raise FileNotFoundError(f"File does not exist: {path}")
    if not p.is_file():
        raise ValueError(f"Path is not a regular file: {path}")

    if p.suffix.lower() in BINARY_SUFFIX_BLOCKLIST and not allow_binary:
        raise CleanRoomError(
            f"Refusing to inline {path}: suffix {p.suffix!r} is on the "
            "clean-room blocklist. Re-invoke with allow_binary=True if you "
            "intend to send this file."
        )

    size = p.stat().st_size
    if size > MAX_FILE_BYTES:
        raise ValueError(
            f"File {path} is {size} bytes; exceeds {MAX_FILE_BYTES}-byte "
            "inline limit. Trim or split before sending."
        )

    data = p.read_bytes()
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        if not allow_binary:
            raise CleanRoomError(
                f"Refusing to inline {path}: content is not valid UTF-8 "
                "(looks binary). Re-invoke with allow_binary=True if you "
                "intend to send this file as a hex dump."
            ) from None
        return data.hex()


def _build_prompt_with_files(
    prompt: str, files: list[str], allow_binary: bool
) -> str:
    if not files:
        return prompt
    parts = [prompt, "", "# Attached files", ""]
    for path in files:
        content = _read_file_for_prompt(path, allow_binary)
        parts.append(f"## {path}")
        parts.append("```")
        parts.append(content)
        parts.append("```")
        parts.append("")
    return "\n".join(parts)


def _openai_compat_chat(
    base_url: str,
    api_key: str,
    model: str,
    prompt: str,
    max_tokens: int,
) -> str:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    with httpx.Client(timeout=httpx.Timeout(API_TIMEOUT_SECONDS)) as client:
        response = client.post(
            f"{base_url}/chat/completions", json=payload, headers=headers
        )
        response.raise_for_status()
        data = response.json()
    return data["choices"][0]["message"]["content"]


def _run_cli(
    argv: list[str],
    cwd: str | None,
    timeout_seconds: int,
    stdin_text: str | None = None,
) -> str:
    binary = argv[0]
    if shutil.which(binary) is None:
        raise RuntimeError(
            f"CLI not found on PATH: {binary!r}. "
            "Install it or adjust your PATH."
        )
    if cwd is not None:
        p = Path(cwd)
        if not p.is_absolute():
            raise ValueError(f"cwd must be an absolute path: {cwd}")
        if not p.is_dir():
            raise ValueError(f"cwd is not a directory: {cwd}")

    try:
        result = subprocess.run(
            argv,
            cwd=cwd,
            input=stdin_text,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(
            f"{binary} timed out after {timeout_seconds}s. "
            "Increase timeout_seconds or split the task."
        ) from e

    out = result.stdout or ""
    err = result.stderr or ""
    if result.returncode != 0:
        return (
            f"[{binary} exited with code {result.returncode}]\n\n"
            f"--- stdout ---\n{out}\n\n--- stderr ---\n{err}"
        )
    if err.strip():
        return f"{out}\n\n--- stderr ---\n{err}"
    return out


@mcp.tool
def ask_deepseek(
    prompt: Annotated[
        str,
        Field(description="Full prompt text to send to DeepSeek."),
    ],
    files: Annotated[
        list[str] | None,
        Field(
            description=(
                "Absolute paths to files to inline into the prompt as UTF-8 "
                "text. Files over 2 MB are rejected. Binary files (by suffix "
                "or content) require allow_binary=True."
            ),
        ),
    ] = None,
    model: Annotated[
        str,
        Field(
            description=(
                "DeepSeek model ID. 'deepseek-chat' (V3) or "
                "'deepseek-reasoner' (R1)."
            ),
        ),
    ] = "deepseek-chat",
    allow_binary: Annotated[
        bool,
        Field(
            description=(
                "If True, binary file content is sent as a hex dump. "
                "Required for proprietary binary files (e.g. wl.ko). "
                "Leave False unless you explicitly intend to send binary."
            ),
        ),
    ] = False,
    max_tokens: Annotated[
        int,
        Field(description="Max output tokens. Default 8192."),
    ] = 8192,
) -> str:
    """Send a prompt to DeepSeek via its OpenAI-compatible endpoint.
    Requires DEEPSEEK_API_KEY environment variable."""
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY environment variable is not set.")
    full_prompt = _build_prompt_with_files(prompt, files or [], allow_binary)
    return _openai_compat_chat(
        DEEPSEEK_BASE_URL, api_key, model, full_prompt, max_tokens
    )


@mcp.tool
def dispatch_gemini(
    prompt: Annotated[
        str,
        Field(description="Task / prompt for the Gemini CLI agent."),
    ],
    cwd: Annotated[
        str | None,
        Field(
            description=(
                "Absolute path to run the Gemini CLI in. The agent can read "
                "(and, unless read_only=True, modify) files under this "
                "directory. Defaults to the MCP server's cwd (typically the "
                "project root)."
            ),
        ),
    ] = None,
    read_only: Annotated[
        bool,
        Field(
            description=(
                "If True (default), runs Gemini CLI with "
                "--approval-mode plan (read-only — no file writes, no "
                "command execution). Set False to run in --approval-mode "
                "yolo (auto-approve all actions) — required when the "
                "agent needs to edit files or execute shell commands "
                "non-interactively. Do NOT use False for untrusted "
                "prompts."
            ),
        ),
    ] = True,
    model: Annotated[
        str | None,
        Field(
            description=(
                "Override the default Gemini model. e.g. 'gemini-2.5-pro', "
                "'gemini-2.5-flash'. None = CLI default."
            ),
        ),
    ] = None,
    timeout_seconds: Annotated[
        int,
        Field(
            description=(
                "Max seconds to wait for the CLI to finish. Default 600."
            ),
        ),
    ] = CLI_DEFAULT_TIMEOUT_SECONDS,
) -> str:
    """Dispatch a task to the Gemini CLI in non-interactive mode. The CLI
    authenticates via the user's Google account (e.g. consumer AI Pro
    subscription) — no API key required. Returns the CLI's captured
    stdout + stderr.

    User must have run `gemini auth login` at least once."""
    argv = ["gemini", "-p", prompt]
    argv.append("--approval-mode")
    # "default" prompts for approval on every action — hangs in a
    # subprocess with no TTY. For non-interactive use we need "yolo"
    # (auto-approve all) or "plan" (read-only). Map read_only=False
    # to yolo so the CLI can actually run shell tools + edit files.
    argv.append("plan" if read_only else "yolo")
    if model:
        argv.extend(["-m", model])
    return _run_cli(argv, cwd, timeout_seconds)


@mcp.tool
def dispatch_kilocode(
    prompt: Annotated[
        str,
        Field(description="Task / message for the Kilo Code agent."),
    ],
    cwd: Annotated[
        str | None,
        Field(
            description=(
                "Absolute path to run Kilo Code in. Defaults to the MCP "
                "server's cwd (typically the project root)."
            ),
        ),
    ] = None,
    timeout_seconds: Annotated[
        int,
        Field(
            description=(
                "Max seconds to wait for the CLI to finish. Default 600."
            ),
        ),
    ] = CLI_DEFAULT_TIMEOUT_SECONDS,
) -> str:
    """Dispatch a task to the Kilo Code CLI via `kilo run`. Auth is handled
    by Kilo Code itself (`kilo auth`). Returns captured stdout + stderr.

    Note: Kilo Code has broader agent capabilities than a pure read-only
    analysis tool; it can modify files and run commands. Scope the task
    carefully."""
    argv = ["kilo", "run", prompt]
    return _run_cli(argv, cwd, timeout_seconds)


if __name__ == "__main__":
    mcp.run()
