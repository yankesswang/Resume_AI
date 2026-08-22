"""Photo URL resolution for candidate headshots.

Regression coverage for the bug where no headshot rendered: Marker writes
extracted images into the *batch* directory while the candidate markdown lives
in a per-candidate subdirectory one level deeper, and photos from several
``output_<batch>/`` directories must all resolve — not just one configured dir.
"""

from pathlib import Path
from urllib.parse import unquote

import pytest

from app import routes
from app.regex_parser import _extract_photo_path


# --- Headshot extraction from markdown ---


def test_headshot_found_outside_basic_info_section():
    """OCR often files the headshot under an unrelated heading."""
    md = (
        "| 姓/名: | 謝金錦 |\n\n"
        "## 自我介紹\n\n"
        "![](_page_3_Picture_1.jpeg)\n\n"
        "熱愛後端開發\n"
    )
    assert _extract_photo_path(md) == "_page_3_Picture_1.jpeg"


def test_project_screenshot_is_not_treated_as_headshot():
    """A resume whose only image is a project poster has no photo."""
    md = "## 專案成就\n\n![](_page_494_Picture_21.jpeg)\n\n排程演算法\n"
    assert _extract_photo_path(md) == ""


def test_first_picture_1_wins_over_later_images():
    md = (
        "![](_page_840_Picture_9.jpeg)\n"
        "![](_page_8_Picture_1.jpeg)\n"
        "![](_page_9_Picture_1.jpeg)\n"
    )
    assert _extract_photo_path(md) == "_page_8_Picture_1.jpeg"


def test_no_images_at_all():
    assert _extract_photo_path("## 自我介紹\n\n沒有照片\n") == ""


@pytest.mark.parametrize(
    "ref", ["_page_3_Picture_1.jpeg", "_page_3_Picture_1.PNG", "_page_12_Picture_1.jpg"]
)
def test_headshot_suffixes(ref):
    assert _extract_photo_path(f"![]({ref})") == ref


@pytest.mark.parametrize("ref", ["_page_3_Picture_10.jpeg", "_page_3_Picture_0.jpeg"])
def test_non_headshot_slots_rejected(ref):
    """Only the Picture_1 slot is the headshot — not Picture_0 or Picture_1N."""
    assert _extract_photo_path(f"![]({ref})") == ""


@pytest.fixture
def photo_root(tmp_path, monkeypatch):
    """Point photo resolution at a temporary project root."""
    monkeypatch.setattr(routes, "PHOTO_ROOT", tmp_path)
    return tmp_path


def _candidate(md_path: Path, photo: str) -> dict:
    return {"photo_path": photo, "source_md_path": str(md_path)}


def test_photo_beside_markdown(photo_root):
    md_dir = photo_root / "output_batch" / "1.0" / "candidate_1_Ann"
    md_dir.mkdir(parents=True)
    (md_dir / "_page_1_Picture_0.jpeg").write_bytes(b"x")

    url = routes._resolve_photo_url(
        _candidate(md_dir / "Ann.md", "_page_1_Picture_0.jpeg")
    )
    assert url == "/output/output_batch/1.0/candidate_1_Ann/_page_1_Picture_0.jpeg"


def test_photo_in_batch_dir_above_markdown(photo_root):
    """The real Marker layout: image in 1.0/, markdown in 1.0/candidate_N_x/."""
    batch = photo_root / "output_batch" / "1.0"
    md_dir = batch / "candidate_5_Bob"
    md_dir.mkdir(parents=True)
    (batch / "_page_11_Picture_1.jpeg").write_bytes(b"x")

    url = routes._resolve_photo_url(
        _candidate(md_dir / "Bob.md", "_page_11_Picture_1.jpeg")
    )
    assert url == "/output/output_batch/1.0/_page_11_Picture_1.jpeg"


