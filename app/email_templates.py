"""Email templates: reusable letter drafts rendered against a candidate.

The system does not send mail. It renders a subject and body with the
candidate's own details filled in, and the operator copies them into whatever
mailbox the company actually sends from. That keeps candidate contact details
out of any third-party SMTP relay and needs no credential management.

Templates are stored as one JSON document in `app_settings` rather than a new
table: the whole set is read and written together by the settings page, and it
is a handful of rows, not a queryable collection.

Variables are `{{name}}`-style placeholders resolved by `build_context()`.
An unknown placeholder renders as a visible `⟨未知變數: x⟩` marker rather than
disappearing — a letter silently missing its interview time reads as finished
and gets sent that way.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import date, datetime
from typing import Any

from app.database import get_app_setting, set_app_setting

_SETTING_KEY = "email_templates"

# `{{ name }}` — whitespace inside the braces is tolerated because operators
# type these by hand into a textarea.
_PLACEHOLDER = re.compile(r"\{\{\s*([a-z0-9_]+)\s*\}\}", re.IGNORECASE)

MAX_TEMPLATES = 50
MAX_SUBJECT = 200
MAX_BODY = 20000


class TemplateError(ValueError):
    """A template the operator must fix before it can be saved."""


# --- Variables -------------------------------------------------------------

# (key, label, example) — the label is what the editor shows beside the chip.
# Every key here must be produced by build_context(), and a test asserts that,
# so the picker can never offer a variable that renders as "unknown".
VARIABLES: list[tuple[str, str]] = [
    ("name", "候選人姓名"),
    ("english_name", "英文姓名"),
    ("email", "候選人 Email"),
    ("school", "學校"),
    ("major", "科系"),
    ("education_level", "學歷"),
    ("years_of_experience", "工作年資"),
    ("job_title", "應徵職缺"),
    ("company", "公司名稱"),
    ("sender_name", "寄件人姓名"),
    ("sender_title", "寄件人職稱"),
    ("sender_email", "寄件人 Email"),
    ("sender_phone", "寄件人電話"),
    ("interview_date", "面試日期"),
    ("interview_time", "面試時間"),
    ("interview_location", "面試地點"),
    ("interview_type", "面試形式"),
    ("today", "今天日期"),
]

VARIABLE_KEYS = frozenset(k for k, _ in VARIABLES)


# --- Defaults --------------------------------------------------------------

def default_templates() -> list[dict]:
    """The starter set, so the feature is usable before anyone writes one."""
    return [
        {
            "id": "invite",
            "name": "面試邀約",
            "subject": "【{{company}}】{{job_title}} 面試邀約 - {{name}} 您好",
            "body": (
                "{{name}} 您好：\n"
                "\n"
                "我是 {{company}} 的 {{sender_name}}（{{sender_title}}）。\n"
                "我們已收到並詳閱您應徵 {{job_title}} 的履歷，對您的經歷相當感興趣，"
                "希望能邀請您進一步面談。\n"
                "\n"
                "面試資訊如下：\n"
                "　日期：{{interview_date}}\n"
                "　時間：{{interview_time}}\n"
                "　形式：{{interview_type}}\n"
                "　地點：{{interview_location}}\n"
                "\n"
                "若上述時間不方便，也請直接回信告知您方便的時段，我們會再為您安排。\n"
                "\n"
                "期待與您見面。\n"
                "\n"
                "{{sender_name}}\n"
                "{{sender_title}} ｜ {{company}}\n"
                "{{sender_email}}　{{sender_phone}}\n"
            ),
        },
        {
            "id": "reject",
            "name": "婉謝通知",
            "subject": "【{{company}}】{{job_title}} 應徵結果通知",
            "body": (
                "{{name}} 您好：\n"
                "\n"
                "感謝您應徵 {{company}} 的 {{job_title}} 職缺，也謝謝您撥空提供履歷。\n"
                "\n"
                "經過審慎評估，考量目前職缺的需求與時程，我們這次先不繼續後續流程。"
                "這並非對您專業能力的否定，僅是這個職缺當下的條件取捨。\n"
                "\n"
                "我們會保留您的資料，若日後有更合適的職缺，會再與您聯繫。"
                "祝您求職順利。\n"
                "\n"
                "{{sender_name}}\n"
                "{{sender_title}} ｜ {{company}}\n"
                "{{sender_email}}\n"
            ),
        },
        {
            "id": "followup",
            "name": "資料補件",
            "subject": "【{{company}}】{{job_title}} 應徵資料補充",
            "body": (
                "{{name}} 您好：\n"
                "\n"
                "我是 {{company}} 的 {{sender_name}}。感謝您應徵 {{job_title}}。\n"
                "\n"
                "為了讓我們更完整地了解您的背景，想再請您補充以下資料：\n"
                "　1. \n"
                "　2. \n"
                "\n"
                "再麻煩您於方便時回覆，謝謝您。\n"
                "\n"
                "{{sender_name}}\n"
                "{{sender_title}} ｜ {{company}}\n"
                "{{sender_email}}　{{sender_phone}}\n"
            ),
        },
    ]


def default_sender() -> dict:
    """Blank sender block — filled in once on the settings page."""
    return {
        "company": "",
        "sender_name": "",
        "sender_title": "",
        "sender_email": "",
        "sender_phone": "",
    }


_SENDER_KEYS = frozenset(default_sender())


# --- Persistence -----------------------------------------------------------

def load() -> dict:
    """Stored templates + sender block, falling back to the defaults.

    A corrupt or hand-edited value falls back rather than raising: the settings
    page is where it gets repaired, and it cannot be opened if reading throws.
    """
    raw = get_app_setting(_SETTING_KEY)
    if not raw:
        return {"templates": default_templates(), "sender": default_sender()}
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return {"templates": default_templates(), "sender": default_sender()}
    if not isinstance(data, dict):
        return {"templates": default_templates(), "sender": default_sender()}

    templates = data.get("templates")
    if not isinstance(templates, list):
        templates = default_templates()

    sender = default_sender()
    stored_sender = data.get("sender")
    if isinstance(stored_sender, dict):
        for key in _SENDER_KEYS:
            value = stored_sender.get(key)
            if isinstance(value, str):
                sender[key] = value

    return {"templates": [_normalise(t) for t in templates if isinstance(t, dict)],
            "sender": sender}


def save(templates: list[dict], sender: dict | None = None) -> dict:
    """Validate and persist the whole set. Raises TemplateError on bad input."""
    cleaned = validate(templates)
    payload = {
        "templates": cleaned,
        "sender": _clean_sender(sender if sender is not None else load()["sender"]),
    }
    set_app_setting(_SETTING_KEY, json.dumps(payload, ensure_ascii=False))
    return payload


def _clean_sender(sender: Any) -> dict:
    out = default_sender()
    if isinstance(sender, dict):
        for key in _SENDER_KEYS:
            value = sender.get(key)
            if isinstance(value, str):
                out[key] = value.strip()
    return out


def _normalise(template: dict) -> dict:
    return {
        "id": str(template.get("id") or uuid.uuid4().hex[:8]),
        "name": str(template.get("name") or "未命名範本"),
        "subject": str(template.get("subject") or ""),
        "body": str(template.get("body") or ""),
    }


# --- Validation ------------------------------------------------------------

def validate(templates: Any) -> list[dict]:
    """Return the cleaned list, or raise TemplateError describing the problem."""
    if not isinstance(templates, list):
        raise TemplateError("範本必須是一個清單")
    if len(templates) > MAX_TEMPLATES:
        raise TemplateError(f"範本數量上限為 {MAX_TEMPLATES} 個")

    cleaned: list[dict] = []
    seen_ids: set[str] = set()
    for index, raw in enumerate(templates):
        if not isinstance(raw, dict):
            raise TemplateError(f"第 {index + 1} 個範本格式錯誤")
        item = _normalise(raw)

        if not item["name"].strip():
            raise TemplateError(f"第 {index + 1} 個範本沒有名稱")
        if not item["subject"].strip():
            raise TemplateError(f"「{item['name']}」缺少主旨")
        if not item["body"].strip():
            raise TemplateError(f"「{item['name']}」缺少內文")
        if len(item["subject"]) > MAX_SUBJECT:
            raise TemplateError(f"「{item['name']}」主旨超過 {MAX_SUBJECT} 字")
        if len(item["body"]) > MAX_BODY:
            raise TemplateError(f"「{item['name']}」內文超過 {MAX_BODY} 字")

        # A duplicate id would make the frontend's selection ambiguous and let
        # an edit to one template overwrite the other.
        if item["id"] in seen_ids:
            item["id"] = uuid.uuid4().hex[:8]
        seen_ids.add(item["id"])

        cleaned.append(item)
    return cleaned


def unknown_variables(text: str) -> list[str]:
    """Placeholders in `text` that build_context() will not fill.

    Surfaced as a warning, never an error: an operator mid-edit types `{{na`
    before finishing the word, and refusing to save at that moment loses work.
    """
    found = [m.group(1).lower() for m in _PLACEHOLDER.finditer(text or "")]
    return sorted({v for v in found if v not in VARIABLE_KEYS})


# --- Rendering -------------------------------------------------------------

def build_context(
    candidate: dict,
    *,
    sender: dict | None = None,
    job_title: str = "",
    interview: dict | None = None,
) -> dict[str, str]:
    """Flatten everything a template may reference into plain strings.

    Every value is a string, and a missing one is "" rather than None, so the
    rendered letter never contains the word "None" where a detail should be.
    """
    sender = _clean_sender(sender or {})
    interview = interview or {}

    context = {
        "name": _text(candidate.get("name")),
        "english_name": _text(candidate.get("english_name")),
        "email": _text(candidate.get("email")),
        "school": _text(candidate.get("school")),
        "major": _text(candidate.get("major")),
        "education_level": _text(candidate.get("education_level")),
        "years_of_experience": _text(candidate.get("years_of_experience")),
        "job_title": _text(job_title),
        "today": date.today().isoformat(),
        "interview_date": _text(interview.get("interview_date")),
        "interview_time": _text(interview.get("interview_time")),
        "interview_location": _text(interview.get("location")),
        "interview_type": _interview_type_label(interview.get("interview_type")),
    }
    context.update(sender)

    # The school/major fall back to the education rows, because the candidate
    # columns are frequently blank while the parsed rows are not.
    if not context["school"] or not context["major"]:
        for row in candidate.get("education") or []:
            if not isinstance(row, dict):
                continue
            if not context["school"]:
                context["school"] = _text(row.get("school"))
            if not context["major"]:
                context["major"] = _text(row.get("department"))
            if context["school"] and context["major"]:
                break

    return context


_INTERVIEW_TYPES = {
    "onsite": "現場面試",
    "online": "線上面試",
    "phone": "電話面試",
}


def _interview_type_label(value: Any) -> str:
    text = _text(value)
    return _INTERVIEW_TYPES.get(text.lower(), text)


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, list):
        return "、".join(_text(v) for v in value if v)
    return str(value).strip()


def render(text: str, context: dict[str, str]) -> str:
    """Substitute `{{var}}`. Unknown names stay visible; empty ones vanish.

    The two cases are deliberately different. A *misspelt* variable is an
    author error and must be seen before the letter is sent. An *empty* one is
    ordinary missing data — a candidate with no English name — and marking it
    would put noise into every letter.
    """
    def _sub(match: re.Match) -> str:
        key = match.group(1).lower()
        if key not in context:
            return f"⟨未知變數: {key}⟩"
        return context[key]

    return _PLACEHOLDER.sub(_sub, text or "")


def render_template(
    template: dict,
    candidate: dict,
    *,
    sender: dict | None = None,
    job_title: str = "",
    interview: dict | None = None,
) -> dict:
    """Render one template for one candidate into a ready-to-copy letter."""
    context = build_context(
        candidate, sender=sender, job_title=job_title, interview=interview
    )
    subject = render(template.get("subject", ""), context)
    body = render(template.get("body", ""), context)

    # Which variables resolved to nothing, so the UI can warn before a letter
    # goes out with a blank where the interview time should be.
    used = {
        m.group(1).lower()
        for m in _PLACEHOLDER.finditer(
            f"{template.get('subject', '')}\n{template.get('body', '')}"
        )
    }
    missing = sorted(k for k in used if k in context and not context[k])

    return {
        "template_id": template.get("id", ""),
        "template_name": template.get("name", ""),
        "to": context["email"],
        "subject": subject,
        "body": body,
        "missing_variables": missing,
        "unknown_variables": unknown_variables(
            f"{template.get('subject', '')}\n{template.get('body', '')}"
        ),
    }
