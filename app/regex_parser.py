"""Regex-based parser for 104.com resume markdown format."""

import re
from app.models import (
    AttachmentExtract,
    EducationExtract,
    ReferenceExtract,
    ResumeExtract,
    WorkExperienceExtract,
)


def _clean(text: str) -> str:
    """Strip whitespace and <br> tags."""
    return re.sub(r"<br\s*/?>", " ", text).strip()


def _parse_table_rows(text: str) -> list[list[str]]:
    """Parse markdown table lines into lists of cell strings."""
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        # Skip separator rows  |---|---|
        if re.match(r"^\|[\s\-:|]+\|$", line):
            continue
        cells = line.split("|")
        # Drop empty first/last from leading/trailing |
        if cells and cells[0].strip() == "":
            cells = cells[1:]
        if cells and cells[-1].strip() == "":
            cells = cells[:-1]
        rows.append([_clean(c) for c in cells])
    return rows


def _kv_from_rows(rows: list[list[str]]) -> dict[str, str]:
    """Extract key:value pairs from table rows where keys end with : or ：."""
    kv: dict[str, str] = {}
    for cells in rows:
        i = 0
        while i < len(cells):
            cell = cells[i].strip()
            # Match keys like "姓/名:" or "年齡："
            if re.search(r"[:：]\s*$", cell):
                key = re.sub(r"[\s*]*[:：]\s*$", "", cell).strip()
                key = key.replace("*", "").strip()
                val = cells[i + 1].strip() if i + 1 < len(cells) else ""
                if key:
                    kv[key] = val
                i += 2
            else:
                i += 1
    return kv


def _split_sections(markdown: str) -> dict[str, str]:
    """Split markdown into named sections by headings."""
    sections: dict[str, str] = {}
    # Match # or ### or #### headings
    parts = re.split(r"^(#{1,4})\s+(.+)$", markdown, flags=re.MULTILINE)

    # parts[0] is text before any heading (if any)
    current_name = "_preamble"
    current_text = parts[0]

    i = 1
    while i < len(parts):
        # Save previous section
        sections[current_name] = current_text.strip()
        # parts[i] = heading markers, parts[i+1] = heading text, parts[i+2] = body
        current_name = parts[i + 1].strip()
        current_text = parts[i + 2] if i + 2 < len(parts) else ""
        i += 3

    sections[current_name] = current_text.strip()
    return sections


def _kv_from_flat_text(section: str) -> dict[str, str]:
    """Fallback: extract key:value pairs from flat text where Marker didn't produce a table.

    OCR sometimes renders the basic info as a single block of text with bold
    markers like: 姓**/**名**:** 林紘頡 ♂ 英⽂名字**:** ...
    We strip the ** markers, then use known field names to split the text.
    """
    # Merge all non-image, non-heading lines into one string
    lines = []
    for line in section.splitlines():
        line = line.strip()
        if not line or line.startswith("!["):
            continue
        if re.match(r"^#{1,4}\s+", line):
            continue
        lines.append(line)
    text = " ".join(lines)

    # Strip bold markers:  姓**/**名**:**  →  姓/名:
    text = text.replace("**", "")

    # Known keys in order of appearance (use both full-width and half-width variants)
    keys = [
        "姓/名", "姓名", "英⽂名字", "英文名字", "104代碼",
        "年齡", "國籍", "⽬前⾝份", "目前身份", "最快可上班⽇", "最快可上班日",
        "⾝⼼障礙類別", "身心障礙類別",
        "學歷", "學校", "科系", "兵役狀況", "退伍時間",
        "希望薪資待遇", "希望職務類別", "希望⼯作地點", "希望工作地點",
        "希望從事產業", "理想職務", "語⾔", "語言", "年資", "特殊⾝份", "特殊身份",
        "最近⼯作", "最近工作", "相關職務經驗/年資",
        "駕駛執照", "交通⼯具", "交通工具",
        "個⼈簡介", "個人簡介", "個⼈格⾔", "個人格言", "個⼈特⾊", "個人特色",
        "個⼈連結", "個人連結",
    ]

    kv: dict[str, str] = {}
    # Build a pattern that splits on any known key followed by : or ：
    escaped_keys = [re.escape(k) for k in keys]
    split_pattern = r"(" + "|".join(escaped_keys) + r")\s*[:：]\s*"
    parts = re.split(split_pattern, text)

    # parts = [before, key1, value1, key2, value2, ...]
    i = 1
    while i < len(parts) - 1:
        key = parts[i].strip()
        val = parts[i + 1].strip()
        if key and key not in kv:
            kv[key] = val
        i += 2

    return kv


