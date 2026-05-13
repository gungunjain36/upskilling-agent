"""Main orchestrator — routes user messages to the right agent."""

import json
import random
from datetime import datetime
from core import (
    run_claude,
    get_user_profile, update_user_profile,
    get_conversation_history, append_message,
    get_roadmap, get_schedule_config,
    is_onboarded,
    log_session, log_challenge, log_concept,
    update_roadmap as tracker_update_roadmap,
    get_roadmap_summary,
)
from agents.personas import COACH_BASE, DOMAIN_PERSONAS, DOMAIN_DISPLAY
from agents.onboarding import handle_onboarding


async def handle_message(user_message: str) -> str:
    """Route an incoming Telegram message and return the bot's response."""
    if not is_onboarded():
        return await handle_onboarding(user_message)

    # Handle slash commands
    if user_message.startswith("/"):
        return await handle_command(user_message)

    # Conversational flow
    return await handle_chat(user_message)


async def handle_command(command: str) -> str:
    cmd = command.split()[0].lower()
    handlers = {
        "/challenge": cmd_challenge,
        "/concept": cmd_concept,
        "/progress": cmd_progress,
        "/status": cmd_status,
        "/help": cmd_help,
        "/topic": cmd_topic,
    }
    handler = handlers.get(cmd)
    if handler:
        return await handler(command)
    return "Unknown command. Type /help to see what's available."


async def handle_chat(user_message: str) -> str:
    profile = get_user_profile()
    history = get_conversation_history()

    # Detect if the user is responding to a challenge
    if _is_challenge_response(history, user_message):
        return await evaluate_challenge_response(user_message, history, profile)

    # General coaching chat
    append_message("user", user_message)
    history = get_conversation_history()

    system = _build_coach_system(profile)
    response = await run_claude(
        _format_history_prompt(history),
        system=system,
        timeout=90,
    )

    append_message("assistant", response)
    log_session(
        domain=_detect_domain_from_context(history),
        topic="general",
        session_type="chat",
        summary=user_message[:100],
    )
    return response


def _is_challenge_response(history: list, message: str) -> bool:
    if not history:
        return False
    last_assistant = next(
        (m["content"] for m in reversed(history) if m["role"] == "assistant"), ""
    )
    challenge_markers = ["take your time", "reply with your approach", "try this", "your turn", "solve this"]
    return any(marker in last_assistant.lower() for marker in challenge_markers)


async def evaluate_challenge_response(response: str, history: list, profile: dict) -> str:
    last_challenge = next(
        (m["content"] for m in reversed(history) if m["role"] == "assistant"), ""
    )
    domain = _detect_domain_from_context(history)
    persona = DOMAIN_PERSONAS.get(domain, "")

    eval_prompt = f"""A student is attempting a challenge. Evaluate their response.

Challenge given:
{last_challenge}

Student's response:
{response}

Evaluate with:
1. What they got right
2. What they missed or could improve
3. A score from 1-10
4. A brief next-level hint or follow-up

Keep it under 250 words. Be encouraging. Format for Telegram (no markdown headers).
End with either another follow-up challenge or confirm they've mastered this and move on.

Respond with JSON:
{{"evaluation": "your evaluation text", "score": 7, "topic": "topic name", "mastered": false}}"""

    try:
        result = await run_claude(eval_prompt, system=persona, timeout=90)
        start, end = result.find("{"), result.rfind("}") + 1
        data = json.loads(result[start:end]) if start >= 0 else {"evaluation": result, "score": 5, "topic": "general", "mastered": False}
    except Exception:
        data = {"evaluation": response, "score": 5, "topic": "general", "mastered": False}

    evaluation_text = data.get("evaluation", "Good attempt! Keep going.")
    score = data.get("score", 5)
    topic = data.get("topic", "general")

    append_message("user", response)
    append_message("assistant", evaluation_text)

    log_challenge(
        domain=domain, topic=topic,
        challenge=last_challenge[:200],
        user_response=response[:200],
        evaluation=evaluation_text[:200],
        score=score,
        status="completed",
    )

    if data.get("mastered"):
        _mark_topic_progress(domain, topic, profile)

    return evaluation_text


def _mark_topic_progress(domain: str, topic: str, profile: dict):
    roadmap = get_roadmap()
    topics = roadmap.get("domains", {}).get(domain, {}).get("topics", [])
    for t in topics:
        if t["topic"].lower() in topic.lower():
            assessments = profile.get("assessments", {})
            current = assessments.get(domain, {}).get("level", 1)
            new_level = min(10, current + 1)
            tracker_update_roadmap(
                topic=t["topic"], domain=domain,
                level_target=t.get("level_target", 8),
                current_level=new_level,
                status="in_progress",
            )
            break


async def cmd_challenge(command: str) -> str:
    profile = get_user_profile()
    domains = profile.get("domains", ["dsa"])
    assessments = profile.get("assessments", {})

    # Pick domain (rotate or from command arg)
    parts = command.split()
    domain = parts[1].lower() if len(parts) > 1 and parts[1].lower() in DOMAIN_PERSONAS else random.choice(domains)
    level = assessments.get(domain, {}).get("level", 3)

    roadmap = get_roadmap()
    topics = roadmap.get("domains", {}).get(domain, {}).get("topics", [])
    topic = topics[0]["topic"] if topics else "fundamentals"

    persona = DOMAIN_PERSONAS.get(domain, "")
    challenge_prompt = f"""Generate a focused practice challenge for a student.
Domain: {DOMAIN_DISPLAY.get(domain, domain)}
Topic: {topic}
Student level: {level}/10

Requirements:
- The challenge should be appropriately difficult for level {level}
- Include any necessary context/setup
- End with: "Take your time. Reply with your approach — code, pseudocode, or just your thinking."
- Keep it under 200 words total

Output only the challenge message, nothing else."""

    challenge = await run_claude(challenge_prompt, system=persona, timeout=60)
    append_message("assistant", challenge)
    log_session(domain=domain, topic=topic, session_type="challenge", summary=f"Level {level} challenge")
    return challenge


