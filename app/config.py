"""Настройки приложения.

Все параметры читаются из окружения (или из файла `.env`), поэтому один и тот же
образ работает локально, в CI и в production без пересборки. Никакой секрет не
зашит в код: у `secret_key` есть заведомо ненастоящее значение по умолчанию, с
которым приложение отказывается стартовать в production.
"""

from functools import lru_cache

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "ApplyTrack API"
    version: str = "1.0.0"
    debug: bool = False

    # --- База данных --------------------------------------------------
    database_url: str = (
        "postgresql+psycopg://applytrack:applytrack@localhost:5432/applytrack"
    )
    sql_echo: bool = False

    # --- Аутентификация -----------------------------------------------
    # `environment` объявлено раньше `secret_key`, потому что валидатор ниже
    # читает его из `info.data`, а там лежат только поля, проверенные раньше
    # в порядке объявления.
    environment: str = "development"

    secret_key: str = Field(
        default="dev-only-insecure-secret-key-change-me",
        min_length=16,
    )
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24
    password_min_length: int = 8

    # --- CORS ----------------------------------------------------------
    # Значения через запятую, например "https://a.com,https://b.com".
    cors_origins: str = "http://localhost:3000,http://localhost:5173"

    # --- Логирование ---------------------------------------------------
    # "console" — читаемая строка для терминала; "json" — один JSON-объект
    # на строку, который умеет индексировать сборщик логов.
    log_level: str = "INFO"
    log_format: str = "console"

    @field_validator("secret_key")
    @classmethod
    def _reject_default_secret_in_production(cls, value: str, info) -> str:
        environment = info.data.get("environment", "development")
        if environment == "production" and value.startswith("dev-only-insecure"):
            raise ValueError(
                "При ENVIRONMENT=production в SECRET_KEY должно стоять настоящее значение"
            )
        return value

    @field_validator("log_format")
    @classmethod
    def _known_log_format(cls, value: str) -> str:
        allowed = {"console", "json"}
        if value not in allowed:
            raise ValueError(f"LOG_FORMAT должен быть одним из {sorted(allowed)}")
        return value

    @model_validator(mode="after")
    def _json_logs_in_production(self) -> "Settings":
        """По умолчанию логи в production — JSON, но только если не сказано иначе.

        `model_fields_set` содержит поля, заданные явно (из окружения или из
        файла `.env`), поэтому явный `LOG_FORMAT=console` всё равно побеждает
        значение по умолчанию.
        """
        if "log_format" not in self.model_fields_set and self.environment == "production":
            self.log_format = "json"
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    """Кэшируем, чтобы окружение разбиралось один раз за процесс."""
    return Settings()
