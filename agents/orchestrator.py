"""Main orchestrator — routes user messages to the right agent."""

import json
import random
from datetime import datetime
from core import (
    run_claude, run_claude_in_session,
    get_user_profile,
    get_roadmap, is_onboarded,
    log_session, log_challenge, log_concept,
    update_roadmap as tracker_update_roadmap,
    get_roadmap_summary,
    get_last_response, save_last_response,
    clear_session, save_session_summary,
)
from agents.personas import (
    COACH_BASE,
    get_persona, get_persona_display, get_all_domain_keys, get_all_personas,
)
from agents.onboarding import handle_onboarding


async def handle_message(user_message: str) -> str:
    if not is_onboarded():
        return await handle_onboarding(user_message)

    if user_message.startswith("/"):
        return await handle_command(user_message)

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
        "/domains": cmd_domains,
    }
    handler = handlers.get(cmd)
    if handler:
        return await handler(command)
    return "Unknown command. Type /help to see what's available."


async def handle_chat(user_message: str) -> str:
    profile = get_user_profile()
    last_response = get_last_response()

    if _is_challenge_response(last_response, user_message):
        return await evaluate_challenge_response(user_message, last_response, profile)

    system = _build_coach_system(profile)
    response = await run_claude_in_session(user_message, system=system, timeout=90)

    save_last_response(response)
    log_session(
        domain=_detect_domain_from_profile(profile),
        topic="general",
        session_type="chat",
        summary=user_message[:100],
    )
    return response


def _is_challenge_response(last_assistant: str, message: str) -> bool:
    if not last_assistant:
        return False
    markers = ["take your time", "reply with your approach", "try this", "your turn", "solve this"]
    return any(m in last_assistant.lower() for m in markers)


async def evaluate_challenge_response(response: str, last_challenge: str, profile: dict) -> str:
    domain = _detect_domain_from_profile(profile)
    persona = get_persona(domain)

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

Keep it under 250 words. Be direct. Format for Telegram, no markdown headers.
End with either a follow-up challenge or confirm they've mastered this and move on.

Respond with JSON:
{{"evaluation": "your evaluation text", "score": 7, "topic": "topic name", "mastered": false}}"""

    try:
        result = await run_claude(eval_prompt, system=persona, timeout=90)
        start, end = result.find("{"), result.rfind("}") + 1
        data = json.loads(result[start:end]) if start >= 0 else {"evaluation": result, "score": 5, "topic": "general", "mastered": False}
    except Exception:
        data = {"evaluation": response, "score": 5, "topic": "general", "mastered": False}

    evaluation_text = data.get("evaluation", "Good attempt. Keep going.")
    score = data.get("score", 5)
    topic = data.get("topic", "general")

    save_last_response(evaluation_text)

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
    domains = profile.get("domains", [])
    assessments = profile.get("assessments", {})

    if not domains:
        return "No domains set up yet. Complete onboarding first."

    parts = command.split()
    # Match arg against known domain keys or display names
    domain = _resolve_domain_arg(parts[1] if len(parts) > 1 else None, domains, profile)
    level = assessments.get(domain, {}).get("level", 3)

    roadmap = get_roadmap()
    topics = roadmap.get("domains", {}).get(domain, {}).get("topics", [])
    topic = topics[0]["topic"] if topics else "fundamentals"

    persona = get_persona(domain)
    display = get_persona_display(domain)

    challenge_prompt = f"""Generate a focused practice challenge for a student.
Domain: {display}
Topic: {topic}
Student level: {level}/10

Requirements:
- Appropriately difficult for level {level}
- Include any necessary context or setup
- End with: "Take your time. Reply with your approach, code, pseudocode, or just your thinking."
- Keep it under 200 words

Output only the challenge message, nothing else."""

    challenge = await run_claude(challenge_prompt, system=persona, timeout=60)
    save_last_response(challenge)
    log_session(domain=domain, topic=topic, session_type="challenge", summary=f"Level {level} challenge")
    return challenge


async def cmd_concept(command: str) -> str:
    profile = get_user_profile()
    domains = profile.get("domains", [])
    assessments = profile.get("assessments", {})

    if not domains:
        return "No domains set up yet. Complete onboarding first."

    parts = command.split()
    domain = _resolve_domain_arg(parts[1] if len(parts) > 1 else None, domains, profile)
    level = assessments.get(domain, {}).get("level", 3)

    roadmap = get_roadmap()
    topics = roadmap.get("domains", {}).get(domain, {}).get("topics", [])

    summary = get_roadmap_summary()
    in_progress = [t for t in summary if t["domain"] == domain and t["status"] != "mastered"]
    topic = in_progress[0]["topic"] if in_progress else (topics[0]["topic"] if topics else "fundamentals")

    persona = get_persona(domain)
    display = get_persona_display(domain)

    concept_prompt = f"""Explain a concept for a student learning {display}.
