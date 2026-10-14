"""Downloads all photo galleries from the Naše MŠ app (nasems.cz) to a directory.

Credentials are taken from (in this order):

\b
  1. environment variables NASEMS_LOGIN and NASEMS_PASSWORD
  2. 1Password via the `op` CLI (first login item with the nasems.cz URL)
  3. interactive prompt

Repeated runs download only photos which aren't on disk yet.
"""

import http.cookiejar
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import click
from bs4 import BeautifulSoup


BASE_URL = "https://nasems.cz"
GALLERY_URL = f"{BASE_URL}/prihlaseno/fotogalerie"
USER_AGENT = "Mozilla/5.0 (nasems-download)"


class Client:
    def __init__(self):
        self.cookies = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cookies)
        )
        self.opener.addheaders = [("User-Agent", USER_AGENT)]

    def request(self, url, data=None, retries=5):
        body = urllib.parse.urlencode(data).encode() if data is not None else None
        for attempt in range(retries):
            try:
                with self.opener.open(url, body, timeout=120) as response:
                    return response.geturl(), response.read(), response.headers
            except urllib.error.URLError, TimeoutError, ConnectionError:
                if attempt == retries - 1:
                    raise
                time.sleep(5 * 2**attempt)

    def login(self, username, password):
        final_url, _, _ = self.request(
            f"{BASE_URL}/", {"login": username, "password": password}
        )
        if "/prihlaseno" not in final_url:
            raise click.ClickException(
                "Login failed, check your username and password."
            )

    def list_folders(self):
        _, body, _ = self.request(GALLERY_URL)
        soup = BeautifulSoup(body, "html.parser")
        return {
            int(container["id"]): container.select_one(".left_side").get_text(
                strip=True
            )
            for container in soup.select(".fotogalerie_containers .container[id]")
        }

    def list_photos(self, folder_id):
        _, body, _ = self.request(
            GALLERY_URL,
            {
                "ajax": "ajax",
                "what": "fotogalerie",
                "action": "load_html_fotogalerie_slozka",
                "slozka": folder_id,
            },
        )
        fragment = json.loads(body)["result"]
        soup = BeautifulSoup(fragment, "html.parser")
        urls = [link["href"] for link in soup.select("a.lightbox[href]")]
        return list(dict.fromkeys(urls))  # deduplicate, keep order

    def download(self, url, target):
        _, body, headers = self.request(url)
        if not headers.get_content_type().startswith("image/"):
            raise RuntimeError("server didn't return an image (session expired?)")
        tmp = target.with_suffix(target.suffix + ".part")
        tmp.write_bytes(body)
        tmp.rename(target)


MAX_NAME_BYTES = 255  # APFS and most other filesystems


def safe_name(name, max_bytes=MAX_NAME_BYTES):
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", name).strip(" .")
    name = name.encode()[:max_bytes].decode(errors="ignore").rstrip(" .")
    return name or "untitled"


def get_folder_dir(output, folder_id, name):
    """Finds the folder's directory by the ID prefix, so that renames don't matter."""
    prefix = f"{folder_id:03d} "
    if output.is_dir():
        for path in sorted(output.iterdir()):
            if path.is_dir() and path.name.startswith(prefix):
                return path
    return output / (prefix + safe_name(name, MAX_NAME_BYTES - len(prefix)))


def op(*args):
    return subprocess.run(
        ["op", *args], check=True, capture_output=True, text=True
    ).stdout


def find_op_item():
    """Finds the first login item with the nasems.cz URL, account by account."""
    for account in json.loads(op("account", "list", "--format", "json")):
        account_id = account["account_uuid"]
        items = json.loads(
            op(
                "item",
                "list",
                "--categories",
                "Login",
                "--format",
                "json",
                "--account",
                account_id,
            )
        )
        for item in items:
            hosts = {
                urllib.parse.urlparse(url.get("href", "")).hostname
                for url in item.get("urls", [])
            }
            if hosts & {"nasems.cz", "www.nasems.cz"}:
                return item["id"], account_id
    raise LookupError("no login item with the nasems.cz URL found")


def op_cache_path():
    config_dir = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return config_dir / "nasems" / "op.json"


def read_op_cache():
    try:
        cache = json.loads(op_cache_path().read_text())
        return cache["item_id"], cache["account_id"]
    except OSError, ValueError, KeyError:
        return None


