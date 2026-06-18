import hashlib
import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from voicerhub_bot.permissions import WORKSPACE_ROLES
from voicerhub_bot.slugs import generate_slug

ROLES = WORKSPACE_ROLES


class SecretCipher:
    def __init__(self, key: str) -> None:
        self._fernet = Fernet(key.encode()) if key else None

    @property
    def configured(self) -> bool:
        return self._fernet is not None

    def encrypt(self, value: str) -> str:
        if self._fernet is None:
            raise RuntimeError("APP_ENCRYPTION_KEY is required")
        return self._fernet.encrypt(value.encode()).decode()

    def decrypt(self, value: str) -> str:
        if self._fernet is None:
            raise RuntimeError("APP_ENCRYPTION_KEY is required")
        try:
            return self._fernet.decrypt(value.encode()).decode()
        except InvalidToken as exc:
            raise RuntimeError("Stored Telegram token cannot be decrypted") from exc


class SaasRepository:
    def __init__(
        self,
        database_path: Path,
        encryption_key: str = "",
        hash_salt: str = "",
    ) -> None:
        self.database_path = database_path
        self.cipher = SecretCipher(encryption_key)
        self.hash_salt = hash_salt
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS companies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    slug TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    active INTEGER NOT NULL DEFAULT 1,
                    max_workspaces INTEGER NOT NULL DEFAULT 3,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS company_members (
                    company_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    role TEXT NOT NULL DEFAULT 'member',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (company_id, user_id),
                    FOREIGN KEY (company_id) REFERENCES companies(id),
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS organizations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    company_id INTEGER,
                    name TEXT NOT NULL,
                    slug TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    active INTEGER NOT NULL DEFAULT 1,
                    max_users INTEGER NOT NULL DEFAULT 50,
                    max_channels INTEGER NOT NULL DEFAULT 1,
                    monthly_publications INTEGER NOT NULL DEFAULT 90,
                    monthly_ai_budget REAL NOT NULL DEFAULT 50,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS organization_members (
                    organization_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    role TEXT NOT NULL DEFAULT 'editor',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (organization_id, user_id),
                    FOREIGN KEY (organization_id) REFERENCES organizations(id),
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS telegram_connections (
                    organization_id INTEGER PRIMARY KEY,
                    channel_id TEXT NOT NULL,
                    bot_token_encrypted TEXT,
                    bot_username TEXT NOT NULL DEFAULT '',
                    active INTEGER NOT NULL DEFAULT 1,
                    verified_at TEXT,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (organization_id) REFERENCES organizations(id)
                );
                CREATE TABLE IF NOT EXISTS audit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    organization_id INTEGER,
                    user_id INTEGER,
                    action TEXT NOT NULL,
                    details TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS service_updates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    body TEXT NOT NULL DEFAULT '',
                    category TEXT NOT NULL DEFAULT 'release',
                    importance TEXT NOT NULL DEFAULT 'info',
                    status TEXT NOT NULL DEFAULT 'published',
                    pinned INTEGER NOT NULL DEFAULT 0,
                    visible_from TEXT,
                    visible_until TEXT,
                    created_by_user_id INTEGER,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    published_at TEXT
                );
                CREATE TABLE IF NOT EXISTS social_connections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    organization_id INTEGER NOT NULL,
                    platform TEXT NOT NULL,
                    external_account_id TEXT NOT NULL,
                    username TEXT NOT NULL DEFAULT '',
                    display_name TEXT NOT NULL DEFAULT '',
                    account_type TEXT NOT NULL DEFAULT '',
                    page_id TEXT NOT NULL DEFAULT '',
                    page_name TEXT NOT NULL DEFAULT '',
                    access_token_encrypted TEXT,
                    token_expires_at TEXT,
                    permissions TEXT NOT NULL DEFAULT '[]',
                    metadata TEXT NOT NULL DEFAULT '{}',
                    active INTEGER NOT NULL DEFAULT 1,
                    verified_at TEXT,
                    last_error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(organization_id, platform),
                    FOREIGN KEY (organization_id) REFERENCES organizations(id)
                );
                CREATE TABLE IF NOT EXISTS social_publish_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    organization_id INTEGER NOT NULL,
                    draft_id INTEGER NOT NULL,
                    platform TEXT NOT NULL,
                    connection_id INTEGER,
                    variant_id INTEGER,
                    media_kind TEXT NOT NULL DEFAULT 'feed_image',
                    scheduled_at TEXT,
                    status TEXT NOT NULL DEFAULT 'queued',
                    provider_container_id TEXT NOT NULL DEFAULT '',
                    provider_media_id TEXT NOT NULL DEFAULT '',
                    permalink TEXT NOT NULL DEFAULT '',
                    error TEXT NOT NULL DEFAULT '',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    created_by_user_id INTEGER,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    published_at TEXT,
                    FOREIGN KEY (organization_id) REFERENCES organizations(id),
                    FOREIGN KEY (connection_id) REFERENCES social_connections(id)
                );
                CREATE TABLE IF NOT EXISTS billing_orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    organization_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    plan_code TEXT NOT NULL,
                    amount_stars INTEGER NOT NULL,
                    payload TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    paid_at TEXT,
                    FOREIGN KEY (organization_id) REFERENCES organizations(id),
                    FOREIGN KEY (user_id) REFERENCES users(id)
                );
                CREATE TABLE IF NOT EXISTS star_payments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id INTEGER NOT NULL,
                    organization_id INTEGER NOT NULL,
                    telegram_user_id INTEGER,
                    telegram_payment_charge_id TEXT NOT NULL UNIQUE,
                    amount_stars INTEGER NOT NULL,
                    raw TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (order_id) REFERENCES billing_orders(id),
                    FOREIGN KEY (organization_id) REFERENCES organizations(id)
                );
                CREATE TABLE IF NOT EXISTS organization_settings (
                    organization_id INTEGER PRIMARY KEY,
                    onboarding_status TEXT NOT NULL DEFAULT 'not_started',
                    onboarding_step INTEGER NOT NULL DEFAULT 0,
                    workspace_mode TEXT NOT NULL DEFAULT 'pipeline',
                    primary_language TEXT NOT NULL DEFAULT 'uk',
                    brand_primary_color TEXT NOT NULL DEFAULT '',
                    brand_logo_asset_id INTEGER,
                    tone_of_voice TEXT NOT NULL DEFAULT '',
                    company_description TEXT NOT NULL DEFAULT '',
                    forbidden_phrases TEXT NOT NULL DEFAULT '',
                    key_services TEXT NOT NULL DEFAULT '',
                    website_url TEXT NOT NULL DEFAULT '',
                    initial_rubrics_created INTEGER NOT NULL DEFAULT 0,
                    first_content_plan_created INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (organization_id) REFERENCES organizations(id)
                );
                """
            )
            self._ensure_column(connection, "organizations", "plan_code", "TEXT NOT NULL DEFAULT 'custom'")
            self._ensure_column(connection, "organizations", "plan_expires_at", "TEXT")
            self._ensure_column(connection, "organizations", "company_id", "INTEGER")
            self._ensure_column(
                connection,
                "organizations",
                "referred_by_organization_id",
                "INTEGER",
            )
            for column, definition in {
                "brand_secondary_color": "TEXT NOT NULL DEFAULT ''",
                "workspace_avatar_asset_id": "INTEGER",
                "favicon_asset_id": "INTEGER",
                "workspace_short_description": "TEXT NOT NULL DEFAULT ''",
            }.items():
                self._ensure_column(
                    connection,
                    "organization_settings",
                    column,
                    definition,
                )
            self._ensure_column(
                connection,
                "audit_events",
                "ip_hash",
                "TEXT NOT NULL DEFAULT ''",
            )
            self._ensure_column(
                connection,
                "audit_events",
                "user_agent",
                "TEXT NOT NULL DEFAULT ''",
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_audit_events_activity
                ON audit_events(created_at, action)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_service_updates_feed
                ON service_updates(status, pinned, published_at, created_at)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_organizations_company
                ON organizations(company_id, active)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_social_publish_jobs_due
                ON social_publish_jobs(platform, status, scheduled_at)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_social_publish_jobs_draft
                ON social_publish_jobs(organization_id, draft_id, platform, created_at)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_company_members_user
                ON company_members(user_id, company_id)
                """
            )
            self._backfill_companies(connection)

    @staticmethod
    def _ensure_column(
        connection: sqlite3.Connection,
        table: str,
        column: str,
        definition: str,
    ) -> None:
        columns = {
            row["name"]
            for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if column not in columns:
            connection.execute(
                f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
            )

    @staticmethod
    def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
        row = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone()
        return row is not None

    @staticmethod
    def _backfill_companies(connection: sqlite3.Connection) -> None:
        organizations = connection.execute(
            """
            SELECT id, name, slug, active, created_at
            FROM organizations
            WHERE company_id IS NULL
            ORDER BY id
            """
        ).fetchall()
        for organization in organizations:
            company = connection.execute(
                "SELECT id FROM companies WHERE slug = ? COLLATE NOCASE",
                (organization["slug"],),
            ).fetchone()
            if company is None:
                cursor = connection.execute(
                    """
                    INSERT INTO companies (
                        name, slug, active, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        organization["name"],
                        organization["slug"],
                        organization["active"],
                        organization["created_at"],
                        organization["created_at"],
                    ),
                )
                company_id = int(cursor.lastrowid)
            else:
                company_id = int(company["id"])
            connection.execute(
                "UPDATE organizations SET company_id = ? WHERE id = ?",
                (company_id, organization["id"]),
            )
        memberships = connection.execute(
            """
            SELECT o.company_id, m.user_id,
                CASE
                    WHEN MAX(CASE WHEN m.role = 'owner' THEN 3
                                      WHEN m.role = 'admin' THEN 2
                                      ELSE 1 END) = 3 THEN 'owner'
                    WHEN MAX(CASE WHEN m.role = 'owner' THEN 3
                                      WHEN m.role = 'admin' THEN 2
                                      ELSE 1 END) = 2 THEN 'admin'
                    ELSE 'member'
                END company_role
            FROM organization_members m
            JOIN organizations o ON o.id = m.organization_id
            WHERE o.company_id IS NOT NULL
            GROUP BY o.company_id, m.user_id
            """
        ).fetchall()
        for membership in memberships:
            connection.execute(
                """
                INSERT INTO company_members (company_id, user_id, role)
                VALUES (?, ?, ?)
                ON CONFLICT(company_id, user_id) DO UPDATE SET
                    role = CASE
                        WHEN company_members.role = 'owner' THEN 'owner'
                        WHEN excluded.role = 'owner' THEN 'owner'
                        WHEN company_members.role = 'admin' THEN 'admin'
                        ELSE excluded.role
                    END
                """,
                (
                    membership["company_id"],
                    membership["user_id"],
                    membership["company_role"],
                ),
            )

    def ensure_legacy_organization(
        self,
        *,
        name: str = "VoicerHub",
        channel_id: str = "@voicerhub",
    ) -> dict:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM organizations WHERE id = 1"
            ).fetchone()
            if row is None:
                connection.execute(
                    """
                    INSERT INTO organizations (
                        id, name, slug, max_users, max_channels,
                        monthly_publications, monthly_ai_budget
                    ) VALUES (1, ?, 'voicerhub', 50, 1, 90, 50)
                    """,
                    (name,),
                )
            connection.execute(
                """
                INSERT INTO telegram_connections (organization_id, channel_id)
                VALUES (1, ?)
                ON CONFLICT(organization_id) DO NOTHING
                """,
                (channel_id,),
            )
            connection.execute(
                """
                INSERT INTO organization_settings (
                    organization_id, onboarding_status, onboarding_step
                ) VALUES (1, 'completed', 5)
                ON CONFLICT(organization_id) DO NOTHING
                """
            )
            users = connection.execute(
                "SELECT id, is_admin FROM users ORDER BY id"
            ).fetchall()
            for user in users:
                connection.execute(
                    """
                    INSERT INTO organization_members (organization_id, user_id, role)
                    VALUES (1, ?, ?)
                    ON CONFLICT(organization_id, user_id) DO NOTHING
                    """,
                    (user["id"], "owner" if user["is_admin"] else "editor"),
                )
            self._backfill_companies(connection)
        return self.get_organization(1)

    def create_company(
        self,
        *,
        name: str,
        slug: str,
        max_workspaces: int = 3,
    ) -> dict:
        normalized = self.unique_company_slug(slug or name)
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO companies (name, slug, max_workspaces)
                VALUES (?, ?, ?)
                """,
                (name.strip(), normalized, max(1, max_workspaces)),
            )
            company_id = int(cursor.lastrowid)
        return self.get_company(company_id)

    def create_organization(
        self,
        *,
        name: str,
        slug: str,
        max_users: int,
        max_channels: int,
        monthly_publications: int,
        monthly_ai_budget: float,
        company_id: int | None = None,
    ) -> dict:
        if company_id is None:
            company = self.create_company(name=name, slug=slug or name)
            company_id = int(company["id"])
        else:
            company = self.get_company(company_id)
            if len(self.workspaces_for_company(company_id)) >= int(
                company["max_workspaces"]
            ):
                raise ValueError("Досягнуто ліміт workspace для компанії")
        normalized = self.unique_slug(slug or name)
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO organizations (
                    company_id, name, slug, max_users, max_channels,
                    monthly_publications, monthly_ai_budget
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    company_id,
                    name.strip(),
                    normalized,
                    max_users,
                    max_channels,
                    monthly_publications,
                    monthly_ai_budget,
                ),
            )
            organization_id = int(cursor.lastrowid)
            connection.execute(
                """
                INSERT INTO organization_settings (organization_id)
                VALUES (?)
                """,
                (organization_id,),
            )
        return self.get_organization(organization_id)

    def create_trial_organization(
        self,
        *,
        name: str,
        slug: str,
        company_id: int | None = None,
    ) -> dict:
        organization = self.create_organization(
            name=name,
            slug=slug,
            max_users=3,
            max_channels=1,
            monthly_publications=30,
            monthly_ai_budget=8,
            company_id=company_id,
        )
        expires_at = datetime.now(timezone.utc) + timedelta(days=14)
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE organizations
                SET plan_code = 'trial', plan_expires_at = ?
                WHERE id = ?
                """,
                (expires_at.isoformat(), organization["id"]),
            )
        return self.get_organization(organization["id"])

    def get_company(self, company_id: int) -> dict:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM companies WHERE id = ?",
                (company_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"Company {company_id} not found")
        return dict(row)

    def delete_empty_company(self, company_id: int) -> bool:
        with self._connect() as connection:
            member_count = connection.execute(
                "SELECT COUNT(*) FROM company_members WHERE company_id = ?",
                (company_id,),
            ).fetchone()[0]
            workspace_member_count = connection.execute(
                """
                SELECT COUNT(*)
                FROM organization_members m
                JOIN organizations o ON o.id = m.organization_id
                WHERE o.company_id = ?
                """,
                (company_id,),
            ).fetchone()[0]
            if member_count or workspace_member_count:
                return False
            workspace_ids = [
                int(row["id"])
                for row in connection.execute(
                    "SELECT id FROM organizations WHERE company_id = ?",
                    (company_id,),
                ).fetchall()
            ]
            for workspace_id in workspace_ids:
                connection.execute(
                    "DELETE FROM organization_settings WHERE organization_id = ?",
                    (workspace_id,),
                )
                connection.execute(
                    "DELETE FROM telegram_connections WHERE organization_id = ?",
                    (workspace_id,),
                )
            connection.execute(
                "DELETE FROM organizations WHERE company_id = ?",
                (company_id,),
            )
            cursor = connection.execute(
                "DELETE FROM companies WHERE id = ?",
                (company_id,),
            )
        return bool(cursor.rowcount)

    def company_for_organization(self, organization_id: int) -> dict:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT c.*
                FROM companies c
                JOIN organizations o ON o.company_id = c.id
                WHERE o.id = ?
                """,
                (organization_id,),
            ).fetchone()
        if row is None:
            raise KeyError("Company not found")
        return dict(row)

    def workspaces_for_company(self, company_id: int) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT o.*,
                    s.workspace_short_description,
                    s.workspace_avatar_asset_id,
                    s.brand_logo_asset_id,
                    s.brand_primary_color,
                    s.brand_secondary_color,
                    COUNT(DISTINCT m.user_id) user_count,
                    COUNT(DISTINCT CASE WHEN tc.active = 1 THEN tc.organization_id END)
                        channel_count
                FROM organizations o
                LEFT JOIN organization_members m ON m.organization_id = o.id
                LEFT JOIN telegram_connections tc ON tc.organization_id = o.id
                LEFT JOIN organization_settings s ON s.organization_id = o.id
                WHERE o.company_id = ?
                GROUP BY o.id
                ORDER BY o.id
                """,
                (company_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_companies(self) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT c.*,
                    COUNT(DISTINCT o.id) workspace_count,
                    COUNT(DISTINCT cm.user_id) user_count
                FROM companies c
                LEFT JOIN organizations o
                  ON o.company_id = c.id
                LEFT JOIN company_members cm
                  ON cm.company_id = c.id
                GROUP BY c.id
                ORDER BY c.id
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def unique_company_slug(
        self,
        value: str,
        *,
        exclude_id: int | None = None,
    ) -> str:
        base = generate_slug(value) or "company"
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, slug FROM companies WHERE slug LIKE ? COLLATE NOCASE",
                (f"{base}%",),
            ).fetchall()
        occupied = {
            str(row["slug"]).lower()
            for row in rows
            if exclude_id is None or int(row["id"]) != exclude_id
        }
        if base not in occupied:
            return base
        suffix = 2
        while f"{base}-{suffix}" in occupied:
            suffix += 1
        return f"{base}-{suffix}"

    def get_organization(self, organization_id: int) -> dict:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM organizations WHERE id = ?",
                (organization_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"Organization {organization_id} not found")
        return dict(row)

    def update_organization(
        self,
        organization_id: int,
        *,
        name: str,
        slug: str,
    ) -> dict:
        normalized = self.unique_slug(slug or name, exclude_id=organization_id)
        if not name.strip() or not normalized:
            raise ValueError("Organization name and slug are required")
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE organizations SET name = ?, slug = ?
                WHERE id = ?
                """,
                (name.strip(), normalized, organization_id),
            )
        return self.get_organization(organization_id)

    def delete_organization(self, organization_id: int) -> dict:
        organization = self.get_organization(organization_id)
        if organization_id == 1:
            raise ValueError("Системний workspace не можна видалити")
        company_id = int(organization["company_id"])
        if len(self.workspaces_for_company(company_id)) <= 1:
            raise ValueError(
                "Не можна видалити єдиний workspace компанії. "
                "Спочатку створіть інший workspace."
            )
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE referral_signups
                SET referrer_organization_id = NULL
                WHERE referrer_organization_id = ?
                """,
                (organization_id,),
            )
            connection.execute(
                """
                UPDATE referral_signups
                SET new_organization_id = NULL
                WHERE new_organization_id = ?
                """,
                (organization_id,),
            )
            connection.execute(
                """
                UPDATE referral_codes
                SET owner_organization_id = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE owner_organization_id = ?
                """,
                (organization_id,),
            )
            connection.execute(
                """
                UPDATE organizations
                SET referred_by_organization_id = NULL
                WHERE referred_by_organization_id = ?
                """,
                (organization_id,),
            )
            connection.execute(
                "DELETE FROM auth_action_tokens WHERE organization_id = ?",
                (organization_id,),
            )
            connection.execute(
                "UPDATE login_events SET organization_id = NULL WHERE organization_id = ?",
                (organization_id,),
            )
            connection.execute(
                """
                DELETE FROM star_payments
                WHERE organization_id = ?
                   OR order_id IN (
                        SELECT id FROM billing_orders WHERE organization_id = ?
                   )
                """,
                (organization_id, organization_id),
            )
            connection.execute(
                "DELETE FROM billing_orders WHERE organization_id = ?",
                (organization_id,),
            )
            connection.execute(
                "DELETE FROM telegram_connections WHERE organization_id = ?",
                (organization_id,),
            )
            connection.execute(
                "DELETE FROM social_publish_jobs WHERE organization_id = ?",
                (organization_id,),
            )
            connection.execute(
                "DELETE FROM social_connections WHERE organization_id = ?",
                (organization_id,),
            )
            connection.execute(
                "DELETE FROM organization_settings WHERE organization_id = ?",
                (organization_id,),
            )
            connection.execute(
                "DELETE FROM organization_members WHERE organization_id = ?",
                (organization_id,),
            )
            connection.execute(
                """
                UPDATE user_sessions
                SET selected_organization_id = (
                    SELECT m.organization_id
                    FROM organization_members m
                    JOIN organizations o ON o.id = m.organization_id
                    WHERE m.user_id = user_sessions.user_id
                      AND o.active = 1
                    ORDER BY m.organization_id
                    LIMIT 1
                )
                WHERE selected_organization_id = ?
                """,
                (organization_id,),
            )
            connection.execute(
                "DELETE FROM organizations WHERE id = ?",
                (organization_id,),
            )
        return organization

    def set_organizations_active(
        self,
        organization_ids: list[int],
        active: bool,
    ) -> int:
        if not organization_ids:
            return 0
        placeholders = ",".join("?" for _ in organization_ids)
        with self._connect() as connection:
            cursor = connection.execute(
                f"""
                UPDATE organizations SET active = ?
                WHERE id IN ({placeholders})
                """,
                (int(active), *organization_ids),
            )
        return int(cursor.rowcount)

    def set_companies_active(
        self,
        company_ids: list[int],
        active: bool,
    ) -> int:
        if not company_ids:
            return 0
        placeholders = ",".join("?" for _ in company_ids)
        with self._connect() as connection:
            cursor = connection.execute(
                f"""
                UPDATE companies SET active = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id IN ({placeholders})
                """,
                (int(active), *company_ids),
            )
            connection.execute(
                f"""
                UPDATE organizations SET active = ?
                WHERE company_id IN ({placeholders})
                """,
                (int(active), *company_ids),
            )
        return int(cursor.rowcount)

    def unique_slug(self, value: str, *, exclude_id: int | None = None) -> str:
        base = generate_slug(value) or "workspace"
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, slug FROM organizations WHERE slug LIKE ? COLLATE NOCASE",
                (f"{base}%",),
            ).fetchall()
        occupied = {
            str(row["slug"]).lower()
            for row in rows
            if exclude_id is None or int(row["id"]) != exclude_id
        }
        if base not in occupied:
            return base
        suffix = 2
        while f"{base}-{suffix}" in occupied:
            suffix += 1
        return f"{base}-{suffix}"

    def organization_settings(self, organization_id: int) -> dict:
        self.get_organization(organization_id)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO organization_settings (organization_id)
                VALUES (?)
                ON CONFLICT(organization_id) DO NOTHING
                """,
                (organization_id,),
            )
            row = connection.execute(
                """
                SELECT * FROM organization_settings
                WHERE organization_id = ?
                """,
                (organization_id,),
            ).fetchone()
        return dict(row)

    def update_organization_settings(
        self,
        organization_id: int,
        **values: object,
    ) -> dict:
        allowed = {
            "onboarding_status",
            "onboarding_step",
            "workspace_mode",
            "primary_language",
            "brand_primary_color",
            "brand_secondary_color",
            "brand_logo_asset_id",
            "workspace_avatar_asset_id",
            "favicon_asset_id",
            "workspace_short_description",
            "tone_of_voice",
            "company_description",
            "forbidden_phrases",
            "key_services",
            "website_url",
            "initial_rubrics_created",
            "first_content_plan_created",
        }
        unknown = set(values) - allowed
        if unknown:
            raise ValueError(f"Unsupported organization settings: {unknown}")
        if values:
            assignments = [f"{key} = ?" for key in values]
            params = [*values.values(), organization_id]
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO organization_settings (organization_id)
                    VALUES (?)
                    ON CONFLICT(organization_id) DO NOTHING
                    """,
                    (organization_id,),
                )
                connection.execute(
                    f"""
                    UPDATE organization_settings
                    SET {", ".join(assignments)}, updated_at = CURRENT_TIMESTAMP
                    WHERE organization_id = ?
                    """,
                    params,
                )
        return self.organization_settings(organization_id)

    def list_organizations(self) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT o.*,
                    c.name company_name, c.slug company_slug,
                    s.workspace_short_description,
                    s.workspace_avatar_asset_id,
                    s.brand_logo_asset_id,
                    s.brand_primary_color,
                    s.brand_secondary_color,
                    COUNT(DISTINCT m.user_id) user_count,
                    COUNT(DISTINCT CASE WHEN tc.active = 1 THEN tc.organization_id END)
                        channel_count
                FROM organizations o
                JOIN companies c ON c.id = o.company_id
                LEFT JOIN organization_members m ON m.organization_id = o.id
                LEFT JOIN telegram_connections tc ON tc.organization_id = o.id
                LEFT JOIN organization_settings s ON s.organization_id = o.id
                GROUP BY o.id
                ORDER BY o.id
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def add_member(self, organization_id: int, user_id: int, role: str) -> None:
        if role not in ROLES:
            raise ValueError("Unsupported organization role")
        organization = self.get_organization(organization_id)
        with self._connect() as connection:
            member_count = connection.execute(
                "SELECT COUNT(*) FROM organization_members WHERE organization_id = ?",
                (organization_id,),
            ).fetchone()[0]
            if member_count >= organization["max_users"]:
                raise ValueError("Organization user limit reached")
            connection.execute(
                """
                INSERT INTO organization_members (organization_id, user_id, role)
                VALUES (?, ?, ?)
                """,
                (organization_id, user_id, role),
            )
        company = self.company_for_organization(organization_id)
        self.add_company_member(
            int(company["id"]),
            user_id,
            "owner" if role == "owner" else "admin" if role == "admin" else "member",
        )

    def add_company_member(
        self,
        company_id: int,
        user_id: int,
        role: str = "member",
    ) -> None:
        if role not in {"owner", "admin", "member"}:
            raise ValueError("Unsupported company role")
        self.get_company(company_id)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO company_members (company_id, user_id, role)
                VALUES (?, ?, ?)
                ON CONFLICT(company_id, user_id) DO UPDATE SET
                    role = CASE
                        WHEN company_members.role = 'owner' THEN 'owner'
                        WHEN excluded.role = 'owner' THEN 'owner'
                        WHEN company_members.role = 'admin' THEN 'admin'
                        ELSE excluded.role
                    END
                """,
                (company_id, user_id, role),
            )

    def company_role_for_user(self, company_id: int, user_id: int) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT role FROM company_members
                WHERE company_id = ? AND user_id = ?
                """,
                (company_id, user_id),
            ).fetchone()
        return str(row["role"]) if row else None

    def company_memberships_for_user(self, user_id: int) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT cm.company_id, cm.role, cm.created_at,
                    c.name company_name, c.slug company_slug,
                    c.active company_active
                FROM company_members cm
                JOIN companies c ON c.id = cm.company_id
                WHERE cm.user_id = ? AND c.active = 1
                ORDER BY cm.company_id
                """,
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def all_company_memberships(self) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT cm.company_id, cm.user_id, cm.role, cm.created_at,
                    c.name company_name, c.slug company_slug,
                    c.active company_active
                FROM company_members cm
                JOIN companies c ON c.id = cm.company_id
                ORDER BY cm.company_id, cm.user_id
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def company_users(self, company_id: int) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT u.id, u.username, u.email, u.display_name, u.active,
                    u.created_at, u.last_login_at, u.last_seen_at, u.login_count,
                    cm.role company_role
                FROM company_members cm
                JOIN users u ON u.id = cm.user_id
                WHERE cm.company_id = ?
                ORDER BY
                    CASE cm.role WHEN 'owner' THEN 0 WHEN 'admin' THEN 1 ELSE 2 END,
                    u.display_name COLLATE NOCASE,
                    u.username COLLATE NOCASE
                """,
                (company_id,),
            ).fetchall()
            workspace_rows = connection.execute(
                """
                SELECT om.user_id, o.id workspace_id, o.name workspace_name,
                    om.role
                FROM organizations o
                JOIN organization_members om ON om.organization_id = o.id
                WHERE o.company_id = ?
                ORDER BY o.id
                """,
                (company_id,),
            ).fetchall()
        roles_by_user: dict[int, list[dict]] = {}
        for workspace in workspace_rows:
            roles_by_user.setdefault(int(workspace["user_id"]), []).append(
                {
                    "workspace_id": int(workspace["workspace_id"]),
                    "workspace_name": workspace["workspace_name"],
                    "role": workspace["role"],
                }
            )
        result = []
        for row in rows:
            item = dict(row)
            item["workspace_roles"] = roles_by_user.get(int(item["id"]), [])
            result.append(item)
        return result

    def companies_for_user(
        self,
        user_id: int,
        *,
        platform_admin: bool = False,
    ) -> list[dict]:
        companies = self.list_companies()
        if platform_admin:
            allowed_ids = {int(item["id"]) for item in companies}
        else:
            allowed_ids = {
                int(item["company_id"])
                for item in self.company_memberships_for_user(user_id)
            }
        result = []
        roles = {
            int(item["company_id"]): item["role"]
            for item in self.company_memberships_for_user(user_id)
        }
        for company in companies:
            if int(company["id"]) not in allowed_ids:
                continue
            result.append(
                {
                    **company,
                    "role": (
                        "platform_admin"
                        if platform_admin
                        else roles.get(int(company["id"]), "member")
                    ),
                    "workspaces": self.workspaces_for_company(int(company["id"])),
                }
            )
        return result

    def upsert_member(self, organization_id: int, user_id: int, role: str) -> None:
        if role not in ROLES:
            raise ValueError("Unsupported organization role")
        existing = self.role_for_user(organization_id, user_id)
        if existing:
            company = self.company_for_organization(organization_id)
            self.add_company_member(
                int(company["id"]),
                user_id,
                "owner" if role == "owner" else "admin" if role == "admin" else "member",
            )
            return
        self.add_member(organization_id, user_id, role)

    def membership_for_user(self, user_id: int) -> dict | None:
        memberships = self.memberships_for_user(user_id)
        return memberships[0] if memberships else None

    def memberships_for_user(self, user_id: int) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT m.organization_id, m.role, o.name organization_name,
                    o.slug organization_slug, o.active organization_active
                FROM organization_members m
                JOIN organizations o ON o.id = m.organization_id
                WHERE m.user_id = ? AND o.active = 1
                ORDER BY m.organization_id
                """,
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def all_memberships(self) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT m.organization_id, m.user_id, m.role, m.created_at,
                    o.name organization_name, o.slug organization_slug,
                    o.active organization_active
                FROM organization_members m
                JOIN organizations o ON o.id = m.organization_id
                ORDER BY m.user_id, m.organization_id
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def role_for_user(self, organization_id: int, user_id: int) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT role FROM organization_members
                WHERE organization_id = ? AND user_id = ?
                """,
                (organization_id, user_id),
            ).fetchone()
        return str(row["role"]) if row else None

    def organizations_for_user(
        self,
        user_id: int,
        *,
        platform_admin: bool = False,
    ) -> list[dict]:
        if platform_admin:
            return self.list_organizations()
        membership_ids = {
            item["organization_id"] for item in self.memberships_for_user(user_id)
        }
        return [
            item
            for item in self.list_organizations()
            if item["id"] in membership_ids
        ]

    def member_ids(self, organization_id: int) -> set[int]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT user_id FROM organization_members WHERE organization_id = ?",
                (organization_id,),
            ).fetchall()
        return {int(row["user_id"]) for row in rows}

    def remove_member(self, organization_id: int, user_id: int) -> None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT role FROM organization_members
                WHERE organization_id = ? AND user_id = ?
                """,
                (organization_id, user_id),
            ).fetchone()
            if row is None:
                raise KeyError("Workspace user not found")
            if row["role"] == "owner":
                raise ValueError("Власника workspace не можна видалити")
            connection.execute(
                """
                DELETE FROM organization_members
                WHERE organization_id = ? AND user_id = ?
                """,
                (organization_id, user_id),
            )
            connection.execute(
                """
                UPDATE user_sessions SET selected_organization_id = NULL
                WHERE user_id = ? AND selected_organization_id = ?
                """,
                (user_id, organization_id),
            )

    def role_counts(self, organization_id: int) -> dict[str, int]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT role, COUNT(*) count
                FROM organization_members
                WHERE organization_id = ?
                GROUP BY role
                """,
                (organization_id,),
            ).fetchall()
        return {str(row["role"]): int(row["count"]) for row in rows}

    def save_telegram_connection(
        self,
        organization_id: int,
        *,
        channel_id: str,
        bot_token: str,
        bot_username: str = "",
    ) -> dict:
        encrypted = self.cipher.encrypt(bot_token.strip())
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO telegram_connections (
                    organization_id, channel_id, bot_token_encrypted,
                    bot_username, active, verified_at, updated_at
                ) VALUES (?, ?, ?, ?, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ON CONFLICT(organization_id) DO UPDATE SET
                    channel_id = excluded.channel_id,
                    bot_token_encrypted = excluded.bot_token_encrypted,
                    bot_username = excluded.bot_username,
                    active = 1,
                    verified_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    organization_id,
                    channel_id.strip(),
                    encrypted,
                    bot_username.strip(),
                ),
            )
        return self.telegram_connection(organization_id, include_token=False)

    def telegram_connection(
        self,
        organization_id: int,
        *,
        include_token: bool,
    ) -> dict:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM telegram_connections WHERE organization_id = ?",
                (organization_id,),
            ).fetchone()
        if row is None:
            raise KeyError("Telegram channel is not connected")
        result = dict(row)
        encrypted = result.pop("bot_token_encrypted")
        result["configured"] = bool(encrypted)
        if include_token and encrypted:
            result["bot_token"] = self.cipher.decrypt(encrypted)
        return result

    def save_social_connection(
        self,
        organization_id: int,
        *,
        platform: str,
        external_account_id: str,
        access_token: str,
        username: str = "",
        display_name: str = "",
        account_type: str = "",
        page_id: str = "",
        page_name: str = "",
        token_expires_at: str = "",
        permissions: list[str] | None = None,
        metadata: dict | None = None,
    ) -> dict:
        encrypted = self.cipher.encrypt(access_token.strip())
        permissions_json = json.dumps(permissions or [], ensure_ascii=False)
        metadata_json = json.dumps(metadata or {}, ensure_ascii=False)
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO social_connections (
                    organization_id, platform, external_account_id, username,
                    display_name, account_type, page_id, page_name,
                    access_token_encrypted, token_expires_at, permissions,
                    metadata, active, verified_at, last_error, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, CURRENT_TIMESTAMP, '', CURRENT_TIMESTAMP)
                ON CONFLICT(organization_id, platform) DO UPDATE SET
                    external_account_id = excluded.external_account_id,
                    username = excluded.username,
                    display_name = excluded.display_name,
                    account_type = excluded.account_type,
                    page_id = excluded.page_id,
                    page_name = excluded.page_name,
                    access_token_encrypted = excluded.access_token_encrypted,
                    token_expires_at = excluded.token_expires_at,
                    permissions = excluded.permissions,
                    metadata = excluded.metadata,
                    active = 1,
                    verified_at = CURRENT_TIMESTAMP,
                    last_error = '',
                    updated_at = CURRENT_TIMESTAMP
                RETURNING id
                """,
                (
                    organization_id,
                    platform,
                    external_account_id,
                    username,
                    display_name,
                    account_type,
                    page_id,
                    page_name,
                    encrypted,
                    token_expires_at,
                    permissions_json,
                    metadata_json,
                ),
            )
            connection_id = int(cursor.fetchone()["id"])
        return self.social_connection(connection_id, include_token=False)

    def social_connection_by_platform(
        self,
        organization_id: int,
        platform: str,
        *,
        include_token: bool = False,
        active_only: bool = False,
    ) -> dict:
        with self._connect() as connection:
            query = """
                SELECT * FROM social_connections
                WHERE organization_id = ? AND platform = ?
            """
            params: list[object] = [organization_id, platform]
            if active_only:
                query += " AND active = 1"
            row = connection.execute(query, params).fetchone()
        if row is None:
            raise KeyError(f"{platform} connection is not configured")
        return self._social_connection_row(row, include_token=include_token)

    def social_connection(self, connection_id: int, *, include_token: bool) -> dict:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM social_connections WHERE id = ?",
                (connection_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"Social connection {connection_id} not found")
        return self._social_connection_row(row, include_token=include_token)

    def _social_connection_row(self, row: sqlite3.Row, *, include_token: bool) -> dict:
        result = dict(row)
        encrypted = result.pop("access_token_encrypted")
        result["configured"] = bool(encrypted)
        result["permissions"] = json.loads(result["permissions"] or "[]")
        result["metadata"] = json.loads(result["metadata"] or "{}")
        if include_token and encrypted:
            result["access_token"] = self.cipher.decrypt(encrypted)
        return result

    def disable_social_connection(self, organization_id: int, platform: str) -> dict:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE social_connections
                SET active = 0, updated_at = CURRENT_TIMESTAMP
                WHERE organization_id = ? AND platform = ?
                """,
                (organization_id, platform),
            )
        return self.social_connection_by_platform(
            organization_id,
            platform,
            include_token=False,
        )

    def set_social_connection_error(
        self,
        connection_id: int,
        error: str,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE social_connections
                SET last_error = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (error[:1000], connection_id),
            )

    def create_social_publish_job(
        self,
        *,
        organization_id: int,
        draft_id: int,
        platform: str,
        connection_id: int | None,
        variant_id: int | None,
        media_kind: str = "feed_image",
        scheduled_at: str | None = None,
        status: str = "queued",
        created_by_user_id: int | None = None,
    ) -> dict:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO social_publish_jobs (
                    organization_id, draft_id, platform, connection_id,
                    variant_id, media_kind, scheduled_at, status, created_by_user_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    organization_id,
                    draft_id,
                    platform,
                    connection_id,
                    variant_id,
                    media_kind,
                    scheduled_at,
                    status,
                    created_by_user_id,
                ),
            )
            job_id = int(cursor.lastrowid)
        return self.social_publish_job(job_id)

    def social_publish_job(self, job_id: int) -> dict:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM social_publish_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"Social publish job {job_id} not found")
        return dict(row)

    def list_social_publish_jobs(
        self,
        organization_id: int,
        *,
        draft_id: int | None = None,
        limit: int = 100,
    ) -> list[dict]:
        query = "SELECT * FROM social_publish_jobs WHERE organization_id = ?"
        params: list[object] = [organization_id]
        if draft_id is not None:
            query += " AND draft_id = ?"
            params.append(draft_id)
        query += " ORDER BY created_at DESC, id DESC LIMIT ?"
        params.append(limit)
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def due_social_publish_jobs(self, platform: str = "instagram") -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM social_publish_jobs
                WHERE platform = ?
                  AND status = 'scheduled'
                  AND scheduled_at IS NOT NULL
                  AND scheduled_at <= STRFTIME('%Y-%m-%dT%H:%M:%SZ', 'now')
                ORDER BY scheduled_at, id
                LIMIT 50
                """,
                (platform,),
            ).fetchall()
        return [dict(row) for row in rows]

    def update_social_publish_job(
        self,
        job_id: int,
        *,
        status: str | None = None,
        provider_container_id: str | None = None,
        provider_media_id: str | None = None,
        permalink: str | None = None,
        error: str | None = None,
        increment_attempts: bool = False,
        published: bool = False,
    ) -> dict:
        assignments = ["updated_at = CURRENT_TIMESTAMP"]
        params: list[object] = []
        if status is not None:
            assignments.append("status = ?")
            params.append(status)
        if provider_container_id is not None:
            assignments.append("provider_container_id = ?")
            params.append(provider_container_id)
        if provider_media_id is not None:
            assignments.append("provider_media_id = ?")
            params.append(provider_media_id)
        if permalink is not None:
            assignments.append("permalink = ?")
            params.append(permalink)
        if error is not None:
            assignments.append("error = ?")
            params.append(error[:1000])
        if increment_attempts:
            assignments.append("attempts = attempts + 1")
        if published:
            assignments.append("published_at = CURRENT_TIMESTAMP")
        params.append(job_id)
        with self._connect() as connection:
            connection.execute(
                f"UPDATE social_publish_jobs SET {', '.join(assignments)} WHERE id = ?",
                params,
            )
        return self.social_publish_job(job_id)

    def organization_ids(self) -> list[int]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id FROM organizations WHERE active = 1 ORDER BY id"
            ).fetchall()
        return [int(row["id"]) for row in rows]

    def audit(
        self,
        organization_id: int | None,
        user_id: int | None,
        action: str,
        details: str = "",
        *,
        ip_address: str = "",
        user_agent: str = "",
    ) -> None:
        ip_hash = (
            hashlib.sha256(
                f"{self.hash_salt}:{ip_address.strip()}".encode()
            ).hexdigest()
            if ip_address
            else ""
        )
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO audit_events (
                    organization_id, user_id, action, details,
                    ip_hash, user_agent
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    organization_id,
                    user_id,
                    action,
                    details[:1000],
                    ip_hash,
                    user_agent[:500],
                ),
            )

    def list_audit_events(
        self,
        *,
        limit: int = 500,
        user_id: int | None = None,
        organization_id: int | None = None,
    ) -> list[dict]:
        conditions: list[str] = []
        params: list[object] = []
        if user_id is not None:
            conditions.append("a.user_id = ?")
            params.append(user_id)
        if organization_id is not None:
            conditions.append("a.organization_id = ?")
            params.append(organization_id)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(max(1, min(limit, 2000)))
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT a.*, u.username, u.email, u.display_name,
                    o.name organization_name, o.slug organization_slug
                FROM audit_events a
                LEFT JOIN users u ON u.id = a.user_id
                LEFT JOIN organizations o ON o.id = a.organization_id
                {where}
                ORDER BY a.id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def create_service_update(
        self,
        *,
        title: str,
        body: str = "",
        category: str = "release",
        importance: str = "info",
        status: str = "published",
        pinned: bool = False,
        visible_from: str | None = None,
        visible_until: str | None = None,
        created_by_user_id: int | None = None,
    ) -> dict:
        published_at = "CURRENT_TIMESTAMP" if status == "published" else "NULL"
        with self._connect() as connection:
            cursor = connection.execute(
                f"""
                INSERT INTO service_updates (
                    title, body, category, importance, status, pinned,
                    visible_from, visible_until, created_by_user_id, published_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, {published_at})
                """,
                (
                    title.strip(),
                    body.strip(),
                    category,
                    importance,
                    status,
                    1 if pinned else 0,
                    visible_from,
                    visible_until,
                    created_by_user_id,
                ),
            )
            update_id = int(cursor.lastrowid)
        return self.service_update(update_id)

    def update_service_update(
        self,
        update_id: int,
        *,
        title: str,
        body: str = "",
        category: str = "release",
        importance: str = "info",
        status: str = "published",
        pinned: bool = False,
        visible_from: str | None = None,
        visible_until: str | None = None,
    ) -> dict:
        current = self.service_update(update_id)
        published_at = current.get("published_at")
        if status == "published" and not published_at:
            published_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        if status != "published":
            published_at = None
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE service_updates
                SET title = ?, body = ?, category = ?, importance = ?,
                    status = ?, pinned = ?, visible_from = ?, visible_until = ?,
                    updated_at = CURRENT_TIMESTAMP, published_at = ?
                WHERE id = ?
                """,
                (
                    title.strip(),
                    body.strip(),
                    category,
                    importance,
                    status,
                    1 if pinned else 0,
                    visible_from,
                    visible_until,
                    published_at,
                    update_id,
                ),
            )
        return self.service_update(update_id)

    def service_update(self, update_id: int) -> dict:
        with self._connect() as connection:
            if self._table_exists(connection, "users"):
                select = """
                    SELECT su.*, u.username created_by_username,
                        u.display_name created_by_display_name
                    FROM service_updates su
                    LEFT JOIN users u ON u.id = su.created_by_user_id
                    WHERE su.id = ?
                    """
            else:
                select = """
                    SELECT su.*, '' created_by_username,
                        '' created_by_display_name
                    FROM service_updates su
                    WHERE su.id = ?
                    """
            row = connection.execute(
                select,
                (update_id,),
            ).fetchone()
        if row is None:
            raise KeyError("Service update not found")
        return dict(row)

    def list_service_updates(
        self,
        *,
        limit: int = 50,
        include_drafts: bool = False,
    ) -> list[dict]:
        conditions = []
        if not include_drafts:
            conditions.extend(
                [
                    "su.status = 'published'",
                    "(su.visible_from IS NULL OR su.visible_from <= CURRENT_TIMESTAMP)",
                    "(su.visible_until IS NULL OR su.visible_until >= CURRENT_TIMESTAMP)",
                ]
            )
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        with self._connect() as connection:
            if self._table_exists(connection, "users"):
                select = """
                    SELECT su.*, u.username created_by_username,
                        u.display_name created_by_display_name
                    FROM service_updates su
                    LEFT JOIN users u ON u.id = su.created_by_user_id
                    """
            else:
                select = """
                    SELECT su.*, '' created_by_username,
                        '' created_by_display_name
                    FROM service_updates su
                    """
            rows = connection.execute(
                f"""
                {select}
                {where}
                ORDER BY su.pinned DESC,
                    COALESCE(su.published_at, su.created_at) DESC,
                    su.id DESC
                LIMIT ?
                """,
                (max(1, min(limit, 200)),),
            ).fetchall()
        return [dict(row) for row in rows]

    def last_activity_by_organization(self) -> dict[int, str]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT organization_id, MAX(created_at) last_activity_at
                FROM audit_events
                WHERE organization_id IS NOT NULL
                GROUP BY organization_id
                """
            ).fetchall()
        return {
            int(row["organization_id"]): row["last_activity_at"]
            for row in rows
        }

    def create_billing_order(
        self,
        *,
        organization_id: int,
        user_id: int,
        plan_code: str,
        amount_stars: int,
        payload: str,
    ) -> dict:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO billing_orders (
                    organization_id, user_id, plan_code, amount_stars, payload
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (organization_id, user_id, plan_code, amount_stars, payload),
            )
            order_id = int(cursor.lastrowid)
        return self.billing_order(order_id)

    def billing_order(self, order_id: int) -> dict:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM billing_orders WHERE id = ?",
                (order_id,),
            ).fetchone()
        if row is None:
            raise KeyError("Billing order not found")
        return dict(row)

    def billing_order_by_payload(self, payload: str) -> dict | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM billing_orders WHERE payload = ?",
                (payload,),
            ).fetchone()
        return dict(row) if row else None

    def complete_star_payment(
        self,
        *,
        order_id: int,
        telegram_user_id: int | None,
        telegram_payment_charge_id: str,
        amount_stars: int,
        plan: dict,
        expires_at: datetime,
        raw: str,
    ) -> bool:
        order = self.billing_order(order_id)
        with self._connect() as connection:
            existing = connection.execute(
                """
                SELECT id FROM star_payments
                WHERE telegram_payment_charge_id = ?
                """,
                (telegram_payment_charge_id,),
            ).fetchone()
            if existing:
                return False
            connection.execute(
                """
                INSERT INTO star_payments (
                    order_id, organization_id, telegram_user_id,
                    telegram_payment_charge_id, amount_stars, raw
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    order_id,
                    order["organization_id"],
                    telegram_user_id,
                    telegram_payment_charge_id,
                    amount_stars,
                    raw[:10000],
                ),
            )
            connection.execute(
                """
                UPDATE billing_orders
                SET status = 'paid', paid_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (order_id,),
            )
            connection.execute(
                """
                UPDATE organizations
                SET plan_code = ?, plan_expires_at = ?, max_users = ?,
                    max_channels = ?, monthly_publications = ?,
                    monthly_ai_budget = ?
                WHERE id = ?
                """,
                (
                    plan["code"],
                    expires_at.isoformat(),
                    plan["users"],
                    plan["channels"],
                    plan["publications"],
                    plan["ai_budget"],
                    order["organization_id"],
                ),
            )
        self.audit(
            order["organization_id"],
            order["user_id"],
            "billing.stars_paid",
            f"{plan['code']}:{amount_stars}",
        )
        return True
