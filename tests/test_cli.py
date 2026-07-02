"""true-research console entrypoint: thin routing, zero engine logic."""

from src import cli


def test_run_subcommand_routes_to_launcher(monkeypatch):
    seen = {}
    monkeypatch.setattr(cli, "_launcher_main", lambda argv: seen.update(a=argv) or 0)
    assert cli.main(["run", "my question", "--cheap", "--detach"]) == 0
    assert seen["a"] == ["my question", "--cheap", "--detach"]


def test_resume_subcommand_routes_to_driver(monkeypatch):
    seen = {}
    monkeypatch.setattr(cli, "_driver_main", lambda argv: seen.update(a=argv) or 0)
    assert cli.main(["resume", "20260701-abc", "--verify"]) == 0
    assert seen["a"] == ["--resume", "20260701-abc", "--verify"]


def test_bare_invocation_passes_through_to_driver(monkeypatch):
    seen = {}
    monkeypatch.setattr(cli, "_driver_main", lambda argv: seen.update(a=argv) or 0)
    assert cli.main(["a question", "--comprehensive"]) == 0
    assert seen["a"] == ["a question", "--comprehensive"]


def test_ui_subcommand_routes_to_server(monkeypatch):
    seen = {}
    monkeypatch.setattr(cli, "_ui_main", lambda argv: seen.update(a=argv) or 0)
    assert cli.main(["ui", "--port", "9999"]) == 0
    assert seen["a"] == ["--port", "9999"]
