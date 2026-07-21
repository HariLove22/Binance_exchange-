from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    app_name: str = "Binance Clone API"
    environment: str = "development"
    debug: bool = True

    api_v1_prefix: str = "/api/v1"

    postgres_user: str = "binance"
    postgres_password: str = "binance_dev_password"
    postgres_host: str = "localhost"
    # 5433, not 5432 — a native PostgreSQL service already owns 5432 on this dev machine.
    postgres_port: int = 5433
    postgres_db: str = "binance"

    # Seconds before a connection attempt / pool wait gives up. Keep these short: an endpoint
    # that hangs on a dead database cannot be distinguished from a slow one.
    # Note this is per resolved host, and "localhost" resolves to both ::1 and 127.0.0.1 — so a
    # fully unreachable database takes roughly double this to report. Keep the total under the
    # client's fetch timeout, or the UI reports a timeout instead of the actual error.
    db_connect_timeout: int = 3
    db_pool_timeout: int = 5

    redis_host: str = "localhost"
    redis_port: int = 6379

    cors_origins: list[str] = ["http://localhost:5173"]

    # --- Auth / JWT ---------------------------------------------------------
    # In production the secret MUST come from the environment and never be committed —
    # anyone holding it can mint a valid token for any user.
    jwt_secret: str = "dev-only-change-me-in-production-please"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24  # 24h; shorten + add refresh tokens in prod

    # --- Email verification (currently DISABLED) ---------------------------
    # require_email_verification=False → users can log in immediately after registering.
    # Flip to True (plus email_enabled=True + SMTP below) to enforce the verify flow.
    require_email_verification: bool = False
    # email_enabled=False → verification links are logged to the console, not actually sent.
    email_enabled: bool = False
    verification_token_expire_hours: int = 48
    frontend_url: str = "http://localhost:5173"

    # SMTP — unused while email_enabled is False, wired for later.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "no-reply@novex.local"

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
