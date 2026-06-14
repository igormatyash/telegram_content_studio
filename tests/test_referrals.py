import sqlite3

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from voicerhub_bot.admin import create_app
from voicerhub_bot.config import Settings
from voicerhub_bot.referrals import ReferralRepository


def make_app(tmp_path):
    settings = Settings(
        telegram_bot_token="telegram",
        openai_api_key="openai",
        admin_username="platform.owner",
        admin_password="initial-password",
        database_path=tmp_path / "platform.sqlite3",
        generated_dir=tmp_path / "generated",
        reference_dir=tmp_path / "references",
        organizations_dir=tmp_path / "organizations",
        app_encryption_key=Fernet.generate_key().decode(),
        privacy_hash_salt="test-referral-salt",
        public_app_url="http://testserver",
    )
    return create_app(settings), settings


def test_referral_repository_migrations_are_idempotent(tmp_path) -> None:
    app, settings = make_app(tmp_path)
    del app
    repository = ReferralRepository(
        settings.database_path,
        settings.privacy_hash_salt,
    )
    owner = repository.code_for_owner(1, 1)
    click = repository.record_click(
        owner["code"],
        ip_address="203.0.113.42",
        user_agent="Referral test browser",
        utm_source="partner",
        utm_campaign="launch",
        landing_url="https://example.test/register",
    )

    ReferralRepository(settings.database_path, settings.privacy_hash_salt)

    assert click["ip_hash"] != "203.0.113.42"
    assert len(click["ip_hash"]) == 64
    with sqlite3.connect(settings.database_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM referral_codes WHERE code = ?",
            (owner["code"],),
        ).fetchone()[0] == 1


def test_referral_link_registration_and_privacy(tmp_path) -> None:
    app, settings = make_app(tmp_path)
    headers = {"X-Requested-With": "VoicerHubAdmin"}
    platform = TestClient(app)
    assert platform.post(
        "/api/login",
        json={"username": "platform.owner", "password": "initial-password"},
    ).status_code == 200
    referral = platform.get("/api/referrals/me").json()

    visitor = TestClient(app)
    opened = visitor.get(
        f"/r/{referral['code']}?utm_source=partner&utm_campaign=summer",
        follow_redirects=False,
        headers={
            "user-agent": "Referral browser",
            "x-forwarded-for": "198.51.100.7",
        },
    )
    assert opened.status_code == 303
    assert opened.headers["location"].startswith(
        f"http://testserver/register?ref={referral['code']}"
    )
    registration_page = visitor.get(opened.headers["location"])
    assert registration_page.status_code == 200
    assert "Вас запросили" in registration_page.text

    registered = visitor.post(
        "/api/register",
        json={
            "username": "referred.owner",
            "password": "referred-password",
            "email": "referred@example.com",
            "display_name": "Referred Owner",
            "workspace_name": "Referred Company",
            "workspace_slug": "referred-company",
            "referral_code": referral["code"],
        },
    )
    assert registered.status_code == 200
    assert registered.json()["referred"] is True
    referred_user = registered.json()["user"]
    referred_organization = registered.json()["organization"]
    assert referred_user["referred_by_user_id"] == 1

    own_summary = platform.get("/api/referrals/me").json()
    assert own_summary["clicks"] == 1
    assert own_summary["signups"] == 1
    assert own_summary["active_clients"] == 1

    visitor_summary = visitor.get("/api/referrals/me").json()
    assert visitor_summary["signups"] == 0
    assert visitor.get("/api/platform/referrals", headers=headers).status_code == 403

    platform_report = platform.get(
        "/api/platform/referrals",
        headers=headers,
    )
    assert platform_report.status_code == 200
    signup = platform_report.json()["signups"][0]
    assert signup["new_user_id"] == referred_user["id"]
    assert signup["new_organization_id"] == referred_organization["id"]
    assert signup["utm_source"] == "partner"
    assert signup["utm_campaign"] == "summer"


def test_referral_cannot_be_used_by_its_owner_and_can_be_disabled(tmp_path) -> None:
    app, _ = make_app(tmp_path)
    platform = TestClient(app)
    platform.post(
        "/api/login",
        json={"username": "platform.owner", "password": "initial-password"},
    )
    headers = {"X-Requested-With": "VoicerHubAdmin"}
    referral = platform.get("/api/referrals/me").json()

    self_signup = platform.post(
        "/api/register",
        json={
            "username": "another.owner",
            "password": "another-password",
            "email": "another@example.com",
            "display_name": "Another Owner",
            "workspace_name": "Another Company",
            "workspace_slug": "another-company",
            "referral_code": referral["code"],
        },
    )
    assert self_signup.status_code == 409
    assert "власним" in self_signup.json()["detail"]

    disabled = platform.post(
        "/api/referrals/me/disable",
        headers=headers,
    )
    assert disabled.status_code == 200
    assert disabled.json()["status"] == "disabled"
    assert TestClient(app).get(f"/r/{referral['code']}").status_code == 404

    rotated = platform.post(
        "/api/referrals/me/rotate",
        headers=headers,
    )
    assert rotated.status_code == 200
    assert rotated.json()["status"] == "active"
    assert rotated.json()["code"] != referral["code"]
