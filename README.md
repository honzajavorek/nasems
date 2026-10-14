# nasems

Downloads photo galleries from [Naše MŠ](https://nasems.cz), an app Czech kindergartens use to communicate with parents. The app lets you download photos only one by one, this tool downloads all of them at once.

## Usage

Requires [uv](https://docs.astral.sh/uv/).

```
uv run nasems [OUTPUT]
```

Photos are saved to `OUTPUT` (default: `photos/`), one subdirectory per gallery folder, e.g. `photos/042 Trip to the Zoo/001_aBcD1234eFgH5678.jpg`.

Repeated runs are idempotent: photos already on disk are skipped, so you can run it regularly to fetch only the new ones.

### Credentials

Credentials are taken from (in this order):

1. environment variables `NASEMS_LOGIN` and `NASEMS_PASSWORD`,
2. 1Password via the [`op` CLI](https://developer.1password.com/docs/cli/): your accounts are searched one by one for a login item with the `nasems.cz` URL, and the first match is used (accounts after it aren't touched). The IDs of the item and its account (no secrets) are then remembered in `~/.config/nasems/op.json`, so next time only that account is unlocked,
3. interactive prompt.

### Options

- `--list` – only list gallery folders and their IDs
- `--folder ID` – download only the given folder (can be repeated)
- `--no-op` – don't use 1Password
- `-j, --jobs N` – parallel downloads (default: 2; the server is slow and starts refusing connections if you use too many)

## How it works

There's no public API, but [nasems.cz](https://nasems.cz) has a web version of the app. The tool logs in with a regular form POST, reads the list of gallery folders from `/prihlaseno/fotogalerie`, and loads each folder via the same AJAX call the web uses. Full-size photos are then downloaded using the session cookie.

## Development

```
uv sync
uv run pytest
```

Tests also run `ruff` lint and format checks. To fix formatting, run `uv run ruff format`.

Parsing is tested against real HTML saved in `tests/fixtures/`. If nasems.cz changes, re-download the fixtures with `uv run python -m tests.download_fixtures` and fix the tests.
