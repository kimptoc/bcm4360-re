# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "fastmcp>=3.0",
#     "httpx>=0.27",
# ]
# ///
"""Partner-LLM MCP server for the BCM4360 RE project.

Exposes two tools to Claude Code:
  - ask_gemini(prompt, files?, model?, allow_binary?, max_tokens?)
  - ask_deepseek(prompt, files?, model?, allow_binary?, max_tokens?)

Both hit OpenAI-compatible endpoints (Google's Gemini compat layer,
DeepSeek's native OpenAI-shape API) so the code path is identical
except for base URL and API key env var.

Clean-room guard: files with binary content or blocklisted suffixes
(.ko, .bin, .fw, .img, .so, .a, .o, .elf, .dll, .dylib) are rejected
unless allow_binary=True is passed explicitly. Prevents accidentally
sending wl.ko or firmware blobs to a cloud LLM.
"""

from __future__ import annotations

import os
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
REQUEST_TIMEOUT_SECONDS = 300.0

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
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
    with httpx.Client(timeout=httpx.Timeout(REQUEST_TIMEOUT_SECONDS)) as client:
        response = client.post(
            f"{base_url}/chat/completions", json=payload, headers=headers
        )
        response.raise_for_status()
        data = response.json()
    return data["choices"][0]["message"]["content"]


@mcp.tool
def ask_gemini(
    prompt: Annotated[
        str,
        Field(description="Full prompt text to send to Gemini."),
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
                "Gemini model ID. Examples: 'gemini-2.5-pro', "
                "'gemini-2.5-flash', 'gemini-2.0-flash-exp'."
            ),
        ),
    ] = "gemini-2.5-pro",
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
    """Send a prompt to Google Gemini via its OpenAI-compatible endpoint.
    Requires GEMINI_API_KEY environment variable."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY environment variable is not set.")
    full_prompt = _build_prompt_with_files(prompt, files or [], allow_binary)
    return _openai_compat_chat(
        GEMINI_BASE_URL, api_key, model, full_prompt, max_tokens
    )


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
    """Send a prompt to DeepSeek. Requires DEEPSEEK_API_KEY environment variable."""
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY environment variable is not set.")
    full_prompt = _build_prompt_with_files(prompt, files or [], allow_binary)
    return _openai_compat_chat(
        DEEPSEEK_BASE_URL, api_key, model, full_prompt, max_tokens
    )


if __name__ == "__main__":
    mcp.run()
