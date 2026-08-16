"""Password hashing for `User` login credentials."""

import bcrypt

# bcrypt truncates input silently past 72 bytes; anything a real password
# manager generates is well under that, so this is a defensive cap, not an
# expected path.
_MAX_PASSWORD_BYTES = 72


def hash_password(password: str) -> str:
    encoded = password.encode("utf-8")[:_MAX_PASSWORD_BYTES]
    return bcrypt.hashpw(encoded, bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    encoded = password.encode("utf-8")[:_MAX_PASSWORD_BYTES]
    return bcrypt.checkpw(encoded, password_hash.encode("utf-8"))
