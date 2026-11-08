import secrets
import string

LETTERS = string.ascii_lowercase
DIGITS = string.digits
SYMBOLS = "!@#$%"
ALNUM = LETTERS + DIGITS


def _pick(pool: str, n: int) -> str:
    return "".join(secrets.choice(pool) for _ in range(n))


def username() -> str:
    return _pick(LETTERS, 4) + _pick(DIGITS, 3)


def password(length: int = 10) -> str:
    core = [
        secrets.choice(string.ascii_uppercase),
        secrets.choice(LETTERS),
        secrets.choice(DIGITS),
        secrets.choice(SYMBOLS),
    ]
    core += [_pick(ALNUM, length - 4)]
    secrets.SystemRandom().shuffle(core)
    return "".join(core)


def mobile() -> str:
    return secrets.choice("6789") + _pick(DIGITS, 9)


def fingerprint() -> dict:
    return {
        "ua": secrets.choice([
            "Mozilla/5.0 (Linux; Android 13; SM-G991B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
            "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Mobile Safari/537.36",
            "Mozilla/5.0 (Linux; Android 12; SM-A536B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Mobile Safari/537.36",
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1",
        ]),
        "viewport": secrets.choice([
            {"width": 393, "height": 851},
            {"width": 412, "height": 915},
            {"width": 360, "height": 800},
        ]),
    }