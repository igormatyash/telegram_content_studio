import hashlib
import secrets
import sqlite3
from pathlib import Path


class ReferralRepository:
    def __init__(self, database_path: Path, hash_salt: str) -> None:
        self.database_path = database_path
        self.hash_salt = hash_salt
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
                CREATE TABLE IF NOT EXISTS referral_codes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    owner_user_id INTEGER NOT NULL,
                    owner_organization_id INTEGER,
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(owner_user_id) REFERENCES users(id) ON DELETE CASCADE,
                    FOREIGN KEY(owner_organization_id) REFERENCES organizations(id)
                );
                CREATE INDEX IF NOT EXISTS idx_referral_codes_owner
                    ON referral_codes(owner_user_id, owner_organization_id, status);
                CREATE TABLE IF NOT EXISTS referral_clicks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    referral_code TEXT NOT NULL,
                    ip_hash TEXT NOT NULL DEFAULT '',
                    user_agent TEXT NOT NULL DEFAULT '',
                    utm_source TEXT NOT NULL DEFAULT '',
                    utm_medium TEXT NOT NULL DEFAULT '',
                    utm_campaign TEXT NOT NULL DEFAULT '',
                    landing_url TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(referral_code) REFERENCES referral_codes(code)
                );
                CREATE INDEX IF NOT EXISTS idx_referral_clicks_code
                    ON referral_clicks(referral_code, created_at);
                CREATE TABLE IF NOT EXISTS referral_signups (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    referral_code TEXT NOT NULL,
                    referrer_user_id INTEGER NOT NULL,
                    referrer_organization_id INTEGER,
                    new_user_id INTEGER NOT NULL UNIQUE,
                    new_organization_id INTEGER,
                    click_id INTEGER,
                    utm_source TEXT NOT NULL DEFAULT '',
                    utm_medium TEXT NOT NULL DEFAULT '',
                    utm_campaign TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(referral_code) REFERENCES referral_codes(code),
                    FOREIGN KEY(referrer_user_id) REFERENCES users(id),
                    FOREIGN KEY(referrer_organization_id) REFERENCES organizations(id),
                    FOREIGN KEY(new_user_id) REFERENCES users(id) ON DELETE CASCADE,
                    FOREIGN KEY(new_organization_id) REFERENCES organizations(id),
                    FOREIGN KEY(click_id) REFERENCES referral_clicks(id)
                );
                CREATE INDEX IF NOT EXISTS idx_referral_signups_code
                    ON referral_signups(referral_code, created_at);
                """
            )

    def _new_code(self) -> str:
        return secrets.token_urlsafe(9).replace("-", "").replace("_", "")[:12].lower()

    def _ip_hash(self, ip_address: str) -> str:
        value = f"{self.hash_salt}:{ip_address.strip()}".encode()
        return hashlib.sha256(value).hexdigest() if ip_address else ""

    def code(self, value: str, *, active_only: bool = False) -> dict | None:
        query = "SELECT * FROM referral_codes WHERE code = ? COLLATE NOCASE"
        params: list[object] = [value.strip()]
        if active_only:
            query += " AND status = 'active'"
        with self._connect() as connection:
            row = connection.execute(query, params).fetchone()
        return dict(row) if row else None

    def code_for_owner(
        self,
        owner_user_id: int,
        owner_organization_id: int | None,
        *,
        create: bool = True,
    ) -> dict | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM referral_codes
                WHERE owner_user_id = ?
                  AND (
                    owner_organization_id = ?
                    OR (owner_organization_id IS NULL AND ? IS NULL)
                  )
                ORDER BY id DESC
                LIMIT 1
                """,
                (owner_user_id, owner_organization_id, owner_organization_id),
            ).fetchone()
        if row or not create:
            return dict(row) if row else None
        return self.rotate(owner_user_id, owner_organization_id)

    def rotate(
        self,
        owner_user_id: int,
        owner_organization_id: int | None,
    ) -> dict:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE referral_codes
                SET status = 'disabled', updated_at = CURRENT_TIMESTAMP
                WHERE owner_user_id = ?
                  AND (
                    owner_organization_id = ?
                    OR (owner_organization_id IS NULL AND ? IS NULL)
                  )
                  AND status = 'active'
                """,
                (owner_user_id, owner_organization_id, owner_organization_id),
            )
            while True:
                code = self._new_code()
                try:
                    cursor = connection.execute(
                        """
                        INSERT INTO referral_codes (
                            code, owner_user_id, owner_organization_id
                        ) VALUES (?, ?, ?)
                        """,
                        (code, owner_user_id, owner_organization_id),
                    )
                    referral_id = int(cursor.lastrowid)
                    break
                except sqlite3.IntegrityError:
                    continue
            row = connection.execute(
                "SELECT * FROM referral_codes WHERE id = ?",
                (referral_id,),
            ).fetchone()
        return dict(row)

    def disable(
        self,
        owner_user_id: int,
        owner_organization_id: int | None,
    ) -> dict:
        referral = self.code_for_owner(
            owner_user_id,
            owner_organization_id,
            create=False,
        )
        if referral is None:
            raise KeyError("Referral code not found")
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE referral_codes
                SET status = 'disabled', updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND owner_user_id = ?
                """,
                (referral["id"], owner_user_id),
            )
        return self.code(referral["code"]) or referral

    def set_codes_status(self, code_ids: list[int], status: str) -> int:
        if status not in {"active", "disabled"}:
            raise ValueError("Unsupported referral status")
        if not code_ids:
            return 0
        placeholders = ",".join("?" for _ in code_ids)
        with self._connect() as connection:
            cursor = connection.execute(
                f"""
                UPDATE referral_codes
                SET status = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id IN ({placeholders})
                """,
                (status, *code_ids),
            )
        return int(cursor.rowcount)

    def record_click(
        self,
        code: str,
        *,
        ip_address: str,
        user_agent: str,
        utm_source: str = "",
        utm_medium: str = "",
        utm_campaign: str = "",
        landing_url: str = "",
    ) -> dict:
        referral = self.code(code, active_only=True)
        if referral is None:
            raise KeyError("Referral code not found")
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO referral_clicks (
                    referral_code, ip_hash, user_agent, utm_source,
                    utm_medium, utm_campaign, landing_url
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    referral["code"],
                    self._ip_hash(ip_address),
                    user_agent[:500],
                    utm_source[:120],
                    utm_medium[:120],
                    utm_campaign[:200],
                    landing_url[:1000],
                ),
            )
            row = connection.execute(
                "SELECT * FROM referral_clicks WHERE id = ?",
                (int(cursor.lastrowid),),
            ).fetchone()
        return dict(row)

    def complete_signup(
        self,
        code: str,
        *,
        new_user_id: int,
        new_organization_id: int | None,
        click_id: int | None = None,
    ) -> dict:
        referral = self.code(code, active_only=True)
        if referral is None:
            raise KeyError("Referral code not found")
        if int(referral["owner_user_id"]) == new_user_id:
            raise ValueError("A user cannot use their own referral link")
        with self._connect() as connection:
            click = None
            if click_id is not None:
                click = connection.execute(
                    """
                    SELECT * FROM referral_clicks
                    WHERE id = ? AND referral_code = ? COLLATE NOCASE
                    """,
                    (click_id, referral["code"]),
                ).fetchone()
            cursor = connection.execute(
                """
                INSERT INTO referral_signups (
                    referral_code, referrer_user_id,
                    referrer_organization_id, new_user_id,
                    new_organization_id, click_id, utm_source,
                    utm_medium, utm_campaign
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    referral["code"],
                    referral["owner_user_id"],
                    referral["owner_organization_id"],
                    new_user_id,
                    new_organization_id,
                    click["id"] if click else None,
                    click["utm_source"] if click else "",
                    click["utm_medium"] if click else "",
                    click["utm_campaign"] if click else "",
                ),
            )
            connection.execute(
                "UPDATE users SET referred_by_user_id = ? WHERE id = ?",
                (referral["owner_user_id"], new_user_id),
            )
            if new_organization_id is not None:
                connection.execute(
                    """
                    UPDATE organizations
                    SET referred_by_organization_id = ?
                    WHERE id = ?
                    """,
                    (referral["owner_organization_id"], new_organization_id),
                )
            row = connection.execute(
                "SELECT * FROM referral_signups WHERE id = ?",
                (int(cursor.lastrowid),),
            ).fetchone()
        return dict(row)

    def owner_summary(
        self,
        owner_user_id: int,
        owner_organization_id: int | None,
    ) -> dict:
        referral = self.code_for_owner(
            owner_user_id,
            owner_organization_id,
        )
        with self._connect() as connection:
            stats = connection.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM referral_clicks
                     WHERE referral_code = ?) clicks,
                    (SELECT COUNT(*) FROM referral_signups
                     WHERE referral_code = ?) signups,
                    (SELECT COUNT(*)
                     FROM referral_signups rs
                     JOIN users u ON u.id = rs.new_user_id
                     WHERE rs.referral_code = ? AND u.active = 1) active_clients
                """,
                (referral["code"], referral["code"], referral["code"]),
            ).fetchone()
        return {**referral, **dict(stats)}

    def platform_summary(self) -> dict:
        with self._connect() as connection:
            codes = connection.execute(
                """
                SELECT rc.*, u.username owner_username,
                    u.display_name owner_display_name,
                    o.name owner_organization_name,
                    COUNT(DISTINCT c.id) clicks,
                    COUNT(DISTINCT s.id) signups,
                    COUNT(DISTINCT s.new_organization_id) organizations_created,
                    MAX(s.created_at) last_signup_at
                FROM referral_codes rc
                JOIN users u ON u.id = rc.owner_user_id
                LEFT JOIN organizations o ON o.id = rc.owner_organization_id
                LEFT JOIN referral_clicks c ON c.referral_code = rc.code
                LEFT JOIN referral_signups s ON s.referral_code = rc.code
                GROUP BY rc.id
                ORDER BY rc.id DESC
                """
            ).fetchall()
            signups = connection.execute(
                """
                SELECT rs.*, invited.username new_username,
                    invited.email new_email, invited.active new_user_active,
                    invited_by.username referrer_username,
                    o.name new_organization_name
                FROM referral_signups rs
                JOIN users invited ON invited.id = rs.new_user_id
                JOIN users invited_by ON invited_by.id = rs.referrer_user_id
                LEFT JOIN organizations o ON o.id = rs.new_organization_id
                ORDER BY rs.id DESC
                """
            ).fetchall()
        return {
            "codes": [dict(row) for row in codes],
            "signups": [dict(row) for row in signups],
        }
