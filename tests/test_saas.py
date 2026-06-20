import sqlite3
from datetime import datetime, timezone

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

import voicerhub_bot.admin as admin_module
from voicerhub_bot.admin import create_app
from voicerhub_bot.billing import STAR_PLANS
from voicerhub_bot.auth import AuthRepository
from voicerhub_bot.config import Settings
from voicerhub_bot.saas import SaasRepository
from voicerhub_bot.saas_worker import _telegram_settings
from voicerhub_bot.storage import DraftRepository, TenantRepository


def test_legacy_company_migration_preserves_users(tmp_path) -> None:
    database = tmp_path / "studio.sqlite3"
    auth = AuthRepository(database)
    owner = auth.create_user("owner", "owner-password", is_admin=True)
    editor = auth.create_user("editor", "editor-password", is_admin=False)
    saas = SaasRepository(database, Fernet.generate_key().decode())

    organization = saas.ensure_legacy_organization()

    assert organization["id"] == 1
    assert saas.membership_for_user(owner["id"])["role"] == "owner"
    assert saas.membership_for_user(editor["id"])["role"] == "editor"
    assert auth.authenticate("owner", "owner-password")["organization_id"] == 1


def test_company_workspace_migration_is_idempotent(tmp_path) -> None:
    database = tmp_path / "company-workspace.sqlite3"
    auth = AuthRepository(database)
    owner = auth.create_user("owner", "owner-password", is_admin=True)
    first = SaasRepository(database, Fernet.generate_key().decode())
    first.ensure_legacy_organization()

    second = SaasRepository(database, Fernet.generate_key().decode())
    company = second.company_for_organization(1)
    companies = second.list_companies()
    members = second.company_users(company["id"])

    assert len(companies) == 1
    assert companies[0]["workspace_count"] == 1
    assert members[0]["id"] == owner["id"]
    assert members[0]["company_role"] == "owner"
    assert members[0]["workspace_roles"][0]["workspace_id"] == 1


