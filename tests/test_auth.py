"""API-key authentication.

``app.auth`` reads the module-level ``settings`` singleton, so these tests patch
attributes on that object rather than the environment — rebuilding ``Settings``
would not be seen by the already-imported module.

Coverage targets the four properties that actually matter for PII exposure:
falling open when disabled, rejecting missing/invalid keys, blocking writes for
read-only principals, and comparing keys in constant time.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import auth
from app.auth import (
    ANONYMOUS,
    Principal,
    _key_id,
    _match,
    is_write_request,
    require_read,
    require_write,
)


class _FakeRequest:
    """Minimal stand-in for starlette's Request (headers + state only)."""

    def __init__(self, headers=None):
        self.headers = headers or {}

        class _State:
            pass

        self.state = _State()


@pytest.fixture
def auth_on(monkeypatch):
    """Enable auth with one full-access and one read-only key."""
    monkeypatch.setattr(auth.settings, "auth_enabled", True)
    monkeypatch.setattr(auth.settings, "api_keys", ("full-secret",))
    monkeypatch.setattr(auth.settings, "readonly_api_keys", ("ro-secret",))
    monkeypatch.setattr(auth.settings, "auth_header", "X-API-Key")


@pytest.fixture
def auth_off(monkeypatch):
    monkeypatch.setattr(auth.settings, "auth_enabled", False)


# ---------------------------------------------------------------------------
# Falls open when disabled
# ---------------------------------------------------------------------------
def test_falls_open_when_disabled(auth_off):
    """Existing local workflows must keep working with no key configured."""
    principal = require_read(_FakeRequest())
    assert principal is ANONYMOUS
    assert principal.anonymous is True
    assert principal.can_write is True


def test_anonymous_may_write_when_disabled(auth_off):
    principal = require_write(_FakeRequest(), require_read(_FakeRequest()))
    assert principal.can_write is True


# ---------------------------------------------------------------------------
# 401 on missing / invalid
# ---------------------------------------------------------------------------
def test_missing_key_is_401(auth_on):
    with pytest.raises(HTTPException) as exc:
        require_read(_FakeRequest())
    assert exc.value.status_code == 401
    assert "Missing" in exc.value.detail
    # The challenge header tells clients which header to send.
    assert exc.value.headers["WWW-Authenticate"] == "X-API-Key"


def test_invalid_key_is_401(auth_on):
    with pytest.raises(HTTPException) as exc:
        require_read(_FakeRequest({"X-API-Key": "wrong"}))
    assert exc.value.status_code == 401
    assert "Invalid" in exc.value.detail


def test_valid_full_key_authenticates(auth_on):
    principal = require_read(_FakeRequest({"X-API-Key": "full-secret"}))
    assert principal.can_write is True
    assert principal.anonymous is False


def test_bearer_token_accepted(auth_on):
    """Proxies that strip custom headers still work via Authorization: Bearer."""
    principal = require_read(_FakeRequest({"Authorization": "Bearer full-secret"}))
    assert principal.can_write is True


def test_bearer_scheme_is_case_insensitive(auth_on):
    principal = require_read(_FakeRequest({"Authorization": "bearer ro-secret"}))
    assert principal.can_write is False


def test_custom_auth_header_is_honoured(auth_on, monkeypatch):
    monkeypatch.setattr(auth.settings, "auth_header", "X-Resume-Key")
    assert require_read(_FakeRequest({"X-Resume-Key": "full-secret"})).can_write is True
    with pytest.raises(HTTPException):
        require_read(_FakeRequest({"X-API-Key": "full-secret"}))


def test_principal_is_attached_to_request_state(auth_on):
    """Audit logging reads request.state.principal, so it must be set."""
    req = _FakeRequest({"X-API-Key": "full-secret"})
    principal = require_read(req)
    assert req.state.principal is principal


# ---------------------------------------------------------------------------
# Read-only principals cannot write
# ---------------------------------------------------------------------------
def test_readonly_key_can_read(auth_on):
    assert require_read(_FakeRequest({"X-API-Key": "ro-secret"})).can_write is False


def test_readonly_principal_rejected_on_write(auth_on):
    ro = require_read(_FakeRequest({"X-API-Key": "ro-secret"}))
    with pytest.raises(HTTPException) as exc:
        require_write(_FakeRequest(), ro)
    assert exc.value.status_code == 403
    assert "read-only" in exc.value.detail.lower()


def test_full_key_passes_write_gate(auth_on):
    full = require_read(_FakeRequest({"X-API-Key": "full-secret"}))
    assert require_write(_FakeRequest(), full) is full


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE", "post", "delete"])
def test_write_methods_detected(method):
    assert is_write_request(method) is True


@pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS", "get"])
def test_read_methods_detected(method):
    assert is_write_request(method) is False


# ---------------------------------------------------------------------------
# Constant-time comparison
# ---------------------------------------------------------------------------
def test_match_uses_constant_time_compare(monkeypatch):
    """Guard against a refactor swapping hmac.compare_digest for `==`.

    A plain equality check short-circuits on the first differing byte, which
    leaks a valid key prefix through response timing.
    """
    calls = []
    real = auth.hmac.compare_digest

    def spy(a, b):
        calls.append((a, b))
        return real(a, b)

    monkeypatch.setattr(auth.hmac, "compare_digest", spy)
    _match("presented", ("a-key", "b-key"))
    assert calls, "hmac.compare_digest was not used — comparison is not constant time"


def test_match_does_not_short_circuit_on_first_hit(monkeypatch):
    """Every candidate is compared even after a match, so timing is uniform."""
    calls = []
    real = auth.hmac.compare_digest

    def spy(a, b):
        calls.append(b)
        return real(a, b)

    monkeypatch.setattr(auth.hmac, "compare_digest", spy)
    assert _match("k1", ("k1", "k2", "k3")) is True
    assert calls == ["k1", "k2", "k3"]


def test_match_semantics():
    assert _match("k1", ("k1", "k2")) is True
    assert _match("nope", ("k1", "k2")) is False
    assert _match("anything", ()) is False


def test_key_id_never_contains_the_key():
    """Audit records outlive credentials — they must not embed the secret."""
    secret = "super-secret-key"
    kid = _key_id(secret)
    assert secret not in kid
    assert kid.startswith("k_")
    assert kid == _key_id(secret)  # stable
    assert kid != _key_id("different-key")


# ---------------------------------------------------------------------------
# Wired into a real app
# ---------------------------------------------------------------------------
def test_dependencies_enforced_through_fastapi(auth_on):
    app = FastAPI()

    @app.get("/read")
    def read(p: Principal = Depends_read()):
        return {"key_id": p.key_id}

    @app.post("/write")
    def write(p: Principal = Depends_write()):
        return {"ok": True}

    client = TestClient(app)

    assert client.get("/read").status_code == 401
    assert client.get("/read", headers={"X-API-Key": "bad"}).status_code == 401
    assert client.get("/read", headers={"X-API-Key": "ro-secret"}).status_code == 200
    # read-only key is accepted for GET but refused for POST
    assert client.post("/write", headers={"X-API-Key": "ro-secret"}).status_code == 403
    assert client.post("/write", headers={"X-API-Key": "full-secret"}).status_code == 200


def Depends_read():
    from fastapi import Depends

    return Depends(require_read)


def Depends_write():
    from fastapi import Depends

    return Depends(require_write)
