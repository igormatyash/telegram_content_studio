from voicerhub_bot.config import Settings


def test_admin_ids_parse_comma_separated_env_value(tmp_path) -> None:
    settings = Settings(
        telegram_bot_token="telegram-token",
        openai_api_key="openai-key",
        admin_user_ids="123, 456",
        database_path=tmp_path / "db.sqlite3",
        generated_dir=tmp_path / "generated",
    )

    assert settings.admin_ids == (123, 456)
