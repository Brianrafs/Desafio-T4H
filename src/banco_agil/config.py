"""Configuração local; credenciais nunca são incluídas em representações."""

from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    groq_api_key: SecretStr = SecretStr("")
    groq_model: str = "groq/llama-3.3-70b-versatile"
    awesome_api_key: SecretStr = SecretStr("")
    data_dir: Path = Path("runtime/data")
