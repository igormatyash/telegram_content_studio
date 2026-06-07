import argparse
import sqlite3
from pathlib import Path

from voicerhub_bot.auth import hash_password


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("username")
    parser.add_argument("password")
    parser.add_argument(
        "--database",
        type=Path,
        default=Path("data/voicerhub_bot.sqlite3"),
    )
    args = parser.parse_args()

    with sqlite3.connect(args.database) as connection:
        cursor = connection.execute(
            """
            UPDATE users
            SET password_hash = ?, active = 1, is_admin = 1
            WHERE username = ? COLLATE NOCASE
            """,
            (hash_password(args.password), args.username),
        )
        if cursor.rowcount != 1:
            raise SystemExit(f"User {args.username!r} was not found")
        connection.execute(
            """
            DELETE FROM user_sessions
            WHERE user_id = (
                SELECT id FROM users WHERE username = ? COLLATE NOCASE
            )
            """,
            (args.username,),
        )


if __name__ == "__main__":
    main()
