from pathlib import Path

import pytest

from nasems import __main__ as nasems


@pytest.fixture(autouse=True)
def no_real_op(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Tests must never touch the real 1Password nor real credentials."""

    def op(*args: str) -> str:
        raise AssertionError(f"test called real 1Password: op {' '.join(args)}")

    monkeypatch.setattr(nasems, "op", op)
    monkeypatch.delenv("NASEMS_LOGIN", raising=False)
    monkeypatch.delenv("NASEMS_PASSWORD", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
