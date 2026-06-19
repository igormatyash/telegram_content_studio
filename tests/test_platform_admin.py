from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from voicerhub_bot.admin import create_app
from voicerhub_bot.config import Settings


HEADERS = {"X-Requested-With": "VoicerHubAdmin"}


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
        privacy_hash_salt="platform-test-salt",
        public_app_url="http://testserver",
    )
    return create_app(settings)


def test_platform_admin_sees_clients_companies_referrals_and_activity(tmp_path) -> None:
    app = make_app(tmp_path)
    platform = TestClient(app)
    assert platform.post(
        "/api/login",
        json={"username": "platform.owner", "password": "initial-password"},
        headers={"user-agent": "Platform browser", "x-forwarded-for": "203.0.113.1"},
    ).status_code == 200
    referral = platform.get("/api/referrals/me").json()

    client = TestClient(app)
    client.get(
        f"/r/{referral['code']}?utm_source=partner&utm_campaign=launch",
        follow_redirects=False,
        headers={"user-agent": "Client browser", "x-forwarded-for": "198.51.100.5"},
    )
    registered = client.post(
        "/api/register",
        json={
            "username": "new.client",
            "password": "new-client-password",
            "email": "client@example.com",
            "display_name": "New Client",
            "workspace_name": "Client Company",
            "workspace_slug": "client-company",
            "referral_code": referral["code"],
        },
        headers={"user-agent": "Client browser", "x-forwarded-for": "198.51.100.5"},
    )
    assert registered.status_code == 200
    user_id = registered.json()["user"]["id"]
    organization_id = registered.json()["organization"]["id"]

    assert client.post("/api/logout", headers=HEADERS).status_code == 200
    assert client.post(
        "/api/login",
        json={"username": "new.client", "password": "new-client-password"},
        headers={"user-agent": "Client browser", "x-forwarded-for": "198.51.100.5"},
    ).status_code == 200

    overview = platform.get("/api/platform/overview", headers=HEADERS)
    clients = platform.get(
        "/api/platform/clients?source=referral&search=client@example.com",
        headers=HEADERS,
    )
    detail = platform.get(f"/api/platform/clients/{user_id}", headers=HEADERS)
    organizations = platform.get(
        "/api/platform/organizations/details",
        headers=HEADERS,
    )
    users = platform.get(
        "/api/platform/users?page=1&per_page=25&sort=created_at&direction=desc",
        headers=HEADERS,
    )
    activity = platform.get(
        "/api/platform/activity?page=1&per_page=25&sort=created_at&direction=desc",
        headers=HEADERS,
    )

    assert overview.status_code == 200
    assert overview.json()["metrics"]["users_total"] == 2
    assert overview.json()["metrics"]["organizations_total"] == 2
    assert overview.json()["metrics"]["referral_signups"] == 1
    assert clients.status_code == 200
    assert clients.json()["clients"][0]["registration_source"] == "referral"
    assert clients.json()["clients"][0]["login_count"] == 2
    assert detail.status_code == 200
    assert detail.json()["client"]["referral_code"] == referral["code"]
    assert detail.json()["client"]["last_login_at"]
    assert users.status_code == 200
    assert users.json()["total"] == 2
    assert users.json()["users"][0]["username"]
    assert activity.status_code == 200
    assert "events" in activity.json()
    assert detail.json()["content_totals"] == {
        "ideas": 0,
        "drafts": 0,
        "published": 0,
    }
    assert any(
        item["id"] == organization_id
        for item in organizations.json()["organizations"]
    )
    actions = {item["action"] for item in activity.json()["events"]}
    assert {
        "referral_link_opened",
        "user_registered",
        "organization_created",
        "referral_signup_completed",
        "user_logged_in",
    } <= actions
    assert activity.json()["logins"][0]["ip_hash"] != "198.51.100.5"


def test_platform_routes_are_hidden_from_regular_users(tmp_path) -> None:
    app = make_app(tmp_path)
    platform = TestClient(app)
    platform.post(
        "/api/login",
        json={"username": "platform.owner", "password": "initial-password"},
    )
    created = platform.post(
        "/api/organizations",
        headers=HEADERS,
        json={
            "name": "Regular Company",
            "slug": "regular-company",
            "owner_username": "regular.owner",
            "owner_password": "regular-password",
            "owner_email": "owner@regular.example",
        },
    )
    assert created.status_code == 200

    regular = TestClient(app)
    assert regular.post(
        "/api/login",
        json={"username": "regular.owner", "password": "regular-password"},
    ).status_code == 200
    assert regular.get("/platform").status_code == 403
    assert regular.get("/platform/clients").status_code == 403
    assert regular.get("/api/platform/overview", headers=HEADERS).status_code == 403
    assert regular.get("/api/platform/activity", headers=HEADERS).status_code == 403

    platform_page = platform.get("/platform/clients")
    assert platform_page.status_code == 200
    assert 'id="platformNav"' in platform_page.text
    assert 'id="platformView"' in platform_page.text
    assert "data-platform-section=\"referrals\"" in platform_page.text
    assert "static/app.js?v=20" in platform_page.text


