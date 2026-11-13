from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    admin_secret: str
    key_pepper: str
    database_url: str = "sqlite:///./data/pocketnode.db"
    inference_timeout_seconds: int = 120
    max_input_characters: int = 20000
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

@lru_cache
def get_settings() -> Settings:
    result = Settings()
    if len(result.admin_secret) < 24 or len(result.key_pepper) < 24:
        raise RuntimeError("ADMIN_SECRET and KEY_PEPPER must each contain at least 24 characters")
    return result
