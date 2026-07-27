"""Application settings (pydantic-settings).

All values can be overridden via environment variables or a ``.env`` file.
Run-time config for the API; the indexer scripts also read DB_* / MONGO_* from here.
"""
from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


def _split(value: str) -> List[str]:
    return [x.strip() for x in (value or "").split(",") if x.strip()]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ── Elasticsearch ─────────────────────────────────────────────────────────
    ES_HOST: str = "https://localhost:9200"
    ES_USER: str = "elastic"
    ES_PASSWORD: str = "changeme"
    ES_CA_CERTS: str = "../Autocomplete-new/config/ca.crt"
    ES_VERIFY_CERTS: bool = True
    INDEX_NAME: str = "places"
    SYNONYM_SET_ID: str = "places_synonyms"

    # ── App / serving ─────────────────────────────────────────────────────────
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000
    DEBUG: bool = False

    # ── Access control ────────────────────────────────────────────────────────
    # CORS origins ("*" = all). Comma-separated for a list.
    ALLOWED_ORIGINS: str = "*"
    # Client IP allowlist. Empty = allow all. Comma-separated IPs/CIDRs.
    ALLOWED_IPS: str = ""

    # ── Postgres (indexer source) ─────────────────────────────────────────────
    DB_HOST: str = "localhost"
    DB_PORT: int = 5432
    DB_USER: str = "dbuser"
    DB_PASSWORD: str = ""
    DB_NAME: str = "dbname"

    # ── Mongo (optional synonym source) ───────────────────────────────────────
    MONGO_URI: str = ""
    MONGO_DB: str = "mongodb"

    @property
    def allowed_origins(self) -> List[str]:
        return _split(self.ALLOWED_ORIGINS)

    @property
    def allowed_ips(self) -> List[str]:
        return _split(self.ALLOWED_IPS)


@lru_cache
def get_settings() -> Settings:
    return Settings()