def write_op_cache(item_id, account_id):
    """Remembers only the IDs of the item and its account, never any secrets."""
    path = op_cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"item_id": item_id, "account_id": account_id}))


def fetch_op_credentials(item_id, account_id):
    fields = json.loads(
        op(
            "item",
            "get",
            item_id,
            "--fields",
            "username,password",
            "--reveal",
            "--format",
            "json",
            "--account",
            account_id,
        )
    )
    values = {field["id"]: field["value"] for field in fields}
    return values["username"], values["password"]


def credentials_from_op():
    if cached := read_op_cache():
        try:
            return fetch_op_credentials(*cached)
        except subprocess.CalledProcessError:
            pass  # item or account is gone, look it up again
    item_id, account_id = find_op_item()
    credentials = fetch_op_credentials(item_id, account_id)
    write_op_cache(item_id, account_id)
    return credentials


def get_credentials(use_op):
    if os.environ.get("NASEMS_LOGIN") and os.environ.get("NASEMS_PASSWORD"):
        return os.environ["NASEMS_LOGIN"], os.environ["NASEMS_PASSWORD"]
    if use_op:
        try:
            return credentials_from_op()
        except FileNotFoundError:
            click.echo("`op` CLI not found, asking for credentials.", err=True)
        except subprocess.CalledProcessError as e:
            click.echo(f"1Password failed: {e.stderr.strip()}", err=True)
        except LookupError as e:
            click.echo(f"1Password: {e}", err=True)
    username = click.prompt("Username")
    password = click.prompt("Password", hide_input=True)
    return username, password


def photo_id(url):
    return url.rstrip("/").rsplit("/", 1)[-1]


def plan_folder(folder_dir, urls):
    """Returns (url, target path) of photos from the folder which aren't on disk yet."""
    existing = {path.stem.split("_", 1)[-1] for path in folder_dir.glob("*.jpg")}
    return [
        (url, folder_dir / f"{index:03d}_{photo_id(url)}.jpg")
        for index, url in enumerate(urls, 1)
        if photo_id(url) not in existing
    ]


def plan_downloads(client, folders, output):
    downloads = []
    for folder_id, name in sorted(folders.items()):
        folder_dir = get_folder_dir(output, folder_id, name)
        folder_dir.mkdir(parents=True, exist_ok=True)
        urls = client.list_photos(folder_id)
        new = plan_folder(folder_dir, urls)
        click.echo(f"{folder_dir.name}: {len(urls)} photos, {len(new)} new")
        downloads.extend(new)
    return downloads


def download_all(client, downloads, jobs):
    """Downloads photos in parallel, returns the number of failures."""
    failed = 0
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        futures = {
            pool.submit(client.download, url, target): target
            for url, target in downloads
        }
        for done, future in enumerate(as_completed(futures), 1):
            try:
                future.result()
            except (OSError, RuntimeError) as e:
                failed += 1
                click.echo(f"\nError downloading {futures[future]}: {e}", err=True)
            click.echo(f"\rDownloading {done}/{len(downloads)}", nl=False)
    click.echo()
    return failed


@click.command(help=__doc__)
@click.argument("output", default="photos", type=click.Path(path_type=Path))
@click.option(
    "--op/--no-op", "use_op", default=True, help="Get credentials from 1Password."
)
@click.option(
    "--folder",
    "folder_ids",
    type=int,
    multiple=True,
    help="Download only the folder with given ID (can be repeated).",
)
@click.option(
    "-j",
    "--jobs",
    type=int,
    default=2,
    show_default=True,
    help="Parallel downloads (more overloads the server).",
)
@click.option("--list", "list_only", is_flag=True, help="Only list the folders.")
def main(output, use_op, folder_ids, jobs, list_only):
    client = Client()
    client.login(*get_credentials(use_op))

    folders = client.list_folders()
    if not folders:
        raise click.ClickException("No photo galleries found.")
    if folder_ids:
        folders = {i: n for i, n in folders.items() if i in folder_ids}

    if list_only:
        for folder_id, name in sorted(folders.items()):
            click.echo(f"{folder_id:>5}  {name}")
        return

    downloads = plan_downloads(client, folders, output)
    if not downloads:
        click.echo("Everything is already downloaded.")
        return

    failed = download_all(client, downloads, jobs)
    click.echo(
        f"Done: {len(downloads) - failed} downloaded to {output}/"
        + (f", {failed} failed (run again)" if failed else "")
    )
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
