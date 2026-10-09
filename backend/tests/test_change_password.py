"""Password hashing and verification for the change-password flow."""

from app.password import hash_password, verify_hash


def test_hash_round_trip():
    stored = hash_password("correct horse")
    assert stored.startswith("pbkdf2_sha256$")
    assert verify_hash("correct horse", stored)
    assert not verify_hash("wrong horse", stored)


def test_hash_is_salted():
    assert hash_password("same") != hash_password("same")


def test_malformed_hash_is_rejected():
    assert not verify_hash("anything", "not-a-hash")
