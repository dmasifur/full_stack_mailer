from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_NAME: str = "Full Stack Mailer"
    APP_ENV: str = "development"

    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000

    DATABASE_URL: str

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True)


settings = Settings()
