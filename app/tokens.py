"""Signed session tokens (JWT, HS256) minted at login.

Hand-rolled rather than PyJWT, for the same reason :mod:`app.migrations` is
hand-rolled: HS256 JWT is ~60 lines of ``hmac`` and ``base64``, and the
deployment story is "clone and run". The parts people get wrong when writing
this themselves are enumerated and handled below.

What this implementation does **not** do, deliberately:

* **No ``alg`` negotiation.** The header's ``alg`` is checked to equal HS256
  and nothing else is accepted — not ``none``, not RS256. Trusting the token's
  own ``alg`` field is the classic JWT forgery, and the only safe reading of a
  header written by the attacker is "must match what we issue".
* **No claims are read before the signature is verified.** Decoding happens
  strictly after :func:`hmac.compare_digest` succeeds.

Revocation
----------
JWTs are self-contained, so "log everyone out" normally needs a blacklist.
Instead each token carries the user's ``token_version``; the auth dependency
compares it to the current value in the DB. Changing a password, suspending an
account or altering its role bumps that column, and every token minted before
that moment stops validating — without storing a single session row.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Any

ALGORITHM = "HS256"


class TokenError(Exception):
    """An invalid, expired, or unverifiable token."""


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def _sign(message: bytes, secret: str) -> bytes:
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).digest()


def encode(payload: dict[str, Any], secret: str) -> str:
    """Sign a claims dict into a compact JWS."""
    if not secret:
        raise TokenError("No signing secret configured.")
    header = {"alg": ALGORITHM, "typ": "JWT"}
    segments = [
        _b64url_encode(json.dumps(header, separators=(",", ":"), sort_keys=True).encode()),
        _b64url_encode(
            json.dumps(payload, separators=(",", ":"), sort_keys=True, default=str).encode()
        ),
    ]
    signing_input = ".".join(segments).encode("ascii")
    segments.append(_b64url_encode(_sign(signing_input, secret)))
    return ".".join(segments)


def decode(token: str, secret: str, *, leeway: int = 0) -> dict[str, Any]:
    """Verify and decode a token. Raises :class:`TokenError` on any problem."""
    if not secret:
        raise TokenError("No signing secret configured.")
    try:
        header_b64, payload_b64, signature_b64 = token.split(".")
    except (ValueError, AttributeError):
        raise TokenError("Malformed token.") from None

    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    try:
        signature = _b64url_decode(signature_b64)
    except Exception:
        raise TokenError("Malformed token signature.") from None

    # Signature first, always: nothing inside the token is trustworthy until
    # this passes, including the header we are about to check.
    if not hmac.compare_digest(signature, _sign(signing_input, secret)):
        raise TokenError("Bad token signature.")

    try:
        header = json.loads(_b64url_decode(header_b64))
        payload = json.loads(_b64url_decode(payload_b64))
    except Exception:
        raise TokenError("Malformed token payload.") from None

    if header.get("alg") != ALGORITHM:
        raise TokenError("Unsupported token algorithm.")
    if not isinstance(payload, dict):
        raise TokenError("Malformed token payload.")

    expiry = payload.get("exp")
    if expiry is None:
        # An unexpiring session token for a PII database is not a token we
        # want to accept, even one we signed.
        raise TokenError("Token has no expiry.")
    try:
        if time.time() > float(expiry) + leeway:
            raise TokenError("Token has expired.")
    except (TypeError, ValueError):
        raise TokenError("Malformed token expiry.") from None

    return payload


def issue_session(
    *,
    user_id: int,
    email: str,
    role: str,
    pii_level: str,
    token_version: int,
    secret: str,
    ttl_seconds: int,
) -> tuple[str, int]:
    """Mint a session token. Returns ``(token, expires_at_epoch)``.

    Role and PII level are embedded for the client's benefit — the UI needs to
    know which controls to render. The server does not trust them: the auth
    dependency re-reads both from the database on every request, so a grade
    changed by root takes effect on the next call rather than at the next
    login.
    """
    now = int(time.time())
    expires_at = now + ttl_seconds
    payload = {
        "sub": str(user_id),
        "email": email,
        "role": role,
        "pii": pii_level,
        "tv": int(token_version),
        "iat": now,
        "exp": expires_at,
        "jti": secrets.token_urlsafe(8),
    }
    return encode(payload, secret), expires_at
