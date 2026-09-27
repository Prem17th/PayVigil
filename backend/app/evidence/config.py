import os
from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class EvidenceSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(
            Path(__file__).resolve().parents[3] / ".env",
            Path(__file__).resolve().parents[2] / ".env",
        ),
        extra="ignore",
    )
    openai_api_key: SecretStr = SecretStr("")
    openai_model: str = ""
    breeth_api_key: SecretStr = SecretStr("")

    @property
    def openai_configured(self):
        return bool(self.openai_api_key.get_secret_value().strip() and self.openai_model.strip())

    @property
    def breeth_configured(self):
        return bool(self.breeth_api_key.get_secret_value().strip())


@lru_cache
def get_evidence_settings() -> EvidenceSettings:
    return (
        EvidenceSettings(_env_file=None)
        if os.getenv("BEFORETRANSFER_DISABLE_DOTENV") == "1"
        else EvidenceSettings()
    )