def _parse_basic_info(section: str, result: dict):
    """Parse the 基本資料 section."""
    rows = _parse_table_rows(section)
    kv = _kv_from_rows(rows)

    # If table parsing found no name, try flat-text fallback
    if not kv.get("姓/名") and not kv.get("姓名"):
        flat_kv = _kv_from_flat_text(section)
        # Merge: flat_kv fills in missing keys
        for k, v in flat_kv.items():
            if k not in kv or not kv[k]:
                kv[k] = v

    # Also try flat-text parse on <br>-expanded version for single-cell tables
    # where all fields are packed into one cell with <br> separators
    if not kv.get("姓/名") and not kv.get("姓名"):
        br_expanded = re.sub(r"<br\s*/?>", "\n", section)
        br_expanded = re.sub(r"\|", " ", br_expanded)
        flat_kv2 = _kv_from_flat_text(br_expanded)
        for k, v in flat_kv2.items():
            if k not in kv or not kv[k]:
                kv[k] = v

    # Name — strip gender symbol and clean artifacts
    name_raw = kv.get("姓/名", kv.get("姓名", ""))
    # Remove known key artifacts that leak into name from <br>-merged cells
    name_raw = re.split(r"英⽂名字|英文名字|104代碼", name_raw)[0]
    name_raw = re.sub(r"\s*[♂♀]\s*", "", name_raw).strip()

    # Fallback: if name still empty, try direct regex on the raw section
    if not name_raw:
        # Match 姓/名 with optional ** bold markers
        name_match = re.search(
            r"姓\*{0,2}[/／]\*{0,2}名\*{0,2}\s*[:：]\s*\*{0,2}\s*([^♂♀\n|*:：]+)",
            section,
        )
        if not name_match:
            name_match = re.search(r"姓名\s*[:：]\s*([^♂♀\n|*:：]+)", section)
        if name_match:
            name_raw = name_match.group(1).strip()
        else:
            # Handle table where name is in first value cell without 姓/名 key:
            #   | 謝岳均 ♂ | 英⽂名字: | ... |
            for cells in rows:
                if len(cells) >= 2:
                    first = cells[0].strip()
                    second = cells[1].strip()
                    # First cell is a name (has CJK + optional gender), second is a known key
                    if re.search(r"[♂♀]", first) and re.search(r"英[⽂文]名字|104代碼", second):
                        name_raw = re.sub(r"\s*[♂♀]\s*", "", first).strip()
                        break
            # Handle broken pipe format: "| Name||" at start of section
            if not name_raw:
                pipe_match = re.search(r"^\|\s*([^\s|][^|]*?)\s*\|{1,2}\s*$", section, re.MULTILINE)
                if pipe_match:
                    candidate_name = pipe_match.group(1).strip()
                    # Sanity: should look like a CJK name or Latin name, not a data field
                    if len(candidate_name) <= 30 and not re.search(r"[:：]", candidate_name):
                        name_raw = candidate_name

    result["name"] = name_raw
    result["english_name"] = kv.get("英⽂名字", kv.get("英文名字", ""))
    result["code_104"] = kv.get("104代碼", "")

    # Fallback: extract 104 code directly from raw section if not found in kv
    if not result["code_104"]:
        code_match = re.search(r"104\*{0,2}代碼\*{0,2}\s*[:：]\s*\*{0,2}\s*(\d+)", section)
        if code_match:
            result["code_104"] = code_match.group(1)
    # Clean: code_104 should be digits only
    if result["code_104"]:
        code_digits = re.match(r"(\d+)", result["code_104"])
        result["code_104"] = code_digits.group(1) if code_digits else ""

    # Clean name: strip any remaining pipe characters
    result["name"] = result["name"].replace("|", "").strip()

    # Age — "2002(24)" → birth_year=2002, age=24
    age_raw = kv.get("年齡", "")
    m = re.match(r"(\d{4})\s*\((\d+)\)", age_raw)
    if m:
        result["birth_year"] = m.group(1)
        result["age"] = m.group(2)
    else:
        result["birth_year"] = age_raw
        result["age"] = age_raw

    result["nationality"] = kv.get("國籍", "")
    result["current_status"] = kv.get("⽬前⾝份", kv.get("目前身份", ""))
    result["earliest_start"] = kv.get("最快可上班⽇", kv.get("最快可上班日", ""))
    result["education_level"] = kv.get("學歷", "")
    result["school"] = kv.get("學校", "")
    result["major"] = kv.get("科系", "")
    result["military_status"] = kv.get("兵役狀況", "")
    result["desired_salary"] = kv.get("希望薪資待遇", "")
    result["desired_industry"] = kv.get("希望從事產業", "")
    result["years_of_experience"] = kv.get("年資", "")

    # Job categories — value often split across multiple columns in the same row.
    # Collect ALL non-key cells from the row, join them, then split on commas.
    job_cats: list[str] = []
    for cells in rows:
        row_str = "|".join(cells)
        if "希望職務類別" in row_str:
            found_key = False
            fragments: list[str] = []
            for c in cells:
                if "希望職務類別" in c:
                    found_key = True
                    continue
                if found_key:
                    val = c.strip()
                    if val and not re.search(r"[:：]\s*$", val):
                        fragments.append(val)
            # Join fragments that were split by column boundaries, then re-split
            merged = ", ".join(fragments)
            job_cats = [s.strip() for s in re.split(r"[,，、]", merged) if s.strip()]
            break
    # Filter out single-char fragments (OCR column-boundary artifacts)
    result["desired_job_categories"] = [c for c in job_cats if len(c) > 1]

    locations_raw = kv.get("希望⼯作地點", kv.get("希望工作地點", ""))
    result["desired_locations"] = [
        s.strip() for s in re.split(r"[,，、]", locations_raw) if s.strip()
    ]

    ideal_raw = kv.get("理想職務", "")
    # Split on whitespace runs that look like position boundaries
    result["ideal_positions"] = [
        s.strip() for s in re.split(r"\s{2,}|[,，、\n]", ideal_raw) if s.strip()
    ]

    # Photo — look for image reference
    photo_match = re.search(r"!\[.*?\]\(([^)]+)\)", section)
    if photo_match:
        result["photo_path"] = photo_match.group(1)

    # LinkedIn — look for URL in surrounding text
    linkedin_match = re.search(
        r"linkedin:\s*\[?(https?://[^\s\]]+)", section, re.IGNORECASE
    )
    if not linkedin_match:
        linkedin_match = re.search(
            r"(https?://(?:www\.)?linkedin\.com/[^\s\]]+)", section, re.IGNORECASE
        )
    if linkedin_match:
        url = linkedin_match.group(1).rstrip(")")
        # Clean markdown-escaped underscores (\_)
        url = url.replace(r"\_", "_")
        url = url.replace("\\_", "_")
        result["linkedin_url"] = url

    # Self introduction — text between 個人簡介 and next section marker
    intro_match = re.search(
        r"個⼈簡介\*{0,2}[:：]\*{0,2}\s*([\s\S]*?)(?=個⼈格⾔|個⼈特⾊|個⼈連結|#|$)",
        section,
    )
    if intro_match:
        result["self_introduction"] = intro_match.group(1).strip()


