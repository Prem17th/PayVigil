import os
import re
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class SponsorSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(
            Path(__file__).resolve().parents[3] / ".env",
            Path(__file__).resolve().parents[2] / ".env",
        ),
        extra="ignore",
    )
    n8n_callback_auth_mode: Literal["header", "hmac"] = "header"
    n8n_webhook_url: str = ""
    n8n_webhook_token: SecretStr = SecretStr("")
    n8n_callback_secret: SecretStr = SecretStr("")
    elevenlabs_api_key: SecretStr = SecretStr("")
    elevenlabs_voice_id: str = ""
    dodo_api_key: SecretStr = SecretStr("")
    dodo_product_id: str = ""
    dodo_webhook_secret: SecretStr = SecretStr("")
    billing_frontend_origin: str = ""

    @property
    def n8n_configured(self):
        return secure_url(self.n8n_webhook_url) and bool(
            self.n8n_webhook_token.get_secret_value()
            and self.n8n_callback_secret.get_secret_value()
        )

    @property
    def voice_configured(self):
        return bool(
            self.elevenlabs_api_key.get_secret_value()
            and re.fullmatch(r"[A-Za-z0-9_-]{1,100}", self.elevenlabs_voice_id)
        )

    @property
    def billing_configured(self):
        return bool(
            self.dodo_api_key.get_secret_value()
            and self.dodo_webhook_secret.get_secret_value()
            and re.fullmatch(r"[A-Za-z0-9_-]{1,100}", self.dodo_product_id)
            and secure_url(self.billing_frontend_origin, origin_only=True)
        )


def secure_url(value: str, *, origin_only=False) -> bool:
    try:
        parsed = urlsplit(value)
        return bool(
            parsed.scheme == "https"
            and parsed.hostname
            and parsed.port in {None, 443}
            and not parsed.username
            and not parsed.password
            and not parsed.query
            and not parsed.fragment
            and (not origin_only or not parsed.path or parsed.path == "/")
        )
    except ValueError:
        return False


@lru_cache
def get_sponsor_settings():
    return (
        SponsorSettings(_env_file=None)
        if os.environ.get("BEFORETRANSFER_DISABLE_DOTENV") == "1"
        else SponsorSettings()
    )
