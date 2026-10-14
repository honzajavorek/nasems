"""Re-downloads HTML fixtures from nasems.cz. Run: uv run python -m tests.download_fixtures

Personal data is replaced based on the HTML structure, so that no real values
need to be listed anywhere in the repository.
"""

import json
from pathlib import Path

from bs4 import BeautifulSoup

from nasems.__main__ import GALLERY_URL, Client, get_credentials


FIXTURES_DIR = Path(__file__).parent / "fixtures"
FOLDER_ID = 17


def select_required(soup, selector):
    if elements := soup.select(selector):
        return elements
    raise ValueError(f"nothing to anonymize at {selector!r}, did the HTML change?")


def replace_text(soup, selector, text):
    for element in select_required(soup, selector):
        element.string = text(element) if callable(text) else text


def anonymize_gallery(html):
    soup = BeautifulSoup(html, "html.parser")
    replace_text(soup, ".button_description", "School")
    replace_text(soup, ".personal_icon", "XY")
    replace_text(soup, ".login .value", "username")
    replace_text(
        soup,
        ".fotogalerie_containers .container[id] .left_side",
        lambda element: f"Folder {element.find_parent(class_='container')['id']}",
    )
    return str(soup)


def anonymize_folder(html, folder_id):
    soup = BeautifulSoup(html, "html.parser")
    replace_text(soup, ".podnadpis .left_side label", f"Folder {folder_id}")
    replace_text(soup, ".podnadpis_1", "Description")
    for element in select_required(soup, "a[download]"):
        element["download"] = "photo.jpg"
    return str(soup)


def main():
    client = Client()
    client.login(*get_credentials(use_op=True))

    _, body, _ = client.request(GALLERY_URL)
    html = anonymize_gallery(body.decode("utf-8"))
    (FIXTURES_DIR / "fotogalerie.html").write_text(html, encoding="utf-8")

    _, body, _ = client.request(
        GALLERY_URL,
        {
            "ajax": "ajax",
            "what": "fotogalerie",
            "action": "load_html_fotogalerie_slozka",
            "slozka": FOLDER_ID,
        },
    )
    html = anonymize_folder(json.loads(body)["result"], FOLDER_ID)
    (FIXTURES_DIR / "fotogalerie_slozka.html").write_text(html, encoding="utf-8")


if __name__ == "__main__":
    main()
