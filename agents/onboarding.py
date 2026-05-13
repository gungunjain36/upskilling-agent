"""Multi-step onboarding flow to profile the user and build their roadmap."""

import json
from datetime import datetime
from core import (
    run_claude,
    get_onboarding_state, save_onboarding_state,
    get_user_profile, save_user_profile,
    save_roadmap, save_schedule_config,
    update_profile_in_tracker, update_roadmap, init_tracker,
)

ONBOARDING_STEPS = [
    "greeting",
    "goals",
    "domains",
    "level_assessment",
    "schedule",
    "confirm",
    "done",
]

DOMAIN_OPTIONS = {
    "1": "dsa",
    "2": "ml",
    "3": "system_design",
    "4": "ai_engineering",
}


async def handle_onboarding(user_message: str) -> str:
    state = get_onboarding_state()
    step = state.get("step", "greeting")

    if step == "greeting":
        return await _step_greeting(state)
    elif step == "goals":
        return await _step_goals(state, user_message)
    elif step == "domains":
        return await _step_domains(state, user_message)
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
    state["step"] = "domains"
    save_onboarding_state(state)
    return (
        "Got it.\n\n"
        "*Which areas do you want to focus on?* Reply with the numbers, e.g. `1 3` for DSA and System Design:\n\n"
        "1. DSA (Data Structures and Algorithms)\n"
        "2. Machine Learning\n"
        "3. System Design\n"
        "4. AI Engineering (building with LLMs and APIs)\n\n"
        "You can pick 1 to 4."
    )


async def _step_domains(state: dict, message: str) -> str:
    selected = []
    for char in message.strip():
        if char in DOMAIN_OPTIONS:
            domain = DOMAIN_OPTIONS[char]
            if domain not in selected:
                selected.append(domain)

    if not selected:
        return "Didn't catch that. Reply with numbers like `1 3` to select your domains."

    state["domains"] = selected
    state["current_domain_index"] = 0
    state["level_assessments"] = {}
    state["step"] = "level_assessment"
    save_onboarding_state(state)

    return await _ask_level_for_domain(state)


async def _ask_level_for_domain(state: dict) -> str:
    domains = state["domains"]
    idx = state.get("current_domain_index", 0)
    domain = domains[idx]

    domain_display = {
        "dsa": "DSA", "ml": "Machine Learning",
        "system_design": "System Design", "ai_engineering": "AI Engineering"
    }

    assessment_questions = {
        "dsa": (
            "*DSA level check*\n\n"
            "Given an array `[3,1,4,1,5,9,2,6]`, describe how you'd find two numbers that add up to a target sum.\n\n"
            "Just explain your approach, no need to write full code."
        ),
        "ml": (
            "*ML level check*\n\n"
            "What is overfitting, and how would you detect and fix it?"
        ),
        "system_design": (
            "*System Design level check*\n\n"
            "If you had to design a URL shortener like bit.ly, what are the first 3 components you'd think about?"
        ),
        "ai_engineering": (
            "*AI Engineering level check*\n\n"
            "What is RAG (Retrieval-Augmented Generation) and when would you use it instead of fine-tuning?"
        ),
    }

    msg = f"Let me check your level in *{domain_display[domain]}*.\n\n"
    msg += assessment_questions[domain]
    msg += "\n\n_Take your time. There's no wrong answer here._"
    return msg


