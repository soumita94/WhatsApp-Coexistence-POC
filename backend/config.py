from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

# .env lives in the project root (one level above backend/)
_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    # Meta App
    meta_app_id: str = ""
    meta_app_secret: str = ""
    meta_config_id: str = ""

    # AXIOM Business
    meta_business_id: str = ""

    # System User
    meta_system_user_id: str = ""
    meta_system_user_access_token: str = ""

    # Graph API
    meta_graph_version: str = "v25.0"

    # Webhook
    meta_webhook_verify_token: str = ""
    meta_webhook_callback_url: str = ""

    # Application
    frontend_origin: str = "http://localhost:8000"

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=False,
    )


settings = Settings()