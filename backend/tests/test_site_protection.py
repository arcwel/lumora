"""Tests for the optional single-shared-password site protection."""

from __future__ import annotations

import pytest

pytest.importorskip("jinja2")

from fastapi.testclient import TestClient  # noqa: E402

from app.auth import hash_password, verify_password  # noqa: E402
from app.main import app, ui_enabled  # noqa: E402

pytestmark = pytest.mark.skipif(not ui_enabled, reason="dashboard UI disabled (no Jinja2)")


def _client() -> TestClient:
    # Don't auto-follow redirects: we want to assert on the 303 to /login.
    return TestClient(app, follow_redirects=False)


def test_password_hash_roundtrip():
    h = hash_password("hunter2")
    assert h.startswith("pbkdf2_sha256$")
    assert verify_password("hunter2", h)
    assert not verify_password("wrong", h)
    assert not verify_password("hunter2", None)
    assert not verify_password("x", "garbage")


def test_site_open_by_default(db_session):
    c = _client()
    assert c.get("/").status_code == 200


def test_cannot_enable_without_password(db_session):
    c = _client()
    resp = c.post("/settings/site-protection", data={"enabled": "on"})
    assert resp.status_code == 303
    assert "needs_password" in resp.headers["location"]
    # Still open — protection wasn't turned on.
    assert c.get("/").status_code == 200


def test_enable_protect_and_login_flow(db_session):
    c = _client()

    # Enable with a password; admin stays logged in via the issued cookie.
    resp = c.post(
        "/settings/site-protection", data={"enabled": "on", "password": "s3cret"}
    )
    assert resp.status_code == 303
    assert "lumora_auth" in resp.cookies or any(
        "lumora_auth" in v for v in resp.headers.get_list("set-cookie")
    )
    # The issued cookie keeps the admin authenticated.
    assert c.get("/").status_code == 200

    # A fresh visitor (no cookie) is redirected to the login page.
    fresh = _client()
    redirect = fresh.get("/")
    assert redirect.status_code == 303
    assert redirect.headers["location"] == "/login"

    # The login page itself is reachable.
    login = fresh.get("/login")
    assert login.status_code == 200
    assert "This site is protected" in login.text

    # Wrong password is rejected.
    bad = fresh.post("/login", data={"password": "nope"})
    assert bad.status_code == 401

    # Correct password authenticates and unlocks the site.
    good = fresh.post("/login", data={"password": "s3cret"})
    assert good.status_code == 303
    assert good.headers["location"] == "/"
    assert fresh.get("/").status_code == 200


def test_exempt_paths_reachable_when_locked(db_session):
    admin = _client()
    admin.post("/settings/site-protection", data={"enabled": "on", "password": "pw"})

    visitor = _client()
    # Health probe and static assets must never be gated.
    assert visitor.get("/health").status_code == 200
    assert visitor.get("/static/css/app.css").status_code == 200
    # Login page is exempt; an arbitrary app page is not.
    assert visitor.get("/login").status_code == 200
    assert visitor.get("/projects/new").status_code == 303


def test_change_password_invalidates_old_sessions(db_session):
    c = _client()
    c.post("/settings/site-protection", data={"enabled": "on", "password": "first"})
    assert c.get("/").status_code == 200  # logged in with "first"

    # Change the password from the same (authenticated) session.
    c.post("/settings/site-protection", data={"enabled": "on", "password": "second"})

    # A session still holding the OLD cookie is now logged out.
    stale = _client()
    stale.cookies.set("lumora_auth", "deadbeef")
    assert stale.get("/").status_code == 303


def test_disable_reopens_site(db_session):
    admin = _client()
    admin.post("/settings/site-protection", data={"enabled": "on", "password": "pw"})

    # Turn it back off (no password needed to disable).
    admin.post("/settings/site-protection", data={"password": ""})

    visitor = _client()
    assert visitor.get("/").status_code == 200
