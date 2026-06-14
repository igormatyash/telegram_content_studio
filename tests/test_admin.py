from io import BytesIO
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

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


def test_invitation_reset_and_trial_workspace_flows(tmp_path) -> None:
    client = make_client(tmp_path)
    assert login(client).status_code == 200
    headers = {"X-Requested-With": "VoicerHubAdmin"}

    invitation = client.post(
        "/api/invitations",
        headers=headers,
        json={"email": "invitee@example.com", "role": "editor"},
    )
    assert invitation.status_code == 200
    token = invitation.json()["url"].split("token=", 1)[1]

    accepted = TestClient(client.app).post(
        "/api/invitations/accept",
        json={
            "token": token,
            "username": "invitee",
            "password": "invitee-password",
            "display_name": "Invited Editor",
        },
    )
    assert accepted.status_code == 200
    assert accepted.json()["user"]["email"] == "invitee@example.com"
    assert client.post(
        "/api/invitations/accept",
        json={
            "token": token,
            "username": "invitee2",
            "password": "invitee-password",
        },
    ).status_code == 400

    user_id = accepted.json()["user"]["id"]
    reset = client.post(
        "/api/password-reset/link",
        headers=headers,
        json={"user_id": user_id},
    )
    assert reset.status_code == 200
    reset_token = reset.json()["url"].split("token=", 1)[1]
    assert client.post(
        "/api/password-reset/complete",
        json={"token": reset_token, "password": "replacement-password"},
    ).status_code == 200

    trial = client.post(
        "/api/account/trial-workspace",
        headers=headers,
        json={"name": "Self Serve", "slug": "self-serve"},
    )
    assert trial.status_code == 200
    assert trial.json()["plan_code"] == "trial"


def test_google_signup_creates_trial_workspace(tmp_path, monkeypatch) -> None:
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
        google_client_id="client-id",
        google_client_secret="client-secret",
        google_redirect_uri="http://testserver/api/auth/google/callback",
        public_app_url="http://testserver",
    )
    client = TestClient(create_app(settings))

    class FakeResponse:
        def __init__(self, payload):
            self.status_code = 200
            self._payload = payload

        def json(self):
            return self._payload

    class FakeAsyncClient:
        def __init__(self, **_):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def post(self, *_args, **_kwargs):
            return FakeResponse({"access_token": "google-access-token"})

        async def get(self, *_args, **_kwargs):
            return FakeResponse(
                {
                    "sub": "google-new-user",
                    "email": "new.user@example.com",
                    "email_verified": True,
                    "name": "New User",
                    "picture": "https://example.com/avatar.png",
                }
            )

    monkeypatch.setattr(admin_module.httpx, "AsyncClient", FakeAsyncClient)
    start = client.get("/api/auth/google/start", follow_redirects=False)
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
    callback = client.get(
        f"/api/auth/google/callback?code=code&state={state}",
        follow_redirects=False,
    )

    assert callback.status_code == 303
    client.cookies.set(
        "voicerhub_session",
        callback.cookies["voicerhub_session"],
    )
    profile = client.get("/api/me")
    assert profile.status_code == 200
    assert profile.json()["role"] == "owner"
    assert profile.json()["workspaces"][0]["plan_code"] == "trial"


def test_modular_frontend_routes_manual_content_and_usage(tmp_path) -> None:
    client = make_client(tmp_path)
    assert login(client).status_code == 200
    headers = {"X-Requested-With": "VoicerHubAdmin"}
    assert client.get("/static/styles.css").status_code == 200
    assert client.get("/static/app.js").status_code == 200
    app_html = client.get("/").text
    styles = client.get("/static/styles.css").text
    assert "static/app.js" in app_html
    assert 'aria-modal="true"' in app_html
    assert 'id="systemBanner"' in app_html
    assert 'id="platformAnalytics"' in app_html
    assert 'id="notificationCount"' in app_html
    assert "prefers-reduced-motion" in styles
    app_script = client.get("/static/app.js").text
    assert "Витрати всіх компаній" in app_script
    assert "bindTelegramValidation" in app_script
    assert "rubric-builder" in app_script
    assert "Реферальна програма" in app_html
    assert "copyReferral" in app_script
    assert client.get("/register").status_code == 200
    assert "history.pushState" in app_script
    assert 'window.addEventListener("popstate"' in app_script
    assert "queryForView" in app_script
    for route in (
        "/dashboard",
        "/ideas?rubric=expert",
        "/content-plan",
        "/drafts?status=ready",
        "/calendar?view=month&date=2026-06",
        "/brand?tab=tone",
        "/expenses",
        "/settings?tab=users",
    ):
        page = client.get(route)
        assert page.status_code == 200
        assert "static/app.js" in page.text

    rubric = client.post(
        "/api/rubrics",
        headers=headers,
        json={
            "name": "Експертні матеріали",
            "slug": "expert",
            "description": "Практичні експертні матеріали для цільової аудиторії.",
            "instructions": "",
            "default_link": "",
        },
    )
    assert rubric.status_code == 200
    idea = client.post(
        "/api/ideas",
        headers=headers,
        json={
            "title": "Ручна ідея",
            "angle": "Практичний кут подачі",
            "product": "expert",
        },
    )
    assert idea.status_code == 200
    draft = client.post(
        "/api/drafts",
        headers=headers,
        json={
            "title": "Ручна чернетка",
            "visual_title": "Ручна чернетка",
            "caption_html": (
                "<b>Ручна чернетка</b>\n\n"
                "Достатньо довгий текст публікації."
            ),
            "product": "expert",
            "link_url": "",
        },
    )
    assert draft.status_code == 200
    assert client.get(
        f"/workspace/voicerhub/drafts/{draft.json()['id']}"
    ).status_code == 200
    usage = client.get("/api/usage", headers=headers)
    assert usage.status_code == 200
    assert {"totals", "models", "users", "rubrics"} <= usage.json().keys()


