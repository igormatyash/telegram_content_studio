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
            for column, definition in {
                "email": "TEXT",
                "google_subject": "TEXT",
                "display_name": "TEXT NOT NULL DEFAULT ''",
                "avatar_url": "TEXT NOT NULL DEFAULT ''",
            }.items():
                if column not in columns:
                    connection.execute(
                        f"ALTER TABLE users ADD COLUMN {column} {definition}"
                    )
            connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email "
                "ON users(email COLLATE NOCASE) WHERE email IS NOT NULL"
            )
            connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_google_subject "
                "ON users(google_subject) WHERE google_subject IS NOT NULL"
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
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS auth_action_tokens (
                    token_hash TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    user_id INTEGER,
                    organization_id INTEGER,
                    email TEXT,
                    role TEXT,
                    expires_at TEXT NOT NULL,
                    used_at TEXT,
                    created_by_user_id INTEGER,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_auth_action_tokens_lookup
                    ON auth_action_tokens(kind, expires_at, used_at);
                CREATE TABLE IF NOT EXISTS oauth_states (
                    state_hash TEXT PRIMARY KEY,
                    invite_token_hash TEXT,
                    expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
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
        email: str | None = None,
        google_subject: str | None = None,
        display_name: str = "",
        avatar_url: str = "",
    ) -> dict:
        normalized = username.strip()
        normalized_email = email.strip().lower() if email else None
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO users (
                    username, password_hash, is_admin, email, google_subject,
                    display_name, avatar_url
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    normalized,
                    hash_password(password),
                    int(is_admin),
                    normalized_email,
                    google_subject,
                    display_name.strip(),
                    avatar_url.strip(),
                ),
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
                SELECT id, username, is_admin, is_super_admin, active, created_at,
                    email, google_subject, display_name, avatar_url
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
                        u.active, u.created_at, u.email, u.google_subject,
                        u.display_name, u.avatar_url
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
                    SELECT id, username, is_admin, is_super_admin, active, created_at,
                        email, google_subject, display_name, avatar_url
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
                    u.active, u.created_at, u.email, u.google_subject,
                    u.display_name, u.avatar_url, s.selected_organization_id
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
                        u.active, u.created_at, u.email, u.google_subject,
                        u.display_name, u.avatar_url
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

    def find_by_email(self, email: str) -> dict | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, username, is_admin, is_super_admin, active, created_at,
                    email, google_subject, display_name, avatar_url
                FROM users WHERE email = ? COLLATE NOCASE
                """,
                (email.strip(),),
            ).fetchone()
        return self._public_user(row) if row else None

    def find_by_google_subject(self, subject: str) -> dict | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, username, is_admin, is_super_admin, active, created_at,
                    email, google_subject, display_name, avatar_url
                FROM users WHERE google_subject = ?
                """,
                (subject,),
            ).fetchone()
        return self._public_user(row) if row else None

    def link_google_identity(
        self,
        user_id: int,
        *,
        subject: str,
        email: str,
        display_name: str,
        avatar_url: str,
    ) -> dict:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE users
                SET google_subject = ?, email = ?, display_name = ?, avatar_url = ?
                WHERE id = ?
                """,
                (
                    subject,
                    email.strip().lower(),
                    display_name.strip(),
                    avatar_url.strip(),
                    user_id,
                ),
            )
        return self.get_user(user_id)

    def create_action_token(
        self,
        kind: str,
        *,
        user_id: int | None = None,
        organization_id: int | None = None,
        email: str | None = None,
        role: str | None = None,
        created_by_user_id: int | None = None,
        lifetime_hours: int = 24,
    ) -> str:
        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        expires_at = datetime.now(timezone.utc) + timedelta(hours=lifetime_hours)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO auth_action_tokens (
                    token_hash, kind, user_id, organization_id, email, role,
                    expires_at, created_by_user_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    token_hash,
                    kind,
                    user_id,
                    organization_id,
                    email.strip().lower() if email else None,
                    role,
                    expires_at.isoformat(),
                    created_by_user_id,
                ),
            )
        return token

    def action_token(self, token: str, kind: str) -> dict | None:
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        return self.action_token_hash(token_hash, kind)

    def action_token_hash(self, token_hash: str, kind: str) -> dict | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM auth_action_tokens
                WHERE token_hash = ? AND kind = ? AND used_at IS NULL
                    AND expires_at > ?
                """,
                (token_hash, kind, datetime.now(timezone.utc).isoformat()),
            ).fetchone()
        return dict(row) if row else None

    def consume_action_token(self, token: str, kind: str) -> dict:
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        return self.consume_action_token_hash(token_hash, kind)

    def consume_action_token_hash(self, token_hash: str, kind: str) -> dict:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM auth_action_tokens
                WHERE token_hash = ? AND kind = ? AND used_at IS NULL
                    AND expires_at > ?
                """,
                (token_hash, kind, datetime.now(timezone.utc).isoformat()),
            ).fetchone()
            if row is None:
                raise KeyError("Token is invalid or expired")
            connection.execute(
                "UPDATE auth_action_tokens SET used_at = ? WHERE token_hash = ?",
                (datetime.now(timezone.utc).isoformat(), token_hash),
            )
        return dict(row)

    def create_oauth_state(
        self,
        invite_token: str | None = None,
        *,
        lifetime_minutes: int = 10,
    ) -> str:
        state = secrets.token_urlsafe(32)
        state_hash = hashlib.sha256(state.encode()).hexdigest()
        invite_hash = (
            hashlib.sha256(invite_token.encode()).hexdigest()
            if invite_token
            else None
        )
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=lifetime_minutes)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO oauth_states (state_hash, invite_token_hash, expires_at)
                VALUES (?, ?, ?)
                """,
                (state_hash, invite_hash, expires_at.isoformat()),
            )
        return state

    def consume_oauth_state(self, state: str) -> dict:
        state_hash = hashlib.sha256(state.encode()).hexdigest()
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM oauth_states
                WHERE state_hash = ? AND expires_at > ?
                """,
                (state_hash, datetime.now(timezone.utc).isoformat()),
            ).fetchone()
            if row is None:
                raise KeyError("OAuth state is invalid or expired")
            connection.execute(
                "DELETE FROM oauth_states WHERE state_hash = ?",
                (state_hash,),
            )
        return dict(row)

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
            "email": row["email"],
            "display_name": row["display_name"] or row["username"],
            "avatar_url": row["avatar_url"] or "",
            "google_connected": bool(row["google_subject"]),
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
