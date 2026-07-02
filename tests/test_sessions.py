"""Session-layer guarantees: per-session endpoint env resolution and the
synthesizer's citation refusal (invariant 3)."""

from pathlib import Path

import pytest

from src.errors import ConfigError
from src.ledger import Ledger
from src.runspace import Runspace
from src.sessions.base import SynthesisError, resolve_endpoint_env
from src.sessions.stub import run_synthesizer
from src.settings import Settings
from src.state import FindingMeta
from tests.conftest import BASE_CONFIG


def _settings(tmp_path: Path, secrets: dict[str, str]) -> Settings:
    import yaml

    raw = yaml.safe_load(yaml.safe_dump(BASE_CONFIG))
    raw["runs_dir"] = str(tmp_path / "runs")
    raw["roles"]["reader_subagent"]["endpoint"] = "local"
    raw["secrets"] = secrets
    return Settings.model_validate(raw)


def test_first_party_endpoint_injects_api_key(tmp_path):
    settings = _settings(tmp_path, {"ANTHROPIC_API_KEY": "sk-test-123"})
    env = resolve_endpoint_env(settings, "worker")
    assert env == {"ANTHROPIC_API_KEY": "sk-test-123"}


def test_custom_base_url_injects_base_url_and_bearer(tmp_path):
    settings = _settings(
        tmp_path, {"ANTHROPIC_API_KEY": "sk-test-123", "OLLAMA_AUTH": "ollama"}
    )
    env = resolve_endpoint_env(settings, "reader_subagent")
    assert env == {
        "ANTHROPIC_BASE_URL": "http://localhost:11434",
        "ANTHROPIC_AUTH_TOKEN": "ollama",
    }


def test_missing_secret_is_a_loud_config_error(tmp_path):
    settings = _settings(tmp_path, {})
    with pytest.raises(ConfigError, match="ANTHROPIC_API_KEY"):
        resolve_endpoint_env(settings, "worker")


def test_secrets_never_appear_in_settings_repr(tmp_path):
    settings = _settings(tmp_path, {"ANTHROPIC_API_KEY": "sk-super-secret"})
    assert "sk-super-secret" not in repr(settings)
    assert "sk-super-secret" not in str(settings)


def test_synthesizer_refuses_unknown_source_ids(tmp_path):
    settings = _settings(tmp_path, {})
    run = Runspace.create(tmp_path / "runs", "q", "general")
    try:
        run.write_finding(
            "bad",
            FindingMeta(question_id="q-001", source_ids=["src-ghost"], confidence=0.9),
            "claim with a ghost citation",
        )
        with pytest.raises(SynthesisError, match="src-ghost"):
            run_synthesizer(run, settings, 1, Ledger(run))
    finally:
        run.release_lock()
