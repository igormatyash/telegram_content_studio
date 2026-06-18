import sqlite3
import time

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from PIL import Image

from voicerhub_bot.admin import create_app
from voicerhub_bot.config import Settings
from voicerhub_bot.instagram import signed_media_token
from voicerhub_bot.saas import SaasRepository
from voicerhub_bot.storage import DraftRepository


def make_client(tmp_path) -> tuple[TestClient, Settings]:
    settings = Settings(
        telegram_bot_token="telegram",
        openai_api_key="openai",
        admin_username="editor",
        admin_password="initial-password",
        database_path=tmp_path / "admin.sqlite3",
        generated_dir=tmp_path / "generated",
        reference_dir=tmp_path / "references",
        organizations_dir=tmp_path / "organizations",
        app_encryption_key=Fernet.generate_key().decode(),
        public_app_url="https://content.example.test",
    )
    return TestClient(create_app(settings)), settings


def login(client: TestClient) -> None:
    response = client.post(
        "/api/login",
        json={"username": "editor", "password": "initial-password"},
    )
    assert response.status_code == 200


def test_instagram_status_is_setup_required_without_meta_env_and_telegram_still_works(tmp_path) -> None:
    client, _ = make_client(tmp_path)
    login(client)

    status = client.get("/api/integrations/instagram/status")
    assert status.status_code == 200
    assert status.json()["setup_required"] is True
    assert "META_APP_ID" in status.json()["missing"]
    assert status.json()["supports"]["feed_image"] is False

    company = client.get("/api/company")
    assert company.status_code == 200
    publish = client.post(
        "/api/drafts/999/instagram/publish",
        headers={"X-Requested-With": "VoicerHubAdmin"},
    )
    assert publish.status_code == 409
    assert "Instagram ще не налаштовано" in publish.json()["detail"]


def test_instagram_media_requires_valid_temporary_signature(tmp_path) -> None:
    client, settings = make_client(tmp_path)
    login(client)
    image_path = tmp_path / "generated" / "post.png"
    Image.new("RGB", (120, 120), (80, 50, 220)).save(image_path)
    draft = DraftRepository(tmp_path / "admin.sqlite3").create(
        topic="Instagram",
        product="tony",
        title="Пост для Instagram",
        caption_html="<b>Caption</b>",
        image_prompt="image",
        image_path=str(image_path),
        tone="expert",
    )
    expires_at, signature = signed_media_token(
        settings,
        organization_id=1,
        draft_id=draft.id,
        expires_in=30,
    )

    ok = client.get(
        f"/media/instagram/{draft.id}?org=1&variant=&exp={expires_at}&sig={signature}"
    )
    assert ok.status_code == 200
    assert ok.headers["content-type"].startswith("image/png")

    bad = client.get(
        f"/media/instagram/{draft.id}?org=1&variant=&exp={expires_at}&sig=bad"
    )
    assert bad.status_code == 403

    expired = int(time.time()) - 1
    expired_response = client.get(
        f"/media/instagram/{draft.id}?org=1&variant=&exp={expired}&sig={signature}"
    )
    assert expired_response.status_code == 403


def test_social_connection_token_is_encrypted_at_rest(tmp_path) -> None:
    key = Fernet.generate_key().decode()
    repo = SaasRepository(tmp_path / "saas.sqlite3", key, "salt")
    repo.ensure_legacy_organization("@channel")

    saved = repo.save_social_connection(
        1,
        platform="instagram",
        external_account_id="17841400000000000",
        access_token="meta-token",
        username="voicerhub",
        permissions=["instagram_content_publish"],
        metadata={"source": "test"},
    )
    loaded = repo.social_connection(saved["id"], include_token=True)

    assert loaded["access_token"] == "meta-token"
    assert loaded["permissions"] == ["instagram_content_publish"]
    assert loaded["metadata"]["source"] == "test"
    with sqlite3.connect(tmp_path / "saas.sqlite3") as connection:
        stored = connection.execute(
            "SELECT access_token_encrypted FROM social_connections WHERE id = ?",
            (saved["id"],),
        ).fetchone()[0]
    assert stored != "meta-token"
    assert "meta-token" not in stored
