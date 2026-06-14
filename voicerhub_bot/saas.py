import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken


ROLES = {"owner", "admin", "editor", "viewer"}


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
    def __init__(self, database_path: Path, encryption_key: str = "") -> None:
        self.database_path = database_path
        self.cipher = SecretCipher(encryption_key)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS organizations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
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
            self._ensure_column(
                connection,
                "organizations",
                "referred_by_organization_id",
                "INTEGER",
            )

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
        return self.get_organization(1)

    def create_organization(
        self,
        *,
        name: str,
        slug: str,
        max_users: int,
        max_channels: int,
        monthly_publications: int,
        monthly_ai_budget: float,
    ) -> dict:
        normalized = re.sub(r"[^a-z0-9-]+", "-", slug.lower()).strip("-")
        if not normalized:
            raise ValueError("Organization slug is required")
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO organizations (
                    name, slug, max_users, max_channels,
                    monthly_publications, monthly_ai_budget
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
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

    def create_trial_organization(self, *, name: str, slug: str) -> dict:
        organization = self.create_organization(
            name=name,
            slug=slug,
            max_users=3,
            max_channels=1,
            monthly_publications=30,
            monthly_ai_budget=8,
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
        normalized = re.sub(r"[^a-z0-9-]+", "-", slug.lower()).strip("-")
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
            "brand_logo_asset_id",
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
                    COUNT(DISTINCT m.user_id) user_count,
                    COUNT(DISTINCT CASE WHEN tc.active = 1 THEN tc.organization_id END)
                        channel_count
                FROM organizations o
                LEFT JOIN organization_members m ON m.organization_id = o.id
                LEFT JOIN telegram_connections tc ON tc.organization_id = o.id
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

    def upsert_member(self, organization_id: int, user_id: int, role: str) -> None:
        if role not in ROLES:
            raise ValueError("Unsupported organization role")
        existing = self.role_for_user(organization_id, user_id)
        if existing:
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
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO audit_events (organization_id, user_id, action, details)
                VALUES (?, ?, ?, ?)
                """,
                (organization_id, user_id, action, details[:1000]),
            )

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
