"""Email template rendering and validation.

Run: python3 tests/test_email_templates.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.email_templates import (  # noqa: E402
    VARIABLE_KEYS,
    TemplateError,
    build_context,
    default_sender,
    default_templates,
    render,
    render_template,
    unknown_variables,
    validate,
)

failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  ok   {name}")
    else:
        print(f"  FAIL {name} {detail}")
        failures.append(name)


CANDIDATE = {
    "name": "王小明",
    "english_name": "Ming Wang",
    "email": "ming@example.com",
    "education_level": "碩士",
    "years_of_experience": "3年",
    "education": [
        {"school": "國立台灣大學", "department": "資訊工程學系碩士班"},
    ],
}

SENDER = {
    "company": "測試公司",
    "sender_name": "陳經理",
    "sender_title": "人資主管",
    "sender_email": "hr@test.com",
    "sender_phone": "02-1234-5678",
}


print("\n--- rendering ---")

ctx = build_context(CANDIDATE, sender=SENDER, job_title="AI 工程師")

check("name substitutes", render("{{name}} 您好", ctx) == "王小明 您好")
check("whitespace in braces tolerated", render("{{ name }}", ctx) == "王小明")
check("case-insensitive", render("{{NAME}}", ctx) == "王小明")
check("sender fields available", ctx["company"] == "測試公司")
check("job_title passed through", ctx["job_title"] == "AI 工程師")

# The school/major columns are blank on this candidate; the education rows are
# not. A letter that says "您在  的學歷" because the column was empty is the
# bug this fallback exists to prevent.
check("school falls back to education rows", ctx["school"] == "國立台灣大學", ctx["school"])
check("major falls back to education rows", ctx["major"] == "資訊工程學系碩士班", ctx["major"])

# An unknown variable must stay visible. Silently dropping it produces a letter
# that reads as complete while missing the thing the author meant to include.
check(
    "unknown variable stays visible",
    render("{{nope}}", ctx) == "⟨未知變數: nope⟩",
    render("{{nope}}", ctx),
)

# An empty *known* variable is ordinary missing data and must render as blank,
# not as a marker — otherwise every letter to a candidate with no English name
# carries noise.
empty_ctx = build_context({"name": "李四"}, sender=SENDER)
check("empty known variable renders blank", render("[{{english_name}}]", empty_ctx) == "[]")

check("None never leaks as the word None", "None" not in render(
    "{{english_name}}{{school}}{{interview_date}}", empty_ctx
))

print("\n--- interview details ---")

interview = {
    "interview_date": "2026-09-01",
    "interview_time": "14:00",
    "location": "台北市信義區",
    "interview_type": "onsite",
}
ictx = build_context(CANDIDATE, sender=SENDER, interview=interview)
check("interview date", ictx["interview_date"] == "2026-09-01")
check("interview location", ictx["interview_location"] == "台北市信義區")
check(
    "interview_type shown in Chinese",
    ictx["interview_type"] == "現場面試",
    ictx["interview_type"],
)
# An unmapped type must pass through rather than vanish: a custom value the
# operator typed is still information.
check(
    "unknown interview_type passes through",
    build_context(CANDIDATE, interview={"interview_type": "咖啡廳"})["interview_type"] == "咖啡廳",
)

print("\n--- variable picker matches the renderer ---")

# Every variable the editor offers must actually resolve. A picker that offers
# a variable build_context() does not produce would insert a chip that renders
# as "unknown" — the UI would be teaching the operator to write broken letters.
for key in VARIABLE_KEYS:
    check(f"picker variable {key} resolves", key in ctx)

print("\n--- default templates ---")

for tpl in default_templates():
    unknown = unknown_variables(f"{tpl['subject']}\n{tpl['body']}")
    check(f"default template '{tpl['name']}' has no unknown variables", not unknown, str(unknown))

rendered = render_template(
    default_templates()[0], CANDIDATE, sender=SENDER,
    job_title="AI 工程師", interview=interview,
)
check("rendered letter has a recipient", rendered["to"] == "ming@example.com")
check("rendered letter has no leftover braces", "{{" not in rendered["body"])
check("no missing variables when all data present", rendered["missing_variables"] == [],
      str(rendered["missing_variables"]))

# With no interview scheduled, the invite template must report exactly which
# fields are blank, so the operator sees it before sending.
bare = render_template(default_templates()[0], CANDIDATE, sender=SENDER, job_title="AI 工程師")
check(
    "missing interview fields are reported",
    "interview_date" in bare["missing_variables"],
    str(bare["missing_variables"]),
)

print("\n--- validation ---")


def expect_error(name: str, templates) -> None:
    try:
        validate(templates)
    except TemplateError:
        print(f"  ok   {name}")
        return
    print(f"  FAIL {name} (no error raised)")
    failures.append(name)


base = {"id": "a", "name": "測試", "subject": "主旨", "body": "內文"}

check("valid template passes", len(validate([base])) == 1)
expect_error("empty name rejected", [{**base, "name": "  "}])
expect_error("empty subject rejected", [{**base, "subject": ""}])
expect_error("empty body rejected", [{**base, "body": ""}])
expect_error("non-list rejected", {"not": "a list"})
expect_error("oversized subject rejected", [{**base, "subject": "x" * 500}])

# A duplicate id makes the frontend's selection ambiguous and lets an edit to
# one template silently overwrite the other, so it is repaired, not rejected.
dupes = validate([base, {**base, "name": "第二個"}])
check("duplicate ids are made unique", dupes[0]["id"] != dupes[1]["id"])

# An operator mid-word has typed an invalid variable. Refusing the save at that
# moment loses their work, so this is a warning surfaced by the UI, not an error.
check("unfinished variable does not block saving", len(validate([{**base, "body": "{{na"}])) == 1)
check("misspelt variable is reported as a warning", unknown_variables("{{nmae}}") == ["nmae"])

print("\n--- sender ---")
check("default sender has every key blank", all(v == "" for v in default_sender().values()))
check(
    "sender values are trimmed",
    build_context(CANDIDATE, sender={"company": "  A  "})["company"] == "A",
)

print()
if failures:
    print(f"{len(failures)} FAILED: {', '.join(failures)}")
    sys.exit(1)
print("All email template tests passed.")