def _parse_contact(section: str, result: dict):
    """Parse the 聯絡方式 section."""
    rows = _parse_table_rows(section)
    kv = _kv_from_rows(rows)

    # Flat-text fallback for contact section too
    if not kv.get("email"):
        text = re.sub(r"\*\*", "", section)
        contact_keys = [
            "email", "聯絡⽅式", "聯絡方式",
            "⼿機1", "手機1", "⼿機2", "手機2",
            "住家", "公司", "地區", "通訊地址",
        ]
        escaped = [re.escape(k) for k in contact_keys]
        pattern = r"(" + "|".join(escaped) + r")\s*[:：]\s*"
        parts = re.split(pattern, text)
        i = 1
        while i < len(parts) - 1:
            key = parts[i].strip()
            val = parts[i + 1].strip()
            if key and key not in kv:
                kv[key] = val
            i += 2

    result["email"] = kv.get("email", "")
    result["mobile1"] = kv.get("⼿機1", kv.get("手機1", ""))
    result["mobile2"] = kv.get("⼿機2", kv.get("手機2", ""))
    result["phone_home"] = kv.get("住家", "")
    result["phone_work"] = kv.get("公司", "")
    result["district"] = kv.get("地區", "")
    result["mailing_address"] = kv.get("通訊地址", "")


