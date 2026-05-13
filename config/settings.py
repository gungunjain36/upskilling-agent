from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    telegram_bot_token: str
    telegram_chat_id: str
    claude_cli_path: str = "claude"
    data_dir: Path = Path("./data")
    timezone: str = "Asia/Kolkata"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    @property
    def memory_dir(self) -> Path:
        return self.data_dir / "memory"

    @property
    def tracker_path(self) -> Path:
        return self.data_dir / "tracker" / "progress.xlsx"


settings = Settings()
