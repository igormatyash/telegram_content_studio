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
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS user_sessions (
                    token_hash TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
                )
                """
            )

    def ensure_bootstrap_admin(self, username: str, password: str) -> None:
        with self._connect() as connection:
            count = connection.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        if count == 0:
            if not password:
                raise RuntimeError("ADMIN_PASSWORD is required for the first administrator")
            self.create_user(username, password, is_admin=True)

    def create_user(self, username: str, password: str, *, is_admin: bool) -> dict:
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
        return self.get_user(user_id)

    def get_user(self, user_id: int) -> dict:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, username, is_admin, active, created_at
                FROM users WHERE id = ?
                """,
                (user_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"User {user_id} not found")
        return self._public_user(row)

    def list_users(self) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, username, is_admin, active, created_at
                FROM users ORDER BY username COLLATE NOCASE
                """
            ).fetchall()
        return [self._public_user(row) for row in rows]

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
            connection.execute(
                """
                INSERT INTO user_sessions (token_hash, user_id, expires_at)
                VALUES (?, ?, ?)
                """,
                (token_hash, user_id, expires.isoformat()),
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
                SELECT u.id, u.username, u.is_admin, u.active, u.created_at
                FROM user_sessions s
                JOIN users u ON u.id = s.user_id
                WHERE s.token_hash = ? AND s.expires_at > ? AND u.active = 1
                """,
                (token_hash, now),
            ).fetchone()
        return self._public_user(row) if row else None

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
    ) -> dict:
        assignments: list[str] = []
        values: list[object] = []
        if is_admin is not None:
            assignments.append("is_admin = ?")
            values.append(int(is_admin))
        if active is not None:
            assignments.append("active = ?")
            values.append(int(active))
        if assignments:
            values.append(user_id)
            with self._connect() as connection:
                connection.execute(
                    f"UPDATE users SET {', '.join(assignments)} WHERE id = ?",
                    values,
                )
                if active is False:
                    connection.execute(
                        "DELETE FROM user_sessions WHERE user_id = ?", (user_id,)
                    )
        return self.get_user(user_id)

    def set_password(self, user_id: int, password: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE users SET password_hash = ? WHERE id = ?",
                (hash_password(password), user_id),
            )
            connection.execute(
                "DELETE FROM user_sessions WHERE user_id = ?", (user_id,)
            )

    @staticmethod
    def _public_user(row: sqlite3.Row) -> dict:
        return {
            "id": row["id"],
            "username": row["username"],
            "is_admin": bool(row["is_admin"]),
            "active": bool(row["active"]),
            "created_at": row["created_at"],
        }