async def _step_level_assessment(state: dict, message: str) -> str:
    domains = state["domains"]
    idx = state.get("current_domain_index", 0)
    domain = domains[idx]

    domain_display = {
        "dsa": "DSA", "ml": "Machine Learning",
        "system_design": "System Design", "ai_engineering": "AI Engineering"
    }

    assessment_prompt = f"""A student is learning {domain_display[domain]}. I asked them an assessment question and they responded.

Their response: "{message}"

Based on this response, rate their current level on a scale of 1-10 where:
- 1-3: Beginner (minimal knowledge)
- 4-6: Intermediate (knows basics, some gaps)
- 7-8: Advanced (solid understanding)
- 9-10: Expert level

Respond with ONLY a JSON object like this:
{{"level": 4, "reasoning": "one sentence explanation", "strengths": ["what they know"], "gaps": ["what to improve"]}}"""

    try:
        result = await run_claude(assessment_prompt, timeout=60)
        start = result.find("{")
        end = result.rfind("}") + 1
        if start >= 0 and end > start:
            assessment = json.loads(result[start:end])
        else:
            assessment = {"level": 3, "reasoning": "Could not parse response", "strengths": [], "gaps": []}
    except Exception:
        assessment = {"level": 3, "reasoning": "Assessment error", "strengths": [], "gaps": []}

    state["level_assessments"][domain] = assessment
    state["current_domain_index"] = idx + 1
    save_onboarding_state(state)

    level = assessment["level"]
    feedback = f"*{domain_display[domain]}:* placing you at level *{level}/10*.\n"
    if assessment.get("strengths"):
        feedback += f"Strong on: {', '.join(assessment['strengths'][:2])}\n"
    if assessment.get("gaps"):
        feedback += f"To work on: {', '.join(assessment['gaps'][:2])}\n"

    if state["current_domain_index"] < len(domains):
        save_onboarding_state(state)
        next_question = await _ask_level_for_domain(state)
        return feedback + "\n\n" + next_question
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

    domains = state["domains"]
    assessments = state["level_assessments"]

    domain_display = {
        "dsa": "DSA", "ml": "Machine Learning",
        "system_design": "System Design", "ai_engineering": "AI Engineering"
    }

    summary = "*Here's your plan:*\n\n"
    summary += f"*Situation:* {state.get('raw_situation', 'Not specified')}\n\n"
    summary += "*Domains and levels:*\n"
    for d in domains:
        lvl = assessments.get(d, {}).get("level", "?")
        summary += f"- {domain_display[d]}: Level {lvl}/10\n"
    summary += f"\n*Schedule:* {message}\n\n"
    summary += "Reply *yes* to confirm and I'll build your roadmap. Or tell me what to change."

    return summary


async def _step_confirm(state: dict, message: str) -> str:
    if not any(w in message.lower() for w in ["yes", "yeah", "ok", "sure", "go", "yep"]):
        state["step"] = "schedule"
        save_onboarding_state(state)
        return "Alright, what schedule works better for you?"

    domains = state["domains"]
    assessments = state["level_assessments"]
    situation = state.get("raw_situation", "")
    raw_schedule = state.get("raw_schedule", "every 3 hours")

    domain_display = {
        "dsa": "DSA", "ml": "Machine Learning",
        "system_design": "System Design", "ai_engineering": "AI Engineering"
    }

    domain_summaries = "\n".join(
        f"- {domain_display[d]}: current level {assessments.get(d, {}).get('level', 3)}/10"
        for d in domains
    )

    roadmap_prompt = f"""Create a structured learning roadmap for a student with this profile:
Situation: {situation}
Domains and current levels:
{domain_summaries}

For each domain, create 5-8 topics ordered by progression from their current level to advanced.

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

Domain keys must be from: {domains}"""

    try:
        result = await run_claude(roadmap_prompt, timeout=90)
        start = result.find("{")
        end = result.rfind("}") + 1
        roadmap_data = json.loads(result[start:end]) if start >= 0 else {}
    except Exception:
        roadmap_data = {}

    init_tracker()

    profile = {
        "onboarded": True,
        "situation": situation,
        "domains": domains,
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
    update_profile_in_tracker("domains", ", ".join(domain_display[d] for d in domains))
    update_profile_in_tracker("onboarded_at", datetime.now().isoformat())

    for d in domains:
        lvl = assessments.get(d, {}).get("level", 3)
        update_profile_in_tracker(f"{d}_initial_level", str(lvl))
        topics = roadmap_data.get("domains", {}).get(d, {}).get("topics", [])
        for t in topics:
            update_roadmap(
                topic=t["topic"],
                domain=d,
                level_target=t.get("level_target", lvl + 2),
                current_level=lvl,
                status="not_started",
                priority=t.get("priority", 1),
                notes=t.get("description", ""),
            )

    state["step"] = "done"
    save_onboarding_state(state)

    domains_list = ", ".join(domain_display[d] for d in domains)
    interval = schedule_config.get("interval_hours", 3)

    return (
        f"*You're set.*\n\n"
        f"Roadmap built for: *{domains_list}*\n"
        f"Concepts and challenges will come every *{interval} hours*.\n\n"
        f"Commands:\n"
        f"/challenge, get a practice problem now\n"
        f"/concept, get a concept explained\n"
        f"/progress, see your roadmap\n"
        f"/status, quick level overview\n\n"
        f"First session coming up soon. Let's get to work."
    )
