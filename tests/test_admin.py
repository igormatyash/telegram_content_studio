from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image

from voicerhub_bot.admin import create_app
from voicerhub_bot.config import Settings
from voicerhub_bot.storage import DraftRepository


def make_client(tmp_path) -> TestClient:
    settings = Settings(
        telegram_bot_token="telegram",
        openai_api_key="openai",
        admin_username="editor",
        admin_password="initial-password",
        database_path=tmp_path / "admin.sqlite3",
        generated_dir=tmp_path / "generated",
        reference_dir=tmp_path / "references",
    )
    return TestClient(create_app(settings))


def login(client: TestClient, username: str = "editor", password: str = "initial-password"):
    return client.post(
        "/api/login",
        json={"username": username, "password": password},
    )


def test_admin_uses_login_session(tmp_path) -> None:
    client = make_client(tmp_path)

    assert "Увійдіть" in client.get("/").text
    assert client.get("/api/dashboard").status_code == 401
    assert login(client).status_code == 200

    response = client.get("/api/dashboard")
    assert response.status_code == 200
    assert response.json()["totals"]["total_cost"] == 0
    assert len(response.json()["templates"]) == 12
    assert "CONTENT STUDIO" in client.get("/").text
    assert "Календар" in client.get("/").text
    assert "Voicer Wave" in client.get("/").text
    cover = client.get("/wave-cover")
    assert cover.status_code == 200
    assert cover.headers["content-type"].startswith("image/jpeg")


def test_admin_creates_and_blocks_user(tmp_path) -> None:
    client = make_client(tmp_path)
    assert login(client).status_code == 200
    headers = {"X-Requested-With": "VoicerHubAdmin"}

    created = client.post(
        "/api/users",
        headers=headers,
        json={
            "username": "content.editor",
            "password": "editor-password",
            "is_admin": False,
        },
    )
    assert created.status_code == 200
    user_id = created.json()["id"]

    second_client = TestClient(client.app)
    assert login(second_client, "content.editor", "editor-password").status_code == 200
    assert second_client.get("/api/users", headers=headers).status_code == 403

    blocked = client.patch(
        f"/api/users/{user_id}",
        headers=headers,
        json={"active": False},
    )
    assert blocked.status_code == 200
    assert second_client.get("/api/dashboard").status_code == 401


def test_admin_uploads_and_deletes_reference(tmp_path) -> None:
    client = make_client(tmp_path)
    assert login(client).status_code == 200
    headers = {"X-Requested-With": "VoicerHubAdmin"}
    buffer = BytesIO()
    Image.new("RGB", (80, 80), (0, 180, 160)).save(buffer, format="PNG")

    response = client.post(
        "/api/references",
        headers=headers,
        files={"file": ("logo.png", buffer.getvalue(), "image/png")},
    )

    assert response.status_code == 200
    reference_id = response.json()["id"]
    assert client.get(f"/api/references/{reference_id}/image").status_code == 200
    assert client.delete(
        f"/api/references/{reference_id}", headers=headers
    ).status_code == 200


def test_admin_marks_successful_post_as_example(tmp_path) -> None:
    client = make_client(tmp_path)
    assert login(client).status_code == 200
    headers = {"X-Requested-With": "VoicerHubAdmin"}
    repository = DraftRepository(tmp_path / "admin.sqlite3")
    draft = repository.create(
        topic="Тестова тема",
        product="tony",
        title="Корисний приклад допису",
        caption_html="<b>Корисний приклад</b>\n\nПрактичний текст для команди.",
        image_prompt="A practical customer experience analytics scene.",
        image_path="",
        tone="expert",
    )

    response = client.put(
        f"/api/drafts/{draft.id}/favorite",
        headers=headers,
        json={"favorite": True},
    )

    assert response.status_code == 200
    assert response.json()["is_favorite"] == 1
    assert repository.favorite_posts()[0]["id"] == draft.id


def test_material_import_rejects_local_address(tmp_path) -> None:
    client = make_client(tmp_path)
    assert login(client).status_code == 200
    response = client.post(
        "/api/materials/import",
        headers={"X-Requested-With": "VoicerHubAdmin"},
        json={
            "url": "http://127.0.0.1/private",
            "product": "tony",
            "count": 1,
            "tone": "expert",
            "text_model": "gpt-5.4-mini",
        },
    )

    assert response.status_code == 422
    assert "локальні адреси" in response.json()["detail"].lower()
