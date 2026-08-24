import ssl

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# "none" disables verification entirely and exists only for providers behind a
# private CA. It makes the broker connection MITM-able, so it is never default.
_SSL_CERT_REQS = {
    "required": ssl.CERT_REQUIRED,
    "optional": ssl.CERT_OPTIONAL,
    "none": ssl.CERT_NONE,
}


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
    ACCESS_TOKEN_TTL_SECONDS: int = 60 * 60 * 8
    SECRET_KEY: str

    ALLOWED_ORIGINS_RAW: str = "http://localhost:3000"

    # Empty means the OAuth callback returns JSON instead of redirecting.
    FRONTEND_URL: str = ""

    MAX_UPLOAD_BYTES: int = 10 * 1024 * 1024

    REDIS_SSL_CERT_REQS: str = "required"

    R2_ENDPOINT_URL: str = ""
    R2_ACCESS_KEY_ID: str = ""
    R2_SECRET_ACCESS_KEY: str = ""
    R2_BUCKET_NAME: str = "mailer-templates"

    # Public read URL for the bucket, used only for inline campaign images.
    # Empty disables image upload — see app/services/asset_storage.py.
    R2_PUBLIC_BASE_URL: str = ""

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

    @field_validator("ACCESS_TOKEN_TTL_SECONDS")
    @classmethod
    def _positive_ttl(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("ACCESS_TOKEN_TTL_SECONDS must be a positive integer.")
        return v

    @field_validator("R2_PUBLIC_BASE_URL")
    @classmethod
    def _no_trailing_slash(cls, v: str) -> str:
        """Keys are joined with a literal "/", so a trailing slash doubles it."""
        return v.rstrip("/")

    @field_validator("REDIS_SSL_CERT_REQS")
    @classmethod
    def _known_cert_reqs(cls, v: str) -> str:
        if v.lower() not in _SSL_CERT_REQS:
            raise ValueError(
                f"REDIS_SSL_CERT_REQS must be one of {sorted(_SSL_CERT_REQS)}, got {v!r}."
            )
        return v.lower()

    @property
    def allowed_origins(self) -> list[str]:
        return [o.strip() for o in self.ALLOWED_ORIGINS_RAW.split(",") if o.strip()]

    @property
    def is_development(self) -> bool:
        return self.APP_ENV == "development"

    @property
    def redis_is_tls(self) -> bool:
        """
        Whether REDIS_URL negotiates TLS.

        SSL options on a plain redis:// URL are silently ignored, so callers
        must not send them.
        """
        return self.REDIS_URL.startswith("rediss://")

    @property
    def redis_ssl_cert_reqs(self) -> ssl.VerifyMode:
        return _SSL_CERT_REQS[self.REDIS_SSL_CERT_REQS]

    @property
    def redis_ssl_options(self) -> dict[str, object] | None:
        """
        SSL options for the broker connection, or None for a non-TLS URL.

        ssl_check_hostname must travel with ssl_cert_reqs: Python refuses to
        combine hostname checking with CERT_NONE, so the "none" escape hatch
        would otherwise be a hard connection error.
        """
        if not self.redis_is_tls:
            return None

        verify = self.REDIS_SSL_CERT_REQS != "none"

        return {
            "ssl_cert_reqs": self.redis_ssl_cert_reqs,
            "ssl_check_hostname": verify,
        }


settings = Settings()
