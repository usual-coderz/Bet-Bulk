from cryptography.fernet import Fernet

from config import settings

_f = Fernet(settings.fernet_key.encode())


def enc(s: str) -> str:
    return _f.encrypt(s.encode()).decode()


def dec(s: str) -> str:
    return _f.decrypt(s.encode()).decode()