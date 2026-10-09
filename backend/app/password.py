"""Password hashing for the UI-changeable app password."""

import base64
import hashlib
import secrets

# A password changed through the UI is stored hashed in app_settings and takes
# precedence over APP_PASSWORD from the environment, which stays the bootstrap
# value until the first change.
PASSWORD_HASH_KEY = "app_password_hash"
PBKDF2_ITERATIONS = 600_000
MIN_PASSWORD_LENGTH = 8


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS
    )
    return "pbkdf2_sha256${}${}${}".format(
        PBKDF2_ITERATIONS,
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(digest).decode("ascii"),
    )


def verify_hash(password: str, stored: str) -> bool:
    try:
        _, iterations, salt_b64, digest_b64 = stored.split("$")
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            base64.b64decode(salt_b64),
            int(iterations),
        )
        return secrets.compare_digest(digest, base64.b64decode(digest_b64))
    except ValueError:
        return False
