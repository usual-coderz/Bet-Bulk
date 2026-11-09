class RegisterError(Exception):
    """Generic registration failure — proxy ko blame nahi."""


class ProxyError(RegisterError):
    """Proxy ki wajah se fail — proxy ko bench karo."""


class CaptchaError(RegisterError):
    """Captcha solve nahi hua."""


class FormError(RegisterError):
    """Form field nahi mila / form hi nahi khula."""