from io import BytesIO
from types import SimpleNamespace

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from PIL import Image

import voicerhub_bot.admin as admin_module
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
        organizations_dir=tmp_path / "organizations",
        app_encryption_key=Fernet.generate_key().decode(),
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


def test_retry_fast_does_not_duplicate_completed_batch(tmp_path, monkeypatch) -> None:
    client = make_client(tmp_path)
    assert login(client).status_code == 200
    headers = {"X-Requested-With": "VoicerHubAdmin"}
    repository = DraftRepository(tmp_path / "admin.sqlite3")
    job = repository.create_job("Готовий Batch", "tony", 1)
    repository.update_job(
        job.id,
        status="text_batch",
        text_batch_id="batch_completed",
    )

    class FakeBatches:
        async def retrieve(self, batch_id):
            assert batch_id == "batch_completed"
            return SimpleNamespace(status="completed")

        async def cancel(self, batch_id):
            raise AssertionError("Completed Batch must not be cancelled")

    class FakeOpenAI:
        def __init__(self, **_):
            self.batches = FakeBatches()

    monkeypatch.setattr(admin_module, "AsyncOpenAI", FakeOpenAI)
    response = client.post(
        f"/api/jobs/{job.id}/retry-fast",
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["job_id"] is None
    assert response.json()["batch_status"] == "completed"
    assert repository.get_job(job.id).status == "text_batch"


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


def test_onboarding_mode_status_api_and_editor_route(tmp_path) -> None:
    client = make_client(tmp_path)
    assert login(client).status_code == 200
    headers = {"X-Requested-With": "VoicerHubAdmin"}

    restarted = client.post("/api/onboarding/restart", headers=headers)
    assert restarted.status_code == 200
    assert restarted.json()["onboarding_status"] == "not_started"
    company = client.put(
        "/api/onboarding/company",
        headers=headers,
        json={
            "name": "Editorial Team",
            "slug": "editorial-team",
            "primary_language": "uk",
            "brand_primary_color": "#10bfae",
        },
    )
    assert company.status_code == 200
    assert company.json()["settings"]["onboarding_step"] == 2
    mode = client.put(
        "/api/workspace/mode",
        headers=headers,
        json={"workspace_mode": "kanban"},
    )
    assert mode.status_code == 200
    assert mode.json()["workspace_mode"] == "kanban"

    repository = DraftRepository(tmp_path / "admin.sqlite3")
    draft = repository.create(
        topic="Статуси",
        product="tony",
        title="Матеріал для рев’ю",
        caption_html="<b>Матеріал</b>\n\nТекст для редакційної перевірки.",
        image_prompt="A detailed editorial review scene.",
        image_path="/tmp/review.png",
    )
    changed = client.post(
        f"/api/drafts/{draft.id}/status",
        headers=headers,
        json={"status": "review"},
    )
    assert changed.status_code == 200
    assert changed.json()["status"] == "review"
    invalid = client.post(
        f"/api/drafts/{draft.id}/status",
        headers=headers,
        json={"status": "published"},
    )
    assert invalid.status_code == 409

    route = client.get(f"/workspace/editorial-team/drafts/{draft.id}")
    assert route.status_code == 200
    assert "data-kanban-label=\"Дошка\"" in route.text
    assert "Налаштування workspace" in route.text
