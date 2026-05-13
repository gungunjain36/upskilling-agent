"""Multi-step onboarding flow. Fully dynamic, no hardcoded domains."""

import json
from datetime import datetime
from core import (
    run_claude,
    get_onboarding_state, save_onboarding_state,
    save_user_profile,
    save_roadmap, save_schedule_config,
    update_profile_in_tracker, update_roadmap, init_tracker,
)
from agents.personas import generate_persona, save_persona, get_assessment_question


async def handle_onboarding(user_message: str) -> str:
    state = get_onboarding_state()
    step = state.get("step", "greeting")

    if step == "greeting":
        return await _step_greeting(state)
    elif step == "goals":
        return await _step_goals(state, user_message)
    elif step == "topics":
        return await _step_topics(state, user_message)
    elif step == "generating_personas":
        # Should not happen via message, but handle gracefully
        return "Still setting up your coaches, give me a moment..."
    elif step == "level_assessment":
        return await _step_level_assessment(state, user_message)
    elif step == "schedule":
        return await _step_schedule(state, user_message)
    elif step == "confirm":
        return await _step_confirm(state, user_message)
    else:
        return "You're already set up. Type anything to start."


async def _step_greeting(state: dict) -> str:
    state["step"] = "goals"
    save_onboarding_state(state)
    return (
        "Hey, I'm *UpskillBot*, your personal learning coach.\n\n"
        "I'll ask you a few quick questions to understand where you are and where you want to go. "
        "Then I'll build your roadmap and start sending you concepts and challenges on a schedule.\n\n"
        "*What's your current situation?*\n"
        "One or two sentences is fine, e.g. 'I'm a final year CS student prepping for placements' "
        "or 'I finished an internship and have 2 months free to upskill'."
    )


async def _step_goals(state: dict, message: str) -> str:
    state["raw_situation"] = message
    state["step"] = "topics"
    save_onboarding_state(state)
    return (
        "Got it.\n\n"
        "*What do you want to learn?* List the topics or skills, separated by commas.\n\n"
        "You can say anything, DSA, System Design, Machine Learning, React, Rust, DevOps, "
        "Competitive Programming, Web3, whatever you need. No restrictions.\n\n"
        "Example: `DSA, System Design, AI Engineering`\n"
        "Or: `React, TypeScript, Node.js`\n"
        "Or: `Competitive Programming, Math for CS`"
    )


async def _step_topics(state: dict, message: str) -> str:
    # Parse topics from comma-separated input
    raw_topics = [t.strip() for t in message.split(",") if t.strip()]

    if not raw_topics:
        return "Didn't catch that. List your topics separated by commas, e.g. `DSA, System Design`."

    if len(raw_topics) > 6:
        return (
            f"That's {len(raw_topics)} topics, which is a lot to cover well. "
            "Pick up to 6 that matter most right now and reply again."
        )

    state["raw_topics"] = raw_topics
    state["step"] = "generating_personas"
    state["current_assessment_index"] = 0
    state["level_assessments"] = {}
    state["generated_domains"] = []
    save_onboarding_state(state)

    # Generate personas for all topics
    topics_list = ", ".join(raw_topics)
    generating_msg = (
        f"Building your coaches for: *{topics_list}*\n\n"
        "Give me a moment to set them up..."
    )

    # Actually generate them (this is async, happens before we reply)
    failed = []
    for topic in raw_topics:
        try:
            persona_data = await generate_persona(topic)
            save_persona(persona_data["key"], persona_data)
            state["generated_domains"].append({
                "key": persona_data["key"],
                "display_name": persona_data["display_name"],
                "original_topic": topic,
            })
        except Exception as e:
            failed.append(topic)

    if not state["generated_domains"]:
        state["step"] = "topics"
        save_onboarding_state(state)
        return "Something went wrong setting up your coaches. Try again with your topics."

    state["step"] = "level_assessment"
    save_onboarding_state(state)

    if failed:
        failed_str = ", ".join(failed)
        result = f"Set up coaches for most topics. Skipped: {failed_str} (you can add them later).\n\n"
    else:
        result = "All coaches ready.\n\n"

    return result + await _ask_level_for_current_domain(state)


async def _ask_level_for_current_domain(state: dict) -> str:
    domains = state["generated_domains"]
    idx = state.get("current_assessment_index", 0)
    domain = domains[idx]

    question = get_assessment_question(domain["key"])

    msg = f"*{domain['display_name']} level check*\n\n"
    msg += question
    msg += "\n\n_Take your time. There's no wrong answer here._"
    return msg


