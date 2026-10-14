import json
import subprocess
from email.message import Message
from pathlib import Path

import click
import pytest

from nasems import __main__ as nasems


FIXTURES_DIR = Path(__file__).parent / "fixtures"


def headers(content_type):
    message = Message()
    message["Content-Type"] = content_type
    return message


@pytest.fixture
def client(monkeypatch):
    client = nasems.Client()
    client.responses = {}
    client.requests = []

    def request(url, data=None):
        client.requests.append((url, data))
        return client.responses[url]

    monkeypatch.setattr(client, "request", request)
    return client


def test_login(client):
    client.responses[f"{nasems.BASE_URL}/"] = (
        "https://nasems.cz/prihlaseno",
        b"",
        None,
    )
    client.login("user", "secret")

    assert client.requests == [
        (f"{nasems.BASE_URL}/", {"login": "user", "password": "secret"})
    ]


def test_login_fails(client):
    client.responses[f"{nasems.BASE_URL}/"] = ("https://nasems.cz/", b"", None)

    with pytest.raises(click.ClickException):
        client.login("user", "wrong")


def test_list_folders(client):
    body = (FIXTURES_DIR / "fotogalerie.html").read_bytes()
    client.responses[nasems.GALLERY_URL] = (nasems.GALLERY_URL, body, None)

    assert client.list_folders() == {
        17: "Folder 17",
        13: "Folder 13",
        9: "Folder 9",
        8: "Folder 8",
        7: "Folder 7",
        6: "Folder 6",
        4: "Folder 4",
        5: "Folder 5",
    }


def test_list_photos(client):
    fragment = (FIXTURES_DIR / "fotogalerie_slozka.html").read_text()
    body = json.dumps({"status": "ok", "result": fragment}).encode()
    client.responses[nasems.GALLERY_URL] = (nasems.GALLERY_URL, body, None)
    urls = client.list_photos(17)

    assert len(urls) == 60
    assert urls[0] == "https://nasems.cz/fotografie/WHIu4xgtP37Yzu5A"
    assert urls[-1] == "https://nasems.cz/fotografie/G1ZdmbPV9WFISv1A"
    assert client.requests[0][1]["slozka"] == 17


def test_download(client, tmp_path):
    url = "https://nasems.cz/fotografie/Full1"
    client.responses[url] = (url, b"JPEG", headers("image/jpeg"))
    target = tmp_path / "001_Full1.jpg"
    client.download(url, target)

    assert target.read_bytes() == b"JPEG"
    assert list(tmp_path.iterdir()) == [target]


def test_download_not_image(client, tmp_path):
    url = "https://nasems.cz/fotografie/Full1"
    client.responses[url] = (url, b"<html>", headers("text/html"))
    target = tmp_path / "001_Full1.jpg"

    with pytest.raises(RuntimeError):
        client.download(url, target)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "name, expected",
    [
        ("Trip to the Zoo", "Trip to the Zoo"),
        ("Výlet do ZOO ", "Výlet do ZOO"),
        ("A/B: C?", "A_B_ C_"),
        ("...", "untitled"),
        ("", "untitled"),
    ],
)
def test_safe_name(name, expected):
    assert nasems.safe_name(name) == expected


def test_safe_name_fits_filesystem_limit():
    name = nasems.safe_name("Žluťoučký kůň " * 20)

    assert len(name.encode()) <= nasems.MAX_NAME_BYTES
    assert name.startswith("Žluťoučký kůň")
    assert not name.endswith(" ")


def test_safe_name_does_not_split_characters():
    assert nasems.safe_name("ččč", max_bytes=5) == "čč"


def test_get_folder_dir_new(tmp_path):
    folder_dir = nasems.get_folder_dir(tmp_path, 17, "Trip to the Zoo")

    assert folder_dir == tmp_path / "017 Trip to the Zoo"


def test_get_folder_dir_new_long_name(tmp_path):
    folder_dir = nasems.get_folder_dir(tmp_path, 17, "Žluťoučký kůň " * 20)
    folder_dir.mkdir()

    assert len(folder_dir.name.encode()) <= nasems.MAX_NAME_BYTES


def test_get_folder_dir_output_missing(tmp_path):
    folder_dir = nasems.get_folder_dir(tmp_path / "photos", 17, "Trip to the Zoo")

    assert folder_dir == tmp_path / "photos" / "017 Trip to the Zoo"


