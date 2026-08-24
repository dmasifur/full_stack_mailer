import base64

from cryptography.fernet import Fernet, InvalidToken

from server.core.config import settings


class TokenEncryptionError(Exception):
    pass


def _get_fernet() -> Fernet:
    raw_key = settings.TOKEN_ENCRYPTION_KEY

    if not raw_key:
        raise TokenEncryptionError(
            "TOKEN_ENCRYPTION_KEY is not set. "
            'Generate one with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
        )

    try:
        key_bytes = raw_key.encode() if isinstance(raw_key, str) else raw_key
        base64.urlsafe_b64decode(key_bytes)
        return Fernet(key_bytes)
    except Exception as exc:
        raise TokenEncryptionError(
            "TOKEN_ENCRYPTION_KEY is not a valid Fernet key."
        ) from exc


def encrypt_token(plaintext: str) -> str:
    if not plaintext:
        raise TokenEncryptionError("Cannot encrypt an empty token.")

    fernet = _get_fernet()
    return fernet.encrypt(plaintext.encode()).decode()


def decrypt_token(ciphertext: str) -> str:
    if not ciphertext:
        raise TokenEncryptionError("Cannot decrypt an empty ciphertext.")

    fernet = _get_fernet()

    try:
        return fernet.decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise TokenEncryptionError(
            "Token decryption failed — invalid or tampered ciphertext."
        ) from exc
