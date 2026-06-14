from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    product_name: str = "Content Studio"
    telegram_bot_token: str
    telegram_channel: str = "@voicerhub"
    admin_user_ids: str = ""

    openai_api_key: str
    openai_text_model: str = "gpt-5.4-mini"
    openai_image_model: str = "gpt-image-2"
    use_image_batch: bool = True
    text_batch_input_price_per_1m: float = 0.75
    text_batch_output_price_per_1m: float = 4.50
    text_standard_input_price_per_1m: float = 1.50
    text_standard_output_price_per_1m: float = 9.00
    image_batch_price_per_generation: float = 0.025
    image_standard_price_per_generation: float = 0.05

    database_path: Path = Path("data/voicerhub_bot.sqlite3")
    generated_dir: Path = Path("data/generated")
    reference_dir: Path = Path("data/references")
    brand_logo_path: Path | None = None
    admin_username: str = "admin"
    admin_password: str = ""
    session_cookie_secure: bool = False
    admin_base_path: str = "/content-admin"
    app_encryption_key: str = ""
    organizations_dir: Path = Path("data/organizations")
    max_organizations: int = 3
    default_max_users: int = 50
    default_max_channels: int = 1
    default_monthly_publications: int = 90
    default_monthly_ai_budget: float = 50.0
    monthly_publications_limit: int = 0
    public_app_url: str = ""
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def admin_ids(self) -> tuple[int, ...]:
        return tuple(
            int(item.strip())
            for item in self.admin_user_ids.split(",")
            if item.strip()
        )

    def prepare_directories(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.generated_dir.mkdir(parents=True, exist_ok=True)
        self.reference_dir.mkdir(parents=True, exist_ok=True)
        self.organizations_dir.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.prepare_directories()
    return settings
