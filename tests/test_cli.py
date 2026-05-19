"""Tests for the CLI surface — no API key required for version; ping is exercised in a smoke check."""

from typer.testing import CliRunner

from doc_agent import __version__
from doc_agent.cli import app

runner = CliRunner()


def test_version_command():
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout


def test_ping_without_key_exits_nonzero(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    # Force a fresh Settings load by reloading the module under test:
    import importlib

    import doc_agent.config as cfg

    importlib.reload(cfg)
    import doc_agent.cli as cli

    importlib.reload(cli)
    result = runner.invoke(cli.app, ["ping"])
    assert result.exit_code == 1
    assert "Setup required" in result.stdout or "ANTHROPIC_API_KEY" in result.stdout