async def cmd_concept(command: str) -> str:
    profile = get_user_profile()
    domains = profile.get("domains", ["dsa"])
    assessments = profile.get("assessments", {})

    parts = command.split()
    domain = parts[1].lower() if len(parts) > 1 and parts[1].lower() in DOMAIN_PERSONAS else random.choice(domains)
    level = assessments.get(domain, {}).get("level", 3)

    roadmap = get_roadmap()
    topics = roadmap.get("domains", {}).get(domain, {}).get("topics", [])

    # Find next not-mastered topic
    summary = get_roadmap_summary()
    in_progress = [t for t in summary if t["domain"] == domain and t["status"] != "mastered"]
    topic = in_progress[0]["topic"] if in_progress else (topics[0]["topic"] if topics else "fundamentals")

    persona = DOMAIN_PERSONAS.get(domain, "")
    concept_prompt = f"""Explain a concept for a student learning {DOMAIN_DISPLAY.get(domain, domain)}.
Topic: {topic}
Student level: {level}/10

Format for Telegram:
- Start with a one-liner "what is it"
- Give the core idea in 3-4 bullet points
- One concrete example (code snippet if relevant, keep it short)
- One "why it matters" point
- End with a question to check understanding

Keep it under 300 words."""

    explanation = await run_claude(concept_prompt, system=persona, timeout=90)
    append_message("assistant", explanation)
    log_concept(domain=domain, topic=topic, title=topic, summary=explanation[:200])
    return explanation


async def cmd_progress(command: str) -> str:
    summary = get_roadmap_summary()
    profile = get_user_profile()
    domains = profile.get("domains", [])

    if not summary:
        return "No roadmap found. Your progress tracker is empty."

    msg = "📊 *Your Progress*\n\n"
    for domain in domains:
        domain_topics = [t for t in summary if t["domain"] == domain]
        if not domain_topics:
            continue
        total = len(domain_topics)
        done = sum(1 for t in domain_topics if t["status"] == "mastered")
        current_level = profile.get("assessments", {}).get(domain, {}).get("level", 1)
        msg += f"*{DOMAIN_DISPLAY.get(domain, domain)}* (Level {current_level}/10)\n"
        msg += f"  {done}/{total} topics mastered\n"
        in_progress = [t for t in domain_topics if t["status"] == "in_progress"]
        if in_progress:
            msg += f"  Currently: {in_progress[0]['topic']}\n"
        msg += "\n"

    return msg.strip()


async def cmd_status(command: str) -> str:
    profile = get_user_profile()
    assessments = profile.get("assessments", {})
    domains = profile.get("domains", [])

    msg = "⚡ *Quick Status*\n\n"
    for d in domains:
        lvl = assessments.get(d, {}).get("level", 1)
        bar = "█" * lvl + "░" * (10 - lvl)
        msg += f"{DOMAIN_DISPLAY.get(d, d)}: `{bar}` {lvl}/10\n"

    return msg.strip()


async def cmd_help(command: str) -> str:
    return (
        "🤖 *UpskillBot Commands*\n\n"
        "/challenge — get a practice challenge\n"
        "/challenge dsa — challenge for a specific domain\n"
        "/concept — get a concept explanation\n"
        "/concept ml — concept for a specific domain\n"
        "/progress — full roadmap progress\n"
        "/status — quick level overview\n"
        "/topic — see what's next on your roadmap\n\n"
        "Or just *chat with me* — ask questions, discuss topics, or ask me to explain anything!"
    )


async def cmd_topic(command: str) -> str:
    profile = get_user_profile()
    domains = profile.get("domains", [])
    summary = get_roadmap_summary()

    msg = "🗺 *Next Topics*\n\n"
    for domain in domains:
        pending = [t for t in summary if t["domain"] == domain and t["status"] != "mastered"]
        if pending:
            next_t = pending[0]
            msg += f"*{DOMAIN_DISPLAY.get(domain, domain)}:* {next_t['topic']}\n"
    return msg.strip()


def _build_coach_system(profile: dict) -> str:
    domains = profile.get("domains", [])
    assessments = profile.get("assessments", {})
    topics_str = ", ".join(
        f"{DOMAIN_DISPLAY.get(d, d)} (level {assessments.get(d, {}).get('level', 1)}/10)"
        for d in domains
    )
    return COACH_BASE.format(
        date=datetime.now().strftime("%Y-%m-%d"),
        profile=f"situation: {profile.get('situation', 'not specified')}",
        topics=topics_str,
    )


def _format_history_prompt(history: list) -> str:
    lines = []
    for m in history[-10:]:  # last 10 messages to control tokens
        role = "User" if m["role"] == "user" else "Assistant"
        lines.append(f"{role}: {m['content']}")
    return "\n\n".join(lines) + "\n\nContinue as the assistant."


def _detect_domain_from_context(history: list) -> str:
    recent = " ".join(m["content"].lower() for m in history[-4:])
    if any(k in recent for k in ["array", "tree", "graph", "dsa", "algorithm", "complexity", "leetcode"]):
        return "dsa"
    if any(k in recent for k in ["neural", "model", "training", "ml", "machine learning", "regression", "classification"]):
        return "ml"
    if any(k in recent for k in ["system design", "scale", "load balancer", "database", "distributed"]):
        return "system_design"
    if any(k in recent for k in ["llm", "rag", "prompt", "embedding", "fine-tune", "agent", "ai engineering"]):
        return "ai_engineering"
    return "dsa"
