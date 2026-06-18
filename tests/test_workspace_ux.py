from concurrent.futures import ThreadPoolExecutor

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from voicerhub_bot.admin import create_app
from voicerhub_bot.config import Settings
from voicerhub_bot.formatting import sanitize_preview_html, strip_formatting
from voicerhub_bot.permissions import has_permission, permissions_for, role_catalog
from voicerhub_bot.saas import SaasRepository
from voicerhub_bot.slugs import generate_slug
from voicerhub_bot.storage import DraftRepository


HEADERS = {"X-Requested-With": "VoicerHubAdmin"}


def make_app(tmp_path):
    settings = Settings(
        telegram_bot_token="telegram",
        openai_api_key="openai",
        admin_username="workspace.owner",
        admin_password="initial-password",
        database_path=tmp_path / "workspace.sqlite3",
        generated_dir=tmp_path / "generated",
        reference_dir=tmp_path / "references",
        organizations_dir=tmp_path / "organizations",
        app_encryption_key=Fernet.generate_key().decode(),
        public_app_url="http://testserver",
    )
    return create_app(settings)


def login(client: TestClient, username="workspace.owner", password="initial-password"):
    return client.post("/api/login", json={"username": username, "password": password})


def test_slug_generation_and_uniqueness(tmp_path) -> None:
    assert generate_slug("ТОВ Нова Клініка") == "tov-nova-klinika"
    assert generate_slug("Panacea HR") == "panacea-hr"

    repository = SaasRepository(
        tmp_path / "saas.sqlite3",
        Fernet.generate_key().decode(),
    )
    first = repository.create_trial_organization(name="Нова Клініка", slug="")
    second = repository.create_trial_organization(name="Нова Клініка", slug="")
    assert first["slug"] == "nova-klinika"
    assert second["slug"] == "nova-klinika-2"


def test_tenant_migrations_are_safe_when_processes_start_together(tmp_path) -> None:
    database = tmp_path / "concurrent.sqlite3"

    with ThreadPoolExecutor(max_workers=4) as pool:
        repositories = list(
            pool.map(lambda _: DraftRepository(database), range(8))
        )

    assert len(repositories) == 8
    assert repositories[0].list_drafts() == []


def test_formatting_helpers_preserve_safe_markup_and_remove_xss() -> None:
    source = (
        '<b>Що бізнес отримує</b> 📊'
        '<script>alert(1)</script>'
        '<a href="javascript:alert(2)">небезпечне</a>'
        '<a href="https://example.com">безпечне</a>'
    )
    rendered = sanitize_preview_html(source)

    assert strip_formatting("<b>Що бізнес отримує</b> 📊") == (
        "Що бізнес отримує 📊"
    )
    assert "<b>Що бізнес отримує</b>" in rendered
    assert "alert(1)" not in rendered
    assert "javascript:" not in rendered
    assert 'href="https://example.com"' in rendered


def test_paginated_lists_and_bulk_actions_are_tenant_scoped(tmp_path) -> None:
    app = make_app(tmp_path)
    owner = TestClient(app)
    assert login(owner).status_code == 200

    for index in range(28):
        response = owner.post(
            "/api/ideas",
            headers=HEADERS,
            json={
                "title": f"Ідея {index:02d}",
                "product": "tony",
                "angle": "Практичний кут подачі для перевірки пагінації.",
                "planned_for": None,
            },
        )
        assert response.status_code == 200

    page = owner.get("/api/ideas?page=2&per_page=10", headers=HEADERS)
    assert page.status_code == 200
    assert page.json()["page"] == 2
    assert page.json()["per_page"] == 10
    assert page.json()["total"] == 28
    assert page.json()["total_pages"] == 3
    assert len(page.json()["items"]) == 10

    capped = owner.get("/api/ideas?page=1&per_page=500", headers=HEADERS)
    assert capped.status_code == 200
    assert capped.json()["per_page"] == 100

    viewer = owner.post(
        "/api/users",
        headers=HEADERS,
        json={
            "username": "workspace.viewer",
            "password": "viewer-password",
            "role": "viewer",
        },
    )
    assert viewer.status_code == 200
    viewer_client = TestClient(app)
    assert login(viewer_client, "workspace.viewer", "viewer-password").status_code == 200
    ids = [item["id"] for item in page.json()["items"][:2]]
    denied = viewer_client.post(
        "/api/ideas/bulk",
        headers=HEADERS,
        json={"ids": ids, "action": "delete", "value": ""},
    )
    assert denied.status_code == 403

    deleted = owner.post(
        "/api/ideas/bulk",
        headers=HEADERS,
        json={"ids": ids, "action": "delete", "value": ""},
    )
    assert deleted.status_code == 200
    assert deleted.json()["changed"] == 2
    assert owner.get("/api/ideas?page=1&per_page=25", headers=HEADERS).json()[
        "total"
    ] == 26