def test_photos_across_multiple_batches_all_resolve(photo_root):
    """A single mounted batch dir used to starve every other batch."""
    urls = []
    for batch_name in ("output_0720", "output_0816"):
        batch = photo_root / batch_name / "1.0"
        md_dir = batch / "candidate_1_X"
        md_dir.mkdir(parents=True)
        (batch / "pic.jpeg").write_bytes(b"x")
        urls.append(routes._resolve_photo_url(_candidate(md_dir / "X.md", "pic.jpeg")))

    assert urls == ["/output/output_0720/1.0/pic.jpeg", "/output/output_0816/1.0/pic.jpeg"]


def test_cjk_batch_dir_is_percent_encoded(photo_root):
    batch = photo_root / "output_0720履歷-20260721T014443Z" / "1.0"
    batch.mkdir(parents=True)
    (batch / "pic.jpeg").write_bytes(b"x")

    url = routes._resolve_photo_url(_candidate(batch / "李修宏.md", "pic.jpeg"))
    assert "履歷" not in url, "CJK path must be percent-encoded for the URL"
    assert unquote(url) == "/output/output_0720履歷-20260721T014443Z/1.0/pic.jpeg"


def test_markdown_relative_prefix_is_stripped(photo_root):
    """photo_path may carry a relative prefix from the markdown image ref."""
    batch = photo_root / "output_batch" / "1.0"
    batch.mkdir(parents=True)
    (batch / "pic.jpeg").write_bytes(b"x")

    url = routes._resolve_photo_url(_candidate(batch / "X.md", "./images/pic.jpeg"))
    assert url == "/output/output_batch/1.0/pic.jpeg"


def test_missing_file_returns_empty_string(photo_root):
    """No broken <img> src — the UI falls back to the name initial."""
    md_dir = photo_root / "output_batch" / "1.0"
    md_dir.mkdir(parents=True)

    assert routes._resolve_photo_url(_candidate(md_dir / "X.md", "nope.jpeg")) == ""


@pytest.mark.parametrize(
    "candidate",
    [
        {"photo_path": "", "source_md_path": "/tmp/x/y.md"},
        {"photo_path": "pic.jpeg", "source_md_path": ""},
        {},
    ],
)
def test_missing_inputs_return_empty_string(photo_root, candidate):
    assert routes._resolve_photo_url(candidate) == ""


def test_does_not_escape_photo_root(photo_root):
    """A markdown path outside the served root must not leak files via /output."""
    outside = photo_root.parent / "outside"
    outside.mkdir(exist_ok=True)
    (outside / "secret.jpeg").write_bytes(b"x")

    assert routes._resolve_photo_url(_candidate(outside / "X.md", "secret.jpeg")) == ""


# --- /output route: serves photos, nothing else ---


@pytest.fixture
def client(photo_root):
    from fastapi.testclient import TestClient

    from main import app

    with TestClient(app) as c:
        yield c


def test_route_serves_image_under_output_dir(client, photo_root):
    batch = photo_root / "output_batch" / "1.0"
    batch.mkdir(parents=True)
    (batch / "pic.png").write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + b"\x00" * 20
    )

    resp = client.get("/output/output_batch/1.0/pic.png")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"


@pytest.mark.parametrize(
    "path",
    [
        "/output/resume_ai.db",  # the SQLite database
        "/output/main.py",  # application source
        "/output/app/routes.py",
        "/output/job_requirement.json",
        "/output/../resume_ai.db",  # traversal out of the root
        "/output/output_batch/../../resume_ai.db",
        "/output/output_batch/notes.md",  # non-image inside an output dir
    ],
)
def test_route_refuses_non_photo_paths(client, photo_root, path):
    """PHOTO_ROOT holds the DB and source; /output must expose only images."""
    (photo_root / "resume_ai.db").write_bytes(b"sqlite")
    (photo_root / "main.py").write_text("secret")
    batch = photo_root / "output_batch"
    batch.mkdir(exist_ok=True)
    (batch / "notes.md").write_text("private")

    assert client.get(path).status_code == 404
