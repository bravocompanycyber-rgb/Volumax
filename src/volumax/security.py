"""Strong encryption helpers and password policy for VOLUMAX."""

from __future__ import annotations

import secrets
import string
from dataclasses import dataclass


# AES-256 is used by 7-Zip when password is set on 7z format.
# ZIP uses ZipCrypto by default in many tools; 7-Zip can use AES for ZIP with -mem=AES256.


@dataclass
class PasswordStrength:
    score: int  # 0-4
    label: str
    hints: list[str]


def assess_password(password: str) -> PasswordStrength:
    hints: list[str] = []
    if not password:
        return PasswordStrength(0, "Empty", ["Enter a password"])
    score = 0
    if len(password) >= 8:
        score += 1
    else:
        hints.append("Use at least 8 characters (12+ recommended)")
    if len(password) >= 12:
        score += 1
    if any(c.islower() for c in password) and any(c.isupper() for c in password):
        score += 1
    else:
        hints.append("Mix upper and lower case")
    if any(c.isdigit() for c in password):
        score += 1
    else:
        hints.append("Include digits")
    if any(c in string.punctuation for c in password):
        score += 1
    else:
        hints.append("Include symbols (!@#$%...)")
    labels = ["Very weak", "Weak", "Fair", "Strong", "Very strong", "Excellent"]
    # score can be up to 5
    label = labels[min(score, 5)]
    if score >= 4 and not hints:
        hints = ["Good password strength"]
    return PasswordStrength(min(score, 4), label, hints)


def generate_secure_password(length: int = 20) -> str:
    """Cryptographically secure random password."""
    length = max(12, min(length, 128))
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*()-_=+[]{}"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def encryption_options_for_format(fmt: str) -> dict:
    """
    Recommended secure options per format.
    7z: AES-256 + optional header encryption (encrypt filenames).
    zip: prefer AES-256 via 7-Zip -mem=AES256 when available.
    """
    fmt = fmt.lower()
    if fmt in ("7z",):
        return {
            "algorithm": "AES-256",
            "encrypt_filenames": True,
            "notes": "Industry-standard AES-256. Enable header encryption so filenames are also protected.",
        }
    if fmt in ("zip",):
        return {
            "algorithm": "AES-256 (via 7-Zip)",
            "encrypt_filenames": False,
            "notes": "Use 7-Zip AES-256 for ZIP when possible. Classic ZipCrypto is weak — avoid for sensitive data.",
        }
    return {
        "algorithm": "Backend-dependent",
        "encrypt_filenames": False,
        "notes": "Prefer 7z with AES-256 for maximum security.",
    }
