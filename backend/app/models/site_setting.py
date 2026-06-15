"""Site-wide settings (singleton).

Holds configuration that applies to the whole deployment rather than to any one
project. Today that is just the optional single shared password that gates the
entire site (see :mod:`app.auth`). The table is intended to hold exactly one row
(``id == 1``); :func:`app.auth.get_site_setting` materialises it lazily.
"""

from __future__ import annotations

from sqlalchemy import Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, TimestampMixin


class SiteSetting(TimestampMixin, Base):
    """Singleton row of deployment-wide settings."""

    __tablename__ = "site_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # When True (and a password hash is set), the site-protection middleware
    # redirects unauthenticated visitors to the login page. Off by default.
    protection_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )

    # PBKDF2 hash of the single shared password, in the format produced by
    # ``app.auth.hash_password`` (``pbkdf2_sha256$iters$salt$hash``). Null until
    # a password has been set. Recovery from lockout is by clearing/replacing
    # this value directly in the database.
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<SiteSetting id={self.id} protection_enabled={self.protection_enabled}>"