def test_workspace_roles_have_expected_permissions() -> None:
    assert permissions_for("owner") >= {
        "content.publish",
        "roles.manage",
        "billing.manage",
    }
    assert has_permission("publisher", "content.publish")
    assert has_permission("publisher", "content.schedule")
    assert not has_permission("publisher", "users.invite")
    assert has_permission("editor", "content.edit")
    assert not has_permission("editor", "content.publish")
    assert not has_permission("viewer", "content.edit")
    assert has_permission("viewer", "content.view")
    assert has_permission("viewer", "platform.view", platform_admin=True)
    owner = role_catalog()[0]
    publish = next(
        item for item in owner["permission_details"]
        if item["key"] == "content.publish"
    )
    assert publish["label"] == "Публікація контенту"
    assert "підключених каналах" in publish["description"]


def test_content_plan_exposes_clear_error_and_cancelled_labels(tmp_path) -> None:
    app = make_app(tmp_path)
    client = TestClient(app)
    assert login(client).status_code == 200
    repository = DraftRepository(tmp_path / "workspace.sqlite3")
    ideas = repository.add_ideas(
        [
            {
                "product": "tony",
                "title": "<b>Плановий матеріал</b>",
                "angle": "Пояснити практичну користь для клієнта.",
                "planned_for": "2026-06-20",
                "plan_id": "plan-test",
            },
            {
                "product": "tony",
                "title": "Скасований матеріал",
                "angle": "Другий елемент плану.",
                "planned_for": "2026-06-21",
                "plan_id": "plan-test",
            },
        ]
    )
    failed = repository.create_job(
        "Плановий матеріал. Пояснити практичну користь для клієнта.",
        "tony",
        0,
        idea_id=ideas[0]["id"],
    )
    repository.update_job(failed.id, status="failed", error="Temporary provider error")
    cancelled = repository.create_job(
        "Скасований матеріал. Другий елемент плану.",
        "tony",
        0,
        idea_id=ideas[1]["id"],
    )
    repository.update_job(cancelled.id, status="cancelled")

    response = client.get("/api/content-plan/items?page=1&per_page=25")
    assert response.status_code == 200
    rows = {item["id"]: item for item in response.json()["items"]}
    assert rows[ideas[0]["id"]]["status"] == "failed"
    assert rows[ideas[0]["id"]]["error_message"] == "Temporary provider error"
    assert rows[ideas[0]["id"]]["title_plain"] == "Плановий матеріал"
    assert rows[ideas[1]["id"]]["status"] == "cancelled"
    assert rows[ideas[1]["id"]]["error_message"] == "Генерацію було скасовано."


def test_ui_contains_pagination_roles_and_appearance(tmp_path) -> None:
    client = TestClient(make_app(tmp_path))
    assert login(client).status_code == 200
    page = client.get("/brand?tab=appearance")

    assert page.status_code == 200
    assert 'data-brand-tab="appearance"' in page.text
    assert 'data-settings="roles"' in page.text
    assert "static/app.js?v=17" in page.text
    assert 'class="ideas-content" id="ideasGrid"' in page.text
    assert 'class="sidebar-scroll"' in page.text
    assert "interactive-widget=resizes-content" in page.text
    assert "static/styles.css?v=15" in page.text
    script = client.get("/static/app.js?v=9")
    assert script.status_code == 200
    assert "function pagination(" in script.text
    assert "function safeHtml(" in script.text
    assert "function decodeHtmlMarkup(" in script.text
    assert "function syncVisualViewport(" in script.text
    assert "Прочитати все" in script.text
    assert "Перевірити текст" not in script.text
    assert "permission-chip" in script.text
    assert "Обрано:" in script.text
    assert "data-buy-plan" in script.text
    styles = client.get("/static/styles.css")
    assert styles.status_code == 200
    assert ".sidebar-scroll" in styles.text
    assert "height: var(--visual-viewport-height)" in styles.text
    assert ".idea-grid { min-width: 0;" in styles.text


def test_ui_contains_generation_progress_and_local_calendar_helpers(tmp_path) -> None:
    client = TestClient(make_app(tmp_path))
    assert login(client).status_code == 200
    page = client.get("/ideas")
    script = client.get("/static/app.js")

    assert page.status_code == 200
    assert 'id="aiProgressOverlay"' in page.text
    assert "Ваші ідеї генеруються" in page.text
    assert script.status_code == 200
    assert "activeGenerationStatuses" in script.text
    assert "updateGenerationPolling" in script.text
    assert "Текст уже готовий, створюємо зображення" in script.text
    assert "localDateKey(x.scheduled_at)" in script.text
    assert "localDateTimeValue(draft.scheduled_at)" in script.text


def test_roles_api_exposes_translated_permission_help(tmp_path) -> None:
    client = TestClient(make_app(tmp_path))
    assert login(client).status_code == 200

    response = client.get("/api/roles")

    assert response.status_code == 200
    owner = response.json()["items"][0]
    permission = next(
        item for item in owner["permission_details"]
        if item["key"] == "workspace.settings"
    )
    assert permission["label"] == "Налаштування workspace"
    assert "загальні параметри" in permission["description"]
