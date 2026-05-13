import json
from pathlib import Path
from typing import Any, Optional
from config import settings


def _ensure_dirs():
    settings.memory_dir.mkdir(parents=True, exist_ok=True)
    settings.tracker_path.parent.mkdir(parents=True, exist_ok=True)


def read_memory(filename: str) -> str:
    _ensure_dirs()
    path = settings.memory_dir / filename
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


def write_memory(filename: str, content: str):
    _ensure_dirs()
    path = settings.memory_dir / filename
    path.write_text(content, encoding="utf-8")


def read_json_memory(filename: str) -> dict:
    content = read_memory(filename)
    if not content:
        return {}
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return {}


def write_json_memory(filename: str, data: dict):
    write_memory(filename, json.dumps(data, indent=2, ensure_ascii=False))


def get_user_profile() -> dict:
    return read_json_memory("user_profile.json")


def save_user_profile(profile: dict):
    write_json_memory("user_profile.json", profile)


def update_user_profile(updates: dict):
    profile = get_user_profile()
    profile.update(updates)
    save_user_profile(profile)


def get_conversation_history() -> list[dict]:
    data = read_json_memory("conversation_history.json")
    return data.get("messages", [])


def save_conversation_history(messages: list[dict]):
    write_json_memory("conversation_history.json", {"messages": messages})


def append_message(role: str, content: str, max_history: int = 20):
    """Append a message and trim to max_history to control token usage."""
    messages = get_conversation_history()
    messages.append({"role": role, "content": content})
    if len(messages) > max_history:
        messages = messages[-max_history:]
    save_conversation_history(messages)


def get_roadmap() -> dict:
    return read_json_memory("roadmap.json")


def save_roadmap(roadmap: dict):
    write_json_memory("roadmap.json", roadmap)


def get_schedule_config() -> dict:
    return read_json_memory("schedule_config.json")


def save_schedule_config(config: dict):
    write_json_memory("schedule_config.json", config)


def is_onboarded() -> bool:
    profile = get_user_profile()
    return profile.get("onboarded", False)


def get_onboarding_state() -> dict:
    return read_json_memory("onboarding_state.json")


def save_onboarding_state(state: dict):
    write_json_memory("onboarding_state.json", state)