def _parse_work_experience(section: str) -> list[WorkExperienceExtract]:
    """Parse work experience entries from the 工作經驗 section.

    Handles both table-based and flat-text formats (with ** bold markers).
    """
    experiences = []

    # Strip ** bold markers for uniform processing
    clean = section.replace("**", "")

    # Strategy: process both table rows AND plain text lines
    rows = _parse_table_rows(section)

    current: dict | None = None
    seq = 0

    def _apply_kv(kv: dict, current: dict):
        if "產業類別" in kv:
            current["industry"] = kv["產業類別"]
        if "公司規模" in kv:
            current["company_size"] = kv["公司規模"]
        if "職務類別" in kv:
            current["job_category"] = kv["職務類別"]
        if "管理責任" in kv:
            current["management_responsibility"] = kv["管理責任"]
        if "職務名稱" in kv:
            current["job_title"] = kv["職務名稱"]
        for k in ("⼯作內容", "工作內容"):
            if k in kv and kv[k]:
                current["job_description"] = kv[k]
        for k in ("⼯作技能", "工作技能"):
            if k in kv and kv[k]:
                current["job_skills"] = kv[k]

    # --- Pass 1: table rows ---
    for cells in rows:
        joined = " ".join(cells)

        company_match = re.search(
            r"(.+?)\s*,\s*(\d{4}/\d{2}/\d{2})\s*~\s*(\S+)\s*\(([^)]+)\)",
            joined,
        )
        if company_match:
            if current:
                experiences.append(WorkExperienceExtract(**current))
            seq += 1
            current = {
                "seq": seq,
                "company_name": company_match.group(1).strip(),
                "date_start": company_match.group(2),
                "date_end": company_match.group(3),
                "duration": company_match.group(4),
                "industry": "", "company_size": "", "job_category": "",
                "management_responsibility": "", "job_title": "",
                "job_description": "", "job_skills": "",
            }
            continue

        if current is None:
            continue

        kv = _kv_from_rows([cells])
        _apply_kv(kv, current)

    if current:
        experiences.append(WorkExperienceExtract(**current))

    # --- Pass 2: flat text fallback (if no table rows matched) ---
    if not experiences:
        current = None
        pending_kv: dict[str, str] = {}  # kv pairs found before company line
        seq = 0
        for line in clean.splitlines():
            line = line.strip()
            if not line:
                continue

            # Company + date line
            company_match = re.search(
                r"(.+?)\s*,\s*(\d{4}/\d{2}/\d{2})\s*~\s*(\S+)\s*\(([^)]+)\)",
                line,
            )
            if company_match:
                if current:
                    experiences.append(WorkExperienceExtract(**current))
                seq += 1
                current = {
                    "seq": seq,
                    "company_name": company_match.group(1).strip(),
                    "date_start": company_match.group(2),
                    "date_end": company_match.group(3),
                    "duration": company_match.group(4),
                    "industry": "", "company_size": "", "job_category": "",
                    "management_responsibility": "", "job_title": "",
                    "job_description": "", "job_skills": "",
                }
                # Apply any kv pairs collected before the company line
                if pending_kv:
                    _apply_kv(pending_kv, current)
                    pending_kv = {}
                continue

            # Extract key:value pairs from the line
            work_keys = ["產業類別", "公司規模", "職務類別", "管理責任", "職務名稱",
                         "⼯作內容", "工作內容", "⼯作技能", "工作技能"]
            escaped = [re.escape(k) for k in work_keys]
            pattern = r"(" + "|".join(escaped) + r")\s*[:：]\s*"
            parts = re.split(pattern, line)
            kv: dict[str, str] = {}
            j = 1
            while j < len(parts) - 1:
                kv[parts[j].strip()] = parts[j + 1].strip()
                j += 2
            if current is not None:
                _apply_kv(kv, current)
            elif kv:
                # Collect kv pairs before company line is found (OCR reordering)
                pending_kv.update(kv)

        if current:
            experiences.append(WorkExperienceExtract(**current))

    return experiences


