"""Redaction of applicant identity by PII level.

A role tells you what someone may *do*. It says nothing about how much of a
real person's identity they need to see in order to do it, and for a database
of thousands of live job applicants those are different questions. A hiring
manager ranking candidates needs the scores; they do not need the mobile
number until they decide to call.

Three levels:

===========  ======================================================
``full``     Everything, as stored.
``partial``  Enough to recognise and discuss a candidate — surname,
             last digits of a phone, email domain — not enough to
             contact them or copy their identity out of the system.
``masked``   No identity at all: a stable code, the scores, the
             career history. Ranking works; identification does not.
===========  ======================================================

Two design decisions worth keeping:

**Redaction happens on the way out, not in the query.** Every route returns
dicts assembled by ``app.database``; masking there would mean auditing dozens
of SELECTs and would break the scoring pipeline, which legitimately needs the
full row. Instead the API layer applies :func:`redact_candidate` to the
response. One place to change, one place to test.

**Masked is a real value, not a blank.** Emptying a field makes the UI look
broken and makes "no data" and "not permitted" indistinguishable — an
important difference when someone is deciding whether a resume is incomplete.
Redacted fields carry a visible marker (``王＊＊``, ``09**-***-123``) so the
reader knows information exists and they are not cleared for it.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

MASK_CHAR = "＊"

# Fields that identify or contact a person. Kept as one table so a new column
# is a one-line change here rather than a hunt through the route handlers.
#
# The `birth_year`/`age` entries matter more than they look: combined with a
# school and a graduation year they re-identify someone even without a name,
# which is exactly the kind of joined-up inference a field-by-field review
# tends to miss.
CONTACT_FIELDS: tuple[str, ...] = (
    "email",
    "mobile1",
    "mobile2",
    "phone_home",
    "phone_work",
    "mailing_address",
    "linkedin_url",
)

IDENTITY_FIELDS: tuple[str, ...] = (
    "name",
    "english_name",
    "code_104",
    "birth_year",
    "age",
    "photo_path",
    "photo_url",
)

# Free text is redacted wholesale at `masked`, because a self-introduction
# routinely contains the writer's own name, phone number and personal site.
# There is no reliable way to strip that, so the level that forbids identity
# forbids the field.
FREETEXT_FIELDS: tuple[str, ...] = (
    "self_introduction",
    "raw_markdown",
    "skills_text",
)

# Paths back to the original document. A masked viewer who can open the source
# PDF is not masked at all.
SOURCE_FIELDS: tuple[str, ...] = (
    "source_pdf_path",
    "source_md_path",
)

_DIGITS = re.compile(r"\d")


def mask_name(value: str) -> str:
    """``王小明`` → ``王＊＊``; ``John Smith`` → ``John ＊＊``.

    Keeping the surname is deliberate: interview panels talk about "the second
    王 candidate", and a fully anonymised list is unusable for the coordination
    work the partial level exists to support.
    """
    value = (value or "").strip()
    if not value:
        return ""
    if " " in value:  # Latin-style "given family"
        first, _, rest = value.partition(" ")
        return f"{first} {MASK_CHAR * min(len(rest), 3)}"
    return value[0] + MASK_CHAR * max(len(value) - 1, 1)


def mask_email(value: str) -> str:
    """``alice@example.com`` → ``a＊＊＊＊@example.com``.

    The domain survives because it is organisational rather than personal
    (which company someone works at now is usually on the resume anyway) and
    it is often what a recruiter is actually checking.
    """
    value = (value or "").strip()
    if "@" not in value:
        return MASK_CHAR * 4 if value else ""
    local, _, domain = value.partition("@")
    keep = local[:1]
    return f"{keep}{MASK_CHAR * max(len(local) - 1, 3)}@{domain}"


def mask_phone(value: str) -> str:
    """Keep the leading two and trailing three digits: ``09＊＊＊＊＊123``.

    Enough to match against a call log or confirm "yes, that's the number I
    was given", not enough to dial from scratch.
    """
    value = (value or "").strip()
    digits = _DIGITS.findall(value)
    if not digits:
        return MASK_CHAR * 4 if value else ""
    if len(digits) <= 5:
        return MASK_CHAR * len(digits)
    return "".join(digits[:2]) + MASK_CHAR * (len(digits) - 5) + "".join(digits[-3:])


def mask_address(value: str) -> str:
    """Keep only the administrative prefix: ``台北市大安區＊＊＊``.

    The city and district are what the app actually uses (commute distance,
    regional filtering); the street address is pure contact information.
    """
    value = (value or "").strip()
    if not value:
        return ""
    match = re.match(r"^(.{0,3}[市縣])?(.{0,3}[區鄉鎮市])?", value)
    prefix = "".join(part for part in (match.groups() if match else ()) if part)
    if not prefix:
        prefix = value[:2]
    return f"{prefix}{MASK_CHAR * 3}"


def _blank(value: Any) -> Any:
    """Redact a value while preserving its type, so clients do not crash."""
    if isinstance(value, str):
        return MASK_CHAR * 3 if value else ""
    if isinstance(value, list):
        return []
    if isinstance(value, dict):
        return {}
    return None


def redact_candidate(row: dict[str, Any], level: str) -> dict[str, Any]:
    """Return a copy of a candidate dict trimmed to ``level``.

    Never mutates the input: the same row object is often handed to the
    scoring pipeline in the same request, and that path needs the real values.
    """
    if level == "full":
        return row
    data = dict(row)

    if level == "partial":
        for field in ("name", "english_name"):
            if data.get(field):
                data[field] = mask_name(str(data[field]))
        if data.get("email"):
            data["email"] = mask_email(str(data["email"]))
        for field in ("mobile1", "mobile2", "phone_home", "phone_work"):
            if data.get(field):
                data[field] = mask_phone(str(data[field]))
        if data.get("mailing_address"):
            data["mailing_address"] = mask_address(str(data["mailing_address"]))
        # The photo is the one field partial cannot soften — a face is either
        # shown or it is not — so it is withheld entirely below `full`.
        for field in ("photo_path", "photo_url"):
            if field in data:
                data[field] = None
        for field in SOURCE_FIELDS:
            if field in data:
                data[field] = None
        # Free text carries the identity the field-level masking just removed:
        # a self-introduction opens "我是王小明" and often quotes a phone
        # number. Masking `name` while serving the same name one field down is
        # not partial redaction, it is the appearance of it.
        for field in FREETEXT_FIELDS:
            if field in data and field != "skills_text":
                data[field] = _blank(data[field])
        data["pii_redacted"] = "partial"
        return data

    # masked
    for field in (*CONTACT_FIELDS, *FREETEXT_FIELDS, *SOURCE_FIELDS):
        if field in data:
            data[field] = _blank(data[field])
    for field in IDENTITY_FIELDS:
        if field in data:
            data[field] = _blank(data[field])
    # Path/URL fields must be None rather than a masked string: the frontend
    # feeds them straight to <img src>, and "＊＊＊" would render as a broken
    # image instead of as no photo.
    for field in ("photo_path", "photo_url"):
        if field in data:
            data[field] = None
    # A stable, non-identifying handle, so the candidate can still be referred
    # to, bookmarked and discussed. Derived from the row id rather than a hash
    # of the name, which would be reversible against a known applicant list.
    if data.get("id") is not None:
        data["name"] = f"候選人 #{data['id']}"
    data["pii_redacted"] = "masked"
    return data


def redact_candidates(rows: Iterable[dict[str, Any]], level: str) -> list[dict[str, Any]]:
    if level == "full":
        return list(rows)
    return [redact_candidate(row, level) for row in rows]


def redact_detail(detail: dict[str, Any], level: str) -> dict[str, Any]:
    """Redact a full candidate detail payload, including its child sections.

    Work and education rows carry identity too: a reference's name and email
    are another living person's data, and are held to the same level as the
    applicant's own.
    """
    if level == "full":
        return detail
    data = redact_candidate(detail, level)

    references = data.get("references")
    if isinstance(references, list) and references:
        redacted_refs = []
        for ref in references:
            ref = dict(ref)
            if level == "masked":
                ref["ref_name"] = _blank(ref.get("ref_name"))
                ref["ref_email"] = _blank(ref.get("ref_email"))
                ref["ref_org"] = _blank(ref.get("ref_org"))
            else:
                if ref.get("ref_name"):
                    ref["ref_name"] = mask_name(str(ref["ref_name"]))
                if ref.get("ref_email"):
                    ref["ref_email"] = mask_email(str(ref["ref_email"]))
            redacted_refs.append(ref)
        data["references"] = redacted_refs

    if level == "masked":
        attachments = data.get("attachments")
        if isinstance(attachments, list) and attachments:
            # Attachment URLs point at portfolio sites and personal drives.
            data["attachments"] = [
                {**dict(a), "url": _blank(dict(a).get("url"))} for a in attachments
            ]

    return data
