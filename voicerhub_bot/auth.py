import hashlib
import hmac
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path


SESSION_DAYS = 30


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode(),
        salt=salt,
        n=2**14,
        r=8,
        p=1,
        dklen=32,
    )
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, salt_hex, digest_hex = encoded.split("$", 2)
        if algorithm != "scrypt":
            return False
        digest = hashlib.scrypt(
            password.encode(),
            salt=bytes.fromhex(salt_hex),
            n=2**14,
            r=8,
            p=1,
            dklen=32,
        )
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


class AuthRepository:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    password_hash TEXT NOT NULL,
                    is_admin INTEGER NOT NULL DEFAULT 0,
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(users)").fetchall()
            }
            if "is_super_admin" not in columns:
                connection.execute(
                    "ALTER TABLE users ADD COLUMN is_super_admin INTEGER NOT NULL DEFAULT 0"
                )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS user_sessions (
                    token_hash TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    selected_organization_id INTEGER,
                    expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
                )
                """
            )
            session_columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(user_sessions)"
                ).fetchall()
            }
            if "selected_organization_id" not in session_columns:
                connection.execute(
                    "ALTER TABLE user_sessions "
                    "ADD COLUMN selected_organization_id INTEGER"
                )
            connection.execute(
                """
                UPDATE users
                SET is_super_admin = 1
                WHERE id = (
                    SELECT id FROM users
                    WHERE is_admin = 1
                    ORDER BY id
                    LIMIT 1
                )
                  AND NOT EXISTS (
                    SELECT 1 FROM users WHERE is_super_admin = 1
                )
                """
            )

    def ensure_bootstrap_admin(self, username: str, password: str) -> None:
        with self._connect() as connection:
            count = connection.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        if count == 0:
            if not password:
                raise RuntimeError("ADMIN_PASSWORD is required for the first administrator")
            user = self.create_user(username, password, is_admin=True)
            with self._connect() as connection:
                connection.execute(
                    "UPDATE users SET is_super_admin = 1 WHERE id = ?",
                    (user["id"],),
                )

    def create_user(
        self,
        username: str,
        password: str,
        *,
        is_admin: bool,
        organization_id: int | None = None,
        role: str | None = None,
    ) -> dict:
        normalized = username.strip()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO users (username, password_hash, is_admin)
                VALUES (?, ?, ?)
                """,
                (normalized, hash_password(password), int(is_admin)),
            )
            user_id = int(cursor.lastrowid)
            if organization_id is not None and self._table_exists(
                connection, "organization_members"
            ):
                connection.execute(
                    """
                    INSERT INTO organization_members (organization_id, user_id, role)
                    VALUES (?, ?, ?)
                    """,
                    (
                        organization_id,
                        user_id,
                        role or ("admin" if is_admin else "editor"),
                    ),
                )
        return self.get_user(user_id)

    def get_user(self, user_id: int) -> dict:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, username, is_admin, is_super_admin, active, created_at
                FROM users WHERE id = ?
                """,
                (user_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"User {user_id} not found")
        return self._public_user(row)

    def list_users(self, organization_id: int | None = None) -> list[dict]:
        with self._connect() as connection:
            if organization_id is not None and self._table_exists(
                connection, "organization_members"
            ):
                rows = connection.execute(
                    """
                    SELECT u.id, u.username, u.is_admin, u.is_super_admin,
                        u.active, u.created_at
                    FROM users u
                    JOIN organization_members m ON m.user_id = u.id
                    WHERE m.organization_id = ?
                    ORDER BY u.username COLLATE NOCASE
                    """,
                    (organization_id,),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT id, username, is_admin, is_super_admin, active, created_at
                    FROM users ORDER BY username COLLATE NOCASE
                    """
                ).fetchall()
        return [
            self._public_user(
                row,
                selected_organization_id=organization_id,
            )
            for row in rows
        ]

    def authenticate(self, username: str, password: str) -> dict | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM users WHERE username = ? COLLATE NOCASE",
                (username.strip(),),
            ).fetchone()
        if row is None or not row["active"]:
            return None
        if not verify_password(password, row["password_hash"]):
            return None
        return self._public_user(row)

    def create_session(self, user_id: int) -> str:
        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        expires = datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM user_sessions WHERE expires_at <= ?",
                (datetime.now(timezone.utc).isoformat(),),
            )
            membership = None
            if self._table_exists(connection, "organization_members"):
                membership = connection.execute(
                    """
                    SELECT organization_id
                    FROM organization_members
                    WHERE user_id = ?
                    ORDER BY organization_id
                    LIMIT 1
                    """,
                    (user_id,),
                ).fetchone()
            connection.execute(
                """
                INSERT INTO user_sessions (
                    token_hash, user_id, selected_organization_id, expires_at
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    token_hash,
                    user_id,
                    membership["organization_id"] if membership else None,
                    expires.isoformat(),
                ),
            )
        return token

    def session_user(self, token: str | None) -> dict | None:
        if not token:
            return None
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT u.id, u.username, u.is_admin, u.is_super_admin,
                    u.active, u.created_at, s.selected_organization_id
                FROM user_sessions s
                JOIN users u ON u.id = s.user_id
                WHERE s.token_hash = ? AND s.expires_at > ? AND u.active = 1
                """,
                (token_hash, now),
            ).fetchone()
        return self._public_user(
            row,
            selected_organization_id=(
                row["selected_organization_id"] if row else None
            ),
        ) if row else None

    def select_session_organization(
        self,
        token: str | None,
        organization_id: int,
    ) -> None:
        if not token:
            raise KeyError("Session not found")
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        with self._connect() as connection:
            session = connection.execute(
                """
                SELECT s.user_id, u.is_super_admin
                FROM user_sessions s
                JOIN users u ON u.id = s.user_id
                WHERE s.token_hash = ?
                """,
                (token_hash,),
            ).fetchone()
            if session is None:
                raise KeyError("Session not found")
            allowed = bool(session["is_super_admin"])
            if not allowed:
                allowed = connection.execute(
                    """
                    SELECT 1 FROM organization_members
                    WHERE user_id = ? AND organization_id = ?
                    """,
                    (session["user_id"], organization_id),
                ).fetchone() is not None
            organization_exists = connection.execute(
                "SELECT 1 FROM organizations WHERE id = ? AND active = 1",
                (organization_id,),
            ).fetchone()
            if not allowed or organization_exists is None:
                raise KeyError("Organization not found")
            connection.execute(
                """
                UPDATE user_sessions
                SET selected_organization_id = ?
                WHERE token_hash = ?
                """,
                (organization_id, token_hash),
            )

    def delete_session(self, token: str | None) -> None:
        if not token:
            return
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM user_sessions WHERE token_hash = ?",
                (hashlib.sha256(token.encode()).hexdigest(),),
            )

    def update_user(
        self,
        user_id: int,
        *,
        is_admin: bool | None = None,
        active: bool | None = None,
        organization_id: int | None = None,
        role: str | None = None,
    ) -> dict:
        assignments: list[str] = []
        values: list[object] = []
        if is_admin is not None:
            assignments.append("is_admin = ?")
            values.append(int(is_admin))
        if active is not None:
            assignments.append("active = ?")
            values.append(int(active))
        membership_role = role
        if membership_role is None and is_admin is not None:
            membership_role = "admin" if is_admin else "editor"
        if assignments or membership_role is not None or active is False:
            with self._connect() as connection:
                if assignments:
                    values.append(user_id)
                    connection.execute(
                        f"UPDATE users SET {', '.join(assignments)} WHERE id = ?",
                        values,
                    )
                if membership_role is not None and self._table_exists(
                    connection, "organization_members"
                ):
                    if organization_id is None:
                        raise ValueError("organization_id is required for role updates")
                    connection.execute(
                        """
                        UPDATE organization_members
                        SET role = CASE WHEN role = 'owner' THEN role ELSE ? END
                        WHERE user_id = ? AND organization_id = ?
                        """,
                        (membership_role, user_id, organization_id),
                    )
                if active is False:
                    connection.execute(
                        "DELETE FROM user_sessions WHERE user_id = ?", (user_id,)
                    )
        user = self.get_user(user_id)
        if organization_id is not None:
            with self._connect() as connection:
                row = connection.execute(
                    """
                    SELECT u.id, u.username, u.is_admin, u.is_super_admin,
                        u.active, u.created_at
                    FROM users u WHERE u.id = ?
                    """,
                    (user_id,),
                ).fetchone()
            return self._public_user(
                row,
                selected_organization_id=organization_id,
            )
        return user

    def set_password(self, user_id: int, password: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE users SET password_hash = ? WHERE id = ?",
                (hash_password(password), user_id),
            )
            connection.execute(
                "DELETE FROM user_sessions WHERE user_id = ?", (user_id,)
            )

    def _public_user(
        self,
        row: sqlite3.Row,
        selected_organization_id: int | None = None,
    ) -> dict:
        user = {
            "id": row["id"],
            "username": row["username"],
            "is_admin": bool(row["is_admin"]),
            "is_super_admin": bool(row["is_super_admin"]),
            "active": bool(row["active"]),
            "created_at": row["created_at"],
        }
        with self._connect() as connection:
            if self._table_exists(connection, "organization_members"):
                if selected_organization_id is None:
                    membership = connection.execute(
                        """
                        SELECT m.organization_id, m.role,
                            o.name organization_name, o.slug organization_slug
                        FROM organization_members m
                        JOIN organizations o ON o.id = m.organization_id
                        WHERE m.user_id = ? AND o.active = 1
                        ORDER BY m.organization_id
                        LIMIT 1
                        """,
                        (row["id"],),
                    ).fetchone()
                else:
                    membership = connection.execute(
                        """
                        SELECT o.id organization_id,
                            COALESCE(m.role, 'platform_admin') role,
                            o.name organization_name, o.slug organization_slug
                        FROM organizations o
                        LEFT JOIN organization_members m
                          ON m.organization_id = o.id AND m.user_id = ?
                        WHERE o.id = ? AND o.active = 1
                          AND (m.user_id IS NOT NULL OR ? = 1)
                        """,
                        (
                            row["id"],
                            selected_organization_id,
                            int(bool(row["is_super_admin"])),
                        ),
                    ).fetchone()
                if membership:
                    user.update(dict(membership))
                    user["is_admin"] = membership["role"] in {
                        "platform_admin",
                        "owner",
                        "admin",
                    }
        return user

    @staticmethod
    def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
        return (
            connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                (table,),
            ).fetchone()
            is not None
        )