def _parse_education(section: str) -> list[EducationExtract]:
    """Parse education entries from the 教育背景 subsection."""
    rows = _parse_table_rows(section)
    entries = []

    for cells in rows:
        # Skip header row containing "學校" as header
        if any(c.strip() == "學校" for c in cells):
            continue
        if any(c.strip() == "教育背景" for c in cells):
            continue

        # Look for numbered rows: "1.", "2.", etc.
        joined = " ".join(cells)
        if not re.search(r"^\d+\.", cells[0].strip()):
            continue

        seq_str = cells[0].strip().rstrip(".")
        school = cells[1].strip() if len(cells) > 1 else ""
        department = cells[2].strip() if len(cells) > 2 else ""
        degree = cells[3].strip() if len(cells) > 3 else ""
        period = cells[4].strip() if len(cells) > 4 else ""
        region = cells[5].strip() if len(cells) > 5 else ""
        status = cells[6].strip() if len(cells) > 6 else ""

        date_start, date_end = "", ""
        period_match = re.match(r"(\d{4}/\d{2}/\d{2})\s*~\s*(\d{4}/\d{2}/\d{2})", period)
        if period_match:
            date_start = period_match.group(1)
            date_end = period_match.group(2)

        entries.append(EducationExtract(
            seq=int(seq_str) if seq_str.isdigit() else 0,
            school=school,
            department=department,
            degree_level=degree,
            date_start=date_start,
            date_end=date_end,
            region=region,
            status=status,
        ))

    return entries


def _parse_skills(sections: dict[str, str], markdown: str) -> tuple[str, list[str]]:
    """Extract skill tags and skills text from 才能專長 and its subsections.

    The 才能專長 heading is a top-level section (# or ##) but the actual skill
    content lives in #### subsections that _split_sections stores separately.
    We extract the full text block between 才能專長 and 自我介紹 from the raw
    markdown to capture everything.
    """
    # Find the skills block in the raw markdown
    start_match = re.search(r"^#{1,4}\s+才能專⻑", markdown, re.MULTILINE)
    if not start_match:
        start_match = re.search(r"^#{1,4}\s+才能專長", markdown, re.MULTILINE)
    if not start_match:
        return "", []

    end_match = re.search(r"^#{1,2}\s+⾃我介紹", markdown[start_match.end():], re.MULTILINE)
    if not end_match:
        end_match = re.search(r"^#{1,2}\s+自我介紹", markdown[start_match.end():], re.MULTILINE)

    if end_match:
        text = markdown[start_match.start():start_match.end() + end_match.start()]
    else:
        text = markdown[start_match.start():]

    # Collect all #tag patterns (skill hashtags like #Python #Machine Learning)
    # These appear on lines like: #Python #JavaScript #MS SQL
    tags: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        # Lines that are primarily hashtags (not markdown headings)
        if line.startswith("#") and not re.match(r"^#{1,4}\s+\S", line):
            for m in re.finditer(r"#(\S[^#]*?)(?=\s+#|\s*$)", line):
                tag = m.group(1).strip()
                if tag:
                    tags.append(tag)

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique_tags: list[str] = []
    for t in tags:
        if t not in seen:
            seen.add(t)
            unique_tags.append(t)

    return text.strip(), unique_tags


def _parse_job_preferences(section: str, result: dict):
    """Parse 求職條件 table."""
    rows = _parse_table_rows(section)
    kv = _kv_from_rows(rows)

    result["work_type"] = kv.get("希望⼯作性質", kv.get("希望工作性質", ""))
    result["shift_preference"] = kv.get("希望上班時段", "")
    result["remote_work_preference"] = kv.get("遠端⼯作", kv.get("遠端工作", ""))


