"""Command-line account administration.

Exists for the one operation the API cannot offer: creating the first root.
Every other account is approved by a root, and the first root has nobody to
approve it, so it is made from the machine that holds the database — the same
trust boundary as read access to the file itself.

Also carries the recovery paths an operator needs when they cannot log in:
listing accounts, resetting a password, and promoting a second root.

    python -m app.accounts_cli bootstrap-root --email root@company.com
    python -m app.accounts_cli list
    python -m app.accounts_cli approve --email new@company.com --role recruiter
    python -m app.accounts_cli reset-password --email someone@company.com
"""

from __future__ import annotations

import argparse
import getpass
import sys

from app import accounts
from app.accounts import AccountError
from app.database import _connect, init_db


def _prompt_password(confirm: bool = True) -> str:
    """Read a password from the terminal, never from argv.

    A ``--password`` flag would put the credential into shell history and into
    the process list, where every other user on the box can read it.
    """
    password = getpass.getpass("Password: ")
    if confirm and password != getpass.getpass("Confirm password: "):
        print("Passwords do not match.", file=sys.stderr)
        raise SystemExit(1)
    error = accounts.validate_password(password)
    if error:
        print(error, file=sys.stderr)
        raise SystemExit(1)
    return password


def cmd_bootstrap_root(args: argparse.Namespace) -> int:
    conn = _connect()
    try:
        if accounts.has_root(conn):
            print(
                "A root account already exists. Use an existing root to grant the "
                "role, or `promote-root` if you are locked out.",
                file=sys.stderr,
            )
            return 1
        password = _prompt_password()
        user = accounts.bootstrap_root(
            conn, email=args.email, password=password, display_name=args.name
        )
    except AccountError as exc:
        print(exc.message, file=sys.stderr)
        return 1
    finally:
        conn.close()
    print(f"root account created: {user['email']} (id={user['id']})")
    print("Set SESSION_SECRET and AUTH_ENABLED=true, then log in at /login.")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    conn = _connect()
    try:
        rows = accounts.list_users(conn, status=args.status)
    finally:
        conn.close()
    if not rows:
        print("(no accounts)")
        return 0
    print(f"{'id':>4}  {'status':<10} {'role':<12} {'pii':<8} email")
    for row in rows:
        print(
            f"{row['id']:>4}  {row['status']:<10} {row['role']:<12} "
            f"{row['pii_level']:<8} {row['email']}"
        )
    return 0


def cmd_approve(args: argparse.Namespace) -> int:
    conn = _connect()
    try:
        user = accounts.get_user_by_email(conn, args.email)
        if user is None:
            print(f"No such account: {args.email}", file=sys.stderr)
            return 1
        actor = _cli_actor(conn)
        pii = args.pii or accounts.DEFAULT_PII_FOR_ROLE.get(args.role, "masked")
        updated = accounts.approve_user(
            conn,
            user_id=int(user["id"]),
            role=args.role,
            pii_level=pii,
            actor=actor,
            note=args.note or "approved via CLI",
        )
    except AccountError as exc:
        print(exc.message, file=sys.stderr)
        return 1
    finally:
        conn.close()
    print(f"{updated['email']}: {updated['role']} / {updated['pii_level']} / active")
    return 0


def cmd_reset_password(args: argparse.Namespace) -> int:
    conn = _connect()
    try:
        user = accounts.get_user_by_email(conn, args.email)
        if user is None:
            print(f"No such account: {args.email}", file=sys.stderr)
            return 1
        password = _prompt_password()
        conn.execute(
            """
            UPDATE users SET password_hash = ?, updated_at = datetime('now'),
                             token_version = token_version + 1
             WHERE id = ?
            """,
            (accounts.hash_password(password), user["id"]),
        )
        accounts.record_user_event(
            conn,
            action="password_reset",
            actor_email="cli",
            target_id=int(user["id"]),
            target_email=user["email"],
            detail={"source": "cli"},
        )
        conn.commit()
    finally:
        conn.close()
    print(f"Password reset for {args.email}. Existing sessions were invalidated.")
    return 0


def cmd_promote_root(args: argparse.Namespace) -> int:
    """Grant root to an existing account, for lockout recovery."""
    conn = _connect()
    try:
        user = accounts.get_user_by_email(conn, args.email)
        if user is None:
            print(f"No such account: {args.email}", file=sys.stderr)
            return 1
        conn.execute(
            """
            UPDATE users SET role = 'root', pii_level = 'full', status = 'active',
                             updated_at = datetime('now'),
                             token_version = token_version + 1
             WHERE id = ?
            """,
            (user["id"],),
        )
        accounts.record_user_event(
            conn,
            action="promote_root",
            actor_email="cli",
            target_id=int(user["id"]),
            target_email=user["email"],
            detail={"source": "cli"},
        )
        conn.commit()
    finally:
        conn.close()
    print(f"{args.email} is now root.")
    return 0


def _cli_actor(conn) -> dict:
    """A synthetic root actor for CLI operations.

    The CLI runs with filesystem access to the database, which already implies
    the ability to make any of these changes with `sqlite3`. Routing them
    through the same functions means they land in the same audit trail rather
    than happening invisibly.
    """
    return {"id": None, "email": "cli", "role": "root", "status": "active"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Resume AI account administration")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("bootstrap-root", help="create the first root account")
    p.add_argument("--email", required=True)
    p.add_argument("--name", default="root")
    p.set_defaults(func=cmd_bootstrap_root)

    p = sub.add_parser("list", help="list accounts")
    p.add_argument("--status", choices=accounts.STATUSES)
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("approve", help="approve a pending account")
    p.add_argument("--email", required=True)
    p.add_argument("--role", choices=accounts.ROLES, default="viewer")
    p.add_argument("--pii", choices=accounts.PII_LEVELS)
    p.add_argument("--note", default="")
    p.set_defaults(func=cmd_approve)

    p = sub.add_parser("reset-password", help="set a new password for an account")
    p.add_argument("--email", required=True)
    p.set_defaults(func=cmd_reset_password)

    p = sub.add_parser("promote-root", help="grant root to an existing account")
    p.add_argument("--email", required=True)
    p.set_defaults(func=cmd_promote_root)

    args = parser.parse_args(argv)
    init_db()  # ensures the accounts tables exist before any command runs
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
