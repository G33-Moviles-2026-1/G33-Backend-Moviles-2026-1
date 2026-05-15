import os

from pydantic_settings import BaseSettings


def _first_env_value(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value and value.strip():
            return value.strip()
    return None


class Settings(BaseSettings):
    database_url: str
    current_term_id: str = "202610"
    google_client_id: str | None = None
    google_client_secret: str | None = None
    google_redirect_uri: str | None = None

    @property
    def resolved_google_client_id(self) -> str | None:
        return self.google_client_id or _first_env_value(
            "GOOGLE_CLIENT_ID",
            "GOOGLE_OAUTH_CLIENT_ID",
            "GOOGLE_CALENDAR_CLIENT_ID",
        )

    @property
    def resolved_google_client_secret(self) -> str | None:
        return self.google_client_secret or _first_env_value(
            "GOOGLE_CLIENT_SECRET",
            "GOOGLE_OAUTH_CLIENT_SECRET",
            "GOOGLE_CALENDAR_CLIENT_SECRET",
        )

    @property
    def resolved_google_redirect_uri(self) -> str | None:
        return self.google_redirect_uri or _first_env_value(
            "GOOGLE_REDIRECT_URI",
            "GOOGLE_OAUTH_REDIRECT_URI",
            "GOOGLE_CALENDAR_REDIRECT_URI",
        )

    @property
    def missing_google_oauth_settings(self) -> list[str]:
        missing: list[str] = []
        if not self.resolved_google_client_id:
            missing.append("GOOGLE_CLIENT_ID")
        if not self.resolved_google_client_secret:
            missing.append("GOOGLE_CLIENT_SECRET")
        return missing

    @property
    def google_oauth_configured(self) -> bool:
        return not self.missing_google_oauth_settings

    class Config:
        env_file = ".env"

settings = Settings()