def test_get_folder_dir_renamed(tmp_path):
    (tmp_path / "017 Old name").mkdir()

    assert nasems.get_folder_dir(tmp_path, 17, "New name") == tmp_path / "017 Old name"


def test_get_folder_dir_ignores_other_ids(tmp_path):
    (tmp_path / "170 Other").mkdir()
    (tmp_path / "0171 Other").mkdir()
    (tmp_path / "017 file.txt").write_text("")

    assert nasems.get_folder_dir(tmp_path, 17, "Trip") == tmp_path / "017 Trip"


def test_plan_folder_skips_existing(tmp_path):
    (tmp_path / "001_Full1.jpg").write_bytes(b"JPEG")
    (tmp_path / "002_Full2.jpg.part").write_bytes(b"JP")
    urls = [
        "https://nasems.cz/fotografie/Full0",
        "https://nasems.cz/fotografie/Full1",
        "https://nasems.cz/fotografie/Full2",
    ]

    assert nasems.plan_folder(tmp_path, urls) == [
        ("https://nasems.cz/fotografie/Full0", tmp_path / "001_Full0.jpg"),
        ("https://nasems.cz/fotografie/Full2", tmp_path / "003_Full2.jpg"),
    ]


def test_plan_folder_everything_downloaded(tmp_path):
    (tmp_path / "001_Full1.jpg").write_bytes(b"JPEG")

    assert nasems.plan_folder(tmp_path, ["https://nasems.cz/fotografie/Full1"]) == []


@pytest.fixture
def fake_op(monkeypatch):
    accounts = {}
    calls = []

    def op(*args):
        calls.append(args)
        if args[:2] == ("account", "list"):
            return json.dumps(
                [{"account_uuid": id, "url": f"{id}.example.com"} for id in accounts]
            )
        account_id = args[args.index("--account") + 1]
        if args[:2] == ("item", "list"):
            return json.dumps(accounts[account_id])
        if args[:2] == ("item", "get"):
            item_ids = [item["id"] for item in accounts.get(account_id, [])]
            if args[2] not in item_ids:
                raise subprocess.CalledProcessError(1, "op", stderr="not found")
            return json.dumps(
                [{"id": "username", "value": "user"}, {"id": "password", "value": "pw"}]
            )
        raise AssertionError(args)

    monkeypatch.setattr(nasems, "op", op)
    return accounts, calls


def login_item(item_id, url):
    return {"id": item_id, "title": item_id, "urls": [{"href": url}]}


def test_find_op_item(fake_op):
    accounts, _ = fake_op
    accounts["work"] = [login_item("w1", "https://example.com")]
    accounts["home"] = [login_item("h1", "https://nasems.cz/prihlaseno")]

    assert nasems.find_op_item() == ("h1", "home")


def test_find_op_item_stops_at_first_match(fake_op):
    accounts, calls = fake_op
    accounts["home"] = [login_item("h1", "https://nasems.cz")]
    accounts["work"] = [login_item("w1", "https://nasems.cz")]

    assert nasems.find_op_item() == ("h1", "home")
    assert not any("work" in call for call in calls)


@pytest.mark.parametrize(
    "url",
    [
        "https://nasems.cz.example.com",
        "https://example.com/nasems.cz",
        "https://notnasems.cz",
    ],
)
def test_find_op_item_requires_exact_host(fake_op, url):
    accounts, _ = fake_op
    accounts["home"] = [login_item("h1", url)]

    with pytest.raises(LookupError):
        nasems.find_op_item()


def test_credentials_from_op_caches_ids(fake_op, tmp_path, monkeypatch):
    accounts, calls = fake_op
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    accounts["work"] = []
    accounts["home"] = [login_item("h1", "https://nasems.cz")]

    assert nasems.credentials_from_op() == ("user", "pw")
    cache = json.loads((tmp_path / "nasems" / "op.json").read_text())
    assert cache == {"item_id": "h1", "account_id": "home"}

    calls.clear()
    assert nasems.credentials_from_op() == ("user", "pw")
    assert [call[:2] for call in calls] == [("item", "get")]


def test_credentials_from_op_stale_cache(fake_op, tmp_path, monkeypatch):
    accounts, _ = fake_op
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    nasems.write_op_cache("gone", "home")
    accounts["home"] = [login_item("h1", "https://nasems.cz")]

    assert nasems.credentials_from_op() == ("user", "pw")
    assert nasems.read_op_cache() == ("h1", "home")
