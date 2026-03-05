from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    database_url: str
    current_term_id: str = "202610"

    class Config:
        env_file = ".env"

settings = Settings()