async def _step_level_assessment(state: dict, message: str) -> str:
    domains = state["generated_domains"]
    idx = state.get("current_assessment_index", 0)
    domain = domains[idx]

    assessment_prompt = f"""A student wants to learn {domain['display_name']}. I asked them an assessment question and they responded.

Their response: "{message}"

Rate their current level on a scale of 1-10 where:
- 1-3: Beginner (minimal knowledge)
- 4-6: Intermediate (knows basics, some gaps)
- 7-8: Advanced (solid understanding)
- 9-10: Expert level

Respond with ONLY a JSON object:
{{"level": 4, "reasoning": "one sentence", "strengths": ["what they know"], "gaps": ["what to improve"]}}"""

    try:
        result = await run_claude(assessment_prompt, timeout=60)
        start, end = result.find("{"), result.rfind("}") + 1
        assessment = json.loads(result[start:end]) if start >= 0 else {"level": 3, "strengths": [], "gaps": []}
    except Exception:
        assessment = {"level": 3, "strengths": [], "gaps": []}

    state["level_assessments"][domain["key"]] = assessment
    state["current_assessment_index"] = idx + 1
    save_onboarding_state(state)

    level = assessment["level"]
    feedback = f"*{domain['display_name']}:* placing you at level *{level}/10*.\n"
    if assessment.get("strengths"):
        feedback += f"Strong on: {', '.join(assessment['strengths'][:2])}\n"
    if assessment.get("gaps"):
        feedback += f"To work on: {', '.join(assessment['gaps'][:2])}\n"

    if state["current_assessment_index"] < len(domains):
        next_q = await _ask_level_for_current_domain(state)
        return feedback + "\n\n" + next_q
    else:
        state["step"] = "schedule"
        save_onboarding_state(state)
        return (
            feedback + "\n\n"
            "Assessments done.\n\n"
            "*When should I send you learning sessions?*\n"
            "Reply like: `every 2 hours` or `9am 2pm 7pm` or `every 3 hours from 9am to 9pm`"
        )


async def _step_schedule(state: dict, message: str) -> str:
    state["raw_schedule"] = message
    state["step"] = "confirm"
    save_onboarding_state(state)

    domains = state["generated_domains"]
    assessments = state["level_assessments"]

    summary = "*Here's your plan:*\n\n"
    summary += f"*Situation:* {state.get('raw_situation', 'Not specified')}\n\n"
    summary += "*Topics and levels:*\n"
    for d in domains:
        lvl = assessments.get(d["key"], {}).get("level", "?")
        summary += f"- {d['display_name']}: Level {lvl}/10\n"
    summary += f"\n*Schedule:* {message}\n\n"
    summary += "Reply *yes* to confirm and I'll build your roadmap. Or tell me what to change."

    return summary


async def _step_confirm(state: dict, message: str) -> str:
    if not any(w in message.lower() for w in ["yes", "yeah", "ok", "sure", "go", "yep"]):
        state["step"] = "schedule"
        save_onboarding_state(state)
        return "What schedule works better for you?"

    domains = state["generated_domains"]
    assessments = state["level_assessments"]
    situation = state.get("raw_situation", "")
    raw_schedule = state.get("raw_schedule", "every 3 hours")

    domain_summaries = "\n".join(
        f"- {d['display_name']}: current level {assessments.get(d['key'], {}).get('level', 3)}/10"
        for d in domains
    )
    domain_keys = [d["key"] for d in domains]

    roadmap_prompt = f"""Create a structured learning roadmap for a student with this profile:
Situation: {situation}
Topics and current levels:
{domain_summaries}

For each topic, create 5-8 subtopics ordered by progression from their current level to advanced.

Respond with ONLY a JSON object in this exact format:
{{
  "domains": {{
    "domain_key": {{
      "topics": [
        {{"topic": "topic name", "level_target": 6, "priority": 1, "description": "brief description"}}
      ]
    }}
  }},
  "schedule": {{
    "raw": "user's schedule string",
    "interval_hours": 3,
    "sessions_per_day": 3
  }}
}}

Domain keys must be from: {domain_keys}"""

    try:
        result = await run_claude(roadmap_prompt, timeout=90)
        start, end = result.find("{"), result.rfind("}") + 1
        roadmap_data = json.loads(result[start:end]) if start >= 0 else {}
    except Exception:
        roadmap_data = {}

    init_tracker()

    profile = {
        "onboarded": True,
        "situation": situation,
        "domains": domain_keys,
        "domain_display": {d["key"]: d["display_name"] for d in domains},
        "assessments": assessments,
        "onboarded_at": datetime.now().isoformat(),
    }
    save_user_profile(profile)
    save_roadmap(roadmap_data)

    schedule_config = roadmap_data.get("schedule", {})
    schedule_config["raw"] = raw_schedule
    if not schedule_config.get("interval_hours"):
        schedule_config["interval_hours"] = 3
    save_schedule_config(schedule_config)

    update_profile_in_tracker("situation", situation)
    update_profile_in_tracker("topics", ", ".join(d["display_name"] for d in domains))
    update_profile_in_tracker("onboarded_at", datetime.now().isoformat())

    for d in domains:
        key = d["key"]
        lvl = assessments.get(key, {}).get("level", 3)
        update_profile_in_tracker(f"{key}_initial_level", str(lvl))
        topics = roadmap_data.get("domains", {}).get(key, {}).get("topics", [])
        for t in topics:
            update_roadmap(
                topic=t["topic"],
                domain=key,
                level_target=t.get("level_target", lvl + 2),
                current_level=lvl,
                status="not_started",
                priority=t.get("priority", 1),
                notes=t.get("description", ""),
            )

    state["step"] = "done"
    save_onboarding_state(state)

    topics_list = ", ".join(d["display_name"] for d in domains)
    interval = schedule_config.get("interval_hours", 3)

    return (
        f"*You're set.*\n\n"
        f"Roadmap built for: *{topics_list}*\n"
        f"Concepts and challenges every *{interval} hours*.\n\n"
        f"Commands:\n"
        f"/challenge, get a practice problem now\n"
        f"/concept, get a concept explained\n"
        f"/progress, see your roadmap\n"
        f"/status, quick level overview\n\n"
        f"First session coming up soon. Let's get to work."
    )
