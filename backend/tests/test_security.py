from app.core.security import hash_password, verify_password


def test_hash_password_roundtrip() -> None:
    hashed = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", hashed)


def test_verify_password_rejects_wrong_password() -> None:
    hashed = hash_password("correct horse battery staple")
    assert not verify_password("wrong password", hashed)


def test_hash_password_is_salted() -> None:
    a = hash_password("same password")
    b = hash_password("same password")
    assert a != b
