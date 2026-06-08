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
from voicerhub_bot.storage import TenantRepository


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
            "max_users": 50,
            "max_channels": 1,
            "monthly_publications": 90,
            "monthly_ai_budget": 50,
        },
    )

    assert response.status_code == 200
    assert response.json()["id"] == 2
    assert response.json()["owner"]["organization_id"] == 2
    assert (tmp_path / "organizations" / "2" / "content.sqlite3").is_file()


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


def test_ai_budget_blocks_new_generation_before_openai_call(tmp_path) -> None:
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
    assert "AI-бюджет" in response.json()["detail"]


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
