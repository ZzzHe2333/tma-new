"""Keep desktop preferences out of deterministic test runs."""
import pytest


@pytest.fixture(autouse=True)
def isolated_app_preferences(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
