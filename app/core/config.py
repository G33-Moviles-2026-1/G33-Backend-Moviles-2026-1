from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    database_url: str
    current_term_id: str = "202610"
    google_client_id: str | None = None
    google_client_secret: str | None = None
    google_redirect_uri: str | None = None

    class Config:
        env_file = ".env"

settings = Settings()
