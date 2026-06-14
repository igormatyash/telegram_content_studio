from voicerhub_bot.auth import AuthRepository, hash_password, verify_password


def test_password_hash_is_salted_and_verifiable() -> None:
    first = hash_password("strong-password")
    second = hash_password("strong-password")

    assert first != second
    assert verify_password("strong-password", first)
    assert not verify_password("wrong-password", first)


def test_password_change_invalidates_sessions(tmp_path) -> None:
    repository = AuthRepository(tmp_path / "auth.sqlite3")
    user = repository.create_user("admin", "first-password", is_admin=True)
    token = repository.create_session(user["id"])

    assert repository.session_user(token)["username"] == "admin"
    repository.set_password(user["id"], "second-password")

    assert repository.session_user(token) is None
    assert repository.authenticate("admin", "first-password") is None
    assert repository.authenticate("admin", "second-password") is not None


def test_action_tokens_are_one_time_and_migrations_are_idempotent(tmp_path) -> None:
    database = tmp_path / "auth.sqlite3"
    repository = AuthRepository(database)
    user = repository.create_user(
        "owner",
        "owner-password",
        is_admin=True,
        email="owner@example.com",
    )
    token = repository.create_action_token(
        "password_reset",
        user_id=user["id"],
        lifetime_hours=2,
    )

    assert repository.action_token(token, "password_reset")["user_id"] == user["id"]
    assert repository.consume_action_token(token, "password_reset")["user_id"] == user["id"]
    assert repository.action_token(token, "password_reset") is None
    AuthRepository(database)


def test_google_identity_links_by_verified_email_data(tmp_path) -> None:
    repository = AuthRepository(tmp_path / "auth.sqlite3")
    user = repository.create_user(
        "editor",
        "editor-password",
        is_admin=False,
        email="editor@example.com",
    )

    linked = repository.link_google_identity(
        user["id"],
        subject="google-subject",
        email="editor@example.com",
        display_name="Editor Name",
        avatar_url="https://example.com/avatar.png",
    )

    assert linked["google_connected"] is True
    assert repository.find_by_google_subject("google-subject")["id"] == user["id"]
    assert repository.find_by_email("EDITOR@example.com")["display_name"] == "Editor Name"


def test_oauth_state_is_one_time(tmp_path) -> None:
    repository = AuthRepository(tmp_path / "auth.sqlite3")
    state = repository.create_oauth_state("invite-token")

    assert repository.consume_oauth_state(state)["invite_token_hash"]
    try:
        repository.consume_oauth_state(state)
    except KeyError:
        pass
    else:
        raise AssertionError("OAuth state must only be consumed once")


def test_login_analytics_are_hashed_and_migrations_are_idempotent(tmp_path) -> None:
    database = tmp_path / "auth.sqlite3"
    repository = AuthRepository(database, "private-test-salt")
    user = repository.create_user(
        "client",
        "client-password",
        is_admin=False,
        email="client@example.com",
    )

    repository.record_login(
        user_id=user["id"],
        organization_id=None,
        ip_address="203.0.113.9",
        user_agent="Test browser",
        success=True,
    )
    repository.record_login(
        user_id=user["id"],
        organization_id=None,
        ip_address="203.0.113.9",
        user_agent="Test browser",
        success=False,
        failure_reason="invalid_credentials",
    )
    AuthRepository(database, "private-test-salt")

    updated = repository.get_user(user["id"])
    events = repository.list_login_events(user_id=user["id"])
    assert updated["login_count"] == 1
    assert updated["last_login_at"]
    assert updated["last_seen_at"]
    assert len(events) == 2
    assert events[0]["ip_hash"] != "203.0.113.9"
    assert len(events[0]["ip_hash"]) == 64
