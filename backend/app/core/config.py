from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_NAME: str = "Full Stack Mailer"
    APP_ENV: str = "development"

    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000

    DATABASE_URL: str
    REDIS_URL: str

    MICROSOFT_CLIENT_ID: str
    MICROSOFT_CLIENT_SECRET: str
    MICROSOFT_TENANT_ID: str = "common"
    MICROSOFT_REDIRECT_URI: str

    TOKEN_ENCRYPTION_KEY: str
    ACCESS_TOKEN_TTL_SECONDS: str
    SECRET_KEY: str

    # Example: "https://app.example.com,https://staging.example.com"
    ALLOWED_ORIGINS_RAW: str = "http://localhost:3000"

    # max CSV upload size in bytes (default 10 MB)
    MAX_UPLOAD_BYTES: int = 10 * 1024 * 1024

    # Cloudflare R2 — template HTML storage
    # Endpoint format: https://<account_id>.r2.cloudflarestorage.com
    R2_ENDPOINT_URL: str = ""
    R2_ACCESS_KEY_ID: str = ""
    R2_SECRET_ACCESS_KEY: str = ""
    R2_BUCKET_NAME: str = "mailer-templates"

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True)

    @field_validator("ALLOWED_ORIGINS_RAW")
    @classmethod
    def _not_star_with_credentials(cls, v: str) -> str:
        origins = [o.strip() for o in v.split(",") if o.strip()]
        if "*" in origins:
            raise ValueError(
                "ALLOWED_ORIGINS_RAW must not contain '*' — "
                "wildcard origins are incompatible with allow_credentials=True."
            )
        return v

    @property
    def allowed_origins(self) -> list[str]:
        return [o.strip() for o in self.ALLOWED_ORIGINS_RAW.split(",") if o.strip()]


settings = Settings()