def test_registration_ignores_legacy_global_workspace_limit(tmp_path) -> None:
    settings = Settings(
        telegram_bot_token="telegram",
        openai_api_key="openai",
        admin_username="platform.owner",
        admin_password="initial-password",
        database_path=tmp_path / "registration.sqlite3",
        generated_dir=tmp_path / "generated",
        reference_dir=tmp_path / "references",
        organizations_dir=tmp_path / "organizations",
        app_encryption_key=Fernet.generate_key().decode(),
        max_organizations=1,
    )
    client = TestClient(create_app(settings))

    response = client.post(
        "/api/register",
        json={
            "username": "new.owner",
            "password": "new-owner-password",
            "email": "new-owner@example.com",
            "display_name": "Новий Власник",
            "workspace_name": "Нова Компанія",
            "workspace_slug": "nova-kompaniia",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["company"]["name"] == "Нова Компанія"
    assert payload["workspace"]["company_id"] == payload["company"]["id"]


def test_organization_onboarding_settings_survive_reinitialization(tmp_path) -> None:
    database = tmp_path / "settings.sqlite3"
    key = Fernet.generate_key().decode()
    saas = SaasRepository(database, key)
    organization = saas.create_organization(
        name="New Workspace",
        slug="new-workspace",
        max_users=10,
        max_channels=1,
        monthly_publications=30,
        monthly_ai_budget=20,
    )
    defaults = saas.organization_settings(organization["id"])
    assert defaults["onboarding_status"] == "not_started"
    assert defaults["workspace_mode"] == "pipeline"

    saas.update_organization_settings(
        organization["id"],
        onboarding_status="in_progress",
        onboarding_step=3,
        workspace_mode="kanban",
        tone_of_voice="Лаконічно та професійно",
    )
    saas = SaasRepository(database, key)
    restored = saas.organization_settings(organization["id"])
    assert restored["onboarding_step"] == 3
    assert restored["workspace_mode"] == "kanban"
    assert restored["tone_of_voice"] == "Лаконічно та професійно"


def test_service_updates_are_idempotent_and_filter_public_feed(tmp_path) -> None:
    database = tmp_path / "updates.sqlite3"
    key = Fernet.generate_key().decode()
    saas = SaasRepository(database, key)

    published = saas.create_service_update(
        title="Нова лента оновлень",
        body="Тут будуть нові функції та важливі повідомлення.",
        title_uk="Нова лента оновлень",
        body_uk="Тут будуть нові функції та важливі повідомлення.",
        category="release",
        importance="success",
        status="published",
        pinned=True,
        created_by_user_id=None,
    )
    draft = saas.create_service_update(
        title="Чернетка",
        body="Користувачі цього не бачать.",
        title_uk="Чернетка",
        body_uk="Користувачі цього не бачать.",
        status="draft",
    )

    public_feed = saas.list_service_updates()
    assert [item["id"] for item in public_feed] == [published["id"]]
    assert public_feed[0]["pinned"] == 1

    admin_feed = saas.list_service_updates(include_drafts=True)
    assert {item["id"] for item in admin_feed} == {published["id"], draft["id"]}

    updated = saas.update_service_update(
        draft["id"],
        title="Опублікована чернетка",
        body="Тепер видно всім.",
        title_uk="Опублікована чернетка",
        body_uk="Тепер видно всім.",
        category="announcement",
        importance="info",
        status="published",
        pinned=False,
    )
    assert updated["published_at"]
    assert len(saas.list_service_updates()) == 2

    reinitialized = SaasRepository(database, key)
    assert {item["title"] for item in reinitialized.list_service_updates()} == {
        "Нова лента оновлень",
        "Опублікована чернетка",
    }


def test_service_updates_are_filtered_by_locale(tmp_path) -> None:
    database = tmp_path / "localized-updates.sqlite3"
    key = Fernet.generate_key().decode()
    saas = SaasRepository(database, key)

    saas.create_service_update(
        title="Нове українське оновлення",
        body="Тільки українська лента.",
        title_uk="Нове українське оновлення",
        body_uk="Тільки українська лента.",
        status="published",
    )
    saas.create_service_update(
        title="English update",
        body="English feed only.",
        title_en="English update",
        body_en="English feed only.",
        status="published",
    )

    assert [item["title"] for item in saas.list_service_updates(locale="uk")] == [
        "Нове українське оновлення"
    ]
    assert [item["title"] for item in saas.list_service_updates(locale="en")] == [
        "English update"
    ]


def test_trial_workspace_has_start_limits_and_expiration(tmp_path) -> None:
    database = tmp_path / "trial.sqlite3"
    saas = SaasRepository(database, Fernet.generate_key().decode())

    organization = saas.create_trial_organization(
        name="Trial Team",
        slug="trial-team",
    )

    assert organization["plan_code"] == "trial"
    assert organization["max_users"] == 3
    assert organization["max_channels"] == 1
    assert organization["monthly_publications"] == 30
    assert organization["monthly_ai_budget"] == 8
    assert organization["monthly_text_generations"] == 60
    assert organization["monthly_image_generations"] == 30
    assert organization["subscription_status"] == "trial"
    assert organization["trial_ends_at"]
    assert datetime.fromisoformat(organization["plan_expires_at"]) > datetime.now(
        timezone.utc
    )


def test_workspace_delete_rejects_last_workspace(tmp_path) -> None:
    database = tmp_path / "delete-last.sqlite3"
    auth = AuthRepository(database)
    auth.create_user("owner", "owner-password", is_admin=True)
    saas = SaasRepository(database, Fernet.generate_key().decode())
    organization = saas.ensure_legacy_organization()

    try:
        saas.delete_organization(organization["id"])
    except ValueError as exc:
        assert "Системний workspace" in str(exc)
    else:
        raise AssertionError("System workspace deletion must be rejected")


def test_tenant_repositories_are_isolated(tmp_path) -> None:
    router = TenantRepository(
        tmp_path / "legacy.sqlite3",
        tmp_path / "organizations",
    )
    first = router.for_organization(1)
    second = router.for_organization(2)

    first.create(
        topic="VoicerHub topic",
        product="tony",
        title="VoicerHub title",
        caption_html="<b>VoicerHub</b>",
        image_prompt="A sufficiently descriptive image generation prompt.",
        image_path="",
    )
    second.create(
        topic="Client topic",
        product="general",
        title="Client title",
        caption_html="<b>Client</b>",
        image_prompt="A sufficiently descriptive image generation prompt.",
        image_path="",
    )

    assert [item["title"] for item in first.list_drafts()] == ["VoicerHub title"]
    assert [item["title"] for item in second.list_drafts()] == ["Client title"]

    first.ensure_legacy_rubrics()
    second.add_rubric(
        slug="company-news",
        name="Новини компанії",
        description="Перевірені новини, оновлення продукту та події цієї компанії.",
    )

    assert {item["slug"] for item in first.list_rubrics()} == {
        "tony",
        "voicer",
        "wave",
    }
    assert [item["slug"] for item in second.list_rubrics()] == ["company-news"]


def test_tenant_migration_is_idempotent_and_filters_foreign_rows(tmp_path) -> None:
    database = tmp_path / "tenant.sqlite3"
    repository = DraftRepository(database, organization_id=7)
    draft = repository.create(
        topic="Tenant topic",
        product="general",
        title="Tenant title",
        caption_html="<b>Tenant title</b>",
        image_prompt="A sufficiently descriptive image prompt for tenant testing.",
        image_path="",
    )
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT organization_id FROM drafts WHERE id = ?",
            (draft.id,),
        ).fetchone()[0] == 7
        connection.execute(
            """
            INSERT INTO drafts (
                topic, product, title, caption_html, image_prompt,
                image_path, organization_id
            ) VALUES ('foreign', 'general', 'Foreign title', '<b>Foreign</b>',
                'A sufficiently descriptive foreign image prompt.', '', 8)
            """
        )

    repository = DraftRepository(database, organization_id=7)

    assert [item["title"] for item in repository.list_drafts()] == ["Tenant title"]
    assert repository.get(draft.id).title == "Tenant title"


def test_telegram_token_is_encrypted_at_rest(tmp_path) -> None:
    database = tmp_path / "studio.sqlite3"
    auth = AuthRepository(database)
    auth.create_user("owner", "owner-password", is_admin=True)
    key = Fernet.generate_key().decode()
    saas = SaasRepository(database, key)
    saas.ensure_legacy_organization()
    token = "123456789:AAExampleTelegramBotTokenForTests"

    saved = saas.save_telegram_connection(
        1,
        channel_id="@example",
        bot_token=token,
        bot_username="example_bot",
    )

    with sqlite3.connect(database) as connection:
        stored = connection.execute(
            "SELECT bot_token_encrypted FROM telegram_connections WHERE organization_id = 1"
        ).fetchone()[0]
    assert saved["configured"] is True
    assert token not in stored
    assert saas.telegram_connection(1, include_token=True)["bot_token"] == token


def test_new_organization_never_inherits_legacy_telegram_channel(tmp_path) -> None:
    settings = Settings(
        telegram_bot_token="legacy-token",
        telegram_channel="@legacy-channel",
        openai_api_key="openai",
        database_path=tmp_path / "content.sqlite3",
        generated_dir=tmp_path / "generated",
        reference_dir=tmp_path / "references",
        organizations_dir=tmp_path / "organizations",
        app_encryption_key=Fernet.generate_key().decode(),
    )
    AuthRepository(settings.database_path)
    saas = SaasRepository(settings.database_path, settings.app_encryption_key)
    saas.ensure_legacy_organization(channel_id=settings.telegram_channel)
    organization = saas.create_organization(
        name="Second company",
        slug="second-company",
        max_users=50,
        max_channels=1,
        monthly_publications=90,
        monthly_ai_budget=50,
    )

    token, channel = _telegram_settings(settings, saas, organization["id"])

    assert token == settings.telegram_bot_token
    assert channel == ""


def test_super_admin_creates_company_with_owner(tmp_path) -> None:
    settings = Settings(
        telegram_bot_token="telegram",
        openai_api_key="openai",
        admin_username="platform.owner",
        admin_password="initial-password",
        database_path=tmp_path / "admin.sqlite3",
        generated_dir=tmp_path / "generated",
        reference_dir=tmp_path / "references",
        organizations_dir=tmp_path / "organizations",
        app_encryption_key=Fernet.generate_key().decode(),
    )
    client = TestClient(create_app(settings))
    assert client.post(
        "/api/login",
        json={"username": "platform.owner", "password": "initial-password"},
    ).status_code == 200

    response = client.post(
        "/api/organizations",
        headers={"X-Requested-With": "VoicerHubAdmin"},
        json={
            "name": "Second Company",
            "slug": "second-company",
            "owner_username": "second.owner",
            "owner_password": "second-password",
            "owner_email": "owner@second.example",
            "owner_display_name": "Second Owner",
            "max_users": 50,
            "max_channels": 1,
            "monthly_publications": 90,
            "monthly_ai_budget": 50,
        },
    )

    assert response.status_code == 200
    assert response.json()["id"] == 2
    assert response.json()["owner"]["organization_id"] == 2
    assert response.json()["owner"]["email"] == "owner@second.example"
    assert response.json()["owner"]["display_name"] == "Second Owner"
    assert (tmp_path / "organizations" / "2" / "content.sqlite3").is_file()


def test_workspace_selection_is_scoped_to_memberships(tmp_path) -> None:
    settings = Settings(
        telegram_bot_token="telegram",
        openai_api_key="openai",
        admin_username="platform.owner",
        admin_password="initial-password",
        database_path=tmp_path / "admin.sqlite3",
        generated_dir=tmp_path / "generated",
        reference_dir=tmp_path / "references",
        organizations_dir=tmp_path / "organizations",
        app_encryption_key=Fernet.generate_key().decode(),
    )
    app = create_app(settings)
    platform = TestClient(app)
    platform.post(
        "/api/login",
        json={"username": "platform.owner", "password": "initial-password"},
    )
    created = platform.post(
        "/api/organizations",
        headers={"X-Requested-With": "VoicerHubAdmin"},
        json={
            "name": "Second Company",
            "slug": "second-company",
            "owner_username": "second.owner",
            "owner_password": "second-password",
        },
    ).json()
    headers = {"X-Requested-With": "VoicerHubAdmin"}

    switched = platform.post(
        "/api/workspace/select",
        headers=headers,
        json={"organization_id": created["id"]},
    )
    assert switched.status_code == 200
    assert platform.get("/api/me").json()["organization_id"] == created["id"]

    owner = TestClient(app)
    owner.post(
        "/api/login",
        json={"username": "second.owner", "password": "second-password"},
    )
    denied = owner.post(
        "/api/workspace/select",
        headers=headers,
        json={"organization_id": 1},
    )
    assert denied.status_code == 404


def test_company_admin_cannot_manage_user_from_another_company(tmp_path) -> None:
    settings = Settings(
        telegram_bot_token="telegram",
        openai_api_key="openai",
        admin_username="platform.owner",
        admin_password="initial-password",
        database_path=tmp_path / "admin.sqlite3",
        generated_dir=tmp_path / "generated",
        reference_dir=tmp_path / "references",
        organizations_dir=tmp_path / "organizations",
        app_encryption_key=Fernet.generate_key().decode(),
    )
    app = create_app(settings)
    platform = TestClient(app)
    platform.post(
        "/api/login",
        json={"username": "platform.owner", "password": "initial-password"},
    )
    created = platform.post(
        "/api/organizations",
        headers={"X-Requested-With": "VoicerHubAdmin"},
        json={
            "name": "Second Company",
            "slug": "second-company",
            "owner_username": "second.owner",
            "owner_password": "second-password",
        },
    )
    second_owner_id = created.json()["owner"]["id"]

    second = TestClient(app)
    second.post(
        "/api/login",
        json={"username": "second.owner", "password": "second-password"},
    )
    response = second.patch(
        "/api/users/1",
        headers={"X-Requested-With": "VoicerHubAdmin"},
        json={"active": False},
    )

    assert second_owner_id != 1
    assert response.status_code == 404


def test_viewer_is_read_only_and_foreign_draft_is_hidden(tmp_path) -> None:
    settings = Settings(
        telegram_bot_token="telegram",
        openai_api_key="openai",
        admin_username="platform.owner",
        admin_password="initial-password",
        database_path=tmp_path / "admin.sqlite3",
        generated_dir=tmp_path / "generated",
        reference_dir=tmp_path / "references",
        organizations_dir=tmp_path / "organizations",
        app_encryption_key=Fernet.generate_key().decode(),
    )
    app = create_app(settings)
    platform = TestClient(app)
    platform.post(
        "/api/login",
        json={"username": "platform.owner", "password": "initial-password"},
    )
    created = platform.post(
        "/api/organizations",
        headers={"X-Requested-With": "VoicerHubAdmin"},
        json={
            "name": "Viewer Company",
            "slug": "viewer-company",
            "owner_username": "viewer.owner",
            "owner_password": "owner-password",
        },
    ).json()
    auth = AuthRepository(settings.database_path)
    viewer = auth.create_user(
        "readonly.viewer",
        "viewer-password",
        is_admin=False,
        organization_id=created["id"],
        role="viewer",
    )
    legacy_draft = DraftRepository(
        settings.database_path,
        organization_id=1,
    ).create(
        topic="Legacy",
        product="general",
        title="Legacy organization draft",
        caption_html="<b>Legacy organization draft</b>",
        image_prompt="A sufficiently descriptive image prompt for a legacy draft.",
        image_path="",
    )
    client = TestClient(app)
    client.post(
        "/api/login",
        json={"username": viewer["username"], "password": "viewer-password"},
    )
    headers = {"X-Requested-With": "VoicerHubAdmin"}

    assert client.get("/api/dashboard").status_code == 200
    assert client.get(f"/api/drafts/{legacy_draft.id}").status_code == 404
    assert client.post(
        "/api/ideas/generate",
        headers=headers,
        json={"product": "all", "count": 1},
    ).status_code == 403


def test_text_quota_blocks_new_generation_before_openai_call(tmp_path) -> None:
    settings = Settings(
        telegram_bot_token="telegram",
        openai_api_key="openai",
        admin_username="platform.owner",
        admin_password="initial-password",
        database_path=tmp_path / "admin.sqlite3",
        generated_dir=tmp_path / "generated",
        reference_dir=tmp_path / "references",
        organizations_dir=tmp_path / "organizations",
        app_encryption_key=Fernet.generate_key().decode(),
    )
    client = TestClient(create_app(settings))
    client.post(
        "/api/login",
        json={"username": "platform.owner", "password": "initial-password"},
    )
    with sqlite3.connect(settings.database_path) as connection:
        connection.execute(
            "UPDATE organizations SET monthly_text_generations = 1, subscription_status = 'custom' WHERE id = 1"
        )
    repository = TenantRepository(settings.database_path, settings.organizations_dir)
    repository.for_organization(1).add_usage(
        job_id=0,
        kind="text",
        model="test",
        cost=50,
    )

    response = client.post(
        "/api/ideas/generate",
        headers={"X-Requested-With": "VoicerHubAdmin"},
        json={
            "product": "general",
            "count": 1,
            "text_model": "gpt-5.4-mini",
            "tone": "expert",
        },
    )

    assert response.status_code == 402
    assert response.json()["detail"]["reason"] == "text_quota_exceeded"


def test_super_admin_sees_usage_by_company_and_user(tmp_path) -> None:
    settings = Settings(
        telegram_bot_token="telegram",
        openai_api_key="openai",
        admin_username="platform.owner",
        admin_password="initial-password",
        database_path=tmp_path / "admin.sqlite3",
        generated_dir=tmp_path / "generated",
        reference_dir=tmp_path / "references",
        organizations_dir=tmp_path / "organizations",
        app_encryption_key=Fernet.generate_key().decode(),
    )
    client = TestClient(create_app(settings))
    login = client.post(
        "/api/login",
        json={"username": "platform.owner", "password": "initial-password"},
    )
    user_id = login.json()["user"]["id"]
    repository = TenantRepository(settings.database_path, settings.organizations_dir)
    repository.for_organization(1).add_usage(
        job_id=0,
        kind="text",
        model="gpt-5.4-mini",
        input_tokens=1000,
        output_tokens=250,
        cost=0.02,
        user_id=user_id,
    )
    repository.for_organization(1).add_usage(
        job_id=0,
        kind="image",
        model="gpt-image-2",
        units=2,
        cost=0.08,
        user_id=user_id,
    )

    response = client.get(
        "/api/platform/usage?period=all",
        headers={"X-Requested-With": "VoicerHubAdmin"},
    )

    assert response.status_code == 200
    report = response.json()
    assert report["totals"]["input_tokens"] == 1000
    assert report["totals"]["output_tokens"] == 250
    assert report["totals"]["image_generations"] == 2
    assert report["totals"]["cost"] == 0.1
    assert report["companies"][0]["organization_name"] == "VoicerHub"
    assert report["users"][0]["username"] == "platform.owner"


def test_admin_lists_plans_and_creates_star_checkout(tmp_path, monkeypatch) -> None:
    settings = Settings(
        telegram_bot_token="telegram",
        openai_api_key="openai",
        admin_username="owner",
        admin_password="owner-password",
        database_path=tmp_path / "billing.sqlite3",
        generated_dir=tmp_path / "generated",
        reference_dir=tmp_path / "references",
        organizations_dir=tmp_path / "organizations",
        app_encryption_key=Fernet.generate_key().decode(),
    )

    async def fake_checkout(self, *, organization_id, user_id, plan_code):
        assert organization_id == 1
        assert user_id > 0
        assert plan_code == "growth"
        return {
            "id": 1,
            "invoice_url": "https://t.me/$invoice",
            "plan": STAR_PLANS["growth"],
        }

    monkeypatch.setattr(
        admin_module.BillingService,
        "create_checkout",
        fake_checkout,
    )
    client = TestClient(create_app(settings))
    assert client.post(
        "/api/login",
        json={"username": "owner", "password": "owner-password"},
    ).status_code == 200
    headers = {"X-Requested-With": "VoicerHubAdmin"}

    plans = client.get("/api/plans", headers=headers)
    assert plans.status_code == 200
    assert [item["code"] for item in plans.json()["plans"]] == [
        "start",
        "growth",
        "scale",
    ]

    checkout = client.post(
        "/api/billing/checkout",
        headers=headers,
        json={"plan_code": "growth"},
    )
    assert checkout.status_code == 200
    assert checkout.json()["invoice_url"] == "https://t.me/$invoice"


def test_star_payment_applies_plan_limits_once(tmp_path) -> None:
    database = tmp_path / "stars.sqlite3"
    auth = AuthRepository(database)
    user = auth.create_user("owner", "owner-password", is_admin=True)
    saas = SaasRepository(database, Fernet.generate_key().decode())
    saas.ensure_legacy_organization()
    order = saas.create_billing_order(
        organization_id=1,
        user_id=user["id"],
        plan_code="growth",
        amount_stars=999,
        payload="cs:1:1:growth:test",
    )
    expires = datetime(2026, 7, 8, tzinfo=timezone.utc)

    assert saas.complete_star_payment(
        order_id=order["id"],
        telegram_user_id=402385847,
        telegram_payment_charge_id="charge-1",
        amount_stars=999,
        plan=STAR_PLANS["growth"],
        expires_at=expires,
        raw="{}",
    )
    assert not saas.complete_star_payment(
        order_id=order["id"],
        telegram_user_id=402385847,
        telegram_payment_charge_id="charge-1",
        amount_stars=999,
        plan=STAR_PLANS["growth"],
        expires_at=expires,
        raw="{}",
    )
    company = saas.get_organization(1)
    assert company["plan_code"] == "growth"
    assert company["max_users"] == 10
    assert company["monthly_publications"] == 120
    assert company["monthly_ai_budget"] == 25
