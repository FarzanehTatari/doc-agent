"""CLI smoke tests — no API key required."""

import importlib

from typer.testing import CliRunner

from doc_agent import __version__

runner = CliRunner()


def _fresh_app():
    """Re-import the CLI so env-var changes are reflected in `settings`."""
    import doc_agent.config as cfg

    importlib.reload(cfg)
    import doc_agent.cli as cli

    importlib.reload(cli)
    return cli.app


def test_version_command():
    result = runner.invoke(_fresh_app(), ["version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout


def test_ping_without_key_exits_nonzero(monkeypatch):
    # delenv alone isn't enough — pydantic-settings would fall back to the
    # repo's real .env file. Explicitly set the env var to empty so it
    # takes precedence over .env and the "no key" branch is exercised.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    result = runner.invoke(_fresh_app(), ["ping"])
    assert result.exit_code == 1
    assert "Setup required" in result.stdout or "ANTHROPIC_API_KEY" in result.stdout


def test_facts_list_empty(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    result = runner.invoke(_fresh_app(), ["facts", "list"])
    assert result.exit_code == 0


def test_facts_add_and_list(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    app = _fresh_app()
    r1 = runner.invoke(
        app,
        ["facts", "add", "Signals use camelCase.", "-c", "naming", "-p", "high"],
    )
    assert r1.exit_code == 0
    r2 = runner.invoke(app, ["facts", "list"])
    assert r2.exit_code == 0
    assert "Signals use camelCase" in r2.stdout


def test_memory_show_empty(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    result = runner.invoke(_fresh_app(), ["memory", "show"])
    assert result.exit_code == 0
    assert "Messages" in result.stdout


def test_memory_clear_when_empty(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    result = runner.invoke(_fresh_app(), ["memory", "clear"])
    assert result.exit_code == 0
