"""Tests for accounts, root approval, session tokens, and PII redaction.

Run: python3 tests/test_accounts.py

Every case runs against a throwaway SQLite file, so the suite never touches the
live candidate database.

The cases worth keeping are the ones asserting a *refusal*: that a fresh
account is powerless, that only root can grant, that a mask cannot be walked
around via export or a photo URL. A permission system is tested by what it
denies — the allow paths fail loudly in normal use, the deny paths fail
silently.
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Must be set before app.settings is imported, since Settings reads the
# environment once at import time.
_TMP_DB = Path(tempfile.mkdtemp(prefix="resume_ai_accounts_")) / "test.db"
os.environ["DB_PATH"] = str(_TMP_DB)
os.environ["AUTH_ENABLED"] = "true"
os.environ["SESSION_SECRET"] = "test-secret-that-is-long-enough-for-validation-32"
os.environ["CORS_ORIGINS"] = "http://localhost:5173"
os.environ["API_KEYS"] = "script-key-abc"
os.environ["READONLY_API_KEYS"] = "readonly-key-xyz"
os.environ["JOB_WORKER_INPROCESS"] = "false"

from app import accounts, tokens  # noqa: E402
from app.accounts import AccountError  # noqa: E402
from app.database import _connect, init_db  # noqa: E402
from app.pii import (  # noqa: E402
    mask_address,
    mask_email,
    mask_name,
    mask_phone,
    redact_candidate,
    redact_detail,
)
from app.settings import settings  # noqa: E402

PASS = 0
FAIL = 0


def check(name: str, condition: bool, detail: str = ""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}  {detail}")


def raises(fn, *args, **kwargs) -> AccountError | None:
    try:
        fn(*args, **kwargs)
    except AccountError as exc:
        return exc
    return None


ROOT_ACTOR = {"id": 1, "email": "root@co.com", "role": "root", "status": "active"}


# --------------------------------------------------------------------------


def test_password_hashing():
    print("\n[password hashing]")
    encoded = accounts.hash_password("correct horse battery")
    check("verifies the right password", accounts.verify_password("correct horse battery", encoded))
    check("rejects the wrong password", not accounts.verify_password("wrong", encoded))
    check("hash is salted (two hashes differ)",
          accounts.hash_password("same") != accounts.hash_password("same"))
    check("plaintext never appears in the hash", "correct horse battery" not in encoded)
    check("malformed stored hash rejects rather than crashing",
          not accounts.verify_password("x", "garbage"))
    # Cost travels with the hash, so raising the constant later must not lock
    # existing users out of their own accounts.
    cheap = accounts.hash_password("legacy", iterations=1000)
    check("old low-cost hash still verifies", accounts.verify_password("legacy", cheap))
    check("old low-cost hash is flagged for rehash", accounts.needs_rehash(cheap))
    check("current hash needs no rehash", not accounts.needs_rehash(encoded))


def test_registration_grants_nothing():
    print("\n[registration]")
    conn = _connect()
    user = accounts.register_user(
        conn, email="Applicant@Co.com", password="a-good-password", company="Acme"
    )
    check("email is normalised to lowercase", user["email"] == "applicant@co.com")
    check("new account is pending", user["status"] == "pending")
    check("new account gets the lowest role", user["role"] == "viewer")
    check("new account gets the lowest PII level", user["pii_level"] == "masked")

    err = raises(accounts.register_user, conn, email="applicant@co.com", password="another-pass")
    check("duplicate email refused", err is not None and err.status_code == 409)

    # The length floor is currently off (MIN_PASSWORD_LENGTH = 1), so a short
    # password is accepted; an empty one still is not.
    short = accounts.register_user(conn, email="short@co.com", password="abc")
    check("short password accepted while the floor is off", short is not None)

    err = raises(accounts.register_user, conn, email="empty@co.com", password="")
    check("empty password still refused", err is not None)

    err = raises(accounts.register_user, conn, email="not-an-email", password="a-good-password")
    check("malformed email refused", err is not None)
    conn.close()


def test_only_root_approves():
    print("\n[approval is root-only]")
    conn = _connect()
    pending = accounts.get_user_by_email(conn, "applicant@co.com")

    for role in ("viewer", "interviewer", "recruiter", "admin"):
        err = raises(
            accounts.approve_user,
            conn,
            user_id=pending["id"],
            role="admin",
            pii_level="full",
            actor={"id": 99, "email": "x@co.com", "role": role, "status": "active"},
        )
        check(f"{role} cannot approve", err is not None and err.status_code == 403)

    # An account whose own status is not active must not act, even as root:
    # a suspended administrator is suspended.
    err = raises(
        accounts.approve_user, conn, user_id=pending["id"], role="admin",
        pii_level="full",
        actor={"id": 1, "email": "r@co.com", "role": "root", "status": "suspended"},
    )
    check("suspended root cannot approve", err is not None)

    approved = accounts.approve_user(
        conn, user_id=pending["id"], role="recruiter", pii_level="partial", actor=ROOT_ACTOR
    )
    check("root can approve", approved["status"] == "active")
    check("approval sets the chosen role", approved["role"] == "recruiter")
    check("approval sets the chosen PII level", approved["pii_level"] == "partial")
    check("approval records who did it", approved["approved_by"] == ROOT_ACTOR["id"])

    err = raises(accounts.approve_user, conn, user_id=999999, role="viewer",
                 pii_level="masked", actor=ROOT_ACTOR)
    check("approving a missing account 404s", err is not None and err.status_code == 404)

    err = raises(accounts.approve_user, conn, user_id=pending["id"], role="wizard",
                 pii_level="full", actor=ROOT_ACTOR)
    check("unknown role refused", err is not None)

    err = raises(accounts.approve_user, conn, user_id=pending["id"], role="viewer",
                 pii_level="everything", actor=ROOT_ACTOR)
    check("unknown PII level refused", err is not None)
    conn.close()


def test_privilege_escalation_guards():
    print("\n[escalation guards]")
    conn = _connect()
    fresh = accounts.register_user(conn, email="climber@co.com", password="a-good-password")

    err = raises(accounts.approve_user, conn, user_id=fresh["id"], role="root",
                 pii_level="full", actor=ROOT_ACTOR)
    check("cannot approve an unreviewed account straight to root", err is not None)

    check("only root holds admin:users",
          [r for r in accounts.ROLES if accounts.has_permission(r, "admin:users")] == ["root"])
    check("admin cannot grant permissions", not accounts.has_permission("admin", "admin:users"))
    check("interviewer cannot export", not accounts.has_permission("interviewer", "export"))
    check("recruiter can export", accounts.has_permission("recruiter", "export"))
    check("viewer can only read", accounts.ROLE_PERMISSIONS["viewer"] == frozenset({"read"}))
    conn.close()


def test_last_root_protected():
    print("\n[last root]")
    conn = _connect()
    root = accounts.bootstrap_root(conn, email="root@co.com", password="root-password-1")
    actor = {"id": root["id"], "email": root["email"], "role": "root", "status": "active"}

    err = raises(accounts.update_grade, conn, user_id=root["id"], actor=actor, role="admin")
    check("last root cannot be demoted", err is not None)

    err = raises(accounts.set_status, conn, user_id=root["id"], status="suspended", actor=actor)
    check("last root cannot be suspended", err is not None)

    err = raises(accounts.bootstrap_root, conn, email="second@co.com", password="another-pass-1")
    check("bootstrap refuses when a root exists", err is not None)

    # With a second root in place the guard must step aside, or the system
    # would be permanently stuck with whoever was first.
    other = accounts.register_user(conn, email="root2@co.com", password="a-good-password")
    accounts.approve_user(conn, user_id=other["id"], role="admin", pii_level="full", actor=actor)
    accounts.update_grade(conn, user_id=other["id"], actor=actor, role="root")
    demoted = accounts.update_grade(conn, user_id=root["id"], actor=actor, role="admin")
    check("a root can be demoted once another exists", demoted["role"] == "admin")
    conn.close()


def test_session_tokens():
    print("\n[session tokens]")
    secret = settings.session_secret
    token, expires_at = tokens.issue_session(
        user_id=7, email="a@co.com", role="recruiter", pii_level="partial",
        token_version=3, secret=secret, ttl_seconds=3600,
    )
    payload = tokens.decode(token, secret)
    check("round-trips the subject", payload["sub"] == "7")
    check("carries the token version", payload["tv"] == 3)
    check("expiry is in the future", expires_at > time.time())

    def rejected(t, s=secret):
        try:
            tokens.decode(t, s)
            return False
        except tokens.TokenError:
            return True

    check("rejects a tampered signature", rejected(token[:-4] + "AAAA"))
    check("rejects a different secret", rejected(token, "another-secret-of-sufficient-length"))
    check("rejects garbage", rejected("not.a.token"))
    check("rejects an empty string", rejected(""))

    # The classic JWT forgery: a token that declares its own algorithm as
    # "none" and carries no signature.
    import base64
    import json as _json

    def b64(raw: bytes) -> str:
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    forged = (
        b64(_json.dumps({"alg": "none", "typ": "JWT"}).encode())
        + "."
        + b64(_json.dumps({"sub": "1", "role": "root", "exp": time.time() + 999}).encode())
        + "."
    )
    check("rejects alg=none forgery", rejected(forged))

    expired, _ = tokens.issue_session(
        user_id=7, email="a@co.com", role="viewer", pii_level="masked",
        token_version=1, secret=secret, ttl_seconds=-10,
    )
    check("rejects an expired token", rejected(expired))

    # A token with no exp is signed correctly but would never stop working.
    forever = tokens.encode({"sub": "1", "tv": 1}, secret)
    check("rejects a token with no expiry", rejected(forever))


def test_token_version_revocation():
    print("\n[revocation]")
    conn = _connect()
    user = accounts.register_user(conn, email="revoke@co.com", password="a-good-password")
    root = accounts.get_user_by_email(conn, "root2@co.com")
    actor = {"id": root["id"], "email": root["email"], "role": "root", "status": "active"}
    accounts.approve_user(conn, user_id=user["id"], role="viewer", pii_level="masked", actor=actor)

    before = accounts.get_user(conn, user["id"])["token_version"]
    accounts.change_password(
        conn, user_id=user["id"], current_password="a-good-password", new_password="new-password-99"
    )
    after = accounts.get_user(conn, user["id"])["token_version"]
    check("password change bumps token_version", after > before)

    err = raises(accounts.change_password, conn, user_id=user["id"],
                 current_password="wrong", new_password="another-password")
    check("password change needs the current password", err is not None and err.status_code == 403)

    v1 = accounts.get_user(conn, user["id"])["token_version"]
    accounts.set_status(conn, user_id=user["id"], status="suspended", actor=actor)
    check("suspension bumps token_version",
          accounts.get_user(conn, user["id"])["token_version"] > v1)

    v2 = accounts.get_user(conn, user["id"])["token_version"]
    accounts.update_grade(conn, user_id=user["id"], actor=actor, role="admin", pii_level="full")
    check("grade change bumps token_version",
          accounts.get_user(conn, user["id"])["token_version"] > v2)
    conn.close()


def test_no_secrets_leak():
    print("\n[serialisation]")
    conn = _connect()
    user = accounts.get_user_by_email(conn, "root2@co.com")
    public = accounts.to_public(user)
    check("password_hash never serialised", "password_hash" not in public)
    check("token_version not serialised", "token_version" not in public)
    check("public form keeps the role", public["role"] == "root")
    check("public form carries a readable label", public["role_label"] == "系統管理者")
    check("public form lists permissions", "admin:users" in public["permissions"])
    conn.close()


def test_audit_trail():
    print("\n[account audit]")
    conn = _connect()
    events = accounts.list_user_events(conn, limit=200)
    actions = {e["action"] for e in events}
    for expected in ("register", "approve", "bootstrap_root", "password_change", "status:suspended"):
        check(f"records {expected!r}", expected in actions)

    approvals = [e for e in events if e["action"] == "approve"]
    check("approval records the actor", all(e["actor_email"] for e in approvals))
    check("approval records the target", all(e["target_email"] for e in approvals))
    check("approval records the granted grade",
          any("recruiter" in (e["detail"] or "") for e in approvals))
    conn.close()


# --------------------------------------------------------------------------
# PII redaction
# --------------------------------------------------------------------------

CANDIDATE = {
    "id": 42,
    "name": "王小明",
    "english_name": "John Smith",
    "code_104": "A1234567",
    "email": "xiaoming@example.com",
    "mobile1": "0912-345-678",
    "phone_home": "02-2700-1234",
    "mailing_address": "台北市大安區忠孝東路四段100號5樓",
    "birth_year": "1995",
    "age": "30",
    "photo_path": "/output/output_1/42.jpg",
    "photo_url": "/output/output_1/42.jpg",
    "source_pdf_path": "/data/resumes/wang.pdf",
    "school": "國立台灣大學",
    "major": "資訊工程學系",
    "total_score": 87.5,
    "llm_tier": 3,
    "skill_tags": ["Python", "RAG"],
    "self_introduction": "我是王小明，手機 0912345678，作品集 wang.dev",
}


def test_mask_helpers():
    print("\n[mask helpers]")
    check("Chinese name keeps the surname", mask_name("王小明") == "王＊＊")
    check("two-character name still masks", mask_name("陳明").startswith("陳"))
    check("Latin name keeps the given name", mask_name("John Smith").startswith("John "))
    check("empty name stays empty", mask_name("") == "")
    check("email keeps its domain", mask_email("alice@corp.com").endswith("@corp.com"))
    check("email hides the local part", "alice" not in mask_email("alice@corp.com"))
    check("phone keeps the last three digits", mask_phone("0912-345-678").endswith("678"))
    check("phone hides the middle", "345" not in mask_phone("0912-345-678"))
    check("address keeps city and district", mask_address("台北市大安區忠孝東路四段100號") == "台北市大安區＊＊＊")
    check("address hides the street", "忠孝東路" not in mask_address("台北市大安區忠孝東路四段100號"))
    check("empty inputs do not crash", mask_phone("") == "" and mask_email("") == "")


def test_redaction_levels():
    print("\n[redaction levels]")
    full = redact_candidate(CANDIDATE, "full")
    check("full level is a no-op", full["name"] == "王小明" and full["email"] == CANDIDATE["email"])

    partial = redact_candidate(CANDIDATE, "partial")
    check("partial masks the name", partial["name"] == "王＊＊")
    check("partial masks the email", "xiaoming" not in partial["email"])
    check("partial masks the phone", "345" not in partial["mobile1"])
    check("partial withholds the photo", partial["photo_url"] is None)
    check("partial withholds the source PDF", partial["source_pdf_path"] is None)
    # Free text quotes the very name and number the field masking removed.
    check("partial redacts the self-introduction", "王小明" not in str(partial["self_introduction"]))
    check("partial keeps the score", partial["total_score"] == 87.5)
    check("partial keeps the school", partial["school"] == "國立台灣大學")

    masked = redact_candidate(CANDIDATE, "masked")
    check("masked replaces the name with a code", masked["name"] == "候選人 #42")
    check("masked removes the real name", "王小明" not in str(masked.values()))
    check("masked removes the email", "example.com" not in str(masked["email"]))
    check("masked removes the birth year", masked["birth_year"] != "1995")
    check("masked removes the 104 code", masked["code_104"] != "A1234567")
    check("masked withholds the photo", masked["photo_url"] is None)
    check("masked keeps the score", masked["total_score"] == 87.5)
    check("masked keeps the tier", masked["llm_tier"] == 3)
    check("masked keeps the school for ranking", masked["school"] == "國立台灣大學")

    check("input is never mutated", CANDIDATE["name"] == "王小明")
    check("unknown level fails closed (treated as masked)",
          redact_candidate(CANDIDATE, "nonsense")["name"] == "候選人 #42")


def test_photo_and_path_fields_are_null():
    print("\n[photo fields]")
    # A masked string in an href/src renders as a broken image rather than as
    # "no photo", so these must be None, not "＊＊＊".
    for level in ("partial", "masked"):
        out = redact_candidate(CANDIDATE, level)
        check(f"{level}: photo_url is None", out["photo_url"] is None)
        check(f"{level}: photo_path is None", out["photo_path"] is None)


def test_redact_detail_children():
    print("\n[nested sections]")
    detail = {
        **CANDIDATE,
        "references": [{"ref_name": "李大華", "ref_email": "lee@corp.com", "ref_org": "某公司"}],
        "attachments": [{"name": "作品集", "url": "https://wang.dev/portfolio"}],
    }
    partial = redact_detail(detail, "partial")
    check("partial masks a reference's name", partial["references"][0]["ref_name"] == "李＊＊")
    check("partial masks a reference's email", "lee@" not in partial["references"][0]["ref_email"])

    masked = redact_detail(detail, "masked")
    check("masked removes the reference entirely", "李大華" not in str(masked["references"]))
    check("masked removes attachment URLs", "wang.dev" not in str(masked["attachments"]))
    check("masked keeps the attachment name", masked["attachments"][0]["name"] == "作品集")


def main():
    init_db()
    test_password_hashing()
    test_registration_grants_nothing()
    test_only_root_approves()
    test_privilege_escalation_guards()
    test_last_root_protected()
    test_session_tokens()
    test_token_version_revocation()
    test_no_secrets_leak()
    test_audit_trail()
    test_mask_helpers()
    test_redaction_levels()
    test_photo_and_path_fields_are_null()
    test_redact_detail_children()
    print(f"\n{'=' * 50}")
    print(f"PASS: {PASS}   FAIL: {FAIL}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
