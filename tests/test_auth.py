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