Topic: {topic}
Student level: {level}/10

Format for Telegram:
- Start with a one-liner "what is it"
- Core idea in 3-4 bullet points
- One concrete example (code snippet if relevant, keep it short)
- One "why it matters" point
- End with a question to check understanding

Keep it under 300 words."""

    explanation = await run_claude(concept_prompt, system=persona, timeout=90)
    save_last_response(explanation)
    log_concept(domain=domain, topic=topic, title=topic, summary=explanation[:200])
    return explanation


async def cmd_progress(command: str) -> str:
    summary = get_roadmap_summary()
    profile = get_user_profile()
    domains = profile.get("domains", [])

    if not summary:
        return "No roadmap found. Your progress tracker is empty."

    msg = "*Your Progress*\n\n"
    for domain in domains:
        display = get_persona_display(domain)
        domain_topics = [t for t in summary if t["domain"] == domain]
        if not domain_topics:
            continue
        total = len(domain_topics)
        done = sum(1 for t in domain_topics if t["status"] == "mastered")
        current_level = profile.get("assessments", {}).get(domain, {}).get("level", 1)
        msg += f"*{display}* (Level {current_level}/10)\n"
        msg += f"  {done}/{total} topics mastered\n"
        in_prog = [t for t in domain_topics if t["status"] == "in_progress"]
        if in_prog:
            msg += f"  Currently on: {in_prog[0]['topic']}\n"
        msg += "\n"

    return msg.strip()


async def cmd_status(command: str) -> str:
    profile = get_user_profile()
    assessments = profile.get("assessments", {})
    domains = profile.get("domains", [])

    msg = "*Status*\n\n"
    for d in domains:
        lvl = assessments.get(d, {}).get("level", 1)
        bar = "█" * lvl + "░" * (10 - lvl)
        msg += f"{get_persona_display(d)}: `{bar}` {lvl}/10\n"

    return msg.strip()


async def cmd_help(command: str) -> str:
    profile = get_user_profile()
    domains = profile.get("domains", [])
    domain_list = ", ".join(get_persona_display(d).lower() for d in domains) if domains else "your topics"

    return (
        "*Commands*\n\n"
        "/challenge, get a practice problem\n"
        f"/challenge {domain_list.split(',')[0].strip() if domains else 'topic'}, challenge for a specific topic\n"
        "/concept, get a concept explained\n"
        "/concept <topic>, concept for a specific topic\n"
        "/progress, full roadmap progress\n"
        "/status, quick level overview\n"
        "/topic, see what's next on your roadmap\n"
        "/domains, list all your configured topics\n\n"
        "Or just chat, ask questions, work through topics, whatever you need."
    )


async def cmd_topic(command: str) -> str:
    profile = get_user_profile()
    domains = profile.get("domains", [])
    summary = get_roadmap_summary()

    msg = "*Next Topics*\n\n"
    for domain in domains:
        pending = [t for t in summary if t["domain"] == domain and t["status"] != "mastered"]
        if pending:
            msg += f"*{get_persona_display(domain)}:* {pending[0]['topic']}\n"
    return msg.strip()


async def cmd_domains(command: str) -> str:
    profile = get_user_profile()
    domains = profile.get("domains", [])
    assessments = profile.get("assessments", {})

    if not domains:
        return "No topics configured yet."

    msg = "*Your Topics*\n\n"
    for d in domains:
        lvl = assessments.get(d, {}).get("level", 1)
        msg += f"- *{get_persona_display(d)}* (level {lvl}/10)\n"
    return msg.strip()


def _resolve_domain_arg(arg: str | None, domains: list, profile: dict) -> str:
    """Match a command argument to a domain key. Falls back to random choice."""
    if not arg:
        return random.choice(domains)

    arg_lower = arg.lower()
    # Exact key match
    if arg_lower in domains:
        return arg_lower
    # Partial display name match
    domain_display = profile.get("domain_display", {})
    for key in domains:
        display = domain_display.get(key, key).lower()
        if arg_lower in display or display in arg_lower:
            return key
    return random.choice(domains)


def _build_coach_system(profile: dict) -> str:
    domains = profile.get("domains", [])
    assessments = profile.get("assessments", {})
    topics_str = ", ".join(
        f"{get_persona_display(d)} (level {assessments.get(d, {}).get('level', 1)}/10)"
        for d in domains
    )
    return COACH_BASE.format(
        date=datetime.now().strftime("%Y-%m-%d"),
        profile=f"situation: {profile.get('situation', 'not specified')}",
        topics=topics_str,
    )


def _detect_domain_from_profile(profile: dict) -> str:
    domains = profile.get("domains", [])
    if not domains:
        return "general"
    return random.choice(domains)