def test_service_updates_feed_is_public_but_managed_by_platform_admin(tmp_path) -> None:
    app = make_app(tmp_path)
    platform = TestClient(app)
    assert platform.post(
        "/api/login",
        json={"username": "platform.owner", "password": "initial-password"},
    ).status_code == 200

    created = platform.post(
        "/api/organizations",
        headers=HEADERS,
        json={
            "name": "Client Workspace",
            "slug": "client-workspace",
            "owner_username": "client.owner",
            "owner_password": "client-password",
            "owner_email": "client@example.com",
        },
    )
    assert created.status_code == 200

    update = platform.post(
        "/api/platform/service-updates",
        headers=HEADERS,
        json={
            "title": "Оновили календар",
            "body": "Тепер у плануванні видно текст і візуал чернетки.",
            "category": "fix",
            "importance": "success",
            "status": "published",
            "pinned": True,
        },
    )
    assert update.status_code == 200
    assert update.json()["published_at"]

    client = TestClient(app)
    assert client.post(
        "/api/login",
        json={"username": "client.owner", "password": "client-password"},
    ).status_code == 200
    public_feed = client.get("/api/service-updates", headers=HEADERS)
    assert public_feed.status_code == 200
    assert public_feed.json()["items"][0]["title"] == "Оновили календар"
    assert public_feed.json()["latest_id"] == update.json()["id"]

    forbidden = client.post(
        "/api/platform/service-updates",
        headers=HEADERS,
        json={
            "title": "Не можна",
            "body": "",
            "category": "announcement",
            "importance": "info",
            "status": "published",
        },
    )
    assert forbidden.status_code == 403

    admin_feed = platform.get("/api/platform/service-updates", headers=HEADERS)
    assert admin_feed.status_code == 200
    assert admin_feed.json()["items"][0]["pinned"] == 1


def test_company_details_include_workspaces_users_and_roles(tmp_path) -> None:
    app = make_app(tmp_path)
    platform = TestClient(app)
    assert platform.post(
        "/api/login",
        json={"username": "platform.owner", "password": "initial-password"},
    ).status_code == 200
    created = platform.post(
        "/api/companies",
        headers=HEADERS,
        json={
            "name": "Multi Workspace Company",
            "slug": "multi-company",
            "workspace_name": "Marketing",
            "owner_username": "multi.owner",
            "owner_password": "multi-owner-password",
            "owner_email": "owner@multi.example",
            "owner_display_name": "Марія Власниця",
            "max_workspaces": 5,
        },
    )
    assert created.status_code == 200
    company_id = created.json()["company"]["id"]

    owner = TestClient(app)
    assert owner.post(
        "/api/login",
        json={"username": "multi.owner", "password": "multi-owner-password"},
    ).status_code == 200
    second_workspace = owner.post(
        "/api/account/trial-workspace",
        headers=HEADERS,
        json={"name": "Sales", "slug": "multi-sales", "company_id": company_id},
    )
    assert second_workspace.status_code == 200
    assert second_workspace.json()["company_id"] == company_id

    companies = platform.get("/api/platform/companies", headers=HEADERS)
    assert companies.status_code == 200
    company = next(
        item for item in companies.json()["companies"]
        if item["id"] == company_id
    )
    assert company["workspace_count"] == 2
    assert company["user_count"] == 1
    assert company["role_counts"]["owner"] == 1

    detail = platform.get(
        f"/api/platform/companies/{company_id}",
        headers=HEADERS,
    )
    assert detail.status_code == 200
    assert {item["name"] for item in detail.json()["workspaces"]} == {
        "Marketing",
        "Sales",
    }
    user = detail.json()["users"][0]
    assert user["display_name"] == "Марія Власниця"
    assert user["email"] == "owner@multi.example"
    assert user["company_role"] == "owner"
    assert {item["role"] for item in user["workspace_roles"]} == {"owner"}

    assert owner.get(
        f"/api/platform/companies/{company_id}",
        headers=HEADERS,
    ).status_code == 403
