"""Optional site-wide password protection.

A single shared password (not per-user accounts) that, when enabled, gates the
whole site behind a login page. State lives in the ``site_settings`` singleton
row (:class:`app.models.site_setting.SiteSetting`); the password is stored as a
PBKDF2-SHA256 hash.

Authentication is tracked with a signed session cookie. The cookie value is an
HMAC derived from the *stored password hash* itself — so it needs no separate
server secret, survives restarts, and is invalidated automatically whenever the
password changes (changing the password logs everyone out). Forging it requires
the stored hash, which only ever lives in the database.

Only the standard library is used (``hashlib`` / ``hmac`` / ``secrets``) so the
feature adds no new dependencies.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets

from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from app.db import SessionLocal
from app.models.site_setting import SiteSetting

logger = logging.getLogger(__name__)

# Session cookie name + the constant message signed to derive its value.
COOKIE_NAME = "lumora_auth"
_COOKIE_MESSAGE = b"lumora-site-auth-v1"

# PBKDF2 parameters. 200k SHA-256 iterations is a sensible 2026 default for an
# interactively-entered password on a self-hosted box.
_PBKDF2_ALGO = "pbkdf2_sha256"
_PBKDF2_ITERATIONS = 200_000

# Paths always reachable without authentication: the login page itself, logout,
# static assets, and the health probe. (Favicon too, so the tab icon loads on
# the login screen.)
_EXEMPT_EXACT = {"/login", "/logout", "/health", "/favicon.ico"}
_EXEMPT_PREFIXES = ("/static/",)


# --------------------------------------------------------------------------- #
# Password hashing
# --------------------------------------------------------------------------- #
def hash_password(password: str) -> str:
    """Hash a plaintext password as ``pbkdf2_sha256$iterations$salt$hash``."""

    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS
    )
    return f"{_PBKDF2_ALGO}${_PBKDF2_ITERATIONS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    """Return True when ``password`` matches the stored PBKDF2 hash."""

    if not stored:
        return False
    try:
        algo, iterations, salt_hex, hash_hex = stored.split("$")
        if algo != _PBKDF2_ALGO:
            return False
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations)
        )
    except (ValueError, TypeError):  # malformed hash record
        return False
    return hmac.compare_digest(dk.hex(), hash_hex)


# --------------------------------------------------------------------------- #
# Session cookie
# --------------------------------------------------------------------------- #
def session_token(password_hash: str) -> str:
    """Derive the signed session-cookie value from the stored password hash."""

    return hmac.new(
        password_hash.encode("utf-8"), _COOKIE_MESSAGE, hashlib.sha256
    ).hexdigest()


def is_authenticated(request: Request, setting: SiteSetting | None) -> bool:
    """True when the request carries a valid session cookie for ``setting``."""

    if setting is None or not setting.password_hash:
        return False
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return False
    return hmac.compare_digest(token, session_token(setting.password_hash))


def set_auth_cookie(response: Response, password_hash: str) -> None:
    """Attach the session cookie to ``response`` (session-scoped, HttpOnly)."""

    response.set_cookie(
        COOKIE_NAME,
        session_token(password_hash),
        httponly=True,
        samesite="lax",
        path="/",
    )


def clear_auth_cookie(response: Response) -> None:
    """Remove the session cookie (used on logout)."""

    response.delete_cookie(COOKIE_NAME, path="/")


# --------------------------------------------------------------------------- #
# Settings access
# --------------------------------------------------------------------------- #
def get_site_setting(db) -> SiteSetting:
    """Return the singleton site-settings row, creating it if absent."""

    setting = db.get(SiteSetting, 1)
    if setting is None:
        setting = SiteSetting(id=1, protection_enabled=False, password_hash=None)
        db.add(setting)
        db.commit()
        db.refresh(setting)
    return setting


def protection_state() -> dict[str, bool]:
    """Lightweight state for templates: is protection on / is a password set."""

    db = SessionLocal()
    try:
        setting = db.get(SiteSetting, 1)
        return {
            "enabled": bool(setting and setting.protection_enabled),
            "has_password": bool(setting and setting.password_hash),
        }
    except Exception:  # noqa: BLE001 - never let the topbar widget break a page
        return {"enabled": False, "has_password": False}
    finally:
        db.close()


def _is_exempt(path: str) -> bool:
    """True for paths reachable without authentication."""

    if path in _EXEMPT_EXACT:
        return True
    return any(path.startswith(prefix) for prefix in _EXEMPT_PREFIXES)


# --------------------------------------------------------------------------- #
# Middleware
# --------------------------------------------------------------------------- #
async def site_protection_middleware(request: Request, call_next):
    """Redirect unauthenticated visitors to the login page when protection is on.

    A no-op unless protection is both enabled *and* a password is set, so the
    site stays fully open until an admin deliberately turns it on.
    """

    if _is_exempt(request.url.path):
        return await call_next(request)

    db = SessionLocal()
    try:
        setting = db.get(SiteSetting, 1)
        active = bool(setting and setting.protection_enabled and setting.password_hash)
        authed = active and is_authenticated(request, setting)
    finally:
        db.close()

    if active and not authed:
        return RedirectResponse(url="/login", status_code=303)

    return await call_next(request)
