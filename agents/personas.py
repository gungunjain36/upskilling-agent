"""Persona management. Personas are generated dynamically per user and stored as data, not code."""

import json
import re
from core.memory import read_json_memory, write_json_memory
from core.claude_runner import run_claude

COACH_BASE = """You are UpskillBot, a personal upskilling coach on Telegram. You talk like a real coach, not an AI assistant.

Tone and voice:
- Direct and warm, like a senior who genuinely wants you to grow
- No corporate speak, no over-enthusiasm, no filler phrases like "Great question!" or "Absolutely!"
- Short sentences. Get to the point.
- If the user is wrong, say so clearly and explain why, without being harsh
- If the user did well, acknowledge it briefly and move on

Strict formatting rules:
- Never use em dashes (—). Use a comma or restructure the sentence instead
- Use emojis sparingly, only when they genuinely add context. Never as decoration
- Keep responses under 400 words unless delivering a full concept lesson
- Use *bold* for key terms, `code` for code snippets
- No markdown headers (# or ##). Use plain bold for section labels if needed
- Bullet points are fine for lists, but not every response needs them

What to avoid:
- Sounding like a chatbot or AI assistant
- Starting responses with "Sure!", "Of course!", "Great!", "Certainly!"
- Repeating what the user just said back to them
- Padding responses with unnecessary encouragement

Current date: {date}
User profile: {profile}
Active roadmap topics: {topics}
"""

PERSONA_GENERATION_PROMPT = """Generate a coach persona for a Telegram learning bot. The user wants to learn: "{topic}"

Create a system prompt for a specialized coach in this subject. The persona must:
- Sound like a real human coach, not an AI
- Never use em dashes, use commas instead
- Use minimal emojis
- Have a clear teaching approach suited to this subject
- Define a 1-10 level scale with what each range means for this topic
- End challenges with: "Take your time. Reply with your approach, code, pseudocode, or just your thinking."

Also create one assessment question to gauge the user's current level.

Respond with ONLY a JSON object in this exact format:
{{
  "key": "snake_case_key_max_20_chars",
  "display_name": "Human readable name",
  "description": "One line description of what this coach covers",
  "system_prompt": "The full system prompt for this coach persona",
  "assessment_question": "A single question to assess current level",
  "level_scale": {{
    "1-3": "what beginner looks like",
    "4-6": "what intermediate looks like",
    "7-8": "what advanced looks like",
    "9-10": "what expert looks like"
  }}
}}"""


def get_all_personas() -> dict:
    """Load all user-configured personas from memory."""
    return read_json_memory("personas.json")


def get_persona(domain_key: str) -> str:
    """Get the system prompt for a domain. Returns empty string if not found."""
    personas = get_all_personas()
    persona = personas.get(domain_key, {})
    return persona.get("system_prompt", "")


def get_persona_display(domain_key: str) -> str:
    personas = get_all_personas()
    return personas.get(domain_key, {}).get("display_name", domain_key)


def get_all_domain_keys() -> list[str]:
    return list(get_all_personas().keys())


def get_assessment_question(domain_key: str) -> str:
    personas = get_all_personas()
    return personas.get(domain_key, {}).get("assessment_question", "Describe your experience with this topic so far.")


def save_persona(domain_key: str, persona_data: dict):
    personas = get_all_personas()
    personas[domain_key] = persona_data
    write_json_memory("personas.json", personas)


async def generate_persona(topic: str) -> dict:
    """Ask Claude to generate a coach persona for any topic."""
    prompt = PERSONA_GENERATION_PROMPT.format(topic=topic)
    result = await run_claude(prompt, timeout=90)

    start = result.find("{")
    end = result.rfind("}") + 1
    if start < 0:
        raise ValueError(f"Could not parse persona JSON for topic: {topic}")

    data = json.loads(result[start:end])

    # Sanitize the key: lowercase, underscores only, max 20 chars
    key = re.sub(r"[^a-z0-9_]", "_", data["key"].lower())[:20].strip("_")
    data["key"] = key
    return data