def _parse_attachments_and_refs(text: str) -> tuple[list[ReferenceExtract], list[AttachmentExtract]]:
    """Parse references and attachments from the bottom section.

    The table has section labels (推薦人, 附件, 專案成就, 其他作品) in the first
    column, but they may appear on the SAME row as a numbered item or on a
    preceding header row.  Numbered attachment rows (1., 2., ...) that appear
    after the 推薦人 header but before 專案成就 are treated as attachments.
    """
    refs: list[ReferenceExtract] = []
    attachments: list[AttachmentExtract] = []

    rows = _parse_table_rows(text)

    # Two-pass: first find where each label starts
    mode = ""
    att_seq = 0

    for cells in rows:
        if not cells:
            continue
        joined = " ".join(cells)

        # Detect section label anywhere in the row
        if "推薦⼈" in joined or "推薦人" in joined:
            mode = "ref"
        if "附件" in joined:
            mode = "att"
        if "專案成就" in joined:
            mode = "project"
        if "其他作品" in joined:
            mode = "other"

        # Skip header rows
        if any(c.strip() in ("#", "名稱", "姓名", "電⼦郵件", "電話", "檔案/連結", "說明")
               for c in cells):
            continue

        # Look for numbered items
        numbered = None
        for c in cells:
            m = re.match(r"^(\d+)\.$", c.strip())
            if m:
                numbered = int(m.group(1))
                break

        if numbered is None:
            continue

        if mode in ("att", "ref"):
            # After 推薦人 header, numbered rows with 名稱/檔案 are attachments
            # (the 104 format puts attachments right after 推薦人)
            att_seq += 1
            name = ""
            file_link = ""
            for c in cells:
                c = c.strip()
                if c and not re.match(r"^\d+\.$", c) and c not in ("推薦⼈", "推薦人", "附件"):
                    if not name:
                        name = c
                    elif not file_link:
                        file_link = c
            attachments.append(AttachmentExtract(
                attachment_type="附件",
                seq=att_seq,
                name=name,
                description="",
                url=file_link,
            ))

    return refs, attachments


