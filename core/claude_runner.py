import asyncio
import json
import subprocess
from typing import Optional
from config import settings

CONTEXT_HANDOVER_THRESHOLD = 80  # % used before we summarize and start a new session


class _SessionExpiredError(Exception):
    pass


async def _run_subprocess(cmd: list, timeout: int) -> subprocess.CompletedProcess:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        lambda: subprocess.run(cmd, capture_output=True, text=True, timeout=timeout),
    )


async def _call_claude_raw(prompt: str, session_id: Optional[str], timeout: int) -> dict:
    """Call the Claude CLI and return parsed JSON output."""
    cmd = [
        settings.claude_cli_path,
        "--dangerously-skip-permissions",
        "--output-format", "json",
        "-p", prompt,
    ]
    if session_id:
        cmd += ["--resume", session_id]

    try:
        result = await _run_subprocess(cmd, timeout)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"Claude CLI timed out after {timeout}s")
    except FileNotFoundError:
        raise RuntimeError(
            f"Claude CLI not found at '{settings.claude_cli_path}'. "
            "Ensure Claude Code is installed and in PATH."
        )

    if result.returncode != 0:
        stderr = result.stderr.strip() if result.stderr else ""
        # Session-related failures should be retried by the caller without session_id
        if session_id and ("session" in stderr.lower() or "resume" in stderr.lower() or not stderr):
            raise _SessionExpiredError(f"Session {session_id} invalid")
        if stderr:
            raise RuntimeError(f"Claude CLI error: {stderr}")

    try:
        data = json.loads(result.stdout.strip())
    except json.JSONDecodeError:
        data = {"result": result.stdout.strip()}

    return data


async def run_claude(
    prompt: str,
    system: Optional[str] = None,
    timeout: int = 120,
) -> str:
    """One-off Claude call with no session management. Use for structured extraction."""
    full_prompt = f"<system_instructions>\n{system}\n</system_instructions>\n\n{prompt}" if system else prompt
    data = await _call_claude_raw(full_prompt, session_id=None, timeout=timeout)
    return data.get("result", "")


async def run_claude_in_session(
    prompt: str,
    system: Optional[str] = None,
    timeout: int = 120,
) -> str:
    """
    Session-aware Claude call. Resumes the existing session if one exists.
    Injects the system prompt only on the first message of a session.
    When the context window nears the limit, generates a handover summary,
    saves it, and starts a fresh session seeded with that summary.
    """
    from core.memory import get_session, save_session, clear_session, get_session_summary, save_session_summary

    session = get_session()
    session_id = session.get("session_id")
    used_pct = session.get("used_percentage", 0)
    is_new_session = session_id is None

    # --- Handover: context window nearly full ---
    if session_id and used_pct >= CONTEXT_HANDOVER_THRESHOLD:
        handover_prompt = (
            "Summarize this entire conversation into a compact handover note. "
            "Include: the user's learning goals, topics and current levels, "
            "what has been covered so far, and any context needed to continue coaching. "
            "Under 300 words. Plain text only."
        )
        handover_data = await _call_claude_raw(handover_prompt, session_id=session_id, timeout=60)
        summary = handover_data.get("result", "")
        if summary:
            save_session_summary(summary)
        clear_session()
        session_id = None
        is_new_session = True

    # --- Build the prompt ---
    # On the first message of a session, inject system + any prior summary
    if is_new_session:
        prior_summary = get_session_summary()
        parts = []
        if system:
            parts.append(f"<system_instructions>\n{system}\n</system_instructions>")
        if prior_summary:
            parts.append(f"<context_from_previous_session>\n{prior_summary}\n</context_from_previous_session>")
        parts.append(prompt)
        full_prompt = "\n\n".join(parts)
    else:
        full_prompt = prompt

    # --- Call Claude ---
    try:
        data = await _call_claude_raw(full_prompt, session_id=session_id, timeout=timeout)
    except _SessionExpiredError:
        # Stale session (e.g. bot restarted). Clear it and retry as a new session.
        clear_session()
        session_id = None
        is_new_session = True
        prior_summary = get_session_summary()
        parts = []
        if system:
            parts.append(f"<system_instructions>\n{system}\n</system_instructions>")
        if prior_summary:
            parts.append(f"<context_from_previous_session>\n{prior_summary}\n</context_from_previous_session>")
        parts.append(prompt)
        full_prompt = "\n\n".join(parts)
        data = await _call_claude_raw(full_prompt, session_id=None, timeout=timeout)

    # --- Persist session state ---
    new_session_id = data.get("session_id") or session_id
    context_window = data.get("context_window") or {}
    new_used_pct = context_window.get("used_percentage", used_pct)

    if new_session_id:
        save_session({
            "session_id": new_session_id,
            "used_percentage": new_used_pct,
        })

    return data.get("result", "")


# Kept for backwards compatibility — callers that still import this will work.
async def run_claude_with_history(
    messages: list[dict],
    system: Optional[str] = None,
    timeout: int = 120,
) -> str:
    history_text = "\n\n".join(
        f"{'User' if m['role'] == 'user' else 'Assistant'}: {m['content']}"
        for m in messages
    )
    prompt = (
        f"<conversation_history>\n{history_text}\n</conversation_history>\n\n"
        "Continue as the assistant. Reply only with your next message, nothing else."
    )
    return await run_claude(prompt, system=system, timeout=timeout)