def test_calendar_schedules_draft_with_visual_and_rejects_missing_visual(
    tmp_path,
) -> None:
    client = make_client(tmp_path)
    assert login(client).status_code == 200
    headers = {"X-Requested-With": "VoicerHubAdmin"}
    repository = DraftRepository(tmp_path / "admin.sqlite3")
    image_path = tmp_path / "scheduled.png"
    Image.new("RGB", (20, 20), "purple").save(image_path)
    ready_for_calendar = repository.create(
        topic="Calendar",
        product="tony",
        title="Чернетка з візуалом",
        caption_html="<b>Чернетка</b>\n\nТекст для календаря.",
        image_prompt="Calendar visual.",
        image_path=str(image_path),
    )
    without_visual = repository.create(
        topic="Calendar",
        product="tony",
        title="Чернетка без візуалу",
        caption_html="<b>Чернетка</b>\n\nТекст без візуалу.",
        image_prompt="Missing visual.",
        image_path="",
    )

    scheduled = client.post(
        f"/api/drafts/{ready_for_calendar.id}/schedule",
        headers=headers,
        json={"scheduled_at": "2030-01-01T10:00:00Z"},
    )
    rejected = client.post(
        f"/api/drafts/{without_visual.id}/schedule",
        headers=headers,
        json={"scheduled_at": "2030-01-01T11:00:00Z"},
    )

    assert scheduled.status_code == 200
    assert repository.draft_record(ready_for_calendar.id)["status"] == "scheduled"
    assert rejected.status_code == 409
    assert "візуал" in rejected.json()["detail"]


def test_telegram_connection_can_be_validated_without_saving(
    tmp_path,
    monkeypatch,
) -> None:
    client = make_client(tmp_path)
    assert login(client).status_code == 200

    class FakeBot:
        def __init__(self, token):
            assert token == "123456789:valid-test-token"

        async def get_me(self):
            return SimpleNamespace(id=99, username="content_test_bot")

        async def get_chat_member(self, channel_id, bot_id):
            assert channel_id == "@content_test"
            assert bot_id == 99
            return SimpleNamespace(status="administrator")

    monkeypatch.setattr(admin_module, "Bot", FakeBot)
    response = client.post(
        "/api/company/telegram/validate",
        headers={"X-Requested-With": "VoicerHubAdmin"},
        json={
            "channel_id": "@content_test",
            "bot_token": "123456789:valid-test-token",
        },
    )

    assert response.status_code == 200
    assert response.json()["bot_username"] == "content_test_bot"
    assert response.json()["membership_status"] == "administrator"


def test_failed_generation_job_can_be_retried_from_notification(tmp_path) -> None:
    client = make_client(tmp_path)
    assert login(client).status_code == 200
    repository = DraftRepository(tmp_path / "admin.sqlite3")
    failed = repository.create_job(
        "Матеріал з помилкою",
        "tony",
        1,
        text_model="gpt-5.4-mini",
        image_model="gpt-image-2",
    )
    repository.update_job(failed.id, status="failed", error="Temporary failure")

    response = client.post(
        f"/api/jobs/{failed.id}/retry-fast",
        headers={"X-Requested-With": "VoicerHubAdmin"},
    )

    assert response.status_code == 200
    assert response.json()["job_id"] != failed.id
    assert repository.get_job(failed.id).status == "cancelled"
    assert repository.get_job(response.json()["job_id"]).status == "queued_text"