def parse_resume_markdown(markdown: str) -> ResumeExtract:
    """Parse a 104.com format resume markdown into structured data using regex."""
    sections = _split_sections(markdown)
    result: dict = {
        "name": "", "english_name": "", "code_104": "", "birth_year": "", "age": "",
        "nationality": "", "current_status": "", "earliest_start": "",
        "education_level": "", "school": "", "major": "", "military_status": "",
        "desired_salary": "", "desired_job_categories": [], "desired_locations": [],
        "desired_industry": "", "ideal_positions": [], "years_of_experience": "",
        "linkedin_url": "", "photo_path": "", "email": "", "mobile1": "",
        "mobile2": "", "phone_home": "", "phone_work": "", "district": "",
        "mailing_address": "", "work_type": "", "shift_preference": "",
        "remote_work_preference": "", "skills_text": "", "skill_tags": [],
        "self_introduction": "", "work_experiences": [], "education": [],
        "references": [], "attachments": [],
    }

    # Parse basic info — could be in 基本資料 section or _preamble
    basic_section = sections.get("基本資料", sections.get("_preamble", ""))
    # The basic info may span from 基本資料 to 聯絡方式, so include preamble if it has tables
    if "基本資料" in sections:
        _parse_basic_info(sections["基本資料"], result)
    elif "_preamble" in sections:
        _parse_basic_info(sections["_preamble"], result)

    # Contact info — may be a normal section, embedded in heading, or inside basic section
    contact_section = sections.get("聯絡⽅式", sections.get("聯絡方式", ""))
    if not contact_section:
        # Check if contact data is embedded in a section name (flat-text OCR artifact)
        for sec_name, sec_body in sections.items():
            if sec_name.startswith("聯絡⽅式") or sec_name.startswith("聯絡方式"):
                contact_section = sec_name + " " + sec_body
                break
    if not contact_section:
        # Contact table may be inside the basic info section (no separate heading)
        contact_section = basic_section
    if contact_section:
        _parse_contact(contact_section, result)

    # Work experience — usually under ### 工作經驗
    # The section may be truncated by stray # headings in OCR output,
    # so fall back to extracting the full block from raw markdown.
    work_section = sections.get("⼯作經驗", sections.get("工作經驗", ""))
    if not work_section or len(work_section) < 50:
        # Extract from raw markdown: everything between 工作經驗 and 才能專長/教育背景 end
        work_start = re.search(r"^#{1,4}\s+[⼯工]作經驗", markdown, re.MULTILINE)
        if work_start:
            work_end = re.search(
                r"^#{1,4}\s+(?:才能專[⻑長]|⾃我介紹|自我介紹)",
                markdown[work_start.end():], re.MULTILINE
            )
            if work_end:
                work_section = markdown[work_start.end():work_start.end() + work_end.start()]
            else:
                work_section = markdown[work_start.end():]
    if work_section:
        result["work_experiences"] = _parse_work_experience(work_section)

    # Education — embedded in work section or as a separate heading
    # The education table may appear within the work experience section text
    edu_text = work_section or ""
    if "教育背景" in edu_text:
        edu_start = edu_text.index("教育背景")
        edu_text = edu_text[edu_start:]
    result["education"] = _parse_education(edu_text)

    # Job preferences — 求職條件 table may also be in the education area
    for section_text in sections.values():
        if "求職條件" in section_text or "希望⼯作性質" in section_text:
            _parse_job_preferences(section_text, result)
            break

    # Skills — collect from raw markdown between 才能專長 and 自我介紹
    skills_text, skill_tags = _parse_skills(sections, markdown)
    result["skills_text"] = skills_text
    result["skill_tags"] = skill_tags

    # Self introduction — under 自我介紹 heading, or extracted from basic info
    intro = sections.get("⾃我介紹", sections.get("自我介紹", ""))
    if intro and not result["self_introduction"]:
        # Strip sub-headings like #### 英文自傳
        result["self_introduction"] = re.sub(r"#{1,4}\s+.+", "", intro).strip()

    # Also check if self_introduction was found in basic info section
    if not result["self_introduction"]:
        intro_match = re.search(
            r"個⼈簡介\*{0,2}[:：]\*{0,2}\s*([\s\S]*?)(?=個⼈格⾔|個⼈特⾊|#|$)",
            basic_section,
        )
        if intro_match:
            result["self_introduction"] = intro_match.group(1).strip()

    # References and attachments — at the end of the document
    # Find the section whose TABLE rows contain 推薦人 / 附件 (not just mention in text)
    for name, text in sections.items():
        table_rows = _parse_table_rows(text)
        row_labels = " ".join(cells[0].strip() for cells in table_rows if cells)
        if "推薦⼈" in row_labels or "推薦人" in row_labels or "附件" in row_labels:
            refs, atts = _parse_attachments_and_refs(text)
            result["references"] = refs
            result["attachments"] = atts
            break

    # Build Pydantic model
    return ResumeExtract(
        name=result["name"],
        english_name=result["english_name"],
        code_104=result["code_104"],
        birth_year=result["birth_year"],
        age=result["age"],
        nationality=result["nationality"],
        current_status=result["current_status"],
        earliest_start=result["earliest_start"],
        education_level=result["education_level"],
        school=result["school"],
        major=result["major"],
        military_status=result["military_status"],
        desired_salary=result["desired_salary"],
        desired_job_categories=result["desired_job_categories"],
        desired_locations=result["desired_locations"],
        desired_industry=result["desired_industry"],
        ideal_positions=result["ideal_positions"],
        years_of_experience=result["years_of_experience"],
        linkedin_url=result["linkedin_url"],
        photo_path=result["photo_path"],
        email=result["email"],
        mobile1=result["mobile1"],
        mobile2=result["mobile2"],
        phone_home=result["phone_home"],
        phone_work=result["phone_work"],
        district=result["district"],
        mailing_address=result["mailing_address"],
        work_type=result["work_type"],
        shift_preference=result["shift_preference"],
        remote_work_preference=result["remote_work_preference"],
        skills_text=result["skills_text"],
        skill_tags=result["skill_tags"],
        self_introduction=result["self_introduction"],
        work_experiences=result["work_experiences"],
        education=result["education"],
        references=result["references"],
        attachments=result["attachments"],
    )
