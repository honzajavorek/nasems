import pytest

from tests.download_fixtures import (
    FIXTURES_DIR,
    FOLDER_ID,
    anonymize_folder,
    anonymize_gallery,
)


def test_gallery_fixture_is_anonymized():
    html = (FIXTURES_DIR / "fotogalerie.html").read_text(encoding="utf-8")

    assert anonymize_gallery(html) == html


def test_folder_fixture_is_anonymized():
    html = (FIXTURES_DIR / "fotogalerie_slozka.html").read_text(encoding="utf-8")

    assert anonymize_folder(html, FOLDER_ID) == html


def test_anonymize_gallery_fails_on_changed_html():
    html = (FIXTURES_DIR / "fotogalerie.html").read_text(encoding="utf-8")
    html = html.replace("personal_icon", "something_else")

    with pytest.raises(ValueError, match="personal_icon"):
        anonymize_gallery(html)


def test_anonymize_folder_fails_on_changed_html():
    with pytest.raises(ValueError):
        anonymize_folder("<div>nothing here</div>", FOLDER_ID)
