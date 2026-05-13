import asyncio
import subprocess
from typing import Optional
from config import settings


async def run_claude(
    prompt: str,
    system: Optional[str] = None,
    timeout: int = 120,
) -> str:
    """Run a prompt through the Claude Code CLI and return the response."""
    if system:
        full_prompt = f"<system_instructions>\n{system}\n</system_instructions>\n\n{prompt}"
    else:
        full_prompt = prompt

    cmd = [settings.claude_cli_path, "-p", full_prompt]

    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            ),
        )

        if result.returncode != 0 and result.stderr:
            raise RuntimeError(f"Claude CLI error: {result.stderr.strip()}")

        return result.stdout.strip()

    except subprocess.TimeoutExpired:
        raise RuntimeError(f"Claude CLI timed out after {timeout}s")
    except FileNotFoundError:
        raise RuntimeError(
            f"Claude CLI not found at '{settings.claude_cli_path}'. "
            "Ensure Claude Code is installed and in PATH."
        )


async def run_claude_with_history(
    messages: list[dict],
    system: Optional[str] = None,
    timeout: int = 120,
) -> str:
    """Run Claude with a conversation history formatted as a single prompt."""
    history_text = "\n\n".join(
        f"{'User' if m['role'] == 'user' else 'Assistant'}: {m['content']}"
        for m in messages
    )
    prompt = f"<conversation_history>\n{history_text}\n</conversation_history>\n\nContinue as the assistant. Reply only with your next message, nothing else."
    return await run_claude(prompt, system=system, timeout=timeout)
